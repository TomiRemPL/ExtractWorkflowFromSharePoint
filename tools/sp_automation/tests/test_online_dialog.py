import tkinter as tk
from unittest.mock import patch

from tools.sp_automation.journal import PreviewJournal, confirmation_phrase
from tools.sp_automation.models import Graph
from tools.sp_automation.online_dialog import OnlinePreviewDialog
from tools.sp_automation.tests.test_engine import SOURCE, graph
from tools.sp_automation.tests.test_sharepoint import setup_reader


def wait_for(root, dialog, prefixes):
    done = tk.StringVar()

    def check(*_args):
        if dialog.status.get().startswith(prefixes):
            done.set(dialog.status.get())

    check()
    if not done.get():
        trace = dialog.status.trace_add("write", check)
        timeout = root.after(10000, lambda: done.set("timeout"))
        root.wait_variable(done)
        root.after_cancel(timeout)
        dialog.status.trace_remove("write", trace)
    return done.get()


def test_online_dialog_previews_records_and_approves_only_current_reads(tmp_path):
    reader, site = setup_reader()
    fresh = reader.refresh_schema(Graph.from_dict(graph()))
    journal = tmp_path / "journal.sqlite"
    root = tk.Tk()
    root.withdraw()
    try:
        dialog = OnlinePreviewDialog(root, fresh, journal_path=journal, read_snapshot=reader.read_snapshot)
        assert wait_for(root, dialog, ("Podgląd ", "Operacja")).startswith("Podgląd ")
        assert dialog.rows.get_children()
        assert str(dialog.approve_button["state"]) == "disabled"
        dialog.record()
        assert str(dialog.approve_button["state"]) == "normal"
        run_id = dialog.preview.run_id

        site.rows[SOURCE][0]["__metadata"]["etag"] = '"changed"'
        with patch("tools.sp_automation.online_dialog.simpledialog.askstring") as ask:
            dialog.start_approval()
            assert "nieaktualny" in wait_for(root, dialog, ("Podgląd jest", "Zatwierdz", "Operacja"))
        ask.assert_not_called()

        site.rows[SOURCE][0]["__metadata"]["etag"] = '"1"'
        with patch("tools.sp_automation.online_dialog.simpledialog.askstring",
                   return_value=confirmation_phrase(run_id)):
            dialog.start_approval()
            assert wait_for(root, dialog, ("Zatwierdz", "Operacja", "Podgląd jest")).startswith("Zatwierdzono")
        dialog.close()
    finally:
        root.destroy()
    with PreviewJournal(journal) as stored:
        assert stored.approval(run_id).write_available is False
    assert all(kwargs.get("allow_redirects") is False for _, kwargs in site.calls)
