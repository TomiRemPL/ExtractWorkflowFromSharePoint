"""Zakładka 1: Ekstrakcja metadanych i workflow z SharePoint 2019."""
from __future__ import annotations

from nicegui import run, ui

from core.config_service import REPO_ROOT, remember_url
from core.extraction_service import ExtractionRequest, run_extraction
from ui.state import AppState


def build_extract_tab(state: AppState) -> None:
    """Buduje formularz ekstrakcji danych z SharePoint."""
    cfg = state.config

    with ui.card().classes("w-full bg-white shadow-sm rounded-xl p-6 gap-4"):
        ui.label("Ekstrakcja metadanych i workflow z SharePoint 2019").classes(
            "text-lg font-semibold text-slate-800"
        )
        ui.label(
            "Pobiera definicje list, pliki .nwf oraz opcjonalnie dane list z witryny SharePoint."
        ).classes("text-sm text-slate-500 -mt-2")

        with ui.row().classes("w-full items-end gap-4"):
            url_input = ui.input(
                label="Adres URL witryny SharePoint",
                value=cfg.sharepoint_url,
                placeholder="https://teams.sp.creditagricole/team/...",
            ).classes("flex-1").props("outlined dense")

            def _apply_history(e) -> None:
                if e.value:
                    url_input.value = e.value

            history_select = ui.select(
                options=cfg.sharepoint_urls,
                label="Historia adresów",
                value=cfg.sharepoint_url if cfg.sharepoint_url in cfg.sharepoint_urls else None,
                on_change=_apply_history,
            ).classes("w-80").props("outlined dense")

        with ui.row().classes("w-full items-center gap-4"):
            auto_dir_chk = ui.checkbox(
                "Automatycznie numeruj (DaneZeSkryptu_nnn)",
                value=cfg.auto_dir,
            )
            custom_dir_input = ui.input(
                label="Własny katalog docelowy",
                value=cfg.custom_dir,
                placeholder="np. DaneZeSkryptu_custom",
            ).classes("flex-1").props("outlined dense")
            custom_dir_input.bind_enabled_from(auto_dir_chk, "value", backward=lambda v: not v)

        with ui.row().classes("w-full items-center gap-6 flex-wrap"):
            inc_data_chk = ui.checkbox(
                "Pobierz dane list (20_dane_*.json)",
                value=cfg.include_data,
            )
            insecure_chk = ui.checkbox(
                "Ignoruj certyfikat SSL (--insecure)",
                value=cfg.insecure_ssl,
            )
            ui.label("(Domyślnie uwierzytelnianie Windows SSO / SSPI)").classes(
                "text-xs text-slate-500"
            )

        with ui.row().classes("w-full items-center gap-4 pt-2"):
            extract_spinner = ui.spinner(size="sm").classes("hidden")

            async def _start_extraction() -> None:
                url = (url_input.value or "").strip()
                if not url:
                    ui.notify("Wprowadź adres URL witryny SharePoint.", type="negative")
                    return

                cfg.sharepoint_url = url
                cfg.sharepoint_urls = remember_url(cfg.sharepoint_urls, url)
                cfg.auto_dir = bool(auto_dir_chk.value)
                cfg.custom_dir = (custom_dir_input.value or "").strip()
                cfg.include_data = bool(inc_data_chk.value)
                cfg.insecure_ssl = bool(insecure_chk.value)
                history_select.options = cfg.sharepoint_urls
                history_select.update()
                state.save()

                btn_extract.disable()
                extract_spinner.classes(remove="hidden")
                state.set_status("Pobieranie z SharePoint w toku...", busy=True)
                try:
                    req = ExtractionRequest(
                        url=url,
                        auto_dir=cfg.auto_dir,
                        custom_dir=cfg.custom_dir,
                        include_data=cfg.include_data,
                        insecure_ssl=cfg.insecure_ssl,
                        repo_root=REPO_ROOT,
                    )
                    result = await run.io_bound(run_extraction, req, state.log_session.log)
                    cfg.report_in = result.output_dir.name
                    if "_" in result.output_dir.name:
                        cfg.report_out = f"out_{result.output_dir.name.split('_')[-1]}"
                    state.save()
                    state.notify_report_paths_updated()

                    if not result.complete:
                        state.set_status(f"Eksport niekompletny: {result.output_dir.name}.", busy=False)
                        ui.notify(
                            f"Eksport niekompletny ({len(result.errors)} błędów). "
                            "Szczegóły: extraction_manifest.json.",
                            type="warning",
                            close_button="OK",
                        )
                    else:
                        state.set_status(
                            f"Zakończono pobieranie do {result.output_dir.name}.", busy=False
                        )
                        ui.notify(
                            f"Pobrano {result.workflow_count} workflow i {result.list_count} list "
                            f"do {result.output_dir.name}.",
                            type="positive",
                        )
                except Exception as exc:
                    state.log_session.log_exception(f"Błąd ekstrakcji: {exc}")
                    state.set_status("Błąd podczas pobierania.", busy=False)
                    ui.notify(f"Błąd ekstrakcji: {exc}", type="negative", close_button="OK")
                finally:
                    extract_spinner.classes(add="hidden")
                    btn_extract.enable()

            btn_extract = ui.button(
                "Rozpocznij pobieranie z SharePoint",
                icon="cloud_download",
                on_click=_start_extraction,
            ).props("unelevated color=primary")
