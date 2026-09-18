"""Unit tests for action_catalog module."""
from __future__ import annotations

import xml.etree.ElementTree as ET
import pytest

from tools.nwf_report.action_catalog import (
    UNKNOWN_TYPES_SEEN,
    _extract_condition_fields,
    _render_condition,
    _render_value_expr,
    describe_action,
)
from tools.nwf_report.metadata_loader import FieldResolver
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference
from tools.nwf_report.tests.fixtures import (
    SAMPLE_CONDITION_PAIR_XML,
    SAMPLE_CROSS_LOOKUP_XML,
)


@pytest.fixture
def sample_resolver() -> FieldResolver:
    list_refs = [
        ListReference(
            list_name="Lista Źródłowa",
            list_id="{AAAAAAAA-1111-2222-3333-444444444444}",
            is_source_list=True,
            fields=[
                FieldRef("Status Elementu", "Status_x0020_Pola", "Choice"),
                FieldRef("Opis Elementu", "Opis_x0020_Pola", "Text"),
                FieldRef("Klucz Obcy", "KluczLookup", "Lookup"),
            ],
        ),
        ListReference(
            list_name="Lista Zewnętrzna",
            list_id="{BBBBBBBB-1111-2222-3333-444444444444}",
            is_source_list=False,
            fields=[
                FieldRef("Pole Zewnętrzne B", "Pole_x0020_Docelowe_B", "Text"),
            ],
        ),
    ]
    return FieldResolver(list_refs, source_list_id="{AAAAAAAA-1111-2222-3333-444444444444}")


def test_describe_set_variable_reads_and_names(sample_resolver: FieldResolver) -> None:
    """Regression test for Bug #2: VariableName comes from <Variable> in param_elements, value from <ListLookup>."""
    var_el = ET.fromstring('<Variable Name="zmienna_status" />')
    lookup_el = ET.fromstring(
        '<ListLookup LookupType="ThisItemLookup"><Field Name="Status_x0020_Pola" Type="Choice" /></ListLookup>'
    )

    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.SPSetVariableAdapter",
        enabled=True,
        condition_use="None",
        params={"VariableName": "", "Value": ""},  # empty in params because they are complex elements
        param_elements={"VariableName": var_el, "Value": lookup_el},
        field_refs=[],
        children=[],
        t_label="Ustaw status roboczy",
    )

    desc = describe_action(node, sample_resolver)

    assert "Ustaw status roboczy" in desc.summary
    assert "Zapisz w zmiennej 'zmienna_status'" in desc.summary
    assert "Status Elementu (Status_x0020_Pola)" in desc.summary
    assert len(desc.reads) == 1
    assert desc.reads[0].internal_name == "Status_x0020_Pola"
    assert desc.is_structural is False


def test_describe_if_else(sample_resolver: FieldResolver) -> None:
    cond_el = ET.fromstring(SAMPLE_CONDITION_PAIR_XML)
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.WFIfElseAdapter",
        enabled=True,
        condition_use="Child",
        params={},
        param_elements={},
        field_refs=[],
        children=[],
        condition_el=cond_el,
    )

    desc = describe_action(node, sample_resolver)

    assert desc.summary.startswith("Warunek: JEŻELI")
    assert "Status Elementu (Status_x0020_Pola)" in desc.summary
    assert "jest równe Aktywny" in desc.summary
    assert "LUB" in desc.summary
    assert "zawiera Pilne" in desc.summary
    assert len(desc.reads) == 2
    read_names = [r.internal_name for r in desc.reads]
    assert "Status_x0020_Pola" in read_names
    assert "Opis_x0020_Pola" in read_names


def test_describe_update_item(sample_resolver: FieldResolver) -> None:
    fields = [
        FieldRef("Status Elementu", "Status_x0020_Pola", "Choice"),
        FieldRef("Opis Elementu", "Opis_x0020_Pola", "Text"),
    ]
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.SPUpdateItemWithKeyAdapter",
        enabled=True,
        condition_use="None",
        params={"UpdateType": "ThisItem"},
        param_elements={},
        field_refs=fields,
        children=[],
    )

    desc = describe_action(node, sample_resolver)

    assert "Zaktualizuj element" in desc.summary
    assert len(desc.writes) == 2
    assert desc.writes[0].internal_name == "Status_x0020_Pola"
    assert desc.writes[1].internal_name == "Opis_x0020_Pola"


def test_describe_cross_item_lookup(sample_resolver: FieldResolver) -> None:
    lookup_el = ET.fromstring(SAMPLE_CROSS_LOOKUP_XML)
    rendered = _render_value_expr(lookup_el, sample_resolver)

    assert "Pole Zewnętrzne B (Pole_x0020_Docelowe_B)" in rendered
    assert "Klucz Obcy (KluczLookup)" in rendered


def test_describe_structural_adapters(sample_resolver: FieldResolver) -> None:
    parallel_node = ActionNode("Nintex.Workflow.Activities.Adapters.WFParallelAdapter", True, "None", {}, {}, [], [])
    branch_node = ActionNode("Nintex.Workflow.Activities.Adapters.WFIfElseBranchAdapter", True, "None", {}, {}, [], [])

    desc_parallel = describe_action(parallel_node, sample_resolver)
    desc_branch = describe_action(branch_node, sample_resolver)

    assert desc_parallel.is_structural is True
    assert desc_branch.is_structural is True


def test_fallback_for_unknown_type(sample_resolver: FieldResolver) -> None:
    UNKNOWN_TYPES_SEEN.clear()
    unknown_node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.CustomUnknownAdapter",
        enabled=True,
        condition_use="None",
        params={"CustomParam": "Wartosc123"},
        param_elements={},
        field_refs=[],
        children=[],
        t_label="Etykieta kroku",
    )

    desc = describe_action(unknown_node, sample_resolver)

    assert "[Nieopisana akcja: Etykieta kroku]" in desc.summary
    assert unknown_node.type in UNKNOWN_TYPES_SEEN

    # Without t_label
    unknown_no_label = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.AnotherUnknownAdapter",
        enabled=True,
        condition_use="None",
        params={},
        param_elements={},
        field_refs=[],
        children=[],
    )
    desc_no_label = describe_action(unknown_no_label, sample_resolver)
    assert "[Nieopisana akcja: AnotherUnknownAdapter]" in desc_no_label.summary
    assert unknown_no_label.type in UNKNOWN_TYPES_SEEN

