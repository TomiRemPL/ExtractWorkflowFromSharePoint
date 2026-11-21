import sqlite3
from dataclasses import asdict, replace
import json

import pytest

from tools.sp_automation.journal import JournalError, PreviewJournal, confirmation_phrase
from tools.sp_automation.models import Graph
from tools.sp_automation.sharepoint import build_online_preview
from tools.sp_automation.tests.test_engine import SOURCE, graph
from tools.sp_automation.tests.test_sharepoint import setup_reader


def recorded(tmp_path):
    reader, site = setup_reader()
    fresh = reader.refresh_schema(Graph.from_dict(graph()))
    preview = build_online_preview(fresh, reader.read_snapshot(fresh))
    journal = PreviewJournal(tmp_path / "journal.sqlite")
    journal.record_preview(preview)
    return reader, site, fresh, preview, journal


def test_approval_requires_exact_phrase_and_current_fresh_read(tmp_path):
    reader, site, fresh, preview, journal = recorded(tmp_path)
    run_id = preview.run_id
    with pytest.raises(JournalError, match="phrase"):
        journal.approve(run_id, approver="tester", confirmation="tak",
                        graph=fresh, fresh_snapshot=reader.read_snapshot(fresh))
    site.rows[SOURCE][0]["__metadata"]["etag"] = '"changed"'
    with pytest.raises(JournalError, match="stale"):
        journal.approve(run_id, approver="tester", confirmation=confirmation_phrase(run_id),
                        graph=fresh, fresh_snapshot=reader.read_snapshot(fresh))
    site.rows[SOURCE][0]["__metadata"]["etag"] = '"1"'
    approval = journal.approve(run_id, approver="tester", confirmation=confirmation_phrase(run_id),
                               graph=fresh, fresh_snapshot=reader.read_snapshot(fresh))
    assert approval.write_available is False
    assert journal.approval(run_id) == approval
    with pytest.raises(JournalError, match="already"):
        journal.approve(run_id, approver="tester", confirmation=confirmation_phrase(run_id),
                        graph=fresh, fresh_snapshot=reader.read_snapshot(fresh))
    kinds = [kind for _, kind, _ in journal.events(run_id)]
    assert kinds == ["preview_recorded", "approval_rejected", "approval_rejected",
                     "approved", "approval_rejected"]
    journal.close()


def test_journal_is_append_only_and_survives_reopen(tmp_path):
    _, _, _, preview, journal = recorded(tmp_path)
    journal.close()
    with PreviewJournal(tmp_path / "journal.sqlite") as reopened:
        assert reopened.preview(preview.run_id)["write_available"] is False
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            reopened._db.execute("UPDATE previews SET change_count = 0")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            reopened._db.execute("DELETE FROM events")
        with pytest.raises(JournalError, match="not recorded"):
            reopened.record_preview(preview)


def test_preview_without_changes_cannot_be_approved(tmp_path):
    reader, _ = setup_reader()
    definition = graph()
    definition["scope"] = {"type": "ids", "ids": [2]}
    fresh = reader.refresh_schema(Graph.from_dict(definition))
    preview = build_online_preview(fresh, reader.read_snapshot(fresh))
    with PreviewJournal(tmp_path / "journal.sqlite") as journal:
        journal.record_preview(preview)
        with pytest.raises(JournalError, match="no changes"):
            journal.approve(preview.run_id, approver="tester",
                            confirmation=confirmation_phrase(preview.run_id),
                            graph=fresh, fresh_snapshot=reader.read_snapshot(fresh))


@pytest.mark.parametrize("table", ["previews", "approvals", "events"])
def test_journal_blocks_replace_even_from_another_connection(tmp_path, table):
    reader, _, fresh, preview, journal = recorded(tmp_path)
    journal.approve(preview.run_id, approver="tester",
                    confirmation=confirmation_phrase(preview.run_id),
                    graph=fresh, fresh_snapshot=reader.read_snapshot(fresh))
    journal.close()
    with sqlite3.connect(tmp_path / "journal.sqlite") as db:
        before = db.execute(f"SELECT * FROM {table}").fetchall()
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute(f"INSERT OR REPLACE INTO {table} SELECT * FROM {table}")
        assert db.execute(f"SELECT * FROM {table}").fetchall() == before


def test_journal_preserves_resource_diagnostics_and_etags(tmp_path):
    _, _, _, preview, journal = recorded(tmp_path)
    journal.close()
    with PreviewJournal(tmp_path / "journal.sqlite") as reopened:
        stored = reopened.preview(preview.run_id)
        assert stored["resources"] == [asdict(resource) for resource in preview.snapshot.resources]
        assert stored["snapshot"]["lists"][SOURCE]["etags"] == (
            preview.snapshot.to_dict()["lists"][SOURCE]["etags"]
        )


@pytest.mark.parametrize("timestamps", [
    None,
    {"started_at": "2000-01-01T00:00:00+00:00", "finished_at": "2000-01-01T00:01:00+00:00"},
    {"started_at": "invalid", "finished_at": "invalid"},
    {"started_at": None, "finished_at": None},
    {"started_at": "2999-01-01T00:00:00", "finished_at": "2999-01-01T00:01:00"},
    {"started_at": "2999-01-01T00:01:00+00:00", "finished_at": "2999-01-01T00:00:00+00:00"},
    {"started_at": "2999-01-01T00:00:00+00:00", "finished_at": "2999-01-01T00:01:00+00:00"},
])
def test_approval_requires_a_read_started_after_preview_creation(tmp_path, timestamps):
    _, _, fresh, preview, journal = recorded(tmp_path)
    snapshot = preview.snapshot
    if timestamps is not None:
        data = snapshot.to_dict()
        data.update(timestamps)
        snapshot = replace(snapshot, payload_json=json.dumps(data))
    with journal:
        with pytest.raises(JournalError, match="fresh read"):
            journal.approve(preview.run_id, approver="tester",
                            confirmation=confirmation_phrase(preview.run_id),
                            graph=fresh, fresh_snapshot=snapshot)
        assert journal.approval(preview.run_id) is None
        assert journal.events(preview.run_id)[-1][1] == "approval_rejected"


def test_journal_open_error_is_reported_as_journal_error(tmp_path):
    with pytest.raises(JournalError, match="Cannot open journal"):
        PreviewJournal(tmp_path / "missing" / "journal.sqlite")


def test_approval_rejects_read_started_exactly_at_preview_creation(tmp_path):
    _, _, fresh, preview, journal = recorded(tmp_path)
    data = preview.snapshot.to_dict()
    data.update(started_at=preview.created_at, finished_at=preview.created_at)
    with journal:
        with pytest.raises(JournalError, match="fresh read"):
            journal.approve(preview.run_id, approver="tester",
                            confirmation=confirmation_phrase(preview.run_id), graph=fresh,
                            fresh_snapshot=replace(preview.snapshot, payload_json=json.dumps(data)))
        assert journal.approval(preview.run_id) is None


def test_locked_journal_does_not_mask_error_or_rollback_another_transaction(tmp_path):
    _, _, _, preview, journal = recorded(tmp_path)
    journal._db.execute("PRAGMA busy_timeout = 1")
    try:
        with sqlite3.connect(tmp_path / "journal.sqlite") as other:
            other.execute("BEGIN IMMEDIATE")
            with pytest.raises(JournalError, match="locked"):
                journal.record_preview(replace(preview, run_id="second-run"))
            assert other.in_transaction
            assert journal._db.in_transaction is False
        journal.record_preview(replace(preview, run_id="second-run"))
        assert journal.preview("second-run")["run_id"] == "second-run"
    finally:
        journal.close()
