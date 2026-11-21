"""Extraction orchestration logic for SharePoint 2019 artifacts."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any

from .client import SharePointClient, SharePointClientError
from .naming import sanitize_filename

logger = logging.getLogger(__name__)

EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
MANIFEST_FORMAT_VERSION = 2
# minimalmetadata keeps per-item ETags (nometadata drops them).
ITEMS_HEADERS = {"Accept": "application/json;odata=minimalmetadata"}
ITEMS_PAGE_SIZE = 5000
# Stay below the SharePoint default lookup column threshold (12).
LOOKUP_BATCH = 10
MAX_SELECT_CHARS = 1500
EXTERNAL_LIST_TEMPLATES = {600}
LOOKUP_TYPES = {"Lookup", "LookupMulti", "User", "UserMulti"}
_ETAG_RE = re.compile(r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]+"')
_DROP = object()
# SharePoint keeps disabled "(Previous Version: <date>)" associations after a republish;
# Nintex ExportWorkflow only serves published workflows ("Workflow not found").
_SUPERSEDED_RE = re.compile(r"\((?:previous version|poprzednia wersja)\s*:", re.IGNORECASE)
# File names in the NintexWorkflows library that may leak into the Title column.
_NINTEX_FILE_SUFFIXES = (".xoml.wfconfig.xml", ".xoml.rules", ".xoml", ".nwf")
PER_ITEM_FALLBACK_LIMIT = 2000

NINTEX_CATEGORY_MAP = {
    "list": "list",
    "site": "site",
    "reusable": "reusable",
    "globallyreusable": "globallyreusable",
}

WORKFLOW_TYPE_LABELS_PL = {
    "list": "Przepływ pracy listy",
    "site": "Przepływ pracy witryny",
    "reusable": "Szablon przepływu pracy wielokrotnego użytku",
    "globallyreusable": "Globalny szablon przepływu pracy wielokrotnego użytku",
}


def _normalize_guid(value: str | None) -> str:
    return str(value or "").strip().strip("{}").lower()


def _is_published_nintex_item(item: dict[str, Any]) -> bool:
    is_prod = item.get("IsProduction")
    if isinstance(is_prod, bool):
        return is_prod
    if isinstance(is_prod, (int, float)):
        return bool(is_prod)
    if isinstance(is_prod, str):
        return is_prod.strip().lower() in ("true", "1", "yes")
    return False


def _nintex_workflow_name(value: Any) -> str:
    """Return the workflow name without NintexWorkflows library file suffixes."""
    name = str(value or "").strip()
    for suffix in _NINTEX_FILE_SUFFIXES:
        if name.casefold().endswith(suffix):
            return name[: -len(suffix)].strip()
    return name


def _is_superseded_association(association: dict[str, Any], name: str) -> bool:
    return association.get("Enabled") is False and bool(_SUPERSEDED_RE.search(name))


def _expanded_lookup_ids(value: Any) -> Any:
    """Map an expanded lookup (``{"Id": n}`` or a list of those) to the ``<Field>Id`` layout."""
    if isinstance(value, dict) and isinstance(value.get("results"), list):
        value = value["results"]
    if isinstance(value, list):
        return [item.get("Id") if isinstance(item, dict) else item for item in value]
    if isinstance(value, dict):
        return value.get("Id")
    return value


def _save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def row_etag(row: dict[str, Any]) -> str | None:
    """Return the single valid item ETag from any OData format, else None."""
    candidates = [row[key] for key in ("odata.etag", "@odata.etag") if key in row]
    metadata = row.get("__metadata")
    if isinstance(metadata, dict) and "etag" in metadata:
        candidates.append(metadata["etag"])
    if (not candidates or any(value != candidates[0] for value in candidates)
            or not isinstance(candidates[0], str) or not _ETAG_RE.fullmatch(candidates[0])):
        return None
    return candidates[0]


def row_id(row: dict[str, Any]) -> int | None:
    value = row.get("ID", row.get("Id"))
    if type(value) is int and value > 0 and ("ID" not in row or "Id" not in row or row["ID"] == row["Id"]):
        return value
    return None


def _strip_transport(value: Any) -> Any:
    """Remove OData transport metadata so rows match the nometadata layout."""
    if isinstance(value, dict):
        if set(value) == {"__deferred"}:
            return _DROP
        if isinstance(value.get("results"), list) and set(value) <= {"results", "__metadata"}:
            return [_strip_transport(item) for item in value["results"]]
        cleaned = {}
        for key, item in value.items():
            if key == "__metadata" or key.startswith(("odata.", "@odata")) or "@odata." in key:
                continue
            item = _strip_transport(item)
            if item is not _DROP:
                cleaned[key] = item
        return cleaned
    if isinstance(value, list):
        return [_strip_transport(item) for item in value]
    return value


def _select_groups(fields: list[Any]) -> list[list[str]]:
    """Split item columns into requests within the lookup threshold and URL limits."""
    plain = ["ID", "FileSystemObjectType", "FileRef", "FileDirRef"]
    lookups: list[str] = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        name = str(field.get("EntityPropertyName") or field.get("InternalName") or "")
        field_type = str(field.get("TypeAsString") or "")
        if (not name or field.get("Hidden") is True or field_type == "Computed"
                or field.get("FieldRef") or field.get("IsDependentLookup") is True):
            continue
        if field_type in LOOKUP_TYPES:
            if field.get("FromBaseType") is True and name not in {"Author", "Editor"}:
                continue
            if f"{name}Id" not in lookups:
                lookups.append(f"{name}Id")
        elif name not in plain:
            plain.append(name)
    groups: list[list[str]] = []
    current: list[str] = []
    for name in plain:
        if current and len(",".join(current + [name])) > MAX_SELECT_CHARS:
            groups.append(current)
            current = ["ID"]
        current.append(name)
    groups.append(current)
    for start in range(0, len(lookups), LOOKUP_BATCH):
        groups.append(["ID", *lookups[start:start + LOOKUP_BATCH]])
    return groups


class SharePointExtractor:
    """Orchestrates extraction of SharePoint lists, columns, and Nintex workflows."""

    def __init__(
        self,
        client: SharePointClient,
        output_dir: Path | str,
        include_data: bool = False,
        include_permissions: bool = False,
    ) -> None:
        self.client = client
        self.output_dir = Path(output_dir)
        self.include_data = include_data
        self.include_permissions = include_permissions
        self.errors: list[dict[str, str]] = []

    def _error(self, resource: str, message: Any, list_id: str = "") -> None:
        entry = {"resource": resource, "message": str(message)}
        if list_id:
            entry["list_id"] = list_id
        self.errors.append(entry)
        logger.warning("Incomplete extraction - %s: %s", resource, message)

    def run(self) -> dict[str, Any]:
        """Execute full extraction workflow and return manifest summary.

        The manifest records every failed or unverified resource; ``complete`` is
        true only when all definitions, data pages, ETags and workflows were read.
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.errors = []
        start_time = datetime.now(timezone.utc).isoformat()
        logger.info("Starting extraction to %s", self.output_dir)
        if self.include_permissions:
            self._error("permissions", "Permission export is not implemented.")

        # 1. Site Metadata & Site Columns
        site_info = self._extract_site_metadata()
        site_title = site_info.get("Title", "SharePoint Site") if isinstance(site_info, dict) else "SharePoint Site"

        # 2. Lists & Definitions
        lists_summary, workflows_found, lists_by_id, nintex_library_id = self._extract_lists_and_definitions()

        # 3. Site-level workflows
        site_workflows = self._extract_site_workflows()
        workflows_found = self._merge_workflows(workflows_found, site_workflows)

        # 4. NintexWorkflows hidden library (Reusable, GloballyReusable, Site, List published)
        library_workflows = self._extract_nintex_workflow_library(nintex_library_id, lists_by_id)
        workflows_found = self._merge_workflows(workflows_found, library_workflows)

        # 5. Export Nintex .nwf files
        exported_nwf = self._export_workflows(workflows_found)

        # 6. Write Workflow-Inventory.csv
        self._write_workflow_inventory(workflows_found, site_title)

        # 6. Write manifest
        data_ok = {"complete", "not_exported", "not_applicable"}
        complete = not self.errors and all(
            entry.get("definition", {}).get("status") == "complete"
            and entry.get("data", {}).get("status") in data_ok
            for entry in lists_summary
        ) and all(wf.get("status") in {"exported", "superseded"} for wf in exported_nwf)
        manifest = {
            "format_version": MANIFEST_FORMAT_VERSION,
            "timestamp": start_time,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "complete": complete,
            "errors": self.errors,
            "site_url": self.client.base_url,
            "site_title": site_title,
            "output_directory": str(self.output_dir.resolve()),
            "lists_count": len(lists_summary),
            "lists": lists_summary,
            "workflows_count": len(workflows_found),
            "workflows": exported_nwf,
            "options": {
                "include_data": self.include_data,
                "include_permissions": self.include_permissions,
            },
        }
        _save_json(self.output_dir / "extraction_manifest.json", manifest)
        if complete:
            logger.info("Extraction finished: complete. Manifest saved.")
        else:
            logger.warning("Extraction finished INCOMPLETE (%d errors). Manifest saved.", len(self.errors))
        return manifest

    def _extract_site_metadata(self) -> dict[str, Any]:
        logger.info("Fetching site metadata and site columns...")
        site_info: dict[str, Any] = {}
        try:
            site_info = self.client.get("_api/web?$select=Title,Url,ServerRelativeUrl,WebTemplate,Created")  # type: ignore
            _save_json(self.output_dir / "00_wlasciwosci.json", site_info)
        except Exception as e:
            self._error("site_properties", e)

        try:
            site_columns = self.client.get_all("_api/web/fields?$select=*&$filter=Hidden eq false")
            _save_json(self.output_dir / "00_kolumny_witryny.json", site_columns)
        except Exception as e:
            self._error("site_columns", e)

        return site_info

    def _extract_lists_and_definitions(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str], str | None]:
        logger.info("Fetching list catalog (10_00_wszystkie_listy.json)...")
        all_lists = self.client.get_all("_api/web/lists?$select=*")
        _save_json(self.output_dir / "10_00_wszystkie_listy.json", all_lists)

        lists_summary: list[dict[str, Any]] = []
        workflows_found: list[dict[str, Any]] = []
        lists_by_id: dict[str, str] = {}
        nintex_library_id: str | None = None

        for item in all_lists:
            list_id = item.get("Id", "")
            title = item.get("Title", "")
            if not list_id or not title:
                self._error("list_catalog", f"List entry without Id or Title: {list_id or title!r}")
                continue

            norm_id = _normalize_guid(list_id)
            lists_by_id[norm_id] = title
            if item.get("BaseTemplate") == 5001 or title.strip().casefold() == "nintexworkflows":
                nintex_library_id = list_id

            safe_title = sanitize_filename(title)
            entry: dict[str, Any] = {"id": list_id, "title": title, "safe_title": safe_title}
            lists_summary.append(entry)
            logger.info("Extracting list definition: '%s' (%s)", title, list_id)
            definition_errors: list[str] = []

            g_url = f"_api/web/lists(guid'{list_id}')"
            try:
                # SchemaXml
                schema_xml = ""
                try:
                    schema_res = self.client.get(f"{g_url}?$select=SchemaXml")
                    if isinstance(schema_res, dict) and isinstance(schema_res.get("SchemaXml"), str):
                        schema_xml = schema_res["SchemaXml"]
                    else:
                        definition_errors.append("SchemaXml: unexpected response")
                except Exception as e:
                    definition_errors.append(f"SchemaXml: {e}")

                # Columns
                kolumny = self.client.get_all(f"{g_url}/fields?$select=*")

                # Content types
                typy_zawartosci = self.client.get_all(f"{g_url}/contenttypes?$expand=Fields")

                # Views
                widoki = self.client.get_all(f"{g_url}/views?$select=*")
                for v in widoki:
                    vid = v.get("Id")
                    if vid:
                        try:
                            vf = self.client.get(f"{g_url}/views(guid'{vid}')/viewfields")
                            if not isinstance(vf, dict) or not isinstance(vf.get("Items"), list):
                                raise SharePointClientError("unexpected viewfields response")
                            v["KolumnyWidoku"] = vf["Items"]
                        except Exception as e:
                            v["KolumnyWidoku"] = f"błąd: {e}"
                            definition_errors.append(f"View {vid} fields: {e}")

                # Forms & Event Receivers
                formularze = self.client.get_all(f"{g_url}/forms")
                event_receivers = self.client.get_all(f"{g_url}/eventreceivers")

                # Workflow associations
                workflowy = self.client.get_all(f"{g_url}/workflowassociations")
                for wf in workflowy:
                    wf_name = wf.get("Name")
                    if wf_name:
                        workflows_found.append({
                            "workflow_name": wf_name,
                            "list_name": title,
                            "list_id": list_id,
                            "workflow_type": "list",
                            "workflow_id": wf.get("Id", ""),
                            "enabled": wf.get("Enabled", True),
                            "superseded": _is_superseded_association(wf, wf_name),
                        })

                list_def = {
                    "lista": item,
                    "schemaXml": schema_xml,
                    "kolumny": kolumny,
                    "typyZawartosci": typy_zawartosci,
                    "widoki": widoki,
                    "formularze": formularze,
                    "eventReceivers": event_receivers,
                    "workflowy": workflowy,
                }
                _save_json(self.output_dir / f"10_lista_{safe_title}.json", list_def)

            except Exception as e:
                definition_errors.append(str(e))
                kolumny = None

            entry["definition"] = {
                "status": "error" if definition_errors else "complete",
                "errors": definition_errors,
            }
            for message in definition_errors:
                self._error("list_definition", message, list_id)

            if not self.include_data:
                entry["data"] = {"status": "not_exported"}
            elif item.get("BaseTemplate") in EXTERNAL_LIST_TEMPLATES:
                entry["data"] = {"status": "not_applicable", "reason": "External list (BCS)"}
            elif kolumny is None:
                entry["data"] = {"status": "error", "errors": ["List definition could not be read."]}
                self._error("list_data", "List definition could not be read.", list_id)
            else:
                entry["data"] = self._extract_list_items(item, g_url, safe_title, kolumny)
                for message in entry["data"].get("errors", []):
                    self._error("list_data", message, list_id)

        return lists_summary, workflows_found, lists_by_id, nintex_library_id

    @staticmethod
    def _merge_workflows(
        primary: list[dict[str, Any]], secondary: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Merge workflow lists while deduplicating by (workflow_type, workflow_name, list_id)."""
        merged: list[dict[str, Any]] = list(primary)
        index: dict[tuple[str, str, str], dict[str, Any]] = {}
        for wf in merged:
            key = (
                str(wf.get("workflow_type") or "").strip().casefold(),
                str(wf.get("workflow_name") or "").strip().casefold(),
                _normalize_guid(wf.get("list_id", "")),
            )
            index[key] = wf

        for wf in secondary:
            key = (
                str(wf.get("workflow_type") or "").strip().casefold(),
                str(wf.get("workflow_name") or "").strip().casefold(),
                _normalize_guid(wf.get("list_id", "")),
            )
            existing = index.get(key)
            if existing is None:
                merged.append(wf)
                index[key] = wf
            else:
                if not existing.get("workflow_id") and wf.get("workflow_id"):
                    existing["workflow_id"] = wf["workflow_id"]
                if not existing.get("associated_content_type") and wf.get("associated_content_type"):
                    existing["associated_content_type"] = wf["associated_content_type"]
        return merged

    def _extract_nintex_workflow_library(
        self, nintex_library_id: str | None, lists_by_id: dict[str, str]
    ) -> list[dict[str, Any]]:
        """Fetch published Nintex workflows (List, Site, Reusable, GloballyReusable) from NintexWorkflows."""
        logger.info("Checking NintexWorkflows hidden library for published workflows...")
        select_cols = (
            "Title,FileLeafRef,NintexWorkflowID,WorkflowCategory,"
            "AssociatedListID,AssociatedContentType,IsProduction,Modified"
        )
        endpoint = (
            f"_api/web/lists(guid'{nintex_library_id}')/items?$top=5000&$select={select_cols}"
            if nintex_library_id
            else f"_api/web/lists/getbytitle('NintexWorkflows')/items?$top=5000&$select={select_cols}"
        )
        try:
            items = self.client.get_all(endpoint)
        except Exception as e:
            if nintex_library_id:
                self._error("nintex_workflow_library", e)
            else:
                logger.info("NintexWorkflows library not found on this site: %s", e)
            return []

        found: list[dict[str, Any]] = []
        for item in items:
            if not _is_published_nintex_item(item):
                continue
            raw_cat = str(item.get("WorkflowCategory") or "").strip()
            wf_type = NINTEX_CATEGORY_MAP.get(raw_cat.casefold())
            if not wf_type:
                continue

            wf_name = _nintex_workflow_name(item.get("Title"))
            if not wf_name:
                leaf = str(item.get("FileLeafRef") or "").strip()
                wf_name = _nintex_workflow_name(leaf)
                if wf_name == leaf:
                    wf_name = Path(leaf).stem
            if not wf_name:
                continue

            assoc_list_id = _normalize_guid(item.get("AssociatedListID"))
            if assoc_list_id and assoc_list_id != EMPTY_GUID and wf_type == "list":
                list_id = assoc_list_id
                list_name = lists_by_id.get(assoc_list_id, "")
            else:
                list_id = ""
                list_name = ""

            found.append({
                "workflow_name": wf_name,
                "list_name": list_name,
                "list_id": list_id,
                "workflow_type": wf_type,
                "workflow_id": _normalize_guid(item.get("NintexWorkflowID")),
                "associated_content_type": str(item.get("AssociatedContentType") or "").strip(),
                "enabled": True,
            })

        return found

    def _extract_site_workflows(self) -> list[dict[str, Any]]:
        logger.info("Checking for site-level workflow associations...")
        site_wfs: list[dict[str, Any]] = []
        try:
            wfs = self.client.get_all("_api/web/workflowassociations")
            for wf in wfs:
                name = wf.get("Name")
                if name:
                    site_wfs.append({
                        "workflow_name": name,
                        "list_name": "",
                        "list_id": "",
                        "workflow_type": "site",
                        "workflow_id": wf.get("Id", ""),
                        "enabled": wf.get("Enabled", True),
                    })
        except Exception as e:
            self._error("site_workflow_associations", e)
        return site_wfs

    def _item_count(self, g_url: str) -> int:
        info = self.client.get(f"{g_url}?$select=ItemCount")
        count = info.get("ItemCount") if isinstance(info, dict) else None
        if type(count) is not int or count < 0:
            raise SharePointClientError("Missing or invalid ItemCount.")
        return count

    def _read_items_chunked(
        self, g_url: str, fields: list[Any],
    ) -> tuple[list[dict[str, Any]], int, list[str], list[str]]:
        """Read columns in groups and merge by ID; any drift between groups is an error.

        A failing group is split until the failing column is isolated, so one column the
        server cannot render does not hide the rest of the list. Returns
        ``(rows, pages, notes, errors)``; ``errors`` name columns/items left unread.
        """
        merged: dict[int, dict[str, Any]] = {}
        etags: dict[int, str | None] = {}
        pages = 0
        notes: list[str] = []
        errors: list[str] = []
        failed: list[tuple[str, Exception]] = []
        initialized = False

        def merge(rows: list[dict[str, Any]]) -> None:
            nonlocal initialized
            first = not initialized
            initialized = True
            seen: set[int] = set()
            for row in rows:
                item_id = row_id(row)
                if item_id is None or item_id in seen:
                    raise SharePointClientError("Missing, invalid or duplicate item ID in chunked read.")
                seen.add(item_id)
                if first:
                    merged[item_id] = dict(row)
                    etags[item_id] = row_etag(row)
                elif item_id not in merged or row_etag(row) != etags[item_id]:
                    raise SharePointClientError("Items changed between chunked reads (ID set or ETag differs).")
                else:
                    merged[item_id].update(row)
            if seen != set(merged):
                raise SharePointClientError("Items changed between chunked reads (ID set differs).")

        pending = _select_groups(fields)
        while pending:
            group = pending.pop(0)
            try:
                rows, read_pages = self.client.get_all_pages(
                    f"{g_url}/items?$top={ITEMS_PAGE_SIZE}&$select={','.join(group)}", headers=ITEMS_HEADERS,
                )
            except SharePointClientError as e:
                columns = [name for name in group if name != "ID"]
                if len(columns) > 1:
                    half = len(columns) // 2
                    pending[:0] = [["ID", *columns[:half]], ["ID", *columns[half:]]]
                elif columns:
                    failed.append((columns[0], e))
                else:
                    raise
                continue
            pages += read_pages
            merge(rows)

        if failed and not initialized:
            raise SharePointClientError(f"No column group could be read: {failed[0][1]}")
        by_column = {
            f"{field.get('EntityPropertyName') or field.get('InternalName')}Id": field
            for field in fields
            if isinstance(field, dict) and str(field.get("TypeAsString") or "") in LOOKUP_TYPES
        }
        for column, error in failed:
            count_before = len(errors)
            pages += self._read_column_fallback(g_url, column, error, merged, etags, notes, errors)
            if len(errors) > count_before and column in by_column:
                diagnosis = self._lookup_diagnosis(by_column[column])
                if diagnosis:
                    errors[-1] += f" Diagnosis: {diagnosis}"
        return [merged[key] for key in sorted(merged)], pages, notes, errors

    def _lookup_diagnosis(self, field: dict[str, Any]) -> str:
        """Explain an unreadable lookup when its display field is gone from the target list."""
        list_id = _normalize_guid(field.get("LookupList"))
        show_field = str(field.get("LookupField") or "")
        if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", list_id) or not show_field:
            return ""
        escaped = show_field.replace("'", "''")
        try:
            self.client.get(
                f"_api/web/lists(guid'{list_id}')/fields/getbyinternalnameortitle('{escaped}')?$select=InternalName"
            )
        except SharePointClientError as e:
            if "HTTP 404" not in str(e):
                return ""
            return (f"lookup display field '{show_field}' (or list {list_id}) no longer exists in this site; "
                    f"repoint the lookup column in SharePoint (ShowField) to an existing field.")
        return ""

    def _read_column_fallback(
        self, g_url: str, column: str, error: Exception,
        merged: dict[int, dict[str, Any]], etags: dict[int, str | None],
        notes: list[str], errors: list[str],
    ) -> int:
        """Recover one column the server refuses to project; return pages read."""
        notes.append(f"Column '{column}' failed in a group read: {error}")
        if column.endswith("Id"):
            # Lookup projection ``<Field>Id`` can fail on malformed values while $expand works.
            base = column[:-2]
            try:
                rows, read_pages = self.client.get_all_pages(
                    f"{g_url}/items?$top={ITEMS_PAGE_SIZE}&$select=ID,{base}/Id&$expand={base}",
                    headers=ITEMS_HEADERS,
                )
                values: dict[int, Any] = {}
                for row in rows:
                    item_id = row_id(row)
                    if item_id is None or item_id not in merged or item_id in values:
                        raise SharePointClientError("Unexpected item ID in expanded lookup read.")
                    if row_etag(row) != etags[item_id]:
                        raise SharePointClientError("Items changed between chunked reads (ETag differs).")
                    values[item_id] = _expanded_lookup_ids(row.get(base))
                if set(values) != set(merged):
                    raise SharePointClientError("Items changed between chunked reads (ID set differs).")
            except SharePointClientError as e:
                notes.append(f"Column '{column}' $expand fallback failed: {e}")
            else:
                for item_id, value in values.items():
                    merged[item_id][column] = value
                notes.append(f"Column '{column}' read via $expand={base}.")
                return read_pages

        if len(merged) > PER_ITEM_FALLBACK_LIMIT:
            errors.append(f"Column '{column}' could not be read ({len(merged)} items exceed the "
                          f"per-item fallback limit {PER_ITEM_FALLBACK_LIMIT}): {error}")
            return 0
        bad: list[int] = []
        first_error = ""
        for item_id in sorted(merged):
            try:
                row = self.client.get(f"{g_url}/items({item_id})?$select=ID,{column}", headers=ITEMS_HEADERS)
                if not isinstance(row, dict) or row_id(row) != item_id or column not in row:
                    raise SharePointClientError("unexpected item response")
            except SharePointClientError as e:
                bad.append(item_id)
                first_error = first_error or str(e)
                continue
            if row_etag(row) != etags[item_id]:
                raise SharePointClientError("Items changed between chunked reads (ETag differs).")
            merged[item_id][column] = row[column]
        if bad:
            shown = ", ".join(map(str, bad[:50])) + (" ..." if len(bad) > 50 else "")
            errors.append(f"Column '{column}' unreadable on the server for {len(bad)} item(s) "
                          f"(IDs: {shown}); value omitted. First error: {first_error}")
        else:
            notes.append(f"Column '{column}' read item by item ({len(merged)} requests).")
        return 0

    def _extract_list_items(
        self, list_item: dict[str, Any], g_url: str, safe_title: str, fields: list[Any],
    ) -> dict[str, Any]:
        """Read all list items with ETags and return the manifest data entry."""
        title = list_item.get("Title", "")
        logger.info("Extracting row data for list '%s'...", title)
        info: dict[str, Any] = {"status": "error", "read_mode": "select_all", "errors": [], "notes": []}
        try:
            before = self._item_count(g_url)
            try:
                rows, pages = self.client.get_all_pages(
                    f"{g_url}/items?$top={ITEMS_PAGE_SIZE}&$select=*,FileRef,FileDirRef", headers=ITEMS_HEADERS,
                )
            except SharePointClientError as e:
                # Typically the lookup column threshold; retry in column groups.
                info["notes"].append(f"$select=* failed, using column groups: {e}")
                info["read_mode"] = "chunked"
                rows, pages, notes, column_errors = self._read_items_chunked(g_url, fields)
                info["notes"].extend(notes)
                info["errors"].extend(column_errors)
            after = self._item_count(g_url)
        except Exception as e:
            info["errors"].append(str(e))
            return info

        ids = [row_id(row) for row in rows]
        etags = {str(item_id): row_etag(row) for item_id, row in zip(ids, rows) if item_id is not None}
        cleaned = [_strip_transport(row) for row in rows]
        missing_ids = sum(item_id is None for item_id in ids)
        duplicates = len(ids) - missing_ids - len({item_id for item_id in ids if item_id is not None})
        missing_etags = sum(value is None for value in etags.values())
        if missing_ids or duplicates:
            info["errors"].append(f"Invalid or duplicate item IDs: {missing_ids} invalid, {duplicates} duplicates.")
        if missing_etags:
            info["errors"].append(f"{missing_etags} items without a valid ETag.")
        if before != after:
            info["errors"].append(f"ItemCount changed during read: {before} -> {after}.")
        elif len(rows) != after:
            info["errors"].append(f"Read {len(rows)} items but ItemCount is {after}.")

        _save_json(self.output_dir / f"20_dane_{safe_title}.json", cleaned)
        _save_json(self.output_dir / f"21_etagi_{safe_title}.json",
                   {key: value for key, value in etags.items() if value is not None})
        info.update({
            "status": "incomplete" if info["errors"] else "complete",
            "rows": len(rows),
            "pages": pages,
            "item_count_before": before,
            "item_count_after": after,
            "data_file": f"20_dane_{safe_title}.json",
            "etag_file": f"21_etagi_{safe_title}.json",
        })
        return info

    def _export_workflows(self, workflows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        logger.info("Exporting %d workflow definitions (.nwf)...", len(workflows))
        results: list[dict[str, Any]] = []
        used_filenames: set[str] = set()

        for wf in workflows:
            wf_name = wf["workflow_name"]
            list_name = wf.get("list_name", "")
            wf_type = wf.get("workflow_type", "list")

            # Determine unique filename
            safe_wf = sanitize_filename(wf_name)
            base_fname = f"{safe_wf}.nwf"
            if base_fname in used_filenames and list_name:
                base_fname = f"{sanitize_filename(list_name)}__{safe_wf}.nwf"
            if base_fname in used_filenames:
                base_fname = f"{safe_wf}_{len(used_filenames) + 1}.nwf"
            used_filenames.add(base_fname)

            target_path = self.output_dir / base_fname
            record: dict[str, Any] = {
                "workflow_name": wf_name,
                "list_name": list_name,
                "workflow_type": wf_type,
                "filename": base_fname,
                "status": "pending",
            }

            if wf.get("superseded"):
                record["status"] = "superseded"
                record["reason"] = "Disabled previous version; Nintex exports only published workflows."
                results.append(record)
                continue

            try:
                nwf_xml = self.client.export_nintex_workflow(
                    workflow_name=wf_name,
                    list_name=list_name,
                    workflow_type=wf_type,
                )
                target_path.write_text(nwf_xml, encoding="utf-8")
                record["status"] = "exported"
                record["bytes"] = len(nwf_xml.encode("utf-8"))
                logger.info("Successfully exported workflow '%s' -> %s", wf_name, base_fname)
            except Exception as e:
                record["status"] = "failed"
                record["error"] = str(e)
                self._error("nintex_workflow_export", f"{wf_name}: {e}")

            results.append(record)

        return results

    def _write_workflow_inventory(self, workflows: list[dict[str, Any]], site_title: str) -> None:
        csv_path = self.output_dir / "Workflow-Inventory.csv"
        headers = [
            "Zbiór witryn",
            "Nazwa witryny",
            "Nazwa listy",
            "Nazwa przepływu pracy",
            "Rodzaj przepływu pracy",
            "Zmodyfikowane przez",
            "Zmodyfikowane",
            "Wersja",
            "Ostatnia zapisana wersja",
            "WebApplicationId",
            "SiteId",
            "Adres URL witryny",
            "WorkflowUrl",
            "WorkflowId",
            "ListId",
            "ListUrl",
            "Liczba dni od ostatniej modyfikacji",
        ]

        with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(headers)
            for wf in workflows:
                wf_type_key = str(wf.get("workflow_type") or "").strip().casefold()
                wf_type_pl = WORKFLOW_TYPE_LABELS_PL.get(wf_type_key, wf.get("workflow_type", ""))
                writer.writerow([
                    self.client.base_url,
                    site_title,
                    wf.get("list_name", ""),
                    wf.get("workflow_name", ""),
                    wf_type_pl,
                    "",  # Zmodyfikowane przez
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "1.0",
                    "1.0",
                    "",
                    "",
                    self.client.base_url,
                    "",
                    wf.get("workflow_id", ""),
                    wf.get("list_id", ""),
                    "",
                    "0",
                ])
        logger.info("Saved workflow inventory: %s", csv_path.name)

