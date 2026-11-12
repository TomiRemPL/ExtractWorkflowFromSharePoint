from __future__ import annotations

import json
import logging
import tkinter as tk
from unittest.mock import Mock

import pytest
from tools.gui import DoraMigrationApp


def _create_app(config_path) -> DoraMigrationApp:
    return DoraMigrationApp(config_path=config_path)


def _cleanup_app(app: DoraMigrationApp, original_level: int) -> None:
    root_logger = logging.getLogger()
    root_logger.removeHandler(app.queue_handler)
    root_logger.setLevel(original_level)
    try:
        if app.winfo_exists():
            app.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def app(tmp_path):
    root_logger = logging.getLogger()
    original_level = root_logger.level
    app = _create_app(tmp_path / "gui_config.json")
    try:
        yield app
    finally:
        _cleanup_app(app, original_level)


def test_gui_app_initialization(app):
    assert app.title() == "Migracja Nintex Workflow -> Oracle APEX"
    assert app.report_in_var.get() != ""
    assert app.report_out_var.get() != ""
    assert app.about_button.cget("text") == "O aplikacji"
    app.update()


def test_about_button_shows_application_information(app, monkeypatch):
    showinfo = Mock()
    monkeypatch.setattr("tools.gui.messagebox.showinfo", showinfo)

    app.about_button.invoke()

    showinfo.assert_called_once_with(
        "O aplikacji",
        "REMBIASZ GRC Tech Solutions Tomasz Rembiasz, NIP: 8871550162\n"
        "Aplikacja powstała dla Credit-Agricole Bank Polska S.A.\n"
        "Wersja: 3.0",
        parent=app,
    )


def test_gui_persists_and_restores_state_on_close(tmp_path):
    cfg = tmp_path / "gui_config.json"
    root_logger = logging.getLogger()
    original_level = root_logger.level

    app1 = _create_app(cfg)
    try:
        app1.geometry("1024x768+40+50")
        app1.update()
        app1.notebook.select(1)
        app1.url_var.set("https://teams.sp.creditagricole/team/DORA")
        app1.auto_dir_var.set(False)
        app1._toggle_custom_extract_dir()
        app1.custom_dir_var.set("DaneZeSkryptu_custom")
        app1.inc_data_var.set(True)
        app1.insecure_ssl_var.set(True)
        app1.report_in_var.set("DaneZeSkryptu_013")
        app1.report_out_var.set("out_013")
        app1._on_close()
    finally:
        _cleanup_app(app1, original_level)

    assert cfg.exists()

    app2 = _create_app(cfg)
    try:
        app2.update()
        assert app2.notebook.index(app2.notebook.select()) == 1
        assert app2.url_var.get() == "https://teams.sp.creditagricole/team/DORA"
        assert app2.auto_dir_var.get() is False
        assert str(app2.custom_dir_entry.cget("state")) == tk.NORMAL
        assert app2.custom_dir_var.get() == "DaneZeSkryptu_custom"
        assert app2.inc_data_var.get() is True
        assert app2.insecure_ssl_var.get() is True
        assert app2.report_in_var.get() == "DaneZeSkryptu_013"
        assert app2.report_out_var.get() == "out_013"
        assert app2.geometry().startswith("1024x768+")
    finally:
        _cleanup_app(app2, original_level)


def test_gui_remembers_sharepoint_url_history(tmp_path):
    cfg = tmp_path / "gui_config.json"
    root_logger = logging.getLogger()
    original_level = root_logger.level

    app1 = _create_app(cfg)
    try:
        app1._remember_url("https://sp.example.com/siteA")
        app1._remember_url("https://sp.example.com/siteB")
        app1._remember_url("https://sp.example.com/siteA")
        app1.url_var.set("https://sp.example.com/siteC")
        app1._on_close()
    finally:
        _cleanup_app(app1, original_level)

    app2 = _create_app(cfg)
    try:
        values = list(app2.url_combo.cget("values"))
        assert values[:3] == [
            "https://sp.example.com/siteC",
            "https://sp.example.com/siteA",
            "https://sp.example.com/siteB",
        ]
        assert app2.url_var.get() == "https://sp.example.com/siteC"
    finally:
        _cleanup_app(app2, original_level)


def test_gui_handles_corrupted_config_file(tmp_path):
    cfg = tmp_path / "gui_config.json"
    cfg.write_text("{not valid json", encoding="utf-8")
    root_logger = logging.getLogger()
    original_level = root_logger.level

    app = _create_app(cfg)
    try:
        assert app.url_var.get() != ""
        data = json.loads(json.dumps(app._collect_config()))
        assert isinstance(data, dict)
    finally:
        _cleanup_app(app, original_level)
