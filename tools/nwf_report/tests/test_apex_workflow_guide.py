from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from tools.nwf_report.html_builder import _generate_html
from tools.nwf_report.metadata_loader import FieldResolver
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference, WorkflowModel
from tools.nwf_report.report_builder import _build_mermaid_with_steps, build_report, build_workflow_data


SOURCE_ID = "{AAAAAAAA-1111-2222-3333-444444444444}"


def _workflow(actions: list[ActionNode]) -> tuple[WorkflowModel, FieldResolver]:
    source = ListReference(
        "Lista testowa",
        SOURCE_ID,
        True,
        [
            FieldRef("Status", "Status_x0020_Pola", "Choice"),
            FieldRef("Kwota", "Kwota", "Number"),
        ],
    )
    wf = WorkflowModel(
        title="Test APEX Workflow",
        description="",
        list_references=[source],
        actions=actions,
        source_path=Path("test.nwf"),
    )
    return wf, FieldResolver([source], source_list_id=SOURCE_ID)


def test_set_variable_maps_to_execute_code_and_uses_bind_variable() -> None:
    action = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.SPSetVariableAdapter",
        param_elements={
            "VariableName": ET.fromstring('<Variable Name="Status" Type="Text" />'),
            "Value": ET.fromstring(
                '<ListLookup LookupType="ThisItemLookup"><Field Name="Status_x0020_Pola" Type="Choice" /></ListLookup>'
            ),
        },
        t_label="Odczytaj status",
    )
    wf, resolver = _workflow([action])
    _, steps = _build_mermaid_with_steps(wf.actions, resolver)

    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    activity = spec["activities"][0]

    assert activity["activity_type"] == "Execute Code"
    assert "Activity Properties > PL/SQL Code" == activity["ui_location"]
    assert ":STATUS := json_value" in activity["plsql_code"]
    assert "apex_workflow.set_variable" not in activity["plsql_code"]
    assert any(var["static_id"] == "STATUS" for var in spec["variables"])
    assert steps[0].node_id == activity["node_id"]


def test_if_else_maps_to_switch_expression_and_branch_transitions() -> None:
    condition = ET.fromstring(
        """<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
            xsi:type="NWConditionConfig">
          <Params>
            <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
            <Param Name="left"><ListLookup LookupType="ThisItemLookup">
              <Field Name="Status_x0020_Pola" Type="Choice" />
            </ListLookup></Param>
            <Param Name="right"><PrimitiveValue Value="Aktywny" /></Param>
          </Params>
        </Condition>"""
    )
    yes_action = ActionNode(
        "Nintex.Workflow.Activities.Adapters.NWWriteToHistoryListAdapter",
        params={"Message": "Tak"},
        branch_label="Tak",
    )
    no_action = ActionNode(
        "Nintex.Workflow.Activities.Adapters.NWWriteToHistoryListAdapter",
        params={"Message": "Nie"},
        branch_label="Nie",
    )
    branch_yes = ActionNode(
        "Nintex.Workflow.Activities.Adapters.WFIfElseBranchAdapter",
        children=[yes_action],
        branch_label="Tak",
    )
    branch_no = ActionNode(
        "Nintex.Workflow.Activities.Adapters.WFIfElseBranchAdapter",
        children=[no_action],
        branch_label="Nie",
    )
    switch = ActionNode(
        "Nintex.Workflow.Activities.Adapters.WFIfElseAdapter",
        children=[branch_no, branch_yes],
        condition_el=condition,
        l_label="Nie",
        r_label="Tak",
        t_label="Status aktywny?",
    )
    wf, resolver = _workflow([switch])
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]

    switch_activity = next(activity for activity in spec["activities"] if activity["activity_type"] == "Switch")
    assert switch_activity["plsql_code"] == ":SP_STATUS_X0020_POLA = 'Aktywny'"
    assert {transition["condition"] for transition in switch_activity["transitions"]} == {"Nie", "Tak"}
    assert all(transition["target_node_id"] for transition in switch_activity["transitions"])
    assert spec["activities"][-1]["activity_type"] == "Workflow End"


def test_sharepoint_update_maps_fields_to_shp_api_execute_code() -> None:
    action = ActionNode(
        "Nintex.Workflow.Activities.Adapters.SPUpdateItemWithKeyAdapter",
        field_refs=[FieldRef("Kwota", "Kwota", "Number")],
        t_label="Zapisz kwotę",
    )
    wf, resolver = _workflow([action])
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    activity = spec["activities"][0]

    assert activity["activity_type"] == "Execute Code"
    assert "shp_api.update_list_item" in activity["plsql_code"]
    assert "'Kwota' VALUE :SP_KWOTA" in activity["plsql_code"]
    assert "P_ITEM_ID" in activity["plsql_code"]
    assert any(variable["field_binding"] == "Kwota" for variable in spec["variables"])


def test_delay_maps_to_native_wait_activity() -> None:
    action = ActionNode(
        "Nintex.Workflow.Activities.Adapters.NWDelayForAdapter",
        params={"Days": "1", "Hours": "2", "Minutes": "5"},
    )
    wf, resolver = _workflow([action])
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]

    assert spec["activities"][0]["activity_type"] == "Wait"
    assert "1565 minut" in spec["activities"][0]["config_notes"][0]
    assert not spec["activities"][0]["plsql_code"]


def test_cross_list_lookup_reads_related_item_from_target_list() -> None:
    target_id = "{BBBBBBBB-1111-2222-3333-444444444444}"
    source = ListReference("Lista źródłowa", SOURCE_ID, True, [])
    target = ListReference(
        "Lista referencyjna",
        target_id,
        False,
        [FieldRef("Nazwa", "Nazwa_x0020_Ref", "Text")],
    )
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    action = ActionNode(
        "Nintex.Workflow.Activities.Adapters.SPSetVariableAdapter",
        param_elements={
            "VariableName": ET.fromstring('<Variable Name="NazwaRef" Type="Text" />'),
            "Value": ET.fromstring(
                f"""<ListLookup LookupType="CrossItemLookup">
                  <Lookup LookupType="ThisItemLookup">
                    <ListId>{SOURCE_ID}</ListId><Field Name="LookupId" Type="Lookup" />
                  </Lookup>
                  <ListId>{target_id}</ListId><Field Name="Nazwa_x0020_Ref" Type="Text" />
                  <CompareField Name="ID" Type="Counter" />
                </ListLookup>"""
            ),
        },
    )
    wf = WorkflowModel("Lookup workflow", "", [source, target], [action], Path("lookup.nwf"))
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    code = spec["activities"][0]["plsql_code"]

    assert "p_list_title => 'Lista źródłowa'" in code
    assert "p_list_title => 'Lista referencyjna'" in code
    assert "l_ref_id := json_value(l_item_json, '$.data.LookupId' RETURNING NUMBER)" in code
    assert ":NAZWAREF := json_value(l_ref_json, '$.data.Nazwa_x0020_Ref')" in code


def test_parameters_markdown_and_html_include_apex_workflow_guide() -> None:
    action = ActionNode(
        "Nintex.Workflow.Activities.Adapters.SPSetVariableAdapter",
        param_elements={
            "VariableName": ET.fromstring('<Variable Name="Status" Type="Text" />'),
            "Value": ET.fromstring('<PrimitiveValue Value="Gotowy" />'),
        },
    )
    wf, resolver = _workflow([action])

    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    report = build_report(wf, resolver)
    html = _generate_html([build_workflow_data(wf, resolver)])

    assert [param["static_id"] for param in spec["parameters"]] == [
        "P_ITEM_ID",
        "P_SITE_URL",
        "P_LIST_TITLE",
        "P_INITIATOR",
        "P_PAYLOAD",
    ]
    assert "Shared Components > Workflows" in report
    assert "Workflow Parameters" in report
    assert "GET_VARIABLE_VALUE" in report
    assert "sec-apex-workflows" in html
    assert "apex_workflow_spec" in html
