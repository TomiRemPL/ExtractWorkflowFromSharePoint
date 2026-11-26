"""Deterministic offline simulation.  This module performs no I/O or writes."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import operator
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .models import Graph, GraphError, _guid


class SimulationError(ValueError):
    """The snapshot or graph cannot safely be simulated."""


@dataclass(frozen=True)
class Change:
    list_id: str
    item_id: int
    field_id: str
    internal_name: str
    entity_property_name: str
    old_value: object
    new_value: object
    source_ids: tuple[int, ...]
    steps: tuple[str, ...]


@dataclass(frozen=True)
class BranchDecision:
    source_id: int
    node_id: str
    matched: bool


@dataclass(frozen=True)
class TraceValue:
    label: str
    alias: str = ""
    list_id: str = ""
    field_id: str = ""
    internal_name: str = ""
    value: Any = None


@dataclass(frozen=True)
class StepTrace:
    source_id: int
    step_no: int
    node_id: str
    node_type: str
    values: tuple[TraceValue, ...]
    outcome: dict[str, Any]
    next_port: str


@dataclass(frozen=True)
class SimulationResult:
    changes: tuple[Change, ...]
    decisions: tuple[BranchDecision, ...]
    graph_digest: str
    snapshot_digest: str
    snapshot_complete: bool = True
    trace: tuple[StepTrace, ...] = ()


def _digest(value):
    try:
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    except (ValueError, TypeError, RecursionError) as exc:
        raise SimulationError("Snapshot must contain finite JSON data") from exc


def _id(value):
    return type(value) is int and value > 0


def _date(value):
    if not isinstance(value, str):
        raise SimulationError("Date must be an ISO timestamp with timezone")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise SimulationError("Date must be an ISO timestamp with timezone") from exc


def _same_value(left, right, field_type):
    if left is None or right is None:
        return left is right
    if field_type == "DateTime":
        return _date(left) == _date(right)
    if field_type in ("Number", "Currency"):
        return left == right
    return type(left) is type(right) and left == right


def _typed(value: Any, field_type: str) -> Any:
    if value is None:
        return None
    if field_type in ("Text", "Note", "Choice"):
        valid = type(value) is str
    elif field_type in ("Number", "Currency"):
        valid = type(value) is int or (type(value) is float and math.isfinite(value))
    elif field_type == "Boolean":
        valid = type(value) is bool
    elif field_type == "Lookup":
        valid = _id(value)
    elif field_type == "LookupMulti":
        valid = isinstance(value, list) and all(_id(i) for i in value) and len(set(value)) == len(value)
    elif field_type == "DateTime":
        _date(value)
        return value
    else:
        raise SimulationError(f"Unsupported field type: {field_type}")
    if not valid:
        raise SimulationError(f"Invalid {field_type} value")
    return value


class _Simulator:
    def __init__(self, graph, snapshot, allow_incomplete=False, record_trace=False):
        self.graph = graph
        self.record_trace = record_trace
        self.trace: list[StepTrace] = []
        self._step_values: list[TraceValue] = []
        self._last_outcome: dict[str, Any] = {}
        self.snapshot = copy.deepcopy(snapshot)
        if not isinstance(self.snapshot, dict) or self.snapshot.get("site") != graph["site"] or self.snapshot.get("schema_fingerprint") != graph["schema_fingerprint"]:
            raise SimulationError("Site or schema fingerprint mismatch")
        lists = self.snapshot.get("lists")
        if not isinstance(lists, dict):
            raise SimulationError("Snapshot lists are missing")
        self.lists = {}
        for list_id, data in lists.items():
            try:
                _guid(list_id)
            except GraphError as exc:
                raise SimulationError("Invalid list GUID") from exc
            if (not isinstance(data, dict) or type(data.get("complete")) is not bool
                    or (data["complete"] is not True and not allow_incomplete)
                    or not isinstance(data.get("fields"), dict) or not isinstance(data.get("items"), list)):
                raise SimulationError("Every supplied list must have complete schema and data")
            rows = {}
            for row in data["items"]:
                if not isinstance(row, dict) or not _id(row.get("ID")) or row["ID"] in rows:
                    raise SimulationError("Missing or duplicate item ID")
                rows[row["ID"]] = row
            names = []
            for field_id, field in data["fields"].items():
                try:
                    _guid(field_id)
                except GraphError as exc:
                    raise SimulationError("Invalid field GUID") from exc
                if not isinstance(field, dict) or not all(isinstance(field.get(k), str) and field[k] for k in ("internal_name", "entity_property_name", "type")):
                    raise SimulationError("Invalid field metadata")
                names.append(field["internal_name"])
            if len(names) != len(set(names)):
                raise SimulationError("Duplicate internal field name")
            self.lists[list_id] = (data["fields"], rows)
        if graph["source_list_id"] not in self.lists:
            raise SimulationError("Source list missing")
        self.nodes = {node["id"]: node for node in graph["nodes"]}
        self.edges = {(edge["from"], edge["port"]): edge["to"] for edge in graph["edges"]}
        self.proposals = {}
        self.decisions = []
        self.aliases: dict[str, tuple[str, int] | list[tuple[str, int]] | None] = {}
        self.preflight()

    def _static_field(self, aliases, alias, field_id):
        if alias not in aliases or aliases[alias][1] != "one":
            raise SimulationError("Field requires a definitely bound single-item alias")
        meta = self.field(aliases[alias][0], field_id)
        if meta.get("field_ref") or meta.get("dependent"):
            raise SimulationError("Dependent FieldRef must be resolved through its main lookup")
        if meta["type"] not in ("Text", "Note", "Choice", "Number", "Currency", "Boolean", "Lookup", "LookupMulti", "DateTime"):
            raise SimulationError("Unsupported field type")
        return meta

    def _check_writable(self, field):
        if (field.get("writable") is not True or field.get("constraints_verified") is not True
                or type(field.get("required")) is not bool or field.get("readonly")
                or field.get("system") or field.get("dependent") or field.get("field_ref")):
            raise SimulationError("Field is not explicitly writable with verified constraints")
        field_type = field["type"]
        if field_type not in ("Text", "Note", "Number", "Currency", "Boolean", "Choice", "DateTime", "Lookup"):
            raise SimulationError("Unsupported assignment type")
        if field_type == "Note" and field.get("plain") is not True:
            raise SimulationError("Only explicitly plain notes are supported")
        if field_type == "Choice" and (not isinstance(field.get("choices"), list) or not all(type(c) is str for c in field["choices"])):
            raise SimulationError("Choice metadata missing or invalid")
        if field_type == "Lookup" and (not isinstance(field.get("lookup_list_id"), str) or field["lookup_list_id"] not in self.lists):
            raise SimulationError("Lookup target metadata or data missing")
        if "max_length" in field and (type(field["max_length"]) is not int or field["max_length"] < 0):
            raise SimulationError("Invalid maximum length")
        if field_type in ("Number", "Currency"):
            for key in ("minimum", "maximum"):
                if key in field:
                    bound = field[key]
                    if not (type(bound) is int or (type(bound) is float and math.isfinite(bound))):
                        raise SimulationError("Invalid number constraint")
            if "minimum" in field and "maximum" in field and field["minimum"] > field["maximum"]:
                raise SimulationError("Invalid number range")

    def _static_expr(self, expr, aliases):
        if expr["kind"] == "field":
            self._static_field(aliases, expr["alias"], expr["field_id"])
        elif expr["kind"] == "count":
            if expr["alias"] not in aliases or aliases[expr["alias"]][1] != "many":
                raise SimulationError("COUNT requires a definitely bound collection")

    def _static_condition(self, condition, aliases):
        op = condition["op"]
        if op in ("and", "or"):
            for child in condition["conditions"]:
                self._static_condition(child, aliases)
        elif op == "not":
            self._static_condition(condition["condition"], aliases)
        elif op in ("any", "all"):
            alias = condition["alias"]
            if alias not in aliases or aliases[alias][1] != "many":
                raise SimulationError("ANY/ALL requires a definitely bound collection")
            nested = dict(aliases)
            nested["item"] = (aliases[alias][0], "one")
            self._static_condition(condition["condition"], nested)
        elif op == "exists":
            if condition["alias"] not in aliases or aliases[condition["alias"]][1] != "one":
                raise SimulationError("EXISTS requires a definitely bound single-item alias")
        elif op in ("empty", "not_empty"):
            self._static_expr(condition["value"], aliases)
        else:
            self._static_expr(condition["left"], aliases)
            self._static_expr(condition["right"], aliases)

    def preflight(self):
        """Check every path even if the scope has no rows or a branch is untaken."""
        incoming = {node: [] for node in self.nodes}
        outgoing = {node: [] for node in self.nodes}
        for (src, _), dest in self.edges.items():
            incoming[dest].append(src)
            outgoing[src].append(dest)
        pending = {node: len(sources) for node, sources in incoming.items()}
        queue = deque(node for node, count in pending.items() if not count)
        states = {}
        while queue:
            node_id = queue.popleft()
            node = self.nodes[node_id]
            if not incoming[node_id]:
                aliases = {"source": (self.graph["source_list_id"], "one")}
            else:
                parents = [states[parent] for parent in incoming[node_id]]
                aliases = {key: value for key, value in parents[0].items() if all(other.get(key) == value for other in parents[1:])}
            if node["type"] == "lookup":
                parent = node["from"]
                if parent not in aliases or aliases[parent][1] != "one" or node["as"] in aliases:
                    raise SimulationError("Lookup alias is unbound or already in use")
                parent_list = aliases[parent][0]
                if node.get("direction", "forward") == "forward":
                    field = self._static_field(aliases, parent, node["field_id"])
                    target = field.get("lookup_list_id")
                    if field["type"] not in ("Lookup", "LookupMulti") or (field["type"] == "LookupMulti") != node.get("many", False):
                        raise SimulationError("Lookup cardinality mismatch")
                    if "target_list_id" in node and node["target_list_id"] != target:
                        raise SimulationError("Lookup target mismatch")
                else:
                    target = node["target_list_id"]
                    field = self._static_field({"target": (target, "one")}, "target", node["field_id"])
                    if field["type"] not in ("Lookup", "LookupMulti") or field.get("lookup_list_id") != parent_list:
                        raise SimulationError("Invalid reverse relation")
                if not isinstance(target, str) or target not in self.lists:
                    raise SimulationError("Lookup target metadata or data missing")
                aliases[node["as"]] = (target, "many" if node.get("many", False) else "one")
            elif node["type"] == "condition":
                self._static_condition(node["condition"], aliases)
            elif node["type"] == "assign":
                field = self._static_field(aliases, node["alias"], node["field_id"])
                self._check_writable(field)
                self._static_expr(node["value"], aliases)
            states[node_id] = aliases
            for dest in outgoing[node_id]:
                pending[dest] -= 1
                if not pending[dest]:
                    queue.append(dest)

    def field(self, list_id, field_id):
        try:
            return self.lists[list_id][0][field_id]
        except KeyError as exc:
            raise SimulationError("Field missing in list context") from exc

    def row(self, list_id, item_id):
        try:
            return self.lists[list_id][1][item_id]
        except KeyError as exc:
            raise SimulationError("Related list or item missing from snapshot") from exc

    def binding(self, alias):
        if alias not in self.aliases:
            raise SimulationError(f"Unbound alias: {alias}")
        return self.aliases[alias]

    def read(self, binding, field_id, *, snapshot=False):
        if binding is None or isinstance(binding, list):
            raise SimulationError("Field requires a single existing item")
        list_id, item_id = binding
        field = self.field(list_id, field_id)
        if field.get("field_ref") or field.get("dependent"):
            raise SimulationError("Dependent FieldRef must be resolved through its main lookup")
        row = self.row(list_id, item_id) if snapshot else self.working.setdefault(binding, dict(self.row(list_id, item_id)))
        name = field["internal_name"]
        if name not in row:
            raise SimulationError("Required field is absent from snapshot")
        return _typed(row[name], field["type"]), field

    def expr(self, expression):
        kind = expression["kind"]
        if kind == "literal":
            value = expression["value"]
            if self.record_trace:
                self._step_values.append(TraceValue(label="literal", value=copy.deepcopy(value)))
            return value, None
        if kind == "count":
            binding = self.binding(expression["alias"])
            if not isinstance(binding, list):
                raise SimulationError("COUNT requires a collection")
            count = len(binding)
            if self.record_trace:
                self._step_values.append(TraceValue(label="count", alias=expression["alias"], value=count))
            return count, None
        binding = self.binding(expression["alias"])
        value, field = self.read(binding, expression["field_id"])
        if self.record_trace and isinstance(binding, tuple):
            self._step_values.append(TraceValue(
                label="field",
                alias=expression["alias"],
                list_id=binding[0],
                field_id=expression["field_id"],
                internal_name=field["internal_name"],
                value=copy.deepcopy(value),
            ))
        return value, field

    def condition(self, condition):
        op = condition["op"]
        if op == "and":
            return all(self.condition(c) for c in condition["conditions"])
        if op == "or":
            return any(self.condition(c) for c in condition["conditions"])
        if op == "not":
            return not self.condition(condition["condition"])
        if op == "exists":
            matched = self.binding(condition["alias"]) is not None
            if self.record_trace:
                self._step_values.append(TraceValue(label="exists", alias=condition["alias"], value=matched))
            return matched
        if op in ("any", "all"):
            collection = self.binding(condition["alias"])
            if not isinstance(collection, list):
                raise SimulationError("ANY/ALL requires a collection")
            if self.record_trace:
                self._step_values.append(TraceValue(label="collection", alias=condition["alias"], value=len(collection)))
            had_previous = "item" in self.aliases
            previous = self.aliases.get("item")
            try:
                def evaluate(binding):
                    self.aliases["item"] = binding
                    return self.condition(condition["condition"])
                return any(map(evaluate, collection)) if op == "any" else all(map(evaluate, collection))
            finally:
                if had_previous:
                    self.aliases["item"] = previous
                else:
                    self.aliases.pop("item", None)
        if op in ("empty", "not_empty"):
            value, _ = self.expr(condition["value"])
            empty = value is None or value == "" or value == []
            return empty if op == "empty" else not empty
        left, left_field = self.expr(condition["left"])
        right, right_field = self.expr(condition["right"])
        types = {f["type"] for f in (left_field, right_field) if f is not None}
        if len(types) > 1 and not types <= {"Number", "Currency"}:
            raise SimulationError("Incompatible field types")
        if left_field is not None and right_field is None and right is not None:
            _typed(right, left_field["type"])
        if right_field is not None and left_field is None and left is not None:
            _typed(left, right_field["type"])
        if left is None or right is None:
            if op not in ("eq", "ne"):
                raise SimulationError("Cannot order null values")
            return (left is right) if op == "eq" else (left is not right)
        if "DateTime" in types:
            left, right = _date(left), _date(right)
        else:
            numeric = type(left) in (int, float) and type(right) in (int, float)
            if not numeric and type(left) is not type(right):
                raise SimulationError("Incompatible comparison types")
            if not isinstance(left, (str, bool, int, float)) or not isinstance(right, (str, bool, int, float)):
                raise SimulationError("Unsupported comparison")
        if op not in ("eq", "ne") and (isinstance(left, bool) or isinstance(right, bool)):
            raise SimulationError("Cannot order booleans")
        return {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt, "le": operator.le, "gt": operator.gt, "ge": operator.ge}[op](left, right)

    def lookup(self, node):
        parent = self.binding(node["from"])
        if parent is None or isinstance(parent, list):
            raise SimulationError("Lookup requires a single existing item")
        source_list, source_id = parent
        direction = node.get("direction", "forward")
        many = node.get("many", False)
        if direction == "forward":
            value, meta = self.read(parent, node["field_id"], snapshot=True)
            target = meta.get("lookup_list_id")
            if meta["type"] not in ("Lookup", "LookupMulti") or not isinstance(target, str) or target not in self.lists:
                raise SimulationError("Lookup target metadata or data missing")
            if "target_list_id" in node and node["target_list_id"] != target:
                raise SimulationError("Lookup target mismatch")
            if (meta["type"] == "LookupMulti") != many:
                raise SimulationError("Lookup cardinality mismatch")
            ids = ([] if value is None else value) if many else ([] if value is None else [value])
            for item_id in ids:
                self.row(target, item_id)
            self.aliases[node["as"]] = [(target, i) for i in sorted(ids)] if many else ((target, ids[0]) if ids else None)
            if self.record_trace:
                self._step_values.append(TraceValue(
                    label="field",
                    alias=node["from"],
                    list_id=source_list,
                    field_id=node["field_id"],
                    internal_name=meta["internal_name"],
                    value=copy.deepcopy(value),
                ))
                self._last_outcome = {
                    "alias": node["as"],
                    "target_list_id": target,
                    "many": many,
                    "bound_ids": sorted(ids) if many else list(ids),
                }
        else:
            target = node["target_list_id"]
            meta = self.field(target, node["field_id"])
            if meta.get("lookup_list_id") != source_list or meta["type"] not in ("Lookup", "LookupMulti"):
                raise SimulationError("Invalid reverse relation")
            result = []
            for item_id in sorted(self.lists[target][1]):
                value, _ = self.read((target, item_id), node["field_id"], snapshot=True)
                if value == source_id or (isinstance(value, list) and source_id in value):
                    result.append((target, item_id))
            self.aliases[node["as"]] = result
            if self.record_trace:
                self._step_values.append(TraceValue(
                    label="source",
                    alias=node["from"],
                    list_id=source_list,
                    value=source_id,
                ))
                self._last_outcome = {
                    "alias": node["as"],
                    "target_list_id": target,
                    "many": True,
                    "bound_ids": [item_id for _, item_id in result],
                }

    def assign(self, node):
        binding = self.binding(node["alias"])
        if binding is None or isinstance(binding, list):
            raise SimulationError("Assignment requires a single existing item")
        old, field = self.read(binding, node["field_id"])
        self._check_writable(field)
        field_type = field["type"]
        if self.record_trace:
            self._step_values.append(TraceValue(
                label="przed",
                alias=node["alias"],
                list_id=binding[0],
                field_id=node["field_id"],
                internal_name=field["internal_name"],
                value=copy.deepcopy(old),
            ))
        value, from_field = self.expr(node["value"])
        if from_field is not None and from_field["type"] != field_type and {from_field["type"], field_type} != {"Number", "Currency"}:
            raise SimulationError("Incompatible assignment types")
        _typed(value, field_type)
        if field.get("required") is True and (value is None or value == ""):
            raise SimulationError("Required field cannot be cleared")
        if field_type == "Choice" and (not isinstance(field.get("choices"), list) or (value is not None and value not in field["choices"])):
            raise SimulationError("Choice metadata missing or value invalid")
        if isinstance(value, str) and "max_length" in field and (type(field["max_length"]) is not int or len(value) > field["max_length"]):
            raise SimulationError("Text length exceeded")
        if field_type in ("Number", "Currency") and value is not None:
            for key, failed in (("minimum", lambda bound: value < bound), ("maximum", lambda bound: value > bound)):
                if key in field:
                    bound = field[key]
                    if not (type(bound) is int or (type(bound) is float and math.isfinite(bound))) or failed(bound):
                        raise SimulationError("Invalid number constraint or value outside range")
        if field_type == "Lookup" and value is not None:
            target = field.get("lookup_list_id")
            if from_field is not None and from_field.get("lookup_list_id") != target:
                raise SimulationError("Lookup assignment target mismatch")
            self.row(target, value)
        self.working[binding][field["internal_name"]] = value
        if self.record_trace:
            self._last_outcome = {
                "alias": node["alias"],
                "list_id": binding[0],
                "field_id": node["field_id"],
                "internal_name": field["internal_name"],
                "old": copy.deepcopy(old),
                "new": copy.deepcopy(value),
                "changed": not _same_value(old, value, field_type),
            }
        key = (*binding, node["field_id"])
        proposal = self.local.get(key)
        if proposal is None:
            self.local[key] = {"old": old, "new": value, "field": field, "steps": [node["id"]]}
        else:
            proposal["new"] = value
            proposal["steps"].append(node["id"])

    def run(self):
        source_list = self.graph["source_list_id"]
        source_ids = sorted(self.lists[source_list][1])
        if self.graph["scope"]["type"] == "ids":
            source_ids = sorted(self.graph["scope"]["ids"])
            if any(i not in self.lists[source_list][1] for i in source_ids):
                raise SimulationError("Selected item missing")
        elif self.graph["scope"]["type"] == "view":
            # Views are resolved only by a fresh online read; never approximated offline.
            resolved = self.snapshot.get("scope_resolution")
            if (not isinstance(resolved, dict) or resolved.get("view_id") != self.graph["scope"]["view_id"]
                    or not isinstance(resolved.get("ids"), list)
                    or any(not _id(i) for i in resolved["ids"])
                    or len(set(resolved["ids"])) != len(resolved["ids"])):
                raise SimulationError("View scope requires a verified online view resolution")
            source_ids = sorted(resolved["ids"])
            if any(i not in self.lists[source_list][1] for i in source_ids):
                raise SimulationError("View item missing from the source list")
        start = next(n["id"] for n in self.nodes.values() if n["type"] == "start")
        for source_id in source_ids:
            self.aliases = {"source": (source_list, source_id)}
            self.working = {}
            self.local = {}
            node_id = start
            step_no = 0
            while True:
                step_no += 1
                self._step_values = []
                self._last_outcome = {}
                node = self.nodes[node_id]
                kind = node["type"]
                if kind in ("end", "skip"):
                    if kind == "skip":
                        dropped = len(self.local)
                        self.local.clear()
                        if self.record_trace:
                            self.trace.append(StepTrace(source_id, step_no, node_id, kind, (), {"dropped": dropped}, ""))
                    elif self.record_trace:
                        self.trace.append(StepTrace(source_id, step_no, node_id, kind, (), {"proposals": len(self.local)}, ""))
                    break
                port = "next"
                if kind == "start" and self.record_trace:
                    self._step_values.append(TraceValue(label="source", alias="source", list_id=source_list, value=source_id))
                    self._last_outcome = {"list_id": source_list, "item_id": source_id}
                elif kind == "lookup":
                    self.lookup(node)
                elif kind == "condition":
                    matched = self.condition(node["condition"])
                    self.decisions.append(BranchDecision(source_id, node_id, matched))
                    port = "true" if matched else "false"
                    if self.record_trace:
                        self._last_outcome = {"matched": matched}
                elif kind == "assign":
                    self.assign(node)
                if self.record_trace:
                    self.trace.append(StepTrace(
                        source_id,
                        step_no,
                        node_id,
                        kind,
                        tuple(self._step_values),
                        self._last_outcome,
                        port,
                    ))
                node_id = self.edges[(node_id, port)]
            for key, proposal in self.local.items():
                if key in self.proposals:
                    previous = self.proposals[key]
                    if not _same_value(previous["new"], proposal["new"], proposal["field"]["type"]):
                        raise SimulationError("Conflicting proposals for the same field")
                    previous["sources"].append(source_id)
                    previous["steps"].extend(proposal["steps"])
                else:
                    proposal["sources"] = [source_id]
                    self.proposals[key] = proposal
        changes = []
        for (list_id, item_id, field_id), proposal in sorted(self.proposals.items()):
            old, new, field = proposal["old"], proposal["new"], proposal["field"]
            if _same_value(old, new, field["type"]):
                continue
            changes.append(Change(list_id, item_id, field_id, field["internal_name"], field["entity_property_name"], old, new, tuple(proposal["sources"]), tuple(proposal["steps"])))
        if len({(c.list_id, c.item_id) for c in changes}) > self.graph["max_updates"]:
            raise SimulationError("Update limit exceeded")
        return tuple(changes)


def simulate(
    graph: Graph,
    snapshot: dict,
    *,
    allow_incomplete: bool = False,
    record_trace: bool = False,
) -> SimulationResult:
    """Simulate a validated graph over a caller-supplied JSON snapshot.

    No network, file access or mutation of the supplied snapshot occurs. On any
    uncertainty or conflict raises SimulationError rather than returning a plan.
    Incomplete snapshots are rejected unless explicitly allowed; such a result is
    advisory only and must never be treated as a complete preview.
    Compare both digests before displaying/reusing an old preview.
    """
    if not isinstance(graph, Graph):
        raise SimulationError("A Graph instance is required")
    try:
        graph = Graph.from_json(graph.to_json())
    except GraphError as exc:
        raise SimulationError("Invalid graph") from exc
    graph_digest = hashlib.sha256(graph.to_json().encode("utf-8")).hexdigest()
    frozen_snapshot = copy.deepcopy(snapshot)
    snapshot_digest = _digest(frozen_snapshot)
    if type(allow_incomplete) is not bool:
        raise SimulationError("allow_incomplete must be a boolean")
    if type(record_trace) is not bool:
        raise SimulationError("record_trace must be a boolean")
    engine = _Simulator(graph.to_dict(), frozen_snapshot, allow_incomplete, record_trace=record_trace)
    changes = engine.run()
    snapshot_complete = all(data.get("complete") is True
                            for data in frozen_snapshot.get("lists", {}).values())
    return SimulationResult(changes, tuple(engine.decisions), graph_digest, snapshot_digest, snapshot_complete, tuple(engine.trace))


def preview_is_current(result: SimulationResult, graph: Graph, snapshot: dict) -> bool:
    """Return whether the exact graph and snapshot match an existing preview."""
    if not isinstance(result, SimulationResult) or not isinstance(graph, Graph):
        return False
    try:
        canonical = Graph.from_json(graph.to_json()).to_json()
        return result.graph_digest == hashlib.sha256(canonical.encode("utf-8")).hexdigest() and result.snapshot_digest == _digest(snapshot)
    except (GraphError, SimulationError):
        return False
