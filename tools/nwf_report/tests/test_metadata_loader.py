"""Unit tests for metadata_loader module."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from tools.nwf_report.metadata_loader import (
    ColumnInfo,
    FieldResolver,
    ListInfo,
    SiteMetadata,
    _norm_guid,
    load_site_metadata,
)
from tools.nwf_report.nwf_parser import FieldRef, ListReference


def test_norm_guid() -> None:
    guid_with_braces = "{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}"
    guid_without_braces = "A1B2C3D4-E5F6-7890-ABCD-EF1234567890"

    assert _norm_guid(guid_with_braces) == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert _norm_guid(guid_without_braces) == "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    assert _norm_guid("") == ""


def test_field_resolver_list_aware_collision() -> None:
    """Regression test for Bug #3: Same InternalName on different lists must resolve to list-specific DisplayName."""
    list_a_id = "{AAAAAAAA-1111-2222-3333-444444444444}"
    list_b_id = "{BBBBBBBB-1111-2222-3333-444444444444}"

    list_refs = [
        ListReference(
            list_name="Lista A",
            list_id=list_a_id,
            is_source_list=True,
            fields=[
                FieldRef(name="Kolumna Tekstowa", internal_name="Wspolna_x0020_Nazwa", field_type="Text"),
                FieldRef(name="Pole Unikalne A", internal_name="Pole_A", field_type="Text"),
            ],
        ),
        ListReference(
            list_name="Lista B",
            list_id=list_b_id,
            is_source_list=False,
            fields=[
                FieldRef(name="Kolumna Lookup do C", internal_name="Wspolna_x0020_Nazwa", field_type="Lookup"),
                FieldRef(name="Pole Unikalne B", internal_name="Pole_B", field_type="Text"),
            ],
        ),
    ]

    resolver = FieldResolver(list_refs, source_list_id=list_a_id)

    # Resolving with list_hint by GUID
    res_a_guid = resolver.resolve("Wspolna_x0020_Nazwa", list_hint=list_a_id)
    assert res_a_guid == "Kolumna Tekstowa (Wspolna_x0020_Nazwa)"

    res_b_guid = resolver.resolve("Wspolna_x0020_Nazwa", list_hint=list_b_id)
    assert res_b_guid == "Kolumna Lookup do C (Wspolna_x0020_Nazwa)"

    # Resolving with list_hint by list title
    res_a_title = resolver.resolve("Wspolna_x0020_Nazwa", list_hint="Lista A")
    assert res_a_title == "Kolumna Tekstowa (Wspolna_x0020_Nazwa)"

    res_b_title = resolver.resolve("Wspolna_x0020_Nazwa", list_hint="Lista B")
    assert res_b_title == "Kolumna Lookup do C (Wspolna_x0020_Nazwa)"


def test_field_resolver_fallback_internal_name() -> None:
    list_refs = [
        ListReference(
            list_name="Lista A",
            list_id="{AAAAAAAA-1111-2222-3333-444444444444}",
            is_source_list=True,
            fields=[
                FieldRef(name="Tytul Pola A", internal_name="Pole_A", field_type="Text"),
            ],
        ),
    ]
    resolver = FieldResolver(list_refs)

    # Without list_hint: falls back to _by_internal_name
    assert resolver.resolve("Pole_A") == "Tytul Pola A (Pole_A)"

    # Unknown field: returns raw internal_name
    assert resolver.resolve("Nieznane_Pole") == "Nieznane_Pole"


def test_field_resolver_fallback_to_site_metadata() -> None:
    site_metadata = SiteMetadata(
        lists_by_id={
            "cccccccc-1111-2222-3333-444444444444": ListInfo(
                title="Lista C",
                list_id="cccccccc-1111-2222-3333-444444444444",
                columns={
                    "pole_c": ColumnInfo(title="Tytuł z SiteMetadata", internal_name="pole_c")
                },
            )
        },
        lists_by_title={},
        site_columns={
            "kolumna_globalna": ColumnInfo(title="Globalna Kolumna", internal_name="kolumna_globalna")
        },
    )

    resolver = FieldResolver([], site_metadata=site_metadata)

    # Resolving through list in SiteMetadata
    res_c = resolver.resolve("pole_c", list_hint="{CCCCCCCC-1111-2222-3333-444444444444}")
    assert res_c == "Tytuł z SiteMetadata (pole_c)"

    # Resolving through site_columns fallback
    res_global = resolver.resolve("kolumna_globalna")
    assert res_global == "Globalna Kolumna (kolumna_globalna)"


def test_load_site_metadata(tmp_path: Path) -> None:
    # Prepare dummy 00_kolumny_witryny.json
    columns_file = tmp_path / "00_kolumny_witryny.json"
    columns_data = [
        {"Title": "Kolumna 1", "InternalName": "Col1", "TypeAsString": "Text"},
        {"Title": "Kolumna 2", "InternalName": "Col2", "TypeAsString": "Choice"},
    ]
    columns_file.write_text(json.dumps(columns_data), encoding="utf-8")

    # Prepare dummy 10_lista_Testowa.json
    list_file = tmp_path / "10_lista_Testowa.json"
    list_data = {
        "lista": {"Id": "{DDDDDDDD-1111-2222-3333-444444444444}", "Title": "Lista Testowa"},
        "kolumny": [
            {"Title": "Pole Listy", "InternalName": "ListCol", "TypeAsString": "Text"}
        ],
    }
    list_file.write_text(json.dumps(list_data), encoding="utf-8")

    meta = load_site_metadata(tmp_path)

    assert "col1" in meta.site_columns
    assert "col2" in meta.site_columns
    assert meta.site_columns["col1"].title == "Kolumna 1"

    norm_id = "dddddddd-1111-2222-3333-444444444444"
    assert norm_id in meta.lists_by_id
    assert "lista testowa" in meta.lists_by_title
    assert meta.lists_by_id[norm_id].title == "Lista Testowa"
    assert "listcol" in meta.lists_by_id[norm_id].columns
