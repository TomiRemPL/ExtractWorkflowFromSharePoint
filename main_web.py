"""Punkt startowy interfejsu webowego DORA opartego na NiceGUI."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import FileResponse
from nicegui import app, ui

REPO_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ui.layout import build_main_page
from ui.state import AppState

APP_STATE = AppState.create()


@app.get("/portal/{out_dir}/{file_path:path}")
def serve_portal_file(out_dir: str, file_path: str) -> FileResponse:
    """Serwuje wygenerowane pliki portalu HTML z katalogu wyjściowego."""
    base = (REPO_ROOT / out_dir).resolve()
    target = (base / file_path).resolve()
    try:
        target.relative_to(REPO_ROOT.resolve())
        target.relative_to(base)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Niedozwolona ścieżka.") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Nie znaleziono pliku portalu.")
    return FileResponse(target)


@app.on_shutdown
def _shutdown() -> None:
    APP_STATE.save()
    APP_STATE.log_session.close()


@ui.page("/")
def index_page() -> None:
    build_main_page(APP_STATE)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DORA NiceGUI Web UI")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("DORA_WEB_PORT", "8080")),
        help="Port serwera HTTP NiceGUI (domyślnie 8080)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Automatycznie otwórz przeglądarkę po starcie",
    )
    return parser.parse_args(argv)


if __name__ in {"__main__", "__mp_main__"}:
    args = parse_args()
    ui.run(
        title="DORA: Migracja SharePoint 2019 → Oracle APEX",
        language="pl",
        port=args.port,
        reload=False,
        show=args.show,
    )
