import json
from unittest.mock import patch

from tools.sp_automation.preview_cli import main
from tools.sp_automation.tests.test_engine import graph
from tools.sp_automation.tests.test_sharepoint import setup_reader


def test_cli_persists_fresh_graph_and_read_only_preview(tmp_path):
    reader, _ = setup_reader()
    original = tmp_path / "graph.json"
    refreshed = tmp_path / "fresh.json"
    preview = tmp_path / "preview.json"
    original.write_text(json.dumps(graph()), encoding="utf-8")
    with patch("tools.sp_automation.preview_cli.SharePointClient", return_value=reader.client):
        assert main(["refresh-schema", "--graph", str(original), "--output", str(refreshed)]) == 0
        assert main(["preview", "--graph", str(refreshed), "--output", str(preview)]) == 0
    stored = json.loads(preview.read_text(encoding="utf-8"))
    assert stored["write_available"] is False
    assert stored["result"]["changes"][0]["new_value"] == 12
    assert stored["resources"]
    assert stored["run_id"]
    assert stored["snapshot"]["lists"]


def test_cli_preserves_existing_output_and_never_connects(tmp_path):
    output = tmp_path / "existing.json"
    output.write_text("keep me", encoding="utf-8")
    with patch("tools.sp_automation.preview_cli.SharePointClient") as connect:
        assert main(["preview", "--graph", "missing.json", "--output", str(output)]) == 1
    connect.assert_not_called()
    assert output.read_text(encoding="utf-8") == "keep me"


def test_cli_removes_failed_result_and_reports_partial_status(tmp_path, caplog):
    reader, site = setup_reader()
    source = tmp_path / "graph.json"
    output = tmp_path / "preview.json"
    source.write_text(json.dumps(graph()), encoding="utf-8")
    with patch("tools.sp_automation.preview_cli.SharePointClient", return_value=reader.client):
        assert main(["preview", "--graph", str(source), "--output", str(output)]) == 1
    assert not output.exists()
    assert site.calls
    assert "fingerprint" in caplog.text
    assert "snapshot-validation: failed" in caplog.text


def test_cli_journals_preview_and_approves_only_after_fresh_read_and_phrase(tmp_path):
    from tools.sp_automation.journal import PreviewJournal

    reader, site = setup_reader()
    original = tmp_path / "graph.json"
    refreshed = tmp_path / "fresh.json"
    journal_path = tmp_path / "journal.sqlite"
    original.write_text(json.dumps(graph()), encoding="utf-8")
    with patch("tools.sp_automation.preview_cli.SharePointClient", return_value=reader.client):
        assert main(["refresh-schema", "--graph", str(original), "--output", str(refreshed)]) == 0
        assert main(["preview", "--graph", str(refreshed), "--output", str(tmp_path / "p.json"),
                     "--journal", str(journal_path)]) == 0
        run_id = json.loads((tmp_path / "p.json").read_text(encoding="utf-8"))["run_id"]
        approve = ["approve", "--graph", str(refreshed), "--journal", str(journal_path),
                   "--run-id", run_id, "--approver", "tester"]
        with patch("builtins.input", return_value="tak"):
            assert main(approve) == 1
        calls = len(site.calls)
        with patch("builtins.input", return_value=f"ZATWIERDZAM {run_id}"):
            assert main(approve) == 0
    assert len(site.calls) > calls
    assert all(kwargs.get("allow_redirects") is False for _, kwargs in site.calls)
    with PreviewJournal(journal_path) as journal:
        assert journal.approval(run_id).approver == "tester"
        assert journal.approval(run_id).write_available is False
