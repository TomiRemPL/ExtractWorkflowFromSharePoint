"""Offline graph designer; editing a draft never executes SharePoint operations."""

from __future__ import annotations

from copy import deepcopy
import json
import logging
import math
import os
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable, cast
from uuid import uuid4

from tools.sp_automation.catalog import normalize_guid
from tools.sp_automation.models import Graph, GraphError
from tools.sp_automation.snapshot_adapter import catalog_graph_fingerprint


_TITLES = {
    "start": "Start",
    "lookup": "Odczyt relacji",
    "condition": "Warunek",
    "assign": "Ustaw pole",
    "merge": "Scalenie",
    "skip": "Pomiń",
    "end": "Koniec",
}
_PORTS = {"condition": ("true", "false"), "skip": (), "end": ()}
_WIDTH, _HEIGHT = 150, 64


def _parse_json(text: str):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Powtórzony klucz: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"Niepoprawna liczba: {value}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


def new_workflow() -> dict:
    return {
        "schema_version": 1, "text_policy": "exact", "id": uuid4().hex, "name": "Nowy algorytm",
        "site": "", "source_list_id": "", "schema_fingerprint": "",
        "max_updates": 0, "scope": {"type": "all"},
        "nodes": [{"id": "start", "type": "start"}],
        "edges": [], "layout": {"start": {"x": 100, "y": 100}},
    }


def _node(kind: str, node_id: str) -> dict:
    result: dict[str, Any] = {"id": node_id, "type": kind}
    if kind == "lookup":
        result.update({"from": "source", "field_id": "", "as": ""})
    elif kind == "condition":
        result.update({"merge": "", "condition": {"op": "exists", "alias": "source"}})
    elif kind == "assign":
        result.update({"alias": "source", "field_id": "", "value": {"kind": "literal", "value": None}})
    return result


class _ExpressionEditor(ttk.LabelFrame):
    """Controls for every expression kind in the graph contract."""

    def __init__(self, parent, title: str, fields: dict[str, str]):
        super().__init__(parent, text=title)
        self.fields = fields
        self.kind = tk.StringVar(value="literal")
        self.alias = tk.StringVar(value="source")
        self.field = tk.StringVar()
        self.literal = tk.StringVar(value="null")
        for label, variable, choices in (
            ("Rodzaj", self.kind, ("field", "literal", "count")),
            ("Alias", self.alias, ()),
            ("Pole", self.field, tuple(fields)),
            ("Literał JSON", self.literal, ()),
        ):
            row = ttk.Frame(self)
            row.pack(fill="x")
            ttk.Label(row, text=label, width=13).pack(side="left")
            ttk.Combobox(row, textvariable=variable, values=choices, width=40).pack(side="left", fill="x", expand=True)

    def set_value(self, value: dict) -> None:
        self.kind.set(value.get("kind", "literal"))
        self.alias.set(value.get("alias", "source"))
        field_id = value.get("field_id", "")
        matches = [label for label, ident in self.fields.items() if ident == field_id]
        self.field.set(matches[0] if len(matches) == 1 else field_id)
        self.literal.set(json.dumps(value.get("value"), ensure_ascii=False))

    def get_value(self) -> dict:
        kind = self.kind.get()
        if kind == "field":
            return {"kind": "field", "alias": self.alias.get(),
                    "field_id": self.fields.get(self.field.get(), self.field.get())}
        if kind == "count":
            return {"kind": "count", "alias": self.alias.get()}
        if kind == "literal":
            return {"kind": "literal", "value": _parse_json(self.literal.get())}
        raise ValueError("Nieznany rodzaj wyrażenia")


class _ConditionEditor(tk.Toplevel):
    """Visual AST editor; no expression or condition is evaluated here."""

    _OPS = ("and", "or", "not", "exists", "empty", "not_empty",
            "eq", "ne", "lt", "le", "gt", "ge", "any", "all")

    def __init__(self, owner, value: dict, fields: dict[str, str], on_accept):
        super().__init__(owner)
        self.title("Konstruktor warunku")
        self.transient(owner.winfo_toplevel())
        self.value = deepcopy(value)
        self.on_accept = on_accept
        self.paths: dict[str, tuple] = {}
        self.tree = ttk.Treeview(self, show="tree", height=12)
        self.tree.grid(row=0, column=0, rowspan=5, sticky="nsew", padx=5, pady=5)
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(0, weight=1)
        panel = ttk.Frame(self)
        panel.grid(row=0, column=1, sticky="nsew", padx=5)
        self.op = tk.StringVar(value="exists")
        self.alias = tk.StringVar(value="source")
        ttk.Label(panel, text="Operator").pack(anchor="w")
        ttk.Combobox(panel, textvariable=self.op, values=self._OPS, state="readonly").pack(fill="x")
        ttk.Label(panel, text="Alias (exists / any / all)").pack(anchor="w")
        ttk.Entry(panel, textvariable=self.alias).pack(fill="x")
        self.left = _ExpressionEditor(panel, "Wartość / lewa strona", fields)
        self.right = _ExpressionEditor(panel, "Prawa strona", fields)
        self.left.pack(fill="x")
        self.right.pack(fill="x")
        ttk.Button(panel, text="Zastąp zaznaczony warunek", command=self._replace).pack(fill="x")
        ttk.Button(panel, text="Dodaj warunek do AND / OR", command=self._add).pack(fill="x")
        ttk.Button(panel, text="Usuń wybrany warunek", command=self._delete).pack(fill="x")
        ttk.Label(panel, text="ANY/ALL wiążą element pod aliasem item. "
                  "Puste: ANY=false, ALL=true; COUNT=0.", wraplength=440).pack(anchor="w")
        ttk.Button(self, text="Zastosuj", command=self._accept).grid(row=5, column=0, sticky="ew")
        ttk.Button(self, text="Anuluj", command=self.destroy).grid(row=5, column=1, sticky="ew")
        self._render(())
        self.grab_set()

    def _at(self, path: tuple):
        result = self.value
        for part in path:
            result = result[part]
        return result

    def _render(self, select: tuple) -> None:
        self.tree.delete(*self.tree.get_children())
        self.paths.clear()

        def append(value, path, parent=""):
            if not isinstance(value, dict):
                raise ValueError("Warunek musi być obiektem")
            op = value.get("op", "?")
            ident = self.tree.insert(parent, "end", text=str(op), open=True)
            self.paths[ident] = path
            if path == select:
                self.tree.selection_set(ident)
            if op in ("and", "or"):
                for index, child in enumerate(value.get("conditions", [])):
                    append(child, path + ("conditions", index), ident)
            elif op in ("not", "any", "all") and "condition" in value:
                append(value["condition"], path + ("condition",), ident)

        append(self.value, ())
        self._selected()

    def _selected_path(self) -> tuple:
        selected = self.tree.selection()
        return self.paths[selected[0]] if selected else ()

    def _selected(self, event=None) -> None:
        value = self._at(self._selected_path())
        self.op.set(value.get("op", "exists"))
        self.alias.set(value.get("alias", "source"))
        self.left.set_value(value.get("value", value.get("left", {"kind": "literal", "value": None})))
        self.right.set_value(value.get("right", {"kind": "literal", "value": None}))

    def _construct(self, old: dict | None = None) -> dict:
        op = self.op.get()
        old = old or {}
        default = {"op": "exists", "alias": "source"}
        if op in ("and", "or"):
            return {"op": op, "conditions": deepcopy(old.get("conditions", [default]))}
        if op in ("not", "any", "all"):
            result = {"op": op, "condition": deepcopy(old.get("condition", default))}
            if op in ("any", "all"):
                result["alias"] = self.alias.get()
            return result
        if op == "exists":
            return {"op": op, "alias": self.alias.get()}
        if op in ("empty", "not_empty"):
            return {"op": op, "value": self.left.get_value()}
        if op in ("eq", "ne", "lt", "le", "gt", "ge"):
            return {"op": op, "left": self.left.get_value(), "right": self.right.get_value()}
        raise ValueError("Nieznany operator")

    def _replace(self) -> None:
        path = self._selected_path()
        try:
            value = self._construct(self._at(path))
            if path:
                self._at(path[:-1])[path[-1]] = value
            else:
                self.value = value
            self._render(path)
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Niepoprawny warunek", str(exc), parent=self)

    def _add(self) -> None:
        path = self._selected_path()
        parent = self._at(path)
        if parent.get("op") not in ("and", "or"):
            messagebox.showerror("Niepoprawny warunek", "Wybierz AND albo OR.", parent=self)
            return
        try:
            child = self._construct()
            parent["conditions"].append(child)
            self._render(path + ("conditions", len(parent["conditions"])-1))
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Niepoprawny warunek", str(exc), parent=self)

    def _delete(self) -> None:
        path = self._selected_path()
        if len(path) >= 2 and path[-2] == "conditions":
            del self._at(path[:-1])[path[-1]]
            self._render(path[:-2])
        else:
            messagebox.showerror("Nie można usunąć", "Wybierz dziecko AND albo OR.", parent=self)

    def _accept(self) -> None:
        self.on_accept(deepcopy(self.value))
        self.destroy()


class WorkflowDraft:
    """Mutable editing state, separate from the validated immutable graph."""

    def __init__(self, value: Graph | dict):
        self.data = value.to_dict() if isinstance(value, Graph) else deepcopy(value)
        self._undo: list[dict] = []
        self._redo: list[dict] = []
        self._saved = deepcopy(self.data)

    @property
    def dirty(self) -> bool:
        return self.data != self._saved

    def replace(self, value: dict) -> None:
        if value != self.data:
            self._undo.append(deepcopy(self.data))
            self._redo.clear()
            self.data = deepcopy(value)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(deepcopy(self.data))
        self.data = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(deepcopy(self.data))
        self.data = self._redo.pop()
        return True

    def graph(self) -> Graph:
        try:
            text = json.dumps(self.data, ensure_ascii=False, allow_nan=False)
        except (ValueError, TypeError, RecursionError) as exc:
            raise GraphError("Niepoprawne dane definicji") from exc
        return Graph.from_json(text)

    def mark_saved(self) -> None:
        self._saved = deepcopy(self.data)


class WorkflowDesigner(ttk.Frame):
    """Reusable offline editor. Call get_graph() to obtain a validated Graph.

    The draft can be incomplete. on_change, if supplied, receives the frame.
    set_graph() replaces the current document; callers should check is_dirty first.
    """

    def __init__(self, parent: tk.Misc, graph: Graph | dict | None = None,
                 catalog=None, on_change=None, on_simulate: Callable[[Graph], None] | None = None,
                 on_online_preview: Callable[[Graph], None] | None = None):
        super().__init__(parent)
        self.catalog = catalog
        self.on_change = on_change
        self.on_simulate: Callable[[Graph], None] | None = on_simulate
        self.on_online_preview: Callable[[Graph], None] | None = on_online_preview
        self._draft = WorkflowDraft(graph if graph is not None else new_workflow())
        self._selected: tuple[str, str | int] | None = None
        self._connecting: tuple[str, str] | None = None
        self._drag: tuple[str, float, float] | None = None
        self._palette_kind: str | None = None
        self._clipboard: dict | None = None
        self._scale = 1.0
        self._path: Path | None = None
        self._form_vars: dict[str, tk.Variable] = {}
        self._form_text: dict[str, tk.Text] = {}
        self._field_choices: dict[str, dict[str, str]] = {}
        self._form_original: dict = {}
        self._build()
        self._refresh()

    @property
    def is_dirty(self) -> bool:
        return self._draft.dirty or self._form_changed()

    def get_draft(self) -> dict:
        """Return a detached copy; unapplied inspector edits are not included."""
        return deepcopy(self._draft.data)

    def get_graph(self) -> Graph:
        """Validate the current applied draft. Invalid or pending edits raise."""
        if self._form_changed():
            raise GraphError("Zastosuj lub anuluj zmiany w inspektorze")
        return self._draft.graph()

    def set_graph(self, graph: Graph | dict) -> None:
        """Replace the document with a validated graph (does not prompt)."""
        value = graph if isinstance(graph, Graph) else Graph.from_dict(graph)
        self._draft = WorkflowDraft(value)
        self._selected = None
        self._connecting = None
        self._path = None
        self._refresh()
        self._notify()

    def set_catalog(self, catalog) -> None:
        """Update catalog choices without discarding unapplied inspector edits."""
        self.catalog = catalog
        if not self._form_changed():
            self._inspector()

    def set_catalog_fingerprint(self) -> None:
        if self.catalog is None or not self._resolve_form():
            return
        try:
            data = self.get_draft()
            data["site"] = self.catalog.site_url
            data["schema_fingerprint"] = data.get("schema_fingerprint") or "pending"
            graph = Graph.from_dict(data)
            data["schema_fingerprint"] = catalog_graph_fingerprint(self.catalog, graph)
        except (GraphError, ValueError) as exc:
            messagebox.showerror("Nie można ustawić fingerprintu", str(exc), parent=self)
            return
        self._replace(data)

    def simulate_offline(self) -> None:
        if self.on_simulate is None or not self._resolve_form():
            return
        try:
            graph = self.get_graph()
        except GraphError as exc:
            messagebox.showerror("Graf jest niepoprawny", str(exc), parent=self)
            return
        self.on_simulate(graph)

    def preview_online(self) -> None:
        if self.on_online_preview is None or not self._resolve_form():
            return
        try:
            graph = self.get_graph()
        except GraphError as exc:
            messagebox.showerror("Graf jest niepoprawny", str(exc), parent=self)
            return
        self.on_online_preview(graph)

    def _notify(self) -> None:
        if self.on_change:
            self.on_change(self)

    def _build(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")
        commands = (
            ("Nowy", self.new_document), ("Otwórz", self.open_file), ("Zapisz", self.save_file),
            ("Cofnij", self.undo), ("Ponów", self.redo),
            ("Kopiuj", self.copy), ("Wklej", self.paste),
            ("Usuń", self.delete_selection), ("Układ", self.auto_layout),
            ("−", lambda: self.zoom(1 / 1.2)), ("+", lambda: self.zoom(1.2)),
            ("Właściwości", self.select_document), ("Fingerprint", self.set_catalog_fingerprint),
            ("Symuluj offline", self.simulate_offline), ("Podgląd online (GET)", self.preview_online),
        )
        for index, (label, command) in enumerate(commands):
            ttk.Button(toolbar, text=label, command=command).grid(row=index // 6, column=index % 6, sticky="ew")
        palette = ttk.LabelFrame(self, text="Paleta — przeciągnij na płótno")
        palette.grid(row=1, column=0, sticky="ns")
        for kind, title in _TITLES.items():
            label = ttk.Label(palette, text=title, relief="raised", padding=6, cursor="hand2")
            label.pack(fill="x", padx=4, pady=2)
            label.bind("<ButtonPress-1>", lambda e, k=kind: self._palette_start(k))
            label.bind("<ButtonRelease-1>", self._palette_drop)

        canvas_frame = ttk.Frame(self)
        canvas_frame.grid(row=1, column=1, sticky="nsew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(canvas_frame, background="white", highlightthickness=0,
                                scrollregion=(-1000, -1000, 3000, 3000))
        self.canvas.grid(row=0, column=0, sticky="nsew")
        hbar = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        vbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        hbar.grid(row=1, column=0, sticky="ew")
        vbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        self.canvas.xview_moveto(0.25)
        self.canvas.yview_moveto(0.25)
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<ButtonPress-2>", self._pan_start)
        self.canvas.bind("<B2-Motion>", self._pan_move)
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Button-4>", lambda e: self.zoom(1.2))
        self.canvas.bind("<Button-5>", lambda e: self.zoom(1 / 1.2))
        self.canvas.bind("<Delete>", lambda e: self.delete_selection())
        self.canvas.bind("<Control-z>", lambda e: self.undo())
        self.canvas.bind("<Control-y>", lambda e: self.redo())
        self.canvas.bind("<Control-c>", lambda e: self.copy())
        self.canvas.bind("<Control-v>", lambda e: self.paste())
        self.canvas.bind("<Escape>", lambda e: self.cancel_connection())

        self.inspector = ttk.LabelFrame(self, text="Inspektor")
        self.inspector.grid(row=1, column=2, sticky="nsew", padx=4)
        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, wraplength=800).grid(row=2, column=0, columnspan=3, sticky="ew")

    def _form_changed(self) -> bool:
        if not self._form_original:
            return False
        current = {key: var.get() for key, var in self._form_vars.items()}
        current.update({key: widget.get("1.0", "end-1c") for key, widget in self._form_text.items()})
        return current != self._form_original

    def _resolve_form(self) -> bool:
        if not self._form_changed():
            return True
        answer = messagebox.askyesnocancel("Niezastosowane zmiany",
            "Zastosować zmiany w inspektorze? Nie — odrzuć; Anuluj — wróć.", parent=self)
        if answer is None:
            return False
        return self.apply_inspector() if answer else True

    def _replace(self, data: dict) -> None:
        self._draft.replace(data)
        self._refresh()
        self._notify()

    def _refresh(self) -> None:
        self._draw()
        self._inspector()
        try:
            self._draft.graph()
            status = "Graf poprawny (tylko definicja; bez wykonania)."
        except GraphError as exc:
            status = f"Blokada definicji: {exc}"
        if self._draft.dirty:
            status += " • Niezapisane zmiany"
        if self._connecting:
            status += " • Wybierz port wejściowy; Esc anuluje"
        self.status.set(status)

    def _world(self, x: float, y: float) -> tuple[float, float]:
        return self.canvas.canvasx(x) / self._scale, self.canvas.canvasy(y) / self._scale

    def _position(self, node_id: str, index: int) -> tuple[float, float]:
        pos = self._draft.data.get("layout", {}).get(node_id)
        if isinstance(pos, dict) and all(isinstance(pos.get(k), (int, float)) for k in ("x", "y")):
            return pos["x"], pos["y"]
        return 80 + (index % 4) * 210, 80 + (index // 4) * 140

    def _draw(self) -> None:
        self.canvas.delete("all")
        nodes = self._draft.data.get("nodes", [])
        positions = {n["id"]: self._position(n["id"], i) for i, n in enumerate(nodes)}
        kinds = {n["id"]: n["type"] for n in nodes}
        connected = {(edge["from"], edge["port"]) for edge in self._draft.data.get("edges", [])}
        s = self._scale
        for index, edge in enumerate(self._draft.data.get("edges", [])):
            if edge["from"] not in positions or edge["to"] not in positions:
                continue
            x1, y1 = positions[edge["from"]]
            x2, y2 = positions[edge["to"]]
            ports = _PORTS.get(kinds[edge["from"]], ("next",))
            offset = 19 if len(ports) == 1 else (9 if edge["port"] == "true" else 45)
            y1 += offset
            y2 += _HEIGHT / 2
            tag = f"edge:{index}"
            selected = self._selected == ("edge", index)
            self.canvas.create_line((x1 + _WIDTH) * s, y1 * s, x2 * s, y2 * s,
                                    arrow="last", width=3 if selected else 2,
                                    fill="#b45309" if selected else "#475569", tags=(tag,))
            label = {"true": "Tak", "false": "Nie", "next": ""}.get(edge["port"], edge["port"])
            if label:
                self.canvas.create_text((x1 + _WIDTH + x2) / 2 * s, (y1 + y2) / 2 * s - 8,
                                        text=label, fill="#7c2d12", tags=(tag,))
        for node in nodes:
            node_id, kind = node["id"], node["type"]
            x, y = positions[node_id]
            tag = f"node:{node_id}"
            color = "#dbeafe" if self._selected == ("node", node_id) else "#f8fafc"
            ports = _PORTS.get(kind, ("next",))
            blocked = any((node_id, port) not in connected for port in ports)
            if kind == "condition":
                blocked |= kinds.get(node.get("merge")) != "merge"
            elif kind in ("lookup", "assign"):
                blocked |= not node.get("field_id")
            self.canvas.create_rectangle(x*s, y*s, (x+_WIDTH)*s, (y+_HEIGHT)*s,
                                         fill=color, outline="#dc2626" if blocked else "#1e40af",
                                         width=2, tags=(tag,))
            self.canvas.create_text((x+_WIDTH/2)*s, (y+22)*s, text=_TITLES.get(kind, kind),
                                    width=(_WIDTH-16)*s, tags=(tag,))
            self.canvas.create_text((x+_WIDTH/2)*s, (y+43)*s, text=node_id,
                                    width=(_WIDTH-16)*s, fill="#475569", tags=(tag,))
            if kind != "start":
                self.canvas.create_oval((x-6)*s, (y+_HEIGHT/2-6)*s, (x+6)*s, (y+_HEIGHT/2+6)*s,
                                        fill="#2563eb", tags=(f"input:{node_id}",))
            for port in ports:
                offset = 19 if len(ports) == 1 else (9 if port == "true" else 45)
                self.canvas.create_oval((x+_WIDTH-6)*s, (y+offset-6)*s, (x+_WIDTH+6)*s, (y+offset+6)*s,
                                        fill="#16a34a" if port != "false" else "#dc2626",
                                        tags=(f"output:{node_id}:{port}",))
                if len(ports) > 1:
                    self.canvas.create_text((x+_WIDTH-15)*s, (y+offset)*s, anchor="e",
                                            text="Tak" if port == "true" else "Nie", tags=(tag,))
        bounds = self.canvas.bbox("all")
        if bounds:
            left, top = self.canvas.canvasx(0), self.canvas.canvasy(0)
            old = tuple(float(v) for v in self.canvas.tk.splitlist(self.canvas.cget("scrollregion")))
            region = (min(old[0], bounds[0]-200), min(old[1], bounds[1]-200),
                      max(old[2], bounds[2]+200), max(old[3], bounds[3]+200))
            if region != old:
                self.canvas.configure(scrollregion=region)
                self.canvas.xview_moveto((left-region[0])/(region[2]-region[0]))
                self.canvas.yview_moveto((top-region[1])/(region[3]-region[1]))

    def _palette_start(self, kind: str) -> None:
        self._palette_kind = kind

    def _palette_drop(self, event: tk.Event) -> None:
        kind, self._palette_kind = self._palette_kind, None
        if not kind or self.winfo_containing(event.x_root, event.y_root) != self.canvas:
            return
        x, y = self._world(event.x_root - self.canvas.winfo_rootx(), event.y_root - self.canvas.winfo_rooty())
        self.add_node(kind, x, y)

    def add_node(self, kind: str, x: float, y: float) -> str | None:
        if kind not in _TITLES or not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("Invalid node")
        if not self._resolve_form():
            return None
        data = self.get_draft()
        node_id = f"{kind}_{uuid4().hex[:8]}"
        data["nodes"].append(_node(kind, node_id))
        data.setdefault("layout", {})[node_id] = {"x": x, "y": y}
        self._selected = ("node", node_id)
        self._replace(data)
        return node_id

    def connect(self, source: str, port: str, target: str) -> None:
        if not self._resolve_form():
            return
        data = self.get_draft()
        nodes = {n["id"]: n for n in data["nodes"]}
        if (source not in nodes or target not in nodes or nodes[target]["type"] == "start"
                or port not in _PORTS.get(nodes[source]["type"], ("next",))):
            raise ValueError("Invalid port")
        data["edges"] = [e for e in data["edges"] if (e["from"], e["port"]) != (source, port)]
        data["edges"].append({"from": source, "port": port, "to": target})
        self._connecting = None
        self._replace(data)

    def _hit(self, event: tk.Event) -> str:
        x, y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x-4, y-4, x+4, y+4)):
            tags = self.canvas.gettags(item)
            if tags:
                return tags[0]
        return ""

    def _press(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        hit = self._hit(event)
        if not self._resolve_form():
            return
        if hit.startswith("output:"):
            node_id, port = hit[len("output:"):].rsplit(":", 1)
            self._connecting = (node_id, port)
            self._refresh()
        elif hit.startswith("input:") and self._connecting:
            self.connect(*self._connecting, hit.split(":", 1)[1])
        elif hit.startswith("node:"):
            node_id = hit.split(":", 1)[1]
            self._selected = ("node", node_id)
            x, y = self._world(event.x, event.y)
            self._drag = (node_id, x, y)
            self._refresh()
        elif hit.startswith("edge:"):
            self._selected = ("edge", int(hit.split(":", 1)[1]))
            self._refresh()
        else:
            self._selected = None
            self._connecting = None
            self._refresh()

    def _motion(self, event: tk.Event) -> None:
        if not self._drag:
            return
        node_id, start_x, start_y = self._drag
        x, y = self._world(event.x, event.y)
        dx, dy = (x-start_x)*self._scale, (y-start_y)*self._scale
        self._draw()
        self.canvas.move(f"node:{node_id}", dx, dy)

    def _release(self, event: tk.Event) -> None:
        if not self._drag:
            return
        node_id, start_x, start_y = self._drag
        self._drag = None
        x, y = self._world(event.x, event.y)
        dx, dy = x-start_x, y-start_y
        if abs(dx) + abs(dy) < 1:
            self._draw()
            return
        data = self.get_draft()
        index = next(i for i, node in enumerate(data["nodes"]) if node["id"] == node_id)
        old_x, old_y = self._position(node_id, index)
        data.setdefault("layout", {})[node_id] = {"x": old_x+dx, "y": old_y+dy}
        self._replace(data)

    def _pan_start(self, event: tk.Event) -> None:
        self.canvas.scan_mark(event.x, event.y)

    def _pan_move(self, event: tk.Event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _wheel(self, event: tk.Event) -> None:
        self.zoom(1.2 if event.delta > 0 else 1 / 1.2)

    def zoom(self, factor: float) -> None:
        self._scale = max(0.35, min(2.5, self._scale * factor))
        self._draw()

    def cancel_connection(self) -> None:
        self._connecting = None
        self.status.set(self.status.get().replace(" • Wybierz port wejściowy; Esc anuluje", ""))

    def delete_selection(self) -> None:
        if not self._selected or not self._resolve_form():
            return
        data = self.get_draft()
        kind, key = self._selected
        if kind == "edge":
            del data["edges"][key]
        else:
            data["nodes"] = [n for n in data["nodes"] if n["id"] != key]
            data["edges"] = [e for e in data["edges"] if key not in (e["from"], e["to"])]
            data.get("layout", {}).pop(key, None)
        self._selected = None
        self._connecting = None
        self._replace(data)

    def copy(self) -> None:
        if self._selected and self._selected[0] == "node" and self._resolve_form():
            self._clipboard = deepcopy(next(n for n in self._draft.data["nodes"] if n["id"] == self._selected[1]))

    def paste(self) -> None:
        if not self._clipboard or not self._resolve_form():
            return
        data = self.get_draft()
        node = deepcopy(self._clipboard)
        source_id = node["id"]
        node["id"] = f"{node['type']}_{uuid4().hex[:8]}"
        source_index = next((i for i, n in enumerate(data["nodes"]) if n["id"] == source_id), 0)
        x, y = self._position(source_id, source_index)
        data["nodes"].append(node)
        data.setdefault("layout", {})[node["id"]] = {"x": x+30, "y": y+30}
        self._selected = ("node", node["id"])
        self._replace(data)

    def undo(self) -> None:
        if self._resolve_form() and self._draft.undo():
            self._selected = None
            self._connecting = None
            self._refresh()
            self._notify()

    def redo(self) -> None:
        if self._resolve_form() and self._draft.redo():
            self._selected = None
            self._connecting = None
            self._refresh()
            self._notify()

    def auto_layout(self) -> None:
        if not self._resolve_form():
            return
        data = self.get_draft()
        nodes, edges = data["nodes"], data["edges"]
        depths = {n["id"]: 0 for n in nodes if n["type"] == "start"}
        # Bounded relaxation also terminates for an invalid cyclic draft.
        for _ in range(len(nodes)):
            changed = False
            for edge in edges:
                if edge["from"] in depths and edge["to"] not in depths:
                    depths[edge["to"]] = depths[edge["from"]] + 1
                    changed = True
            if not changed:
                break
        rows: dict[int, int] = {}
        for node in nodes:
            depth = depths.get(node["id"], 0)
            row = rows.get(depth, 0)
            rows[depth] = row + 1
            data.setdefault("layout", {})[node["id"]] = {"x": 80 + 220*depth, "y": 80 + 120*row}
        self._replace(data)

    def select_document(self) -> None:
        if self._resolve_form():
            self._selected = None
            self._refresh()

    def _alias_list(self, alias: str, seen: set[str] | None = None) -> str:
        if alias == "source":
            return self._draft.data.get("source_list_id", "")
        seen = seen or set()
        if alias in seen:
            return ""
        seen.add(alias)
        matches = [n for n in self._draft.data["nodes"]
                   if n["type"] == "lookup" and n.get("as") == alias]
        if len(matches) != 1:
            return ""
        node = matches[0]
        if node.get("direction", "forward") == "reverse":
            return node.get("target_list_id", "")
        source_id = self._alias_list(node.get("from", ""), seen)
        record = getattr(self.catalog, "lists", {}).get(source_id)
        if record is None:
            return ""
        fields = [field for field in record.fields.values() if field.field_id == node.get("field_id")]
        return normalize_guid(fields[0].lookup_list) if len(fields) == 1 else ""

    def _catalog_fields(self, list_id: str = "") -> dict[str, str]:
        choices = {}
        for record in getattr(self.catalog, "lists", {}).values():
            if list_id and record.id != list_id:
                continue
            for field in record.fields.values():
                if field.field_id:
                    label = (f"{record.title} / {field.title} | {field.internal_name} | "
                             f"REST: {field.entity_property_name or 'nieznane'} | "
                             f"{field.type_as_string} | {field.field_id}")
                    choices[label] = field.field_id
        return choices

    def _catalog_lists(self) -> dict[str, str]:
        return {f"{record.title} | {record.id}": record.id
                for record in getattr(self.catalog, "lists", {}).values()}

    def _inspector(self) -> None:
        for child in self.inspector.winfo_children():
            child.destroy()
        self._form_vars = {}
        self._form_text = {}
        self._form_original = {}
        self._field_choices = {}
        data = self._draft.data
        if self._selected and self._selected[0] == "edge":
            edge = data["edges"][self._selected[1]]
            ttk.Label(self.inspector, text=f"Połączenie: {edge['from']} → {edge['to']}\n"
                      f"Port: {edge['port']}\nUsuń lub podłącz port ponownie.", wraplength=300).pack(anchor="w")
            return
        if self._selected and self._selected[0] == "node":
            node = next((n for n in data["nodes"] if n["id"] == self._selected[1]), None)
            if node is None:
                self._selected = None
                self._inspector()
                return
            ttk.Label(self.inspector, text=f"{_TITLES.get(node['type'], node['type'])} — {node['id']}",
                      wraplength=300).pack(anchor="w")
            kind = node["type"]
            if kind == "lookup":
                self._entry("from", "Alias źródła", node.get("from", ""))
                source_alias = node.get("from", "")
                source_list = (node.get("target_list_id", "") if node.get("direction") == "reverse"
                               else self._alias_list(source_alias))
                self._choice("field_id", "Pole relacji", node.get("field_id", ""), self._catalog_fields(source_list))
                self._entry("as", "Alias wyniku", node.get("as", ""))
                self._choice("direction", "Kierunek", node.get("direction", "forward"),
                             {"forward": "forward", "reverse": "reverse"})
                self._check("many", "Kolekcja", node.get("many", False))
                self._choice("target_list_id", "Lista docelowa (odwrotne)", node.get("target_list_id", ""),
                             self._catalog_lists())
            elif kind == "condition":
                merges = {n["id"]: n["id"] for n in data["nodes"] if n["type"] == "merge"}
                self._choice("merge", "Wspólne scalenie", node.get("merge", ""), merges)
                self._json_entry("condition", "Warunek (AST JSON)", node.get("condition", {}))
                ttk.Button(self.inspector, text="Konstruktor warunku", command=self._condition_builder).pack(fill="x")
                ttk.Label(self.inspector, text="ANY/ALL: pusty zbiór = false/true; COUNT = 0.",
                          wraplength=300).pack(anchor="w")
            elif kind == "assign":
                self._entry("alias", "Alias celu", node.get("alias", ""))
                self._choice("field_id", "Pole celu", node.get("field_id", ""),
                             self._catalog_fields(self._alias_list(node.get("alias", ""))))
                self._json_entry("value", "Wartość (wyrażenie JSON)", node.get("value", {}))
                ttk.Button(self.inspector, text="Konstruktor wartości", command=self._expression_builder).pack(fill="x")
            else:
                ttk.Label(self.inspector, text="Brak parametrów.").pack(anchor="w")
        else:
            ttk.Label(self.inspector, text="Definicja (bez danych wierszy); porównanie tekstu: dokładne",
                      wraplength=300).pack(anchor="w")
            for key, label in (("id", "ID"), ("name", "Nazwa"), ("site", "Adres witryny")):
                self._entry(key, label, data.get(key, ""))
            self._choice("source_list_id", "Lista źródłowa", data.get("source_list_id", ""), self._catalog_lists())
            self._entry("schema_fingerprint", "Fingerprint schematu", data.get("schema_fingerprint", ""))
            self._entry("max_updates", "Limit zmian", str(data.get("max_updates", 0)))
            self._json_entry("scope", "Zakres JSON (all / ids / view)", data.get("scope", {"type": "all"}))
        if self._form_vars or self._form_text:
            ttk.Button(self.inspector, text="Zastosuj", command=self.apply_inspector).pack(fill="x", pady=4)
            ttk.Button(self.inspector, text="Anuluj zmiany", command=self._inspector).pack(fill="x")
        self._form_original = {key: var.get() for key, var in self._form_vars.items()}
        self._form_original.update({key: widget.get("1.0", "end-1c") for key, widget in self._form_text.items()})
        for var in self._form_vars.values():
            var.trace_add("write", lambda *_: self._pending_change())
        for widget in self._form_text.values():
            widget.edit_modified(False)
            widget.bind("<<Modified>>", self._text_modified)

    def _pending_change(self) -> None:
        status = self.status.get().replace(" • Niezapisane zmiany", "")
        self.status.set(status + (" • Niezapisane zmiany" if self.is_dirty else ""))
        self._notify()

    def _text_modified(self, event: tk.Event) -> None:
        widget = cast(tk.Text, event.widget)
        if widget.edit_modified():
            widget.edit_modified(False)
            self._pending_change()

    def _entry(self, key: str, label: str, value: str) -> None:
        ttk.Label(self.inspector, text=label).pack(anchor="w")
        var = tk.StringVar(value=value)
        ttk.Entry(self.inspector, textvariable=var, width=35).pack(fill="x")
        self._form_vars[key] = var

    def _choice(self, key: str, label: str, value: str, choices: dict[str, str]) -> None:
        ttk.Label(self.inspector, text=label).pack(anchor="w")
        matches = [k for k, v in choices.items() if v == value]
        display = matches[0] if len(matches) == 1 else value
        var = tk.StringVar(value=display)
        ttk.Combobox(self.inspector, textvariable=var, values=list(choices), width=35).pack(fill="x")
        self._form_vars[key] = var
        self._field_choices[key] = choices

    def _check(self, key: str, label: str, value: bool) -> None:
        var = tk.BooleanVar(value=value)
        ttk.Checkbutton(self.inspector, text=label, variable=var).pack(anchor="w")
        self._form_vars[key] = var

    def _json_entry(self, key: str, label: str, value) -> None:
        ttk.Label(self.inspector, text=label).pack(anchor="w")
        widget = tk.Text(self.inspector, height=6, width=35, wrap="word", undo=True)
        widget.insert("1.0", json.dumps(value, ensure_ascii=False, indent=2))
        widget.pack(fill="x")
        self._form_text[key] = widget

    @staticmethod
    def _set_json(widget: tk.Text, value: dict) -> None:
        widget.delete("1.0", "end")
        widget.insert("1.0", json.dumps(value, ensure_ascii=False, indent=2))

    def _condition_builder(self) -> None:
        widget = self._form_text["condition"]
        try:
            value = _parse_json(widget.get("1.0", "end-1c"))
            if not isinstance(value, dict):
                raise ValueError("Warunek musi być obiektem")
            _ConditionEditor(self, value, self._catalog_fields(), lambda result: self._set_json(widget, result))
        except (ValueError, TypeError, RecursionError) as exc:
            messagebox.showerror("Niepoprawny warunek", str(exc), parent=self)

    def _expression_builder(self) -> None:
        widget = self._form_text["value"]
        try:
            value = _parse_json(widget.get("1.0", "end-1c"))
            if not isinstance(value, dict):
                raise ValueError("Wyrażenie musi być obiektem")
        except ValueError as exc:
            messagebox.showerror("Niepoprawne wyrażenie", str(exc), parent=self)
            return
        dialog = tk.Toplevel(self)
        dialog.title("Konstruktor wartości")
        dialog.transient(self.winfo_toplevel())
        editor = _ExpressionEditor(dialog, "Wartość", self._catalog_fields())
        editor.pack(fill="both", expand=True)
        editor.set_value(value)

        def accept():
            try:
                self._set_json(widget, editor.get_value())
            except ValueError as exc:
                messagebox.showerror("Niepoprawne wyrażenie", str(exc), parent=dialog)
                return
            dialog.destroy()

        ttk.Button(dialog, text="Zastosuj", command=accept).pack(side="left")
        ttk.Button(dialog, text="Anuluj", command=dialog.destroy).pack(side="left")
        dialog.grab_set()

    def apply_inspector(self) -> bool:
        try:
            updates: dict[str, Any] = {
                key: self._field_choices.get(key, {}).get(var.get(), var.get())
                for key, var in self._form_vars.items()
            }
            for key, widget in self._form_text.items():
                updates[key] = _parse_json(widget.get("1.0", "end-1c"))
            data = self.get_draft()
            if self._selected and self._selected[0] == "node":
                node = next(n for n in data["nodes"] if n["id"] == self._selected[1])
                for key, value in updates.items():
                    if key == "target_list_id" and not value:
                        node.pop(key, None)
                    else:
                        node[key] = value
            else:
                updates["max_updates"] = int(updates["max_updates"])
                data.update(updates)
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Niepoprawne dane", str(exc), parent=self)
            return False
        self._replace(data)
        return True

    def _confirm_discard(self) -> bool:
        if not self.is_dirty:
            return True
        answer = messagebox.askyesnocancel("Niezapisane zmiany",
            "Zapisać zmiany przed otwarciem innej definicji?", parent=self)
        if answer is None:
            return False
        return self.save_file() if answer else True

    def confirm_close(self) -> bool:
        """Ask about unsaved edits; hosts can veto closing if this returns False."""
        return self._confirm_discard()

    def new_document(self) -> bool:
        if not self._confirm_discard():
            return False
        self._draft = WorkflowDraft(new_workflow())
        self._selected = None
        self._connecting = None
        self._path = None
        self._refresh()
        self._notify()
        return True

    def open_file(self, path: str | Path | None = None) -> bool:
        if not self._confirm_discard():
            return False
        if path is None:
            path = filedialog.askopenfilename(parent=self, filetypes=[("JSON", "*.json"), ("Wszystkie", "*")])
        if not path:
            return False
        try:
            graph = Graph.from_json(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, GraphError) as exc:
            messagebox.showerror("Nie można otworzyć", str(exc), parent=self)
            return False
        self.set_graph(graph)
        self._path = Path(path)
        return True

    def save_file(self, path: str | Path | None = None) -> bool:
        if self._form_changed() and not self.apply_inspector():
            return False
        try:
            graph = self.get_graph()
        except GraphError as exc:
            messagebox.showerror("Graf jest niepoprawny", str(exc), parent=self)
            return False
        path = path or self._path
        if path is None:
            path = filedialog.asksaveasfilename(parent=self, defaultextension=".json",
                filetypes=[("JSON", "*.json"), ("Wszystkie", "*")])
        if not path:
            return False
        path = Path(path)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        created = False
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as file:
                created = True
                file.write(graph.to_json())
                file.write("\n")
            os.replace(temporary, path)
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("Nie można zapisać", str(exc), parent=self)
            return False
        finally:
            if created:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as exc:
                    logging.warning("Nie udało się usunąć pliku tymczasowego %s: %s", temporary, exc)
        self._path = path
        self._draft.mark_saved()
        self._refresh()
        self._notify()
        return True
