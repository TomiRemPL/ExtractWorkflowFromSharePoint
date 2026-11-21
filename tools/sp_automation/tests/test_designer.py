from types import SimpleNamespace
import tkinter as tk

import pytest

from tools.sp_automation.catalog import Catalog, FieldRecord, ListRecord
from tools.sp_automation.designer import WorkflowDesigner, WorkflowDraft, _ConditionEditor
from tools.sp_automation.engine import simulate
from tools.sp_automation.models import GraphError
from tools.sp_automation.tests.test_engine import GOAL, REL, RELATED_GOAL, SOURCE, TARGET, graph, snapshot


def test_draft_roundtrip_and_history():
    draft = WorkflowDraft(graph())
    assert draft.graph().to_dict() == graph()
    value = draft.graph().to_dict()
    value["layout"]["start"]["x"] = 20
    draft.replace(value)
    assert draft.dirty
    assert draft.undo()
    assert not draft.dirty
    assert draft.redo()
    assert draft.dirty


@pytest.fixture
def designer():
    root = tk.Tk()
    root.geometry("1200x700+0+0")
    frame = WorkflowDesigner(root, graph())
    frame.pack(fill="both", expand=True)
    root.update()
    yield frame
    root.destroy()


@pytest.fixture
def local_path(tmp_path):
    return tmp_path / "designer.json"


def _event_at(frame, x, y):
    canvas = frame.canvas
    return SimpleNamespace(
        x=x * frame._scale - canvas.canvasx(0),
        y=y * frame._scale - canvas.canvasy(0),
    )


def test_drag_from_palette_connect_branches_and_reconnect(designer):
    frame = designer
    before = len(frame.get_draft()["nodes"])
    frame._palette_start("condition")
    canvas = frame.canvas
    event = _event_at(frame, 280, 220)
    event.x_root = int(event.x + canvas.winfo_rootx())
    event.y_root = int(event.y + canvas.winfo_rooty())
    frame._palette_drop(event)
    draft = frame.get_draft()
    assert len(draft["nodes"]) == before + 1
    new = draft["nodes"][-1]["id"]
    assert draft["layout"][new] == {"x": 280, "y": 220}
    frame._press(_event_at(frame, 430, 229))
    assert frame._connecting == (new, "true")
    frame._press(_event_at(frame, 1, 34))
    # The start has no input port, so it cannot be selected as a destination.
    assert not any(e["from"] == new for e in frame.get_draft()["edges"])
    frame.connect(new, "true", "merge")
    frame.connect(new, "false", "merge")
    frame.connect(new, "true", "set")
    assert [(e["port"], e["to"]) for e in frame.get_draft()["edges"] if e["from"] == new] == [
        ("false", "merge"), ("true", "set")]
    assert {frame.canvas.itemcget(i, "text") for i in frame.canvas.find_all()
            if frame.canvas.type(i) == "text"} >= {"Tak", "Nie"}


def test_move_zoom_pan_copy_delete_and_undo(designer):
    frame = designer
    frame._press(_event_at(frame, 50, 20))
    frame._motion(_event_at(frame, 80, 60))
    frame._release(_event_at(frame, 80, 60))
    assert frame.get_draft()["layout"]["start"] == {"x": 31, "y": 42}
    frame.undo()
    assert frame.get_draft()["layout"]["start"] == {"x": 1, "y": 2}
    frame.redo()
    assert frame.get_draft()["layout"]["start"] == {"x": 31, "y": 42}
    frame.zoom(1.2)
    assert frame._scale == pytest.approx(1.2)
    old_view = frame.canvas.xview()
    frame._pan_start(SimpleNamespace(x=100, y=100))
    frame._pan_move(SimpleNamespace(x=60, y=100))
    assert frame.canvas.xview() != old_view
    frame._selected = ("node", "read")
    frame.copy()
    frame.paste()
    copy_id = frame.get_draft()["nodes"][-1]["id"]
    assert copy_id != "read"
    frame.delete_selection()
    assert copy_id not in {n["id"] for n in frame.get_draft()["nodes"]}
    frame.undo()
    assert copy_id in {n["id"] for n in frame.get_draft()["nodes"]}


def test_invalid_pending_inspector_and_cancel_preserve_document(designer, monkeypatch, local_path):
    frame = designer
    messages = []
    monkeypatch.setattr("tools.sp_automation.designer.messagebox.showerror", lambda *a, **k: messages.append(a))
    monkeypatch.setattr("tools.sp_automation.designer.messagebox.askyesnocancel", lambda *a, **k: None)
    frame._selected = ("node", "if")
    frame._inspector()
    widget = frame._form_text["condition"]
    widget.delete("1.0", "end")
    widget.insert("1.0", "{")
    original = frame.get_draft()
    assert frame.is_dirty
    assert not frame.save_file(local_path)
    assert messages
    assert not local_path.exists()
    assert not frame.open_file(local_path)
    assert frame.get_draft() == original
    assert widget.get("1.0", "end-1c") == "{"


def test_save_reopen_layout_edges_and_simulation(designer, local_path):
    frame = designer
    before = simulate(frame.get_graph(), snapshot())
    assert frame.save_file(local_path)
    assert not frame.is_dirty
    frame.connect("if", "true", "merge")
    assert frame.is_dirty
    frame.undo()
    assert not frame.is_dirty
    assert frame.open_file(local_path)
    assert frame.get_graph().to_dict() == graph()
    assert simulate(frame.get_graph(), snapshot()) == before


def test_delete_edge_validation_and_catalog_inspector(designer):
    frame = designer
    frame._selected = ("edge", 3)
    frame.delete_selection()
    with pytest.raises(GraphError, match="port"):
        frame.get_graph()
    frame.undo()
    field_id = graph()["nodes"][1]["field_id"]
    field = FieldRecord("Internal", "Nazwa", "Lookup", field_id, "RestName")
    record = ListRecord(graph()["source_list_id"], "Lista", fields={"Internal": field})
    frame.catalog = Catalog(lists={record.id: record})
    frame._selected = ("node", "read")
    frame._inspector()
    labels = frame._catalog_fields()
    assert any("Lista / Nazwa | Internal | REST: RestName | Lookup" in label for label in labels)
    assert frame._field_choices["field_id"][frame._form_vars["field_id"].get()] == field_id


def test_set_catalog_refreshes_clean_inspector_and_preserves_pending_edits(designer):
    frame = designer
    field_id = graph()["nodes"][1]["field_id"]

    def catalog(title):
        field = FieldRecord("Internal", title, "Lookup", field_id)
        record = ListRecord(SOURCE, "Lista", fields={"Internal": field})
        return Catalog(lists={record.id: record})

    frame._selected = ("node", "read")
    frame._inspector()
    before = frame.get_draft()
    frame.set_catalog(catalog("Stare"))
    assert "Stare" in frame._form_vars["field_id"].get()
    assert frame.get_draft() == before
    assert not frame.is_dirty

    frame._form_vars["as"].set("zmieniony")
    old_field = frame._form_vars["field_id"]
    new_catalog = catalog("Nowe")
    frame.set_catalog(new_catalog)
    assert frame.catalog is new_catalog
    assert frame._form_vars["field_id"] is old_field
    assert frame._form_vars["as"].get() == "zmieniony"
    assert frame.is_dirty
    assert frame.apply_inspector()
    assert frame.get_draft()["nodes"][1]["as"] == "zmieniony"
    assert "Nowe" in frame._form_vars["field_id"].get()

    frame._selected = ("node", "if")
    frame._inspector()
    text = frame._form_text["condition"]
    text.delete("1.0", "end")
    text.insert("1.0", "{")
    frame.set_catalog(catalog("Kolejne"))
    assert frame._form_text["condition"] is text
    assert text.get("1.0", "end-1c") == "{"


def test_inspector_applies_and_validation_rejects_bad_graph(designer, monkeypatch, local_path):
    frame = designer
    messages = []
    monkeypatch.setattr("tools.sp_automation.designer.messagebox.showerror", lambda *a, **k: messages.append(a))
    frame._selected = ("node", "if")
    frame._inspector()
    frame._form_vars["merge"].set("end")
    assert frame.apply_inspector()
    assert frame.get_draft()["nodes"][2]["merge"] == "end"
    assert not frame.save_file(local_path)
    assert messages and not local_path.exists()
    frame.undo()
    assert frame.get_graph().to_dict() == graph()


def test_structured_condition_builder_and_value_preserve_simulation(designer, local_path):
    frame = designer
    before = simulate(frame.get_graph(), snapshot())
    frame._selected = ("node", "if")
    frame._inspector()
    result = []
    dialog = _ConditionEditor(frame, {"op": "exists", "alias": "mechanism"}, {}, result.append)
    dialog.op.set("and")
    dialog._replace()
    root = next(i for i, path in dialog.paths.items() if path == ())
    # Keep the existing child, then add two independently configured conditions.
    dialog.tree.selection_set(root)
    dialog._selected()
    child = next(i for i, path in dialog.paths.items() if path == ("conditions", 0))
    dialog.tree.selection_set(child)
    dialog._selected()
    dialog.op.set("exists")
    dialog.alias.set("mechanism")
    dialog._replace()
    root = next(i for i, path in dialog.paths.items() if path == ())
    dialog.tree.selection_set(root)
    dialog._selected()
    dialog.op.set("empty")
    dialog.left.set_value({"kind": "field", "alias": "source", "field_id": GOAL})
    dialog._add()
    root = next(i for i, path in dialog.paths.items() if path == ())
    dialog.tree.selection_set(root)
    dialog._selected()
    dialog.op.set("not_empty")
    dialog.left.set_value({"kind": "field", "alias": "mechanism", "field_id": RELATED_GOAL})
    dialog._add()
    dialog._accept()
    frame._set_json(frame._form_text["condition"], result[0])
    assert frame.apply_inspector()
    assert frame.get_graph().to_dict()["nodes"][2]["condition"] == graph()["nodes"][2]["condition"]
    assert frame.save_file(local_path)
    assert frame.open_file(local_path)
    assert simulate(frame.get_graph(), snapshot()) == before


def test_canvas_events_connect_and_cancel(designer):
    frame = designer
    condition = frame.add_node("condition", 40, 100)
    target = frame.add_node("merge", 250, 100)
    canvas = frame.canvas
    canvas.update()
    def click(x, y):
        event = _event_at(frame, x, y)
        canvas.event_generate("<ButtonPress-1>", x=round(event.x), y=round(event.y))
        canvas.event_generate("<ButtonRelease-1>", x=round(event.x), y=round(event.y))
        canvas.update()
    click(190, 109)
    assert frame._connecting == (condition, "true")
    click(250, 132)
    assert {"from": condition, "port": "true", "to": target} in frame.get_draft()["edges"]
    click(190, 145)
    assert frame._connecting == (condition, "false")
    frame.cancel_connection()
    assert frame._connecting is None
    assert not any(e["from"] == condition and e["port"] == "false" for e in frame.get_draft()["edges"])


def test_pending_changes_notify_and_close_can_be_cancelled(designer, monkeypatch):
    frame = designer
    notifications = []
    frame.on_change = lambda current: notifications.append(current.is_dirty)
    frame._form_vars["name"].set("Nowa nazwa")
    assert notifications[-1]
    monkeypatch.setattr("tools.sp_automation.designer.messagebox.askyesnocancel", lambda *a, **k: None)
    assert not frame.confirm_close()
    assert frame._form_vars["name"].get() == "Nowa nazwa"


def test_duplicate_json_keys_do_not_silently_change_condition(designer, monkeypatch):
    frame = designer
    monkeypatch.setattr("tools.sp_automation.designer.messagebox.showerror", lambda *a, **k: None)
    frame._selected = ("node", "if")
    frame._inspector()
    widget = frame._form_text["condition"]
    widget.delete("1.0", "end")
    widget.insert("1.0", '{"op":"exists","op":"empty","alias":"source"}')
    assert not frame.apply_inspector()
    assert frame.get_draft()["nodes"][2]["condition"] == graph()["nodes"][2]["condition"]


def test_create_definition_from_empty_designer_and_reopen(designer, local_path):
    root = designer.master
    designer.destroy()
    frame = WorkflowDesigner(root)
    frame.pack(fill="both", expand=True)
    root.update()
    for key, value in {
        "id": "built", "name": "Built", "site": snapshot()["site"], "source_list_id": SOURCE,
        "schema_fingerprint": "schema-1", "max_updates": "10",
    }.items():
        frame._form_vars[key].set(value)
    assert frame.apply_inspector()

    def drop(kind):
        frame._palette_start(kind)
        canvas = frame.canvas
        point = _event_at(frame, 200, 200)
        point.x_root = int(point.x + canvas.winfo_rootx())
        point.y_root = int(point.y + canvas.winfo_rooty())
        frame._palette_drop(point)
        return frame.get_draft()["nodes"][-1]["id"]

    read = drop("lookup")
    frame._form_vars["field_id"].set(REL)
    frame._form_vars["as"].set("mechanism")
    assert frame.apply_inspector()
    condition = drop("condition")
    merge = drop("merge")
    assign = drop("assign")
    frame._form_vars["field_id"].set(GOAL)
    frame._expression_builder()
    dialog = next(w for w in frame.winfo_children() if isinstance(w, tk.Toplevel))
    editor = next(w for w in dialog.winfo_children() if hasattr(w, "set_value"))
    editor.set_value({"kind": "field", "alias": "mechanism", "field_id": RELATED_GOAL})
    next(w for w in dialog.winfo_children() if w.winfo_class() == "TButton" and w.cget("text") == "Zastosuj").invoke()
    assert frame.apply_inspector()
    end = drop("end")
    frame._selected = ("node", condition)
    frame._inspector()
    frame._form_vars["merge"].set(merge)
    frame._set_json(frame._form_text["condition"], graph()["nodes"][2]["condition"])
    assert frame.apply_inspector()
    for source, port, target in (
        ("start", "next", read), (read, "next", condition), (condition, "true", assign),
        (condition, "false", merge), (assign, "next", merge), (merge, "next", end),
    ):
        frame.connect(source, port, target)
    frame.auto_layout()
    built = frame.get_graph()
    assert [(change.item_id, change.field_id, change.new_value)
            for change in simulate(built, snapshot()).changes] == [(1, GOAL, 12)]
    assert frame.save_file(local_path)
    assert frame.open_file(local_path)
    assert frame.get_graph() == built


def test_failed_save_does_not_replace_existing_file(designer, monkeypatch, local_path):
    local_path.write_text("original", encoding="utf-8")
    monkeypatch.setattr("tools.sp_automation.designer.messagebox.showerror", lambda *a, **k: None)
    def fail_replace(source, target):
        raise OSError("simulated failure")
    monkeypatch.setattr("tools.sp_automation.designer.os.replace", fail_replace)
    designer._form_vars["name"].set("Edited")
    assert not designer.save_file(local_path)
    assert local_path.read_text(encoding="utf-8") == "original"
    assert designer.is_dirty
    assert not list(local_path.parent.glob(f".{local_path.name}.*.tmp"))


def test_save_does_not_remove_existing_temporary_file(designer, monkeypatch, local_path):
    monkeypatch.setattr("tools.sp_automation.designer.messagebox.showerror", lambda *a, **k: None)
    monkeypatch.setattr("tools.sp_automation.designer.uuid4", lambda: SimpleNamespace(hex="existing"))
    temporary = local_path.with_name(f".{local_path.name}.existing.tmp")
    temporary.write_text("untouched", encoding="utf-8")
    assert not designer.save_file(local_path)
    assert temporary.read_text(encoding="utf-8") == "untouched"


def test_new_document_preserves_unsaved_draft_if_cancelled(designer, monkeypatch):
    designer.add_node("end", 500, 300)
    before = designer.get_draft()
    monkeypatch.setattr("tools.sp_automation.designer.messagebox.askyesnocancel", lambda *a, **k: None)
    assert not designer.new_document()
    assert designer.get_draft() == before
    monkeypatch.setattr("tools.sp_automation.designer.messagebox.askyesnocancel", lambda *a, **k: False)
    assert designer.new_document()
    assert [node["type"] for node in designer.get_draft()["nodes"]] == ["start"]


def test_field_inspector_uses_alias_list_and_never_guesses_ambiguous_names(designer):
    frame = designer
    shared = GOAL
    source = ListRecord(SOURCE, "Źródło", fields={
        "relation": FieldRecord("relation", "Relacja", "Lookup", REL, lookup_list=TARGET),
        "goal": FieldRecord("goal", "Cel źródła", "Lookup", shared),
    })
    target = ListRecord(TARGET, "Cel", fields={
        "goal": FieldRecord("goal", "Inne znaczenie", "Text", shared),
    })
    frame.catalog = Catalog(lists={TARGET: target, SOURCE: source})
    frame._selected = ("node", "set")
    frame._inspector()
    assert "Źródło / Cel źródła" in frame._form_vars["field_id"].get()
    frame._form_vars["alias"].set("mechanism")
    assert frame.apply_inspector()
    assert "Cel / Inne znaczenie" in frame._form_vars["field_id"].get()
    frame._form_vars["alias"].set("unknown")
    assert frame.apply_inspector()
    assert frame._form_vars["field_id"].get() == shared
