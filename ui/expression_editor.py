"""Kontrolki wyrażeń i wizualny edytor AST; bez wykonywania warunków."""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any, Callable

from nicegui import ui

from core.automation_service import (
    catalog_field_options,
    format_condition_summary,
    is_guid_text,
    parse_graph_json,
)
from tools.sp_automation.catalog import Catalog, FieldRecord

EXPRESSION_KINDS = {
    "literal": "Stała (literal)",
    "field": "Wartość pola (field)",
    "count": "Liczba elementów (count)",
}
CONDITION_OPS = {
    "and": "I (and)", "or": "LUB (or)", "not": "NIE (not)",
    "any": "Dowolny element (any)", "all": "Wszystkie elementy (all)",
    "exists": "Istnieje (exists)", "empty": "Puste (empty)",
    "not_empty": "Niepuste (not_empty)", "eq": "Równe (eq)",
    "ne": "Różne (ne)", "lt": "Mniejsze (lt)", "le": "Mniejsze lub równe (le)",
    "gt": "Większe (gt)", "ge": "Większe lub równe (ge)",
}


def set_select_options(select: ui.select, options: dict[str, str], value: str) -> None:
    """Nie gub ręcznie wpisanych identyfikatorów przy zmianie katalogu, bez pokazywania GUID."""
    choices = dict(options)
    if value and value not in choices:
        choices[value] = "Wybrano z definicji (brak w katalogu)" if is_guid_text(value) else f"Ręcznie: {value}"
    select.set_options(choices, value=value or None)


class ExpressionEditor:
    def __init__(
        self,
        title: str,
        catalog: Catalog | None,
        alias_resolver: Callable[[str], str | None] | None = None,
        target_field_resolver: Callable[[], tuple[FieldRecord | None, str | None]] | None = None,
        on_change: Callable[[], None] | None = None,
    ):
        self.title = title
        self.alias_resolver = alias_resolver
        self.target_field_resolver = target_field_resolver
        self._on_change = on_change
        self._updating = False
        with ui.column().classes("w-full gap-2"):
            ui.label(title).classes("font-medium text-slate-700")
            self.kind = ui.select(EXPRESSION_KINDS, value="literal", label="Rodzaj").props("outlined dense").classes("w-full")
            self.alias = ui.input("Alias", value="source").props("outlined dense").classes("w-full")
            self.field_select = ui.select(
                catalog_field_options(catalog, mode="readable"), label="Pole z katalogu", with_input=True,
            ).props("outlined dense").classes("w-full")
            self.field = ui.input("Pole (GUID lub nazwa ręczna)", value="").props("outlined dense").classes("w-full")
            self.field.set_visibility(False)
            self.literal = ui.input("Literał JSON", value="null").props("outlined dense").classes("w-full")
        self.catalog = catalog
        self.field_select.on_value_change(lambda e: self.field.set_value(e.value or ""))
        self.field.on_value_change(self._handle_field_change)
        self.alias.on_value_change(self._handle_alias_change)
        self.kind.on_value_change(self._handle_kind_change)
        self.literal.on_value_change(lambda _: self._notify_change())
        self._visibility()

    def _notify_change(self) -> None:
        if not self._updating and self._on_change is not None:
            self._on_change()

    def _handle_field_change(self, e) -> None:
        self.set_catalog(self.catalog, e.value or "")
        self._notify_change()

    def _handle_alias_change(self, _e) -> None:
        self.set_catalog(self.catalog)
        self._notify_change()

    def _handle_kind_change(self, _e) -> None:
        self._visibility()
        self._notify_change()

    def _visibility(self) -> None:
        self.alias.set_visibility(self.kind.value != "literal")
        self.field_select.set_visibility(self.kind.value == "field")
        self.field.set_visibility(False)
        self.literal.set_visibility(self.kind.value == "literal")

    def set_catalog(self, catalog: Catalog | None, field_id: str | None = None) -> None:
        self.catalog = catalog
        list_id = self.alias_resolver(self.alias.value or "source") if self.alias_resolver else None
        target_field, target_list_id = (
            self.target_field_resolver() if self.target_field_resolver else (None, None)
        )
        was_updating = self._updating
        self._updating = True
        try:
            set_select_options(
                self.field_select,
                catalog_field_options(
                    catalog,
                    list_id=list_id,
                    mode="readable",
                    compatible_with=target_field,
                    compatible_list_id=target_list_id,
                ),
                self.field.value if field_id is None else field_id,
            )
        finally:
            self._updating = was_updating

    def set_value(self, value: dict[str, Any]) -> None:
        self._updating = True
        try:
            self.kind.value = value.get("kind", "literal")
            self.alias.value = value.get("alias", "source")
            self.field.value = value.get("field_id", "")
            self.literal.value = json.dumps(value.get("value"), ensure_ascii=False, allow_nan=False)
            self.set_catalog(self.catalog)
            self._visibility()
        finally:
            self._updating = False

    def get_value(self) -> dict[str, Any]:
        kind = self.kind.value
        if kind == "literal":
            raw = (self.literal.value or "").strip()
            if not raw:
                raise ValueError(
                    f"{self.title}: pole 'Literał JSON' jest puste. "
                    'Wpisz np. "tekst" (w cudzysłowach), liczbę (123), true/false lub null.'
                )
            try:
                value = parse_graph_json('{"value":' + raw + '}')["value"]
            except ValueError as exc:
                raise ValueError(
                    f"{self.title}: niepoprawny 'Literał JSON' ({raw}). "
                    'Tekst wpisuj w cudzysłowach (np. "Tak"), liczby bez cudzysłowów (np. 123), '
                    f"a wartość pustą jako null. Szczegóły: {exc}"
                ) from exc
            return {"kind": "literal", "value": value}
        if kind == "field":
            return {"kind": "field", "alias": self.alias.value or "",
                    "field_id": self.field.value or ""}
        if kind == "count":
            return {"kind": "count", "alias": self.alias.value or ""}
        raise ValueError("Nieznany rodzaj wyrażenia.")

    def values(self) -> tuple:
        return (self.kind.value, self.alias.value, self.field.value, self.literal.value)


class ConditionEditor:
    def __init__(
        self,
        catalog: Catalog | None,
        on_accept: Callable[[dict[str, Any]], None],
        alias_resolver: Callable[[str], str | None] | None = None,
        graph_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self.catalog = catalog
        self.alias_resolver = alias_resolver
        self.graph_provider = graph_provider
        self.value: dict[str, Any] = {"op": "exists", "alias": "source"}
        self.paths: dict[str, tuple[str | int, ...]] = {}
        self.selected = "root"
        self.on_accept = on_accept
        self._loading = False
        self.dialog = ui.dialog().props("persistent")
        with self.dialog, ui.card().classes("w-[1100px] max-w-[95vw] max-h-[90vh] overflow-auto p-6 gap-4"):
            ui.label("Konstruktor warunku (drzewo)").classes("text-lg font-semibold")
            with ui.row().classes("w-full gap-4 items-start"):
                self.tree = ui.tree([], on_select=self._select).classes("w-1/3 min-w-[200px]")
                with ui.column().classes("flex-1 min-w-[300px] gap-3"):
                    self.op = ui.select(CONDITION_OPS, value="exists", label="Operator").props("outlined dense").classes("w-full")
                    self.alias = ui.input("Alias (exists / any / all)", value="source").props("outlined dense").classes("w-full")
                    with ui.row().classes("w-full gap-4") as self.expr_row:
                        with ui.column().classes("flex-1 min-w-[200px]") as self.left_col:
                            self.left = ExpressionEditor(
                                "Wartość / lewa strona",
                                catalog,
                                alias_resolver=alias_resolver,
                                on_change=self._on_form_change,
                            )
                        with ui.column().classes("flex-1 min-w-[200px]") as self.right_col:
                            self.right = ExpressionEditor(
                                "Prawa strona",
                                catalog,
                                alias_resolver=alias_resolver,
                                on_change=self._on_form_change,
                            )
                    ui.button("Zastąp zaznaczony warunek", on_click=self._replace).props("outline")
                    ui.button("Dodaj warunek do AND / OR", on_click=self._add).props("outline")
                    ui.button("Usuń wybrany warunek", on_click=self._delete).props("outline color=negative")
                    ui.label("ANY/ALL wiążą element jako alias item. Puste: ANY = fałsz, ALL = prawda; COUNT = 0.").classes("text-xs")
                    self.error_label = ui.label("").classes(
                        "text-xs text-red-800 bg-red-50 p-2 rounded border border-red-200 w-full"
                    )
                    self.error_label.set_visibility(False)
                    self.summary = ui.label("").classes(
                        "text-xs text-slate-700 bg-slate-50 p-2 rounded border border-slate-200 w-full whitespace-pre-wrap"
                    )
                    with ui.expansion("Podgląd techniczny warunku (JSON)", icon="code").classes(
                        "w-full border border-slate-200 rounded-lg"
                    ):
                        self.preview = ui.textarea("Podgląd warunku (JSON)", value="{}").props(
                            "readonly outlined autogrow"
                        ).classes("w-full font-mono text-xs")
            with ui.row().classes("w-full justify-end"):
                ui.button("Anuluj", on_click=self.dialog.close).props("flat")
                ui.button("Zastosuj", on_click=self._accept).props("unelevated")
        self.op.on_value_change(lambda _: self._on_form_change())
        self.alias.on_value_change(lambda _: self._on_form_change())
        self._update_op_visibility()

    def set_catalog(self, catalog: Catalog | None) -> None:
        self.catalog = catalog
        self.left.set_catalog(catalog)
        self.right.set_catalog(catalog)
        self._update_summary()

    def _update_summary(self) -> None:
        graph = self.graph_provider() if self.graph_provider else None
        self.summary.text = format_condition_summary(self.value, graph, self.catalog)

    def open(self, value: dict[str, Any]) -> None:
        self.value = deepcopy(value)
        try:
            self._render(())
        except (ValueError, TypeError, RecursionError) as exc:
            ui.notify(f"Niepoprawny warunek: {exc}", type="negative")
            return
        self.dialog.open()

    def _at(self, path: tuple[str | int, ...]) -> Any:
        value: Any = self.value
        for part in path:
            value = value[part]
        return value

    def _update_op_visibility(self) -> None:
        op = self.op.value
        self.alias.set_visibility(op in ("exists", "any", "all"))
        show_left = op in ("empty", "not_empty", "eq", "ne", "lt", "le", "gt", "ge")
        show_right = op in ("eq", "ne", "lt", "le", "gt", "ge")
        self.expr_row.set_visibility(show_left or show_right)
        self.left_col.set_visibility(show_left)
        self.right_col.set_visibility(show_right)

    def _on_form_change(self) -> None:
        self._update_op_visibility()
        if self._loading or self.selected not in self.paths:
            return
        path = self.paths[self.selected]
        try:
            draft = self._construct(self._at(path))
        except (ValueError, TypeError) as exc:
            self.error_label.text = str(exc)
            self.error_label.set_visibility(True)
            return
        preview_tree = deepcopy(self.value)
        if path:
            target: Any = preview_tree
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = draft
        else:
            preview_tree = draft
        graph = self.graph_provider() if self.graph_provider else None
        self.preview.value = json.dumps(preview_tree, ensure_ascii=False, indent=2)
        self.summary.text = format_condition_summary(preview_tree, graph, self.catalog)
        self.error_label.text = ""
        self.error_label.set_visibility(False)

    def _render(self, selected: tuple[str | int, ...]) -> None:
        paths: dict[str, tuple[str | int, ...]] = {}
        graph = self.graph_provider() if self.graph_provider else None

        def node(value: Any, path: tuple[str | int, ...]) -> dict:
            if not isinstance(value, dict) or value.get("op") not in CONDITION_OPS:
                raise ValueError("Warunek musi być obiektem ze znanym operatorem.")
            key = f"node_{len(paths)}"
            paths[key] = path
            op = value["op"]
            children = []
            if op in ("and", "or"):
                if not isinstance(value.get("conditions", []), list):
                    raise ValueError("Dzieci AND / OR muszą być listą.")
                children = [node(child, path + ("conditions", i))
                            for i, child in enumerate(value.get("conditions", []))]
            elif op in ("not", "any", "all") and "condition" in value:
                children = [node(value["condition"], path + ("condition",))]
            label = CONDITION_OPS[op]
            if op in ("exists", "empty", "not_empty", "eq", "ne", "lt", "le", "gt", "ge"):
                label = f"{label} — {format_condition_summary(value, graph, self.catalog)}"
            return {"id": key, "label": label, "children": children}

        nodes = [node(self.value, ())]
        self.paths = paths
        self.selected = next(key for key, path in paths.items() if path == selected)
        self.tree.props["nodes"] = nodes
        self.tree.expand().select(self.selected).update()
        self.preview.value = json.dumps(self.value, ensure_ascii=False, indent=2)
        self._update_summary()
        self.error_label.text = ""
        self.error_label.set_visibility(False)
        self._load_selected()

    def _select(self, e) -> None:
        if e.value in self.paths:
            self.selected = e.value
            self._load_selected()

    def _load_selected(self) -> None:
        value = self._at(self.paths[self.selected])
        self._loading = True
        try:
            self.op.value = value["op"]
            self.alias.value = value.get("alias", "source")
            self.left.set_value(value.get("value", value.get("left", {"kind": "literal", "value": None})))
            self.right.set_value(value.get("right", {"kind": "literal", "value": None}))
        finally:
            self._loading = False
        self._update_op_visibility()

    def _construct(self, old: dict[str, Any] | None = None) -> dict[str, Any]:
        old = old or {}
        op = self.op.value
        default = {"op": "exists", "alias": "source"}
        if op in ("and", "or"):
            return {"op": op, "conditions": deepcopy(old.get("conditions", [default]))}
        if op in ("not", "any", "all"):
            result = {"op": op, "condition": deepcopy(old.get("condition", default))}
            if op != "not":
                result["alias"] = self.alias.value or ""
            return result
        if op == "exists":
            return {"op": op, "alias": self.alias.value or ""}
        if op in ("empty", "not_empty"):
            return {"op": op, "value": self.left.get_value()}
        if op in ("eq", "ne", "lt", "le", "gt", "ge"):
            return {"op": op, "left": self.left.get_value(), "right": self.right.get_value()}
        raise ValueError("Nieznany operator.")

    def _apply_selected(self) -> bool:
        path = self.paths[self.selected]
        try:
            value = self._construct(self._at(path))
            if path:
                self._at(path[:-1])[path[-1]] = value
            else:
                self.value = value
            self._render(path)
            return True
        except (ValueError, TypeError) as exc:
            self.error_label.text = str(exc)
            self.error_label.set_visibility(True)
            ui.notify(f"Niepoprawny warunek: {exc}", type="negative")
            return False

    def _replace(self) -> None:
        self._apply_selected()

    def _add(self) -> None:
        path = self.paths[self.selected]
        parent = self._at(path)
        if parent["op"] not in ("and", "or"):
            ui.notify("Wybierz warunek AND albo OR.", type="negative")
            return
        try:
            child = self._construct()
            parent.setdefault("conditions", []).append(child)
            self._render(path + ("conditions", len(parent["conditions"]) - 1))
        except (ValueError, TypeError) as exc:
            self.error_label.text = str(exc)
            self.error_label.set_visibility(True)
            ui.notify(f"Niepoprawny warunek: {exc}", type="negative")

    def _delete(self) -> None:
        path = self.paths[self.selected]
        if len(path) < 2 or path[-2] != "conditions":
            ui.notify("Wybierz dziecko warunku AND albo OR.", type="negative")
            return
        del self._at(path[:-1])[path[-1]]
        self._render(path[:-2])

    def _accept(self) -> None:
        if not self._apply_selected():
            return
        self.on_accept(deepcopy(self.value))
        self.dialog.close()
