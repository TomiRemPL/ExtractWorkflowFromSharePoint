"""Zakładka przeglądania relacji w historycznym eksporcie SharePoint."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from tools.sp_automation.catalog import Catalog
from tools.sp_automation.comparison_dialog import ComparisonDialog
from tools.sp_automation.relation_map import MapEdge, MapNode, RelationMap


@dataclass(frozen=True)
class ListView:
    key: str
    title: str
    details: str
    priority: bool = False


@dataclass(frozen=True)
class RelationView:
    key: str
    source: str
    target: str
    label: str
    details: str
    target_title: str = ""


@dataclass(frozen=True)
class RelationsSnapshot:
    lists: list[ListView]
    relations: list[RelationView]
    summary: str
    diagnostics: str = ""
    catalog: Catalog | None = field(default=None, repr=False, compare=False)


def find_paths(
    relations: list[RelationView], source: str, target: str, max_depth: int = 6, max_paths: int = 20,
) -> tuple[list[list[RelationView]], bool]:
    """Znajduje ścieżki skierowanych lookupów bez przechodzenia cykli."""
    outgoing: dict[str, list[RelationView]] = defaultdict(list)
    for relation in relations:
        outgoing[relation.source].append(relation)
    pending = deque([(source, [], frozenset([source]))])
    found: list[list[RelationView]] = []
    examined = 0
    while pending:
        current, path, visited = pending.popleft()
        if len(path) >= max_depth:
            continue
        for relation in outgoing[current]:
            examined += 1
            if examined > 10000:
                return found, True
            if relation.target in visited:
                continue
            next_path = [*path, relation]
            if relation.target == target:
                found.append(next_path)
                if len(found) > max_paths:
                    return found[:max_paths], True
            else:
                pending.append((relation.target, next_path, visited | {relation.target}))
    return found, False


class RelationsTab(ttk.Frame):
    """Odczytowa przeglądarka danych; loader nie ma dostępu do widgetów Tk."""

    def __init__(
        self,
        parent: tk.Misc,
        loader: Callable[[Path], RelationsSnapshot],
        initial_dir: str = "",
        on_loaded: Callable[[RelationsSnapshot | None], None] | None = None,
    ) -> None:
        super().__init__(parent, padding=8)
        self._loader = loader
        self._on_loaded = on_loaded
        self._results: queue.Queue[tuple[RelationsSnapshot | None, str]] = queue.Queue()
        self._lists: dict[str, ListView] = {}
        self._relations: dict[str, RelationView] = {}
        self._visible_edges: list[RelationView] = []
        self._path_choices: dict[str, str] = {}
        self._diagnostics = ""
        self._catalog: Catalog | None = None
        self._comparison: ComparisonDialog | None = None
        self.path_var = tk.StringVar(value=initial_dir)
        self.status_var = tk.StringVar(value="Eksport offline — brak połączenia i możliwości zapisu.")
        self.include_external = tk.BooleanVar(value=False)
        self.path_start = tk.StringVar()
        self.path_end = tk.StringVar()

        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        ttk.Label(top, text="Katalog eksportu:").pack(side=tk.LEFT)
        ttk.Entry(top, textvariable=self.path_var, width=35).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        ttk.Button(top, text="Wybierz...", command=self._browse).pack(side=tk.LEFT)
        self.load_button = ttk.Button(top, text="Wczytaj", command=self.load)
        self.load_button.pack(side=tk.LEFT, padx=(5, 0))
        ttk.Label(self, textvariable=self.status_var, wraplength=800).pack(fill=tk.X, pady=(4, 4))
        options = ttk.Frame(self)
        options.pack(fill=tk.X)
        ttk.Checkbutton(
            options, text="Pokaż listy docelowe poza wyborem", variable=self.include_external,
            command=self._selection_changed,
        ).pack(side=tk.LEFT)
        ttk.Button(options, text="Problemy odczytu", command=lambda: self._show_details(self._diagnostics)).pack(side=tk.LEFT, padx=8)
        ttk.Button(options, text="Porównaj ścieżki", command=self._compare_paths).pack(side=tk.LEFT)

        panes = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        panes.pack(fill=tk.BOTH, expand=True)
        left = ttk.LabelFrame(panes, text="Listy (Ctrl: wybór wielu)", padding=4)
        right = ttk.Frame(panes)
        panes.add(left, weight=1)
        panes.add(right, weight=4)

        self.list_tree = ttk.Treeview(left, columns=("rows",), show="tree", selectmode="extended", height=8)
        list_scroll = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.list_tree.yview)
        self.list_tree.configure(yscrollcommand=list_scroll.set)
        self.list_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_tree.bind("<<TreeviewSelect>>", self._selection_changed)

        self.map = RelationMap(right, self._select_node, self._select_edge)
        self.map.pack(fill=tk.BOTH, expand=True)
        path_frame = ttk.Frame(right)
        path_frame.pack(fill=tk.X, pady=(4, 2))
        ttk.Label(path_frame, text="Ścieżka od:").pack(side=tk.LEFT)
        self.start_combo = ttk.Combobox(path_frame, textvariable=self.path_start, state="readonly", width=18)
        self.start_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Label(path_frame, text="do:").pack(side=tk.LEFT)
        self.end_combo = ttk.Combobox(path_frame, textvariable=self.path_end, state="readonly", width=18)
        self.end_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        ttk.Button(path_frame, text="Pokaż ścieżki", command=self._show_paths).pack(side=tk.LEFT)
        ttk.Label(right, text="Powiązania między wybranymi listami (kliknij numer na mapie lub wiersz):").pack(anchor=tk.W)
        edge_frame = ttk.Frame(right)
        edge_frame.pack(fill=tk.X)
        self.edge_tree = ttk.Treeview(
            edge_frame, columns=("source", "field", "target"), show="headings", selectmode="browse", height=4,
        )
        for column, title, width in (
            ("source", "Lista źródłowa", 180), ("field", "Pole Lookup", 170), ("target", "Lista docelowa", 180),
        ):
            self.edge_tree.heading(column, text=title)
            self.edge_tree.column(column, width=width, minwidth=60, stretch=True)
        edge_scroll = ttk.Scrollbar(edge_frame, orient=tk.VERTICAL, command=self.edge_tree.yview)
        self.edge_tree.configure(yscrollcommand=edge_scroll.set)
        self.edge_tree.pack(side=tk.LEFT, fill=tk.X, expand=True)
        edge_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.edge_tree.bind("<<TreeviewSelect>>", self._edge_selected)
        detail_frame = ttk.Frame(right)
        detail_frame.pack(fill=tk.BOTH)
        self.details = tk.Text(detail_frame, height=5, wrap=tk.WORD, state=tk.DISABLED)
        detail_scroll = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL, command=self.details.yview)
        self.details.configure(yscrollcommand=detail_scroll.set)
        self.details.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        detail_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.map.show([], [])

    def _browse(self) -> None:
        directory = filedialog.askdirectory(parent=self, title="Wybierz katalog eksportu SharePoint")
        if directory:
            self.path_var.set(directory)

    def load(self) -> None:
        path = self.path_var.get().strip()
        if not path:
            messagebox.showerror("Brak katalogu", "Wybierz katalog eksportu.", parent=self)
            return
        if self._comparison is not None and self._comparison.winfo_exists():
            self._comparison.close()
            self._comparison = None
        self.load_button.configure(state=tk.DISABLED)
        self.status_var.set("Wczytywanie lokalnego eksportu...")

        def worker() -> None:
            try:
                self._results.put((self._loader(Path(path)), ""))
            except Exception as exc:
                self._results.put((None, f"{type(exc).__name__}: {exc}"))

        threading.Thread(target=worker, daemon=True).start()
        self.after(50, self._finish_load)

    def _finish_load(self) -> None:
        try:
            snapshot, error = self._results.get_nowait()
        except queue.Empty:
            self.after(50, self._finish_load)
            return
        self.load_button.configure(state=tk.NORMAL)
        if snapshot is None:
            self.status_var.set("Nie udało się wczytać eksportu; poprzedni widok nie jest aktualny.")
            self._clear()
            if self._on_loaded:
                self._on_loaded(None)
            messagebox.showerror("Błąd odczytu eksportu", error, parent=self)
            return
        self._lists = {item.key: item for item in snapshot.lists}
        self._catalog = snapshot.catalog
        self._relations = {item.key: item for item in snapshot.relations}
        self._diagnostics = snapshot.diagnostics or "Brak zgłoszonych problemów odczytu."
        self.list_tree.delete(*self.list_tree.get_children())
        for item in snapshot.lists:
            self.list_tree.insert("", tk.END, iid=item.key, text=item.title)
        selected = [item.key for item in snapshot.lists if item.priority]
        if not selected:
            selected = [item.key for item in snapshot.lists[:6]]
        self.list_tree.selection_set(selected)
        self.status_var.set(snapshot.summary)
        self._selection_changed()
        if self._on_loaded:
            self._on_loaded(snapshot)

    def _clear(self) -> None:
        self._catalog = None
        self._lists.clear()
        self._relations.clear()
        self._visible_edges.clear()
        self._path_choices.clear()
        self._diagnostics = ""
        self.start_combo.configure(values=())
        self.end_combo.configure(values=())
        self.path_start.set("")
        self.path_end.set("")
        self.list_tree.delete(*self.list_tree.get_children())
        self.edge_tree.delete(*self.edge_tree.get_children())
        self.map.show([], [])
        self._show_details("")

    def _compare_paths(self) -> None:
        if self._catalog is None:
            messagebox.showerror("Brak danych", "Najpierw wczytaj eksport.", parent=self)
            return
        selected = set(self.list_tree.selection())
        if len(selected) < 3:
            messagebox.showerror("Brak list", "Wybierz co najmniej trzy listy do porównania.", parent=self)
            return
        if self._comparison is not None and self._comparison.winfo_exists():
            self._comparison.close()
        self._comparison = ComparisonDialog(self, self._catalog, selected)

    def _selection_changed(self, _event: tk.Event | None = None) -> None:
        selected = set(self.list_tree.selection())
        nodes = [MapNode(item.key, item.title) for item in self._lists.values() if item.key in selected]
        self._visible_edges = [
            item for item in self._relations.values()
            if item.source in selected and (item.target in selected or self.include_external.get())
        ]
        if self.include_external.get():
            additional = {item.target: item.target_title for item in self._visible_edges if item.target not in selected}
            for key, title in additional.items():
                item = self._lists.get(key)
                nodes.append(MapNode(key, item.title if item else title or f"Nieznana lista: {key}", external=True))
        self._path_choices = {f"{node.title} [{node.key}]": node.key for node in nodes}
        choices = list(self._path_choices)
        self.start_combo.configure(values=choices)
        self.end_combo.configure(values=choices)
        if self.path_start.get() not in self._path_choices:
            self.path_start.set(choices[0] if choices else "")
        if self.path_end.get() not in self._path_choices:
            self.path_end.set(choices[-1] if choices else "")
        edges = [MapEdge(item.key, item.source, item.target, item.label) for item in self._visible_edges]
        self.map.show(nodes, edges)
        self.edge_tree.delete(*self.edge_tree.get_children())
        for number, item in enumerate(self._visible_edges, 1):
            self.edge_tree.insert(
                "", tk.END, iid=item.key,
                values=(
                    self._lists[item.source].title,
                    f"{number}. {item.label}",
                    self._lists[item.target].title if item.target in self._lists
                    else item.target_title or f"Nieznana lista: {item.target}",
                ),
            )
        if len(selected) == 1:
            self._show_details(self._lists[next(iter(selected))].details)
        else:
            self._show_details("Wybierz listę lub relację, aby zobaczyć szczegóły.")

    def _select_node(self, key: str) -> None:
        if key in self._lists:
            self._show_details(self._lists[key].details)
        else:
            self._show_details(f"Lista {key} nie została znaleziona w eksporcie.")

    def _select_edge(self, key: str) -> None:
        if key in self._relations and self.edge_tree.exists(key):
            self.edge_tree.selection_set(key)
            self.edge_tree.see(key)
            self._show_details(self._relations[key].details)

    def _edge_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.edge_tree.selection()
        if selected and selected[0] in self._relations:
            self._show_details(self._relations[selected[0]].details)

    def _show_paths(self) -> None:
        source = self._path_choices.get(self.path_start.get())
        target = self._path_choices.get(self.path_end.get())
        if not source or not target or source == target:
            self._show_details("Wybierz dwie różne listy na mapie.")
            return
        paths, truncated = find_paths(self._visible_edges, source, target)
        if not paths:
            text = "Nie znaleziono skierowanej ścieżki w widocznym grafie (maksymalnie 6 relacji)."
            if truncated:
                text += " Przeszukiwanie przerwano po osiągnięciu limitu."
            self._show_details(text)
            return
        lines = ["Ścieżki skierowanych relacji Lookup (maksymalnie 6 relacji):"]
        for index, path in enumerate(paths, 1):
            name = self._lists[source].title if source in self._lists else source
            parts = [name]
            for edge in path:
                target_name = self._lists[edge.target].title if edge.target in self._lists else edge.target_title or edge.target
                parts.append(f" --[{edge.label}]--> {target_name}")
            lines.append(f"{index}. {''.join(parts)}")
        if truncated:
            lines.append("Wynik ograniczono z powodu limitu ścieżek lub przeszukiwania.")
        self._show_details("\n".join(lines))

    def _show_details(self, text: str) -> None:
        self.details.configure(state=tk.NORMAL)
        self.details.delete("1.0", tk.END)
        self.details.insert("1.0", text)
        self.details.configure(state=tk.DISABLED)
