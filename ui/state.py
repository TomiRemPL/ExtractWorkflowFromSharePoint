"""Wspólny stan aplikacji webowej DORA."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.config_service import DEFAULT_CONFIG_PATH, REPO_ROOT, GuiConfig, load_config, save_config
from core.logging_service import LogSession
from tools.sp_automation.catalog import Catalog


@dataclass
class AppState:
    """Stan współdzielony między zakładkami interfejsu NiceGUI."""

    config: GuiConfig
    log_session: LogSession
    catalog: Catalog | None = None
    busy_count: int = 0
    status_text: str = "Gotowy."
    _status_listeners: list[Callable[[str, bool], None]] = field(default_factory=list)
    _report_sync_listeners: list[Callable[[], None]] = field(default_factory=list)
    _catalog_listeners: list[Callable[[Catalog | None], None]] = field(default_factory=list)

    @classmethod
    def create(cls) -> "AppState":
        config = load_config(DEFAULT_CONFIG_PATH, REPO_ROOT)
        log_session = LogSession(DEFAULT_CONFIG_PATH.parent / "logs")
        log_session.start()
        return cls(config=config, log_session=log_session)

    def save(self) -> None:
        save_config(self.config, DEFAULT_CONFIG_PATH)

    def set_status(self, text: str, busy: bool | None = None) -> None:
        self.status_text = text
        if busy is True:
            self.busy_count += 1
        elif busy is False and self.busy_count > 0:
            self.busy_count -= 1
        is_busy = self.busy_count > 0
        for listener in list(self._status_listeners):
            listener(text, is_busy)

    def on_status_change(self, callback: Callable[[str, bool], None]) -> None:
        self._status_listeners.append(callback)

    def on_report_sync(self, callback: Callable[[], None]) -> None:
        self._report_sync_listeners.append(callback)

    def notify_report_paths_updated(self) -> None:
        for callback in list(self._report_sync_listeners):
            callback()

    def on_catalog_change(self, callback: Callable[[Catalog | None], None]) -> None:
        self._catalog_listeners.append(callback)

    def set_catalog(self, catalog: Catalog | None) -> None:
        self.catalog = catalog
        for callback in list(self._catalog_listeners):
            callback(catalog)
