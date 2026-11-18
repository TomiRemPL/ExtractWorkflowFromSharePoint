"""Extraction orchestration logic for SharePoint 2019 artifacts."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any

from .client import SharePointClient, SharePointClientError
from .naming import sanitize_filename

logger = logging.getLogger(__name__)

EMPTY_GUID = "00000000-0000-0000-0000-000000000000"

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


def _save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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

    def run(self) -> dict[str, Any]:
        """Execute full extraction workflow and return manifest summary."""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        start_time = datetime.now(timezone.utc).isoformat()
        logger.info("Starting extraction to %s", self.output_dir)

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
        manifest = {
            "timestamp": start_time,
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
        logger.info("Extraction finished successfully. Manifest saved.")
        return manifest

    def _extract_site_metadata(self) -> dict[str, Any]:
        logger.info("Fetching site metadata and site columns...")
        site_info: dict[str, Any] = {}
        try:
            site_info = self.client.get("_api/web?$select=Title,Url,ServerRelativeUrl,WebTemplate,Created")  # type: ignore
            _save_json(self.output_dir / "00_wlasciwosci.json", site_info)
        except Exception as e:
            logger.warning("Could not fetch site properties: %s", e)

        try:
            site_columns = self.client.get_all("_api/web/fields?$select=*&$filter=Hidden eq false")
            _save_json(self.output_dir / "00_kolumny_witryny.json", site_columns)
        except Exception as e:
            logger.warning("Could not fetch site columns: %s", e)

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
                continue

            norm_id = _normalize_guid(list_id)
            lists_by_id[norm_id] = title
            if item.get("BaseTemplate") == 5001 or title.strip().casefold() == "nintexworkflows":
                nintex_library_id = list_id

            safe_title = sanitize_filename(title)
            lists_summary.append({"id": list_id, "title": title, "safe_title": safe_title})
            logger.info("Extracting list definition: '%s' (%s)", title, list_id)

            g_url = f"_api/web/lists(guid'{list_id}')"
            try:
                # SchemaXml
                schema_xml = ""
                try:
                    schema_res = self.client.get(f"{g_url}?$select=SchemaXml")
                    if isinstance(schema_res, dict):
                        schema_xml = schema_res.get("SchemaXml", "")
                except Exception as e:
                    logger.debug("Failed to get SchemaXml for %s: %s", title, e)

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
                            v["KolumnyWidoku"] = vf.get("Items", []) if isinstance(vf, dict) else []
                        except Exception as e:
                            v["KolumnyWidoku"] = f"błąd: {e}"

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

                # Optional row data extraction
                if self.include_data and item.get("BaseTemplate") != 600:
                    self._extract_list_items(item, g_url, safe_title)

            except Exception as e:
                logger.warning("Error extracting list '%s': %s", title, e)

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
            logger.debug("Could not fetch NintexWorkflows library: %s", e)
            return []

        found: list[dict[str, Any]] = []
        for item in items:
            if not _is_published_nintex_item(item):
                continue
            raw_cat = str(item.get("WorkflowCategory") or "").strip()
            wf_type = NINTEX_CATEGORY_MAP.get(raw_cat.casefold())
            if not wf_type:
                continue

            wf_name = str(item.get("Title") or "").strip()
            if not wf_name:
                leaf = str(item.get("FileLeafRef") or "").strip()
                wf_name = Path(leaf).stem if leaf else ""
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
            logger.debug("Could not fetch site workflows: %s", e)
        return site_wfs

    def _extract_list_items(self, list_item: dict[str, Any], g_url: str, safe_title: str) -> None:
        title = list_item.get("Title", "")
        if title in ("NintexWorkflowHistory", "Workflow History", "Historia przepływu pracy"):
            return
        logger.info("Extracting row data for list '%s'...", title)
        try:
            items = self.client.get_all(f"{g_url}/items?$top=5000&$select=*,FileRef,FileDirRef")
            _save_json(self.output_dir / f"20_dane_{safe_title}.json", items)
        except Exception as e:
            logger.warning("Failed to extract data for list '%s': %s", title, e)

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
                logger.warning("Failed to export .nwf for '%s': %s", wf_name, e)

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

