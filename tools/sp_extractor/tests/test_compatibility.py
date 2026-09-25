"""End-to-end test verifying compatibility between sp_extractor output and nwf_report generator."""

from pathlib import Path
from unittest.mock import MagicMock
import pytest

from tools.sp_extractor.client import SharePointClient
from tools.sp_extractor.extractor import SharePointExtractor
from tools.nwf_report.generate_report import main as generate_report_main
from tools.nwf_report.tests.fixtures import build_exported_nwf_xml


def test_extractor_output_consumed_by_nwf_report(tmp_path: Path):
    mock_client = MagicMock(spec=SharePointClient)
    mock_client.base_url = "http://sp.corp.local/sites/dora"

    mock_client.get.side_effect = lambda path: {
        "_api/web?$select=Title,Url,ServerRelativeUrl,WebTemplate,Created": {
            "Title": "DORA Witryna",
            "Url": "http://sp.corp.local/sites/dora",
        },
        "_api/web/lists(guid'list-1')?$select=SchemaXml": {
            "SchemaXml": "<List Title='Lista_Testowa_A'/>",
        },
    }.get(path, {})

    def mock_get_all(path):
        if "fields?$select=*&$filter=Hidden eq false" in path:
            return [{"InternalName": "Title", "Title": "Tytul", "TypeAsString": "Text"}]
        if path == "_api/web/lists?$select=*":
            return [{
                "Id": "list-1",
                "Title": "Lista_Testowa_A",
                "BaseTemplate": 100,
            }]
        if "workflowassociations" in path and "lists" in path:
            return [{
                "Id": "wf-1",
                "Name": "Test_Workflow",
                "Enabled": True,
            }]
        return []

    mock_client.get_all.side_effect = mock_get_all
    mock_client.export_nintex_workflow.return_value = build_exported_nwf_xml()

    # 1. Run extractor
    data_dir = tmp_path / "DaneZeSkryptu_001"
    extractor = SharePointExtractor(client=mock_client, output_dir=data_dir)
    manifest = extractor.run()

    assert (data_dir / "Test_Workflow.nwf").exists()
    assert (data_dir / "10_lista_Lista_Testowa_A.json").exists()
    assert (data_dir / "Workflow-Inventory.csv").exists()

    # 2. Feed extracted directory into nwf_report generator
    report_out = tmp_path / "reports_out"
    exit_code = generate_report_main(["--input", str(data_dir), "--output", str(report_out)])

    assert exit_code == 0
    assert (report_out / "index.md").exists()
    assert (report_out / "workflow-migration-manual.html").exists()
    report_md_path = report_out / "Test Workflow.md"
    assert report_md_path.exists()
    report_text = report_md_path.read_text(encoding="utf-8")
    assert "## Kompletna procedura orkiestracji PL/SQL (Oracle APEX / SHP_API)" in report_text
    assert "process_wf_test_workflow" in report_text



