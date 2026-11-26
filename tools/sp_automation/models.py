"""Versioned, offline-only graph contract.  No executable expressions are accepted."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID


class GraphError(ValueError):
    """The serialized graph is invalid or uses an unsupported construct."""


def _object(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise GraphError("Invalid object keys")


def _string(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise GraphError("Expected a nonempty string")


def _guid(value):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise GraphError("Expected a canonical lowercase GUID") from exc


def _expr(value):
    if not isinstance(value, dict):
        raise GraphError("Invalid expression")
    kind = value.get("kind")
    if kind == "field":
        _object(value, ("kind", "alias", "field_id"))
        _string(value["alias"])
        _guid(value["field_id"])
    elif kind == "literal":
        _object(value, ("kind", "value"))
        item = value["value"]
        if item is not None and type(item) not in (str, bool, int, float):
            raise GraphError("Literal must be a scalar")
        if isinstance(item, float) and not math.isfinite(item):
            raise GraphError("Non-finite number")
    elif kind == "count":
        _object(value, ("kind", "alias"))
        _string(value["alias"])
    else:
        raise GraphError("Unsupported expression")


def _condition(value, depth=0):
    if depth > 32 or not isinstance(value, dict):
        raise GraphError("Invalid condition")
    op = value.get("op")
    if op in ("and", "or"):
        _object(value, ("op", "conditions"))
        if not isinstance(value["conditions"], list) or not value["conditions"]:
            raise GraphError("Empty logical condition")
        for child in value["conditions"]:
            _condition(child, depth + 1)
    elif op == "not":
        _object(value, ("op", "condition"))
        _condition(value["condition"], depth + 1)
    elif op in ("empty", "not_empty"):
        _object(value, ("op", "value"))
        _expr(value["value"])
    elif op == "exists":
        _object(value, ("op", "alias"))
        _string(value["alias"])
    elif op in ("eq", "ne", "lt", "le", "gt", "ge"):
        _object(value, ("op", "left", "right"))
        _expr(value["left"])
        _expr(value["right"])
    elif op in ("any", "all"):
        _object(value, ("op", "alias", "condition"))
        _string(value["alias"])
        _condition(value["condition"], depth + 1)
    else:
        raise GraphError("Unsupported condition")


def _validate(data):
    _object(data, ("schema_version", "id", "name", "site", "source_list_id", "schema_fingerprint", "max_updates", "text_policy", "scope", "nodes", "edges"), ("layout",))
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise GraphError("Unsupported schema version")
    for key in ("id", "name", "site", "schema_fingerprint"):
        _string(data[key])
    url = urlsplit(data["site"])
    if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise GraphError("Site must be an absolute URL without credentials, query or fragment")
    _guid(data["source_list_id"])
    if type(data["max_updates"]) is not int or data["max_updates"] < 0:
        raise GraphError("Invalid update limit")
    if data["text_policy"] != "exact":
        raise GraphError("Only exact, case-sensitive text comparison is supported")
    scope = data["scope"]
    if not isinstance(scope, dict):
        raise GraphError("Invalid scope")
    if scope.get("type") == "all":
        _object(scope, ("type",))
    elif scope.get("type") == "ids":
        _object(scope, ("type", "ids"))
        ids = scope["ids"]
        if not isinstance(ids, list) or any(type(i) is not int or i <= 0 for i in ids) or len(set(ids)) != len(ids):
            raise GraphError("Invalid selected IDs")
    elif scope.get("type") == "view":
        _object(scope, ("type", "view_id"))
        _guid(scope["view_id"])
    else:
        raise GraphError("Unsupported scope")
    nodes = data["nodes"]
    edges = data["edges"]
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 256 or not isinstance(edges, list) or len(edges) > 2 * len(nodes):
        raise GraphError("Invalid graph size")
    by_id = {}
    for node in nodes:
        if not isinstance(node, dict):
            raise GraphError("Invalid node")
        kind = node.get("type")
        if kind in ("start", "merge", "skip", "end"):
            _object(node, ("id", "type"))
        elif kind == "lookup":
            _object(node, ("id", "type", "from", "field_id", "as"), ("direction", "many", "target_list_id"))
            _string(node["from"])
            _string(node["as"])
            _guid(node["field_id"])
            if node["as"] in ("source", "item"):
                raise GraphError("Reserved alias")
            if node.get("direction", "forward") not in ("forward", "reverse") or type(node.get("many", False)) is not bool:
                raise GraphError("Invalid relation mode")
            if "target_list_id" in node:
                _guid(node["target_list_id"])
            if node.get("direction") == "reverse" and (not node.get("many") or "target_list_id" not in node):
                raise GraphError("Reverse lookup requires a target and collection")
        elif kind == "condition":
            _object(node, ("id", "type", "condition", "merge"))
            _string(node["merge"])
            _condition(node["condition"])
        elif kind == "assign":
            _object(node, ("id", "type", "alias", "field_id", "value"))
            _string(node["alias"])
            _guid(node["field_id"])
            _expr(node["value"])
        else:
            raise GraphError("Unsupported node type")
        _string(node["id"])
        if node["id"] in by_id:
            raise GraphError("Duplicate node ID")
        by_id[node["id"]] = node
    starts = [n["id"] for n in nodes if n["type"] == "start"]
    if len(starts) != 1:
        raise GraphError("Exactly one start is required")
    outgoing = {node_id: {} for node_id in by_id}
    for edge in edges:
        _object(edge, ("from", "port", "to"))
        src, port, dest = edge["from"], edge["port"], edge["to"]
        if not all(isinstance(x, str) for x in (src, port, dest)) or src not in by_id or dest not in by_id or port in outgoing[src]:
            raise GraphError("Invalid edge")
        outgoing[src][port] = dest
    for node_id, node in by_id.items():
        expected = {"true", "false"} if node["type"] == "condition" else set() if node["type"] in ("end", "skip") else {"next"}
        if set(outgoing[node_id]) != expected:
            raise GraphError("Missing or invalid port")
    seen, active = set(), set()
    def visit(node_id):
        if node_id in active:
            raise GraphError("Graph cycles are not supported")
        if node_id in seen:
            return
        active.add(node_id)
        for dest in outgoing[node_id].values():
            visit(dest)
        active.remove(node_id)
        seen.add(node_id)
    visit(starts[0])
    if len(seen) != len(nodes):
        raise GraphError("Unreachable node")
    incoming = {node_id: set() for node_id in by_id}
    for src, destinations in outgoing.items():
        for dest in destinations.values():
            incoming[dest].add(src)
    for node_id, node in by_id.items():
        if node["type"] == "condition":
            merge = node["merge"]
            if merge not in by_id or by_id[merge]["type"] != "merge":
                raise GraphError("Condition requires an explicit merge")
            cache = {}
            def branch_nodes(current):
                if current == merge:
                    return set()
                if current in cache:
                    return cache[current]
                if not outgoing[current]:
                    raise GraphError("Branch does not reach its merge")
                result = {current}
                for dest in outgoing[current].values():
                    result.update(branch_nodes(dest))
                cache[current] = result
                return result
            left = branch_nodes(outgoing[node_id]["true"])
            right = branch_nodes(outgoing[node_id]["false"])
            if left & right:
                raise GraphError("Branches meet before the declared merge")
            for branch in (left, right):
                if any(incoming[n] - branch - {node_id} for n in branch):
                    raise GraphError("Branch has an external entry")
    layout = data.get("layout", {})
    if not isinstance(layout, dict) or set(layout) - set(by_id):
        raise GraphError("Invalid layout")
    for position in layout.values():
        _object(position, ("x", "y"))
        if any(not (type(position[k]) is int or (type(position[k]) is float and math.isfinite(position[k]))) for k in ("x", "y")):
            raise GraphError("Invalid coordinates")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise GraphError("Duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True)
class Graph:
    """Immutable canonical graph; use from_json/from_dict and to_json for persistence."""
    _json: str

    @classmethod
    def from_json(cls, text: str) -> Graph:
        try:
            data = json.loads(text, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(GraphError("Non-finite number")))
            _validate(data)
            canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            canonical.encode("utf-8")
            return cls(canonical)
        except (ValueError, TypeError, RecursionError) as exc:
            if isinstance(exc, GraphError):
                raise
            raise GraphError("Invalid graph JSON") from exc

    @classmethod
    def from_dict(cls, data: dict) -> Graph:
        try:
            return cls.from_json(json.dumps(data, ensure_ascii=False, allow_nan=False))
        except (TypeError, ValueError, RecursionError) as exc:
            if isinstance(exc, GraphError):
                raise
            raise GraphError("Invalid graph data") from exc

    def to_json(self) -> str:
        return self._json

    def to_dict(self) -> dict:
        return json.loads(self._json)
