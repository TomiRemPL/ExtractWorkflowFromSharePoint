"""Unit tests for generate_report CLI module."""
from __future__ import annotations

from pathlib import Path
import sys
import pytest

from tools.nwf_report.generate_report import _safe_filename, main
from tools.nwf_report.tests.fixtures import build_exported_nwf_xml


def test_safe_filename() -> None:
    unsafe = 'DT01: Kwalifikacja / Weryfikacja * "Test"? <A|B>'
    safe = _safe_filename(unsafe)

    for forbidden in r'\/:*?"<>|':
        assert forbidden not in safe

    assert safe == "DT01_ Kwalifikacja _ Weryfikacja _ _Test__ _A_B_"

    # Leading/trailing spaces stripped
    assert _safe_filename("  .nazwa.  ") == ".nazwa."


def test_connection_string_redacted_from_all_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    inner = """<ExportedWorkflow><Title>Secret test</Title><Configurations><ActionConfigs>
      <NWActionConfig><Type>Nintex.Workflow.Activities.Adapters.NWRunSqlAdapter</Type>
        <Enabled>true</Enabled><Parameters>
          <Parameter Name="ConnectionString"><PrimitiveValue Value="Server=test;UID=synthetic_user;PWD=synthetic_password" /></Parameter>
          <Parameter Name="Username"><PrimitiveValue Value="synthetic_user" /></Parameter>
          <Parameter Name="Password"><PrimitiveValue Value="synthetic_password" /></Parameter>
        </Parameters>
      </NWActionConfig></ActionConfigs></Configurations></ExportedWorkflow>"""
    (input_dir / "test.nwf").write_text(build_exported_nwf_xml(inner), encoding="utf-8")

    main(["--input", str(input_dir), "--output", str(output_dir)])

    captured = capsys.readouterr()
    contents = [captured.out, captured.err]
    contents.extend(path.read_text(encoding="utf-8") for path in output_dir.iterdir() if path.is_file())
    assert contents
    for content in contents:
        assert "synthetic_user" not in content
        assert "synthetic_password" not in content
        assert "Server=test;UID=" not in content


def test_recognized_action_with_sensitive_value_is_redacted_and_blocked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    inner = """<ExportedWorkflow><Title>Sensitive value test</Title><Configurations><ActionConfigs>
      <NWActionConfig><Type>SPSetVariableAdapter</Type><Enabled>true</Enabled><Parameters>
        <Parameter Name="VariableName"><Variable Name="Example" Type="Text" /></Parameter>
        <Parameter Name="Value"><PrimitiveValue Value="Server=test;UID=synthetic_user;Pwd=synthetic_password" /></Parameter>
      </Parameters></NWActionConfig>
    </ActionConfigs></Configurations></ExportedWorkflow>"""
    (input_dir / "test.nwf").write_text(build_exported_nwf_xml(inner), encoding="utf-8")

    main(["--input", str(input_dir), "--output", str(output_dir)])

    captured = capsys.readouterr()
    contents = [captured.out, captured.err]
    contents.extend(path.read_text(encoding="utf-8") for path in output_dir.iterdir() if path.is_file())
    assert all("synthetic_user" not in content and "synthetic_password" not in content for content in contents)
    report = (output_dir / "Sensitive value test.md").read_text(encoding="utf-8")
    assert "dane uwierzytelniające" in report
    assert "RAISE_APPLICATION_ERROR" in report


def test_malformed_xml_does_not_echo_sensitive_values(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    broken = '<ExportedWorkflow><Password>synthetic_password</Password><Broken>'
    (input_dir / "broken.nwf").write_text(build_exported_nwf_xml(broken), encoding="utf-8")

    main(["--input", str(input_dir), "--output", str(output_dir)])

    captured = capsys.readouterr()
    output = captured.out + captured.err
    output += "".join(path.read_text(encoding="utf-8") for path in output_dir.iterdir() if path.is_file())
    assert "synthetic_password" not in output
    assert "BŁĄD" in output or "BLAD" in output


def test_unknown_types_are_isolated_between_generator_runs(tmp_path: Path) -> None:
    def write_input(directory: Path, action_type: str) -> None:
        directory.mkdir()
        inner = f"""<ExportedWorkflow><Title>Test</Title><Configurations><ActionConfigs>
          <NWActionConfig><Type>{action_type}</Type><Enabled>true</Enabled></NWActionConfig>
        </ActionConfigs></Configurations></ExportedWorkflow>"""
        (directory / "test.nwf").write_text(build_exported_nwf_xml(inner), encoding="utf-8")

    first_input, second_input = tmp_path / "input1", tmp_path / "input2"
    first_output, second_output = tmp_path / "output1", tmp_path / "output2"
    write_input(first_input, "UnknownSyntheticAdapter")
    write_input(second_input, "NWWorkflowVariablesAdapter")

    main(["--input", str(first_input), "--output", str(first_output)])
    main(["--input", str(second_input), "--output", str(second_output)])

    assert "UnknownSyntheticAdapter" in (first_output / "walkthrough.md").read_text(encoding="utf-8")
    second_walkthrough = (second_output / "walkthrough.md").read_text(encoding="utf-8")
    assert "UnknownSyntheticAdapter" not in second_walkthrough
    assert "**Nierozpoznane typy akcji:** 0" in second_walkthrough
    assert "**Nierozpoznane typy akcji:** 0" in (second_output / "index.md").read_text(encoding="utf-8")


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
