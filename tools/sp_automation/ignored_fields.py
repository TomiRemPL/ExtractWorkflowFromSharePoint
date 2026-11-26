"""Konfigurowalna lista pól Lookup pomijanych przy relacjach (pola wbudowane SharePoint)."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .catalog import FieldRecord, normalize_guid

DEFAULT_IGNORED_FIELDS_PATH = Path(__file__).resolve().parents[2] / "config" / "relations_ignored_fields.json"
_LOOKUP_TYPES = frozenset({"lookup", "lookupmulti"})


@dataclass(frozen=True)
class IgnoredFieldsPolicy:
    """Nazwy wewnętrzne (casefold) i reguła pól wbudowanych wskazujących tabele, nie listy."""

    names: frozenset[str] = frozenset()
    ignore_base_type_non_list_targets: bool = True
    source: str = ""
    warnings: tuple[str, ...] = ()

    def reason(self, field: FieldRecord) -> str:
        """Zwraca powód pominięcia pola albo pusty tekst, gdy pole jest relacją do pokazania."""
        if field.internal_name.casefold() in self.names:
            return f"pole „{field.internal_name}” na liście pomijanych w konfiguracji"
        if (
            self.ignore_base_type_non_list_targets
            and field.type_as_string.lower() in _LOOKUP_TYPES
            and field.metadata.get("FromBaseType") is True
        ):
            target = str(field.lookup_list or "").strip()
            if target.casefold() != "self" and not normalize_guid(target):
                return f"pole wbudowane SharePoint (FromBaseType) wskazujące tabelę „{target or 'brak'}”, nie listę"
        return ""

    def is_ignored(self, field: FieldRecord) -> bool:
        return bool(self.reason(field))


def _names(value: Any, warnings: list[str]) -> set[str]:
    groups = value.values() if isinstance(value, dict) else [value]
    names: set[str] = set()
    for group in groups:
        if not isinstance(group, list):
            warnings.append("Grupa w „ignored_fields” nie jest listą nazw; pominięto ją.")
            continue
        for name in group:
            if isinstance(name, str) and name.strip():
                names.add(name.strip().casefold())
            else:
                warnings.append(f"Niepoprawna nazwa pola w „ignored_fields”: {name!r}; pominięto ją.")
    return names


def load_ignored_fields(path: Path | None = None) -> IgnoredFieldsPolicy:
    """Wczytuje politykę; przy braku lub błędzie pliku zostaje tylko reguła FromBaseType."""
    config_path = Path(path) if path is not None else DEFAULT_IGNORED_FIELDS_PATH
    if not config_path.exists():
        return IgnoredFieldsPolicy(
            source=str(config_path),
            warnings=(f"Brak pliku pól pomijanych ({config_path}); działa tylko reguła FromBaseType.",),
        )
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        message = f"Nie można odczytać pliku pól pomijanych ({config_path}): {exc}; działa tylko reguła FromBaseType."
        logging.warning(message)
        return IgnoredFieldsPolicy(source=str(config_path), warnings=(message,))
    if not isinstance(data, dict):
        message = f"Plik pól pomijanych ({config_path}) nie zawiera obiektu JSON; działa tylko reguła FromBaseType."
        logging.warning(message)
        return IgnoredFieldsPolicy(source=str(config_path), warnings=(message,))
    warnings: list[str] = []
    flag = data.get("ignore_base_type_non_list_targets", True)
    if not isinstance(flag, bool):
        warnings.append("„ignore_base_type_non_list_targets” musi być true/false; przyjęto true.")
        flag = True
    names = _names(data.get("ignored_fields", []), warnings)
    for message in warnings:
        logging.warning("%s (%s)", message, config_path)
    return IgnoredFieldsPolicy(frozenset(names), flag, str(config_path), tuple(warnings))


_cache: dict[str, tuple[float | None, IgnoredFieldsPolicy]] = {}


def default_ignored_fields() -> IgnoredFieldsPolicy:
    """Polityka z domyślnego pliku, wczytywana ponownie po zmianie pliku."""
    path = DEFAULT_IGNORED_FIELDS_PATH
    try:
        mtime: float | None = path.stat().st_mtime
    except OSError:
        mtime = None
    cached = _cache.get(str(path))
    if cached is None or cached[0] != mtime:
        cached = (mtime, load_ignored_fields(path))
        _cache[str(path)] = cached
    return cached[1]
