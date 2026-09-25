"""Unit tests for SharePointExtractor with mocked responses."""

from pathlib import Path
from unittest.mock import MagicMock
import json
import pytest

from tools.sp_extractor.client import SharePointClient
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

