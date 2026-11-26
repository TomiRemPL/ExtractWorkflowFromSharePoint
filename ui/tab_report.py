"""Zakładka 2: Generowanie raportów Markdown, skryptów SQL i portalu HTML."""
from __future__ import annotations

from urllib.parse import quote

from nicegui import run, ui

from core.config_service import REPO_ROOT, list_export_dirs
from core.report_service import (
    ReportRequest,
    open_output_folder,
    resolve_portal_path,
    run_report_generation,
)
from ui.state import AppState


def build_report_tab(state: AppState) -> None:
    """Buduje panel generowania raportów i otwierania portalu migracji."""
    cfg = state.config
    export_dirs = list_export_dirs(REPO_ROOT)

    with ui.card().classes("w-full bg-white shadow-sm rounded-xl p-6 gap-4"):
        ui.label("Generowanie raportów Markdown/PL-SQL i portalu HTML").classes(
            "text-lg font-semibold text-slate-800"
        )
        ui.label(
            "Przetwarza wyeksportowane pliki .nwf i metadane JSON do raportów migracyjnych Oracle APEX."
        ).classes("text-sm text-slate-500 -mt-2")

        with ui.row().classes("w-full items-end gap-4"):
            in_dir_input = ui.input(
                label="Katalog z danymi (.nwf i JSON)",
                value=cfg.report_in,
            ).classes("flex-1").props("outlined dense")

            def _pick_export_dir(e) -> None:
                if e.value:
                    in_dir_input.value = e.value
                    if "_" in e.value:
                        out_dir_input.value = f"out_{e.value.split('_')[-1]}"

            export_picker = ui.select(
                options=export_dirs,
                label="Wykryte eksporty",
                value=cfg.report_in if cfg.report_in in export_dirs else None,
                on_change=_pick_export_dir,
            ).classes("w-64").props("outlined dense")

        with ui.row().classes("w-full items-end gap-4"):
            out_dir_input = ui.input(
                label="Katalog wyjściowy raportów",
                value=cfg.report_out,
            ).classes("flex-1").props("outlined dense")

            def _refresh_dirs() -> None:
                dirs = list_export_dirs(REPO_ROOT)
                export_picker.options = dirs
                export_picker.update()
                ui.notify(f"Odświeżono listę ({len(dirs)} katalogów).", type="info")

            ui.button(
                "Odśwież listę",
                icon="refresh",
                on_click=_refresh_dirs,
            ).props("outline color=primary")

        def _sync_from_state() -> None:
            in_dir_input.value = cfg.report_in
            out_dir_input.value = cfg.report_out

        state.on_report_sync(_sync_from_state)

        with ui.row().classes("w-full items-center gap-4 pt-2 flex-wrap"):
            report_spinner = ui.spinner(size="sm").classes("hidden")

            async def _start_reporting() -> None:
                in_dir = (in_dir_input.value or "").strip()
                out_dir = (out_dir_input.value or "").strip()
                if not in_dir or not out_dir:
                    ui.notify("Podaj katalog wejściowy i wyjściowy.", type="negative")
                    return

                cfg.report_in = in_dir
                cfg.report_out = out_dir
                state.save()

                btn_report.disable()
                report_spinner.classes(remove="hidden")
                state.set_status("Generowanie raportów...", busy=True)
                try:
                    req = ReportRequest(input_dir=in_dir, output_dir=out_dir, repo_root=REPO_ROOT)
                    result = await run.io_bound(run_report_generation, req, state.log_session.log)
                    if result.exit_code == 0:
                        state.set_status(f"Raporty gotowe w: {out_dir}", busy=False)
                        ui.notify(
                            f"Wygenerowano raporty i portal HTML w {out_dir}/.",
                            type="positive",
                        )
                    else:
                        state.set_status("Generowanie zakończone ostrzeżeniem.", busy=False)
                        ui.notify(
                            f"Generator zakończył działanie z kodem {result.exit_code}.",
                            type="warning",
                        )
                except Exception as exc:
                    state.log_session.log_exception(f"Błąd generowania raportów: {exc}")
                    state.set_status("Błąd generowania raportów.", busy=False)
                    ui.notify(f"Błąd: {exc}", type="negative", close_button="OK")
                finally:
                    report_spinner.classes(add="hidden")
                    btn_report.enable()

            btn_report = ui.button(
                "Generuj raporty i portal HTML",
                icon="auto_awesome",
                on_click=_start_reporting,
            ).props("unelevated color=primary")

            def _open_portal() -> None:
                out_dir = (out_dir_input.value or "").strip()
                portal = resolve_portal_path(out_dir, repo_root=REPO_ROOT)
                if not portal.exists():
                    ui.notify(
                        f"Plik {portal} nie istnieje. Najpierw wygeneruj raporty.",
                        type="warning",
                    )
                    return
                state.log_session.log(f"Otwieranie portalu: {portal}")
                ui.navigate.to(f"/portal/{quote(out_dir)}/workflow-migration-manual.html", new_tab=True)

            ui.button(
                "Otwórz portal w przeglądarce",
                icon="open_in_new",
                on_click=_open_portal,
            ).props("outline color=primary")

            def _open_folder() -> None:
                out_dir = (out_dir_input.value or "").strip()
                try:
                    open_output_folder(out_dir, repo_root=REPO_ROOT)
                except FileNotFoundError as exc:
                    ui.notify(str(exc), type="warning")

            ui.button(
                "Otwórz katalog w Eksploratorze",
                icon="folder_open",
                on_click=_open_folder,
            ).props("flat color=primary")
