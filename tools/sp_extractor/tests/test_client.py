"""Tests for SharePointClient with mocked HTTP responses."""

from unittest.mock import MagicMock, patch
import pytest
from tools.sp_extractor.client import SharePointClient, SharePointClientError


def test_client_init_sspi():
    client = SharePointClient("http://sp.corp.local/sites/dora")
    assert client.base_url == "http://sp.corp.local/sites/dora"
    assert client.origin == "http://sp.corp.local"


def test_client_init_ntlm():
    client = SharePointClient(
        "http://sp.corp.local/sites/dora",
        username="user1",
        password="pwd",
        domain="CORP",
    )
    assert client.base_url == "http://sp.corp.local/sites/dora"


def test_resolve_url():
    client = SharePointClient("http://sp.corp.local/sites/dora")
    assert client.resolve_url("_api/web") == "http://sp.corp.local/sites/dora/_api/web"
    assert client.resolve_url("/_api/web") == "http://sp.corp.local/_api/web"
    assert client.resolve_url("http://sp.other.local/sites/dora/_api/web") == "http://sp.corp.local/sites/dora/_api/web"


def test_get_success_nometadata():
    mock_session = MagicMock()
    mock_res = MagicMock()
    mock_res.ok = True
    mock_res.status_code = 200
    mock_res.headers = {"Content-Type": "application/json"}
    mock_res.json.return_value = {"Title": "DORA", "Url": "http://sp/sites/dora"}
    mock_session.get.return_value = mock_res

    client = SharePointClient("http://sp/sites/dora", session=mock_session)
    data = client.get("_api/web")
    assert data["Title"] == "DORA"


def test_get_all_pagination():
    mock_session = MagicMock()
    # Page 1
    res1 = MagicMock()
    res1.ok = True
    res1.status_code = 200
    res1.headers = {"Content-Type": "application/json"}
    res1.json.return_value = {
        "value": [{"Id": "1", "Title": "List 1"}],
        "odata.nextLink": "http://sp/sites/dora/_api/web/lists?$skiptoken=10",
    }
    # Page 2
    res2 = MagicMock()
    res2.ok = True
    res2.status_code = 200
    res2.headers = {"Content-Type": "application/json"}
    res2.json.return_value = {
        "value": [{"Id": "2", "Title": "List 2"}],
    }
    mock_session.get.side_effect = [res1, res2]

    client = SharePointClient("http://sp/sites/dora", session=mock_session)
    items = client.get_all("_api/web/lists")
    assert len(items) == 2
    assert items[0]["Title"] == "List 1"
    assert items[1]["Title"] == "List 2"


def test_export_nintex_workflow_success():
    mock_session = MagicMock()
    mock_res = MagicMock()
    mock_res.ok = True
    mock_res.status_code = 200
    mock_res.text = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <ExportWorkflowResponse xmlns="http://nintex.com">
      <ExportWorkflowResult>&lt;NWExportedWorkflow&gt;content&lt;/NWExportedWorkflow&gt;</ExportWorkflowResult>
    </ExportWorkflowResponse>
  </soap:Body>
</soap:Envelope>"""
    mock_session.post.return_value = mock_res

    client = SharePointClient("http://sp/sites/dora", session=mock_session)
    content = client.export_nintex_workflow("Workflow A", "Lista B", "list")
    assert content == "<NWExportedWorkflow>content</NWExportedWorkflow>"

