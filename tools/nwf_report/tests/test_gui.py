from __future__ import annotations

import json
import logging
import os
from pathlib import Path
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


def test_gui_has_offline_relations_tab_and_persists_export_path(app, tmp_path):
    app.relations_tab.path_var.set(str(tmp_path))
    app.notebook.select(app.automation_tab)
    app.update()

    assert app.notebook.index(app.notebook.select()) == 2
    assert app._collect_config()["relations_in"] == str(tmp_path)
    assert "offline" in app.relations_tab.status_var.get().lower()


def test_gui_displays_relations_from_export(app, tmp_path):
    source_id = "00000000-0000-0000-0000-000000000001"
    target_id = "00000000-0000-0000-0000-000000000002"
    (tmp_path / "extraction_manifest.json").write_text(json.dumps({
        "lists": [{"id": source_id, "title": "Kontrole", "safe_title": "Kontrole"},
                  {"id": target_id, "title": "Cele", "safe_title": "Cele"}],
        "options": {"include_data": True},
    }), encoding="utf-8")
    for name, list_id, fields, rows in (
        ("Kontrole", source_id, [{"InternalName": "Cel", "Title": "Cel", "TypeAsString": "Lookup",
                                  "LookupList": target_id}], [{"Id": 1, "CelId": 2}]),
        ("Cele", target_id, [], [{"Id": 2}]),
    ):
        (tmp_path / f"10_lista_{name}.json").write_text(json.dumps({
            "lista": {"Id": list_id, "Title": name}, "kolumny": fields, "widoki": [],
        }), encoding="utf-8")
        (tmp_path / f"20_dane_{name}.json").write_text(json.dumps(rows), encoding="utf-8")

    snapshot = app._load_relations_snapshot(tmp_path)
    app.relations_tab._results.put((snapshot, ""))
    app.relations_tab._finish_load()
    assert len(app.relations_tab.list_tree.get_children()) == 2
    assert len(app.relations_tab.edge_tree.get_children()) == 1
    assert app.workflow_designer.catalog is snapshot.catalog


def test_gui_closing_can_be_cancelled_by_designer(app, monkeypatch):
    monkeypatch.setattr(app.workflow_designer, "confirm_close", lambda: False)
    app._on_close()
    assert app.winfo_exists()


def test_gui_failed_reload_clears_designer_catalog(app, monkeypatch):
    app.workflow_designer.set_catalog(object())
    monkeypatch.setattr("tools.sp_automation.relation_tab.messagebox.showerror", lambda *_args, **_kw: None)
    app.relations_tab._results.put((None, "Niepoprawny eksport"))
    app.relations_tab._finish_load()
    assert app.workflow_designer.catalog is None


@pytest.mark.skipif(os.environ.get("CHECK_SP_005") != "1", reason="local snapshot verification is opt-in")
def test_gui_displays_real_005_relations(app):
    root = Path("DaneZeSkryptu_005")
    if not (root / "extraction_manifest.json").is_file():
        pytest.skip("local export 005 unavailable")
    snapshot = app._load_relations_snapshot(root)
    app.relations_tab._results.put((snapshot, ""))
    app.relations_tab._finish_load()
    assert len(app.relations_tab.list_tree.selection()) == 6
    assert len(app.relations_tab.edge_tree.get_children()) == 7
    app.relations_tab._select_edge(app.relations_tab.edge_tree.get_children()[0])
    assert "wypełnione" in app.relations_tab.details.get("1.0", tk.END)

    app.relations_tab._compare_paths()
    dialog = app.relations_tab._comparison
    assert dialog is not None

    def wait_for_status(prefix):
        if dialog.status.get().startswith(prefix):
            return
        done = tk.StringVar()
        trace = dialog.status.trace_add(
            "write", lambda *_args: done.set("ok") if dialog.status.get().startswith(prefix) else None,
        )
        timeout = app.after(30000, lambda: done.set("timeout"))
        app.wait_variable(done)
        app.after_cancel(timeout)
        dialog.status.trace_remove("write", trace)
        assert done.get() == "ok", dialog.status.get()

    wait_for_status("Znaleziono")
    index = next(i for i, path in enumerate(dialog.paths)
                 if path.direct.field.internal_name == "Cel_x0020_SKW"
                 and path.first.field.internal_name == "Mechanizm_x0020_kontrolny")
    dialog.combo.current(index)
    dialog.compare()
    wait_for_status("Wynik")
    result = dialog.text.get("1.0", tk.END)
    assert "pośrednia wypełniona: 3" in result
    assert "Różne wartości: 6" in result
    dialog.close()
