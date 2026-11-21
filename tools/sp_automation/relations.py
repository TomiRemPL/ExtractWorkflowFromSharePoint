"""Main SharePoint Lookup edges and offline snapshot statistics."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from .catalog import Catalog, FieldRecord, ListRecord, normalize_guid


@dataclass(frozen=True)
class RelationStats:
    """Counts of source rows; dangling is a subset of populated, not an extra category.

    Dangling is None without usable target IDs. Even zero is only an observation
    of this historical, potentially incomplete snapshot.
    """
    total: int | None
    populated: int | None
    empty: int | None
    missing: int | None
    unknown: int | None
    dangling: int | None


@dataclass(frozen=True)
class Relation:
    source_list_id: str
    target_list_id: str
    field: FieldRecord
    kind: str
    target_status: str
    stats: RelationStats
    # target item ID -> source item IDs, only where both IDs are valid.
    reverse_index: dict[int, tuple[int, ...]] = dataclass_field(default_factory=dict, repr=False)


def _id(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value > 0 else None
    if isinstance(value, str) and len(value) <= 20 and value.isascii() and value.isdecimal():
        number = int(value)
        return number if number > 0 else None
    return None


def _lookup_ids(value: Any, multi: bool) -> tuple[str, tuple[int, ...]]:
    if value is None or value == "" or value == []:
        return "empty", ()
    if isinstance(value, dict) and "results" in value:
        value = value["results"]
    if isinstance(value, list):
        if not multi:
            return "unknown", ()
        if not value:
            return "empty", ()
        values = value
    else:
        values = [value]
    ids = []
    for item in values:
        number = _id(item.get("Id", item.get("ID"))) if isinstance(item, dict) else _id(item)
        if number is None:
            return "unknown", ()
        ids.append(number)
    return "populated", tuple(ids)


def _target_ids(target: ListRecord | None) -> set[int] | None:
    if target is None or target.rows is None:
        return None
    values = [_id(row.get("Id", row.get("ID"))) for row in target.rows]
    if any(v is None for v in values) or len(set(values)) != len(values):
        return None
    return {value for value in values if value is not None}


def _row_lookup(row: dict[str, Any], col: FieldRecord) -> tuple[str, tuple[int, ...]]:
    id_keys = list(dict.fromkeys(k for k in (
        f"{col.entity_property_name}Id" if col.entity_property_name else "",
        f"{col.internal_name}Id",
    ) if k))
    value_keys = list(dict.fromkeys(k for k in (col.entity_property_name, col.internal_name) if k))
    keys = [name for name in id_keys if name in row]
    if not keys:
        keys = [name for name in value_keys if name in row]
    if not keys:
        return "missing", ()
    parsed = [_lookup_ids(row[key], col.type_as_string.lower() == "lookupmulti") for key in keys]
    return parsed[0] if all(value == parsed[0] for value in parsed) else ("unknown", ())


def _stats(source: ListRecord, target: ListRecord | None, col: FieldRecord) -> tuple[RelationStats, dict[int, tuple[int, ...]]]:
    if source.rows is None:
        return RelationStats(None, None, None, None, None, None), {}
    targets = _target_ids(target)
    populated = empty = missing = unknown = dangling = 0
    reverse: dict[int, list[int]] = {}
    for row in source.rows:
        status, ids = _row_lookup(row, col)
        if status == "missing":
            missing += 1
            continue
        if status == "empty":
            empty += 1
        elif status == "unknown":
            unknown += 1
        else:
            populated += 1
            if targets is not None and any(value not in targets for value in ids):
                dangling += 1
            source_id = _id(row.get("Id", row.get("ID")))
            if source_id is not None:
                for value in set(ids):
                    reverse.setdefault(value, []).append(source_id)
    return (
        RelationStats(len(source.rows), populated, empty, missing, unknown,
                      dangling if targets is not None else None),
        {key: tuple(value) for key, value in reverse.items()},
    )


def build_relations(catalog: Catalog) -> list[Relation]:
    """Return main Lookup edges, including external and invalid references.

    User and projected fields are not edges. Target statuses distinguish absent
    or invalid references, missing data and unconfirmed historical exports.
    """
    relations: list[Relation] = []
    for source in catalog.lists.values():
        for col in source.fields.values():
            typ = col.type_as_string.lower()
            if typ not in {"lookup", "lookupmulti"} or normalize_guid(col.field_ref) or col.schema_error:
                continue
            target_id = source.id if col.lookup_list.strip().lower() == "self" else normalize_guid(col.lookup_list)
            target = catalog.lists.get(target_id)
            if not target_id:
                target_status = "invalid_reference"
            elif target is None:
                target_status = "external"
            elif target.rows is not None and _target_ids(target) is None:
                target_status = "invalid_item_ids"
            else:
                target_status = target.data_status
            stats, reverse = _stats(source, target, col)
            relations.append(Relation(source.id, target_id, col, typ, target_status, stats, reverse))
    return relations
