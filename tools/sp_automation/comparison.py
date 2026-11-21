"""Compare a direct single Lookup with a two-hop path in an offline export."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .catalog import Catalog, ListRecord
from .relations import Relation, _id, _row_lookup, build_relations


class ComparisonError(ValueError):
    """The available export cannot support this comparison."""


@dataclass(frozen=True)
class ComparisonPath:
    direct: Relation
    first: Relation
    second: Relation


@dataclass(frozen=True)
class ComparisonRow:
    source_id: int
    intermediate_id: int | None
    direct_id: int | None
    indirect_id: int | None
    status: str


def comparison_paths(catalog: Catalog, selected: set[str]) -> list[ComparisonPath]:
    """Find direct and two-hop paths within the explicitly selected lists."""
    outgoing: dict[str, list[Relation]] = defaultdict(list)
    for relation in build_relations(catalog):
        if (relation.kind == "lookup" and relation.source_list_id in selected
                and relation.target_list_id in selected
                and relation.source_list_id != relation.target_list_id):
            outgoing[relation.source_list_id].append(relation)
    paths = []
    for directs in outgoing.values():
        for direct in directs:
            for first in directs:
                if first.target_list_id == direct.target_list_id:
                    continue
                for second in outgoing.get(first.target_list_id, ()):
                    if second.target_list_id == direct.target_list_id:
                        paths.append(ComparisonPath(direct, first, second))
    return sorted(paths, key=lambda p: (
        catalog.lists[p.direct.source_list_id].title.casefold(),
        p.direct.field.title.casefold(), p.first.field.title.casefold(), p.second.field.title.casefold(),
    ))


def _rows(record: ListRecord | None) -> dict[int, dict]:
    if record is None or record.rows is None:
        raise ComparisonError("Brak danych jednej z list potrzebnych do porównania.")
    rows = {}
    for row in record.rows:
        item_id = _id(row.get("Id", row.get("ID")))
        if (item_id is None or ("Id" in row and "ID" in row and _id(row["Id"]) != _id(row["ID"]))
                or item_id in rows):
            raise ComparisonError("Brak, niejednoznaczność lub powtórzenie ID elementu w eksporcie.")
        rows[item_id] = row
    return rows


def compare_paths(catalog: Catalog, path: ComparisonPath) -> list[ComparisonRow]:
    """Compare observed IDs only; no completeness or business rule is asserted."""
    available = {(r.source_list_id, r.field.internal_name, r.target_list_id, r.field.field_id): r
                 for r in build_relations(catalog) if r.kind == "lookup"}
    keys = [(r.source_list_id, r.field.internal_name, r.target_list_id, r.field.field_id)
            for r in (path.direct, path.first, path.second)]
    if any(key not in available for key in keys):
        raise ComparisonError("Niepoprawne lub nieaktualne relacje porównania.")
    direct, first, second = (available[key] for key in keys)
    if (first.source_list_id != direct.source_list_id
            or first.target_list_id != second.source_list_id
            or second.target_list_id != direct.target_list_id):
        raise ComparisonError("Niepoprawne lub nieaktualne relacje porównania.")
    source = _rows(catalog.lists.get(direct.source_list_id))
    intermediate = _rows(catalog.lists.get(first.target_list_id))
    target = _rows(catalog.lists.get(direct.target_list_id))
    result = []
    for source_id, row in sorted(source.items()):
        direct_status, direct_ids = _row_lookup(row, direct.field)
        first_status, first_ids = _row_lookup(row, first.field)
        direct_id = direct_ids[0] if direct_ids else None
        intermediate_id = first_ids[0] if first_ids else None
        indirect_id = None
        if direct_status in ("missing", "unknown") or first_status in ("missing", "unknown"):
            status = "unknown"
        elif direct_id is not None and direct_id not in target:
            status = "missing_target"
        elif intermediate_id is None:
            status = "no_intermediate"
        elif intermediate_id not in intermediate:
            status = "missing_intermediate"
        else:
            second_status, indirect_ids = _row_lookup(intermediate[intermediate_id], second.field)
            indirect_id = indirect_ids[0] if indirect_ids else None
            if second_status in ("missing", "unknown"):
                status = "unknown"
            elif indirect_id is not None and indirect_id not in target:
                status = "missing_target"
            elif direct_id is None and indirect_id is None:
                status = "both_empty"
            elif indirect_id is None:
                status = "indirect_empty"
            elif direct_id is None:
                status = "direct_empty"
            else:
                status = "equal" if direct_id == indirect_id else "different"
        result.append(ComparisonRow(source_id, intermediate_id, direct_id, indirect_id, status))
    return result
