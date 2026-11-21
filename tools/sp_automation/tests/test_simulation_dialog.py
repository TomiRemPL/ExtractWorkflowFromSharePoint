import tkinter as tk

from tools.sp_automation.simulation_dialog import SimulationDialog
from tools.sp_automation.tests.test_snapshot_adapter import catalog, ready_graph


def test_simulation_dialog_shows_advisory_proposals_without_mutating_export():
    source_catalog = catalog()
    source_rows = source_catalog.lists[next(iter(source_catalog.lists))].rows
    assert source_rows is not None
    before = [dict(row) for row in source_rows]
    root = tk.Tk()
    root.withdraw()
    try:
        dialog = SimulationDialog(root, source_catalog, ready_graph(source_catalog))
        done = tk.StringVar()

        def finish_when_ready(*_args):
            status = dialog.status.get()
            if status.startswith("Zakończono") or status.startswith("Symulacja zablokowana"):
                done.set(status)

        finish_when_ready()
        if not done.get():
            trace = dialog.status.trace_add("write", finish_when_ready)
            timeout = root.after(10000, lambda: done.set("timeout"))
            root.wait_variable(done)
            root.after_cancel(timeout)
            dialog.status.trace_remove("write", trace)
        assert done.get().startswith("Zakończono"), done.get()
        assert "NIE" in done.get()
        assert dialog.rows.get_children()
        assert "niepotwierdzonej kompletności" in dialog.warnings.get("1.0", "end")
        assert [dict(row) for row in source_rows] == before
        dialog.close()
    finally:
        root.destroy()
