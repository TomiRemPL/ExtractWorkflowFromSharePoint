"""Asynchronous, read-only preview of an automation over a local export."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import queue
import threading
import tkinter as tk
from tkinter import ttk

from .catalog import Catalog
from .engine import SimulationResult, simulate
from .models import Graph
from .snapshot_adapter import AdaptedSnapshot, build_simulation_snapshot


@dataclass(frozen=True)
class _Success:
    adapted: AdaptedSnapshot
    result: SimulationResult


@dataclass(frozen=True)
class _Failure:
    message: str


def _display(value: object) -> str:
    text = "Puste" if value is None else str(value)
    return text if len(text) <= 180 else text[:177] + "..."


class SimulationDialog(tk.Toplevel):
    """Runs the pure simulation outside Tk's event loop and displays proposals."""

    def __init__(self, parent: tk.Misc, catalog: Catalog, graph: Graph) -> None:
        super().__init__(parent)
        self.title("Symulacja offline — tylko podgląd")
        self.geometry("1120x650")
        self._results: queue.Queue[_Success | _Failure] = queue.Queue()
        self._pending: str | None = None
        self.protocol("WM_DELETE_WINDOW", self.close)

        ttk.Label(
            self,
            text=("DANE HISTORYCZNE — wynik orientacyjny; eksport może być niepełny, "
                  "filtry widoków nie są stosowane. To nie jest zatwierdzenie ani zapis do SharePoint."),
            wraplength=1080,
        ).pack(fill="x", padx=8, pady=6)
        self.status = tk.StringVar(value="Przygotowywanie migawki i symulacji...")
        ttk.Label(self, textvariable=self.status, wraplength=1080).pack(fill="x", padx=8, pady=4)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.rows = ttk.Treeview(
            frame, columns=("list", "item", "field", "old", "new", "sources", "steps"),
            show="headings", height=12,
        )
        for column, title, width in (
            ("list", "Lista GUID", 250), ("item", "Element", 70), ("field", "Pole", 180),
            ("old", "Wartość przed", 150), ("new", "Proponowana wartość", 180),
            ("sources", "Elementy źródłowe", 150), ("steps", "Kroki", 120),
        ):
            self.rows.heading(column, text=title)
            self.rows.column(column, width=width, minwidth=60, stretch=True)
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.rows.yview)
        xbar = ttk.Scrollbar(frame, orient="horizontal", command=self.rows.xview)
        self.rows.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
        self.rows.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        self.warnings = tk.Text(self, height=6, wrap="word", state="disabled")
        self.warnings.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(self, text="Zamknij", command=self.close).pack(anchor="e", padx=8, pady=(0, 8))
        self._start(catalog, graph)

    def _start(self, catalog: Catalog, graph: Graph) -> None:
        def worker() -> None:
            try:
                adapted = build_simulation_snapshot(catalog, graph)
                result = simulate(graph, adapted.data, allow_incomplete=not adapted.complete)
                self._results.put(_Success(adapted, result))
            except Exception as exc:
                logging.exception("Symulacja offline nie powiodła się")
                self._results.put(_Failure(f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self._pending = self.after(50, self._finish)

    def _finish(self) -> None:
        try:
            result = self._results.get_nowait()
        except queue.Empty:
            self._pending = self.after(50, self._finish)
            return
        self._pending = None
        if isinstance(result, _Failure):
            self.status.set(f"Symulacja zablokowana: {result.message}")
            self._set_warnings("Brak wiarygodnego podglądu. Sprawdź zgodność witryny, pól i schematu.")
            return

        changes = result.result.changes
        for index, change in enumerate(changes[:1000]):
            self.rows.insert("", "end", iid=str(index), values=(
                change.list_id, change.item_id, f"{change.internal_name} ({change.field_id})",
                _display(change.old_value), _display(change.new_value),
                ", ".join(map(str, change.source_ids)), ", ".join(change.steps),
            ))
        decisions = len(result.result.decisions)
        self.status.set(
            f"Zakończono podgląd: {len(changes)} proponowanych zmian; "
            f"{decisions} decyzji warunkowych. Dane kompletne: {'tak' if result.result.snapshot_complete else 'NIE'}."
        )
        warnings = [
            "Symulacja jest wyłącznie offline. Nie wysłano żadnego żądania do SharePoint.",
            "Propozycje oparte na eksporcie o niepotwierdzonej kompletności nie są podstawą zapisu.",
            *result.adapted.warnings,
        ]
        if len(changes) > 1000:
            warnings.append(f"Tabela pokazuje 1000 z {len(changes)} zmian.")
        if not changes:
            warnings.append("Brak zmian w dostępnych danych nie dowodzi braku zmian poza eksportem.")
        self._set_warnings("\n".join(warnings))

    def _set_warnings(self, text: str) -> None:
        self.warnings.configure(state="normal")
        self.warnings.delete("1.0", "end")
        self.warnings.insert("1.0", text)
        self.warnings.configure(state="disabled")

    def close(self) -> None:
        if self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None
        self.destroy()
