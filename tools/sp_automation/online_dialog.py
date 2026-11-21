"""GET-only online preview dialog with local journaling and explicit approval.

All SharePoint reads run in a worker thread; Tk widgets and the SQLite journal are
used only on the main thread. Approval records consent for one exact preview after
a fresh read; it never writes to SharePoint.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import getpass
import logging
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from tools.sp_extractor.client import SharePointClient
from .journal import JournalError, PreviewJournal, confirmation_phrase
from .models import Graph
from .sharepoint import OnlinePreview, OnlineReadError, OnlineSnapshot, SharePointReader, build_online_preview
from .simulation_dialog import _display


ReadSnapshot = Callable[[Graph], OnlineSnapshot]


def read_with_windows_sso(graph: Graph) -> OnlineSnapshot:
    client = SharePointClient(graph.to_dict()["site"])
    try:
        return SharePointReader(client).read_snapshot(graph)
    finally:
        client.session.close()


@dataclass(frozen=True)
class _Done:
    kind: str
    value: object


class OnlinePreviewDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, graph: Graph, *, journal_path: Path,
                 read_snapshot: ReadSnapshot = read_with_windows_sso) -> None:
        super().__init__(parent)
        self.title("Podgląd online (tylko GET) — bez zapisu do SharePoint")
        self.geometry("1120x680")
        self.graph = graph
        self.journal_path = Path(journal_path)
        self._read_snapshot = read_snapshot
        self.preview: OnlinePreview | None = None
        self.recorded = False
        self._results: queue.Queue[_Done] = queue.Queue()
        self._pending: str | None = None
        self.protocol("WM_DELETE_WINDOW", self.close)

        ttk.Label(self, wraplength=1080, text=(
            "Świeży odczyt GET wymaganych list i pól z kontrolą stronicowania i ETag. "
            "Zatwierdzenie zapisuje wyłącznie zgodę w lokalnym dzienniku; zapis do SharePoint "
            "nie jest dostępny."
        )).pack(fill="x", padx=8, pady=6)
        self.status = tk.StringVar(value="Odczyt danych z SharePoint (GET)...")
        ttk.Label(self, textvariable=self.status, wraplength=1080).pack(fill="x", padx=8, pady=4)
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.rows = ttk.Treeview(
            frame, columns=("list", "item", "field", "old", "new", "sources"), show="headings", height=12,
        )
        for column, title, width in (
            ("list", "Lista GUID", 250), ("item", "Element", 70), ("field", "Pole", 200),
            ("old", "Wartość przed", 170), ("new", "Proponowana wartość", 190),
            ("sources", "Elementy źródłowe", 150),
        ):
            self.rows.heading(column, text=title)
            self.rows.column(column, width=width, minwidth=60, stretch=True)
        ybar = ttk.Scrollbar(frame, orient="vertical", command=self.rows.yview)
        self.rows.configure(yscrollcommand=ybar.set)
        self.rows.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        self.details = tk.Text(self, height=7, wrap="word", state="disabled")
        self.details.pack(fill="x", padx=8, pady=(0, 8))
        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=(0, 8))
        self.record_button = ttk.Button(buttons, text="Zapisz w dzienniku", state="disabled",
                                        command=self.record)
        self.record_button.pack(side="left")
        self.approve_button = ttk.Button(buttons, text="Zatwierdź (ponowny odczyt GET)...",
                                         state="disabled", command=self.start_approval)
        self.approve_button.pack(side="left", padx=4)
        ttk.Button(buttons, text="Zamknij", command=self.close).pack(side="right")
        self._run("preview", lambda: build_online_preview(graph, self._read_snapshot(graph)))

    def _run(self, kind: str, work: Callable[[], object]) -> None:
        def worker() -> None:
            try:
                self._results.put(_Done(kind, work()))
            except Exception as exc:
                if not isinstance(exc, (OnlineReadError, ValueError)):
                    logging.exception("Podgląd online nie powiódł się")
                self._results.put(_Done("error", exc))

        threading.Thread(target=worker, daemon=True).start()
        self._pending = self.after(50, self._poll)

    def _poll(self) -> None:
        try:
            done = self._results.get_nowait()
        except queue.Empty:
            self._pending = self.after(50, self._poll)
            return
        self._pending = None
        if done.kind == "error":
            self._failed(done.value)
        elif isinstance(done.value, OnlinePreview):
            self._show(done.value)
        elif isinstance(done.value, OnlineSnapshot):
            self._approve(done.value)

    def _failed(self, exc: object) -> None:
        self.status.set(f"Operacja zablokowana: {type(exc).__name__}: {exc}")
        lines = ["Brak wiarygodnego wyniku; nie wykonano żadnego zapisu do SharePoint."]
        for resource in getattr(exc, "resources", ()):
            lines.append(f"{resource.resource}: {resource.status}; strony={resource.pages}; "
                         f"rekordy={resource.records}; stronicowanie pełne={resource.pagination_complete}")
        self._set_details("\n".join(lines))
        self._update_buttons()

    def _show(self, preview: OnlinePreview) -> None:
        self.preview = preview
        data = preview.to_dict()
        changes = data["result"]["changes"]
        for index, change in enumerate(changes[:1000]):
            self.rows.insert("", "end", iid=str(index), values=(
                change["list_id"], change["item_id"],
                f"{change['internal_name']} ({change['field_id']})",
                _display(change["old_value"]), _display(change["new_value"]),
                ", ".join(map(str, change["source_ids"])),
            ))
        snapshot = data["snapshot"]
        scope = snapshot.get("scope_resolution")
        self.status.set(f"Podgląd {preview.run_id}: {len(changes)} proponowanych zmian "
                        f"(tylko odczyt; zapis niedostępny).")
        lines = [f"Witryna: {snapshot['site']} (site {snapshot['site_id']}, web {snapshot['web_id']})"]
        if scope:
            lines.append(f"Zakres widoku „{scope['title']}”: {len(scope['ids'])} elementów "
                         "(filtr CAML oceniony lokalnie; potwierdź na serwerze).")
        for resource in preview.snapshot.resources:
            lines.append(f"{resource.resource}: {resource.status}; strony={resource.pages}; "
                         f"rekordy={resource.records}")
        lines.extend(snapshot.get("warnings", []))
        if len(changes) > 1000:
            lines.append(f"Tabela pokazuje 1000 z {len(changes)} zmian.")
        self._set_details("\n".join(lines))
        self._update_buttons()

    def _update_buttons(self) -> None:
        preview = self.preview if self._pending is None else None
        self.record_button.configure(state="normal" if preview and not self.recorded else "disabled")
        has_changes = preview is not None and bool(preview.to_dict()["result"]["changes"])
        self.approve_button.configure(state="normal" if has_changes and self.recorded else "disabled")

    def record(self) -> None:
        if self.preview is None or self.recorded:
            return
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            with PreviewJournal(self.journal_path) as journal:
                journal.record_preview(self.preview)
        except (OSError, JournalError) as exc:
            messagebox.showerror("Dziennik", str(exc), parent=self)
            return
        self.recorded = True
        self.status.set(f"Podgląd {self.preview.run_id} zapisany w {self.journal_path}.")
        self._update_buttons()

    def start_approval(self) -> None:
        if self.preview is None or not self.recorded or self._pending is not None:
            return
        self.status.set("Ponowny odczyt GET przed zatwierdzeniem...")
        self.record_button.configure(state="disabled")
        self.approve_button.configure(state="disabled")
        self._run("approve", lambda: self._read_snapshot(self.graph))

    def _approve(self, fresh: OnlineSnapshot) -> None:
        assert self.preview is not None
        run_id = self.preview.run_id
        if not self.preview.is_current(self.graph, fresh):
            self.status.set("Podgląd jest nieaktualny (zmienione dane, ETag, zakres lub graf). "
                            "Wykonaj nowy podgląd; zatwierdzenie jest niemożliwe.")
            return
        phrase = confirmation_phrase(run_id)
        typed = simpledialog.askstring(
            "Jawne zatwierdzenie",
            f"Zatwierdzenie zapisze zgodę w dzienniku; zapis do SharePoint NIE zostanie wykonany.\n"
            f"Wpisz dokładnie: {phrase}", parent=self,
        )
        try:
            with PreviewJournal(self.journal_path) as journal:
                approval = journal.approve(run_id, approver=getpass.getuser(), confirmation=typed or "",
                                           graph=self.graph, fresh_snapshot=fresh)
        except (OSError, JournalError) as exc:
            self.status.set(f"Zatwierdzenie odrzucone: {exc}")
            self._update_buttons()
            return
        self.status.set(f"Zatwierdzono {run_id} przez {approval.approver}; zapis niedostępny.")
        self.approve_button.configure(state="disabled")

    def _set_details(self, text: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def close(self) -> None:
        if self._pending is not None:
            self.after_cancel(self._pending)
            self._pending = None
        self.destroy()


def default_journal_path(repo_root: Path) -> Path:
    """Git-ignored location for local preview/approval journals."""
    return repo_root / "out_automation" / "journal.sqlite"


def choose_journal_path(parent: tk.Misc, initial: Path) -> Path | None:
    selected = filedialog.asksaveasfilename(
        parent=parent, title="Dziennik podglądów (SQLite, poza Git)",
        initialdir=str(initial.parent), initialfile=initial.name,
        defaultextension=".sqlite", filetypes=[("SQLite", "*.sqlite"), ("Wszystkie", "*.*")],
        confirmoverwrite=False,
    )
    return Path(selected) if selected else None
