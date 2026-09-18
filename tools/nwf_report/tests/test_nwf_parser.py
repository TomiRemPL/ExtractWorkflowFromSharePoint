"""Unit tests for nwf_parser module."""
from __future__ import annotations

import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

from tools.nwf_report.nwf_parser import (
    ActionNode,
    FieldRef,
    ListReference,
    WorkflowModel,
    iter_actions,
    parse_nwf,
    _branch_labels,
    _parse_action,
    _parse_field_refs,
    _parse_param_elements,
    _parse_parameters,
)
from tools.nwf_report.tests.fixtures import (
    MINIMAL_INNER_WORKFLOW_XML,
    build_exported_nwf_xml,
)


def test_parse_nwf_structure(tmp_path: Path) -> None:
    xml_content = build_exported_nwf_xml()
    file_path = tmp_path / "test.nwf"
    file_path.write_text(xml_content, encoding="utf-8-sig")

    model = parse_nwf(file_path)

    assert model.title == "Test Workflow"
    assert model.description == "Workflow testowy description"
    assert len(model.list_references) == 2
    assert model.source_list is not None
    assert model.source_list.list_name == "Lista Testowa A"
    assert model.source_list.is_source_list is True
    assert len(model.actions) == 2


def test_parse_action_parameters() -> None:
    action_xml = """<NWActionConfig>
      <Type>Nintex.Workflow.Activities.Adapters.SPSetVariableAdapter</Type>
      <Enabled>true</Enabled>
      <ConditionUse>None</ConditionUse>
      <Parameters>
        <Parameter Name="SimpleParam"><PrimitiveValue Value="ProstaWartosc" /></Parameter>
        <Parameter Name="VariableName"><Variable Name="varTest" /></Parameter>
        <Parameter Name="Value">
          <ListLookup LookupType="ThisItemLookup">
            <Field Name="Kolumna1" Type="Text" />
          </ListLookup>
        </Parameter>
      </Parameters>
    </NWActionConfig>"""
    el = ET.fromstring(action_xml)

    params = _parse_parameters(el)
    assert params["SimpleParam"] == "ProstaWartosc"
    assert not params["VariableName"]
    assert not params["Value"].strip()

    param_elements = _parse_param_elements(el)
    assert "VariableName" in param_elements
    assert param_elements["VariableName"].tag == "Variable"
    assert param_elements["VariableName"].attrib["Name"] == "varTest"
    assert "Value" in param_elements
    assert param_elements["Value"].tag == "ListLookup"


def test_branch_labels_for_if_else() -> None:
    action_xml = """<NWActionConfig>
      <Type>Nintex.Workflow.Activities.Adapters.WFIfElseAdapter</Type>
      <LLabel>Nie</LLabel>
      <RLabel>Tak</RLabel>
    </NWActionConfig>"""
    el = ET.fromstring(action_xml)

    labels = _branch_labels("WFIfElseAdapter", el, 2)
    assert labels == ["Nie", "Tak"]

    # When branch count is not 2
    labels_other = _branch_labels("WFIfElseAdapter", el, 3)
    assert labels_other == ["", "", ""]


def test_parse_action_with_child_activities() -> None:
    action_xml = """<NWActionConfig>
      <Type>Nintex.Workflow.Activities.Adapters.WFIfElseAdapter</Type>
      <Enabled>true</Enabled>
      <ConditionUse>Child</ConditionUse>
      <LLabel>Opcja Nie</LLabel>
      <RLabel>Opcja Tak</RLabel>
      <ChildActivities>
        <NWActionConfig>
          <Type>Nintex.Workflow.Activities.Adapters.WFIfElseBranchAdapter</Type>
          <Enabled>true</Enabled>
          <ChildActivities>
            <NWActionConfig>
              <Type>Nintex.Workflow.Activities.Adapters.NWWriteToHistoryListAdapter</Type>
              <Enabled>true</Enabled>
            </NWActionConfig>
          </ChildActivities>
        </NWActionConfig>
        <NWActionConfig>
          <Type>Nintex.Workflow.Activities.Adapters.WFIfElseBranchAdapter</Type>
          <Enabled>true</Enabled>
          <ChildActivities />
        </NWActionConfig>
      </ChildActivities>
    </NWActionConfig>"""
    el = ET.fromstring(action_xml)
    node = _parse_action(el)

    assert node.type.endswith("WFIfElseAdapter")
    assert len(node.children) == 2
    assert node.children[0].branch_label == "Opcja Nie"
    assert node.children[1].branch_label == "Opcja Tak"
    assert len(node.children[0].children) == 1
    assert node.children[0].children[0].type.endswith("NWWriteToHistoryListAdapter")


def test_parse_field_refs() -> None:
    action_xml = """<NWActionConfig>
      <FieldReferences>
        <FieldReference Name="Etykieta 1" Value="Pole_x0020_A" Type="Text" />
        <FieldReference Name="" Value="Pole_x0020_B" Type="Choice" />
      </FieldReferences>
    </NWActionConfig>"""
    el = ET.fromstring(action_xml)
    refs = _parse_field_refs(el)

    assert len(refs) == 2
    assert refs[0].name == "Etykieta 1"
    assert refs[0].internal_name == "Pole_x0020_A"
    assert refs[0].field_type == "Text"
    assert refs[1].name == ""
    assert refs[1].internal_name == "Pole_x0020_B"


def test_iter_actions() -> None:
    child2 = ActionNode("TypeC", True, "None", {}, {}, [], [])
    child1 = ActionNode("TypeB", True, "None", {}, {}, [], [child2])
    root = ActionNode("TypeA", True, "None", {}, {}, [], [child1])

    flattened = list(iter_actions([root]))
    assert len(flattened) == 3
    assert flattened[0] == (root, 0)
    assert flattened[1] == (child1, 1)
    assert flattened[2] == (child2, 2)
