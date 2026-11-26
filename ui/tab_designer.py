"""Podzakładka 3.2: Projektant algorytmu (prototyp offline), symulacja i podgląd online GET."""
from __future__ import annotations

import getpass
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from nicegui import run, ui

from core.automation_service import (
    NODE_TITLES,
    OnlinePreviewOutcome,
    approve_online_preview,
    catalog_field_options,
    catalog_list_options,
    catalog_reverse_lookup_list_options,
    catalog_view_options,
    create_node_dict,
    default_journal_path,
    expected_confirmation_phrase,
    format_condition_summary,
    load_graph_file,
    new_workflow,
    parse_graph_json,
    record_preview_in_journal,
    resolve_alias_list_id,
    resolve_field_record,
    run_offline_simulation,
    run_online_preview,
    save_graph_file,
    validate_graph,
)
from core.config_service import REPO_ROOT
from tools.sp_automation.catalog import FieldRecord
from tools.sp_automation.models import Graph
from ui.expression_editor import CONDITION_OPS, ConditionEditor, ExpressionEditor, set_select_options
from ui.flow_canvas import register_flow_assets, render_flow_canvas
from ui.state import AppState

_CANVAS_ID = "dora-designer-flow-canvas"


def build_designer_tab(state: AppState):
    """Buduje interaktywnego projektanta grafu oraz modale symulacji i podglądu online."""
    register_flow_assets()

    designer_state: dict[str, Any] = {
        "graph": new_workflow(),
        "selected_id": "start",
        "preview_outcome": None,
        "recorded": False,
        "validated_graph": None,
        "syncing": False,
        "json_error": False,
    }
    designer_state["saved_graph"] = deepcopy(designer_state["graph"])

    def _alias_list_id(alias: str) -> str | None:
        return resolve_alias_list_id(designer_state["graph"], state.catalog, alias)

    # --- Modal: Symulacja offline ---
    sim_dialog = ui.dialog()
    with sim_dialog, ui.card().classes("w-[1100px] max-w-[95vw] p-6 gap-4"):
        ui.label("Symulacja offline — tylko podgląd").classes("text-lg font-semibold text-slate-800")
        ui.label(
            "DANE HISTORYCZNE — wynik orientacyjny; eksport może być niepełny, "
            "filtry widoków nie są stosowane. To nie jest zatwierdzenie ani zapis do SharePoint."
        ).classes("text-xs text-amber-800 bg-amber-50 p-3 rounded-lg border border-amber-200")
        with ui.row().classes("items-center gap-3"):
            sim_spinner = ui.spinner(size="sm").classes("hidden")
            sim_status = ui.label("Gotowy.").classes("text-sm text-slate-700")
        with ui.tabs(value="changes").classes("w-full") as sim_tabs:
            ui.tab("changes", label="Proponowane zmiany", icon="edit_note")
            ui.tab("trace", label="Przebieg krok po kroku", icon="timeline")
        with ui.tab_panels(sim_tabs, value="changes").classes("w-full p-0"):
            with ui.tab_panel("changes").classes("p-0"):
                sim_table = ui.table(
                    columns=[
                        {"name": "list", "label": "Lista", "field": "list", "align": "left"},
                        {"name": "item", "label": "Element", "field": "item", "align": "left"},
                        {"name": "field", "label": "Pole", "field": "field", "align": "left"},
                        {"name": "old", "label": "Wartość przed", "field": "old", "align": "left"},
                        {"name": "new", "label": "Proponowana wartość", "field": "new", "align": "left"},
                        {"name": "sources", "label": "Elementy źródłowe", "field": "sources", "align": "left"},
                        {"name": "steps", "label": "Kroki", "field": "steps", "align": "left"},
                    ],
                    rows=[],
                    pagination=10,
                ).classes("w-full")
            with ui.tab_panel("trace").classes("p-0 gap-2"):
                sim_trace_filter = ui.input(
                    placeholder="Filtruj po elemencie, węźle, zmiennej lub wyniku...",
                ).classes("w-full").props("outlined dense clearable")
                sim_trace_table = ui.table(
                    columns=[
                        {"name": "source_id", "label": "Element", "field": "source_id", "align": "left", "sortable": True},
                        {"name": "step_no", "label": "Krok", "field": "step_no", "align": "left"},
                        {"name": "node", "label": "Węzeł", "field": "node", "align": "left"},
                        {"name": "variables", "label": "Użyte zmienne i wartości", "field": "variables", "align": "left"},
                        {"name": "result", "label": "Wynik kroku", "field": "result", "align": "left"},
                        {"name": "next_port", "label": "Wyjście", "field": "next_port", "align": "left"},
                    ],
                    rows=[],
                    pagination=12,
                ).classes("w-full")
                sim_trace_filter.bind_value(sim_trace_table, "filter")
        sim_warnings = ui.textarea(label="Ostrzeżenia", value="").props("readonly outlined autogrow").classes("w-full text-xs")
        with ui.row().classes("w-full justify-end"):
            ui.button("Zamknij", on_click=sim_dialog.close).props("flat color=primary")

    # --- Modal: Podgląd online (tylko GET) ---
    online_dialog = ui.dialog()
    with online_dialog, ui.card().classes("w-[1100px] max-w-[95vw] p-6 gap-4"):
        ui.label("Podgląd online (tylko GET) — bez zapisu do SharePoint").classes(
            "text-lg font-semibold text-slate-800"
        )
        ui.label(
            "Świeży odczyt GET wymaganych list i pól z kontrolą stronicowania i ETag. "
            "Zatwierdzenie zapisuje wyłącznie zgodę w lokalnym dzienniku; zapis do SharePoint nie jest dostępny."
        ).classes("text-xs text-blue-800 bg-blue-50 p-3 rounded-lg border border-blue-200")
        with ui.row().classes("items-center gap-3"):
            online_spinner = ui.spinner(size="sm").classes("hidden")
            online_status = ui.label("Odczyt danych z SharePoint (GET)...").classes("text-sm text-slate-700")
        online_table = ui.table(
            columns=[
                {"name": "list", "label": "Lista", "field": "list", "align": "left"},
                {"name": "item", "label": "Element", "field": "item", "align": "left"},
                {"name": "field", "label": "Pole", "field": "field", "align": "left"},
                {"name": "old", "label": "Wartość przed", "field": "old", "align": "left"},
                {"name": "new", "label": "Proponowana wartość", "field": "new", "align": "left"},
                {"name": "sources", "label": "Elementy źródłowe", "field": "sources", "align": "left"},
            ],
            rows=[],
            pagination=10,
        ).classes("w-full")
        online_details = ui.textarea(label="Szczegóły odczytu", value="").props("readonly outlined autogrow").classes("w-full font-mono text-xs")
        with ui.row().classes("w-full items-center justify-between gap-4"):
            with ui.row().classes("gap-3"):
                btn_record_journal = ui.button("Zapisz w dzienniku", icon="save").props("outline color=primary")
                btn_approve_online = ui.button("Zatwierdź (ponowny odczyt GET)...", icon="verified").props("unelevated color=primary")
            ui.button("Zamknij", on_click=online_dialog.close).props("flat color=primary")

    # --- Modal potwierdzenia zatwierdzenia ---
    approve_dialog = ui.dialog()
    with approve_dialog, ui.card().classes("w-[520px] max-w-[95vw] p-6 gap-4"):
        ui.label("Jawne zatwierdzenie w dzienniku").classes("text-lg font-semibold text-slate-800")
        approve_prompt_lbl = ui.label("").classes("text-sm text-slate-700 whitespace-pre-line")
        approve_input = ui.input(label="Fraza potwierdzenia").classes("w-full").props("outlined dense")
        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Anuluj", on_click=approve_dialog.close).props("flat")
            btn_confirm_approve = ui.button("Potwierdź zapis zgody", color="primary").props("unelevated")

    def _update_online_buttons() -> None:
        outcome: OnlinePreviewOutcome | None = designer_state["preview_outcome"]
        recorded = bool(designer_state["recorded"])
        if outcome is not None and not recorded:
            btn_record_journal.enable()
        else:
            btn_record_journal.disable()
        if outcome is not None and outcome.total_changes > 0 and recorded:
            btn_approve_online.enable()
        else:
            btn_approve_online.disable()

    def _record_journal() -> None:
        outcome: OnlinePreviewOutcome | None = designer_state["preview_outcome"]
        if outcome is None or designer_state["recorded"]:
            return
        journal_path = default_journal_path(REPO_ROOT)
        try:
            record_preview_in_journal(outcome.preview, journal_path)
        except Exception as exc:
            ui.notify(f"Błąd zapisu dziennika: {exc}", type="negative")
            return
        designer_state["recorded"] = True
        online_status.text = f"Podgląd {outcome.preview.run_id} zapisany w {journal_path}."
        _update_online_buttons()
        ui.notify("Zapisano podgląd w dzienniku SQLite.", type="positive")

    btn_record_journal.on_click(_record_journal)

    def _open_approve_prompt() -> None:
        outcome: OnlinePreviewOutcome | None = designer_state["preview_outcome"]
        if outcome is None or not designer_state["recorded"]:
            return
        phrase = expected_confirmation_phrase(outcome.preview.run_id)
        approve_prompt_lbl.text = (
            "Zatwierdzenie zapisze zgodę w dzienniku; zapis do SharePoint NIE zostanie wykonany.\n"
            f"Wpisz dokładnie: {phrase}"
        )
        approve_input.value = ""
        approve_dialog.open()

    btn_approve_online.on_click(_open_approve_prompt)

    async def _confirm_approve() -> None:
        outcome: OnlinePreviewOutcome | None = designer_state["preview_outcome"]
        graph: Graph | None = designer_state["validated_graph"]
        if outcome is None or graph is None:
            return
        approve_dialog.close()
        online_spinner.classes(remove="hidden")
        online_status.text = "Ponowny odczyt GET przed zatwierdzeniem..."
        try:
            approval = await run.io_bound(
                approve_online_preview,
                outcome.preview,
                graph,
                approve_input.value or "",
                default_journal_path(REPO_ROOT),
                getpass.getuser(),
            )
            online_status.text = f"Zatwierdzono {outcome.preview.run_id} przez {approval.approver}; zapis niedostępny."
            btn_approve_online.disable()
            ui.notify("Zatwierdzenie zapisane w lokalnym dzienniku.", type="positive")
        except Exception as exc:
            online_status.text = f"Zatwierdzenie odrzucone: {exc}"
            ui.notify(f"Zatwierdzenie odrzucone: {exc}", type="negative")
        finally:
            online_spinner.classes(add="hidden")

    btn_confirm_approve.on_click(_confirm_approve)

    # --- Główna karta Projektanta ---
    with ui.card().classes("w-full bg-white shadow-sm rounded-xl p-6 gap-4"):
        ui.label(
            "Symulacja jest orientacyjna i offline; nie wykonuje ani nie zatwierdza zmian SharePoint."
        ).classes("text-xs text-amber-800 bg-amber-50 p-3 rounded-lg border border-amber-200 w-full")

        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            btn_new = ui.button("Nowy graf", icon="note_add").props("outline color=primary")
            btn_cancel = ui.button("Anuluj zmiany", icon="undo").props("outline color=primary")
            dirty_label = ui.label("Niezapisane zmiany").classes("text-sm text-amber-800")
            node_kind_select = ui.select(
                options={k: v for k, v in NODE_TITLES.items() if k != "start"},
                value="lookup",
                label="Typ węzła",
            ).classes("w-44").props("outlined dense")
            btn_add_node = ui.button("Dodaj węzeł", icon="add").props("outline color=primary")
            btn_sim = ui.button("Symulacja offline", icon="play_arrow").props("unelevated color=primary")
            btn_online = ui.button("Podgląd online (tylko GET)", icon="cloud_sync").props("outline color=primary")

        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            name_input = ui.input(label="Nazwa algorytmu", value=designer_state["graph"]["name"]).classes("flex-1").props("outlined dense")
            site_input = ui.input(label="Witryna SharePoint", value=designer_state["graph"]["site"]).classes("flex-1").props("outlined dense")
            source_list_input = ui.input(label="GUID listy źródłowej", value=designer_state["graph"]["source_list_id"]).classes("w-72").props("outlined dense")
            source_list_input.set_visibility(False)
            source_list_select = ui.select(catalog_list_options(state.catalog), label="Lista źródłowa", with_input=True).classes("w-72").props("outlined dense")

        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            scope_select = ui.select(
                {"all": "Cała lista (all)", "ids": "Wybrane ID (ids)", "view": "Widok listy (view)"},
                value="all", label="Zakres (scope)",
            ).classes("w-56").props("outlined dense")
            view_select = ui.select({}, label="Widok listy", with_input=True, new_value_mode="add-unique").classes("flex-1").props("outlined dense")
            scope_ids_input = ui.input(
                label="Wybrane ID elementów (np. 1, 2, 5)", value="",
            ).classes("flex-1").props("outlined dense")
            max_updates_input = ui.number(
                label="Limit aktualizacji (max_updates)", value=0, min=0, step=1, precision=0,
            ).classes("w-72").props("outlined dense")
            ui.label("0 = bez limitu").classes("text-xs text-slate-600")

        with ui.row().classes("w-full items-end gap-3 flex-wrap"):
            graph_file_input = ui.input(
                label="Ścieżka pliku JSON grafu",
                value=str(REPO_ROOT / "out_automation" / "workflow_draft.json"),
            ).classes("flex-1").props("outlined dense")
            btn_load_json = ui.button("Wczytaj JSON", icon="folder_open").props("outline color=primary")
            btn_save_json = ui.button("Zapisz JSON", icon="save").props("outline color=primary")

        # --- Interaktywne płótno Flow + Inspektor węzła ---
        with ui.row().classes("w-full gap-4 items-start flex-nowrap"):
            with ui.column().classes("w-2/3 flex-1 gap-2"):
                ui.label(
                    "Przeciągaj węzły, kliknij węzeł aby edytować, lub kliknij port wyjściowy (●) i wskaż węzeł docelowy (kliknięcie krawędzi ją usuwa)."
                ).props(f'id="{_CANVAS_ID}-hint"').classes("text-xs text-slate-600")
                ui.html(f'<div id="{_CANVAS_ID}" class="dora-flow-wrap"></div>', sanitize=False).classes("w-full")

            # Prawy panel: Inspektor wybranego węzła
            with ui.card().classes("w-1/3 min-w-[300px] bg-slate-50 p-4 gap-3 shadow-none border border-slate-200"):
                ui.label("Inspektor węzła").classes("font-semibold text-slate-700")
                insp_header = ui.label("Wybrano: start (Start)").classes("text-xs text-slate-600")

                # Pola dla lookup
                with ui.column().classes("w-full gap-2") as box_lookup:
                    lk_from = ui.input(label="Z aliasu (from)", value="source").classes("w-full").props("outlined dense")
                    lk_field = ui.input(label="Pole Lookup (field_id)", value="").classes("w-full").props("outlined dense")
                    lk_field.set_visibility(False)
                    lk_field_select = ui.select(
                        catalog_field_options(state.catalog, lookup_only=True),
                        label="Pole Lookup z katalogu", with_input=True,
                    ).classes("w-full").props("outlined dense")
                    lk_as = ui.input(label="Jako alias (as)", value="").classes("w-full").props("outlined dense")
                    lk_direction = ui.select(
                        {"forward": "W przód (forward)", "reverse": "Odwrotny (reverse)"},
                        value="forward", label="Kierunek relacji",
                    ).classes("w-full").props("outlined dense")
                    lk_many = ui.checkbox("Kolekcja (many)", value=False)
                    lk_target_list = ui.input(label="GUID listy docelowej (target_list_id)", value="").classes("w-full").props("outlined dense")
                    lk_target_list.set_visibility(False)
                    lk_target_list_select = ui.select(
                        catalog_list_options(state.catalog),
                        label="Lista docelowa (odwrotne)", with_input=True,
                    ).classes("w-full").props("outlined dense")

                # Pola dla condition
                with ui.column().classes("w-full gap-2") as box_condition:
                    cond_merge = ui.select({}, label="Wspólne scalenie (merge)", with_input=True).classes("w-full").props("outlined dense")
                    cond_op = ui.select(options=CONDITION_OPS, value="exists", label="Operator").classes("w-full").props("outlined dense")
                    cond_alias = ui.input(label="Alias", value="source").classes("w-full").props("outlined dense")
                    cond_summary = ui.label("").classes(
                        "text-xs text-slate-700 bg-white p-2 rounded border border-slate-200 w-full whitespace-pre-wrap"
                    )
                    btn_condition_builder = ui.button("Konstruktor warunku (drzewo)...").props("outline")
                    with ui.expansion("Podgląd techniczny warunku (JSON)", icon="code").classes(
                        "w-full border border-slate-200 rounded-lg"
                    ):
                        cond_json = ui.textarea(label="Warunek (JSON)", value="{}").classes("w-full font-mono text-xs").props("outlined rows=4")

                # Pola dla assign
                with ui.column().classes("w-full gap-2") as box_assign:
                    asg_alias = ui.input(label="Alias docelowy", value="source").classes("w-full").props("outlined dense")
                    asg_field_select = ui.select(
                        catalog_field_options(state.catalog, mode="writable"),
                        label="Pole docelowe z katalogu", with_input=True,
                    ).classes("w-full").props("outlined dense")
                    asg_field = ui.input(label="Pole docelowe (field_id)", value="").classes("w-full").props("outlined dense")
                    asg_field.set_visibility(False)

                    def _assign_target_field() -> tuple[FieldRecord | None, str | None]:
                        target_list_id = _alias_list_id(asg_alias.value or "source")
                        fld = resolve_field_record(state.catalog, asg_field.value or "", target_list_id)
                        return (fld, target_list_id)

                    asg_expression = ExpressionEditor(
                        "Konstruktor wartości",
                        state.catalog,
                        alias_resolver=_alias_list_id,
                        target_field_resolver=_assign_target_field,
                    )

                with ui.row().classes("w-full justify-between pt-2"):
                    btn_apply_node = ui.button("Zastosuj", icon="check").props("unelevated color=primary size=sm")
                    btn_delete_node = ui.button("Usuń węzeł", icon="delete").props("outline color=negative size=sm")

        with ui.expansion("Podgląd i edycja surowego JSON grafu", icon="code").classes("w-full border border-slate-200 rounded-lg"):
            json_editor = ui.textarea(
                label="Definicja grafu (JSON)",
                value=json.dumps(designer_state["graph"], ensure_ascii=False, indent=2),
            ).props("outlined rows=12").classes("w-full font-mono text-xs")
            json_error_label = ui.label("").classes("text-sm text-red-700")

    def _accept_condition(value: dict[str, Any]) -> None:
        cond_op.value = value["op"]
        cond_alias.value = value.get("alias", "source")
        cond_json.value = json.dumps(value, ensure_ascii=False, indent=2)
        _on_apply_node()

    condition_builder = ConditionEditor(
        state.catalog,
        _accept_condition,
        alias_resolver=_alias_list_id,
        graph_provider=lambda: designer_state["graph"],
    )

    def _open_condition_builder() -> None:
        try:
            condition_builder.open(parse_graph_json(cond_json.value or "{}"))
        except ValueError as exc:
            ui.notify(f"Niepoprawny warunek: {exc}", type="negative")

    btn_condition_builder.on_click(_open_condition_builder)

    def _inspector_values() -> tuple:
        node = _find_node(designer_state["selected_id"])
        if node is None:
            return ()
        if node.get("type") == "lookup":
            return (
                lk_from.value,
                lk_field.value,
                lk_as.value,
                lk_direction.value,
                bool(lk_many.value),
                lk_target_list.value,
            )
        if node.get("type") == "condition":
            return (cond_merge.value or "", cond_op.value, cond_alias.value, cond_json.value)
        if node.get("type") == "assign":
            return (asg_alias.value, asg_field.value, asg_expression.values())
        return ()

    def _update_dirty() -> None:
        pending = _inspector_values() != designer_state.get("inspector_original", ())
        dirty = (designer_state["graph"] != designer_state["saved_graph"]
                 or designer_state["json_error"] or pending)
        dirty_label.set_visibility(dirty)
        btn_cancel.set_enabled(dirty)

    def _lookup_field_list_id() -> str | None:
        if lk_direction.value == "reverse":
            return (lk_target_list.value or "").strip() or None
        return _alias_list_id(lk_from.value or "source")

    def _refresh_lk_field_options() -> None:
        target_list = _alias_list_id(lk_from.value or "source") if lk_direction.value == "reverse" else None
        set_select_options(
            lk_field_select,
            catalog_field_options(
                state.catalog,
                list_id=_lookup_field_list_id(),
                mode="lookup",
                lookup_target_list_id=target_list,
            ),
            lk_field.value or "",
        )

    def _refresh_lk_target_list_options() -> None:
        is_reverse = lk_direction.value == "reverse"
        lk_target_list_select.set_visibility(is_reverse)
        options = (
            catalog_reverse_lookup_list_options(state.catalog, _alias_list_id(lk_from.value or "source"))
            if is_reverse
            else catalog_list_options(state.catalog)
        )
        set_select_options(lk_target_list_select, options, lk_target_list.value or "")

    def _refresh_asg_field_options() -> None:
        set_select_options(
            asg_field_select,
            catalog_field_options(state.catalog, list_id=_alias_list_id(asg_alias.value or "source"), mode="writable"),
            asg_field.value or "",
        )
        asg_expression.set_catalog(state.catalog)

    def _refresh_catalog(_catalog=None) -> None:
        list_options = catalog_list_options(state.catalog)
        set_select_options(source_list_select, list_options, source_list_input.value or "")
        set_select_options(view_select, catalog_view_options(state.catalog, source_list_input.value or ""),
                           view_select.value or "")
        _refresh_lk_target_list_options()
        _refresh_lk_field_options()
        _refresh_asg_field_options()
        asg_expression.set_catalog(state.catalog)
        condition_builder.set_catalog(state.catalog)
        selected = _find_node(designer_state["selected_id"])
        if selected is not None and selected.get("type") == "condition":
            cond_summary.text = format_condition_summary(
                selected.get("condition") or {"op": "exists", "alias": "source"},
                designer_state["graph"],
                state.catalog,
            )
        render_flow_canvas(_CANVAS_ID, designer_state["graph"], designer_state["selected_id"], state.catalog)

    def _find_node(node_id: str | None) -> dict[str, Any] | None:
        if not node_id:
            return None
        for node in designer_state["graph"].get("nodes", []):
            if str(node.get("id")) == node_id:
                return node
        return None

    def _refresh_inspector() -> None:
        node = _find_node(designer_state["selected_id"])
        if node is None:
            insp_header.text = "Nie wybrano węzła"
            box_lookup.set_visibility(False)
            box_condition.set_visibility(False)
            box_assign.set_visibility(False)
            btn_apply_node.disable()
            btn_delete_node.disable()
            designer_state["inspector_original"] = ()
            return

        kind = str(node.get("type", ""))
        insp_header.text = f"Wybrano: {node.get('id')} ({NODE_TITLES.get(kind, kind)})"
        box_lookup.set_visibility(kind == "lookup")
        box_condition.set_visibility(kind == "condition")
        box_assign.set_visibility(kind == "assign")

        if kind == "lookup":
            lk_from.value = str(node.get("from", "source"))
            lk_field.value = str(node.get("field_id", ""))
            lk_as.value = str(node.get("as", ""))
            lk_direction.value = str(node.get("direction", "forward"))
            lk_many.value = bool(node.get("many", False))
            lk_target_list.value = str(node.get("target_list_id", ""))
            _refresh_lk_target_list_options()
            _refresh_lk_field_options()
        elif kind == "condition":
            merges = {
                str(n["id"]): str(n["id"])
                for n in designer_state["graph"].get("nodes", [])
                if n.get("type") == "merge" and n.get("id")
            }
            set_select_options(cond_merge, merges, str(node.get("merge", "")))
            cond = node.get("condition") or {"op": "exists", "alias": "source"}
            cond_op.value = str(cond.get("op", "exists"))
            cond_alias.value = str(cond.get("alias", "source"))
            cond_json.value = json.dumps(cond, ensure_ascii=False, indent=2)
            cond_summary.text = format_condition_summary(cond, designer_state["graph"], state.catalog)
        elif kind == "assign":
            asg_alias.value = str(node.get("alias", "source"))
            asg_field.value = str(node.get("field_id", ""))
            _refresh_asg_field_options()
            asg_expression.set_value(node.get("value", {"kind": "literal", "value": None}))

        if kind in ("lookup", "condition", "assign"):
            btn_apply_node.enable()
        else:
            btn_apply_node.disable()

        if kind == "start":
            btn_delete_node.disable()
        else:
            btn_delete_node.enable()
        designer_state["inspector_original"] = _inspector_values()

    def _sync_ui_from_graph() -> None:
        designer_state["syncing"] = True
        g = designer_state["graph"]
        name_input.value = g.get("name", "")
        site_input.value = g.get("site", "")
        source_list_input.value = g.get("source_list_id", "")
        scope = g.get("scope", {"type": "all"})
        set_select_options(
            scope_select,
            {"all": "Cała lista (all)", "ids": "Wybrane ID (ids)", "view": "Widok listy (view)"},
            scope.get("type", "all"),
        )
        set_select_options(view_select, catalog_view_options(state.catalog, source_list_input.value),
                           scope.get("view_id", ""))
        scope_ids_input.value = ", ".join(str(item_id) for item_id in scope.get("ids", []))
        view_select.set_visibility(scope_select.value == "view")
        scope_ids_input.set_visibility(scope_select.value == "ids")
        max_updates_input.value = g.get("max_updates", 0)
        set_select_options(source_list_select, catalog_list_options(state.catalog), source_list_input.value)
        json_editor.value = json.dumps(g, ensure_ascii=False, indent=2)
        designer_state["json_error"] = False
        json_error_label.text = ""
        _refresh_inspector()
        designer_state["syncing"] = False
        _update_dirty()
        render_flow_canvas(_CANVAS_ID, g, designer_state["selected_id"], state.catalog)

    def _parse_scope_ids(raw: str) -> list[int]:
        tokens = [part for part in re.split(r"[,\s;]+", raw.strip()) if part]
        ids: list[int] = []
        seen: set[int] = set()
        for token in tokens:
            if not re.fullmatch(r"\d+", token):
                raise ValueError(f"Niepoprawne ID elementu: {token}")
            item_id = int(token)
            if item_id <= 0:
                raise ValueError("ID elementu musi być liczbą całkowitą > 0.")
            if item_id in seen:
                raise ValueError(f"Powtórzone ID elementu: {item_id}")
            seen.add(item_id)
            ids.append(item_id)
        return ids

    def _header_values(parsed: dict[str, Any]) -> None:
        parsed["name"] = (name_input.value or "").strip()
        parsed["site"] = (site_input.value or "").strip()
        parsed["source_list_id"] = (source_list_input.value or "").strip()
        limit = max_updates_input.value
        if limit is None or limit < 0 or int(limit) != limit:
            raise ValueError("Limit aktualizacji musi być nieujemną liczbą całkowitą.")
        parsed["max_updates"] = int(limit)
        scope_type = scope_select.value or "all"
        if scope_type == "view":
            parsed["scope"] = {"type": "view", "view_id": view_select.value or ""}
        elif scope_type == "ids":
            parsed["scope"] = {"type": "ids", "ids": _parse_scope_ids(scope_ids_input.value or "")}
        else:
            parsed["scope"] = {"type": "all"}

    def _pull_graph_from_ui() -> dict[str, Any]:
        parsed = parse_graph_json(json_editor.value or "{}")
        _header_values(parsed)
        designer_state["graph"] = parsed
        return parsed

    def _header_changed() -> None:
        if designer_state["syncing"]:
            return
        try:
            parsed = parse_graph_json(json_editor.value or "{}")
            if parsed.get("source_list_id", "") != (source_list_input.value or "").strip():
                designer_state["syncing"] = True
                view_select.value = None
                designer_state["syncing"] = False
            _header_values(parsed)
        except ValueError as exc:
            designer_state["json_error"] = True
            json_error_label.text = f"Niepoprawna definicja grafu: {exc}"
            _update_dirty()
            return
        designer_state["graph"] = parsed
        designer_state["syncing"] = True
        json_editor.value = json.dumps(parsed, ensure_ascii=False, indent=2)
        designer_state["syncing"] = False
        designer_state["json_error"] = False
        json_error_label.text = ""
        view_select.set_visibility(scope_select.value == "view")
        scope_ids_input.set_visibility(scope_select.value == "ids")
        _refresh_catalog()
        _update_dirty()

    source_list_select.on_value_change(lambda e: source_list_input.set_value(e.value or ""))
    lk_field_select.on_value_change(lambda e: lk_field.set_value(e.value or ""))
    lk_field.on_value_change(lambda: _refresh_lk_field_options())
    lk_from.on_value_change(lambda: (_refresh_lk_target_list_options(), _refresh_lk_field_options()))
    lk_direction.on_value_change(lambda: (_refresh_lk_target_list_options(), _refresh_lk_field_options()))
    lk_target_list_select.on_value_change(lambda e: lk_target_list.set_value(e.value or ""))
    lk_target_list.on_value_change(lambda: (
        _refresh_lk_target_list_options(),
        _refresh_lk_field_options(),
    ))
    asg_field_select.on_value_change(lambda e: asg_field.set_value(e.value or ""))
    asg_field.on_value_change(lambda: _refresh_asg_field_options())
    asg_alias.on_value_change(lambda: _refresh_asg_field_options())
    for control in (name_input, site_input, source_list_input, scope_select, view_select, scope_ids_input, max_updates_input):
        control.on_value_change(_header_changed)
    state.on_catalog_change(_refresh_catalog)
    _sync_ui_from_graph()
    ui.timer(0.2, _update_dirty)
    ui.timer(0.15, lambda: render_flow_canvas(_CANVAS_ID, designer_state["graph"], designer_state["selected_id"], state.catalog), once=True)

    # --- Zdarzenia z interaktywnego płótna JS ---
    def _on_node_move(e) -> None:
        args = e.args or {}
        nid = str(args.get("id", ""))
        if not nid:
            return
        layout = designer_state["graph"].setdefault("layout", {})
        layout[nid] = {"x": int(args.get("x", 100)), "y": int(args.get("y", 100))}
        json_editor.value = json.dumps(designer_state["graph"], ensure_ascii=False, indent=2)
        _update_dirty()

    def _on_node_select(e) -> None:
        args = e.args or {}
        designer_state["selected_id"] = str(args.get("id", "")) or None
        _refresh_inspector()
        render_flow_canvas(_CANVAS_ID, designer_state["graph"], designer_state["selected_id"], state.catalog)

    def _on_edge_add(e) -> None:
        args = e.args or {}
        src = str(args.get("from", ""))
        dst = str(args.get("to", ""))
        port = str(args.get("port", "") or "")
        if not src or not dst or src == dst:
            return
        src_node = _find_node(src)
        if not port and src_node is not None and src_node.get("type") != "condition":
            port = "next"
        edges = designer_state["graph"].setdefault("edges", [])
        edge: dict[str, Any] = {"from": src, "to": dst}
        if port:
            edge["port"] = port
        if edge not in edges:
            edges.append(edge)
            _sync_ui_from_graph()
            ui.notify(f"Połączono {src} → {dst}" + (f" [{port}]" if port else ""), type="positive")

    def _on_edge_delete(e) -> None:
        args = e.args or {}
        idx = args.get("index")
        edges = designer_state["graph"].get("edges", [])
        if isinstance(idx, int) and 0 <= idx < len(edges):
            removed = edges.pop(idx)
            _sync_ui_from_graph()
            ui.notify(f"Usunięto połączenie {removed.get('from')} → {removed.get('to')}", type="info")

    ui.on("dora_flow_node_move", _on_node_move)
    ui.on("dora_flow_node_select", _on_node_select)
    ui.on("dora_flow_edge_add", _on_edge_add)
    ui.on("dora_flow_edge_delete", _on_edge_delete)

    def _on_apply_node() -> bool:
        original = _find_node(designer_state["selected_id"])
        if original is None:
            return True
        node = deepcopy(original)
        kind = str(node.get("type", ""))
        try:
            if kind == "lookup":
                node["from"] = (lk_from.value or "source").strip()
                node["field_id"] = (lk_field.value or "").strip()
                node["as"] = (lk_as.value or "").strip()
                direction = str(lk_direction.value or "forward")
                if direction != "forward":
                    node["direction"] = direction
                else:
                    node.pop("direction", None)
                if lk_many.value:
                    node["many"] = True
                else:
                    node.pop("many", None)
                target_list_id = (lk_target_list.value or "").strip()
                if target_list_id:
                    node["target_list_id"] = target_list_id
                else:
                    node.pop("target_list_id", None)
            elif kind == "condition":
                node["merge"] = (cond_merge.value or "").strip()
                parsed_cond = parse_graph_json(cond_json.value or "{}")
                parsed_cond["op"] = str(cond_op.value or parsed_cond.get("op", "exists"))
                if parsed_cond["op"] in ("exists", "any", "all"):
                    parsed_cond["alias"] = (cond_alias.value or "source").strip()
                node["condition"] = parsed_cond
            elif kind == "assign":
                node["alias"] = (asg_alias.value or "source").strip()
                node["field_id"] = (asg_field.value or "").strip()
                node["value"] = asg_expression.get_value()
            original.update(node)
            _sync_ui_from_graph()
            ui.notify(f"Zaktualizowano węzeł {node.get('id')}.", type="positive")
            return True
        except Exception as exc:
            ui.notify(f"Błąd parametrów węzła: {exc}", type="negative")
            return False

    def _on_delete_node() -> None:
        nid = designer_state["selected_id"]
        if not nid or nid == "start":
            return
        g = designer_state["graph"]
        g["nodes"] = [n for n in g.get("nodes", []) if str(n.get("id")) != nid]
        g["edges"] = [e for e in g.get("edges", []) if str(e.get("from")) != nid and str(e.get("to")) != nid]
        g.get("layout", {}).pop(nid, None)
        designer_state["selected_id"] = "start"
        _sync_ui_from_graph()
        ui.notify(f"Usunięto węzeł {nid}.", type="info")

    def _on_new_graph() -> None:
        designer_state["graph"] = new_workflow()
        designer_state["saved_graph"] = deepcopy(designer_state["graph"])
        designer_state["selected_id"] = "start"
        _sync_ui_from_graph()
        ui.notify("Utworzono nowy pusty graf.", type="info")

    def _on_add_node() -> None:
        try:
            g = _pull_graph_from_ui()
        except Exception as exc:
            ui.notify(f"Niepoprawny JSON grafu: {exc}", type="negative")
            return
        kind = str(node_kind_select.value or "lookup")
        existing = {str(n.get("id")) for n in g.get("nodes", [])}
        idx = 1
        while f"{kind}_{idx}" in existing:
            idx += 1
        node_id = f"{kind}_{idx}"
        g.setdefault("nodes", []).append(create_node_dict(kind, node_id))
        g.setdefault("layout", {})[node_id] = {"x": 140 + (idx % 4) * 230, "y": 120 + (idx // 4) * 120}
        designer_state["selected_id"] = node_id
        _sync_ui_from_graph()
        ui.notify(f"Dodano węzeł {node_id}.", type="positive")

    def _on_load_json() -> None:
        path = Path((graph_file_input.value or "").strip())
        if not path.exists():
            ui.notify(f"Plik {path} nie istnieje.", type="warning")
            return
        try:
            designer_state["graph"] = load_graph_file(path)
            designer_state["saved_graph"] = deepcopy(designer_state["graph"])
            nodes = designer_state["graph"].get("nodes") or []
            designer_state["selected_id"] = str(nodes[0].get("id")) if nodes else None
            _sync_ui_from_graph()
            ui.notify(f"Wczytano graf z {path.name}.", type="positive")
        except Exception as exc:
            ui.notify(f"Błąd wczytywania JSON: {exc}", type="negative")

    def _on_save_json() -> None:
        path = Path((graph_file_input.value or "").strip())
        try:
            if _inspector_values() != designer_state.get("inspector_original", ()) and not _on_apply_node():
                return
            g = _pull_graph_from_ui()
            save_graph_file(path, g)
            designer_state["saved_graph"] = deepcopy(g)
            _sync_ui_from_graph()
            ui.notify(f"Zapisano graf do {path}.", type="positive")
        except Exception as exc:
            ui.notify(f"Błąd zapisu JSON: {exc}", type="negative")

    def _on_json_edit(e) -> None:
        if designer_state["syncing"]:
            return
        try:
            parsed = parse_graph_json(e.value or "{}")
        except ValueError as exc:
            designer_state["json_error"] = True
            json_error_label.text = f"Niepoprawny JSON grafu: {exc}"
            _update_dirty()
            return
        designer_state["graph"] = parsed
        _sync_ui_from_graph()

    def _cancel_changes() -> None:
        designer_state["graph"] = deepcopy(designer_state["saved_graph"])
        nodes = designer_state["graph"].get("nodes", [])
        designer_state["selected_id"] = next(
            (str(node["id"]) for node in nodes if node.get("type") == "start"), None,
        )
        _sync_ui_from_graph()
        ui.notify("Przywrócono ostatnią zapisaną definicję grafu.", type="info")

    async def _on_simulate() -> None:
        if state.catalog is None:
            ui.notify("Najpierw wczytaj lokalny eksport list w zakładce Relacje offline.", type="negative")
            return
        try:
            raw = _pull_graph_from_ui()
            graph = validate_graph(raw, state.catalog)
        except Exception as exc:
            ui.notify(f"Błąd walidacji grafu: {exc}", type="negative")
            return

        sim_table.rows = []
        sim_table.update()
        sim_trace_table.rows = []
        sim_trace_table.update()
        sim_warnings.value = ""
        sim_status.text = "Przygotowywanie migawki i symulacji..."
        sim_spinner.classes(remove="hidden")
        sim_dialog.open()
        try:
            outcome = await run.io_bound(run_offline_simulation, state.catalog, graph)
            sim_table.rows = outcome.rows
            sim_table.update()
            sim_trace_table.rows = outcome.trace_rows
            sim_trace_table.update()
            sim_status.text = (
                f"Zakończono podgląd: {len(outcome.result.changes)} proponowanych zmian; "
                f"{outcome.decisions_count} decyzji warunkowych. "
                f"Dane kompletne: {'tak' if outcome.result.snapshot_complete else 'NIE'}."
            )
            sim_warnings.value = "\n".join(outcome.warnings)
        except Exception as exc:
            sim_status.text = f"Symulacja zablokowana: {exc}"
            sim_warnings.value = "Brak wiarygodnego podglądu. Sprawdź zgodność witryny, pól i schematu."
        finally:
            sim_spinner.classes(add="hidden")

    async def _on_online_preview() -> None:
        try:
            raw = _pull_graph_from_ui()
            graph = validate_graph(raw, state.catalog)
        except Exception as exc:
            ui.notify(f"Błąd walidacji grafu: {exc}", type="negative")
            return

        designer_state["validated_graph"] = graph
        designer_state["preview_outcome"] = None
        designer_state["recorded"] = False
        _update_online_buttons()
        online_table.rows = []
        online_table.update()
        online_details.value = ""
        online_status.text = "Odczyt danych z SharePoint (GET)..."
        online_spinner.classes(remove="hidden")
        online_dialog.open()
        try:
            outcome = await run.io_bound(run_online_preview, graph, state.catalog)
            designer_state["preview_outcome"] = outcome
            online_table.rows = outcome.rows
            online_table.update()
            online_status.text = (
                f"Podgląd {outcome.preview.run_id}: {outcome.total_changes} proponowanych zmian "
                "(tylko odczyt; zapis niedostępny)."
            )
            online_details.value = "\n".join(outcome.details_lines)
        except Exception as exc:
            online_status.text = f"Operacja zablokowana: {type(exc).__name__}: {exc}"
            lines = ["Brak wiarygodnego wyniku; nie wykonano żadnego zapisu do SharePoint."]
            for resource in getattr(exc, "resources", ()):
                lines.append(
                    f"{resource.resource}: {resource.status}; strony={resource.pages}; "
                    f"rekordy={resource.records}; stronicowanie pełne={resource.pagination_complete}"
                )
            online_details.value = "\n".join(lines)
        finally:
            online_spinner.classes(add="hidden")
            _update_online_buttons()

    json_editor.on_value_change(_on_json_edit)
    btn_apply_node.on_click(_on_apply_node)
    btn_delete_node.on_click(_on_delete_node)
    btn_new.on_click(_on_new_graph)
    btn_cancel.on_click(_cancel_changes)
    btn_add_node.on_click(_on_add_node)
    btn_load_json.on_click(_on_load_json)
    btn_save_json.on_click(_on_save_json)
    btn_sim.on_click(_on_simulate)
    btn_online.on_click(_on_online_preview)

    def _refresh_canvas() -> None:
        render_flow_canvas(_CANVAS_ID, designer_state["graph"], designer_state["selected_id"], state.catalog)

    return _refresh_canvas
