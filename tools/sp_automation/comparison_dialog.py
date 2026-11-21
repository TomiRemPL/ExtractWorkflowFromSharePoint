"""Read-only comparison of selected paths in the relations workspace."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable

from .catalog import Catalog
from .comparison import ComparisonPath, ComparisonRow, compare_paths, comparison_paths


_STATUS = {
    "direct_empty": "Pusta relacja bezpośrednia, pośrednia wypełniona",
    "different": "Różne wartości",
    "equal": "Wartości zgodne",
    "both_empty": "Obie wartości puste",
    "indirect_empty": "Pusta relacja pośrednia",
    "no_intermediate": "Brak relacji do listy pośredniej",
    "missing_intermediate": "Brak elementu pośredniego w eksporcie",
    "missing_target": "Brak elementu docelowego w eksporcie",
    "unknown": "Brak pola lub nierozpoznana wartość",
}


@dataclass(frozen=True)
class _Paths:
    paths: list[ComparisonPath]


@dataclass(frozen=True)
class _Rows:
    label: str
    rows: list[ComparisonRow]


@dataclass(frozen=True)
class _Failure:
    message: str


def _label(catalog: Catalog, path: ComparisonPath) -> str:
    lists = catalog.lists
    direct, first, second = path.direct, path.first, path.second
    return (f"{lists[direct.source_list_id].title} [{direct.source_list_id}]: "
            f"{direct.field.title} [{direct.field.internal_name}] → "
            f"{lists[direct.target_list_id].title} [{direct.target_list_id}] | "
            f"przez {first.field.title} [{first.field.internal_name}] → "
            f"{lists[first.target_list_id].title} [{first.target_list_id}]: "
            f"{second.field.title} [{second.field.internal_name}]")


def _render(label: str, rows: list[ComparisonRow]) -> str:
    counts = Counter(row.status for row in rows)
    lines = [
        "Porównanie historycznego eksportu, bez filtrów widoków.",
        "Kompletność danych i reguły biznesowe nie są potwierdzone. To nie jest plan zapisu.",
        label,
        f"Elementy źródłowe: {len(rows)}",
        *[f"{label}: {counts[status]}" for status, label in _STATUS.items() if counts[status]],
        "",
        "ID źródła | ID pośrednie | ID bezpośrednie | ID pośredniego celu | wynik",
    ]
    for row in rows[:200]:
        show = lambda value: str(value) if value is not None else "—"
        lines.append(f"{row.source_id} | {show(row.intermediate_id)} | {show(row.direct_id)} | "
                     f"{show(row.indirect_id)} | {_STATUS[row.status]}")
    if len(rows) > 200:
        lines.append(f"Pokazano 200 z {len(rows)} wierszy; podsumowanie obejmuje wszystkie.")
    return "\n".join(lines)


class ComparisonDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, catalog: Catalog, selected: set[str]) -> None:
        super().__init__(parent)
        self.title("Porównanie ścieżek Lookup — offline")
        self.geometry("1000x600")
        self.catalog = catalog
        self.selected = set(selected)
        self.paths: list[ComparisonPath] = []
        self.results: queue.Queue[_Paths | _Rows | _Failure] = queue.Queue()
        self.pending: str | None = None
        self.protocol("WM_DELETE_WINDOW", self.close)

        ttk.Label(self, text="Porównanie wybranych list. Dane historyczne; brak zapisu do SharePoint.",
                  wraplength=950).pack(fill="x", padx=8, pady=5)
        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=8)
        self.combo = ttk.Combobox(controls, state="disabled")
        self.combo.pack(side="left", fill="x", expand=True)
        self.combo.bind("<<ComboboxSelected>>", self._clear_result)
        self.button = ttk.Button(controls, text="Porównaj", state="disabled", command=self.compare)
        self.button.pack(side="left", padx=5)
        self.status = tk.StringVar(value="Wyszukiwanie ścieżek...")
        ttk.Label(self, textvariable=self.status, wraplength=950).pack(fill="x", padx=8, pady=5)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.text = tk.Text(frame, wrap="none", state="disabled")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=scrollbar.set, xscrollcommand=horizontal.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self._run(lambda: _Paths(comparison_paths(self.catalog, self.selected)))

    def _run(self, operation: Callable[[], _Paths | _Rows]) -> None:
        def worker() -> None:
            try:
                self.results.put(operation())
            except Exception as exc:
                logging.exception("Nie udało się porównać ścieżek offline")
                self.results.put(_Failure(f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self.pending = self.after(50, self._finish)

    def _finish(self) -> None:
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            self.pending = self.after(50, self._finish)
            return
        self.pending = None
        if isinstance(result, _Failure):
            self.status.set(f"Błąd: {result.message}")
            self.combo.configure(state="readonly" if self.paths else "disabled")
            self.button.configure(state="normal" if self.paths else "disabled")
        elif isinstance(result, _Paths):
            self.paths = result.paths
            self.combo.configure(values=[_label(self.catalog, path) for path in self.paths],
                                 state="readonly" if self.paths else "disabled")
            if self.paths:
                self.combo.current(0)
                self.button.configure(state="normal")
                self.status.set(f"Znaleziono ścieżki: {len(self.paths)}. Wybierz ścieżkę i porównaj.")
            else:
                self.status.set("Brak pasujących ścieżek pojedynczych Lookup w wybranych listach.")
        else:
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", _render(result.label, result.rows))
            self.text.configure(state="disabled")
            self.combo.configure(state="readonly")
            self.button.configure(state="normal")
            self.status.set("Wynik orientacyjny; dane i filtry widoków wymagają weryfikacji.")

    def _clear_result(self, _event: tk.Event | None = None) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        self.status.set("Wybrano inną ścieżkę; uruchom porównanie.")

    def compare(self) -> None:
        index = self.combo.current()
        if index < 0:
            self.status.set("Wybierz ścieżkę do porównania.")
            return
        path = self.paths[index]
        self.button.configure(state="disabled")
        self.combo.configure(state="disabled")
        self.status.set("Porównywanie eksportu...")
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        label = _label(self.catalog, path)
        self._run(lambda: _Rows(label, compare_paths(self.catalog, path)))

    def close(self) -> None:
        if self.pending is not None:
            self.after_cancel(self.pending)
            self.pending = None
        self.destroy()
