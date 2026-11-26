"""Serwis generowania raportów Markdown/PL-SQL oraz portalu HTML."""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from core.config_service import REPO_ROOT
from core.logging_service import LineWriter
from tools.nwf_report.generate_report import main as generate_report_main


@dataclass(frozen=True)
class ReportRequest:
    """Parametry generowania raportów i portalu migracji."""

    input_dir: str
    output_dir: str
    repo_root: Path = REPO_ROOT


@dataclass(frozen=True)
class ReportResult:
    """Wynik generowania raportów i portalu HTML."""

    exit_code: int
    output_dir: Path
    portal_path: Path
    portal_exists: bool


def resolve_portal_path(output_dir: str, repo_root: Path = REPO_ROOT) -> Path:
    """Zwraca bezwzględną ścieżkę do pliku `workflow-migration-manual.html`."""
    return (repo_root / output_dir.strip() / "workflow-migration-manual.html").resolve()


def resolve_output_folder(output_dir: str, repo_root: Path = REPO_ROOT) -> Path:
    """Zwraca bezwzględną ścieżkę katalogu wyjściowego raportów."""
    return (repo_root / output_dir.strip()).resolve()


def open_output_folder(output_dir: str, repo_root: Path = REPO_ROOT) -> Path:
    """Otwiera katalog wyjściowy w systemowym menedżerze plików."""
    folder = resolve_output_folder(output_dir, repo_root=repo_root)
    if not folder.exists():
        raise FileNotFoundError(f"Katalog {folder} nie istnieje.")
    if sys.platform == "win32":
        os.startfile(folder)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(folder)])
    return folder


def run_report_generation(
    request: ReportRequest,
    log_fn: Callable[[str], None] | None = None,
) -> ReportResult:
    """Uruchamia generator raportów z przekierowaniem stdout/stderr; przystosowana do `run.io_bound`."""
    in_dir = request.input_dir.strip()
    out_dir = request.output_dir.strip()
    if not in_dir or not out_dir:
        raise ValueError("Podaj katalog wejściowy i wyjściowy.")

    emit = log_fn or (lambda _msg: None)
    emit(f"Uruchomienie generatora raportów: {in_dir} -> {out_dir}")

    stdout_writer = LineWriter(emit)
    stderr_writer = LineWriter(emit, prefix="[stderr] ")
    try:
        with contextlib.redirect_stdout(stdout_writer), contextlib.redirect_stderr(stderr_writer):
            code = generate_report_main(["--input", in_dir, "--output", out_dir])
    finally:
        stdout_writer.flush()
        stderr_writer.flush()

    if code == 0:
        emit(f"SUKCES: Wygenerowano raporty, dyspozytor PL/SQL oraz portal HTML w {out_dir}/")
    else:
        emit(f"Generator zwrócił kod wyjścia: {code}")

    resolved_out = resolve_output_folder(out_dir, repo_root=request.repo_root)
    portal = resolve_portal_path(out_dir, repo_root=request.repo_root)
    return ReportResult(
        exit_code=code,
        output_dir=resolved_out,
        portal_path=portal,
        portal_exists=portal.exists(),
    )
