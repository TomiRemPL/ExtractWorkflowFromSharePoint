"""Tests for tools.sp_extractor.naming."""

from pathlib import Path
import pytest
from tools.sp_extractor.naming import get_next_output_dir, resolve_output_dir, sanitize_filename


def test_sanitize_filename():
    assert sanitize_filename("Normal Title") == "Normal_Title"
    assert sanitize_filename("List: With / Illegal \\ Chars * ?") == "List_With_Illegal_Chars"
    assert sanitize_filename("Trailing dot.") == "Trailing_dot"
    assert sanitize_filename("   Spaces   ") == "Spaces"
    assert sanitize_filename("") == "unnamed"


def test_get_next_output_dir_empty(tmp_path: Path):
    next_dir = get_next_output_dir(base_dir=tmp_path)
    assert next_dir == tmp_path / "DaneZeSkryptu_001"


def test_get_next_output_dir_existing_sequence(tmp_path: Path):
    (tmp_path / "DaneZeSkryptu").mkdir()
    (tmp_path / "DaneZeSkryptu_001").mkdir()
    (tmp_path / "DaneZeSkryptu_002").mkdir()
    (tmp_path / "Other_Directory").mkdir()

    next_dir = get_next_output_dir(base_dir=tmp_path)
    assert next_dir == tmp_path / "DaneZeSkryptu_003"


def test_get_next_output_dir_gap(tmp_path: Path):
    (tmp_path / "DaneZeSkryptu_005").mkdir()

    next_dir = get_next_output_dir(base_dir=tmp_path)
    assert next_dir == tmp_path / "DaneZeSkryptu_006"


def test_resolve_output_dir_explicit(tmp_path: Path):
    custom = tmp_path / "MyCustomDir"
    resolved = resolve_output_dir(output=custom, base_dir=tmp_path, create=True)
    assert resolved == custom
    assert custom.exists()
    assert custom.is_dir()


def test_resolve_output_dir_auto(tmp_path: Path):
    resolved = resolve_output_dir(output=None, base_dir=tmp_path, create=True)
    assert resolved == tmp_path / "DaneZeSkryptu_001"
    assert resolved.exists()
    assert resolved.is_dir()

    # Second call should find 001 exists and create 002
    resolved2 = resolve_output_dir(output=None, base_dir=tmp_path, create=True)
    assert resolved2 == tmp_path / "DaneZeSkryptu_002"
    assert resolved2.exists()
