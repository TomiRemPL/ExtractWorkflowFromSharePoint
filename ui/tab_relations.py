"""Podzakładka 3.1: Przeglądanie relacji w historycznym eksporcie SharePoint."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from nicegui import run, ui

from core.automation_service import (
    ComparisonOption,
    ListItemView,
    RelationEdgeView,
    RelationsData,
    find_paths,
    list_comparison_options,
    load_relations,
    run_path_comparison,
)
from core.config_service import REPO_ROOT, list_export_dirs
from tools.sp_automation.catalog import Catalog
from ui.state import AppState


def _mermaid_safe(text: str) -> str:
    return text.replace('"', "'").replace("\n", " ").strip()


def _build_mermaid(
    selected_lists: list[ListItemView],
    edges: list[RelationEdgeView],
) -> str:
    if not selected_lists:
        return "flowchart LR\n  empty[\"Wybierz listy po lewej stronie\"]"
    lines = ["flowchart LR"]
    node_ids: dict[str, str] = {}
    for idx, item in enumerate(selected_lists):
        nid = f"L{idx}"
        node_ids[item.key] = nid
        lines.append(f'  {nid}["{_mermaid_safe(item.title)}"]')
    for edge in edges[:40]:
        src = node_ids.get(edge.source)
        dst = node_ids.get(edge.target)
        if not src:
            src = f"EXT_{abs(hash(edge.source)) % 10000}"
            node_ids[edge.source] = src
            lines.append(f'  {src}["{_mermaid_safe(edge.source)}"]')
        if not dst:
            dst = f"EXT_{abs(hash(edge.target)) % 10000}"
            node_ids[edge.target] = dst
            lines.append(f'  {dst}["{_mermaid_safe(edge.target_title or edge.target)}"]')
        lines.append(f'  {src} -->|"{_mermaid_safe(edge.label)}"| {dst}')
    return "\n".join(lines)


def build_relations_tab(
    state: AppState,
    on_catalog_loaded: Callable[[Catalog | None], None] | None = None,
) -> None:
    """Buduje widok relacji offline z tabelą list, mapą Mermaid i porównaniem ścieżek."""
    cfg = state.config
    export_dirs = [str(REPO_ROOT / d) for d in list_export_dirs(REPO_ROOT)]

    local_state: dict = {
        "data": None,
        "lists_by_key": {},
        "selected_keys": set(),
        "visible_edges": [],
        "mermaid_code": 'flowchart LR\n  empty["Wczytaj eksport, aby zobaczyć relacje"]',
        "zoom": 100,
    }

    # --- Dialog: Powiększona mapa powiązań (pełny ekran) ---
    map_dialog = ui.dialog().props("maximized")
    with map_dialog, ui.card().classes("w-full h-full bg-slate-50 p-6 gap-4 flex flex-col"):
        with ui.row().classes("w-full items-center justify-between"):
            ui.label("Mapa powiązań (Mermaid)").classes("text-lg font-semibold text-slate-800")
            with ui.row().classes("items-center gap-2"):
                zoom_label = ui.label("100%").classes("text-sm text-slate-600 w-12 text-center")

                def _set_zoom(new_zoom: int) -> None:
                    z = max(50, min(250, new_zoom))
                    local_state["zoom"] = z
                    zoom_label.text = f"{z}%"
                    mermaid_modal_wrap.style(f"width: {z}%; min-width: {int(1100 * z / 100)}px;")

                ui.button(icon="zoom_out", on_click=lambda: _set_zoom(local_state["zoom"] - 25)).props(
                    "outline color=primary size=sm"
                ).tooltip("Pomniejsz")
                ui.button("100%", on_click=lambda: _set_zoom(100)).props(
                    "outline color=primary size=sm"
                )
                ui.button(icon="zoom_in", on_click=lambda: _set_zoom(local_state["zoom"] + 25)).props(
                    "outline color=primary size=sm"
                ).tooltip("Powiększ")
                ui.button("Zamknij", icon="close", on_click=map_dialog.close).props(
                    "unelevated color=primary size=sm"
                )

        with ui.scroll_area().classes("w-full flex-1 bg-white rounded-xl border border-slate-200 p-6"):
            with ui.column().style("width: 100%; min-width: 1100px;") as mermaid_modal_wrap:
                mermaid_modal_view = ui.mermaid(local_state["mermaid_code"]).classes("w-full")

    def _open_map_dialog() -> None:
        mermaid_modal_view.set_content(local_state["mermaid_code"])
        map_dialog.open()

    # --- Dialog: Problemy odczytu ---
    diag_dialog = ui.dialog()
    with diag_dialog, ui.card().classes("w-[760px] max-w-[95vw] p-6 gap-4"):
        ui.label("Problemy odczytu eksportu").classes("text-lg font-semibold text-slate-800")
        diag_text = ui.textarea(value="Brak danych.").props("readonly outlined autogrow").classes("w-full font-mono text-xs")
        with ui.row().classes("w-full justify-end"):
            ui.button("Zamknij", on_click=diag_dialog.close).props("flat color=primary")

    # --- Dialog: Porównanie ścieżek ---
    cmp_dialog = ui.dialog()
    with cmp_dialog, ui.card().classes("w-[1000px] max-w-[95vw] p-6 gap-4"):
        ui.label("Porównanie ścieżek Lookup — offline").classes("text-lg font-semibold text-slate-800")
        ui.label(
            "Porównanie wybranych list. Dane historyczne; brak zapisu do SharePoint."
        ).classes("text-sm text-slate-500 -mt-2")
        cmp_options_map: dict[int, ComparisonOption] = {}
        with ui.row().classes("w-full items-end gap-4"):
            cmp_select = ui.select(options={}, label="Ścieżka do porównania").classes("flex-1").props("outlined dense")
            cmp_spinner = ui.spinner(size="sm").classes("hidden")
            cmp_btn = ui.button("Porównaj", icon="compare_arrows").props("unelevated color=primary")
        cmp_status = ui.label("Wybierz ścieżkę i kliknij Porównaj.").classes("text-sm text-slate-600")
        cmp_summary = ui.label("").classes("text-xs text-slate-600 whitespace-pre-line")
        cmp_table = ui.table(
            columns=[
                {"name": "source_id", "label": "ID źródła", "field": "source_id", "align": "left"},
                {"name": "intermediate_id", "label": "ID pośrednie", "field": "intermediate_id", "align": "left"},
                {"name": "direct_id", "label": "ID bezpośrednie", "field": "direct_id", "align": "left"},
                {"name": "indirect_id", "label": "ID pośredniego celu", "field": "indirect_id", "align": "left"},
                {"name": "status", "label": "Wynik", "field": "status", "align": "left"},
            ],
            rows=[],
            pagination=15,
        ).classes("w-full")
        with ui.row().classes("w-full justify-end"):
            ui.button("Zamknij", on_click=cmp_dialog.close).props("flat color=primary")

    async def _run_comparison() -> None:
        data: RelationsData | None = local_state["data"]
        if data is None or data.catalog is None:
            return
        idx = cmp_select.value
        if idx is None or idx not in cmp_options_map:
            ui.notify("Wybierz ścieżkę z listy.", type="warning")
            return
        cmp_spinner.classes(remove="hidden")
        cmp_btn.disable()
        try:
            report = await run.io_bound(run_path_comparison, data.catalog, cmp_options_map[idx])
            cmp_status.text = f"Elementy źródłowe: {report.total_rows}" + (
                " (pokazano 200 pierwszych)" if report.truncated else ""
            )
            cmp_summary.text = " | ".join(f"{k}: {v}" for k, v in report.status_counts)
            cmp_table.rows = report.rows
            cmp_table.update()
        except Exception as exc:
            ui.notify(f"Błąd porównania: {exc}", type="negative")
        finally:
            cmp_spinner.classes(add="hidden")
            cmp_btn.enable()

    cmp_btn.on_click(_run_comparison)

    async def _open_comparison_dialog() -> None:
        data: RelationsData | None = local_state["data"]
        if data is None or data.catalog is None:
            ui.notify("Najpierw wczytaj lokalny eksport.", type="warning")
            return
        selected = set(local_state["selected_keys"])
        if not selected:
            ui.notify("Zaznacz przynajmniej jedną listę.", type="warning")
            return
        options = await run.io_bound(list_comparison_options, data.catalog, selected)
        cmp_options_map.clear()
        for opt in options:
            cmp_options_map[opt.index] = opt
        cmp_select.options = {opt.index: opt.label for opt in options}
        cmp_select.value = options[0].index if options else None
        cmp_select.update()
        cmp_table.rows = []
        cmp_table.update()
        cmp_summary.text = ""
        cmp_status.text = (
            f"Znaleziono {len(options)} par ścieżek do porównania."
            if options
            else "Brak pasujących par ścieżek dla wybranych list."
        )
        cmp_dialog.open()

    # --- Główna karta Relacji offline ---
    with ui.card().classes("w-full bg-white shadow-sm rounded-xl p-6 gap-4"):
        with ui.row().classes("w-full items-end gap-4 flex-wrap"):
            export_input = ui.input(
                label="Katalog eksportu SharePoint",
                value=cfg.relations_in,
            ).classes("flex-1 min-w-[260px]").props("outlined dense")

            def _pick_dir(e) -> None:
                if e.value:
                    export_input.value = e.value

            ui.select(
                options=export_dirs,
                label="Wykryte eksporty",
                value=cfg.relations_in if cfg.relations_in in export_dirs else None,
                on_change=_pick_dir,
            ).classes("w-72").props("outlined dense")

            load_spinner = ui.spinner(size="sm").classes("hidden")
            load_btn = ui.button("Wczytaj", icon="upload_file").props("unelevated color=primary")

        status_lbl = ui.label("Eksport offline — brak połączenia i możliwości zapisu.").classes(
            "text-sm text-slate-600"
        )

        with ui.row().classes("w-full items-center gap-4 flex-wrap"):
            include_ext_chk = ui.checkbox("Pokaż listy docelowe poza wyborem", value=False)
            ui.button(
                "Problemy odczytu",
                icon="info",
                on_click=lambda: (
                    setattr(
                        diag_text,
                        "value",
                        local_state["data"].diagnostics if local_state["data"] else "Brak wczytanego eksportu.",
                    ),
                    diag_dialog.open(),
                ),
            ).props("outline color=primary size=sm")
            ui.button(
                "Porównaj ścieżki",
                icon="compare_arrows",
                on_click=_open_comparison_dialog,
            ).props("outline color=primary size=sm")

        with ui.row().classes("w-full gap-4 items-start flex-nowrap"):
            # Lewy panel: Listy
            with ui.card().classes("w-1/3 min-w-[260px] bg-slate-50 p-4 gap-3 shadow-none border border-slate-200"):
                ui.label("Listy SharePoint").classes("font-semibold text-slate-700")
                list_filter = ui.input(placeholder="Filtruj listy...").classes("w-full").props("outlined dense clearable")
                list_table = ui.table(
                    columns=[
                        {"name": "title", "label": "Nazwa listy", "field": "title", "align": "left", "sortable": True},
                    ],
                    rows=[],
                    row_key="key",
                    selection="multiple",
                    pagination=12,
                ).classes("w-full")
                list_filter.bind_value(list_table, "filter")

            # Prawy panel: Ścieżki, Mapa, Tabela relacji, Szczegóły
            with ui.column().classes("w-2/3 flex-1 gap-4"):
                with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                    path_start = ui.select(options={}, label="Ścieżka od").classes("flex-1 min-w-[180px]").props("outlined dense")
                    path_end = ui.select(options={}, label="do").classes("flex-1 min-w-[180px]").props("outlined dense")
                    btn_paths = ui.button("Pokaż ścieżki", icon="route").props("outline color=primary")

                with ui.card().classes("w-full bg-slate-50 p-4 shadow-none border border-slate-200"):
                    with ui.row().classes("w-full items-center justify-between mb-2"):
                        ui.label("Mapa powiązań (Mermaid)").classes("text-sm font-semibold text-slate-700")
                        ui.button(
                            "Powiększ mapę",
                            icon="open_in_full",
                            on_click=_open_map_dialog,
                        ).props("outline color=primary size=sm")
                    mermaid_view = ui.mermaid("flowchart LR\n  empty[\"Wczytaj eksport, aby zobaczyć relacje\"]").classes("w-full overflow-x-auto")

                edge_table = ui.table(
                    columns=[
                        {"name": "source_title", "label": "Lista źródłowa", "field": "source_title", "align": "left"},
                        {"name": "label", "label": "Pole Lookup", "field": "label", "align": "left"},
                        {"name": "target_title", "label": "Lista docelowa", "field": "target_title", "align": "left"},
                    ],
                    rows=[],
                    row_key="key",
                    selection="single",
                    pagination=8,
                ).classes("w-full")

                details_box = ui.textarea(
                    label="Szczegóły wybranej listy / relacji / ścieżek",
                    value="",
                ).props("readonly outlined rows=8").classes("w-full font-mono text-xs")

    def _refresh_view() -> None:
        data: RelationsData | None = local_state["data"]
        if data is None:
            return
        selected = {row["key"] for row in list_table.selected}
        local_state["selected_keys"] = selected
        include_ext = bool(include_ext_chk.value)

        lists_by_key: dict[str, ListItemView] = local_state["lists_by_key"]
        selected_lists = [lists_by_key[k] for k in selected if k in lists_by_key]

        visible_edges = [
            edge
            for edge in data.relations
            if edge.source in selected and (include_ext or edge.target in selected)
        ]
        local_state["visible_edges"] = visible_edges

        edge_table.rows = [
            {
                "key": edge.key,
                "source_title": lists_by_key[edge.source].title if edge.source in lists_by_key else edge.source,
                "label": edge.label,
                "target_title": edge.target_title or (
                    lists_by_key[edge.target].title if edge.target in lists_by_key else edge.target
                ),
                "details": edge.details,
            }
            for edge in visible_edges
        ]
        edge_table.update()

        mermaid_code = _build_mermaid(selected_lists, visible_edges)
        local_state["mermaid_code"] = mermaid_code
        mermaid_view.set_content(mermaid_code)
        mermaid_modal_view.set_content(mermaid_code)

        if selected_lists:
            details_box.value = "\n\n".join(item.details for item in selected_lists[:3])
        else:
            details_box.value = "Zaznacz jedną lub więcej list po lewej stronie."

    list_table.on("selection", lambda _e: _refresh_view())
    include_ext_chk.on_value_change(lambda _e: _refresh_view())
    edge_table.on(
        "selection",
        lambda _e: setattr(
            details_box,
            "value",
            edge_table.selected[0]["details"] if edge_table.selected else details_box.value,
        ),
    )

    def _show_paths() -> None:
        data: RelationsData | None = local_state["data"]
        if data is None:
            ui.notify("Najpierw wczytaj eksport.", type="warning")
            return
        src = path_start.value
        dst = path_end.value
        if not src or not dst:
            ui.notify("Wybierz listę początkową i końcową.", type="warning")
            return
        if src == dst:
            details_box.value = "Lista początkowa i końcowa są takie same."
            return
        found, truncated = find_paths(data.relations, src, dst)
        if not found:
            details_box.value = "Brak skierowanej ścieżki lookup między wybranymi listami."
            return
        lists_by_key = local_state["lists_by_key"]
        lines = []
        for idx, path in enumerate(found, start=1):
            chain = " → ".join(
                f"{lists_by_key[edge.source].title if edge.source in lists_by_key else edge.source} ({edge.label})"
                for edge in path
            )
            last_target = path[-1].target
            end_title = lists_by_key[last_target].title if last_target in lists_by_key else last_target
            lines.append(f"{idx}. {chain} → {end_title}")
        if truncated:
            lines.append("(Wyszukiwanie ograniczone do pierwszych wyników)")
        details_box.value = "\n".join(lines)

    btn_paths.on_click(_show_paths)

    async def _load_export() -> None:
        path_str = (export_input.value or "").strip()
        if not path_str:
            ui.notify("Wybierz katalog eksportu.", type="negative")
            return
        cfg.relations_in = path_str
        state.save()

        load_btn.disable()
        load_spinner.classes(remove="hidden")
        status_lbl.text = "Wczytywanie lokalnego eksportu..."
        state.set_status("Wczytywanie relacji offline...", busy=True)
        try:
            data = await run.io_bound(load_relations, Path(path_str))
            local_state["data"] = data
            local_state["lists_by_key"] = {item.key: item for item in data.lists}
            state.set_catalog(data.catalog)
            if on_catalog_loaded:
                on_catalog_loaded(data.catalog)

            rows = [{"key": item.key, "title": item.title} for item in data.lists]
            list_table.rows = rows
            default_sel = [r for r in rows if local_state["lists_by_key"][r["key"]].priority]
            if not default_sel:
                default_sel = rows[:6]
            list_table.selected = default_sel
            list_table.update()

            choices = {item.key: item.title for item in data.lists}
            path_start.options = choices
            path_end.options = choices
            path_start.value = data.lists[0].key if data.lists else None
            path_end.value = data.lists[1].key if len(data.lists) > 1 else path_start.value
            path_start.update()
            path_end.update()

            status_lbl.text = data.summary
            _refresh_view()
            state.set_status("Wczytano relacje offline.", busy=False)
            ui.notify(data.summary, type="positive")
        except Exception as exc:
            local_state["data"] = None
            state.set_catalog(None)
            if on_catalog_loaded:
                on_catalog_loaded(None)
            status_lbl.text = "Nie udało się wczytać eksportu."
            state.set_status("Błąd odczytu eksportu.", busy=False)
            ui.notify(f"Błąd odczytu eksportu: {exc}", type="negative", close_button="OK")
        finally:
            load_spinner.classes(add="hidden")
            load_btn.enable()

    load_btn.on_click(_load_export)
