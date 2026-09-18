"""Wczytywanie metadanych witryny SharePoint z eksportu JSON (DaneZeSkryptu),
zgodnego z konwencja nazewnictwa opisana w manualu (prefiksy 00_/10_/20_...).

Sluzy jako fallback dla resolvera nazw pol, gdy dany .nwf nie zawiera
wlasnego slownika (ListReferences) dla danej listy (np. listy spoza
witryny lub listy usuniete od czasu eksportu workflow).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ColumnInfo:
    title: str
    internal_name: str
    type_as_string: str = ""
    formula: str = ""


@dataclass
class ListInfo:
    title: str
    list_id: str
    columns: dict[str, ColumnInfo] = field(default_factory=dict)  # klucz: InternalName (lowercase)


@dataclass
class SiteMetadata:
    lists_by_id: dict[str, ListInfo] = field(default_factory=dict)  # klucz: GUID (lowercase, bez klamer)
    lists_by_title: dict[str, ListInfo] = field(default_factory=dict)  # klucz: tytul (lowercase)
    site_columns: dict[str, ColumnInfo] = field(default_factory=dict)  # klucz: InternalName (lowercase), globalny fallback


def _norm_guid(value: str) -> str:
    return value.strip().strip("{}").lower()


def _load_json(path: Path):
    with path.open(encoding="utf-8-sig") as fh:
        return json.load(fh)


def load_site_metadata(dane_dir: str | Path) -> SiteMetadata:
    dane_dir = Path(dane_dir)
    meta = SiteMetadata()

    site_columns_path = dane_dir / "00_kolumny_witryny.json"
    if site_columns_path.exists():
        for col in _load_json(site_columns_path):
            info = ColumnInfo(
                title=col.get("Title", ""),
                internal_name=col.get("InternalName", ""),
                type_as_string=col.get("TypeAsString", ""),
                formula=col.get("Formula", "") or "",
            )
            meta.site_columns[info.internal_name.lower()] = info

    for lista_path in sorted(dane_dir.glob("10_lista_*.json")):
        try:
            data = _load_json(lista_path)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        lista = data.get("lista", {})
        list_id = lista.get("Id", "")
        title = lista.get("Title", "")
        list_info = ListInfo(title=title, list_id=list_id)
        for col in data.get("kolumny", []):
            info = ColumnInfo(
                title=col.get("Title", ""),
                internal_name=col.get("InternalName", ""),
                type_as_string=col.get("TypeAsString", ""),
                formula=col.get("Formula", "") or "",
            )
            list_info.columns[info.internal_name.lower()] = info
        if list_id:
            meta.lists_by_id[_norm_guid(list_id)] = list_info
        if title:
            meta.lists_by_title[title.lower()] = list_info

    return meta


class FieldResolver:
    """Rozwiazuje wewnetrzna nazwe/GUID pola na czytelna postac 'Tytul (nazwa_wewnetrzna)'.

    Kolejnosc zrodel:
    1. Slownik pol z samego pliku .nwf (ListReferences) - najbardziej wiarygodny
       dla danego workflow.
    2. Metadane globalne witryny (00_kolumny_witryny.json / 10_lista_*.json) - fallback.
    """

    def __init__(self, list_references, site_metadata: SiteMetadata | None = None, source_list_id: str = ""):
        self._by_list_and_name: dict[str, dict[str, str]] = {}  # list_id/list_name (lower) -> {internal_name: title}
        self._by_internal_name: dict[str, str] = {}  # fallback bez kontekstu listy (gdy nazwa jednoznaczna)
        self.source_list_id = source_list_id
        for lr in list_references:
            per_list: dict[str, str] = {}
            for f in lr.fields:
                if not f.internal_name:
                    continue
                title = f.name or f.internal_name
                per_list[f.internal_name.lower()] = title
                self._by_internal_name.setdefault(f.internal_name.lower(), title)
            if lr.list_id:
                self._by_list_and_name[_norm_guid(lr.list_id)] = per_list
            if lr.list_name:
                self._by_list_and_name[lr.list_name.lower()] = per_list
        self._site_metadata = site_metadata or SiteMetadata()

    def resolve(self, internal_name: str, list_hint: str = "") -> str:
        if not internal_name:
            return "(brak)"
        key = internal_name.lower()

        # Najpierw probujemy dopasowac w kontekscie konkretnej listy (unika kolizji
        # nazw wewnetrznych powtarzajacych sie na roznych listach).
        if list_hint:
            per_list = self._by_list_and_name.get(_norm_guid(list_hint)) or self._by_list_and_name.get(list_hint.lower())
            if per_list and key in per_list:
                return f"{per_list[key]} ({internal_name})"

        title = self._by_internal_name.get(key)
        if title:
            return f"{title} ({internal_name})"

        if list_hint:
            list_info = self._site_metadata.lists_by_id.get(_norm_guid(list_hint)) or \
                self._site_metadata.lists_by_title.get(list_hint.lower())
            if list_info:
                col = list_info.columns.get(key)
                if col:
                    return f"{col.title} ({internal_name})"

        col = self._site_metadata.site_columns.get(key)
        if col:
            return f"{col.title} ({internal_name})"

        return internal_name  # nierozpoznane - zwracamy nazwe techniczna bez tlumaczenia

    def get_title(self, internal_name: str, list_hint: str = "") -> str:
        """Zwraca sama czytelna nazwe pola (DisplayName), bez doklejonego (InternalName)."""
        resolved = self.resolve(internal_name, list_hint)
        suffix = f" ({internal_name})"
        if resolved.endswith(suffix):
            return resolved[:-len(suffix)]
        return resolved

