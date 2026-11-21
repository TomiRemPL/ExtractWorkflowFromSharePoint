from __future__ import annotations

import tkinter as tk

from tools.sp_automation.catalog import Catalog, FieldRecord, ListRecord
from tools.sp_automation.relation_map import MapEdge, MapNode, RelationMap
from tools.sp_automation.relation_tab import ListView, RelationView, RelationsSnapshot, RelationsTab, find_paths


def test_map_draws_nodes_and_relations_without_network() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        widget = RelationMap(root, lambda _key: None, lambda _key: None)
        widget.show(
            [MapNode("a", "Procesy"), MapNode("b", "Kontrole")],
            [MapEdge("rel", "b", "a", "Proces IT")],
        )
        assert widget.canvas.find_withtag("node0")
        assert widget.canvas.find_withtag("node1")
        assert widget.canvas.find_withtag("edge1")
        assert widget.canvas.tag_bind("edge1", "<Button-1>")
        widget.show([], [])
        assert not widget.canvas.find_withtag("edge1")
    finally:
        root.destroy()


def test_tab_renders_selection_and_relation_details() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        tab = RelationsTab(root, lambda _path: RelationsSnapshot([], [], ""))
        snapshot = RelationsSnapshot(
            [ListView("a", "Procesy", "Informacje o procesach", True),
             ListView("b", "Kontrole", "Informacje o kontrolach", True)],
            [RelationView("r1", "b", "a", "Proces IT", "Pole: Proces IT\nBraki: 2")],
            "Dane historyczne",
        )
        tab._results.put((snapshot, ""))
        tab._finish_load()
        assert len(tab.edge_tree.get_children()) == 1
        assert tab.map.canvas.find_withtag("edge1")
        tab._select_edge("r1")
        assert "Braki: 2" in tab.details.get("1.0", tk.END)
        tab.list_tree.selection_set("a")
        tab._selection_changed()
        assert not tab.edge_tree.get_children()
        assert "Informacje o procesach" in tab.details.get("1.0", tk.END)
    finally:
        root.destroy()


def test_tab_shows_outgoing_external_lists_only_on_request() -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        tab = RelationsTab(root, lambda _path: RelationsSnapshot([], [], ""))
        snapshot = RelationsSnapshot(
            [ListView("a", "Procesy", "", True), ListView("b", "Inna lista", "")],
            [RelationView("r1", "a", "b", "Pole", "Relacja")],
            "Eksport",
        )
        tab._results.put((snapshot, ""))
        tab._finish_load()
        assert not tab.edge_tree.get_children()
        tab.include_external.set(True)
        tab._selection_changed()
        assert tab.edge_tree.get_children() == ("r1",)
        assert tab.map.canvas.find_withtag("node1")
    finally:
        root.destroy()


def test_tab_clears_previous_result_on_load_error(monkeypatch) -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        tab = RelationsTab(root, lambda _path: RelationsSnapshot([], [], ""))
        tab._results.put((RelationsSnapshot([ListView("a", "Procesy", "", True)], [], "OK"), ""))
        tab._finish_load()
        errors: list[str] = []
        monkeypatch.setattr("tools.sp_automation.relation_tab.messagebox.showerror", lambda _title, msg, **_kw: errors.append(msg))
        tab._results.put((None, "Niepoprawny JSON"))
        tab._finish_load()
        assert not tab.list_tree.get_children()
        assert "Niepoprawny JSON" in errors[0]
        assert "Nie udało się" in tab.status_var.get()
    finally:
        root.destroy()


def test_paths_include_direct_and_indirect_routes_and_do_not_loop() -> None:
    relations = [
        RelationView("1", "r", "c", "Cel", ""),
        RelationView("2", "r", "m", "Mechanizm", ""),
        RelationView("3", "m", "c", "Cel", ""),
        RelationView("4", "c", "r", "Powrót", ""),
    ]
    paths, truncated = find_paths(relations, "r", "c")
    assert [[edge.key for edge in path] for path in paths] == [["1"], ["2", "3"]]
    assert not truncated
    assert find_paths(relations, "c", "missing") == ([], False)


def test_load_result_is_delivered_to_tk_main_loop(tmp_path) -> None:
    root = tk.Tk()
    root.withdraw()
    try:
        snapshot = RelationsSnapshot([ListView("one", "Lista", "", True)], [], "Wczytano")
        tab = RelationsTab(root, lambda _path: snapshot, str(tmp_path))
        done = tk.StringVar()
        tab.status_var.trace_add(
            "write", lambda *_args: done.set("ok") if tab.status_var.get() == "Wczytano" else None,
        )
        timeout = root.after(5000, lambda: done.set("timeout"))
        tab.load()
        root.wait_variable(done)
        root.after_cancel(timeout)
        assert done.get() == "ok"
        assert tab.list_tree.get_children() == ("one",)
    finally:
        root.destroy()


def test_comparison_dialog_uses_selected_catalog_and_clears_stale_results() -> None:
    source, middle, target = (
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
    )
    direct = FieldRecord("Goal", "Cel", "Lookup", lookup_list=target)
    via = FieldRecord("Mechanism", "Mechanizm", "Lookup", lookup_list=middle)
    indirect = FieldRecord("Goal", "Cel", "Lookup", lookup_list=target)
    catalog = Catalog(lists={
        source: ListRecord(source, "Kontrole", fields={"Goal": direct, "Mechanism": via},
                           rows=[{"Id": 1, "GoalId": None, "MechanismId": 2}]),
        middle: ListRecord(middle, "Mechanizmy", fields={"Goal": indirect},
                           rows=[{"Id": 2, "GoalId": 3}]),
        target: ListRecord(target, "Cele", rows=[{"Id": 3}]),
    })
    root = tk.Tk()
    root.withdraw()
    try:
        tab = RelationsTab(root, lambda _path: RelationsSnapshot([], [], ""))
        snapshot = RelationsSnapshot([ListView(key, rec.title, "", True) for key, rec in catalog.lists.items()],
                                     [], "Dane", catalog=catalog)
        tab._results.put((snapshot, ""))
        tab._finish_load()
        tab._compare_paths()
        dialog = tab._comparison
        assert dialog is not None

        def wait_for_status(prefix: str) -> None:
            if dialog.status.get().startswith(prefix):
                return
            done = tk.StringVar()
            trace = dialog.status.trace_add(
                "write", lambda *_args: done.set("ok") if dialog.status.get().startswith(prefix) else None,
            )
            timeout = root.after(5000, lambda: done.set("timeout"))
            root.wait_variable(done)
            root.after_cancel(timeout)
            dialog.status.trace_remove("write", trace)
            assert done.get() == "ok"

        wait_for_status("Znaleziono")
        dialog.compare()
        wait_for_status("Wynik")
        text = dialog.text.get("1.0", "end")
        assert "Pusta relacja bezpośrednia, pośrednia wypełniona: 1" in text
        assert "To nie jest plan zapisu" in text
        dialog._clear_result()
        assert not dialog.text.get("1.0", "end").strip()
        catalog.lists[target].rows = None
        dialog.compare()
        wait_for_status("Błąd:")
        assert "Brak danych" in dialog.status.get()
        assert str(dialog.combo.cget("state")) == "readonly"
        assert not dialog.text.get("1.0", "end").strip()
        dialog.close()
    finally:
        root.destroy()
