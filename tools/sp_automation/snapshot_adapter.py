"""Adapt historical SharePoint exports for explicitly advisory simulation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Any
from urllib.parse import urlsplit

from .catalog import Catalog, FieldRecord, ListRecord, normalize_guid
from .models import Graph, GraphError
from .relations import _id, _row_lookup


class SnapshotAdapterError(ValueError):
    """The selected graph cannot be mapped safely onto the available export."""


@dataclass(frozen=True)
class AdaptedSnapshot:
    data: dict[str, Any]
    complete: bool
    warnings: tuple[str, ...]


_SUPPORTED = {
    "Text", "Note", "Choice", "Number", "Currency", "Boolean",
    "Lookup", "LookupMulti", "DateTime",
}
_SYSTEM_FIELDS = {
    "attachments", "author", "contenttype", "contenttypeid", "created", "editor",
    "filedirref", "fileref", "guid", "id", "modified", "owshiddenversion",
    "uniqueid", "_moderationstatus",
}


def _site_key(value: str) -> tuple[str, str, int | None, str]:
    try:
        parsed = urlsplit(value)
        if (parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError
        return (parsed.scheme.lower(), parsed.hostname.lower(), parsed.port,
                parsed.path.rstrip("/"))
    except (ValueError, TypeError) as exc:
        raise SnapshotAdapterError("Adres witryny w eksporcie lub definicji jest niepoprawny.") from exc


def _graph(graph: Graph | dict[str, Any]) -> dict[str, Any]:
    try:
        value = graph if isinstance(graph, Graph) else Graph.from_dict(graph)
        return Graph.from_json(value.to_json()).to_dict()
    except GraphError as exc:
        raise SnapshotAdapterError("Definicja grafu jest niepoprawna.") from exc


def _required_lists(catalog: Catalog, graph: dict[str, Any]) -> set[str]:
    return _graph_requirements(graph, catalog.lists.get)[0]


def _graph_requirements(
    graph: dict[str, Any], get_record: Callable[[str], ListRecord | None],
) -> tuple[set[str], dict[str, set[str]]]:
    """Resolve the same graph dependencies against offline or freshly read schemas."""
    source_id = graph["source_list_id"]
    if get_record(source_id) is None:
        raise SnapshotAdapterError("Lista źródłowa nie występuje w eksporcie.")
    aliases = {"source": source_id}
    required = {source_id}
    fields: dict[str, set[str]] = {source_id: set()}
    pending = [node for node in graph["nodes"] if node["type"] == "lookup"]
    while pending:
        progressed = False
        remaining = []
        for node in pending:
            if node.get("direction", "forward") == "reverse":
                target_id = node["target_list_id"]
                parent_id = aliases.get(node["from"])
                if parent_id is None:
                    remaining.append(node)
                    continue
                record = get_record(target_id)
                field = _field_by_id(record, node["field_id"])
                lookup_id = target_id if field.lookup_list.strip().casefold() == "self" else normalize_guid(field.lookup_list)
                if lookup_id != parent_id:
                    raise SnapshotAdapterError("Relacja odwrotna nie zgadza się ze schematem eksportu.")
            else:
                parent_id = aliases.get(node["from"])
                if parent_id is None:
                    remaining.append(node)
                    continue
                record = get_record(parent_id)
                if record is None:
                    raise SnapshotAdapterError("Brakuje definicji listy źródłowej relacji.")
                field = _field_by_id(record, node["field_id"])
                target_id = record.id if field.lookup_list.strip().casefold() == "self" else normalize_guid(field.lookup_list)
                if not target_id:
                    raise SnapshotAdapterError("Lista docelowa Lookup jest nieznana.")
                if "target_list_id" in node and node["target_list_id"] != target_id:
                    raise SnapshotAdapterError("Lista docelowa Lookup nie zgadza się z definicją.")
            if node["as"] in aliases:
                raise SnapshotAdapterError("Alias Lookup jest niejednoznaczny.")
            aliases[node["as"]] = target_id
            required.update((parent_id, target_id))
            owner = target_id if node.get("direction") == "reverse" else parent_id
            fields.setdefault(owner, set()).add(node["field_id"])
            progressed = True
        if not progressed:
            raise SnapshotAdapterError("Nie można rozwiązać list dla relacji w grafie.")
        pending = remaining
    for node in graph["nodes"]:
        if node["type"] != "assign":
            continue
        list_id = aliases.get(node["alias"])
        if list_id is None:
            raise SnapshotAdapterError("Nie można rozwiązać listy docelowej przypisania.")
        field = _field_by_id(get_record(list_id), node["field_id"])
        fields.setdefault(list_id, set()).add(node["field_id"])
        if field.type_as_string == "Lookup":
            target_id = list_id if field.lookup_list.strip().casefold() == "self" else normalize_guid(field.lookup_list)
            if not target_id:
                raise SnapshotAdapterError("Lista docelowa przypisywanego Lookup jest nieznana.")
            required.add(target_id)
    def references(value: Any, bindings: dict[str, str]) -> None:
        if isinstance(value, list):
            for child in value:
                references(child, bindings)
        elif isinstance(value, dict):
            if value.get("op") in {"any", "all"}:
                list_id = bindings.get(value["alias"])
                if list_id is None:
                    raise SnapshotAdapterError("Nie można rozwiązać aliasu kolekcji.")
                references(value["condition"], {**bindings, "item": list_id})
            elif value.get("kind") == "field":
                list_id = bindings.get(value["alias"])
                if list_id is None:
                    raise SnapshotAdapterError("Nie można rozwiązać aliasu pola.")
                _field_by_id(get_record(list_id), value["field_id"])
                fields.setdefault(list_id, set()).add(value["field_id"])
            else:
                for child in value.values():
                    references(child, bindings)

    references(graph["nodes"], aliases)
    for list_id in required:
        get_record(list_id)
        fields.setdefault(list_id, set())
    return required, fields


def _field_by_id(record: ListRecord | None, field_id: str) -> FieldRecord:
    if record is None:
        raise SnapshotAdapterError("Brak definicji jednej z list grafu.")
    matches = [field for field in record.fields.values() if field.field_id == field_id]
    if len(matches) != 1:
        raise SnapshotAdapterError("Pole grafu jest nieobecne lub niejednoznaczne w eksporcie.")
    return matches[0]


def _fingerprint(catalog: Catalog, list_ids: set[str]) -> str:
    schemas = []
    for list_id in sorted(list_ids):
        record = catalog.lists.get(list_id)
        if (record is None or record.definition_status not in {"unconfirmed", "complete"}
                or not record.schema_fingerprint):
            raise SnapshotAdapterError("Brakuje schematu jednej z list używanych przez graf.")
        schemas.append((list_id, record.schema_fingerprint))
    payload = json.dumps(schemas, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def catalog_graph_fingerprint(catalog: Catalog, graph: Graph | dict[str, Any]) -> str:
    """Return a graph-specific digest; it does not attest to export completeness."""
    data = _graph(graph)
    return _fingerprint(catalog, _required_lists(catalog, data))


def _numeric(value: Any) -> int | float | None:
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", value):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _choices(value: Any) -> list[str] | None:
    if isinstance(value, dict) and isinstance(value.get("results"), list):
        value = value["results"]
    return value if isinstance(value, list) and all(type(item) is str for item in value) else None


def _field_metadata(field: FieldRecord, catalog: Catalog) -> dict[str, Any]:
    raw = field.metadata
    field_type = field.type_as_string
    readonly = raw.get("ReadOnlyField") is not False
    system = (raw.get("FromBaseType") is True
              and field.internal_name.casefold() in _SYSTEM_FIELDS)
    dependent = bool(field.field_ref) or raw.get("IsDependentLookup") is True
    required = raw.get("Required")
    meta: dict[str, Any] = {
        "internal_name": field.internal_name,
        "entity_property_name": field.entity_property_name or field.internal_name,
        "type": field_type,
        "required": required,
        "readonly": readonly,
        "system": system,
        "dependent": dependent,
        "field_ref": bool(field.field_ref),
    }
    valid = (
        not field.schema_error and field_type in _SUPPORTED and type(required) is bool
        and raw.get("ReadOnlyField") is False and not dependent
        and raw.get("ValidationFormula") in (None, "")
        and raw.get("ValidationMessage") in (None, "")
    )
    if field_type == "Lookup":
        target = normalize_guid(field.lookup_list)
        allow_multiple = raw.get("AllowMultipleValues")
        if field.lookup_list.strip().casefold() == "self":
            target = normalize_guid(raw.get("SourceID")) or ""
        meta["lookup_list_id"] = target
        valid = valid and type(allow_multiple) is bool and not allow_multiple and target in catalog.lists
    elif field_type == "LookupMulti":
        target = normalize_guid(field.lookup_list)
        meta["lookup_list_id"] = target
        valid = False
    elif field_type == "Choice":
        choices = _choices(raw.get("Choices"))
        if choices is not None:
            meta["choices"] = choices
        valid = valid and choices is not None and raw.get("AllowMultipleValues") is False
    elif field_type == "Text":
        maximum = raw.get("MaxLength")
        if type(maximum) is int and maximum >= 0:
            meta["max_length"] = maximum
        else:
            valid = False
    elif field_type == "Note":
        valid = valid and raw.get("RichText") is False and raw.get("AppendOnly") is False
        meta["plain"] = raw.get("RichText") is False
    elif field_type in {"Number", "Currency"}:
        for raw_key, key in (("MinimumValue", "minimum"), ("MaximumValue", "maximum")):
            if raw_key in raw and raw[raw_key] is not None:
                number = _numeric(raw[raw_key])
                if number is None:
                    valid = False
                else:
                    meta[key] = number
    elif field_type in {"Boolean", "DateTime"}:
        pass
    else:
        valid = False
    meta["constraints_verified"] = bool(valid)
    meta["writable"] = bool(valid and not readonly and not system)
    return meta


def _rows(record: ListRecord) -> list[dict[str, Any]]:
    if record.rows is None:
        raise SnapshotAdapterError(f"Brak wyeksportowanych danych listy {record.title or record.id}.")
    fields = list(record.fields.values())
    converted: list[dict[str, Any]] = []
    for source in record.rows:
        item_id = _id(source.get("ID", source.get("Id")))
        if item_id is None or ("ID" in source and "Id" in source and _id(source["ID"]) != _id(source["Id"])):
            raise SnapshotAdapterError(f"Niepoprawne lub niejednoznaczne ID elementu listy {record.title or record.id}.")
        row: dict[str, Any] = {"ID": item_id}
        for field in fields:
            if field.type_as_string in {"Lookup", "LookupMulti"}:
                status, ids = _row_lookup(source, field)
                if status == "populated":
                    row[field.internal_name] = list(ids) if field.type_as_string == "LookupMulti" else ids[0]
                elif status == "empty":
                    row[field.internal_name] = [] if field.type_as_string == "LookupMulti" else None
                elif status == "unknown":
                    row[field.internal_name] = {"unknown": True}
                continue
            names = list(dict.fromkeys(name for name in (field.entity_property_name, field.internal_name) if name))
            present = [name for name in names if name in source]
            if not present:
                continue
            value = source[present[0]]
            if any(source[name] != value for name in present[1:]):
                row[field.internal_name] = {"conflict": True}
                continue
            if value is None or type(value) in {str, int, float, bool}:
                row[field.internal_name] = value
        converted.append(row)
    return converted


def build_simulation_snapshot(catalog: Catalog, graph: Graph | dict[str, Any]) -> AdaptedSnapshot:
    """Build an offline snapshot without claiming that historical data is complete."""
    graph_data = _graph(graph)
    if _site_key(catalog.site_url) != _site_key(graph_data["site"]):
        raise SnapshotAdapterError("Adres witryny w definicji różni się od eksportu.")
    if graph_data["scope"]["type"] == "view":
        raise SnapshotAdapterError(
            "Zakres widoku wymaga świeżego odczytu online; eksport historyczny nie stosuje filtrów widoków.")
    required = _required_lists(catalog, graph_data)
    fingerprint = _fingerprint(catalog, required)
    if graph_data["schema_fingerprint"] != fingerprint:
        raise SnapshotAdapterError("Fingerprint grafu jest nieaktualny; odśwież go z eksportu.")
    lists = {}
    warnings = []
    complete = True
    for list_id in sorted(required):
        record = catalog.lists[list_id]
        if record.definition_status not in {"unconfirmed", "complete"}:
            raise SnapshotAdapterError(f"Brak potwierdzonego schematu listy {record.title or list_id}.")
        rows = _rows(record)
        is_complete = record.data_status == "complete" and record.definition_status == "complete"
        complete = complete and is_complete
        if not is_complete:
            warnings.append(f"{record.title or list_id}: kompletność eksportu niepotwierdzona.")
        if record.item_count is not None and record.item_count != len(rows):
            warnings.append(f"{record.title or list_id}: liczba wierszy różni się od ItemCount.")
        fields = {}
        field_ids = [field.field_id for field in record.fields.values() if field.field_id]
        if any(count > 1 for count in Counter(field_ids).values()):
            raise SnapshotAdapterError(f"Niejednoznaczne GUID pól na liście {record.title or list_id}.")
        for field in record.fields.values():
            if field.field_id:
                fields[field.field_id] = _field_metadata(field, catalog)
        lists[list_id] = {"complete": is_complete, "fields": fields, "items": rows}
    return AdaptedSnapshot(
        {"site": graph_data["site"], "schema_fingerprint": fingerprint, "lists": lists},
        complete,
        tuple(warnings),
    )
