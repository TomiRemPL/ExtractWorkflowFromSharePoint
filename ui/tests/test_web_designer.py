"""Regresje konstruktorów i synchronizacji formularzy NiceGUI bez przeglądarki."""
from copy import deepcopy
import json

import pytest
from nicegui import ui

from tools.sp_automation.catalog import Catalog, FieldRecord, ListRecord
from core.config_service import GuiConfig
from core.logging_service import LogSession
from ui.expression_editor import ConditionEditor, ExpressionEditor, set_select_options
from ui.flow_canvas import build_flow_payload
from ui.state import AppState
from ui.tab_designer import build_designer_tab


@pytest.mark.parametrize("value", [
    {"kind": "literal", "value": None},
    {"kind": "literal", "value": ["tekst", 123, False]},
    {"kind": "field", "alias": "item", "field_id": "manual"},
    {"kind": "count", "alias": "relacja"},
])
def test_expression_round_trip(value):
    with ui.column():
        editor = ExpressionEditor("Wartość", None)
        editor.set_value(value)
        assert editor.get_value() == value


@pytest.mark.parametrize("literal", ["NaN", '{"x":1,"x":2}', ""])
def test_expression_rejects_invalid_literal(literal):
    with ui.column():
        editor = ExpressionEditor("Wartość", None)
        editor.literal.value = literal
        with pytest.raises(ValueError):
            editor.get_value()


def test_expression_catalog_refresh_preserves_manual_and_uses_new_catalog():
    with ui.column():
        editor = ExpressionEditor("Wartość", None)
        field = FieldRecord("Title", "Tytuł", "Text", "field-id")
        catalog = Catalog(lists={"list": ListRecord("list", "Lista", fields={"Title": field})})
        editor.set_catalog(catalog)
        editor.field.value = "manual"
        assert "field-id" in editor.field_select.options
        assert editor.field_select.value == "manual"
        editor.field_select.value = "field-id"
        assert editor.field.value == "field-id"


def test_condition_tree_nested_replace_add_delete_and_accept():
    initial = {"op": "and", "conditions": [
        {"op": "exists", "alias": "source"},
        {"op": "not", "condition": {"op": "empty", "value": {"kind": "literal", "value": None}}},
    ]}
    accepted = []
    with ui.column():
        editor = ConditionEditor(None, accepted.append)
        editor.value = deepcopy(initial)
        editor._render(("conditions", 1, "condition"))
        editor.op.value = "eq"
        editor.left.set_value({"kind": "count", "alias": "relacja"})
        editor.right.literal.value = "123"
        editor._replace()
        editor._render(())
        editor.op.value = "exists"
        editor.alias.value = "nowy"
        editor._add()
        assert editor.value["conditions"][-1] == {"op": "exists", "alias": "nowy"}
        editor._delete()
        editor._accept()
        assert initial["conditions"][1]["condition"]["op"] == "empty"
        assert accepted[0]["conditions"][1]["condition"] == {
            "op": "eq", "left": {"kind": "count", "alias": "relacja"},
            "right": {"kind": "literal", "value": 123},
        }


def test_condition_accept_applies_pending_edits_without_replace_click():
    accepted = []
    with ui.column():
        editor = ConditionEditor(None, accepted.append)
        editor.open({"op": "exists", "alias": "source"})
        editor.op.value = "eq"
        editor.left.set_value({"kind": "field", "alias": "source", "field_id": "Title"})
        editor.right.set_value({"kind": "literal", "value": "OK"})
        editor._accept()
    assert accepted == [{
        "op": "eq",
        "left": {"kind": "field", "alias": "source", "field_id": "Title"},
        "right": {"kind": "literal", "value": "OK"},
    }]


def test_condition_editor_shows_preview_and_helpful_literal_error():
    accepted = []
    with ui.column():
        editor = ConditionEditor(None, accepted.append)
        editor.open({"op": "exists", "alias": "source"})
        assert '"op": "exists"' in editor.preview.value
        editor.op.value = "eq"
        editor.right.literal.value = "Tak"
        editor._accept()
        assert accepted == []
        assert editor.error_label.visible
        assert "cudzysłowach" in editor.error_label.text


@pytest.mark.parametrize("op", ["any", "all", "not", "empty", "not_empty", "ne", "lt", "le", "gt", "ge", "or"])
def test_condition_construct_preserves_contract(op):
    with ui.column():
        editor = ConditionEditor(None, lambda value: None)
        editor.op.value = op
        value = editor._construct()
        assert value["op"] == op
        if op in ("any", "all", "not"):
            assert value["condition"] == {"op": "exists", "alias": "source"}
            assert ("alias" in value) == (op != "not")
        elif op in ("empty", "not_empty"):
            assert value["value"] == {"kind": "literal", "value": None}
        elif op == "or":
            assert len(value["conditions"]) == 1
        else:
            assert value["left"] == value["right"] == {"kind": "literal", "value": None}


@pytest.fixture
def designer_form(tmp_path, monkeypatch):
    monkeypatch.setattr("ui.tab_designer.render_flow_canvas", lambda *args: None)
    state = AppState(GuiConfig(), LogSession(tmp_path))
    with ui.column() as container:
        build_designer_tab(state)
        elements = list(container.descendants())

        def control(label):
            return next(element for element in elements if getattr(element, "label", None) == label)

        def click(text):
            button = next(element for element in elements if isinstance(element, ui.button) and element.text == text)
            listener = next(listener for listener in button._event_listeners.values() if listener.type == "click")
            assert listener.handler is not None
            listener.handler(None)

        yield state, control, click
    container.delete()


def test_designer_save_pending_expression_and_cancel_restores_saved_graph(designer_form, tmp_path):
    _, control, click = designer_form
    control("Typ węzła").value = "assign"
    click("Dodaj węzeł")
    control("Literał JSON").value = '"wartosc"'
    path = tmp_path / "draft.json"
    control("Ścieżka pliku JSON grafu").value = str(path)
    click("Zapisz JSON")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["nodes"][-1]["value"] == {"kind": "literal", "value": "wartosc"}
    control("Nazwa algorytmu").value = "zmiana"
    click("Anuluj zmiany")
    assert json.loads(control("Definicja grafu (JSON)").value) == saved


def test_designer_catalog_sync_and_source_change_clear_view(designer_form):
    state, control, _ = designer_form
    catalog = Catalog(lists={"a": ListRecord("a", "Alfa"), "b": ListRecord("b", "Beta")})
    state.set_catalog(catalog)
    assert "a" in control("Lista źródłowa").options
    control("Lista źródłowa").value = "a"
    assert control("GUID listy źródłowej").value == "a"
    control("Zakres (scope)").value = "view"
    set_select_options(control("Widok listy"), {"widok": "Widok"}, "widok")
    control("GUID listy źródłowej").value = "b"
    graph = json.loads(control("Definicja grafu (JSON)").value)
    assert graph["source_list_id"] == "b"
    assert graph["scope"] == {"type": "view", "view_id": ""}


def test_designer_cancel_handles_custom_start_id_and_invalid_json(designer_form, tmp_path):
    _, control, click = designer_form
    graph = json.loads(control("Definicja grafu (JSON)").value)
    graph["nodes"][0]["id"] = "custom_start"
    graph["layout"] = {"custom_start": {"x": 100, "y": 100}}
    control("Definicja grafu (JSON)").value = json.dumps(graph)
    path = tmp_path / "draft.json"
    control("Ścieżka pliku JSON grafu").value = str(path)
    click("Zapisz JSON")
    control("Definicja grafu (JSON)").value = "{"
    click("Anuluj zmiany")
    assert json.loads(control("Definicja grafu (JSON)").value) == graph


def test_designer_scope_ids_parsing_and_validation(designer_form):
    _, control, _ = designer_form
    control("Zakres (scope)").value = "ids"
    control("Wybrane ID elementów (np. 1, 2, 5)").value = "1, 5 10"
    graph = json.loads(control("Definicja grafu (JSON)").value)
    assert graph["scope"] == {"type": "ids", "ids": [1, 5, 10]}

    control("Wybrane ID elementów (np. 1, 2, 5)").value = "2, 2"
    assert json.loads(control("Definicja grafu (JSON)").value)["scope"] == {"type": "ids", "ids": [1, 5, 10]}
    err_lbl = next(el for el in control("Definicja grafu (JSON)").parent_slot.children if isinstance(el, ui.label))
    assert "Powtórzone ID elementu: 2" in err_lbl.text


def test_designer_lookup_advanced_and_condition_merge(designer_form):
    state, control, click = designer_form
    catalog = Catalog(lists={"target-guid": ListRecord("target-guid", "Docelowa")})
    state.set_catalog(catalog)

    control("Typ węzła").value = "lookup"
    click("Dodaj węzeł")
    control("Kierunek relacji").value = "reverse"
    many_cb = next(el for el in control("Kierunek relacji").parent_slot.children if isinstance(el, ui.checkbox))
    many_cb.value = True
    control("Lista docelowa (odwrotne)").value = "target-guid"
    click("Zastosuj")

    graph = json.loads(control("Definicja grafu (JSON)").value)
    lk = graph["nodes"][-1]
    assert lk["direction"] == "reverse"
    assert lk["many"] is True
    assert lk["target_list_id"] == "target-guid"

    control("Typ węzła").value = "merge"
    click("Dodaj węzeł")
    control("Typ węzła").value = "condition"
    click("Dodaj węzeł")
    assert "merge_1" in control("Wspólne scalenie (merge)").options
    control("Wspólne scalenie (merge)").value = "merge_1"
    click("Zastosuj")

    graph = json.loads(control("Definicja grafu (JSON)").value)
    cond = graph["nodes"][-1]
    assert cond["merge"] == "merge_1"


def test_designer_filters_fields_by_source_list_and_lookup_alias(designer_form):
    state, control, click = designer_form
    catalog = Catalog(lists={
        "list-a": ListRecord("list-a", "Alfa", fields={
            "Title": FieldRecord("Title", "Tytuł A", "Text", "a-title"),
            "RefB": FieldRecord("RefB", "Relacja do B", "Lookup", "a-ref-b", lookup_list="list-b"),
        }),
        "list-b": ListRecord("list-b", "Beta", fields={
            "Status": FieldRecord("Status", "Status B", "Text", "b-status"),
            "RefA": FieldRecord("RefA", "Relacja do A", "Lookup", "b-ref-a", lookup_list="list-a"),
        }),
    })
    state.set_catalog(catalog)
    control("Lista źródłowa").value = "list-a"

    control("Typ węzła").value = "lookup"
    click("Dodaj węzeł")
    assert list(control("Pole Lookup z katalogu").options) == ["a-ref-b"]

    control("Pole Lookup z katalogu").value = "a-ref-b"
    control("Jako alias (as)").value = "beta"
    click("Zastosuj")

    control("Pole Lookup (field_id)").value = ""
    control("Kierunek relacji").value = "reverse"
    control("Lista docelowa (odwrotne)").value = "list-b"
    assert list(control("Pole Lookup z katalogu").options) == ["b-ref-a"]

    control("Typ węzła").value = "assign"
    click("Dodaj węzeł")
    assert set(control("Pole docelowe z katalogu").options) == {"a-title", "a-ref-b"}

    control("Rodzaj").value = "field"
    assert set(control("Pole z katalogu").options) == {"a-title", "a-ref-b"}

    control("Alias docelowy").value = "beta"
    assert set(control("Pole docelowe z katalogu").options) == {"b-status", "b-ref-a"}

    expr_alias = next(
        el for el in control("Pole z katalogu").parent_slot.children
        if isinstance(el, ui.input) and el.label == "Alias"
    )
    expr_alias.value = "beta"
    assert set(control("Pole z katalogu").options) == {"b-status", "b-ref-a"}


def test_designer_hides_raw_guid_and_field_id_inputs_visually(designer_form):
    state, control, click = designer_form
    guid_list = "7cb6c650-ee85-45f2-93c5-4eadc8382043"
    guid_field = "d340fca5-f503-4baa-bae9-90f1447ebff6"

    assert control("GUID listy źródłowej").visible is False

    control("Typ węzła").value = "lookup"
    click("Dodaj węzeł")
    assert control("Pole Lookup (field_id)").visible is False
    assert control("GUID listy docelowej (target_list_id)").visible is False

    control("Typ węzła").value = "assign"
    click("Dodaj węzeł")
    assert control("Pole docelowe (field_id)").visible is False
    control("Rodzaj").value = "field"
    assert control("Pole z katalogu").visible is True
    assert control("Pole (GUID lub nazwa ręczna)").visible is False

    select = control("Lista źródłowa")
    set_select_options(select, {}, guid_list)
    assert select.value == guid_list
    assert guid_list not in select.options[guid_list]

    payload_no_cat = build_flow_payload(
        {"nodes": [{"id": "assign_1", "type": "assign", "alias": "source", "field_id": guid_field}], "edges": [], "layout": {}},
        catalog=None,
    )
    assert payload_no_cat["subtitles"]["assign_1"] == "assign_1"

    catalog = Catalog(lists={
        guid_list: ListRecord(guid_list, "Ocena", fields={
            "Status": FieldRecord("Status", "Status końcowy", "Text", guid_field),
        }),
    })
    payload_with_cat = build_flow_payload(
        {
            "source_list_id": guid_list,
            "nodes": [{"id": "assign_1", "type": "assign", "alias": "source", "field_id": guid_field}],
            "edges": [],
            "layout": {},
        },
        catalog=catalog,
    )
    assert payload_with_cat["subtitles"]["assign_1"] == "assign_1 → Status końcowy [Status]"
    assert guid_field not in payload_with_cat["subtitles"]["assign_1"]


def test_designer_tables_use_lista_header_without_guid(tmp_path, monkeypatch):
    monkeypatch.setattr("ui.tab_designer.render_flow_canvas", lambda *args: None)
    state = AppState(GuiConfig(), LogSession(tmp_path))
    before_ids = set(ui.context.client.elements)
    with ui.column() as container:
        build_designer_tab(state)
        tables = [
            el for el_id, el in ui.context.client.elements.items()
            if el_id not in before_ids and isinstance(el, ui.table)
        ]
        assert len(tables) == 3
        all_headers = [[col["label"] for col in table.columns] for table in tables]
        for headers in all_headers:
            assert "Lista GUID" not in headers
        assert sum("Lista" in headers for headers in all_headers) == 2
        trace_headers = next(headers for headers in all_headers if "Użyte zmienne i wartości" in headers)
        assert "Wynik kroku" in trace_headers
    container.delete()


def test_designer_filters_dropdowns_by_operation_context(designer_form):
    state, control, click = designer_form
    src_id = "11111111-1111-4111-8111-111111111111"
    tgt_id = "22222222-2222-4222-8222-222222222222"
    other_id = "33333333-3333-4333-8333-333333333333"

    f_text = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
    f_computed = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"
    f_readonly = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3"
    f_num = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4"
    f_lookup = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa5"
    f_lookup_multi = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa6"
    f_user = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa7"
    f_back_lookup = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"
    f_tgt_text = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2"

    catalog = Catalog(lists={
        src_id: ListRecord(src_id, "Źródło", fields={
            "Title": FieldRecord("Title", "Symbol kategorii", "Text", f_text, metadata={"ReadOnlyField": False, "Required": False, "MaxLength": 255}),
            "LinkTitleNoMenu": FieldRecord("LinkTitleNoMenu", "Symbol kategorii", "Computed", f_computed, metadata={"ReadOnlyField": True, "Required": False}),
            "Locked": FieldRecord("Locked", "Zablokowane", "Text", f_readonly, metadata={"ReadOnlyField": True, "Required": False, "MaxLength": 50}),
            "Score": FieldRecord("Score", "Wynik", "Number", f_num, metadata={"ReadOnlyField": False, "Required": False}),
            "Cat": FieldRecord("Cat", "Kategoria", "Lookup", f_lookup, lookup_list=tgt_id, metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": False}),
            "CatMulti": FieldRecord("CatMulti", "Kategorie", "LookupMulti", f_lookup_multi, lookup_list=tgt_id, metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": True}),
            "Owner": FieldRecord("Owner", "Właściciel", "User", f_user, lookup_list="UserInfo", metadata={"ReadOnlyField": True, "Required": False}),
        }),
        tgt_id: ListRecord(tgt_id, "Docelowa", fields={
            "BackRef": FieldRecord("BackRef", "Powiązanie", "Lookup", f_back_lookup, lookup_list=src_id, metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": False}),
            "Name": FieldRecord("Name", "Nazwa", "Text", f_tgt_text, metadata={"ReadOnlyField": False, "Required": False, "MaxLength": 255}),
        }),
        other_id: ListRecord(other_id, "Niepowiązana", fields={}),
    })
    state.set_catalog(catalog)
    control("Lista źródłowa").value = src_id

    # Lookup node: excludes User, hides target_list in forward, filters target_list in reverse
    control("Typ węzła").value = "lookup"
    click("Dodaj węzeł")
    assert set(control("Pole Lookup z katalogu").options) == {f_lookup, f_lookup_multi}
    assert control("Lista docelowa (odwrotne)").visible is False
    control("Kierunek relacji").value = "reverse"
    assert control("Lista docelowa (odwrotne)").visible is True
    assert set(control("Lista docelowa (odwrotne)").options) == {tgt_id}
    control("Lista docelowa (odwrotne)").value = tgt_id
    assert set(control("Pole Lookup z katalogu").options) == {f_back_lookup}

    # Assign node: target dropdown only shows writable fields; expression narrows to compatible types
    control("Typ węzła").value = "assign"
    click("Dodaj węzeł")
    assert set(control("Pole docelowe z katalogu").options) == {f_text, f_num, f_lookup}
    control("Rodzaj").value = "field"
    assert f_computed not in control("Pole z katalogu").options
    assert f_user not in control("Pole z katalogu").options

    control("Pole docelowe z katalogu").value = f_text
    assert set(control("Pole z katalogu").options) == {f_text, f_readonly}

    control("Pole docelowe z katalogu").value = f_lookup
    assert set(control("Pole z katalogu").options) == {f_lookup}

    # Condition editor: excludes Computed and User
    with ui.column():
        cond_editor = ConditionEditor(catalog, lambda _v: None, alias_resolver=lambda _a: src_id)
        assert f_computed not in cond_editor.left.field_select.options
        assert f_user not in cond_editor.left.field_select.options
        assert f_text in cond_editor.left.field_select.options


def test_condition_editor_live_preview_and_operator_visibility():
    list_id = "11111111-1111-4111-8111-111111111111"
    field_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
    catalog = Catalog(lists={
        list_id: ListRecord(list_id, "Lista", fields={
            "Status": FieldRecord("Status", "Status", "Text", field_id, metadata={"ReadOnlyField": False, "Required": False, "MaxLength": 50}),
        }),
    })
    accepted = []
    with ui.column():
        editor = ConditionEditor(catalog, accepted.append, alias_resolver=lambda _a: list_id)
        editor.open({"op": "exists", "alias": "source"})
        assert editor.alias.visible is True
        assert editor.left_col.visible is False
        assert editor.right_col.visible is False

        editor.op.value = "eq"
        assert editor.alias.visible is False
        assert editor.left_col.visible is True
        assert editor.right_col.visible is True
        assert '"op": "eq"' in editor.preview.value

        editor.left.kind.value = "field"
        editor.left.field_select.value = field_id
        editor.right.literal.value = '"OK"'
        preview = json.loads(editor.preview.value)
        assert preview == {
            "op": "eq",
            "left": {"kind": "field", "alias": "source", "field_id": field_id},
            "right": {"kind": "literal", "value": "OK"},
        }
        assert "Status" in editor.summary.text

        editor.op.value = "empty"
        assert editor.left_col.visible is True
        assert editor.right_col.visible is False

        editor.op.value = "and"
        assert editor.alias.visible is False
        assert editor.left_col.visible is False
        assert editor.right_col.visible is False

        editor.op.value = "eq"
        editor._accept()
        assert accepted == [preview]


def test_designer_condition_builder_saves_to_graph_json(tmp_path, monkeypatch):
    monkeypatch.setattr("ui.tab_designer.render_flow_canvas", lambda *args: None)
    list_id = "11111111-1111-4111-8111-111111111111"
    field_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1"
    state = AppState(GuiConfig(), LogSession(tmp_path))
    state.set_catalog(Catalog(lists={
        list_id: ListRecord(list_id, "Lista", fields={
            "Status": FieldRecord("Status", "Status", "Text", field_id, metadata={"ReadOnlyField": False, "Required": False, "MaxLength": 50}),
        }),
    }))
    before_ids = set(ui.context.client.elements)
    with ui.column() as container:
        build_designer_tab(state)
        elements = [el for el_id, el in ui.context.client.elements.items() if el_id not in before_ids]

        def control(label):
            return next(el for el in elements if getattr(el, "label", None) == label)

        def click(text):
            button = next(el for el in elements if isinstance(el, ui.button) and el.text == text)
            listener = next(listener for listener in button._event_listeners.values() if listener.type == "click")
            listener.handler(None)

        control("Lista źródłowa").value = list_id
        control("Typ węzła").value = "condition"
        click("Dodaj węzeł")
        click("Konstruktor warunku (drzewo)...")

        op_selects = [el for el in elements if isinstance(el, ui.select) and el.label == "Operator"]
        assert len(op_selects) == 2
        dlg_op = op_selects[1]
        dlg_card = dlg_op.parent_slot.parent.parent_slot.parent.parent_slot.parent
        dlg_descendants = list(dlg_card.descendants())
        dlg_left_kind = next(el for el in dlg_descendants if isinstance(el, ui.select) and el.label == "Rodzaj")
        dlg_left_field = next(el for el in dlg_descendants if isinstance(el, ui.select) and el.label == "Pole z katalogu")
        dlg_literals = [el for el in dlg_descendants if isinstance(el, ui.input) and el.label == "Literał JSON"]
        dlg_apply = next(el for el in dlg_descendants if isinstance(el, ui.button) and el.text == "Zastosuj")

        dlg_op.value = "eq"
        dlg_left_kind.value = "field"
        dlg_left_field.value = field_id
        dlg_literals[1].value = '"Tak"'
        apply_listener = next(l for l in dlg_apply._event_listeners.values() if l.type == "click")
        apply_listener.handler(None)

        expected_cond = {
            "op": "eq",
            "left": {"kind": "field", "alias": "source", "field_id": field_id},
            "right": {"kind": "literal", "value": "Tak"},
        }
        assert json.loads(control("Warunek (JSON)").value) == expected_cond
        graph = json.loads(control("Definicja grafu (JSON)").value)
        assert graph["nodes"][-1]["condition"] == expected_cond
    container.delete()
