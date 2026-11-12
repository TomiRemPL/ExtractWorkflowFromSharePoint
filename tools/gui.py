"""Natywny interfejs graficzny (GUI) dla pakietu DORA:
- Ekstrakcja metadanych i workflow z SharePoint 2019 (sp_extractor)
- Generowanie raportow Markdown, PL/SQL i portalu HTML (nwf_report)
- Podglad logow w czasie rzeczywistym i uruchamianie portalu w przegladarce
"""
from __future__ import annotations

import json
import logging
import os
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.nwf_report.app_info import APPLICATION_NOTICE, APP_VERSION, AUTHOR
from tools.nwf_report.generate_report import main as generate_report_main
from tools.sp_extractor.client import SharePointClient
from tools.sp_extractor.extractor import SharePointExtractor
from tools.sp_extractor.naming import resolve_output_dir

DEFAULT_CONFIG_PATH = REPO_ROOT / ".dora_gui_config.json"
DEFAULT_SHAREPOINT_URL = "https://teams.sp.creditagricole/team/ITMM"
MAX_URL_HISTORY = 20


class QueueHandler(logging.Handler):
    """Przekierowuje rekordy logowania do kolejki GUI."""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        self.log_queue.put(msg)


class DoraMigrationApp(tk.Tk):
    def __init__(self, config_path: Path | None = None):
        super().__init__()
        self.title("Migracja Nintex Workflow -> Oracle APEX")
        self.config_path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
        self._url_history: list[str] = [DEFAULT_SHAREPOINT_URL]

        # Domyslne centrowanie okna i wysuniecie na pierwszy plan
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - 950) // 2)
        y = max(0, (sh - 720) // 2)
        self.geometry(f"950x720+{x}+{y}")
        self.minsize(800, 600)
        self.lift()
        self.attributes("-topmost", True)
        self.after(800, lambda: self.attributes("-topmost", False))
        self.focus_force()

        # Kolejka logow
        self.log_queue: queue.Queue = queue.Queue()
        self._setup_logging()

        # Budowa UI i wczytanie zapisanej konfiguracji
        self._build_ui()
        self._auto_detect_dirs()
        self._load_and_apply_config()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._process_log_queue)

    def _show_about(self) -> None:
        messagebox.showinfo(
            "O aplikacji",
            f"{AUTHOR}\n{APPLICATION_NOTICE}\nWersja: {APP_VERSION}",
            parent=self,
        )

    def _setup_logging(self):
        self.queue_handler = QueueHandler(self.log_queue)
        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")
        self.queue_handler.setFormatter(formatter)
        logging.getLogger().addHandler(self.queue_handler)
        logging.getLogger().setLevel(logging.INFO)

    def _build_ui(self):
        # Styl
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        # Naglowek
        header_frame = ttk.Frame(self, padding="15 12 15 8")
        header_frame.pack(fill=tk.X)
        self.about_button = ttk.Button(
            header_frame, text="O aplikacji", command=self._show_about
        )
        self.about_button.grid(row=0, column=1, sticky=tk.E, padx=(12, 0))
        header_frame.columnconfigure(0, weight=1)
        title_lbl = ttk.Label(
            header_frame,
            text="DORA: Migracja SharePoint 2019 -> Oracle APEX",
            font=("Segoe UI", 14, "bold"),
        )
        title_lbl.grid(row=0, column=0, sticky=tk.W)
        subtitle_lbl = ttk.Label(
            header_frame,
            text="Ekstraktor konfiguracji, generator raportów Markdown/PL-SQL i interaktywnego portalu migracji.",
            font=("Segoe UI", 9),
            foreground="#555555",
        )
        subtitle_lbl.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 0))

        # Zakladki Notebook
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.X, padx=15, pady=5)

        # Karta 1: Ekstraktor
        tab_extract = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab_extract, text=" 1. Ekstrakcja z SharePoint ")
        self._build_extract_tab(tab_extract)

        # Karta 2: Generator Raportow
        tab_report = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab_report, text=" 2. Generowanie raportów i portalu ")
        self._build_report_tab(tab_report)

        # Sekcja Logow (na dole)
        log_frame = ttk.LabelFrame(self, text="Dziennik zdarzeń i logi w czasie rzeczywistym", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(5, 10))

        self.log_text = tk.Text(
            log_frame,
            wrap=tk.WORD,
            height=12,
            font=("Consolas", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
        )
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Pasek stanu
        status_bar = ttk.Frame(self, padding="10 4")
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_lbl = ttk.Label(status_bar, text="Gotowy.", font=("Segoe UI", 9))
        self.status_lbl.pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(status_bar, mode="indeterminate", length=150)
        self.progress.pack(side=tk.RIGHT, padx=5)

    def _build_extract_tab(self, parent):
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.X, expand=True)

        ttk.Label(grid, text="Adres URL witryny SharePoint:").grid(row=0, column=0, sticky=tk.W, pady=4)
        self.url_var = tk.StringVar(value=DEFAULT_SHAREPOINT_URL)
        self.url_combo = ttk.Combobox(
            grid, textvariable=self.url_var, values=self._url_history, width=62
        )
        self.url_combo.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=4)

        ttk.Label(grid, text="Katalog docelowy:").grid(row=1, column=0, sticky=tk.W, pady=4)
        dest_box = ttk.Frame(grid)
        dest_box.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=4)

        self.auto_dir_var = tk.BooleanVar(value=True)
        self.custom_dir_var = tk.StringVar()
        self.chk_auto = ttk.Checkbutton(
            dest_box,
            text="Automatycznie numeruj (DaneZeSkryptu_nnn)",
            variable=self.auto_dir_var,
            command=self._toggle_custom_extract_dir,
        )
        self.chk_auto.pack(side=tk.LEFT)

        self.custom_dir_entry = ttk.Entry(dest_box, textvariable=self.custom_dir_var, state=tk.DISABLED)
        self.custom_dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        ttk.Label(grid, text="Opcje autoryzacji:").grid(row=2, column=0, sticky=tk.W, pady=4)
        opt_box = ttk.Frame(grid)
        opt_box.grid(row=2, column=1, sticky=tk.W, padx=5, pady=4)

        self.inc_data_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_box, text="Pobierz dane list (20_dane_*.json)", variable=self.inc_data_var).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        self.insecure_ssl_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt_box, text="Ignoruj certyfikat SSL (--insecure)", variable=self.insecure_ssl_var).pack(
            side=tk.LEFT, padx=(0, 10)
        )
        ttk.Label(opt_box, text="(Domyślnie Windows SSO / SSPI)", foreground="#666666").pack(side=tk.LEFT)

        # Przycisk startu ekstrakcji
        btn_box = ttk.Frame(parent)
        btn_box.pack(fill=tk.X, pady=(10, 0))
        self.btn_extract = ttk.Button(
            btn_box, text=" Rozpocznij pobieranie z SharePoint ", command=self._start_extraction
        )
        self.btn_extract.pack(side=tk.LEFT)

    def _toggle_custom_extract_dir(self):
        if self.auto_dir_var.get():
            self.custom_dir_entry.configure(state=tk.DISABLED)
        else:
            self.custom_dir_entry.configure(state=tk.NORMAL)

    def _build_report_tab(self, parent):
        grid = ttk.Frame(parent)
        grid.pack(fill=tk.X, expand=True)

        ttk.Label(grid, text="Katalog z danymi (.nwf i JSON):").grid(row=0, column=0, sticky=tk.W, pady=4)
        in_box = ttk.Frame(grid)
        in_box.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=4)
        self.report_in_var = tk.StringVar(value="DaneZeSkryptu_002")
        ttk.Entry(in_box, textvariable=self.report_in_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(in_box, text="Przeglądaj...", command=self._browse_report_input).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(grid, text="Katalog wyjściowy raportów:").grid(row=1, column=0, sticky=tk.W, pady=4)
        out_box = ttk.Frame(grid)
        out_box.grid(row=1, column=1, sticky=tk.EW, padx=5, pady=4)
        self.report_out_var = tk.StringVar(value="out_002")
        ttk.Entry(out_box, textvariable=self.report_out_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(out_box, text="Przeglądaj...", command=self._browse_report_output).pack(side=tk.LEFT, padx=(4, 0))

        grid.columnconfigure(1, weight=1)

        # Przyciski
        btn_box = ttk.Frame(parent)
        btn_box.pack(fill=tk.X, pady=(12, 0))

        self.btn_report = ttk.Button(
            btn_box, text=" Generuj raporty i portal HTML ", command=self._start_reporting
        )
        self.btn_report.pack(side=tk.LEFT, padx=(0, 6))

        self.btn_open_portal = ttk.Button(
            btn_box, text=" Otwórz portal w przeglądarce ", command=self._open_portal_browser
        )
        self.btn_open_portal.pack(side=tk.LEFT, padx=6)

        self.btn_open_folder = ttk.Button(
            btn_box, text=" Otwórz katalog w Eksploratorze ", command=self._open_output_folder
        )
        self.btn_open_folder.pack(side=tk.LEFT, padx=6)

    def _auto_detect_dirs(self):
        """Wykrywa najnowszy istniejacy katalog DaneZeSkryptu_nnn i proponuje out_nnn."""
        subdirs = sorted([d.name for d in REPO_ROOT.glob("DaneZeSkryptu*") if d.is_dir()])
        if subdirs:
            latest = subdirs[-1]
            self.report_in_var.set(latest)
            if "_" in latest:
                suffix = latest.split("_")[-1]
                self.report_out_var.set(f"out_{suffix}")
            else:
                self.report_out_var.set("out")

    def _remember_url(self, url: str) -> None:
        """Dodaje adres SharePoint na poczatek historii (bez duplikatow)."""
        cleaned = url.strip()
        if not cleaned:
            return
        self._url_history = [u for u in self._url_history if u != cleaned]
        self._url_history.insert(0, cleaned)
        self._url_history = self._url_history[:MAX_URL_HISTORY]
        self.url_combo.configure(values=self._url_history)

    def _load_and_apply_config(self) -> None:
        """Wczytuje konfiguracje GUI z pliku JSON, jesli istnieje."""
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logging.warning("Nie udało się wczytać konfiguracji GUI (%s): %s", self.config_path, exc)
            return
        if not isinstance(data, dict):
            return

        geometry = data.get("window_geometry")
        if isinstance(geometry, str) and geometry:
            try:
                self.geometry(geometry)
            except tk.TclError:
                pass
        if data.get("window_state") == "zoomed":
            try:
                self.state("zoomed")
            except tk.TclError:
                pass

        active_tab = data.get("active_tab")
        if isinstance(active_tab, int) and 0 <= active_tab < self.notebook.index("end"):
            self.notebook.select(active_tab)

        raw_history = data.get("sharepoint_urls")
        if isinstance(raw_history, list):
            history = [u.strip() for u in raw_history if isinstance(u, str) and u.strip()]
            if history:
                self._url_history = list(dict.fromkeys(history))[:MAX_URL_HISTORY]
                self.url_combo.configure(values=self._url_history)

        sharepoint_url = data.get("sharepoint_url")
        if isinstance(sharepoint_url, str) and sharepoint_url.strip():
            self.url_var.set(sharepoint_url.strip())
            self._remember_url(sharepoint_url.strip())

        if isinstance(data.get("auto_dir"), bool):
            self.auto_dir_var.set(data["auto_dir"])
            self._toggle_custom_extract_dir()
        if isinstance(data.get("custom_dir"), str):
            self.custom_dir_var.set(data["custom_dir"])
        if isinstance(data.get("include_data"), bool):
            self.inc_data_var.set(data["include_data"])
        if isinstance(data.get("insecure_ssl"), bool):
            self.insecure_ssl_var.set(data["insecure_ssl"])

        if isinstance(data.get("report_in"), str) and data["report_in"].strip():
            self.report_in_var.set(data["report_in"].strip())
        if isinstance(data.get("report_out"), str) and data["report_out"].strip():
            self.report_out_var.set(data["report_out"].strip())

    def _collect_config(self) -> dict:
        """Zbiera biezacy stan GUI do slownika serializowanego jako JSON."""
        current_url = self.url_var.get().strip()
        if current_url:
            self._remember_url(current_url)
        try:
            active_tab = int(self.notebook.index(self.notebook.select()))
        except tk.TclError:
            active_tab = 0
        try:
            win_state = self.state()
        except tk.TclError:
            win_state = "normal"

        return {
            "window_geometry": self.geometry(),
            "window_state": win_state,
            "active_tab": active_tab,
            "sharepoint_url": current_url,
            "sharepoint_urls": list(self._url_history),
            "auto_dir": bool(self.auto_dir_var.get()),
            "custom_dir": self.custom_dir_var.get(),
            "include_data": bool(self.inc_data_var.get()),
            "insecure_ssl": bool(self.insecure_ssl_var.get()),
            "report_in": self.report_in_var.get().strip(),
            "report_out": self.report_out_var.get().strip(),
        }

    def _save_config(self) -> None:
        """Zapisuje biezaca konfiguracje GUI do pliku JSON."""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            payload = self._collect_config()
            self.config_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logging.warning("Nie udało się zapisać konfiguracji GUI (%s): %s", self.config_path, exc)

    def _on_close(self) -> None:
        self._save_config()
        self.destroy()

    def _browse_report_input(self):
        d = filedialog.askdirectory(initialdir=REPO_ROOT, title="Wybierz katalog ze zrzutem SharePoint")
        if d:
            rel = os.path.relpath(d, REPO_ROOT)
            self.report_in_var.set(rel)
            if "_" in rel:
                suffix = rel.split("_")[-1]
                self.report_out_var.set(f"out_{suffix}")

    def _browse_report_output(self):
        d = filedialog.askdirectory(initialdir=REPO_ROOT, title="Wybierz katalog docelowy raportów")
        if d:
            self.report_out_var.set(os.path.relpath(d, REPO_ROOT))

    def _process_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.log_text.insert(tk.END, msg + "\n")
            self.log_text.see(tk.END)
        self.after(100, self._process_log_queue)

    def log(self, msg: str):
        self.log_queue.put(msg)

    def _start_extraction(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showerror("Błąd", "Wprowadź adres URL witryny SharePoint.")
            return

        self._remember_url(url)
        self._save_config()
        self.btn_extract.configure(state=tk.DISABLED)
        self.progress.start(10)
        self.status_lbl.configure(text="Pobieranie z SharePoint w toku...")

        def task():
            try:
                self.log(f"Inicjalizacja klienta SharePoint dla: {url}")
                client = SharePointClient(
                    base_url=url,
                    verify_ssl=not self.insecure_ssl_var.get(),
                )

                if self.auto_dir_var.get():
                    out_dir = resolve_output_dir(None, base_dir=REPO_ROOT)
                else:
                    custom = self.custom_dir_var.get().strip() or "DaneZeSkryptu_custom"
                    out_dir = REPO_ROOT / custom

                self.log(f"Rozpoczęcie ekstrakcji do: {out_dir.resolve()}")
                extractor = SharePointExtractor(
                    client=client,
                    output_dir=out_dir,
                    include_data=self.inc_data_var.get(),
                )
                manifest = extractor.run()
                wf_count = len(manifest.get("workflows", []))
                list_count = len(manifest.get("lists", []))
                self.log(f"SUKCES: Zakończono ekstrakcję. Pobrano {wf_count} workflow, {list_count} list.")
                self.status_lbl.configure(text=f"Zakończono pobieranie do {out_dir.name}.")

                # Zaktualizuj zakladke raportow
                self.report_in_var.set(out_dir.name)
                if "_" in out_dir.name:
                    sfx = out_dir.name.split("_")[-1]
                    self.report_out_var.set(f"out_{sfx}")
            except Exception as e:
                self.log(f"BŁĄD ekstrakcji: {e}")
                self.status_lbl.configure(text="Błąd podczas pobierania.")
                messagebox.showerror("Błąd ekstrakcji", str(e))
            finally:
                self.progress.stop()
                self.btn_extract.configure(state=tk.NORMAL)

        threading.Thread(target=task, daemon=True).start()

    def _start_reporting(self):
        in_dir = self.report_in_var.get().strip()
        out_dir = self.report_out_var.get().strip()
        if not in_dir or not out_dir:
            messagebox.showerror("Błąd", "Podaj katalog wejściowy i wyjściowy.")
            return

        self._save_config()
        self.btn_report.configure(state=tk.DISABLED)
        self.progress.start(10)
        self.status_lbl.configure(text="Generowanie raportów...")

        def task():
            try:
                self.log(f"Uruchomienie generatora raportów: {in_dir} -> {out_dir}")
                code = generate_report_main(["--input", in_dir, "--output", out_dir])
                if code == 0:
                    self.log(f"SUKCES: Wygenerowano raporty, dyspozytor PL/SQL oraz portal HTML w {out_dir}/")
                    self.status_lbl.configure(text=f"Raporty gotowe w: {out_dir}")
                else:
                    self.log(f"Generator zwrócił kod wyjścia: {code}")
                    self.status_lbl.configure(text="Generowanie zakończone ostrzeżeniem.")
            except Exception as e:
                self.log(f"BŁĄD generowania raportów: {e}")
                self.status_lbl.configure(text="Błąd generowania raportów.")
                messagebox.showerror("Błąd", str(e))
            finally:
                self.progress.stop()
                self.btn_report.configure(state=tk.NORMAL)

        threading.Thread(target=task, daemon=True).start()

    def _open_portal_browser(self):
        out_dir = Path(self.report_out_var.get().strip())
        portal = (REPO_ROOT / out_dir / "workflow-migration-manual.html").resolve()
        if portal.exists():
            self.log(f"Otwieranie portalu: {portal}")
            webbrowser.open(portal.as_uri())
        else:
            messagebox.showwarning("Brak pliku", f"Plik {portal} nie istnieje. Najpierw wygeneruj raporty.")

    def _open_output_folder(self):
        out_dir = Path(self.report_out_var.get().strip())
        folder = (REPO_ROOT / out_dir).resolve()
        if folder.exists():
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        else:
            messagebox.showwarning("Brak katalogu", f"Katalog {folder} nie istnieje.")


def main():
    app = DoraMigrationApp()
    app.mainloop()


if __name__ == "__main__":
    main()
