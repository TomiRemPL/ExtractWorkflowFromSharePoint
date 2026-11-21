"""Read an extractor snapshot without making SharePoint requests.

Legacy manifests identify filenames but do not certify completeness.  A data
file is usable only when its manifest entry and list definition agree on GUID.
Format v2 manifests (extractor with completeness checks) can certify a list as
``complete`` once rows, item IDs and the ``21_etagi_*.json`` file agree.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, TypeGuard
from uuid import UUID
import xml.etree.ElementTree as ET

_ETAG_RE = re.compile(r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]+"')


class CatalogError(ValueError):
    """The snapshot cannot be identified safely."""


def normalize_guid(value: Any) -> str:
    try:
        return str(UUID(str(value).strip().strip("{}")))
    except (ValueError, TypeError, AttributeError):
        return ""


@dataclass(frozen=True)
class Issue:
    code: str
    message: str
    list_id: str = ""
    field_name: str = ""

    @property
    def severity(self) -> str:
        return "warning" if self.code in {"missing_definition", "missing_data", "missing_views", "system_field_ref",
                                          "incomplete_export", "incomplete_definition", "incomplete_data"} else "error"


@dataclass(frozen=True)
class FieldRecord:
    internal_name: str
    title: str
    type_as_string: str
    field_id: str = ""
    entity_property_name: str = ""
    lookup_list: str = ""
    lookup_field: str = ""
    field_ref: str = ""
    schema_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ViewRecord:
    id: str
    title: str
    server_relative_url: str = ""
    view_query: str = ""
    fields: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class ListRecord:
    id: str
    title: str
    fields: dict[str, FieldRecord] = field(default_factory=dict)
    views: list[ViewRecord] = field(default_factory=list)
    rows: list[dict[str, Any]] | None = field(default=None, repr=False)
    definition_status: str = "missing"
    views_status: str = "missing"
    data_status: str = "missing"
    item_count: int | None = None
    schema_fingerprint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict, repr=False)
    workflow_associations: list[dict[str, Any]] | None = field(default=None, repr=False)
    event_receivers: list[dict[str, Any]] | None = field(default=None, repr=False)
    row_etags: dict[int, str] | None = field(default=None, repr=False)

    @property
    def row_count(self) -> int | None:
        """None means unavailable; zero means an exported empty array."""
        return len(self.rows) if self.rows is not None else None


@dataclass
class Catalog:
    lists: dict[str, ListRecord] = field(default_factory=dict)
    site_url: str = ""
    timestamp: str = ""
    issues: list[Issue] = field(default_factory=list)


def _read_json(path: Path, root: Path) -> Any:
    if not path.resolve().is_relative_to(root.resolve()):
        raise OSError("Resource resolves outside the snapshot directory.")
    with path.open(encoding="utf-8-sig") as file:
        return json.load(file)


def _safe_title(value: Any) -> TypeGuard[str]:
    # A manifest is data, not permission to read arbitrary paths.
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and not any(c in value for c in "/\\:\0")
    )


def _parse_field(raw: dict[str, Any], issues: list[Issue], list_id: str) -> FieldRecord:
    name = str(raw.get("InternalName") or "")
    attrs: dict[str, str] = {}
    schema_error = False
    if raw.get("SchemaXml"):
        try:
            attrs = ET.fromstring(raw["SchemaXml"]).attrib
        except (ET.ParseError, TypeError, ValueError):
            schema_error = True
            issues.append(Issue("invalid_field_schema", "Invalid field SchemaXml.", list_id, name))
    field_type = str(raw.get("TypeAsString") or attrs.get("Type") or "")
    if not raw.get("TypeAsString") and field_type.lower() == "lookup" and attrs.get("Mult", "").lower() == "true":
        field_type = "LookupMulti"
    return FieldRecord(
        internal_name=name,
        title=str(raw.get("Title") or name),
        type_as_string=field_type,
        field_id=normalize_guid(raw.get("Id") or attrs.get("ID")),
        entity_property_name=str(raw.get("EntityPropertyName") or ""),
        lookup_list=str(raw.get("LookupList") or attrs.get("List") or ""),
        lookup_field=str(raw.get("LookupField") or attrs.get("ShowField") or ""),
        field_ref=str(raw.get("FieldRef") or attrs.get("FieldRef") or ""),
        schema_error=schema_error,
        metadata=raw,
    )


def _parse_definition(record: ListRecord, document: Any, issues: list[Issue]) -> bool:
    if not isinstance(document, dict) or not isinstance(document.get("lista"), dict):
        issues.append(Issue("invalid_definition", "Invalid list definition.", record.id))
        record.definition_status = "error"
        return False
    info = document["lista"]
    if (normalize_guid(info.get("Id")) != record.id
            or (record.title and info.get("Title") and info["Title"] != record.title)):
        issues.append(Issue("identity_mismatch", "Definition identity does not match manifest.", record.id))
        record.definition_status = "identity_error"
        return False
    fields = document.get("kolumny")
    views = document.get("widoki")
    if views is None:
        issues.append(Issue("missing_views", "List views are missing.", record.id))
        views = []
    elif not isinstance(views, list):
        record.views_status = "error"
    else:
        record.views_status = "unconfirmed"
    if not isinstance(fields, list) or not isinstance(views, list):
        issues.append(Issue("invalid_definition", "Invalid fields or views collection.", record.id))
        record.definition_status = "error"
        return False
    record.metadata = info
    for key, attribute in (("workflowy", "workflow_associations"), ("eventReceivers", "event_receivers")):
        value = document.get(key)
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            setattr(record, attribute, value)
        elif value is not None:
            issues.append(Issue("invalid_resource", "Invalid list resource collection.", record.id, key))
    count = info.get("ItemCount")
    record.item_count = count if isinstance(count, int) and not isinstance(count, bool) else None
    seen: dict[str, str] = {}
    ambiguous_names: set[str] = set()
    for raw in fields:
        if not isinstance(raw, dict) or not isinstance(raw.get("InternalName"), str) or not raw["InternalName"]:
            issues.append(Issue("invalid_field", "Field without an internal name.", record.id))
            continue
        field_record = _parse_field(raw, issues, record.id)
        key = field_record.internal_name.casefold()
        if key in ambiguous_names:
            continue
        if key in seen:
            issues.append(Issue("duplicate_field", "Duplicate field internal name.", record.id, field_record.internal_name))
            del record.fields[seen[key]]
            ambiguous_names.add(key)
            continue
        seen[key] = field_record.internal_name
        record.fields[field_record.internal_name] = field_record
    field_ids = Counter(f.field_id for f in record.fields.values() if f.field_id)
    ids = {f.field_id: f for f in record.fields.values() if f.field_id and field_ids[f.field_id] == 1}
    # Pola systemowe z nieguidowym FieldRef zbieramy w jeden wpis na listę/bibliotekę.
    system_refs: list[str] = []
    for col in record.fields.values():
        if col.field_ref and col.type_as_string.lower().startswith("lookup"):
            parent_id = normalize_guid(col.field_ref)
            if not parent_id:
                system_refs.append(col.internal_name)
                continue
            parent = ids.get(parent_id)
            if not parent or parent is col or normalize_guid(parent.field_ref) or not parent.type_as_string.lower().startswith("lookup"):
                issues.append(Issue("missing_lookup_parent", "Lookup projection has no valid main field.", record.id, col.internal_name))
            elif (col.lookup_list and parent.lookup_list
                  and col.lookup_list.strip("{}").lower() != parent.lookup_list.strip("{}").lower()):
                issues.append(Issue("lookup_parent_mismatch", "Lookup projection and main field refer to different lists.", record.id, col.internal_name))
    if system_refs:
        issues.append(Issue(
            "system_field_ref",
            f"{len(system_refs)} non-GUID FieldRef lookup field(s) treated as main Lookups; verify manually.",
            record.id, ", ".join(system_refs)))
    for raw in views:
        if not isinstance(raw, dict):
            issues.append(Issue("invalid_view", "Invalid view.", record.id))
            continue
        view_fields = raw.get("KolumnyWidoku", [])
        record.views.append(ViewRecord(
            id=normalize_guid(raw.get("Id")),
            title=str(raw.get("Title") or ""),
            server_relative_url=str(raw.get("ServerRelativeUrl") or ""),
            view_query=str(raw.get("ViewQuery") or ""),
            fields=tuple(x for x in view_fields if isinstance(x, str)) if isinstance(view_fields, list) else (),
            metadata=raw,
        ))
    # Canonical field metadata, independent of row values and file ordering.
    schema = {
        "list_schema": document.get("schemaXml") or "",
        "fields": [f.metadata for f in sorted(record.fields.values(), key=lambda f: f.internal_name)],
    }
    record.schema_fingerprint = hashlib.sha256(
        json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    record.definition_status = "unconfirmed"
    return True


def load_catalog(path: str | Path) -> Catalog:
    """Load a legacy extraction. Missing/invalid manifest raises CatalogError.

    Per-list statuses are ``complete`` (v2 only), ``unconfirmed``, ``missing``,
    ``not_exported``, ``error`` or ``identity_error``; unconfirmed does not assert completeness.
    Row data is intentionally omitted from dataclass representations.
    """
    root = Path(path)
    try:
        manifest = _read_json(root / "extraction_manifest.json", root)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CatalogError("Missing or invalid extraction manifest.") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("lists"), list):
        raise CatalogError("Invalid extraction manifest: lists must be an array.")
    catalog = Catalog(site_url=str(manifest.get("site_url") or ""), timestamp=str(manifest.get("timestamp") or ""))
    v2 = manifest.get("format_version") == 2
    if v2 and manifest.get("complete") is not True:
        catalog.issues.append(Issue("incomplete_export", "Extractor marked the export as incomplete."))
    entries = manifest["lists"]
    id_counts = Counter(normalize_guid(e.get("id")) for e in entries if isinstance(e, dict))
    title_counts = Counter(e.get("safe_title", "").casefold() for e in entries
                           if isinstance(e, dict) and _safe_title(e.get("safe_title")))
    options = manifest.get("options")
    include_data = options.get("include_data") if isinstance(options, dict) else None
    invalid_options = ((options is not None and not isinstance(options, dict))
                       or (include_data is not None and not isinstance(include_data, bool)))
    if invalid_options:
        catalog.issues.append(Issue("invalid_manifest_options", "Invalid manifest data-export option."))
    for entry in entries:
        if not isinstance(entry, dict):
            catalog.issues.append(Issue("invalid_manifest_entry", "Invalid manifest list entry."))
            continue
        list_id = normalize_guid(entry.get("id"))
        if not list_id or id_counts[list_id] != 1:
            catalog.issues.append(Issue("invalid_manifest_id", "Missing, invalid or duplicate list GUID.", list_id))
            continue
        record = ListRecord(id=list_id, title=str(entry.get("title") or ""))
        catalog.lists[list_id] = record
        safe = entry.get("safe_title")
        if not _safe_title(safe) or title_counts[safe.casefold()] != 1:
            record.definition_status = record.data_status = "identity_error"
            catalog.issues.append(Issue("ambiguous_path", "Unsafe or ambiguous manifest filename.", list_id))
            continue
        definition_path = root / f"10_lista_{safe}.json"
        try:
            definition = _read_json(definition_path, root)
        except FileNotFoundError:
            catalog.issues.append(Issue("missing_definition", "List definition is missing.", list_id))
            record.data_status = "identity_error"
            continue
        except (OSError, UnicodeError, json.JSONDecodeError):
            record.definition_status = "error"
            record.data_status = "identity_error"
            catalog.issues.append(Issue("invalid_definition", "Cannot read list definition.", list_id))
            continue
        if not _parse_definition(record, definition, catalog.issues):
            record.data_status = "identity_error"
            continue
        if v2:
            definition_info = entry.get("definition")
            if isinstance(definition_info, dict) and definition_info.get("status") == "complete":
                record.definition_status = "complete"
                if record.views_status == "unconfirmed":
                    record.views_status = "complete"
            else:
                catalog.issues.append(Issue("incomplete_definition", "Extractor reported definition errors.", list_id))
        if invalid_options:
            record.data_status = "error"
            continue
        if include_data is False:
            record.data_status = "not_exported"
            continue
        data_info = entry.get("data") if v2 else None
        data_state = data_info.get("status") if isinstance(data_info, dict) else None
        if v2 and data_state in {"not_exported", "not_applicable"}:
            record.data_status = "not_exported"
            continue
        if v2 and data_state not in {"complete", "incomplete"}:
            record.data_status = "error"
            catalog.issues.append(Issue("incomplete_data", "Extractor could not read list data.", list_id))
            continue
        try:
            rows = _read_json(root / f"20_dane_{safe}.json", root)
        except FileNotFoundError:
            catalog.issues.append(Issue("missing_data", "List data file is missing.", list_id))
            continue
        except (OSError, UnicodeError, json.JSONDecodeError):
            record.data_status = "error"
            catalog.issues.append(Issue("invalid_data", "Cannot read list data.", list_id))
            continue
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            record.data_status = "error"
            catalog.issues.append(Issue("invalid_data", "List data must be an array of objects.", list_id))
            continue
        record.rows = rows
        record.data_status = "unconfirmed"
        if data_state == "complete":
            _confirm_data(record, root, safe, data_info, catalog.issues)
        elif data_state == "incomplete":
            catalog.issues.append(Issue("incomplete_data", "Extractor reported incomplete list data.", list_id))
    return catalog


def _confirm_data(record: ListRecord, root: Path, safe: str, info: dict[str, Any], issues: list[Issue]) -> None:
    """Mark v2 data complete only if rows, IDs and the ETag file agree with the manifest."""
    ids = [row.get("ID") for row in record.rows or []]
    try:
        etags = _read_json(root / f"21_etagi_{safe}.json", root)
    except (OSError, UnicodeError, json.JSONDecodeError):
        etags = None
    valid = (
        isinstance(etags, dict)
        and info.get("rows") == len(ids) == info.get("item_count_after")
        and all(type(item_id) is int and item_id > 0 for item_id in ids)
        and len(set(ids)) == len(ids)
        and set(etags) == {str(item_id) for item_id in ids}
        and all(isinstance(value, str) and _ETAG_RE.fullmatch(value) for value in etags.values())
    )
    if not valid:
        record.data_status = "error"
        issues.append(Issue("inconsistent_export", "Data, ETag file and manifest disagree.", record.id))
        return
    record.row_etags = {int(key): value for key, value in etags.items()}
    record.data_status = "complete"
