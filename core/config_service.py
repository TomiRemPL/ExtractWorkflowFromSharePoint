"""Zarządzanie konfiguracją GUI DORA oraz wykrywaniem katalogów eksportu."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = REPO_ROOT / ".dora_gui_config.json"
DEFAULT_SHAREPOINT_URL = "https://teams.sp.creditagricole/team/ITMM"
MAX_URL_HISTORY = 20


@dataclass
class GuiConfig:
    """Stan konfiguracji zapisywany między uruchomieniami aplikacji."""

    window_geometry: str = "950x720"
    window_state: str = "normal"
    active_tab: int = 0
    sharepoint_url: str = DEFAULT_SHAREPOINT_URL
    sharepoint_urls: list[str] = field(default_factory=lambda: [DEFAULT_SHAREPOINT_URL])
    auto_dir: bool = True
    custom_dir: str = ""
    include_data: bool = False
    insecure_ssl: bool = False
    report_in: str = "DaneZeSkryptu_002"
    report_out: str = "out_002"
    relations_in: str = ""


def detect_latest_dirs(repo_root: Path = REPO_ROOT) -> tuple[str, str] | None:
    """Wykrywa najnowszy katalog DaneZeSkryptu* i proponuje odpowiadający out*."""
    subdirs = sorted([d.name for d in repo_root.glob("DaneZeSkryptu*") if d.is_dir()])
    if not subdirs:
        return None
    latest = subdirs[-1]
    if "_" in latest:
        suffix = latest.split("_")[-1]
        return latest, f"out_{suffix}"
    return latest, "out"


def list_export_dirs(repo_root: Path = REPO_ROOT) -> list[str]:
    """Zwraca posortowaną listę katalogów DaneZeSkryptu* w repozytorium."""
    return sorted([d.name for d in repo_root.glob("DaneZeSkryptu*") if d.is_dir()])


def list_output_dirs(repo_root: Path = REPO_ROOT) -> list[str]:
    """Zwraca posortowaną listę katalogów out* w repozytorium."""
    return sorted([d.name for d in repo_root.glob("out*") if d.is_dir()])


def remember_url(history: list[str], url: str, limit: int = MAX_URL_HISTORY) -> list[str]:
    """Dodaje adres SharePoint na początek historii (bez duplikatów)."""
    cleaned = url.strip()
    if not cleaned:
        return list(history)
    updated = [u for u in history if u != cleaned]
    updated.insert(0, cleaned)
    return updated[:limit]


def load_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
    repo_root: Path = REPO_ROOT,
) -> GuiConfig:
    """Wczytuje konfigurację z pliku JSON z zastosowaniem auto-detekcji katalogów."""
    cfg = GuiConfig()
    detected = detect_latest_dirs(repo_root)
    if detected is not None:
        cfg.report_in, cfg.report_out = detected
        cfg.relations_in = str(repo_root / detected[0])
    else:
        initial_export = repo_root / "DaneZeSkryptu_005"
        if initial_export.is_dir():
            cfg.relations_in = str(initial_export)

    if not config_path.exists():
        return cfg

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logging.warning("Nie udało się wczytać konfiguracji GUI (%s): %s", config_path, exc)
        return cfg

    if not isinstance(data, dict):
        return cfg

    if isinstance(data.get("window_geometry"), str) and data["window_geometry"]:
        cfg.window_geometry = data["window_geometry"]
    if isinstance(data.get("window_state"), str):
        cfg.window_state = data["window_state"]
    if isinstance(data.get("active_tab"), int):
        cfg.active_tab = data["active_tab"]

    raw_history = data.get("sharepoint_urls")
    if isinstance(raw_history, list):
        history = [u.strip() for u in raw_history if isinstance(u, str) and u.strip()]
        if history:
            cfg.sharepoint_urls = list(dict.fromkeys(history))[:MAX_URL_HISTORY]

    sharepoint_url = data.get("sharepoint_url")
    if isinstance(sharepoint_url, str) and sharepoint_url.strip():
        cfg.sharepoint_url = sharepoint_url.strip()
        cfg.sharepoint_urls = remember_url(cfg.sharepoint_urls, cfg.sharepoint_url)

    if isinstance(data.get("auto_dir"), bool):
        cfg.auto_dir = data["auto_dir"]
    if isinstance(data.get("custom_dir"), str):
        cfg.custom_dir = data["custom_dir"]
    if isinstance(data.get("include_data"), bool):
        cfg.include_data = data["include_data"]
    if isinstance(data.get("insecure_ssl"), bool):
        cfg.insecure_ssl = data["insecure_ssl"]

    if isinstance(data.get("report_in"), str) and data["report_in"].strip():
        cfg.report_in = data["report_in"].strip()
    if isinstance(data.get("report_out"), str) and data["report_out"].strip():
        cfg.report_out = data["report_out"].strip()
    if isinstance(data.get("relations_in"), str) and data["relations_in"].strip():
        cfg.relations_in = data["relations_in"].strip()

    return cfg


def save_config(config: GuiConfig, config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Zapisuje konfigurację GUI do pliku JSON."""
    if config.sharepoint_url.strip():
        config.sharepoint_urls = remember_url(config.sharepoint_urls, config.sharepoint_url)
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        logging.warning("Nie udało się zapisać konfiguracji GUI (%s): %s", config_path, exc)
