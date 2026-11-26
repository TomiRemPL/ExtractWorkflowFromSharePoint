"""Regresje wyboru i prezentacji relacji offline w NiceGUI."""
import asyncio
import inspect

import pytest
from nicegui import ui
from nicegui.events import GenericEventArguments

from core.automation_service import ListItemView, RelationEdgeView, RelationsData
from core.config_service import GuiConfig
from core.logging_service import LogSession
from tools.sp_automation.catalog import Catalog
from ui.state import AppState
from ui.tab_relations import _build_mermaid, build_relations_tab


@pytest.fixture
def relations_form(tmp_path, monkeypatch):
    lists = [
        ListItemView("a", "Alpha", "", priority=True),
        ListItemView("b", "Beta", "", is_system=True),
        ListItemView("c", "Charlie", ""),
        ListItemView("d", "Delta", ""),
    ]
    edges = [
        RelationEdgeView("ab", "a", "b", "AB", "", "b"),
        RelationEdgeView("ca", "c", "a", "CA", "", "a"),
        RelationEdgeView("bd", "b", "d", "BD", "", "d"),
        RelationEdgeView(
            "a:FileRef", "a", "invalid:a:FileRef", "Ścieżka", "", "Nieznana lista docelowa",
            ignored_reason="pole wbudowane",
        ),
    ]
    data = RelationsData(lists, edges, "Synthetic export", "", Catalog(), ignored_count=1)
    monkeypatch.setattr("ui.tab_relations.load_relations", lambda _path: data)
    monkeypatch.setattr(AppState, "save", lambda _self: None)

    async def io_bound(callback, *args):
        return callback(*args)

    monkeypatch.setattr("ui.tab_relations.run.io_bound", io_bound)

    def handle_click(callback, arguments):
        result = callback(arguments) if inspect.signature(callback).parameters else callback()
        if inspect.isawaitable(result):
            async def await_result():
                with arguments.sender.parent_slot:
                    await result
            asyncio.run(await_result())

    monkeypatch.setattr("nicegui.elements.button.handle_event", handle_click)
    state = AppState(GuiConfig(relations_in=str(tmp_path)), LogSession(tmp_path))
    with ui.column() as container:
        previous_ids = set(container.client.elements)
        build_relations_tab(state)
        elements = [element for key, element in container.client.elements.items() if key not in previous_ids]
        list_table = next(e for e in elements if isinstance(e, ui.table) and e.selection == "multiple")
        edge_table = next(e for e in elements if isinstance(e, ui.table) and e.selection == "single")
        maps = [e for e in elements if isinstance(e, ui.mermaid)]

        def control(label):
            return next(e for e in elements if getattr(e, "text", None) == label)

        def click(text):
            button = next(e for e in elements if isinstance(e, ui.button) and e.text == text)
            listener = next(e for e in button._event_listeners.values() if e.type == "click")
            listener.handler(None)

        def select(*keys):
            rows = [row for row in list_table.rows if row["key"] in keys]
            listener = next(e for e in list_table._event_listeners.values() if e.type == "selection")
            for args in (
                {"added": False, "rows": [], "keys": [row["key"] for row in list_table.selected]},
                {"added": True, "rows": rows, "keys": [row["key"] for row in rows]},
            ):
                listener.handler(GenericEventArguments(sender=list_table, client=list_table.client, args=args))

        click("Wczytaj")
        yield state, list_table, edge_table, maps, control, click, select, data
    for element in elements:
        if isinstance(element, ui.dialog):
            element.delete()
    container.delete()


def test_relations_auto_neighbors_do_not_change_selection_and_maps_match(relations_form):
    state, table, edges, maps, control, _, select, data = relations_form
    assert control("Automatycznie dodawaj powiązane listy").value is True
    assert control("Pokaż listy systemowe").value is True
    assert not control("Pokaż listy docelowe poza wyborem").enabled
    assert [row["key"] for row in table.selected] == ["a"]
    assert [row["key"] for row in edges.rows] == ["ab", "ca"]
    assert maps[0].content == maps[1].content
    assert '["Beta (systemowa)"]:::systemList' in maps[0].content
    assert '["Charlie"]:::userList' in maps[0].content
    assert "Delta" not in maps[0].content
    assert edges.rows[0]["target_title"] == "Beta"
    assert state.catalog is data.catalog
    select("c")
    assert [row["key"] for row in edges.rows] == ["ca"]
    assert "Beta" not in maps[0].content
    select()
    assert not edges.rows
    assert "Wybierz listy" in maps[0].content


def test_relations_system_fields_hidden_by_default_and_toggle(relations_form):
    _, _, edges, maps, control, _, _, _ = relations_form
    toggle = control("Pokaż pola systemowe")
    assert toggle.value is False
    assert "a:FileRef" not in {row["key"] for row in edges.rows}
    assert "Nieznana lista docelowa" not in maps[0].content
    assert control("Pominięte relacje pól systemowych: 1.") is not None
    toggle.value = True
    assert [row["key"] for row in edges.rows] == ["ab", "ca", "a:FileRef"]
    assert '["Nieznana lista docelowa"]:::externalList' in maps[0].content
    assert maps[0].content == maps[1].content
    toggle.value = False
    assert [row["key"] for row in edges.rows] == ["ab", "ca"]


def test_relations_hide_and_restore_manual_system_selection(relations_form):
    _, table, edges, maps, control, _, select, _ = relations_form
    select("a", "b")
    edges.selected = [edges.rows[0]]
    control("Pokaż listy systemowe").value = False
    assert "b" not in {row["key"] for row in table.rows}
    assert [row["key"] for row in table.selected] == ["a"]
    assert [row["key"] for row in edges.rows] == ["ca"]
    assert not edges.selected
    assert "Beta" not in maps[0].content and "Delta" not in maps[0].content
    assert maps[0].content == maps[1].content
    select("c")
    control("Pokaż listy systemowe").value = True
    assert {row["key"] for row in table.selected} == {"b", "c"}
    select("b")
    control("Pokaż listy systemowe").value = False
    assert not edges.rows
    assert "Brak widocznych list" in maps[0].content
    control("Pokaż listy systemowe").value = True
    assert [row["key"] for row in table.selected] == ["b"]


def test_relations_legacy_mode_and_reload_clear_previous_selection(relations_form):
    _, table, edges, _, control, click, select, data = relations_form
    auto = control("Automatycznie dodawaj powiązane listy")
    legacy = control("Pokaż listy docelowe poza wyborem")
    auto.value = False
    assert legacy.enabled and not edges.rows
    legacy.value = True
    assert [row["key"] for row in edges.rows] == ["ab"]
    auto.value = True
    assert not legacy.enabled and legacy.value
    assert [row["key"] for row in edges.rows] == ["ab", "ca"]
    auto.value = False
    assert [row["key"] for row in edges.rows] == ["ab"]
    select("b")
    control("Pokaż listy systemowe").value = False
    data.lists[:] = [ListItemView("new", "New export", "", priority=True)]
    data.relations.clear()
    click("Wczytaj")
    control("Pokaż listy systemowe").value = True
    assert [row["key"] for row in table.selected] == ["new"]


def test_relations_comparison_uses_manual_lists_not_auto_neighbors(relations_form, monkeypatch):
    _, _, _, _, _, click, select, _ = relations_form
    selections = []

    def options(_catalog, selected):
        selections.append(selected)
        return []

    monkeypatch.setattr("ui.tab_relations.list_comparison_options", options)
    click("Porównaj ścieżki")
    assert selections == [{"a"}]
    select("a", "b")
    click("Porównaj ścieżki")
    assert selections[-1] == {"a", "b"}


def test_mermaid_renders_all_edges_with_distinct_node_classes():
    lists = [
        ListItemView("a", 'Alpha "quoted"', ""),
        ListItemView("b", "Beta", "", is_system=True),
        ListItemView("external", "Outside", "", is_external=True),
    ]
    edges = [RelationEdgeView(f"edge{i}", "a", "b", f"Lookup {i}", "") for i in range(45)]
    edges.append(RelationEdgeView("external", "a", "external", "External", ""))
    code = _build_mermaid(lists, edges)
    assert code.count("-->") == 46
    assert '["Alpha \'quoted\'"]:::userList' in code
    assert '["Beta (systemowa)"]:::systemList' in code
    assert '["Outside"]:::externalList' in code
    assert '"Lookup 44"' in code
