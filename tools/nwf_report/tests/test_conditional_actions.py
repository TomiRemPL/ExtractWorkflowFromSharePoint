from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.nwf_report.action_catalog import build_path_b_code, describe_action
from tools.nwf_report.metadata_loader import FieldResolver
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference, WorkflowModel, _parse_action
from tools.nwf_report.report_builder import _build_mermaid_with_steps, build_workflow_data

XSI = 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
SOURCE_ID = "{AAAAAAAA-1111-2222-3333-444444444444}"
TARGET_ID = "{BBBBBBBB-1111-2222-3333-444444444444}"


@pytest.fixture
def resolver() -> FieldResolver:
    return FieldResolver([])


@pytest.fixture
def update_resolver() -> FieldResolver:
    target = ListReference("Lista docelowa", TARGET_ID, False, [FieldRef("Title", "Title", "Text")])
    return FieldResolver([target])


def _condition(operator: str, left: str, right: str) -> str:
    return f"""<Condition xsi:type="NWConditionConfig" Name="Jeśli" {XSI}><Params>
      <Param Name="operator"><PrimitiveValue Value="{operator}" /></Param>
      <Param Name="left">{left}</Param>
      <Param Name="right">{right}</Param>
    </Params></Condition>"""


def _run_if(condition_xml: str, children_xml: str = "") -> ActionNode:
    return _parse_action(ET.fromstring(f"""<NWActionConfig>
      <Type>Nintex.Workflow.Activities.Adapters.NWRunIf2Adapter</Type><Enabled>true</Enabled>
      <ConditionUse>This</ConditionUse><TLabel>Warunek</TLabel>{condition_xml}
      <ChildActivities><NWActionConfig><Type>WFSequenceAdapter</Type><Enabled>true</Enabled>
        <ChildActivities>{children_xml}</ChildActivities>
      </NWActionConfig></ChildActivities></NWActionConfig>"""))


VAR_LEFT = '<Variable Name="Status" Type="Text" />'
HISTORY_CHILD = """<NWActionConfig><Type>NWWriteToHistoryListAdapter</Type><Enabled>true</Enabled>
  <TLabel>Wpis</TLabel><Parameters><Parameter Name="Message"><PrimitiveValue Value="Zapis" /></Parameter></Parameters>
</NWActionConfig>"""


def _condition_code(resolver: FieldResolver, operator: str, right: str, left: str = VAR_LEFT) -> str:
    return describe_action(_run_if(_condition(operator, left, right)), resolver).plsql_code.splitlines()[0]


def test_run_if_plsql_contains_child_actions(resolver: FieldResolver) -> None:
    node = _run_if(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="Tak" />'), HISTORY_CHILD)
    desc = describe_action(node, resolver)

    assert desc.plsql_code.startswith("IF :STATUS = 'Tak' THEN")
    assert "Zapis" in desc.plsql_code
    assert desc.plsql_code.rstrip().endswith("END IF;")
    assert "Akcje warunkowe" not in desc.plsql_code
    assert not desc.blocking_reasons


def test_run_if_mermaid_contains_children_with_labeled_edges(resolver: FieldResolver) -> None:
    node = _run_if(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="Tak" />'), HISTORY_CHILD)
    after = ActionNode("NWWriteToHistoryListAdapter", t_label="Po")
    mermaid, steps = _build_mermaid_with_steps([node, after], resolver)

    assert all(step.node_id for step in steps if step.node.type != "WFSequenceAdapter")
    child = next(step for step in steps if step.node.t_label == "Wpis")
    condition = next(step for step in steps if step.node.t_label == "Warunek")
    assert f"{condition.node_id} -- Tak --> {child.node_id}" in mermaid
    assert "-- Nie -->" in mermaid


def test_empty_run_if_mermaid_keeps_both_exit_labels(resolver: FieldResolver) -> None:
    node = ActionNode(
        "NWRunIf2Adapter",
        condition_el=ET.fromstring(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="Tak" />')),
    )
    mermaid, _ = _build_mermaid_with_steps([node], resolver)
    assert "n1 -- Tak --> stop" in mermaid
    assert "n1 -- Nie --> stop" in mermaid


def test_run_if_apex_spec_has_no_empty_transition_targets(resolver: FieldResolver) -> None:
    node = _run_if(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="Tak" />'), HISTORY_CHILD)
    source = ListReference("Lista", SOURCE_ID, True, [])
    wf = WorkflowModel(
        title="T",
        description="",
        list_references=[source],
        actions=[node],
        source_path=Path("t.nwf"),
        workflow_type="List",
    )
    spec = build_workflow_data(wf, FieldResolver([source], source_list_id=SOURCE_ID))["apex_workflow_spec"]

    targets = [edge["target_node_id"] for activity in spec["activities"] for edge in activity["transitions"]]
    assert targets and all(targets)


def test_if_else_plsql_contains_both_branches(resolver: FieldResolver) -> None:
    yes_child = _parse_action(ET.fromstring(HISTORY_CHILD))
    no_child = ActionNode("NWWriteToHistoryListAdapter", params={"Message": "Inaczej"})
    node = ActionNode(
        "Nintex.Workflow.Activities.Adapters.WFIfElseAdapter",
        condition_use="Child",
        condition_el=ET.fromstring(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="A" />')),
        children=[
            ActionNode("WFSequenceAdapter", branch_label="Tak", children=[yes_child]),
            ActionNode("WFSequenceAdapter", branch_label="Nie", children=[no_child]),
        ],
    )
    code = describe_action(node, resolver).plsql_code

    assert "IF :STATUS = 'A' THEN" in code
    assert "ELSE" in code and "Zapis" in code and "Inaczej" in code


def test_if_else_with_single_false_branch_preserves_its_side(resolver: FieldResolver) -> None:
    no_child = ActionNode("NWWriteToHistoryListAdapter", params={"Message": "Inaczej"}, branch_label="Nie")
    node = ActionNode(
        "WFIfElseAdapter",
        condition_el=ET.fromstring(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="A" />')),
        children=[no_child],
    )
    code = describe_action(node, resolver).plsql_code

    assert "THEN\n    NULL;\nELSE" in code
    assert "Inaczej" in code.split("ELSE", 1)[1]


@pytest.mark.parametrize(
    ("operator", "right", "expected"),
    [
        ("StartsWith", '<PrimitiveValue Value="AB" />', "IF INSTR(:STATUS, 'AB') = 1 THEN"),
        ("EndsWith", '<PrimitiveValue Value="AB" />', "IF SUBSTR(:STATUS, -LENGTH('AB')) = 'AB' THEN"),
        ("Contains", '<PrimitiveValue Value="AB" />', "IF INSTR(:STATUS, 'AB') > 0 THEN"),
        ("Equal", '<PrimitiveValue Value="" />', "IF :STATUS IS NULL THEN"),
        ("NotEqual", '<PrimitiveValue Value="" />', "IF :STATUS IS NOT NULL THEN"),
        ("IsEmpty", '<PrimitiveValue Value="" />', "IF :STATUS IS NULL THEN"),
        ("NotIsEmpty", '<PrimitiveValue Value="" />', "IF :STATUS IS NOT NULL THEN"),
        ("NotEqual", '<PrimitiveValue Value="X" />', "IF (:STATUS IS NULL OR :STATUS != 'X') THEN"),
        ("LessThanOrEqual", "<SpecialReference>CurrentDate</SpecialReference>", "IF :STATUS <= TRUNC(SYSDATE) THEN"),
    ],
)
def test_condition_operators(resolver: FieldResolver, operator: str, right: str, expected: str) -> None:
    assert _condition_code(resolver, operator, right) == expected


def test_unknown_condition_operator_is_blocking(resolver: FieldResolver) -> None:
    desc = describe_action(_run_if(_condition("Matches", VAR_LEFT, '<PrimitiveValue Value="x" />')), resolver)
    assert desc.blocking_reasons
    assert "TODO" in desc.plsql_code


@pytest.mark.parametrize(
    "condition_xml",
    [
        "",
        _condition("Equal", VAR_LEFT, '<PrimitiveValue Value="{Common:Nieznany}" />'),
        _condition("Equal", VAR_LEFT, '<PrimitiveValue Value="{Common:ItemUrl}" />'),
        _condition("Equal", VAR_LEFT, "<UnsupportedValue />"),
        _condition("Equal", '<Variable Name="" />', '<PrimitiveValue Value="x" />'),
        _condition("Equal", "", '<PrimitiveValue Value="x" />'),
        _condition("Equal", VAR_LEFT, ""),
        _condition("GreaterThan", VAR_LEFT, '<PrimitiveValue Value="" />'),
        _condition("Contains", VAR_LEFT, '<PrimitiveValue Value="" />'),
    ],
)
def test_unresolved_conditions_block_both_execution_paths(
    resolver: FieldResolver, condition_xml: str
) -> None:
    node = _run_if(condition_xml, HISTORY_CHILD)
    desc = describe_action(node, resolver)

    assert desc.blocking_reasons
    code = build_path_b_code([node], resolver)
    assert "RAISE_APPLICATION_ERROR(-20090" in code
    assert "Zapis" not in code


@pytest.mark.parametrize(("operator", "missing_child"), [("Xor", False), ("And", True)])
def test_invalid_condition_pair_is_blocking(
    resolver: FieldResolver, operator: str, missing_child: bool
) -> None:
    condition = ET.Element(
        "Condition",
        {"{http://www.w3.org/2001/XMLSchema-instance}type": "ConditionPair", "Operator": operator},
    )
    left = ET.fromstring(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="x" />'))
    left.tag = "Left"
    condition.append(left)
    if not missing_child:
        right = ET.fromstring(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="y" />'))
        right.tag = "Right"
        condition.append(right)
    node = ActionNode("NWRunIf2Adapter", condition_el=condition, children=[ActionNode("NWCommitAdapter")])

    assert describe_action(node, resolver).blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in build_path_b_code([node], resolver)


def test_unresolved_condition_installs_apex_guard_before_actions() -> None:
    node = _run_if(
        _condition("Equal", VAR_LEFT, '<PrimitiveValue Value="{Common:Nieznany}" />'),
        HISTORY_CHILD,
    )
    source = ListReference("Lista", SOURCE_ID, True, [])
    workflow = WorkflowModel("Test", "", [source], [node], Path("t.nwf"), "List")
    spec = build_workflow_data(workflow, FieldResolver([source], source_list_id=SOURCE_ID))["apex_workflow_spec"]

    assert spec["path_a_status"] == "Zablokowana"
    assert spec["path_b_status"] == "Zablokowana"
    assert spec["standard_activities"][1]["node_id"] == "migration_guard"
    assert "RAISE_APPLICATION_ERROR(-20090" in spec["path_b"]["plsql_code"]


def test_conditional_comment_only_branches_have_null_statements(resolver: FieldResolver) -> None:
    condition = ET.fromstring(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="x" />'))
    commit = ActionNode("NWCommitAdapter")
    run_if = ActionNode("NWRunIf2Adapter", condition_el=condition, children=[commit])
    if_else = ActionNode(
        "WFIfElseAdapter",
        condition_el=condition,
        children=[
            ActionNode("WFSequenceAdapter", branch_label="Tak", children=[commit]),
            ActionNode("WFSequenceAdapter", branch_label="Nie", children=[commit]),
        ],
    )

    assert describe_action(run_if, resolver).plsql_code.count("NULL;") == 1
    assert describe_action(if_else, resolver).plsql_code.count("NULL;") == 2
    assert build_path_b_code([run_if], resolver).count("NULL;") == 1


def test_condition_ignores_coercion_element(resolver: FieldResolver) -> None:
    right = '<PrimitiveValue Value="5" /><Coercion>Number</Coercion>'
    code = _condition_code(resolver, "GreaterThan", right)
    assert code.startswith("IF :STATUS > ") and "5" in code and "Number" not in code


def _set_variable(value_xml: str) -> ActionNode:
    return _parse_action(ET.fromstring(f"""<NWActionConfig><Type>SPSetVariableAdapter</Type><Enabled>true</Enabled>
      <Parameters><Parameter Name="VariableName"><Variable Name="Wynik" Type="Text" /></Parameter>
      <Parameter Name="Value">{value_xml}</Parameter></Parameters></NWActionConfig>"""))


def test_set_variable_workflow_start_date_uses_systimestamp(resolver: FieldResolver) -> None:
    desc = describe_action(_set_variable('<WorkflowContextData Name="StartDate" />'), resolver)
    assert desc.plsql_code.startswith(":WYNIK := SYSTIMESTAMP")
    assert "przybliżenie" in desc.plsql_code
    assert not desc.blocking_reasons


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("{Common:WebUrl}", ":V_SITE_URL"),
        ("{Common:StartDate}", "SYSTIMESTAMP"),
        ("{Common:CurrentDate}", "TRUNC(SYSDATE)"),
    ],
)
def test_common_tokens_are_translated(resolver: FieldResolver, token: str, expected: str) -> None:
    desc = describe_action(_set_variable(f'<PrimitiveValue Value="{token}" ValueType="String" />'), resolver)
    assert expected in desc.plsql_code
    assert token not in desc.plsql_code
    assert not desc.blocking_reasons


def test_common_token_inside_text_is_formatted(resolver: FieldResolver) -> None:
    desc = describe_action(_set_variable('<PrimitiveValue Value="Data: {Common:CurrentDate}" ValueType="String" />'), resolver)
    assert "'Data: ' || TO_CHAR(TRUNC(SYSDATE), 'YYYY-MM-DD HH24:MI:SS')" in desc.plsql_code


def test_unknown_common_token_is_blocking(resolver: FieldResolver) -> None:
    desc = describe_action(_set_variable('<PrimitiveValue Value="{Common:Nieznany}" ValueType="String" />'), resolver)
    assert any("Nieprzetłumaczone tokeny" in reason for reason in desc.blocking_reasons)


def test_token_after_comment_marker_in_string_is_blocking(resolver: FieldResolver) -> None:
    node = ActionNode("NWWriteToHistoryListAdapter", params={"Message": "tekst -- {Common:Nieznany}"})
    assert any("Nieprzetłumaczone tokeny" in reason for reason in describe_action(node, resolver).blocking_reasons)


def test_token_only_in_a_real_sql_comment_does_not_block(resolver: FieldResolver) -> None:
    node = ActionNode("NWBusinessProcessAdapter", t_label="{Common:Nieznany}")
    assert not describe_action(node, resolver).blocking_reasons


def test_unresolved_child_token_does_not_block_parent_but_blocks_path_b(resolver: FieldResolver) -> None:
    child = '<NWActionConfig><Type>NWWriteToHistoryListAdapter</Type><Enabled>true</Enabled><Parameters>' \
        '<Parameter Name="Message"><PrimitiveValue Value="{Common:Nieznany}" /></Parameter>' \
        '</Parameters></NWActionConfig>'
    node = _run_if(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="x" />'), child)

    assert not describe_action(node, resolver).blocking_reasons
    assert describe_action(node.children[0].children[0], resolver).blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in build_path_b_code([node], resolver)


def test_unsupported_set_variable_value_is_blocking(resolver: FieldResolver) -> None:
    desc = describe_action(_set_variable("<UnsupportedValue />"), resolver)
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


def _update_item(key_field: str, key_xml: str) -> ActionNode:
    return _parse_action(ET.fromstring(f"""<NWActionConfig><Type>SPUpdateItemWithKeyAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="ListId"><PrimitiveValue Value="{{BBBBBBBB-1111-2222-3333-444444444444}}" /></Parameter>
        <Parameter Name="LookupField"><PrimitiveValue Value="{key_field}" /></Parameter>
        <Parameter Name="LookupFieldValue">{key_xml}</Parameter>
      </Parameters>
      <FieldReferences><FieldReference Name="Status" Value="Status" Type="Text"><PrimitiveValue Value="Nowy" /></FieldReference></FieldReferences>
    </NWActionConfig>"""))


def test_update_item_with_variable_id_key_uses_bind(update_resolver: FieldResolver) -> None:
    desc = describe_action(_update_item("ID", '<Variable Name="RefId" Type="Number" />'), update_resolver)
    assert "p_item_id     => :REFID," in desc.plsql_code
    assert "TODO" not in desc.plsql_code
    assert not desc.blocking_reasons


def test_update_item_with_primitive_id_key_converts_to_number(update_resolver: FieldResolver) -> None:
    desc = describe_action(_update_item("ID", '<PrimitiveValue Value="12" />'), update_resolver)
    assert "p_item_id     => TO_NUMBER('12')," in desc.plsql_code


def test_update_item_with_non_id_key_looks_up_item(update_resolver: FieldResolver) -> None:
    desc = describe_action(_update_item("Title", '<Variable Name="Klucz" Type="Text" />'), update_resolver)
    assert "get_list_items(" in desc.plsql_code
    assert "$top=2&$filter=Title%20eq%20" in desc.plsql_code
    assert "UTL_URL.escape(REPLACE(:KLUCZ, '''', ''''''), TRUE, 'AL32UTF8')" in desc.plsql_code
    assert "IF :KLUCZ IS NULL THEN" in desc.plsql_code
    assert "RAISE_APPLICATION_ERROR(-20094" in desc.plsql_code
    assert "RAISE_APPLICATION_ERROR(-20095" in desc.plsql_code
    assert "$.data[1].Id" in desc.plsql_code
    assert "$.next_url" in desc.plsql_code
    assert "p_item_id     => json_value(l_ref_json, '$.data[0].Id' RETURNING NUMBER)" in desc.plsql_code
    assert not desc.blocking_reasons


def test_update_item_same_list_with_explicit_key_is_not_current_item() -> None:
    node = _update_item("ID", '<Variable Name="RefId" Type="Number" />')
    node.params["ThisItem"] = "false"
    source_id = node.params["ListId"]
    source = ListReference("Lista", source_id, True, [])
    resolver = FieldResolver([source], source_list_id=source_id)

    desc = describe_action(node, resolver)
    assert "p_item_id     => :REFID," in desc.plsql_code
    assert "p_item_id     => :V_ITEM_ID," not in desc.plsql_code
    assert not desc.blocking_reasons


def test_update_item_numeric_key_uses_locale_independent_format(update_resolver: FieldResolver) -> None:
    node = _update_item("Kod", '<Variable Name="Klucz" Type="Number" />')
    node.params["LookupFieldType"] = "Number"
    desc = describe_action(node, update_resolver)

    assert "TO_CHAR(:KLUCZ, 'TM9', 'NLS_NUMERIC_CHARACTERS=''.,''')" in desc.plsql_code
    assert "UTL_URL.escape" not in desc.plsql_code


def test_update_item_without_key_is_blocked(update_resolver: FieldResolver) -> None:
    desc = describe_action(_update_item("ID", '<PrimitiveValue Value="" />'), update_resolver)
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code


def test_update_item_with_unresolved_target_list_is_blocked(resolver: FieldResolver) -> None:
    desc = describe_action(_update_item("ID", '<Variable Name="RefId" Type="Number" />'), resolver)
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


@pytest.mark.parametrize(("field", "field_type"), [("Kod", "Boolean"), ("Kod", ""), ("Title-x", "Text")])
def test_non_id_update_with_unsupported_filter_is_blocked(
    update_resolver: FieldResolver, field: str, field_type: str
) -> None:
    node = _update_item(field, '<Variable Name="Klucz" Type="Text" />')
    node.params["LookupFieldType"] = field_type
    desc = describe_action(node, update_resolver)
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


def test_create_site_item_maps_field_references_and_output_variable(resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWCreateSiteSpecificItemAdapter</Type><Enabled>true</Enabled>
      <BLabel>Lista</BLabel>
      <Parameters>
        <Parameter Name="Output"><Variable Name="NoweId" Type="Number" /></Parameter>
      </Parameters>
      <FieldReferences>
        <FieldReference Name="Tytuł" Value="Title" Type="Text"><Variable Name="Nazwa" Type="Text" /></FieldReference>
        <FieldReference Name="Kod" Value="Kod" Type="Text"><PrimitiveValue Value="K1" /></FieldReference>
      </FieldReferences>
    </NWActionConfig>"""))
    desc = describe_action(node, resolver)

    assert "'Title' VALUE :NAZWA" in desc.plsql_code
    assert "'Kod' VALUE 'K1'" in desc.plsql_code
    assert ":NOWEID := json_value(l_resp, '$.item_id' RETURNING NUMBER);" in desc.plsql_code
    assert {ref.internal_name for ref in desc.writes} == {"Title", "Kod"}


def test_create_site_item_without_fields_is_blocked(resolver: FieldResolver) -> None:
    node = ActionNode("NWCreateSiteSpecificItemAdapter", b_label="Lista")
    desc = describe_action(node, resolver)

    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


def test_create_site_item_without_output_does_not_invent_bind(resolver: FieldResolver) -> None:
    node = ActionNode(
        "NWCreateSiteSpecificItemAdapter",
        b_label="Lista",
        raw_el=ET.fromstring(
            '<NWActionConfig><FieldReferences><FieldReference Value="Title" Type="Text">'
            '<PrimitiveValue Value="Test" /></FieldReference></FieldReferences></NWActionConfig>'
        ),
    )
    desc = describe_action(node, resolver)

    assert not desc.blocking_reasons
    assert "add_list_item" in desc.plsql_code
    assert ":V_NEW_ITEM_ID" not in desc.plsql_code


def test_create_site_item_uses_target_list_metadata_with_single_quoted_id() -> None:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Shared", "Shared", "Lookup")])
    target = ListReference("Target", TARGET_ID, False, [FieldRef("Shared", "Shared", "Text")])
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    node = ActionNode(
        "NWCreateSiteSpecificItemAdapter",
        params={"Query": f"<Lists><List ID='{TARGET_ID}' /></Lists>"},
        raw_el=ET.fromstring(
            '<NWActionConfig><FieldReferences><FieldReference Value="Shared" Type="Text">'
            '<PrimitiveValue Value="Test" /></FieldReference></FieldReferences></NWActionConfig>'
        ),
    )
    desc = describe_action(node, resolver)

    assert "'Shared' VALUE 'Test'" in desc.plsql_code
    assert "'SharedId'" not in desc.plsql_code
    assert not desc.blocking_reasons


def test_create_site_item_uses_label_for_target_list_metadata() -> None:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Shared", "Shared", "Lookup")])
    target = ListReference("Target", TARGET_ID, False, [FieldRef("Shared", "Shared", "Text")])
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    node = ActionNode(
        "NWCreateSiteSpecificItemAdapter",
        b_label="Target",
        raw_el=ET.fromstring(
            '<NWActionConfig><FieldReferences><FieldReference Value="Shared" Type="Text">'
            '<PrimitiveValue Value="Test" /></FieldReference></FieldReferences></NWActionConfig>'
        ),
    )
    desc = describe_action(node, resolver)
    assert "'Shared' VALUE 'Test'" in desc.plsql_code
    assert "'SharedId'" not in desc.plsql_code
    assert not desc.blocking_reasons


def test_create_site_item_wires_source_fields_and_target_list_in_apex() -> None:
    source = ListReference("Source", SOURCE_ID, True, [
        FieldRef("Input", "SourceInput", "Text"),
        FieldRef("Other", "Other", "Text"),
        FieldRef("Source Shared", "Shared", "Lookup"),
    ])
    target = ListReference("Target", TARGET_ID, False, [
        FieldRef("Target Shared", "Shared", "Text"),
        FieldRef("Target Other", "TargetOther", "Text"),
    ])
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    node = ActionNode(
        "NWCreateSiteSpecificItemAdapter",
        params={"Query": f"<List ID='{TARGET_ID}' />"},
        raw_el=ET.fromstring("""<NWActionConfig><FieldReferences>
          <FieldReference Value="Shared" Type="Text">
            <ListLookup LookupType="ThisItemLookup"><Field Name="SourceInput" Type="Text" /></ListLookup>
          </FieldReference>
          <FieldReference Value="TargetOther" Type="Text">
            <PrimitiveValue Value="{ItemProperty:Other}" />
          </FieldReference>
        </FieldReferences></NWActionConfig>"""),
    )
    workflow = WorkflowModel("Test", "", [source, target], [node], Path("t.nwf"), "List")
    data = build_workflow_data(workflow, resolver)
    step = next(step for step in data["steps"] if step["short_type"] == "NWCreateSiteSpecificItemAdapter")
    spec = data["apex_workflow_spec"]
    get_item, parse = spec["standard_activities"][2:4]
    query = next(item["value"] for item in get_item["parameter_mapping"] if item["parameter"] == "p_query")

    assert {item["internal_name"] for item in step["reads"]} == {"SourceInput", "Other"}
    assert {item["list_id"] for item in step["writes"]} == {TARGET_ID}
    assert all(item["list_name"] == "Target" for item in step["writes"])
    assert "SourceInput" in query and "Other" in query
    assert ":SP_SOURCEINPUT := " in parse["plsql_code"]
    assert ":SP_OTHER := " in parse["plsql_code"]
    assert "'Shared' VALUE :SP_SOURCEINPUT" in spec["path_b"]["plsql_code"]
    assert "'TargetOther' VALUE :SP_OTHER" in spec["path_b"]["plsql_code"]


def test_cross_list_value_reports_source_and_target_fields_separately() -> None:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Key", "SourceKey", "Number")])
    target = ListReference("Target", TARGET_ID, False, [FieldRef("Value", "TargetValue", "Text")])
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    node = _set_variable(f"""<ListLookup LookupType="CrossItemLookup">
      <Lookup LookupType="ThisItemLookup"><Field Name="SourceKey" Type="Number" /></Lookup>
      <ListId>{TARGET_ID}</ListId><Field Name="TargetValue" Type="Text" />
      <CompareField Name="ID" Type="Counter" />
    </ListLookup>""")
    desc = describe_action(node, resolver)

    assert {(ref.internal_name, ref.list_id) for ref in desc.reads} == {
        ("SourceKey", ""), ("TargetValue", TARGET_ID)
    }


@pytest.mark.parametrize("usage", ["variable", "condition"])
def test_cross_list_lookup_by_non_id_requires_manual_migration(usage: str) -> None:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Key", "SourceKey", "Text")])
    target = ListReference("Target", TARGET_ID, False, [
        FieldRef("Value", "TargetValue", "Text"),
        FieldRef("Key", "TargetKey", "Text"),
    ])
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    lookup = f"""<ListLookup LookupType="CrossItemLookup">
      <Lookup LookupType="ThisItemLookup"><Field Name="SourceKey" Type="Text" /></Lookup>
      <ListId>{TARGET_ID}</ListId><Field Name="TargetValue" Type="Text" />
      <CompareField Name="TargetKey" Type="Text" />
    </ListLookup>"""
    node = (
        _set_variable(lookup)
        if usage == "variable"
        else _run_if(_condition("Equal", lookup, '<PrimitiveValue Value="x" />'), HISTORY_CHILD)
    )
    workflow = WorkflowModel("Test", "", [source, target], [node], Path("t.nwf"), "List")
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]

    assert any("CrossItemLookup" in reason and "ID" in reason for reason in describe_action(node, resolver).blocking_reasons)
    assert spec["path_a_status"] == "Zablokowana"
    assert spec["path_b_status"] == "Zablokowana"
    assert spec["standard_activities"][1]["node_id"] == "migration_guard"
    assert "RAISE_APPLICATION_ERROR(-20090" in spec["path_b"]["plsql_code"]


def test_cross_list_lookup_with_unresolved_target_is_blocked() -> None:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Key", "SourceKey", "Number")])
    resolver = FieldResolver([source], source_list_id=SOURCE_ID)
    node = _set_variable(f"""<ListLookup LookupType="CrossItemLookup">
      <Lookup LookupType="ThisItemLookup"><Field Name="SourceKey" Type="Number" /></Lookup>
      <ListId>{TARGET_ID}</ListId><Field Name="TargetValue" Type="Text" />
      <CompareField Name="ID" Type="Counter" />
    </ListLookup>""")
    desc = describe_action(node, resolver)

    assert any("listy" in reason and TARGET_ID in reason for reason in desc.blocking_reasons)
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


def test_update_item_wires_fields_used_in_explicit_values() -> None:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Input", "SourceInput", "Text")])
    target = ListReference("Target", TARGET_ID, False, [FieldRef("Status", "Status", "Text")])
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    node = _update_item("ID", '<Variable Name="RefId" Type="Number" />')
    assert node.raw_el is not None
    ref = node.raw_el.find("FieldReferences/FieldReference")
    assert ref is not None
    ref.remove(ref[0])
    ref.append(ET.fromstring('<ListLookup LookupType="ThisItemLookup"><Field Name="SourceInput" Type="Text" /></ListLookup>'))
    workflow = WorkflowModel("Test", "", [source, target], [node], Path("t.nwf"), "List")
    data = build_workflow_data(workflow, resolver)
    step = next(step for step in data["steps"] if step["short_type"] == "SPUpdateItemWithKeyAdapter")
    spec = data["apex_workflow_spec"]
    get_item, parse = spec["standard_activities"][2:4]
    query = next(item["value"] for item in get_item["parameter_mapping"] if item["parameter"] == "p_query")

    assert any(item["internal_name"] == "SourceInput" for item in step["reads"])
    assert "SourceInput" in query
    assert ":SP_SOURCEINPUT := " in parse["plsql_code"]
    assert "'Status' VALUE :SP_SOURCEINPUT" in spec["path_b"]["plsql_code"]


def test_email_tokens_declare_and_parse_all_referenced_fields() -> None:
    source = ListReference("Source", SOURCE_ID, True, [
        FieldRef("Title", "Title", "Text"),
        FieldRef("Details", "Details", "Text"),
        FieldRef("Contact", "Contact", "Text"),
    ])
    resolver = FieldResolver([source], source_list_id=SOURCE_ID)
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWSendMessageAdapter</Type><Enabled>true</Enabled>
      <Approvers><Approver User="{ItemProperty:Contact}" /></Approvers>
      <Message><Subject>{ItemProperty:Title}</Subject><Body>{ItemProperty:Details}</Body></Message>
    </NWActionConfig>"""))
    workflow = WorkflowModel("Test", "", [source], [node], Path("t.nwf"), "List")
    data = build_workflow_data(workflow, resolver)
    step = next(step for step in data["steps"] if step["short_type"] == "NWSendMessageAdapter")
    spec = data["apex_workflow_spec"]
    get_item, parse = spec["standard_activities"][2:4]
    query = next(item["value"] for item in get_item["parameter_mapping"] if item["parameter"] == "p_query")
    variables = {var["static_id"] for var in spec["variables"]}

    assert {item["internal_name"] for item in step["reads"]} == {"Title", "Details", "Contact"}
    for field in ("Title", "Details", "Contact"):
        assert field in query
        assert f":SP_{field.upper()} := " in parse["plsql_code"]
        assert f"SP_{field.upper()}" in variables
        assert f":SP_{field.upper()}" in spec["path_b"]["plsql_code"]


def test_build_string_reads_variable_output_and_declares_its_inputs() -> None:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Title", "Title", "Text")])
    resolver = FieldResolver([source], source_list_id=SOURCE_ID)
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWBuildStringAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="Input"><PrimitiveValue Value="{ItemProperty:Title} {WorkflowVariable:InputVar}" /></Parameter>
        <Parameter Name="Output"><Variable Name="Result" Type="Text" /></Parameter>
      </Parameters></NWActionConfig>"""))
    workflow = WorkflowModel("Test", "", [source], [node], Path("t.nwf"), "List")
    data = build_workflow_data(workflow, resolver)
    spec = data["apex_workflow_spec"]
    step = next(step for step in data["steps"] if step["short_type"] == "NWBuildStringAdapter")
    variables = {var["static_id"] for var in spec["variables"]}

    assert ":RESULT := :SP_TITLE || ' ' || :INPUTVAR;" in step["plsql_code"]
    assert ":V_BUILT_STRING" not in step["plsql_code"]
    assert {"RESULT", "INPUTVAR", "SP_TITLE"} <= variables
    assert any(item["internal_name"] == "Title" for item in step["reads"])
    assert {"Result", "InputVar"} <= {item["name"] for item in data["variables"]}


def test_build_string_without_output_is_blocked(resolver: FieldResolver) -> None:
    node = ActionNode("NWBuildStringAdapter", params={"Input": "Test"})
    desc = describe_action(node, resolver)
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


def test_variables_used_only_in_conditions_are_declared_with_their_types() -> None:
    source = ListReference("Source", SOURCE_ID, True, [])
    resolver = FieldResolver([source], source_list_id=SOURCE_ID)
    node = _run_if(_condition(
        "LessThanOrEqual",
        '<Variable Name="Start" Type="DateTime" />',
        '<Variable Name="Deadline" Type="DateTime" />',
    ), HISTORY_CHILD)
    workflow = WorkflowModel("Test", "", [source], [node], Path("t.nwf"), "List")
    data = build_workflow_data(workflow, resolver)
    spec = data["apex_workflow_spec"]
    variables = {var["static_id"]: var["data_type"] for var in spec["variables"]}

    assert variables["START"] == "TIMESTAMP"
    assert variables["DEADLINE"] == "TIMESTAMP"
    assert any(":START <= :DEADLINE" in activity["plsql_code"] for activity in spec["activities"])
    assert {item["name"]: item["type"] for item in data["variables"]} == {
        "Start": "DateTime", "Deadline": "DateTime"
    }


def test_workflow_variable_tokens_in_email_and_field_values_are_declared() -> None:
    source = ListReference("Source", SOURCE_ID, True, [])
    target = ListReference("Target", TARGET_ID, False, [FieldRef("Title", "Title", "Text")])
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    email = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWSendMessageAdapter</Type><Enabled>true</Enabled>
      <Message><Subject>{WorkflowVariable:SubjectValue}</Subject><Body>Body</Body></Message>
    </NWActionConfig>"""))
    create = ActionNode(
        "NWCreateSiteSpecificItemAdapter",
        params={"Query": f"<List ID='{TARGET_ID}' />"},
        raw_el=ET.fromstring("""<NWActionConfig><FieldReferences>
          <FieldReference Value="Title" Type="Text"><PrimitiveValue Value="{WorkflowVariable:TitleValue}" /></FieldReference>
        </FieldReferences></NWActionConfig>"""),
    )
    workflow = WorkflowModel("Test", "", [source, target], [email, create], Path("t.nwf"), "List")
    data = build_workflow_data(workflow, resolver)
    spec = data["apex_workflow_spec"]
    variables = {var["static_id"] for var in spec["variables"]}

    assert {"SUBJECTVALUE", "TITLEVALUE"} <= variables
    assert ":SUBJECTVALUE" in spec["path_b"]["plsql_code"]
    assert ":TITLEVALUE" in spec["path_b"]["plsql_code"]
    assert {"SubjectValue", "TitleValue"} <= {item["name"] for item in data["variables"]}


def test_create_site_item_with_unresolved_target_list_is_blocked(resolver: FieldResolver) -> None:
    node = ActionNode(
        "NWCreateSiteSpecificItemAdapter",
        params={"Query": f"<List ID='{TARGET_ID}' />"},
        raw_el=ET.fromstring(
            '<NWActionConfig><FieldReferences><FieldReference Value="Title" Type="Text">'
            '<PrimitiveValue Value="Test" /></FieldReference></FieldReferences></NWActionConfig>'
        ),
    )
    desc = describe_action(node, resolver)
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


def test_create_site_item_with_unsupported_value_is_blocked(resolver: FieldResolver) -> None:
    node = ActionNode(
        "NWCreateSiteSpecificItemAdapter",
        b_label="Lista",
        raw_el=ET.fromstring(
            '<NWActionConfig><FieldReferences><FieldReference Value="Title" Type="Text">'
            '<UnsupportedValue /></FieldReference></FieldReferences></NWActionConfig>'
        ),
    )
    desc = describe_action(node, resolver)

    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


def test_set_field_with_key_reads_variable_value(resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>SPSetFieldWithKeyAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="LookupField"><PrimitiveValue Value="Status" /></Parameter>
        <Parameter Name="LookupFieldValue"><Variable Name="NowyStatus" Type="Text" /></Parameter>
      </Parameters></NWActionConfig>"""))
    desc = describe_action(node, resolver)
    assert "'Status' VALUE :NOWYSTATUS" in desc.plsql_code


def test_set_field_with_unsupported_value_is_blocking(resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>SPSetFieldWithKeyAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="LookupField"><PrimitiveValue Value="Status" /></Parameter>
        <Parameter Name="LookupFieldValue"><UnsupportedValue /></Parameter>
      </Parameters></NWActionConfig>"""))
    desc = describe_action(node, resolver)
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


def test_set_field_requires_a_value_but_allows_explicit_empty_value(resolver: FieldResolver) -> None:
    missing = ActionNode("SPSetFieldWithKeyAdapter", params={"LookupField": "Status"})
    empty = _parse_action(ET.fromstring("""<NWActionConfig><Type>SPSetFieldWithKeyAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="LookupField"><PrimitiveValue Value="Status" /></Parameter>
        <Parameter Name="LookupFieldValue"><PrimitiveValue Value="" /></Parameter>
      </Parameters></NWActionConfig>"""))
    no_element = _parse_action(ET.fromstring("""<NWActionConfig><Type>SPSetFieldWithKeyAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="LookupField"><PrimitiveValue Value="Status" /></Parameter>
        <Parameter Name="LookupFieldValue" />
      </Parameters></NWActionConfig>"""))
    direct_text = _parse_action(ET.fromstring("""<NWActionConfig><Type>SPSetFieldWithKeyAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="LookupField"><PrimitiveValue Value="Status" /></Parameter>
        <Parameter Name="LookupFieldValue">Gotowy</Parameter>
      </Parameters></NWActionConfig>"""))

    assert describe_action(missing, resolver).blocking_reasons
    assert "RAISE_APPLICATION_ERROR(-20090" in describe_action(missing, resolver).plsql_code
    assert describe_action(no_element, resolver).blocking_reasons
    assert not describe_action(empty, resolver).blocking_reasons
    assert not describe_action(direct_text, resolver).blocking_reasons
    assert "'Status' VALUE 'Gotowy'" in describe_action(direct_text, resolver).plsql_code


def test_update_item_without_field_mapping_is_blocked(resolver: FieldResolver) -> None:
    desc = describe_action(ActionNode("SPUpdateItemWithKeyAdapter"), resolver)
    assert any("mapowania pól" in reason for reason in desc.blocking_reasons)
    assert "RAISE_APPLICATION_ERROR(-20090" in desc.plsql_code


def test_path_b_run_if_wraps_children(resolver: FieldResolver) -> None:
    node = _run_if(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="Tak" />'), HISTORY_CHILD)
    code = build_path_b_code([node], resolver)
    assert "IF :STATUS = 'Tak' THEN" in code
    assert "END IF;" in code


def _write_status(enabled: bool = True) -> ActionNode:
    return ActionNode(
        "SPSetFieldWithKeyAdapter",
        enabled=enabled,
        params={"LookupField": "Status", "LookupFieldValue": "Gotowy"},
    )


def _read_status() -> ActionNode:
    return ActionNode(
        "NWBuildStringAdapter",
        params={"Input": "{ItemProperty:Status}"},
        param_elements={"Output": ET.Element("Variable", Name="Result", Type="Text")},
    )


def _status_workflow_spec(actions: list[ActionNode]) -> dict:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Status", "Status", "Text")])
    target = ListReference("Target", TARGET_ID, False, [FieldRef("Status", "Status", "Text")])
    workflow = WorkflowModel("Test", "", [source, target], actions, Path("t.nwf"), "List")
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    return build_workflow_data(workflow, resolver)["apex_workflow_spec"]


@pytest.mark.parametrize("usage", ["build_string", "condition", "history", "email", "variable"])
def test_reading_current_field_after_write_blocks_both_paths(usage: str) -> None:
    if usage == "build_string":
        read = _read_status()
    elif usage == "condition":
        read = _run_if(_condition(
            "Equal",
            '<ListLookup LookupType="ThisItemLookup"><Field Name="Status" Type="Text" /></ListLookup>',
            '<PrimitiveValue Value="Gotowy" />',
        ), HISTORY_CHILD)
    elif usage == "history":
        read = ActionNode("NWWriteToHistoryListAdapter", params={"Message": "{ItemProperty:Status}"})
    elif usage == "email":
        read = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWSendMessageAdapter</Type><Enabled>true</Enabled>
          <Message><Subject>{ItemProperty:Status}</Subject><Body>Body</Body></Message></NWActionConfig>"""))
    else:
        read = _set_variable(
            '<ListLookup LookupType="ThisItemLookup"><Field Name="Status" Type="Text" /></ListLookup>'
        )
    spec = _status_workflow_spec([_write_status(), read])

    assert spec["path_a_status"] == spec["path_b_status"] == "Zablokowana"
    assert any("Status" in reason and "odśwież" in reason for reason in spec["path_a_blocking_reasons"])
    assert spec["standard_activities"][1]["node_id"] == "migration_guard"
    assert "RAISE_APPLICATION_ERROR(-20090" in spec["path_b"]["plsql_code"]
    assert "update_list_item" not in spec["path_b"]["plsql_code"]


def test_read_before_write_does_not_block_current_field() -> None:
    spec = _status_workflow_spec([_read_status(), _write_status()])
    assert spec["path_a_status"] == spec["path_b_status"] == "Wymaga weryfikacji"


def test_reading_other_field_after_write_does_not_block() -> None:
    read = _read_status()
    read.params["Input"] = "{ItemProperty:Title}"
    spec = _status_workflow_spec([_write_status(), read])
    assert spec["path_a_status"] == spec["path_b_status"] == "Wymaga weryfikacji"


def test_disabled_write_does_not_block_current_field_read() -> None:
    spec = _status_workflow_spec([_write_status(enabled=False), _read_status()])
    assert spec["path_a_status"] == spec["path_b_status"] == "Wymaga weryfikacji"


def test_other_list_write_does_not_dirty_same_named_source_field() -> None:
    other_list_update = ActionNode(
        "SPUpdateItemWithKeyAdapter",
        params={"ListId": TARGET_ID, "ThisItem": "false", "LookupField": "ID"},
        param_elements={"LookupFieldValue": ET.Element("Variable", Name="RefId", Type="Number")},
        field_refs=[FieldRef("Status", "Status", "Text")],
    )
    spec = _status_workflow_spec([other_list_update, _read_status()])
    assert spec["path_a_status"] == spec["path_b_status"] == "Wymaga weryfikacji"


def test_keyed_update_to_source_list_can_modify_current_item() -> None:
    source_list_update = ActionNode(
        "SPUpdateItemWithKeyAdapter",
        params={"ListId": SOURCE_ID, "ThisItem": "false", "LookupField": "ID"},
        param_elements={"LookupFieldValue": ET.Element("Variable", Name="RefId", Type="Number")},
        field_refs=[FieldRef("Status", "Status", "Text")],
    )
    spec = _status_workflow_spec([source_list_update, _read_status()])
    assert any("Status" in reason and "odśwież" in reason for reason in spec["path_b_blocking_reasons"])


def test_cross_list_read_does_not_use_same_named_cached_source_field() -> None:
    cross_list_read = _set_variable(f"""<ListLookup LookupType="CrossItemLookup">
      <Lookup LookupType="ThisItemLookup"><Field Name="ID" Type="Counter" /></Lookup>
      <ListId>{TARGET_ID}</ListId><Field Name="Status" Type="Text" />
      <CompareField Name="ID" Type="Counter" />
    </ListLookup>""")
    spec = _status_workflow_spec([_write_status(), cross_list_read])
    assert spec["path_a_status"] == spec["path_b_status"] == "Wymaga weryfikacji"


def test_conditional_write_followed_by_read_is_blocked() -> None:
    condition = ET.fromstring(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="Tak" />'))
    conditional = ActionNode("NWRunIf2Adapter", condition_el=condition, children=[_write_status()])
    spec = _status_workflow_spec([conditional, _read_status()])
    assert any("Status" in reason and "odśwież" in reason for reason in spec["path_b_blocking_reasons"])


def test_mutually_exclusive_branches_do_not_imply_read_after_write() -> None:
    condition = ET.fromstring(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="Tak" />'))
    conditional = ActionNode("WFIfElseAdapter", condition_el=condition, children=[
        ActionNode("WFIfElseBranchAdapter", branch_label="Tak", children=[_write_status()]),
        ActionNode("WFIfElseBranchAdapter", branch_label="Nie", children=[_read_status()]),
    ])
    spec = _status_workflow_spec([conditional])
    assert spec["path_a_status"] == spec["path_b_status"] == "Wymaga weryfikacji"


def test_read_after_either_conditional_branch_sees_possible_write() -> None:
    condition = ET.fromstring(_condition("Equal", VAR_LEFT, '<PrimitiveValue Value="Tak" />'))
    conditional = ActionNode("WFIfElseAdapter", condition_el=condition, children=[
        ActionNode("WFIfElseBranchAdapter", branch_label="Tak", children=[_write_status()]),
        ActionNode("WFIfElseBranchAdapter", branch_label="Nie", children=[]),
    ])
    spec = _status_workflow_spec([conditional, _read_status()])
    assert any("Status" in reason and "odśwież" in reason for reason in spec["path_b_blocking_reasons"])


def test_next_iteration_can_read_field_written_in_previous_iteration() -> None:
    loop = ActionNode("NWForEachLoopAdapter", children=[_read_status(), _write_status()])
    spec = _status_workflow_spec([loop])
    assert any("Status" in reason and "odśwież" in reason for reason in spec["path_b_blocking_reasons"])


def test_parallel_branch_can_read_field_written_by_other_branch() -> None:
    parallel = ActionNode("WFParallelAdapter", children=[
        ActionNode("WFSequenceAdapter", children=[_read_status()]),
        ActionNode("WFSequenceAdapter", children=[_write_status()]),
    ])
    spec = _status_workflow_spec([parallel])
    assert any("Status" in reason and "odśwież" in reason for reason in spec["path_b_blocking_reasons"])
