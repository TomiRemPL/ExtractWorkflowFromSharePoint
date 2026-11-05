from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest
from tools.gui import DoraMigrationApp


@pytest.fixture
def app():
    root_logger = logging.getLogger()
    original_level = root_logger.level
    app = DoraMigrationApp()
    try:
        yield app
    finally:
        root_logger.removeHandler(app.queue_handler)
        root_logger.setLevel(original_level)
        app.destroy()


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
