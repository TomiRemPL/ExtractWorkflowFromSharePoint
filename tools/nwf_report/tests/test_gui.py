from __future__ import annotations

import pytest
from tools.gui import DoraMigrationApp


def test_gui_app_initialization():
    app = DoraMigrationApp()
    try:
        assert app.title() == "DORA - Migracja Nintex Workflow -> Oracle APEX"
        assert app.report_in_var.get() != ""
        assert app.report_out_var.get() != ""
        app.update()
    finally:
        app.destroy()

