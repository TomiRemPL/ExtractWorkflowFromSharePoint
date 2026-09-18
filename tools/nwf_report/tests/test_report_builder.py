"""Unit tests for report_builder module."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.nwf_report.metadata_loader import FieldResolver
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference, WorkflowModel
from tools.nwf_report.report_builder import (
    _build_mermaid,
    _collect_steps,
    _mermaid_label,
    build_workflow_data,
    build_report,
)


@pytest.fixture
def sample_resolver() -> FieldResolver:
    list_refs = [
        ListReference(
            list_name="Lista Rejestr",
            list_id="{AAAAAAAA-1111-2222-3333-444444444444}",
            is_source_list=True,
            fields=[
                FieldRef("Tytuł Elementu", "Title", "Text"),
                FieldRef("Wartość Kwoty", "Kwota", "Number"),
            ],
        )
    ]
    return FieldResolver(list_refs, source_list_id="{AAAAAAAA-1111-2222-3333-444444444444}")


def test_mermaid_label() -> None:
    short_text = 'Zwykły "tekst"'
    assert _mermaid_label(short_text, max_len=60) == "Zwykły 'tekst'"

    long_text = "To jest bardzo długi tekst, który z całą pewnością przekracza limit sześćdziesięciu znaków i powinien zostać ucięty"
    res = _mermaid_label(long_text, max_len=60)
    assert len(res) == 60
    assert res.endswith("…")

    multiline = "Linia 1\nLinia 2\nLinia 3"
    assert "\n" not in _mermaid_label(multiline)
    assert _mermaid_label(multiline) == "Linia 1 Linia 2 Linia 3"


def test_build_mermaid_flow(sample_resolver: FieldResolver) -> None:
    node1 = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWWorkflowVariablesAdapter",
        enabled=True,
        condition_use="None",
        params={"StartManually": "True"},
        param_elements={},
        field_refs=[],
        children=[],
    )
    node2 = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.SPUpdateItemWithKeyAdapter",
        enabled=True,
        condition_use="None",
        params={},
        param_elements={},
        field_refs=[FieldRef("Wartość Kwoty", "Kwota", "Number")],
        children=[],
        t_label="Krok aktualizacji",
    )

    mermaid_code = _build_mermaid([node1, node2], sample_resolver)

    assert "flowchart TD" in mermaid_code
    assert "--> n1" in mermaid_code
    assert "n1 --> n2" in mermaid_code
    assert "Zaktualizuj element" in mermaid_code


def test_build_mermaid_with_branching(sample_resolver: FieldResolver) -> None:
    branch_nie = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.WFIfElseBranchAdapter",
        enabled=True,
        condition_use="None",
        params={},
        param_elements={},
        field_refs=[],
        children=[
            ActionNode("Nintex.Workflow.Activities.Adapters.NWWriteToHistoryListAdapter", True, "None", {"Message": "Gałąź Nie"}, {}, [], [], t_label="Log Nie")
        ],
        branch_label="Nie",
    )
    branch_tak = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.WFIfElseBranchAdapter",
        enabled=True,
        condition_use="None",
        params={},
        param_elements={},
        field_refs=[],
        children=[
            ActionNode("Nintex.Workflow.Activities.Adapters.NWWriteToHistoryListAdapter", True, "None", {"Message": "Gałąź Tak"}, {}, [], [], t_label="Log Tak")
        ],
        branch_label="Tak",
    )

    cond_node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.WFIfElseAdapter",
        enabled=True,
        condition_use="Child",
        params={},
        param_elements={},
        field_refs=[],
        children=[branch_nie, branch_tak],
        l_label="Nie",
        r_label="Tak",
    )

    mermaid_code = _build_mermaid([cond_node], sample_resolver)

    assert "{" in mermaid_code and "}" in mermaid_code  # Diamond shape for condition
    assert "-- Nie -->" in mermaid_code
    assert "-- Tak -->" in mermaid_code
    assert "Zapisz wpis w historii" in mermaid_code


def test_build_report_structure(sample_resolver: FieldResolver) -> None:
    from pathlib import Path

    action = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.SPUpdateItemWithKeyAdapter",
        enabled=True,
        condition_use="None",
        params={},
        param_elements={},
        field_refs=[FieldRef("Wartość Kwoty", "Kwota", "Number")],
        children=[],
        t_label="Zapisz kwotę",
    )

    wf = WorkflowModel(
        title="Przykładowy Workflow",
        description="Opis działania tego workflow",
        list_references=[
            ListReference("Lista Rejestr", "{AAAAAAAA-1111-2222-3333-444444444444}", True, [
                FieldRef("Wartość Kwoty", "Kwota", "Number")
            ])
        ],
        actions=[action],
        source_path=Path("DaneZeSkryptu/test.nwf"),
    )

    report = build_report(wf, sample_resolver)

    assert "# Przykładowy Workflow" in report
    assert "> Opis działania tego workflow" in report
    assert "## Podstawowe informacje" in report
    assert "**Lista źródłowa:** Lista Rejestr" in report
    assert "## Diagram przepływu" in report
    assert "```mermaid" in report
    assert "## Kroki workflow" in report
    assert "Zaktualizuj element" in report
    assert "## Pola odczytywane / zapisywane" in report
    assert "| Pole | Odczyt | Zapis |" in report
    assert "Wartość Kwoty (Kwota)" in report


def test_build_workflow_data_extracts_migration_contract(sample_resolver: FieldResolver) -> None:
    trigger = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWWorkflowVariablesAdapter",
        enabled=True,
        condition_use="None",
        params={
            "StartManually": "true",
            "StartOnChange": "true",
            "Id": "workflow-123",
        },
        param_elements={},
        field_refs=[],
        children=[],
    )
    variable = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.SPSetVariableAdapter",
        enabled=True,
        condition_use="None",
        params={"Value": "{WorkflowVariable:Status}"},
        param_elements={"VariableName": ET.fromstring('<VariableName Name="Status" Type="Text" Description="Status procesu" />')},
        field_refs=[],
        children=[],
        t_label="Ustaw status",
    )
    update = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.SPUpdateItemWithKeyAdapter",
        enabled=True,
        condition_use="None",
        params={"ListId": "{AAAAAAAA-1111-2222-3333-444444444444}"},
        param_elements={},
        field_refs=[FieldRef("Wartość Kwoty", "Kwota", "Number")],
        children=[],
        t_label="Zapisz kwotę",
    )
    wf = WorkflowModel(
        title="Migracja statusu",
        description="Workflow do migracji",
        list_references=[
            ListReference(
                "Lista Rejestr",
                "{AAAAAAAA-1111-2222-3333-444444444444}",
                True,
                [FieldRef("Wartość Kwoty", "Kwota", "Number")],
            )
        ],
        actions=[trigger, variable, update],
        source_path=Path("DaneZeSkryptu/migracja.nwf"),
    )

    data = build_workflow_data(wf, sample_resolver)

    assert data["triggers"] == ["ręcznie", "zmiana elementu"]
    assert data["workflow_guid"] == "workflow-123"
    assert data["variables"] == [{"name": "Status", "type": "Text", "description": "Status procesu"}]
    assert data["actions_count"] == 2
    assert data["fields"][0]["internal_name"] == "Kwota"
    assert data["steps"][1]["hint_apex"]

