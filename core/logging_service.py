"""Obsługa dziennika zdarzeń i bufora logów na żywo dla interfejsu webowego."""
from __future__ import annotations

import io
import logging
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable

from tools.nwf_report.app_info import APP_VERSION

LOG_FILE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
UI_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"


def create_log_file_handler(log_dir: Path, now: datetime | None = None) -> logging.FileHandler:
    """Tworzy plik logu `dora_gui_RRRRMMDD_GGMMSS.log` dla jednego uruchomienia aplikacji."""
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    handler = logging.FileHandler(log_dir / f"dora_gui_{stamp}.log", encoding="utf-8")
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(LOG_FILE_FORMAT))
    return handler


class LineWriter(io.TextIOBase):
    """Strumień tekstowy przekazujący każdą pełną linię do funkcji logującej."""

    def __init__(self, log_fn: Callable[[str], None], prefix: str = ""):
        super().__init__()
        self._log_fn = log_fn
        self._prefix = prefix
        self._buffer = ""

    def write(self, text: str) -> int:
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._log_fn(self._prefix + line)
        return len(text)

    def flush(self) -> None:
        if self._buffer.strip():
            self._log_fn(self._prefix + self._buffer)
        self._buffer = ""


class LogBuffer:
    """Bezpieczny wątkowo bufor linii logów z indeksowaniem sekwencyjnym."""

    def __init__(self, maxlen: int = 2000):
        self._lock = threading.Lock()
        self._entries: deque[tuple[int, str]] = deque(maxlen=maxlen)
        self._next_id = 1

    def append(self, message: str) -> int:
        with self._lock:
            entry_id = self._next_id
            self._next_id += 1
            self._entries.append((entry_id, message))
            return entry_id

    def get_since(self, last_id: int) -> tuple[int, list[str]]:
        with self._lock:
            lines = [msg for eid, msg in self._entries if eid > last_id]
            latest_id = self._entries[-1][0] if self._entries else last_id
            return latest_id, lines

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class BufferLoggingHandler(logging.Handler):
    """Przekierowuje rekordy `logging` do `LogBuffer`."""

    def __init__(self, buffer: LogBuffer):
        super().__init__()
        self.buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        self.buffer.append(self.format(record))


class LogSession:
    """Zarządza sesją logowania do pliku oraz buforem dla UI."""

    def __init__(self, log_dir: Path):
        self.log_dir = Path(log_dir)
        self.buffer = LogBuffer()
        self.file_handler: logging.FileHandler | None = None
        self.log_file_path: Path | None = None
        self._buffer_handler = BufferLoggingHandler(self.buffer)
        self._buffer_handler.setFormatter(logging.Formatter(UI_LOG_FORMAT, "%H:%M:%S"))
        self._console_logger = logging.getLogger("dora.web.konsola")
        self._console_logger.propagate = False
        self._console_logger.setLevel(logging.INFO)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(self._buffer_handler)
        try:
            self.file_handler = create_log_file_handler(self.log_dir)
        except OSError as exc:
            self.log(f"UWAGA: nie udało się utworzyć pliku logu w {self.log_dir}: {exc}")
            return
        root.addHandler(self.file_handler)
        self._console_logger.addHandler(self.file_handler)
        self.log_file_path = Path(self.file_handler.baseFilename)
        self.log(f"DORA Web {APP_VERSION}; log zapisywany do: {self.log_file_path}")

    def log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.buffer.append(f"{stamp} [INFO] {message}")
        self._console_logger.info(message)

    def log_exception(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.buffer.append(f"{stamp} [ERROR] {message}")
        self._console_logger.exception(message)

    def close(self) -> None:
        root = logging.getLogger()
        root.removeHandler(self._buffer_handler)
        if self.file_handler is not None:
            root.removeHandler(self.file_handler)
            self._console_logger.removeHandler(self.file_handler)
            self.file_handler.close()
            self.file_handler = None
        self._started = False
