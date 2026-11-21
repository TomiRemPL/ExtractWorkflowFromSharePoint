"""Durable, append-only SQLite journal of online previews and explicit approvals.

An approval records that a person accepted one exact, still-current preview. It is
not an execution: no SharePoint write path exists, so approved runs stay
``write_available=False`` until a separately agreed and tested writer is added.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from .engine import SimulationResult, preview_is_current
from .models import Graph
from .sharepoint import OnlinePreview, OnlineSnapshot, _content


class JournalError(ValueError):
    """The journal cannot record the requested entry safely."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS previews (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    site TEXT NOT NULL,
    site_id TEXT NOT NULL,
    web_id TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    graph_digest TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    change_count INTEGER NOT NULL,
    preview_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    run_id TEXT PRIMARY KEY REFERENCES previews(run_id),
    approved_at TEXT NOT NULL,
    approver TEXT NOT NULL,
    graph_digest TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    statement TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES previews(run_id),
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""
_TABLE_KEYS = {"previews": "run_id", "approvals": "run_id", "events": "id"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def confirmation_phrase(run_id: str) -> str:
    """Exact text a person must type to approve one preview."""
    return f"ZATWIERDZAM {run_id}"


@dataclass(frozen=True)
class Approval:
    run_id: str
    approved_at: str
    approver: str
    graph_digest: str
    snapshot_digest: str
    write_available: bool = False


class PreviewJournal:
    """Append-only journal; UPDATE and DELETE are blocked by SQLite triggers."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        try:
            self._db = sqlite3.connect(self.path, isolation_level=None)
        except sqlite3.Error as exc:
            raise JournalError(f"Cannot open journal: {exc}") from exc
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.execute("PRAGMA synchronous = FULL")
            self._db.executescript("BEGIN;" + _SCHEMA + "".join(
                f"""CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'append-only journal'); END;
                CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'append-only journal'); END;
                CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table}
                WHEN EXISTS (SELECT 1 FROM {table} WHERE {key} = NEW.{key})
                BEGIN SELECT RAISE(ABORT, 'append-only journal'); END;"""
                for table, key in _TABLE_KEYS.items()
            ) + "COMMIT;")
        except sqlite3.Error as exc:
            self._db.close()
            raise JournalError(f"Cannot open journal: {exc}") from exc

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> PreviewJournal:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _event(self, run_id: str, kind: str, detail: str) -> None:
        self._db.execute("INSERT INTO events (run_id, at, kind, detail) VALUES (?, ?, ?, ?)",
                         (run_id, _now(), kind, detail))

    def record_preview(self, preview: OnlinePreview) -> None:
        if not isinstance(preview, OnlinePreview):
            raise JournalError("Only online previews can be journaled.")
        data = preview.to_dict()
        snapshot = data["snapshot"]
        graph_digest, snapshot_digest = preview.digests
        try:
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute(
                "INSERT INTO previews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (preview.run_id, preview.created_at, _now(), snapshot["site"], snapshot["site_id"],
                 snapshot["web_id"], json.dumps(snapshot["scope"], sort_keys=True), graph_digest,
                 snapshot_digest, len(data["result"]["changes"]),
                 json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False)),
            )
            self._event(preview.run_id, "preview_recorded", "read-only preview; no write executed")
            self._db.execute("COMMIT")
        except sqlite3.Error as exc:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise JournalError(f"Preview was not recorded: {exc}") from exc

    def preview(self, run_id: str) -> dict[str, Any]:
        row = self._db.execute("SELECT preview_json FROM previews WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise JournalError("Unknown preview run_id.")
        return json.loads(row[0])

    def approval(self, run_id: str) -> Approval | None:
        row = self._db.execute(
            "SELECT run_id, approved_at, approver, graph_digest, snapshot_digest "
            "FROM approvals WHERE run_id = ?", (run_id,),
        ).fetchone()
        return Approval(*row) if row else None

    def events(self, run_id: str) -> list[tuple[str, str, str]]:
        return self._db.execute(
            "SELECT at, kind, detail FROM events WHERE run_id = ? ORDER BY id", (run_id,),
        ).fetchall()

    def approve(self, run_id: str, *, approver: str, confirmation: str,
                graph: Graph, fresh_snapshot: OnlineSnapshot) -> Approval:
        """Approve one preview only if a fresh GET read still matches it exactly."""
        row = self._db.execute(
            "SELECT graph_digest, snapshot_digest, change_count, created_at "
            "FROM previews WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise JournalError("Unknown preview run_id.")
        graph_digest, snapshot_digest, change_count, created_at = row

        def reject(reason: str) -> JournalError:
            self._event(run_id, "approval_rejected", reason)
            return JournalError(reason)

        if not isinstance(approver, str) or not approver.strip() or len(approver) > 200:
            raise reject("Approver identity is required.")
        if confirmation != confirmation_phrase(run_id):
            raise reject("Confirmation phrase does not match this run.")
        if change_count == 0:
            raise reject("Preview has no changes to approve.")
        if self.approval(run_id) is not None:
            raise reject("Preview is already approved.")
        if not isinstance(fresh_snapshot, OnlineSnapshot) or not fresh_snapshot.resources or any(
            resource.status != "success" or not resource.pagination_complete
            for resource in fresh_snapshot.resources
        ):
            raise reject("Approval requires a successful, complete fresh read.")
        data = fresh_snapshot.to_dict()
        approved_at = _now()
        try:
            times = [datetime.fromisoformat(value) for value in (
                created_at, data["started_at"], data["finished_at"], approved_at,
            )]
            if (any(value.utcoffset() is None for value in times)
                    or not times[0] < times[1] <= times[2] <= times[3]):
                raise ValueError("Invalid read chronology")
        except (KeyError, TypeError, ValueError) as exc:
            raise reject("Approval requires a fresh read started after preview creation "
                         "with valid timezone-aware timestamps.") from exc
        stored = SimulationResult((), (), graph_digest, snapshot_digest, True)
        if not preview_is_current(stored, graph, _content(data)):
            raise reject("Preview is stale: graph, data, scope or ETags changed.")
        approval = Approval(run_id, approved_at, approver.strip(), graph_digest, snapshot_digest)
        try:
            self._db.execute("BEGIN IMMEDIATE")
            self._db.execute(
                "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, approval.approved_at, approval.approver, graph_digest, snapshot_digest,
                 confirmation),
            )
            self._event(run_id, "approved", "approved for a future writer; no write executed")
            self._db.execute("COMMIT")
        except sqlite3.Error as exc:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise JournalError(f"Approval was not recorded: {exc}") from exc
        return approval
