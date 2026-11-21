"""Selective, GET-only reads for automation previews; no SharePoint writer."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit
from uuid import uuid4

import requests

from tools.sp_extractor.client import SharePointClient
from .catalog import Catalog, ListRecord, _parse_definition, normalize_guid
from .engine import SimulationResult, preview_is_current, simulate
from .models import Graph
from .snapshot_adapter import (
    SnapshotAdapterError, _field_by_id, _field_metadata, _fingerprint,
    _graph_requirements, _rows, _site_key,
)
from .views import ViewScopeError, evaluate_view, parse_view_query


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class ResourceRead:
    resource: str
    started_at: str
    finished_at: str
    status: str
    pages: int
    records: int
    pagination_complete: bool
    error: str = ""


class OnlineReadError(ValueError):
    """A read failed; resource diagnostics are available, but no usable snapshot."""

    def __init__(self, message: str, resources: tuple[ResourceRead, ...] = ()) -> None:
        super().__init__(message)
        self.resources = resources


@dataclass(frozen=True)
class OnlineSnapshot:
    payload_json: str
    resources: tuple[ResourceRead, ...]

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.payload_json)


@dataclass(frozen=True)
class OnlinePreview:
    run_id: str
    created_at: str
    graph_json: str
    snapshot: OnlineSnapshot
    result_json: str

    def to_dict(self) -> dict[str, Any]:
        """Return a detached copy, never mutable state used by this preview."""
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "graph": json.loads(self.graph_json),
            "snapshot": self.snapshot.to_dict(),
            "result": json.loads(self.result_json),
            "resources": [asdict(resource) for resource in self.snapshot.resources],
            "write_available": False,
        }

    @property
    def digests(self) -> tuple[str, str]:
        """(graph_digest, snapshot_digest) binding this preview to exact inputs."""
        result = json.loads(self.result_json)
        return result["graph_digest"], result["snapshot_digest"]

    def is_current(self, graph: Graph, snapshot: OnlineSnapshot) -> bool:
        result = json.loads(self.result_json)
        comparison = SimulationResult(
            (), (), result["graph_digest"], result["snapshot_digest"], True,
        )
        return preview_is_current(comparison, graph, _content(snapshot.to_dict()))


def _content(data: dict[str, Any]) -> dict[str, Any]:
    """Snapshot content used for digests; read timestamps do not change the data."""
    return {key: value for key, value in data.items() if key not in {"started_at", "finished_at"}}


def build_online_preview(graph: Graph, snapshot: OnlineSnapshot) -> OnlinePreview:
    """Calculate an immutable read-only proposal, not an approval to write."""
    data = snapshot.to_dict()
    if data.get("origin") != "online" or not snapshot.resources or any(
        resource.status != "success" or not resource.pagination_complete
        for resource in snapshot.resources
    ):
        raise OnlineReadError("Online preview requires successful, complete reads.")
    if data.get("scope") != graph.to_dict()["scope"]:
        raise OnlineReadError("Preview scope differs from the read scope.")
    for record in data["lists"].values():
        for row in record["items"]:
            _etag({"odata.etag": record["etags"].get(str(row["ID"]))})
    result = simulate(graph, _content(data))
    return OnlinePreview(str(uuid4()), _now(), graph.to_json(), snapshot, _json(asdict(result)))


def _etag(row: dict[str, Any]) -> str:
    metadata = row.get("__metadata")
    candidates = [row[key] for key in ("odata.etag", "@odata.etag") if key in row]
    if isinstance(metadata, dict) and "etag" in metadata:
        candidates.append(metadata["etag"])
    if (not candidates or any(value != candidates[0] for value in candidates)
            or not isinstance(candidates[0], str)
            or not re.fullmatch(r'(?:W/)?"[\x21\x23-\x7e\x80-\xff]+"', candidates[0])):
        raise OnlineReadError("Missing, conflicting or invalid item ETag.")
    return candidates[0]


class SharePointReader:
    """Use existing authentication with strict TLS, proxy and pagination checks."""

    def __init__(self, client: SharePointClient, *, max_pages: int = 1000,
                 max_items: int = 100_000) -> None:
        if (type(max_pages) is not int or max_pages <= 0
                or type(max_items) is not int or max_items <= 0):
            raise OnlineReadError("Read limits must be positive integers.")
        site = _site_key(client.base_url)
        if site[0] != "https" or client.session.verify is False:
            raise OnlineReadError("Online automation reads require HTTPS and TLS verification.")
        self.client = client
        self.max_pages = max_pages
        self.max_items = max_items
        self.resources: list[ResourceRead] = []

    def _get(self, url: str, params: dict[str, str] | None = None) -> Any:
        try:
            response = self.client.session.get(
                url, params=params, headers={"Accept": "application/json;odata=verbose"},
                timeout=self.client.timeout, allow_redirects=False,
                verify=self.client.session.verify,
                proxies={"http": "http://127.0.0.1:3001", "https": "http://127.0.0.1:3001"},
            )
            if response.status_code != 200:
                raise OnlineReadError(f"GET failed: HTTP {response.status_code}.")
            return response.json()
        except requests.RequestException as exc:
            raise OnlineReadError("GET failed: transport or JSON response error.") from exc
        except ValueError as exc:
            if isinstance(exc, OnlineReadError):
                raise
            raise OnlineReadError("GET returned invalid JSON.") from exc

    def _url(self, path: str) -> str:
        return f"{self.client.base_url}/{path}"

    def _next(self, value: Any, current: str, endpoint: str) -> str:
        if (not isinstance(value, str) or not value.strip() or "\\" in value
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            raise OnlineReadError("Invalid pagination link.")
        try:
            url = urljoin(current, value)
            parsed, expected = urlsplit(url), urlsplit(endpoint)
        except ValueError as exc:
            raise OnlineReadError("Invalid pagination URL.") from exc
        if (parsed.scheme != expected.scheme or parsed.netloc.lower() != expected.netloc.lower()
                or parsed.username or parsed.password or parsed.fragment
                or unquote(parsed.path) != unquote(expected.path)):
            raise OnlineReadError("Pagination link left the requested site or resource.")
        return url

    def _read(self, path: str, params: dict[str, str], *, collection: bool) -> Any:
        started = _now()
        pages, count, complete = 0, 0, False
        endpoint = self._url(path)
        url = endpoint
        seen = set()
        items: list[dict[str, Any]] = []
        try:
            while True:
                prepared = requests.Request("GET", url, params=params).prepare().url
                if prepared in seen or pages >= self.max_pages:
                    raise OnlineReadError("Pagination loop or page limit exceeded.")
                seen.add(prepared)
                data = self._get(url, params)
                pages += 1
                if not isinstance(data, dict):
                    raise OnlineReadError("Invalid OData object.")
                body = data.get("d", data)
                if not isinstance(body, dict):
                    raise OnlineReadError("Invalid OData envelope.")
                if not collection:
                    if "results" in body or "value" in body:
                        raise OnlineReadError("Expected one object, not a collection.")
                    count, complete = 1, True
                    return body
                key = "results" if "d" in data else "value"
                page = body.get(key)
                if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                    raise OnlineReadError("Invalid OData collection.")
                items.extend(page)
                count += len(page)
                if count > self.max_items:
                    raise OnlineReadError("Read item limit exceeded; data was not truncated.")
                links = [body[key] for key in ("__next", "odata.nextLink", "@odata.nextLink")
                         if key in body]
                if not links:
                    complete = True
                    return items
                if any(link != links[0] for link in links):
                    raise OnlineReadError("Conflicting pagination links.")
                url = self._next(links[0], url, endpoint)
                params = {}
        except OnlineReadError as exc:
            self.resources.append(ResourceRead(
                path, started, _now(), "partial" if count else "failed",
                pages, count, False, str(exc),
            ))
            raise OnlineReadError(str(exc), tuple(self.resources)) from exc
        finally:
            if complete:
                self.resources.append(ResourceRead(
                    path, started, _now(), "success", pages, count, True,
                ))

    def _definition(self, list_id: str) -> ListRecord:
        path = f"_api/web/lists(guid'{list_id}')"
        info = self._read(path, {
            "$select": "Id,Title,ItemCount,SchemaXml,ListItemEntityTypeFullName,"
                       "ValidationFormula,ValidationMessage,EnableVersioning,"
                       "EffectiveBasePermissions,RootFolder/ServerRelativeUrl",
            "$expand": "RootFolder",
        }, collection=False)
        if (normalize_guid(info.get("Id")) != list_id or not isinstance(info.get("Title"), str)
                or type(info.get("ItemCount")) is not int or info["ItemCount"] < 0
                or not isinstance(info.get("SchemaXml"), str) or not info["SchemaXml"]):
            raise OnlineReadError("List identity, schema or ItemCount is missing or invalid.")
        fields = self._read(f"{path}/fields", {"$select": "*"}, collection=True)
        # REST transport metadata must not affect the schema fingerprint.
        fields = [{key: value for key, value in field.items()
                   if key not in {"__metadata", "odata.metadata", "@odata.context"}}
                  for field in fields]
        record = ListRecord(list_id, info["Title"])
        issues = []
        if not _parse_definition(record, {
            "lista": info, "schemaXml": info["SchemaXml"], "kolumny": fields, "widoki": [],
        }, issues) or any(issue.severity == "error" for issue in issues):
            raise OnlineReadError("Fresh list schema is invalid or ambiguous.")
        record.definition_status = "complete"
        schema = {
            "fields_and_schema": record.schema_fingerprint,
            "list": {key: info.get(key) for key in (
                "Id", "ListItemEntityTypeFullName", "ValidationFormula",
                "ValidationMessage", "EnableVersioning",
            )},
        }
        record.schema_fingerprint = hashlib.sha256(_json(schema).encode("utf-8")).hexdigest()
        return record

    def _schemas(self, graph: Graph) -> tuple[Catalog, dict[str, set[str]]]:
        definition = Graph.from_json(graph.to_json()).to_dict()
        if _site_key(definition["site"]) != _site_key(self.client.base_url):
            raise OnlineReadError("Graph site differs from the requested site.")
        catalog = Catalog(site_url=definition["site"], timestamp=_now())

        def load(list_id: str) -> ListRecord:
            if list_id not in catalog.lists:
                catalog.lists[list_id] = self._definition(list_id)
            return catalog.lists[list_id]

        _, fields = _graph_requirements(definition, load)
        return catalog, fields

    def refresh_schema(self, graph: Graph) -> Graph:
        """Return a new definition bound to fresh schemas, without data or approval."""
        self.resources = []
        started = _now()
        try:
            graph = Graph.from_json(graph.to_json())
            catalog, _ = self._schemas(graph)
            definition = graph.to_dict()
            definition["schema_fingerprint"] = _fingerprint(catalog, set(catalog.lists))
            return Graph.from_dict(definition)
        except (OnlineReadError, SnapshotAdapterError) as exc:
            raise self._failure("schema-validation", started, exc) from exc

    def _failure(self, resource: str, started: str, exc: ValueError) -> OnlineReadError:
        self.resources.append(ResourceRead(
            resource, started, _now(), "failed", 0, 0, False, str(exc),
        ))
        return OnlineReadError(str(exc), tuple(self.resources))

    def _view(self, list_id: str, view_id: str) -> dict[str, Any]:
        info = self._read(f"_api/web/lists(guid'{list_id}')/views(guid'{view_id}')", {
            "$select": "Id,Title,ViewQuery,Paged,RowLimit,Scope,ViewType",
        }, collection=False)
        if (normalize_guid(info.get("Id")) != view_id or not isinstance(info.get("ViewQuery"), str)
                or not isinstance(info.get("Title"), str)):
            raise OnlineReadError("View identity or ViewQuery is missing or invalid.")
        if info.get("Paged") is not True:
            raise OnlineReadError("Non-paged views limit membership by RowLimit; not supported.")
        if info.get("ViewType") not in {"HTML", "GRID"}:
            raise OnlineReadError("Only standard HTML/GRID views are supported as scope.")
        return {key: info.get(key) for key in ("Id", "Title", "ViewQuery", "Paged", "RowLimit",
                                                "Scope", "ViewType")}

    def read_snapshot(self, graph: Graph) -> OnlineSnapshot:
        """Read only graph lists and columns; full list rows preserve reverse/self lookups."""
        self.resources = []
        started = _now()
        try:
            graph = Graph.from_json(graph.to_json())
            definition = graph.to_dict()
            catalog, required_fields = self._schemas(graph)
            fingerprint = _fingerprint(catalog, set(catalog.lists))
            if definition["schema_fingerprint"] != fingerprint:
                raise OnlineReadError("Schema fingerprint changed; explicitly refresh the definition.")
            web = self._read("_api/web", {"$select": "Id,Url"}, collection=False)
            site = self._read("_api/site", {"$select": "Id"}, collection=False)
            if (not normalize_guid(web.get("Id")) or not normalize_guid(site.get("Id"))
                    or _site_key(web.get("Url")) != _site_key(catalog.site_url)):
                raise OnlineReadError("Server site/web identity differs from the requested site.")
            source_id = definition["source_list_id"]
            view = view_filter = None
            filter_types: dict[str, str] = {"ID": "Counter"}
            if definition["scope"]["type"] == "view":
                view = self._view(source_id, definition["scope"]["view_id"])
                try:
                    view_filter = parse_view_query(view["ViewQuery"])
                except ViewScopeError as exc:
                    raise OnlineReadError(f"View scope is not supported: {exc}") from exc
                source = catalog.lists[source_id]
                for name in sorted(view_filter.field_names - {"ID"}):
                    field = source.fields.get(name)
                    if field is None or not field.field_id:
                        raise OnlineReadError("View filter references a field missing from the schema.")
                    required_fields[source_id].add(field.field_id)
                    filter_types[name] = field.type_as_string
            lists = {}
            resolution = None
            for list_id, field_ids in sorted(required_fields.items()):
                record = catalog.lists[list_id]
                fields = {field_id: _field_by_id(record, field_id) for field_id in sorted(field_ids)}
                select = ["Id"]
                for field in fields.values():
                    name = field.entity_property_name
                    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                        raise OnlineReadError("Required field has no verified REST property mapping.")
                    select.append(name + "Id" if field.type_as_string in {"Lookup", "LookupMulti"} else name)
                scoped = view is not None and list_id == source_id
                if scoped:
                    select.append("FileSystemObjectType")
                rows = self._read(f"_api/web/lists(guid'{list_id}')/items", {
                    "$select": ",".join(dict.fromkeys(select)), "$orderby": "Id", "$top": "500",
                }, collection=True)
                etags = {}
                for row in rows:
                    item_id = row.get("Id", row.get("ID"))
                    if (type(item_id) is not int or item_id <= 0 or str(item_id) in etags
                            or ("ID" in row and row["ID"] != item_id)):
                        raise OnlineReadError("Missing, conflicting or duplicate item ID.")
                    etags[str(item_id)] = _etag(row)
                    if scoped and row.get("FileSystemObjectType") != 0:
                        raise OnlineReadError("View scope over lists with folders is not supported.")
                converted = _rows(replace(record, rows=rows, fields={
                    field.internal_name: field for field in fields.values()
                }))
                if any(field.internal_name not in row or isinstance(row[field.internal_name], dict)
                       for row in converted for field in fields.values()):
                    raise OnlineReadError("Required field value is missing or ambiguous.")
                after = self._definition(list_id)
                if (after.schema_fingerprint != record.schema_fingerprint
                        or after.item_count != record.item_count or len(rows) != record.item_count):
                    raise OnlineReadError("Schema or ItemCount changed, or the list read is incomplete.")
                if scoped:
                    assert view is not None and view_filter is not None
                    try:
                        ids = evaluate_view(view_filter, converted, filter_types)
                    except ViewScopeError as exc:
                        raise OnlineReadError(f"View scope is not supported: {exc}") from exc
                    if self._view(source_id, definition["scope"]["view_id"]) != view:
                        raise OnlineReadError("View definition changed during the read.")
                    resolution = {
                        "view_id": definition["scope"]["view_id"], "title": view["Title"],
                        "view_query_sha256": hashlib.sha256(view["ViewQuery"].encode("utf-8")).hexdigest(),
                        "ids": ids,
                    }
                lists[list_id] = {
                    "complete": True, "fields": {
                        key: _field_metadata(
                            replace(field, lookup_list=list_id)
                            if field.lookup_list.strip().casefold() == "self" else field,
                            catalog,
                        ) for key, field in fields.items()
                    }, "items": sorted(converted, key=lambda row: row["ID"]), "etags": etags,
                }
            payload = {
                "origin": "online", "site": catalog.site_url, "site_id": normalize_guid(site["Id"]),
                "web_id": normalize_guid(web["Id"]), "schema_fingerprint": fingerprint,
                "scope": definition["scope"], "started_at": started, "finished_at": _now(),
                "lists": lists,
                "warnings": ["Paging completeness is not a transactionally consistent snapshot.",
                             "Permissions, content types and server write codecs are not certified."],
            }
            if resolution is not None:
                payload["scope_resolution"] = resolution
                payload["warnings"].append(
                    "View membership is evaluated locally from a verified CAML subset; "
                    "confirm against the server view before relying on it.")
            return OnlineSnapshot(_json(payload), tuple(self.resources))
        except (OnlineReadError, SnapshotAdapterError) as exc:
            raise self._failure("snapshot-validation", started, exc) from exc
