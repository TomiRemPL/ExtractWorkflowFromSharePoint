"""Adaptacja katalogu do czytelnego, odczytowego widoku GUI."""

from __future__ import annotations

import heapq
from pathlib import Path
from typing import Any

from tools.sp_automation.catalog import Catalog, CatalogError, Issue, ListRecord, load_catalog
from tools.sp_automation.relation_tab import ListView, RelationView, RelationsSnapshot
from tools.sp_automation.relations import Relation, build_relations


_FOCUS_IDS = {
    "d5670805-4592-4ef6-9b55-54252ac07e12",
    "9de40d46-5804-43c1-a74c-f3ddd4327b73",
    "460a09d4-cece-45d6-ac46-05ea92255cc0",
    "435dadf3-ab5d-4d56-a38e-f7bb8e837c53",
    "fa878eea-2434-4dec-b5df-52ce112ce654",
    "01ed4d26-26f1-4f67-9ade-9994464b14bb",
}

_STATUS = {
    "missing": "brak w eksporcie",
    "not_exported": "nie eksportowano",
    "complete": "kompletne (potwierdzone stronicowanie i ETag)",
    "unconfirmed": "dostępne, kompletność niepotwierdzona",
    "error": "błąd",
    "identity_error": "niezgodna lub niepotwierdzona tożsamość",
    "external": "lista docelowa poza katalogiem",
    "invalid_reference": "nieprawidłowa referencja listy",
    "invalid_item_ids": "nieprawidłowe lub niejednoznaczne identyfikatory elementów",
}

_ISSUE = {
    "invalid_field_schema": "Niepoprawny SchemaXml pola",
    "invalid_definition": "Nieprawidłowa lub nieczytelna definicja listy",
    "identity_mismatch": "Definicja nie odpowiada liście z manifestu",
    "missing_views": "Brak widoków listy",
    "invalid_resource": "Nieprawidłowy zasób listy",
    "invalid_field": "Pole bez nazwy wewnętrznej",
    "duplicate_field": "Powtórzona nazwa wewnętrzna pola",
    "system_field_ref": "Pola z nieguidowym FieldRef (zwykle systemowe) traktowane jako główne Lookup; zweryfikuj ręcznie, jeśli są używane",
    "missing_lookup_parent": "Brak głównego pola projekcji Lookup",
    "lookup_parent_mismatch": "Projekcja i główne pole Lookup wskazują różne listy",
    "invalid_view": "Nieprawidłowy widok",
    "invalid_manifest_options": "Nieprawidłowe opcje eksportu w manifeście",
    "invalid_manifest_entry": "Nieprawidłowa pozycja listy w manifeście",
    "invalid_manifest_id": "Brak, powtórzenie lub niepoprawny GUID listy",
    "ambiguous_path": "Niejednoznaczna lub niedozwolona nazwa pliku w manifeście",
    "missing_definition": "Brak definicji listy",
    "missing_data": "Brak pliku danych listy",
    "invalid_data": "Nieprawidłowy lub nieczytelny plik danych listy",
    "incomplete_export": "Ekstraktor oznaczył eksport jako niekompletny",
    "incomplete_definition": "Ekstraktor zgłosił błędy odczytu definicji listy",
    "incomplete_data": "Dane listy niekompletne lub nieodczytane przez ekstraktor",
    "inconsistent_export": "Dane, plik ETag i manifest są niezgodne",
}


def _issue_text(issue: Issue) -> str:
    description = _ISSUE.get(issue.code, issue.message)
    field = f" ({issue.field_name})" if issue.field_name else ""
    return f"{description}{field} [{issue.code}]"


def _status(value: str) -> str:
    return _STATUS.get(value, value)


def _text(value: Any) -> str:
    if value is None:
        return "(puste)"
    return " ".join(str(value).split())[:120]


def _row_id(row: dict[str, Any]) -> int | None:
    value = row.get("Id", row.get("ID"))
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 20:
        number = int(value)
        return number if number > 0 else None
    return None


def _index_rows(record: ListRecord) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    duplicates: set[int] = set()
    for row in record.rows or []:
        row_id = _row_id(row)
        if row_id is not None:
            if row_id in result:
                duplicates.add(row_id)
            else:
                result[row_id] = row
    for row_id in duplicates:
        del result[row_id]
    return result


def _list_details(record: ListRecord, catalog: Catalog) -> str:
    workflow_count = len(record.workflow_associations) if record.workflow_associations is not None else "nieznana"
    change_count = (
        sum(workflow.get("AutoStartChange") is True for workflow in record.workflow_associations)
        if record.workflow_associations is not None
        and all(isinstance(workflow.get("AutoStartChange"), bool) for workflow in record.workflow_associations)
        else "nieznana"
    )
    receivers = len(record.event_receivers) if record.event_receivers is not None else "nieznana"
    lines = [
        record.title,
        f"GUID: {record.id}",
        f"Witryna według manifestu: {catalog.site_url or 'nieznana'}",
        f"Fingerprint pojedynczej listy: {record.schema_fingerprint or 'nieznany'} "
        "(nie potwierdza kompletności schematu całego algorytmu)",
        f"Definicja: {_status(record.definition_status)}",
        f"Dane: {_status(record.data_status)}; wiersze: {record.row_count if record.row_count is not None else 'brak danych'}; "
        f"ItemCount w metadanych: {record.item_count if record.item_count is not None else 'nieznany'}",
        f"Widoki: {_status(record.views_status)}",
        f"Workflow skojarzone: {workflow_count}; uruchamiane po zmianie: {change_count}; "
        f"event receivers: {receivers} (według eksportu)",
        f"Wersjonowanie: {_text(record.metadata['EnableVersioning']) if 'EnableVersioning' in record.metadata else 'nieznane'}",
        "",
        "Pola (nazwa wyświetlana — InternalName — typ — nazwa REST):",
    ]
    for col in record.fields.values():
        flags = []
        if col.metadata.get("ReadOnlyField") is True:
            flags.append("tylko odczyt")
        if col.metadata.get("Required") is True:
            flags.append("wymagane")
        if col.field_ref:
            flags.append(f"projekcja pola {col.field_ref}")
        suffix = f" ({', '.join(flags)})" if flags else ""
        lines.append(
            f"• {col.title or col.internal_name} — {col.internal_name} — {col.type_as_string or '?'}"
            f" — {col.entity_property_name or 'nieznana'}{suffix}"
        )
    lines.append("")
    lines.append("Widoki (ich filtr NIE jest stosowany do mapy):")
    for view in record.views:
        lines.append(f"• {view.title}: {view.server_relative_url or '(brak URL)'}")
        if view.view_query:
            lines.append(f"  CAML: {view.view_query}")
    issues = [issue for issue in catalog.issues if issue.list_id == record.id]
    if issues:
        lines.append("")
        lines.append("Problemy odczytu metadanych:")
        lines.extend(f"• {_issue_text(issue)}" for issue in issues)
    return "\n".join(lines)


def _number(value: int | None) -> str:
    return str(value) if value is not None else "nieznane"


def _relation_details(
    relation: Relation,
    catalog: Catalog,
    indexes: dict[str, dict[int, dict[str, Any]]],
) -> str:
    source = catalog.lists[relation.source_list_id]
    target = catalog.lists.get(relation.target_list_id)
    target_title = target.title if target else relation.target_list_id or "nieustalona"
    stats = relation.stats
    lines = [
        f"{source.title} → {target_title}",
        f"Pole: {relation.field.title or relation.field.internal_name}",
        f"InternalName: {relation.field.internal_name}; REST: {relation.field.entity_property_name or 'nieznana'}",
        f"Typ: {relation.field.type_as_string}; pole wyświetlane docelowej listy: {relation.field.lookup_field or 'nieznane'}",
        f"Stan danych docelowych: {_status(relation.target_status)}",
        f"Wiersze źródła: {_number(stats.total)}; wypełnione: {_number(stats.populated)}; puste: {_number(stats.empty)}",
        f"Brak pola w eksporcie: {_number(stats.missing)}; wartość nierozpoznana: {_number(stats.unknown)}; "
        f"ID bez dopasowania w eksporcie: {_number(stats.dangling)}",
        "Liczby dotyczą wyłącznie migawki offline i nie potwierdzają jej kompletności.",
    ]
    if relation.reverse_index:
        lines.extend(["", "Przykłady powiązań (maks. 25, identyfikatory z eksportu):"])
        source_rows = indexes.get(relation.source_list_id, {})
        target_rows = indexes.get(relation.target_list_id, {})
        target_property = relation.field.lookup_field
        if target and target_property in target.fields:
            target_property = target.fields[target_property].entity_property_name or target_property
        total_pairs = sum(len(sources) for sources in relation.reverse_index.values())
        pairs = ((source_id, target_id) for target_id, sources in relation.reverse_index.items() for source_id in sources)
        for source_id, target_id in heapq.nsmallest(25, pairs):
            source_row = source_rows.get(source_id)
            target_row = target_rows.get(target_id)
            source_label = _text(source_row.get("Title")) if source_row else "(brak jednoznacznego elementu)"
            if target_row is None:
                target_label = "(brak w eksporcie lub niejednoznaczny ID)"
            elif target_property and target_property in target_row:
                target_label = _text(target_row[target_property])
            else:
                target_label = f"(pole wyświetlane niedostępne; Tytuł: {_text(target_row.get('Title'))})"
            lines.append(f"• #{source_id} {source_label} → #{target_id} {target_label}")
        if total_pairs > 25:
            lines.append(f"Pokazano 25 z {total_pairs} powiązań.")
    return "\n".join(lines)


def load_relations_snapshot(path: Path) -> RelationsSnapshot:
    """Odczytuje lokalne pliki; nie tworzy ani nie wysyła żądań do SharePoint."""
    try:
        catalog = load_catalog(path)
    except CatalogError as exc:
        raise CatalogError(f"Nie można wczytać manifestu eksportu: {exc}") from exc
    indexes = {key: _index_rows(record) for key, record in catalog.lists.items()}
    records = sorted(catalog.lists.values(), key=lambda item: (item.title.casefold(), item.id))
    lists = [
        ListView(item.id, item.title or item.id, _list_details(item, catalog), item.id in _FOCUS_IDS)
        for item in records
    ]
    relations = []
    for relation in build_relations(catalog):
        target = relation.target_list_id or f"invalid:{relation.source_list_id}:{relation.field.internal_name}"
        relations.append(RelationView(
            key=f"{relation.source_list_id}:{relation.field.internal_name}",
            source=relation.source_list_id,
            target=target,
            label=relation.field.title or relation.field.internal_name,
            details=_relation_details(relation, catalog, indexes),
            target_title=relation.target_list_id or "Nieznana lista docelowa",
        ))
    summary = (
        f"Migawka offline: {catalog.timestamp or 'czas nieznany'}; listy: {len(lists)}; "
        f"zidentyfikowane relacje Lookup: {len(relations)}; uwagi: {len(catalog.issues)}. "
        "Kompletność niepotwierdzona. Brak zapisu do SharePoint."
    )
    diagnostics = "\n".join(
        f"{catalog.lists[issue.list_id].title if issue.list_id in catalog.lists else 'Witryna'}"
        f" — {_issue_text(issue)}" for issue in catalog.issues
    )
    return RelationsSnapshot(lists, relations, summary, diagnostics, catalog)
