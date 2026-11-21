"""Explicit GET-only schema refresh, online preview and approval using Windows SSO."""

from __future__ import annotations

import argparse
import getpass
import json
import logging
from pathlib import Path

from tools.sp_extractor.client import SharePointClient
from .engine import SimulationError
from .journal import JournalError, PreviewJournal, confirmation_phrase
from .models import Graph, GraphError
from .sharepoint import OnlineReadError, SharePointReader, build_online_preview
from .snapshot_adapter import SnapshotAdapterError


logger = logging.getLogger(__name__)
_ERRORS = (OSError, UnicodeError, GraphError, OnlineReadError, SnapshotAdapterError,
           SimulationError, JournalError)


def _log_failure(exc: Exception) -> None:
    logger.error("GET-only operation failed: %s", exc)
    if isinstance(exc, OnlineReadError):
        for resource in exc.resources:
            logger.error("Resource %s: %s; pages=%s; records=%s; pagination_complete=%s",
                         resource.resource, resource.status, resource.pages,
                         resource.records, resource.pagination_complete)


def _approve(args: argparse.Namespace) -> int:
    try:
        graph = Graph.from_json(args.graph.read_text(encoding="utf-8-sig"))
        if not args.journal.is_file():
            raise JournalError("Journal file does not exist.")
        with PreviewJournal(args.journal) as journal:
            preview = journal.preview(args.run_id)
            print(f"Run {args.run_id}: {len(preview['result']['changes'])} proposed changes; "
                  "re-reading current data (GET only) before approval.")
            client = SharePointClient(graph.to_dict()["site"])
            try:
                snapshot = SharePointReader(client).read_snapshot(graph)
            finally:
                client.session.close()
            phrase = confirmation_phrase(args.run_id)
            typed = input(f"Approval records consent only; no SharePoint write is executed.\n"
                          f"Type '{phrase}' to approve: ")
            journal.approve(args.run_id, approver=args.approver or getpass.getuser(),
                            confirmation=typed, graph=graph, fresh_snapshot=snapshot)
    except _ERRORS as exc:
        _log_failure(exc)
        return 1
    logger.info("Approval recorded in %s; write execution is not available.", args.journal)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Explicit SharePoint GET-only operation; writes to SharePoint are unavailable.",
    )
    parser.add_argument("operation", choices=("refresh-schema", "preview", "approve"))
    parser.add_argument("--graph", required=True, type=Path, help="Validated automation graph JSON.")
    parser.add_argument("--output", type=Path,
                        help="New local output file (outside Git); existing files are never overwritten.")
    parser.add_argument("--journal", type=Path,
                        help="Local SQLite journal (outside Git) for previews and approvals.")
    parser.add_argument("--run-id", help="Preview run_id to approve.")
    parser.add_argument("--approver", help="Approver identity (default: Windows user name).")
    args = parser.parse_args(argv)
    if args.operation == "approve":
        if args.journal is None or not args.run_id:
            parser.error("approve requires --journal and --run-id")
        return _approve(args)
    if args.output is None:
        parser.error(f"{args.operation} requires --output")
    if args.journal is not None and args.operation != "preview":
        parser.error("--journal is only used by preview and approve")
    created = False
    try:
        # Reserve the destination before authentication or any network reads.
        with args.output.open("x", encoding="utf-8") as output:
            created = True
            graph = Graph.from_json(args.graph.read_text(encoding="utf-8-sig"))
            client = SharePointClient(graph.to_dict()["site"])
            try:
                reader = SharePointReader(client)
                if args.operation == "refresh-schema":
                    value = reader.refresh_schema(graph).to_dict()
                else:
                    snapshot = reader.read_snapshot(graph)
                    preview = build_online_preview(graph, snapshot)
                    value = preview.to_dict()
                    if args.journal is not None:
                        with PreviewJournal(args.journal) as journal:
                            journal.record_preview(preview)
                json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.write("\n")
            finally:
                client.session.close()
    except _ERRORS as exc:
        _log_failure(exc)
        if created:
            try:
                args.output.unlink()
            except OSError as cleanup_error:
                logger.error("Failed to remove incomplete local output: %s", cleanup_error)
        return 1
    logger.info("GET-only operation completed. Local result: %s", args.output)
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())
