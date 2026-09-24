"""Unit tests for generate_report CLI module."""
from __future__ import annotations

from pathlib import Path
import sys
import pytest

from tools.nwf_report.generate_report import _safe_filename, main


def test_safe_filename() -> None:
    unsafe = 'DT01: Kwalifikacja / Weryfikacja * "Test"? <A|B>'
    safe = _safe_filename(unsafe)

    for forbidden in r'\/:*?"<>|':
        assert forbidden not in safe

    assert safe == "DT01_ Kwalifikacja _ Weryfikacja _ _Test__ _A_B_"

    # Leading/trailing spaces stripped
    assert _safe_filename("  .nazwa.  ") == ".nazwa."


def test_e2e_generate_report_sample_workflows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Smoke/Integration test running generate_report on real files in DaneZeSkryptu."""
    dane_dir = Path("DaneZeSkryptu")
    if not dane_dir.exists():
        pytest.skip("Katalog DaneZeSkryptu nie istnieje w bieżącym katalogu")

    out_dir = tmp_path / "out"

    test_args = [
        "generate_report.py",
        "--input",
        str(dane_dir),
        "--output",
        str(out_dir),
    ]
    monkeypatch.setattr(sys, "argv", test_args)

    main()

    # Verify index.md was generated
    index_path = out_dir / "index.md"
    assert index_path.exists()
    index_content = index_path.read_text(encoding="utf-8")
    assert "# Raporty workflow Nintex" in index_content

    # Verify walkthrough.md was generated
    walkthrough_path = out_dir / "walkthrough.md"
    assert walkthrough_path.exists()
    walkthrough_content = walkthrough_path.read_text(encoding="utf-8")
    assert "# Podsumowanie przetwarzania przepływów pracy (Walkthrough)" in walkthrough_content
    assert "Liczba znalezionych plików `.nwf`:" in walkthrough_content

    # Check that at least 4 workflow markdown files + index.md + walkthrough.md exist
    md_files = list(out_dir.glob("*.md"))
    assert len(md_files) >= 6

    # Check that representative reports were created
    expected_names = [
        "DT01 Mechanizm Kwalifikacji Usługi.md",
        "DT01 Wypełnienie pól Nr RKU oraz Nazwa.md",
        "RT0202 Pobranie danych z Kwalifikacji Usługi.md",
        "RT0701 Pobranie danych z Kwalifikacji Usługi do RT0701.md",
    ]
    for expected in expected_names:
        report_file = out_dir / expected
        assert report_file.exists(), f"Brak wygenerowanego raportu {expected}"
        content = report_file.read_text(encoding="utf-8")
        assert content.startswith("# ")
        assert "```mermaid" in content

    # Verify workflow-migration-manual.html was generated and contains interactive app
    html_path = out_dir / "workflow-migration-manual.html"
    assert html_path.exists(), "Brak wygenerowanego pliku workflow-migration-manual.html"
    html_content = html_path.read_text(encoding="utf-8")
    assert "<!doctype html>" in html_content
    assert 'id="workflows-data"' in html_content
    assert 'id="inspector"' in html_content
    assert 'function resolveMermaidNodeId(nodeEl, wf)' in html_content
    assert 'viewState.startNodeEl' in html_content
    assert 'document.elementFromPoint(event.clientX, event.clientY)' in html_content
    assert '"node_id": "start"' in html_content
    assert '"node_id": "stop"' in html_content
    assert "DT01 Mechanizm Kwalifikacji" in html_content
    assert "Oracle APEX Flow" in html_content

