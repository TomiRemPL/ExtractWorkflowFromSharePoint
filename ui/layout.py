"""Wspólny układ interfejsu webowego DORA (nagłówek, zakładki, dziennik logów, pasek stanu)."""
from __future__ import annotations

from nicegui import ui

from tools.nwf_report.app_info import APPLICATION_NOTICE, APP_VERSION, AUTHOR
from ui.state import AppState
from ui.tab_designer import build_designer_tab
from ui.tab_extract import build_extract_tab
from ui.tab_relations import build_relations_tab
from ui.tab_report import build_report_tab

TAB_KEYS = ["extract", "report", "automation"]


def build_main_page(state: AppState) -> None:
    """Buduje główny widok aplikacji NiceGUI."""
    ui.colors(primary="#1d4ed8", secondary="#475569", accent="#2563eb")
    ui.query("body").classes("bg-slate-50 text-slate-800")

    # Dialog: O aplikacji
    about_dialog = ui.dialog()
    with about_dialog, ui.card().classes("w-[480px] max-w-[95vw] p-6 gap-3"):
        ui.label("O aplikacji").classes("text-lg font-semibold text-slate-800")
        ui.label(AUTHOR).classes("text-sm text-slate-700")
        ui.label(APPLICATION_NOTICE).classes("text-sm text-slate-700")
        ui.label(f"Wersja: {APP_VERSION}").classes("text-xs text-slate-500")
        with ui.row().classes("w-full justify-end pt-2"):
            ui.button("Zamknij", on_click=about_dialog.close).props("flat color=primary")

    # Górny pasek nawigacyjny
    with ui.header().classes("bg-white text-slate-800 border-b border-slate-200 px-6 py-3 shadow-sm"):
        with ui.row().classes("w-full max-w-7xl mx-auto items-center justify-between"):
            with ui.column().classes("gap-0"):
                ui.label("DORA: Migracja SharePoint 2019 → Oracle APEX").classes(
                    "text-lg font-bold text-slate-900"
                )
                ui.label(
                    "Ekstraktor konfiguracji, generator raportów Markdown/PL-SQL i interaktywnego portalu migracji."
                ).classes("text-xs text-slate-500")
            ui.button("O aplikacji", icon="info", on_click=about_dialog.open).props(
                "outline color=primary size=sm"
            )

    initial_tab_idx = state.config.active_tab
    initial_tab = (
        TAB_KEYS[initial_tab_idx]
        if 0 <= initial_tab_idx < len(TAB_KEYS)
        else TAB_KEYS[0]
    )

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-4"):
        with ui.tabs(value=initial_tab).classes("w-full bg-white rounded-xl shadow-sm px-2") as tabs:
            ui.tab("extract", label="1. Ekstrakcja z SharePoint", icon="cloud_download")
            ui.tab("report", label="2. Generowanie raportów i portalu", icon="description")
            ui.tab("automation", label="3. Automatyzacje", icon="account_tree")

        def _on_tab_change(e) -> None:
            if e.value in TAB_KEYS:
                state.config.active_tab = TAB_KEYS.index(e.value)
                state.save()
            if e.value == "automation" and auto_tabs.value == "designer":
                ui.timer(0.05, refresh_designer_canvas, once=True)

        tabs.on_value_change(_on_tab_change)

        with ui.tab_panels(tabs, value=initial_tab).classes("w-full bg-transparent p-0"):
            with ui.tab_panel("extract").classes("p-0"):
                build_extract_tab(state)

            with ui.tab_panel("report").classes("p-0"):
                build_report_tab(state)

            with ui.tab_panel("automation").classes("p-0 gap-4"):
                with ui.tabs(value="relations").classes("w-full bg-white rounded-xl shadow-sm px-2") as auto_tabs:
                    ui.tab("relations", label="Relacje offline", icon="hub")
                    ui.tab("designer", label="Projektant (prototyp offline)", icon="schema")

                with ui.tab_panels(auto_tabs, value="relations").classes("w-full bg-transparent p-0 mt-4"):
                    with ui.tab_panel("relations").classes("p-0"):
                        build_relations_tab(state)
                    with ui.tab_panel("designer").classes("p-0"):
                        refresh_designer_canvas = build_designer_tab(state)

                auto_tabs.on_value_change(
                    lambda e: ui.timer(0.05, refresh_designer_canvas, once=True)
                    if e.value == "designer"
                    else None
                )

        # Dziennik zdarzeń i logi w czasie rzeczywistym
        with ui.card().classes("w-full bg-white shadow-sm rounded-xl p-6 gap-3"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.label("Dziennik zdarzeń i logi w czasie rzeczywistym").classes(
                    "text-sm font-semibold text-slate-700"
                )
                with ui.row().classes("items-center gap-3"):
                    global_spinner = ui.spinner(size="sm").classes("hidden")
                    status_label = ui.label(state.status_text).classes("text-xs text-slate-500")
                    ui.button(
                        "Wyczyść widok",
                        icon="delete_sweep",
                        on_click=lambda: log_view.clear(),
                    ).props("flat size=sm color=primary")

            log_view = ui.log(max_lines=600).classes(
                "w-full h-52 bg-slate-900 text-slate-100 rounded-lg p-3 font-mono text-xs"
            )

        last_log_id = {"value": 0}

        def _poll_logs() -> None:
            new_id, lines = state.log_session.buffer.get_since(last_log_id["value"])
            if lines:
                last_log_id["value"] = new_id
                for line in lines:
                    log_view.push(line)

        _poll_logs()
        ui.timer(0.25, _poll_logs)

        def _on_status(text: str, is_busy: bool) -> None:
            status_label.text = text
            if is_busy:
                global_spinner.classes(remove="hidden")
            else:
                global_spinner.classes(add="hidden")

        state.on_status_change(_on_status)
