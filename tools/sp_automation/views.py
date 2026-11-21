"""Fail-closed local evaluation of a small, verified subset of SharePoint view CAML.

Only membership filters (``<Where>``) are evaluated; ``OrderBy``/``GroupBy`` do not
change membership and are ignored. Anything whose SharePoint semantics are not
reproducible locally (dates, ``<Today/>``, ``<UserID/>``, ``Contains``, display-text
Lookup comparisons, ambiguous NULL handling or case-dependent text results) is
rejected instead of being approximated.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException


class ViewScopeError(ValueError):
    """The view cannot be evaluated with verified, reproducible semantics."""


_COMPARISONS = {"Eq", "Neq", "Lt", "Leq", "Gt", "Geq"}
_NULL_TESTS = {"IsNull", "IsNotNull"}
_TEXT_TYPES = {"Text", "Choice"}
_VALUE_TYPES = {
    "Text": {"Text", "Choice"},
    "Choice": {"Text", "Choice"},
    "Number": {"Number", "Currency", "Integer"},
    "Currency": {"Number", "Currency", "Integer"},
    "Integer": {"Number", "Integer", "Counter"},
    "Counter": {"Number", "Integer", "Counter"},
    "Boolean": {"Boolean", "Integer"},
    "Lookup": {"Lookup", "Integer", "Counter"},
}


@dataclass(frozen=True)
class ViewFilter:
    """Parsed ``<Where>`` tree; ``node`` is None when the view has no filter."""

    node: tuple | None
    field_names: frozenset[str]


def _local(element: Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _no_text(element: Element) -> None:
    if (element.text or "").strip() or (element.tail or "").strip():
        raise ViewScopeError(f"Unexpected text in CAML element {_local(element)}.")


def _field_ref(element: Element) -> tuple[str, bool]:
    if _local(element) != "FieldRef" or len(element) or set(element.attrib) - {"Name", "LookupId"}:
        raise ViewScopeError("Unsupported FieldRef in view filter.")
    name = element.attrib.get("Name", "")
    lookup_id = element.attrib.get("LookupId", "").upper()
    if not name or lookup_id not in {"", "TRUE"}:
        raise ViewScopeError("FieldRef requires Name and only LookupId=\"TRUE\" is supported.")
    return name, lookup_id == "TRUE"


def _value(element: Element) -> tuple[str, str]:
    if _local(element) != "Value" or len(element) or set(element.attrib) != {"Type"}:
        raise ViewScopeError("Only literal <Value Type=...> elements are supported "
                             "(no Today, UserID or date options).")
    return element.attrib["Type"], element.text or ""


def _parse(element: Element, names: set[str], depth: int = 0) -> tuple:
    if depth > 32:
        raise ViewScopeError("View filter is nested too deeply.")
    _no_text(element)
    tag = _local(element)
    if element.attrib:
        raise ViewScopeError(f"Unsupported attributes on {tag}.")
    children = list(element)
    if tag in {"And", "Or"}:
        if len(children) < 2:
            raise ViewScopeError(f"{tag} requires at least two conditions.")
        return (tag, tuple(_parse(child, names, depth + 1) for child in children))
    if tag in _NULL_TESTS:
        if len(children) != 1:
            raise ViewScopeError(f"{tag} requires exactly one FieldRef.")
        name, lookup_id = _field_ref(children[0])
        names.add(name)
        return (tag, name, lookup_id)
    if tag in _COMPARISONS:
        if len(children) != 2:
            raise ViewScopeError(f"{tag} requires FieldRef and Value.")
        name, lookup_id = _field_ref(children[0])
        names.add(name)
        return (tag, name, lookup_id, _value(children[1]))
    if tag == "In":
        if len(children) != 2 or _local(children[1]) != "Values" or children[1].attrib:
            raise ViewScopeError("In requires FieldRef and Values.")
        name, lookup_id = _field_ref(children[0])
        values = tuple(_value(child) for child in children[1])
        if not values:
            raise ViewScopeError("In requires at least one Value.")
        names.add(name)
        return ("In", name, lookup_id, values)
    raise ViewScopeError(f"Unsupported CAML operator: {tag}.")


def parse_view_query(view_query: str) -> ViewFilter:
    """Parse ``SP.View.ViewQuery``; unknown constructs raise ViewScopeError."""
    if not isinstance(view_query, str):
        raise ViewScopeError("ViewQuery must be a string.")
    try:
        root = SafeET.fromstring(f"<Query>{view_query}</Query>", forbid_dtd=True)
    except (SafeET.ParseError, DefusedXmlException) as exc:
        raise ViewScopeError("ViewQuery is not valid, safe XML.") from exc
    _no_text(root)
    wheres = [child for child in root if _local(child) == "Where"]
    if any(_local(child) not in {"Where", "OrderBy", "GroupBy"} for child in root) or len(wheres) > 1:
        raise ViewScopeError("ViewQuery may only contain one Where, OrderBy and GroupBy.")
    if not wheres:
        return ViewFilter(None, frozenset())
    where = wheres[0]
    _no_text(where)
    if where.attrib or len(where) != 1:
        raise ViewScopeError("Where must contain exactly one condition.")
    names: set[str] = set()
    return ViewFilter(_parse(where[0], names), frozenset(names))


def _literal(value: tuple[str, str], field_type: str, lookup_id: bool) -> Any:
    value_type, text = value
    if field_type == "Lookup" and not lookup_id:
        raise ViewScopeError("Lookup filters must compare LookupId, not display text.")
    if lookup_id and field_type != "Lookup":
        raise ViewScopeError("LookupId is only supported on single Lookup fields.")
    if value_type not in _VALUE_TYPES.get(field_type, set()):
        raise ViewScopeError(f"Value type {value_type} is not supported for {field_type}.")
    if field_type in _TEXT_TYPES:
        return text
    stripped = text.strip()
    if field_type == "Boolean":
        mapping = {"1": True, "0": False, "true": True, "false": False}
        if stripped.casefold() not in mapping:
            raise ViewScopeError("Invalid Boolean value in view filter.")
        return mapping[stripped.casefold()]
    try:
        number = int(stripped) if field_type in {"Lookup", "Counter", "Integer"} else float(stripped)
    except ValueError as exc:
        raise ViewScopeError("Invalid numeric value in view filter.") from exc
    if isinstance(number, float) and not math.isfinite(number):
        raise ViewScopeError("Non-finite number in view filter.")
    return number


def _compare(op: str, left: Any, right: Any, field_type: str) -> bool:
    if left is None:
        if op == "Eq":
            return False
        raise ViewScopeError(f"{op} on an empty value has unverified SharePoint semantics.")
    if field_type in _TEXT_TYPES:
        if type(left) is not str:
            raise ViewScopeError("Text field returned a non-text value.")
        if op not in {"Eq", "Neq"}:
            raise ViewScopeError("Ordering text comparisons depend on SQL collation.")
        exact, folded = left == right, left.casefold() == right.casefold()
        if exact != folded:
            raise ViewScopeError("Text filter result depends on letter case (SQL collation).")
        return exact if op == "Eq" else not exact
    if field_type == "Boolean":
        if type(left) is not bool or op not in {"Eq", "Neq"}:
            raise ViewScopeError("Boolean filters support only Eq/Neq on boolean values.")
    elif type(left) not in {int, float} or isinstance(left, bool):
        raise ViewScopeError("Numeric field returned a non-numeric value.")
    return {
        "Eq": left == right, "Neq": left != right, "Lt": left < right,
        "Leq": left <= right, "Gt": left > right, "Geq": left >= right,
    }[op]


def _matches(node: tuple, row: dict[str, Any], types: dict[str, str]) -> bool:
    tag = node[0]
    if tag in {"And", "Or"}:
        results = [_matches(child, row, types) for child in node[1]]
        return all(results) if tag == "And" else any(results)
    name, lookup_id = node[1], node[2]
    field_type = types[name]
    value = row.get("ID") if name == "ID" else row.get(name, _MISSING)
    if value is _MISSING or isinstance(value, dict):
        raise ViewScopeError(f"View filter field {name} was not read unambiguously.")
    if tag in _NULL_TESTS:
        if value == "":
            raise ViewScopeError("Empty text versus NULL is ambiguous for IsNull/IsNotNull.")
        return (value is None) == (tag == "IsNull")
    if tag == "In":
        literals = [_literal(item, field_type, lookup_id) for item in node[3]]
        return any(_compare("Eq", value, literal, field_type) for literal in literals)
    return _compare(tag, value, _literal(node[3], field_type, lookup_id), field_type)


_MISSING = object()


def evaluate_view(view_filter: ViewFilter, rows: list[dict[str, Any]],
                  field_types: dict[str, str]) -> list[int]:
    """Return sorted IDs matching the filter; any unverifiable case raises."""
    if view_filter.node is None:
        return sorted(row["ID"] for row in rows)
    missing = view_filter.field_names - set(field_types)
    if missing:
        raise ViewScopeError("View filter references unknown fields: " + ", ".join(sorted(missing)))
    unsupported = {name for name in view_filter.field_names
                   if field_types[name] not in _VALUE_TYPES}
    if unsupported:
        raise ViewScopeError("View filter uses unsupported field types: " + ", ".join(sorted(unsupported)))
    return sorted(row["ID"] for row in rows if _matches(view_filter.node, row, field_types))
