from copy import deepcopy
from unittest.mock import Mock, patch

import pytest
import requests

from tools.sp_automation.models import Graph
from tools.sp_automation.sharepoint import (
    OnlineReadError, SharePointReader, build_online_preview,
)
from tools.sp_automation.tests.test_engine import GOAL, SOURCE, TARGET, graph
from tools.sp_automation.tests.test_snapshot_adapter import catalog
from tools.sp_extractor.client import SharePointClient


BASE = "https://example.test/sites/test"


def client():
    with patch("tools.sp_extractor.client.HttpNegotiateAuth"):
        return SharePointClient(BASE)


def response(data, status=200):
    result = Mock(status_code=status)
    result.json.return_value = deepcopy(data)
    return result


@pytest.mark.parametrize("verbose", [False, True])
def test_both_odata_formats_preserve_all_pages_and_exact_etags(verbose):
    connection = client()
    reader = SharePointReader(connection)
    endpoint = BASE + "/_api/web/items"
    rows = [{"Id": 1, "__metadata": {"etag": '"7"'}}]
    first = {"d": {"results": rows, "__next": endpoint + "?$skiptoken=1"}} if verbose else {
        "value": rows, "@odata.nextLink": endpoint + "?$skiptoken=1",
    }
    last = {"d": {"results": []}} if verbose else {"value": []}
    with patch.object(connection.session, "get", side_effect=[response(first), response(last)]) as get:
        result = reader._read("_api/web/items", {"$select": "Id"}, collection=True)
    assert result == rows
    assert get.call_args_list[0].kwargs["params"] == {"$select": "Id"}
    assert get.call_args_list[1].kwargs["params"] == {}
    assert all(call.kwargs["allow_redirects"] is False and call.kwargs["verify"] is True
               and call.kwargs["proxies"]["https"] == "http://127.0.0.1:3001"
               for call in get.call_args_list)
    resource = reader.resources[0]
    assert (resource.status, resource.pages, resource.records, resource.pagination_complete) == (
        "success", 2, 1, True,
    )


@pytest.mark.parametrize("link", [
    "https://other.test/sites/test/_api/web/items?$skiptoken=1",
    BASE + "/_api/web/fields?$skiptoken=1",
    "http://example.test/sites/test/_api/web/items?$skiptoken=1",
    "/other/_api/web/items?$skiptoken=1",
    "", None, 42, "https://[", "?page=2\n",
])
def test_bad_next_links_fail_before_another_request(link):
    connection = client()
    with patch.object(connection.session, "get", return_value=response({
        "value": [{"Id": 1}], "odata.nextLink": link,
    })) as get:
        with pytest.raises(OnlineReadError) as failure:
            SharePointReader(connection)._read("_api/web/items", {}, collection=True)
    assert get.call_count == 1
    assert failure.value.resources[-1].status == "partial"
    assert failure.value.resources[-1].pagination_complete is False


@pytest.mark.parametrize("payload", [
    [], {"d": {}}, {"value": "wrong"}, {"d": {"results": [None]}},
    {"value": [], "odata.nextLink": "?page=2", "@odata.nextLink": "?page=3"},
])
def test_malformed_collections_never_become_empty_success(payload):
    connection = client()
    with patch.object(connection.session, "get", return_value=response(payload)):
        with pytest.raises(OnlineReadError):
            SharePointReader(connection)._read("_api/web/items", {}, collection=True)


def test_loop_and_safety_limits_do_not_return_truncated_data():
    connection = client()
    repeating = response({"value": [{"Id": 1}], "odata.nextLink": "?page=2"})
    with patch.object(connection.session, "get", return_value=repeating) as get:
        with pytest.raises(OnlineReadError, match="loop"):
            SharePointReader(connection)._read("_api/web/items", {}, collection=True)
    assert get.call_count == 2
    for limits, match in [({"max_pages": 1}, "page limit"), ({"max_items": 1}, "item limit")]:
        with patch.object(connection.session, "get", return_value=response({
            "value": [{"Id": 1}, {"Id": 2}], "odata.nextLink": "?page=2",
        })):
            with pytest.raises(OnlineReadError, match=match):
                SharePointReader(connection, **limits)._read("_api/web/items", {}, collection=True)


@pytest.mark.parametrize("status", [301, 401, 403, 429, 500])
def test_http_errors_are_explicit_and_do_not_include_response_bodies(status):
    connection = client()
    with patch.object(connection.session, "get", return_value=response({}, status)):
        with pytest.raises(OnlineReadError, match=f"HTTP {status}") as failure:
            SharePointReader(connection)._read("_api/web/items", {}, collection=True)
    assert failure.value.resources[-1].status == "failed"


def test_transport_error_on_second_page_retains_partial_diagnostics():
    connection = client()
    with patch.object(connection.session, "get", side_effect=[
        response({"value": [{"Id": 1}], "odata.nextLink": "?page=2"}),
        requests.Timeout("sensitive transport details"),
    ]):
        with pytest.raises(OnlineReadError, match="transport") as failure:
            SharePointReader(connection)._read("_api/web/items", {}, collection=True)
    assert failure.value.resources[-1].records == 1
    assert "sensitive" not in str(failure.value)


class FakeSite:
    def __init__(self):
        self.calls = []
        self.infos = {}
        self.fields = {}
        self.rows = {}
        self.overrides = {}
        source = catalog()
        for list_id, record in source.lists.items():
            self.infos[list_id] = {
                "Id": list_id, "Title": record.title, "ItemCount": len(record.rows),
                "SchemaXml": "<List />", "ListItemEntityTypeFullName": "SP.Data.TestListItem",
            }
            self.fields[list_id] = [
                {**field.metadata, "Id": field.field_id, "InternalName": field.internal_name,
                 "EntityPropertyName": field.entity_property_name, "Title": field.title,
                 "TypeAsString": field.type_as_string, "LookupList": field.lookup_list}
                for field in record.fields.values()
            ]
            self.rows[list_id] = [
                {**row, "__metadata": {"etag": f'"{row["ID"]}"'}} for row in record.rows
            ]

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url in self.overrides:
            return response(self.overrides[url])
        if url == BASE + "/_api/web":
            return response({"d": {"Id": SOURCE, "Url": BASE}})
        if url == BASE + "/_api/site":
            return response({"d": {"Id": TARGET}})
        for list_id in self.infos:
            path = BASE + f"/_api/web/lists(guid'{list_id}')"
            if url == path:
                return response({"d": self.infos[list_id]})
            if url == path + "/fields":
                return response({"d": {"results": self.fields[list_id]}})
            if url == path + "/items":
                return response({"d": {"results": self.rows[list_id]}})
        raise AssertionError(f"Unexpected request: {url}")


def setup_reader():
    connection = client()
    site = FakeSite()
    connection.session.get = Mock(side_effect=site.get)
    return SharePointReader(connection), site


def test_fresh_selective_read_and_immutable_preview_invalidate_on_etag_or_graph_change():
    from dataclasses import replace
    import json

    reader, site = setup_reader()
    initial = Graph.from_dict(graph())
    fresh = reader.refresh_schema(initial)
    assert fresh.to_dict()["schema_fingerprint"] != initial.to_dict()["schema_fingerprint"]
    snapshot = reader.read_snapshot(fresh)
    preview = build_online_preview(fresh, snapshot)
    assert preview.to_dict()["result"]["changes"][0]["new_value"] == 12
    assert preview.to_dict()["write_available"] is False
    assert preview.is_current(fresh, snapshot)
    detached = preview.to_dict()
    detached["snapshot"]["lists"][SOURCE]["items"][0]["Goal"] = 999
    assert preview.to_dict()["snapshot"]["lists"][SOURCE]["items"][0]["Goal"] is None
    assert snapshot.to_dict()["lists"][SOURCE]["etags"]["1"] == '"1"'
    queries = {url: kwargs["params"]["$select"] for url, kwargs in site.calls if url.endswith("/items")}
    assert queries[BASE + f"/_api/web/lists(guid'{SOURCE}')/items"] == "Id,MechanismId,GoalId"
    assert queries[BASE + f"/_api/web/lists(guid'{TARGET}')/items"] == "Id,GoalId"
    assert not any("workflow" in url or "siteusers" in url for url, _ in site.calls)
    changed_etag = snapshot.to_dict()
    changed_etag["lists"][SOURCE]["etags"]["1"] = 'W/"2"'
    assert not preview.is_current(fresh, replace(snapshot, payload_json=json.dumps(changed_etag)))
    site.rows[SOURCE][0]["__metadata"]["etag"] = 'W/"2"'
    assert not preview.is_current(fresh, reader.read_snapshot(fresh))
    changed = fresh.to_dict()
    changed["max_updates"] = 0
    assert not preview.is_current(Graph.from_dict(changed), snapshot)


@pytest.mark.parametrize("mutate,match", [
    (lambda site: site.rows[SOURCE][0].pop("__metadata"), "ETag"),
    (lambda site: site.rows[SOURCE][0]["__metadata"].update(etag="*"), "ETag"),
    (lambda site: site.rows[SOURCE][0]["__metadata"].update(etag='"bad\x00tag"'), "ETag"),
    (lambda site: site.rows[SOURCE][0].update(**{"odata.etag": '"other"'}), "ETag"),
    (lambda site: site.rows[SOURCE].append(deepcopy(site.rows[SOURCE][0])), "duplicate"),
    (lambda site: site.rows[SOURCE][0].pop("GoalId"), "field value"),
    (lambda site: site.rows[SOURCE].pop(), "incomplete"),
    (lambda site: site.fields[SOURCE][0].update(EntityPropertyName=""), "fingerprint"),
])
def test_bad_online_inputs_never_produce_snapshot(mutate, match):
    reader, site = setup_reader()
    fresh = reader.refresh_schema(Graph.from_dict(graph()))
    mutate(site)
    with pytest.raises(OnlineReadError, match=match):
        reader.read_snapshot(fresh)


def test_schema_or_count_changes_during_read_block_preview():
    for key, value in [("SchemaXml", "<List Changed='true' />"), ("ItemCount", 999)]:
        reader, site = setup_reader()
        fresh = reader.refresh_schema(Graph.from_dict(graph()))
        original = site.get

        def changing(url, **kwargs):
            result = original(url, **kwargs)
            if url.endswith("/items"):
                site.infos[SOURCE][key] = value
            return result

        reader.client.session.get.side_effect = changing
        with pytest.raises(OnlineReadError, match="changed"):
            reader.read_snapshot(fresh)


def test_tls_and_site_mismatch_block_requests():
    connection = client()
    connection.session.verify = False
    with pytest.raises(OnlineReadError, match="TLS"):
        SharePointReader(connection)
    reader, site = setup_reader()
    changed = graph()
    changed["site"] = "https://other.test/sites/test"
    with pytest.raises(OnlineReadError, match="site"):
        reader.read_snapshot(Graph.from_dict(changed))
    assert not site.calls


def test_explicit_id_scope_does_not_hide_self_lookup_dependencies():
    reader, _ = setup_reader()
    definition = graph()
    definition["scope"] = {"type": "ids", "ids": [2]}
    fresh = reader.refresh_schema(Graph.from_dict(definition))
    snapshot = reader.read_snapshot(fresh)
    assert len(snapshot.to_dict()["lists"][SOURCE]["items"]) == 2
    assert not build_online_preview(fresh, snapshot).to_dict()["result"]["changes"]


def test_assignment_lookup_target_is_read_even_without_traversal():
    reader, site = setup_reader()
    extra = "00000000-0000-0000-0000-000000000003"
    site.infos[extra] = {**site.infos[TARGET], "Id": extra, "ItemCount": 1}
    site.fields[extra] = []
    site.rows[extra] = [{"Id": 30, "__metadata": {"etag": '"1"'}}]
    site.fields[SOURCE][1]["LookupList"] = extra
    definition = graph()
    definition["nodes"][3]["value"] = {"kind": "literal", "value": 30}
    fresh = reader.refresh_schema(Graph.from_dict(definition))
    snapshot = reader.read_snapshot(fresh)
    assert snapshot.to_dict()["lists"][extra]["fields"] == {}
    assert build_online_preview(fresh, snapshot).to_dict()["result"]["changes"][0]["new_value"] == 30


def test_reverse_collection_conditions_select_fields_on_item_alias():
    reader, site = setup_reader()
    site.fields[TARGET][0]["LookupList"] = SOURCE
    site.rows[TARGET] = [
        {"Id": 10, "GoalId": 1, "__metadata": {"etag": '"1"'}},
        {"Id": 11, "GoalId": 1, "__metadata": {"etag": '"1"'}},
        {"Id": 12, "GoalId": None, "__metadata": {"etag": '"1"'}},
    ]
    definition = graph()
    definition["nodes"][1].update(
        direction="reverse", many=True, target_list_id=TARGET,
        field_id=site.fields[TARGET][0]["Id"],
    )
    definition["nodes"][2]["condition"] = {
        "op": "any", "alias": "mechanism", "condition": {
            "op": "eq", "left": {
                "kind": "field", "alias": "item", "field_id": site.fields[TARGET][0]["Id"],
            }, "right": {"kind": "literal", "value": 1},
        },
    }
    definition["nodes"][3]["value"] = {"kind": "literal", "value": 12}
    fresh = reader.refresh_schema(Graph.from_dict(definition))
    snapshot = reader.read_snapshot(fresh)
    result = build_online_preview(fresh, snapshot).to_dict()["result"]
    assert [(change["item_id"], change["new_value"]) for change in result["changes"]] == [(1, 12)]


def test_online_preview_rejects_a_different_scope_and_missing_etags():
    from dataclasses import replace
    import json

    reader, _ = setup_reader()
    fresh = reader.refresh_schema(Graph.from_dict(graph()))
    snapshot = reader.read_snapshot(fresh)
    data = snapshot.to_dict()
    data["scope"] = {"type": "ids", "ids": [1]}
    with pytest.raises(OnlineReadError, match="scope"):
        build_online_preview(fresh, replace(snapshot, payload_json=json.dumps(data)))
    data["scope"] = {"type": "all"}
    data["lists"][SOURCE]["etags"].clear()
    with pytest.raises(OnlineReadError, match="ETag"):
        build_online_preview(fresh, replace(snapshot, payload_json=json.dumps(data)))


def test_rest_property_name_and_unrelated_columns_are_not_conflated():
    reader, site = setup_reader()
    site.fields[SOURCE][1]["EntityPropertyName"] = "GoalRest"
    for row in site.rows[SOURCE]:
        row["GoalRestId"] = row.pop("GoalId")
    site.fields[SOURCE].append({
        "Id": "00000000-0000-0000-0000-000000000099",
        "InternalName": "Unrelated", "EntityPropertyName": "Unrelated", "TypeAsString": "Text",
    })
    fresh = reader.refresh_schema(Graph.from_dict(graph()))
    snapshot = reader.read_snapshot(fresh)
    result = build_online_preview(fresh, snapshot).to_dict()["result"]
    assert result["changes"][0]["entity_property_name"] == "GoalRest"
    assert "Unrelated" not in snapshot.to_dict()["lists"][SOURCE]["items"][0]
    query = next(kwargs["params"]["$select"] for url, kwargs in site.calls
                 if url == BASE + f"/_api/web/lists(guid'{SOURCE}')/items")
    assert query == "Id,MechanismId,GoalRestId"


def test_invalid_json_and_schema_are_reported_explicitly():
    connection = client()
    malformed = response({})
    malformed.json.side_effect = ValueError("invalid JSON body")
    with patch.object(connection.session, "get", return_value=malformed):
        with pytest.raises(OnlineReadError, match="invalid JSON"):
            SharePointReader(connection)._read("_api/web/items", {}, collection=True)
    reader, site = setup_reader()
    site.fields[SOURCE][0]["SchemaXml"] = "<broken"
    with pytest.raises(OnlineReadError, match="schema"):
        reader.refresh_schema(Graph.from_dict(graph()))


VIEW = "00000000-0000-0000-0000-0000000000a1"
VIEW_URL = BASE + f"/_api/web/lists(guid'{SOURCE}')/views(guid'{VIEW}')"
MECHANISM_10 = ('<Where><Eq><FieldRef Name="Mechanism" LookupId="TRUE"/>'
                '<Value Type="Lookup">10</Value></Eq></Where><OrderBy><FieldRef Name="ID"/></OrderBy>')


def view_site(view_query, **overrides):
    reader, site = setup_reader()
    for row in site.rows[SOURCE]:
        row["FileSystemObjectType"] = 0
    site.overrides[VIEW_URL] = {"d": {
        "Id": VIEW, "Title": "Open items", "ViewQuery": view_query, "Paged": True,
        "RowLimit": 30, "Scope": 0, "ViewType": "HTML", **overrides,
    }}
    definition = graph()
    definition["scope"] = {"type": "view", "view_id": VIEW}
    return reader, site, reader.refresh_schema(Graph.from_dict(definition))


def test_unchanged_reread_keeps_preview_current_despite_new_timestamps():
    reader, _ = setup_reader()
    fresh = reader.refresh_schema(Graph.from_dict(graph()))
    with patch("tools.sp_automation.sharepoint._now", side_effect=[f"t{i}" for i in range(100)]):
        first = reader.read_snapshot(fresh)
        second = reader.read_snapshot(fresh)
    assert first.to_dict()["started_at"] != second.to_dict()["started_at"]
    assert build_online_preview(fresh, first).is_current(fresh, second)


def test_view_scope_is_resolved_from_fresh_view_and_limits_source_items():
    reader, site, fresh = view_site(MECHANISM_10)
    snapshot = reader.read_snapshot(fresh)
    data = snapshot.to_dict()
    assert data["scope_resolution"]["ids"] == [1]
    assert data["scope_resolution"]["title"] == "Open items"
    assert len(data["lists"][SOURCE]["items"]) == 2
    query = next(kwargs["params"]["$select"] for url, kwargs in site.calls
                 if url == BASE + f"/_api/web/lists(guid'{SOURCE}')/items")
    assert query.endswith("FileSystemObjectType")
    preview = build_online_preview(fresh, snapshot)
    assert [change["item_id"] for change in preview.to_dict()["result"]["changes"]] == [1]
    site.overrides[VIEW_URL]["d"]["ViewQuery"] = MECHANISM_10.replace(">10<", ">11<")
    changed = reader.read_snapshot(fresh)
    assert changed.to_dict()["scope_resolution"]["ids"] == [2]
    assert not preview.is_current(fresh, changed)


@pytest.mark.parametrize("query,overrides,match", [
    (MECHANISM_10, {"Paged": False}, "RowLimit"),
    (MECHANISM_10, {"ViewType": "CALENDAR"}, "HTML"),
    (MECHANISM_10, {"Id": TARGET}, "View identity"),
    ('<Where><Eq><FieldRef Name="Created"/><Value Type="DateTime"><Today/></Value></Eq></Where>',
     {}, "not supported"),
    ('<Where><Eq><FieldRef Name="Mechanism"/><Value Type="Lookup">Name</Value></Eq></Where>',
     {}, "not supported"),
    ('<Where><Eq><FieldRef Name="Unknown"/><Value Type="Text">x</Value></Eq></Where>',
     {}, "missing from the schema"),
])
def test_unsupported_views_block_the_snapshot(query, overrides, match):
    reader, _, fresh = view_site(query, **overrides)
    with pytest.raises(OnlineReadError, match=match):
        reader.read_snapshot(fresh)


def test_view_scope_rejects_folders_and_view_changes_during_read():
    reader, site, fresh = view_site(MECHANISM_10)
    site.rows[SOURCE][1]["FileSystemObjectType"] = 1
    with pytest.raises(OnlineReadError, match="folders"):
        reader.read_snapshot(fresh)
    reader, site, fresh = view_site(MECHANISM_10)
    original = site.get

    def changing(url, **kwargs):
        result = original(url, **kwargs)
        if url.endswith("/items"):
            site.overrides[VIEW_URL]["d"]["Title"] = "Renamed"
        return result

    reader.client.session.get.side_effect = changing
    with pytest.raises(OnlineReadError, match="View definition changed"):
        reader.read_snapshot(fresh)
