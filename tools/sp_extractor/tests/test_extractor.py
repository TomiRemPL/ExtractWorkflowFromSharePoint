"""Unit tests for SharePointExtractor with mocked responses."""

from pathlib import Path
from unittest.mock import MagicMock
import json
import pytest

from tools.sp_extractor.client import SharePointClient, SharePointClientError
from tools.sp_extractor.extractor import SharePointExtractor


def test_extractor_run_flow(tmp_path: Path):
    mock_client = MagicMock(spec=SharePointClient)
    mock_client.base_url = "http://sp.corp.local/sites/dora"

    # Mock site properties
    mock_client.get.side_effect = lambda path: {
        "_api/web?$select=Title,Url,ServerRelativeUrl,WebTemplate,Created": {
            "Title": "DORA Witryna",
            "Url": "http://sp.corp.local/sites/dora",
        },
        "_api/web/lists(guid'list-guid-1')?$select=SchemaXml": {
            "SchemaXml": "<List Title='Kwalifikacja'/>",
        },
        "_api/web/lists(guid'list-guid-1')/views(guid'view-guid-1')/viewfields": {
            "Items": ["Title", "Status"],
        },
    }.get(path, {})

    # Mock list/collections
    def mock_get_all(path):
        if "fields?$select=*&$filter=Hidden eq false" in path:
            return [{"InternalName": "Col1", "Title": "Kolumna 1", "TypeAsString": "Text"}]
        if path == "_api/web/lists?$select=*":
            return [{
                "Id": "list-guid-1",
                "Title": "Kwalifikacja Uslug",
                "BaseTemplate": 100,
            }]
        if "views?$select=*" in path:
            return [{"Id": "view-guid-1", "Title": "Wszystkie elementy"}]
        if "workflowassociations" in path and "lists" in path:
            return [{
                "Id": "wf-guid-1",
                "Name": "DT01 Mechanizm",
                "Enabled": True,
            }]
        return []

    mock_client.get_all.side_effect = mock_get_all

    # Mock Nintex export
    mock_client.export_nintex_workflow.return_value = "<NWExportedWorkflow><Root/></NWExportedWorkflow>"

    output_dir = tmp_path / "DaneZeSkryptu_001"
    extractor = SharePointExtractor(client=mock_client, output_dir=output_dir)
    manifest = extractor.run()

    # Verify generated files
    assert (output_dir / "00_kolumny_witryny.json").exists()
    assert (output_dir / "10_00_wszystkie_listy.json").exists()
    assert (output_dir / "10_lista_Kwalifikacja_Uslug.json").exists()
    assert (output_dir / "DT01_Mechanizm.nwf").exists()
    assert (output_dir / "Workflow-Inventory.csv").exists()
    assert (output_dir / "extraction_manifest.json").exists()

    # Verify nwf content
    assert (output_dir / "DT01_Mechanizm.nwf").read_text(encoding="utf-8") == "<NWExportedWorkflow><Root/></NWExportedWorkflow>"

    # Verify 10_lista content structure
    lista_json = json.loads((output_dir / "10_lista_Kwalifikacja_Uslug.json").read_text(encoding="utf-8"))
    assert lista_json["lista"]["Title"] == "Kwalifikacja Uslug"
    assert lista_json["schemaXml"] == "<List Title='Kwalifikacja'/>"

    # Verify manifest
    assert manifest["lists_count"] == 1
    assert manifest["workflows_count"] == 1
    assert manifest["workflows"][0]["status"] == "exported"
    assert manifest["format_version"] == 2
    assert manifest["complete"] is True
    assert manifest["lists"][0]["definition"]["status"] == "complete"
    assert manifest["lists"][0]["data"] == {"status": "not_exported"}


LIST_ID = "11111111-2222-3333-4444-555555555555"
G_URL = f"_api/web/lists(guid'{LIST_ID}')"
FIELDS = [
    {"InternalName": "Title", "EntityPropertyName": "Title", "TypeAsString": "Text",
     "Id": "aaaaaaaa-0000-0000-0000-000000000001"},
    {"InternalName": "Owner", "EntityPropertyName": "Owner", "TypeAsString": "User",
     "Id": "aaaaaaaa-0000-0000-0000-000000000002"},
]


def _row(item_id: int, etag: str = '"1"', **values):
    return {"odata.type": "SP.Data.ListItem", "odata.etag": etag, "ID": item_id, "Id": item_id, **values}


def _data_client(pages_for, counts=(2, 2), base_template=100):
    """Mocked client (no SharePoint): one list, items served by ``pages_for(path)``."""
    client = MagicMock(spec=SharePointClient)
    client.base_url = "https://sp.example/sites/test"
    remaining = list(counts)

    def get(path):
        if path == f"{G_URL}?$select=ItemCount":
            return {"ItemCount": remaining.pop(0)}
        if path == f"{G_URL}?$select=SchemaXml":
            return {"SchemaXml": "<List/>"}
        return {"Title": "Test"}

    def get_all(path):
        if path == "_api/web/lists?$select=*":
            return [{"Id": LIST_ID, "Title": "Lista testowa", "BaseTemplate": base_template}]
        if path == f"{G_URL}/fields?$select=*":
            return FIELDS
        return []

    client.get.side_effect = get
    client.get_all.side_effect = get_all
    client.get_all_pages.side_effect = lambda path, headers=None: pages_for(path)
    return client


def test_extractor_data_complete_with_etags(tmp_path: Path):
    client = _data_client(lambda path: ([_row(1, Title="A"), _row(2, '"2"', Title="B", OwnerId=7)], 1))

    manifest = SharePointExtractor(client=client, output_dir=tmp_path, include_data=True).run()

    data = manifest["lists"][0]["data"]
    assert manifest["complete"] is True and manifest["errors"] == []
    assert data["status"] == "complete" and data["rows"] == 2 and data["read_mode"] == "select_all"
    assert data["item_count_before"] == data["item_count_after"] == 2
    rows = json.loads((tmp_path / "20_dane_Lista_testowa.json").read_text(encoding="utf-8"))
    assert rows[1] == {"ID": 2, "Id": 2, "Title": "B", "OwnerId": 7}
    etags = json.loads((tmp_path / "21_etagi_Lista_testowa.json").read_text(encoding="utf-8"))
    assert etags == {"1": '"1"', "2": '"2"'}
    _, kwargs = client.get_all_pages.call_args
    assert "minimalmetadata" in kwargs["headers"]["Accept"]


@pytest.mark.parametrize(
    ("rows", "counts", "message"),
    [
        ([_row(1)], (2, 2), "Read 1 items but ItemCount is 2"),
        ([_row(1), _row(2)], (2, 3), "ItemCount changed"),
        ([_row(1), {"ID": 2, "Id": 2}], (2, 2), "without a valid ETag"),
        ([_row(1), _row(1)], (2, 2), "duplicate"),
    ],
)
def test_extractor_flags_incomplete_data(tmp_path: Path, rows, counts, message):
    client = _data_client(lambda path: (rows, 1), counts=counts)

    manifest = SharePointExtractor(client=client, output_dir=tmp_path, include_data=True).run()

    data = manifest["lists"][0]["data"]
    assert manifest["complete"] is False
    assert data["status"] == "incomplete"
    assert any(message in error for error in data["errors"])
    assert manifest["errors"][0]["list_id"] == LIST_ID


def test_extractor_chunked_fallback_merges_by_id(tmp_path: Path):
    def pages_for(path):
        if "$select=*" in path:
            raise SharePointClientError("HTTP 500: lookup column threshold")
        if "OwnerId" in path:
            return [_row(2, '"2"', OwnerId=7), _row(1, OwnerId=None)], 1
        return [_row(1, Title="A"), _row(2, '"2"', Title="B")], 1

    manifest = SharePointExtractor(
        client=_data_client(pages_for), output_dir=tmp_path, include_data=True,
    ).run()

    data = manifest["lists"][0]["data"]
    assert data["status"] == "complete" and data["read_mode"] == "chunked" and data["pages"] == 2
    rows = json.loads((tmp_path / "20_dane_Lista_testowa.json").read_text(encoding="utf-8"))
    assert rows == [{"ID": 1, "Id": 1, "Title": "A", "OwnerId": None},
                    {"ID": 2, "Id": 2, "Title": "B", "OwnerId": 7}]


def test_extractor_isolates_failing_lookup_and_reads_it_via_expand(tmp_path: Path):
    """Mocked server: ``OwnerId`` projection fails (FormatException) but $expand works."""
    def pages_for(path):
        if "$select=*" in path or "$select=ID,OwnerId" in path:
            raise SharePointClientError("HTTP 500: System.FormatException")
        if "$expand=Owner" in path:
            return [_row(1, Owner={"Id": 7}), _row(2, '"2"', Owner=None)], 1
        return [_row(1, Title="A"), _row(2, '"2"', Title="B")], 1

    manifest = SharePointExtractor(
        client=_data_client(pages_for), output_dir=tmp_path, include_data=True,
    ).run()

    data = manifest["lists"][0]["data"]
    assert manifest["complete"] is True and data["status"] == "complete"
    assert any("$expand=Owner" in note for note in data["notes"])
    rows = json.loads((tmp_path / "20_dane_Lista_testowa.json").read_text(encoding="utf-8"))
    assert rows == [{"ID": 1, "Id": 1, "Title": "A", "OwnerId": 7},
                    {"ID": 2, "Id": 2, "Title": "B", "OwnerId": None}]


def test_extractor_bisects_group_and_reports_unreadable_items(tmp_path: Path):
    """Mocked server: ``Title`` fails in bulk and for item 2; other columns are kept."""
    def pages_for(path):
        if "$select=*" in path or "Title" in path:
            raise SharePointClientError("HTTP 500: System.FormatException")
        if "OwnerId" in path:
            return [_row(1, OwnerId=7), _row(2, '"2"', OwnerId=None)], 1
        return [_row(1), _row(2, '"2"')], 1

    client = _data_client(pages_for)
    list_get = client.get.side_effect

    def get(path, headers=None):
        if path == f"{G_URL}/items(1)?$select=ID,Title":
            return _row(1, Title="A")
        if path == f"{G_URL}/items(2)?$select=ID,Title":
            raise SharePointClientError("HTTP 500: System.FormatException")
        return list_get(path)

    client.get.side_effect = get
    manifest = SharePointExtractor(client=client, output_dir=tmp_path, include_data=True).run()

    data = manifest["lists"][0]["data"]
    assert manifest["complete"] is False and data["status"] == "incomplete"
    assert data["rows"] == 2 and "Column 'Title'" in data["errors"][0] and "IDs: 2" in data["errors"][0]
    rows = json.loads((tmp_path / "20_dane_Lista_testowa.json").read_text(encoding="utf-8"))
    assert rows[0]["Title"] == "A" and rows[0]["OwnerId"] == 7
    assert "Title" not in rows[1] and rows[1]["OwnerId"] is None


def test_extractor_diagnoses_lookup_with_missing_display_field(tmp_path: Path):
    """Mocked server: a lookup whose ShowField was deleted fails in every GET form."""
    target = "99999999-0000-0000-0000-000000000000"
    fields = [*FIELDS, {"InternalName": "Area", "EntityPropertyName": "Area", "TypeAsString": "Lookup",
                        "LookupList": "{" + target.upper() + "}", "LookupField": "Gone_x0020_Field"}]

    def pages_for(path):
        if "$select=*" in path or "Area" in path:
            raise SharePointClientError("HTTP 500: System.FormatException")
        return [_row(1, Title="A", OwnerId=None)], 1

    client = _data_client(pages_for, counts=(1, 1))
    list_get_all, list_get = client.get_all.side_effect, client.get.side_effect
    client.get_all.side_effect = lambda path: fields if path == f"{G_URL}/fields?$select=*" else list_get_all(path)

    def get(path, headers=None):
        if "/items(1)?" in path:
            raise SharePointClientError("HTTP 500: System.FormatException")
        if path.startswith(f"_api/web/lists(guid'{target}')/fields/getbyinternalnameortitle('Gone_x0020_Field')"):
            raise SharePointClientError("HTTP 404 from ...: field does not exist")
        return list_get(path)

    client.get.side_effect = get
    manifest = SharePointExtractor(client=client, output_dir=tmp_path, include_data=True).run()

    error = manifest["lists"][0]["data"]["errors"][0]
    assert "Column 'AreaId'" in error and "'Gone_x0020_Field'" in error and "no longer exists" in error


def test_extractor_skips_superseded_versions_and_normalizes_library_names(tmp_path: Path):
    client = MagicMock(spec=SharePointClient)
    client.base_url = "https://sp.example/sites/test"
    client.get.side_effect = lambda path: {"SchemaXml": "<List/>"} if "SchemaXml" in path else {"Title": "Test"}

    def get_all(path):
        if path == "_api/web/lists?$select=*":
            return [{"Id": "list-1", "Title": "Lista", "BaseTemplate": 100},
                    {"Id": "nw-lib", "Title": "NintexWorkflows", "BaseTemplate": 5001}]
        if "lists(guid'list-1')/workflowassociations" in path:
            return [{"Id": "a1", "Name": "WF", "Enabled": True},
                    {"Id": "a0", "Name": "WF (poprzednia wersja: 06.10.2025 16:05:24)", "Enabled": False}]
        if "lists(guid'nw-lib')/items" in path:
            return [{"Title": "WF.xoml.wfconfig.xml", "WorkflowCategory": "List",
                     "AssociatedListID": "{LIST-1}", "IsProduction": True},
                    {"Title": "Wielokrotny.xoml.wfconfig.xml", "WorkflowCategory": "Reusable",
                     "IsProduction": True}]
        return []

    client.get_all.side_effect = get_all
    client.export_nintex_workflow.return_value = "<NWExportedWorkflow/>"

    manifest = SharePointExtractor(client=client, output_dir=tmp_path).run()

    statuses = {wf["workflow_name"]: wf["status"] for wf in manifest["workflows"]}
    assert statuses == {"WF": "exported", "WF (poprzednia wersja: 06.10.2025 16:05:24)": "superseded",
                        "Wielokrotny": "exported"}
    assert manifest["complete"] is True and manifest["errors"] == []
    assert client.export_nintex_workflow.call_count == 2


def test_extractor_chunked_fallback_rejects_changed_etag(tmp_path: Path):
    def pages_for(path):
        if "$select=*" in path:
            raise SharePointClientError("HTTP 500")
        if "OwnerId" in path:
            return [_row(1, '"9"', OwnerId=7)], 1
        return [_row(1, Title="A")], 1

    manifest = SharePointExtractor(
        client=_data_client(pages_for, counts=(1, 1)), output_dir=tmp_path, include_data=True,
    ).run()

    data = manifest["lists"][0]["data"]
    assert manifest["complete"] is False and data["status"] == "error"
    assert "ETag differs" in data["errors"][0]
    assert not (tmp_path / "20_dane_Lista_testowa.json").exists()


def test_extractor_external_list_data_not_applicable(tmp_path: Path):
    client = _data_client(lambda path: pytest.fail("external list items must not be read"), base_template=600)

    manifest = SharePointExtractor(client=client, output_dir=tmp_path, include_data=True).run()

    assert manifest["lists"][0]["data"]["status"] == "not_applicable"
    assert manifest["complete"] is True


def test_extractor_v2_output_loads_as_complete_catalog(tmp_path: Path):
    from tools.sp_automation.catalog import load_catalog

    client = _data_client(lambda path: ([_row(1, Title="A"), _row(2, '"2"', Title="B")], 1))
    SharePointExtractor(client=client, output_dir=tmp_path, include_data=True).run()

    record = load_catalog(tmp_path).lists[LIST_ID]
    assert (record.definition_status, record.data_status) == ("complete", "complete")
    assert record.row_etags == {1: '"1"', 2: '"2"'}

    (tmp_path / "21_etagi_Lista_testowa.json").write_text('{"1": "\\"1\\""}', encoding="utf-8")
    catalog = load_catalog(tmp_path)
    assert catalog.lists[LIST_ID].data_status == "error"
    assert "inconsistent_export" in {issue.code for issue in catalog.issues}


def test_extractor_records_errors_instead_of_reporting_success(tmp_path: Path):
    client = _data_client(lambda path: ([], 1))
    original = client.get_all.side_effect

    def get_all(path):
        if "/views?" in path:
            raise SharePointClientError("HTTP 403")
        return original(path)

    client.get_all.side_effect = get_all

    manifest = SharePointExtractor(
        client=client, output_dir=tmp_path, include_permissions=True,
    ).run()

    assert manifest["complete"] is False
    assert manifest["lists"][0]["definition"]["status"] == "error"
    assert {error["resource"] for error in manifest["errors"]} == {"permissions", "list_definition"}


def test_extractor_discovers_published_reusable_and_skips_drafts(tmp_path: Path):
    mock_client = MagicMock(spec=SharePointClient)
    mock_client.base_url = "http://sp.corp.local/sites/ictrisk"
    mock_client.get.return_value = {"Title": "ICT Risk"}

    def mock_get_all(path):
        if path == "_api/web/lists?$select=*":
            return [
                {"Id": "list-guid-1", "Title": "(R0001) Rejestr Ryzyk ICT", "BaseTemplate": 100},
                {"Id": "nw-lib-guid", "Title": "NintexWorkflows", "BaseTemplate": 5001},
            ]
        if "lists(guid'list-guid-1')/workflowassociations" in path:
            return [{"Id": "wf-list-1", "Name": "List WF", "Enabled": True}]
        if "lists(guid'nw-lib-guid')/items" in path:
            return [
                # Duplicate of published list workflow -> should deduplicate
                {
                    "Title": "List WF",
                    "NintexWorkflowID": "wf-list-1",
                    "WorkflowCategory": "List",
                    "AssociatedListID": "list-guid-1",
                    "IsProduction": True,
                },
                # Published Reusable -> should be exported
                {
                    "Title": "R0001 Ocena ryzyka",
                    "NintexWorkflowID": "wf-reusable-1",
                    "WorkflowCategory": "Reusable",
                    "AssociatedListID": "00000000-0000-0000-0000-000000000000",
                    "AssociatedContentType": "0x0100ABC",
                    "IsProduction": True,
                },
                # Draft Reusable -> should be skipped
                {
                    "Title": "R0001 Szkic",
                    "NintexWorkflowID": "wf-reusable-draft",
                    "WorkflowCategory": "Reusable",
                    "IsProduction": False,
                },
                # UDA -> should be skipped
                {
                    "Title": "Moje UDA",
                    "NintexWorkflowID": "uda-1",
                    "WorkflowCategory": "UserDefinedAction",
                    "IsProduction": True,
                },
            ]
        return []

    mock_client.get_all.side_effect = mock_get_all
    mock_client.export_nintex_workflow.return_value = "<ExportedWorkflowWithListMetdata/>"

    output_dir = tmp_path / "DaneZeSkryptu_001"
    manifest = SharePointExtractor(client=mock_client, output_dir=output_dir).run()

    assert manifest["workflows_count"] == 2
    exported_types = {w["workflow_name"]: w["workflow_type"] for w in manifest["workflows"]}
    assert exported_types == {"List WF": "list", "R0001 Ocena ryzyka": "reusable"}
    assert (output_dir / "R0001_Ocena_ryzyka.nwf").exists()
    assert not (output_dir / "R0001_Szkic.nwf").exists()

    mock_client.export_nintex_workflow.assert_any_call(
        workflow_name="R0001 Ocena ryzyka",
        list_name="",
        workflow_type="reusable",
    )

    csv_text = (output_dir / "Workflow-Inventory.csv").read_text(encoding="utf-8-sig")
    assert "Szablon przepływu pracy wielokrotnego użytku" in csv_text
    assert "R0001 Szkic" not in csv_text

