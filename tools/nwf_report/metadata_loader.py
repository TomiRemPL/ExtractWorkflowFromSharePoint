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
from typing import Any
from uuid import UUID
from xml.etree import ElementTree as ET


@dataclass
class ColumnInfo:
    title: str
    internal_name: str
    type_as_string: str = ""
    formula: str = ""
    field_id: str = ""
    entity_property_name: str = ""
    lookup_field: str = ""
    lookup_list: str = ""
    schema_xml: str = ""


@dataclass(frozen=True)
class RestFieldMapping:
    property_name: str
    lookup_value: str = "Title"
    error: str = ""
    warnings: tuple[str, ...] = ()


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


def _column_info(col: dict[str, Any]) -> ColumnInfo:
    return ColumnInfo(
        title=col.get("Title", ""),
        internal_name=col.get("InternalName", ""),
        type_as_string=col.get("TypeAsString", ""),
        formula=col.get("Formula", "") or "",
        field_id=col.get("Id", "") or "",
        entity_property_name=col.get("EntityPropertyName", "") or "",
        lookup_field=col.get("LookupField", "") or "",
        lookup_list=col.get("LookupList", "") or "",
        schema_xml=col.get("SchemaXml", "") or "",
    )


def load_site_metadata(dane_dir: str | Path) -> SiteMetadata:
    dane_dir = Path(dane_dir)
    meta = SiteMetadata()

    site_columns_path = dane_dir / "00_kolumny_witryny.json"
    if site_columns_path.exists():
        for col in _load_json(site_columns_path):
            info = _column_info(col)
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
            info = _column_info(col)
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
        ambiguous_names: set[str] = set()
        self._types_by_list: dict[str, dict[str, str]] = {}  # list_id/list_name (lower) -> {internal_name: FieldType}
        self._list_id_to_name: dict[str, str] = {}
        self.source_list_id = source_list_id
        self.source_list_name = ""
        for lr in list_references:
            if lr.list_id and lr.list_name:
                self._list_id_to_name[_norm_guid(lr.list_id)] = lr.list_name
            if lr.is_source_list and lr.list_name:
                self.source_list_name = lr.list_name
            per_list: dict[str, str] = {}
            per_list_types: dict[str, str] = {}
            for f in lr.fields:
                if not f.internal_name:
                    continue
                title = f.name or f.internal_name
                per_list[f.internal_name.lower()] = title
                if f.field_type:
                    per_list_types[f.internal_name.lower()] = f.field_type
                key = f.internal_name.lower()
                if key not in ambiguous_names:
                    existing = self._by_internal_name.get(key)
                    if existing is not None and existing != title:
                        self._by_internal_name.pop(key)
                        ambiguous_names.add(key)
                    else:
                        self._by_internal_name[key] = title
            if lr.list_id:
                self._by_list_and_name[_norm_guid(lr.list_id)] = per_list
                self._types_by_list[_norm_guid(lr.list_id)] = per_list_types
            if lr.list_name:
                self._by_list_and_name[lr.list_name.lower()] = per_list
                self._types_by_list[lr.list_name.lower()] = per_list_types
        self._site_metadata = site_metadata or SiteMetadata()

    def _site_list(self, list_hint: str) -> ListInfo | None:
        if not list_hint:
            return None
        return (
            self._site_metadata.lists_by_id.get(_norm_guid(list_hint))
            or self._site_metadata.lists_by_title.get(list_hint.lower())
        )

    def resolve_rest_field(
        self, internal_name: str, list_hint: str = "", *, lookup: bool = False
    ) -> RestFieldMapping:
        """Resolve the REST property and displayed lookup field using list-specific metadata."""
        effective_list = list_hint or self.source_list_id or self.source_list_name
        list_info = self._site_list(effective_list)
        column = list_info.columns.get(internal_name.lower()) if list_info else None
        if list_info is None or column is None:
            return RestFieldMapping(
                internal_name,
                warnings=(f"Brak metadanych REST pola {internal_name}; przyjęto InternalName.",),
            )

        property_name = column.entity_property_name or column.internal_name
        warnings: list[str] = []
        if not column.entity_property_name:
            warnings.append(f"Brak EntityPropertyName pola {internal_name}; przyjęto InternalName.")
        if not lookup:
            return RestFieldMapping(property_name, warnings=tuple(warnings))

        attributes: dict[str, str] = {}
        if column.schema_xml:
            try:
                attributes = ET.fromstring(column.schema_xml).attrib
            except ET.ParseError as exc:
                return RestFieldMapping(
                    property_name,
                    error=f"Niepoprawny SchemaXml pola {internal_name}: {exc}; wymagana ręczna migracja.",
                    warnings=tuple(warnings),
                )

        field_ref = attributes.get("FieldRef", "")
        parent: ColumnInfo | None = None
        if field_ref:
            try:
                parent_id = str(UUID(field_ref.strip().strip("{}")))
            except ValueError:
                warnings.append(
                    f"Pole {internal_name} ma systemowy FieldRef {field_ref}; "
                    "dotychczasowe mapowanie Lookup wymaga ręcznej weryfikacji."
                )
                return RestFieldMapping(property_name, warnings=tuple(warnings))
            parents = [
                candidate for candidate in list_info.columns.values()
                if candidate.field_id and _norm_guid(candidate.field_id) == parent_id
            ]
            if len(parents) != 1 or parents[0].internal_name.lower() == internal_name.lower():
                return RestFieldMapping(
                    property_name,
                    error=f"Nie ustalono głównego pola Lookup dla {internal_name} (FieldRef: {field_ref}).",
                    warnings=tuple(warnings),
                )
            parent = parents[0]
            if parent.type_as_string and not parent.type_as_string.lower().startswith("lookup"):
                return RestFieldMapping(
                    property_name,
                    error=f"Główne pole {parent.internal_name} dla {internal_name} nie jest polem Lookup.",
                    warnings=tuple(warnings),
                )
            if column.lookup_list and parent.lookup_list and (
                _norm_guid(column.lookup_list) != _norm_guid(parent.lookup_list)
            ):
                return RestFieldMapping(
                    property_name,
                    error=f"Pola {internal_name} i {parent.internal_name} wskazują różne listy Lookup.",
                    warnings=tuple(warnings),
                )
            property_name = parent.entity_property_name or parent.internal_name
            if not parent.entity_property_name:
                warnings.append(
                    f"Brak EntityPropertyName głównego pola {parent.internal_name}; przyjęto InternalName."
                )

        lookup_value = column.lookup_field or attributes.get("ShowField", "")
        if not lookup_value:
            if parent:
                return RestFieldMapping(
                    property_name,
                    error=f"Nie ustalono pola docelowego Lookup dla {internal_name}.",
                    warnings=tuple(warnings),
                )
            lookup_value = "Title"
            warnings.append(f"Nie ustalono pola docelowego Lookup dla {internal_name}; przyjęto Title.")

        target_hint = column.lookup_list or (parent.lookup_list if parent else "")
        target_list = self._site_list(target_hint)
        target_column = target_list.columns.get(lookup_value.lower()) if target_list else None
        if target_column:
            if target_column.entity_property_name:
                lookup_value = target_column.entity_property_name
            else:
                warnings.append(
                    f"Brak EntityPropertyName pola docelowego {lookup_value} dla {internal_name}; "
                    "przyjęto InternalName."
                )
        elif lookup_value.lower() != "title":
            warnings.append(
                f"Nie potwierdzono nazwy REST pola docelowego {lookup_value} dla {internal_name}."
            )

        return RestFieldMapping(property_name, lookup_value, warnings=tuple(warnings))

    def get_list_name(self, list_hint: str = "") -> str:
        """Zwraca czytelną nazwę listy na podstawie GUID-a lub podpowiedzi listy."""
        if not list_hint:
            list_hint = self.source_list_id
        if not list_hint:
            return self.source_list_name or "Lista_Docelowa"
        norm = _norm_guid(list_hint)
        if norm in self._list_id_to_name:
            return self._list_id_to_name[norm]
        list_info = self._site_metadata.lists_by_id.get(norm)
        if list_info and list_info.title:
            return list_info.title
        list_info = self._site_metadata.lists_by_title.get(list_hint.lower())
        if list_info and list_info.title:
            return list_info.title
        return list_hint

    def resolve(self, internal_name: str, list_hint: str = "") -> str:
        if not internal_name:
            return "(brak)"
        key = internal_name.lower()

        # Najpierw probujemy dopasowac w kontekscie konkretnej listy (unika kolizji
        # nazw wewnetrznych powtarzajacych sie na roznych listach).
        effective_list = list_hint or self.source_list_id
        if effective_list:
            per_list = self._by_list_and_name.get(_norm_guid(effective_list)) or self._by_list_and_name.get(effective_list.lower())
            if per_list and key in per_list:
                return f"{per_list[key]} ({internal_name})"

            list_info = self._site_metadata.lists_by_id.get(_norm_guid(effective_list)) or \
                self._site_metadata.lists_by_title.get(effective_list.lower())
            if list_info:
                col = list_info.columns.get(key)
                if col:
                    return f"{col.title} ({internal_name})"
            return internal_name

        title = self._by_internal_name.get(key)
        if title:
            return f"{title} ({internal_name})"

        col = self._site_metadata.site_columns.get(key)
        if col:
            return f"{col.title} ({internal_name})"

        return internal_name  # nierozpoznane - zwracamy nazwe techniczna bez tlumaczenia

    def get_field_type(self, internal_name: str, list_hint: str = "") -> str:
        """Zwraca typ pola SharePoint (np. Text, Lookup, User) w kontekscie listy; pusty, gdy nieznany."""
        if not internal_name:
            return ""
        key = internal_name.lower()
        list_hint = list_hint or self.source_list_id
        if list_hint:
            per_list = self._types_by_list.get(_norm_guid(list_hint)) or self._types_by_list.get(list_hint.lower())
            if per_list and key in per_list:
                return per_list[key]
            list_info = self._site_metadata.lists_by_id.get(_norm_guid(list_hint)) or \
                self._site_metadata.lists_by_title.get(list_hint.lower())
            if list_info and key in list_info.columns and list_info.columns[key].type_as_string:
                return list_info.columns[key].type_as_string
            return ""
        col = self._site_metadata.site_columns.get(key)
        return col.type_as_string if col else ""

    def get_title(self, internal_name: str, list_hint: str = "") -> str:
        """Zwraca sama czytelna nazwe pola (DisplayName), bez doklejonego (InternalName)."""
        resolved = self.resolve(internal_name, list_hint)
        suffix = f" ({internal_name})"
        if resolved.endswith(suffix):
            return resolved[:-len(suffix)]
        return resolved
