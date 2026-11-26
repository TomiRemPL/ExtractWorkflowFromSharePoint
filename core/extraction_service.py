"""Serwis ekstrakcji metadanych, workflow i list z SharePoint 2019."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.config_service import REPO_ROOT
from tools.sp_extractor.client import SharePointClient
from tools.sp_extractor.extractor import SharePointExtractor
from tools.sp_extractor.naming import resolve_output_dir


@dataclass(frozen=True)
class ExtractionRequest:
    """Parametry zadania ekstrakcji z witryny SharePoint."""

    url: str
    auto_dir: bool = True
    custom_dir: str = ""
    include_data: bool = False
    insecure_ssl: bool = False
    repo_root: Path = REPO_ROOT


@dataclass(frozen=True)
class ExtractionResult:
    """Wynik zakończonej ekstrakcji SharePoint."""

    output_dir: Path
    workflow_count: int
    list_count: int
    complete: bool
    errors: list[dict] = field(default_factory=list)


def run_extraction(
    request: ExtractionRequest,
    log_fn: Callable[[str], None] | None = None,
) -> ExtractionResult:
    """Wykonuje ekstrakcję z SharePoint; przystosowana do `run.io_bound`."""
    url = request.url.strip()
    if not url:
        raise ValueError("Wprowadź adres URL witryny SharePoint.")

    emit = log_fn or (lambda _msg: None)
    emit(f"Inicjalizacja klienta SharePoint dla: {url}")
    client = SharePointClient(
        base_url=url,
        verify_ssl=not request.insecure_ssl,
    )
    try:
        if request.auto_dir:
            out_dir = resolve_output_dir(None, base_dir=request.repo_root)
        else:
            custom = request.custom_dir.strip() or "DaneZeSkryptu_custom"
            out_dir = request.repo_root / custom

        emit(f"Rozpoczęcie ekstrakcji do: {out_dir.resolve()}")
        extractor = SharePointExtractor(
            client=client,
            output_dir=out_dir,
            include_data=request.include_data,
        )
        manifest = extractor.run()
    finally:
        client.session.close()

    workflows = manifest.get("workflows", [])
    lists = manifest.get("lists", [])
    complete = manifest.get("complete") is not False
    errors = list(manifest.get("errors", []))
    if not complete:
        emit(
            f"UWAGA: eksport NIEKOMPLETNY ({len(errors)} błędów). "
            f"Pobrano {len(workflows)} workflow, {len(lists)} list."
        )
        for error in errors[:20]:
            emit(f"  - {error.get('resource')}: {error.get('message')}")
    else:
        emit(
            f"SUKCES: Zakończono ekstrakcję. "
            f"Pobrano {len(workflows)} workflow, {len(lists)} list."
        )

    return ExtractionResult(
        output_dir=out_dir,
        workflow_count=len(workflows),
        list_count=len(lists),
        complete=complete,
        errors=errors,
    )
