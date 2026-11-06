from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from tools.nwf_report.html_builder import _generate_html
from tools.nwf_report.metadata_loader import FieldResolver
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference, WorkflowModel, _parse_action
from tools.nwf_report.report_builder import _build_mermaid_with_steps, build_dispatcher_package, build_report, build_workflow_data


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
        workflow_type="List",
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
    assert "Activity Properties > Code > PL/SQL Code" == activity["ui_location"]
    assert ":STATUS := :SP_STATUS_X0020_POLA;" in activity["plsql_code"]
    assert any(var["static_id"] == "SP_STATUS_X0020_POLA" for var in spec["variables"])
    parse_code = spec["standard_activities"][3]["plsql_code"]
    assert ":SP_STATUS_X0020_POLA := apex_json.get_varchar2(p_path => 'data.Status_x0020_Pola');" in parse_code
    assert "apex_workflow.set_variable" not in activity["plsql_code"]
    assert any(var["static_id"] == "STATUS" for var in spec["variables"])
    assert steps[0].node_id == activity["node_id"]


def test_collection_variables_and_loop_transitions() -> None:
    loop = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWForEachLoopAdapter</Type><Enabled>true</Enabled><TLabel>Loop</TLabel><Parameters>
        <Parameter Name="Target"><Variable Name="Items" Type="ArrayList" /></Parameter>
        <Parameter Name="Value"><Variable Name="Item" Type="Text" /></Parameter>
        <Parameter Name="Index"><Variable Name="Index" Type="Number" /></Parameter>
        <Parameter Name="Break"><PrimitiveValue Value="false" /><Variable Name="" Type="Boolean" /></Parameter>
      </Parameters><ChildActivities><NWActionConfig>
        <Type>NWWriteToHistoryListAdapter</Type><Enabled>true</Enabled><TLabel>Body</TLabel>
      </NWActionConfig></ChildActivities></NWActionConfig>"""))
    after = ActionNode("NWWriteToHistoryListAdapter", t_label="After")
    wf, resolver = _workflow([loop, after])

    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    activities = {activity["title"]: activity for activity in spec["activities"]}
    variables = {variable["static_id"]: variable["data_type"] for variable in spec["variables"]}

    assert variables["ITEMS"] == "CLOB"
    assert variables["ITEM"] == "VARCHAR2"
    assert variables["INDEX"] == "NUMBER"
    assert any(edge["target_node_id"] == activities["Loop"]["node_id"] for edge in activities["Body"]["transitions"])
    assert any(
        edge["condition"] == "Po zakończeniu pętli" and edge["target_node_id"] == activities["After"]["node_id"]
        for edge in activities["Loop"]["transitions"]
    )


def test_run_if_sequences_true_branch_and_bypasses_it_on_false() -> None:
    first = ActionNode("NWWriteToHistoryListAdapter", t_label="First")
    second = ActionNode("NWWriteToHistoryListAdapter", t_label="Second")
    branch = ActionNode("WFSequenceAdapter", children=[first, second])
    run_if = ActionNode("NWRunIf2Adapter", t_label="Condition", children=[branch])
    after = ActionNode("NWWriteToHistoryListAdapter", t_label="After")
    wf, resolver = _workflow([run_if, after])

    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    activities = {activity["title"]: activity for activity in spec["activities"]}
    transitions = activities["Condition"]["transitions"]
    assert any(edge["condition"] == "True" and edge["target_node_id"] == activities["First"]["node_id"] for edge in transitions)
    assert any(edge["condition"] == "False" and edge["target_node_id"] == activities["After"]["node_id"] for edge in transitions)
    assert any(edge["target_node_id"] == activities["Second"]["node_id"] for edge in activities["First"]["transitions"])
    assert any(edge["target_node_id"] == activities["After"]["node_id"] for edge in activities["Second"]["transitions"])


def test_conditional_at_end_of_loop_body_returns_to_loop_on_both_branches() -> None:
    loop = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWForEachLoopAdapter</Type><Enabled>true</Enabled>
      <TLabel>Loop</TLabel><Parameters>
        <Parameter Name="Target"><Variable Name="Items" Type="ArrayList" /></Parameter>
        <Parameter Name="Value"><Variable Name="Item" Type="Text" /></Parameter>
        <Parameter Name="Break"><PrimitiveValue Value="false" /><Variable Name="" /></Parameter>
      </Parameters><ChildActivities><NWActionConfig>
        <Type>NWRunIf2Adapter</Type><Enabled>true</Enabled><TLabel>Condition</TLabel>
        <ChildActivities><NWActionConfig>
          <Type>NWWriteToHistoryListAdapter</Type><Enabled>true</Enabled><TLabel>Body</TLabel>
        </NWActionConfig></ChildActivities>
      </NWActionConfig></ChildActivities></NWActionConfig>"""))
    wf, resolver = _workflow([loop, ActionNode("NWWriteToHistoryListAdapter", t_label="After")])
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    activities = {activity["title"]: activity for activity in spec["activities"]}

    assert any(
        edge["condition"] == "False" and edge["target_node_id"] == activities["Loop"]["node_id"]
        for edge in activities["Condition"]["transitions"]
    )
    assert any(edge["target_node_id"] == activities["Loop"]["node_id"] for edge in activities["Body"]["transitions"])
    assert not any(
        edge["condition"] == "False" and edge["target_node_id"] == "stop"
        for edge in activities["Condition"]["transitions"]
    )


def test_empty_run_if_has_true_and_false_exit_paths() -> None:
    wf, resolver = _workflow([ActionNode("NWRunIf2Adapter", t_label="Condition")])
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    condition = next(activity for activity in spec["activities"] if activity["title"] == "Condition")

    assert {(edge["condition"], edge["target_node_id"]) for edge in condition["transitions"]} == {
        ("True", "stop"), ("False", "stop")
    }


def test_if_else_empty_branch_at_end_reaches_workflow_end() -> None:
    empty = ActionNode("WFSequenceAdapter", branch_label="Nie")
    body = ActionNode("NWWriteToHistoryListAdapter", t_label="Body")
    populated = ActionNode("WFSequenceAdapter", branch_label="Tak", children=[body])
    condition = ActionNode("WFIfElseAdapter", t_label="Condition", children=[empty, populated])
    wf, resolver = _workflow([condition])
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    activities = {activity["title"]: activity for activity in spec["activities"]}

    assert any(
        edge["condition"] == "Nie" and edge["target_node_id"] == "stop"
        for edge in activities["Condition"]["transitions"]
    )
    assert any(
        edge["condition"] == "Tak" and edge["target_node_id"] == activities["Body"]["node_id"]
        for edge in activities["Condition"]["transitions"]
    )
    assert any(edge["target_node_id"] == "stop" for edge in activities["Body"]["transitions"])


def test_blocked_action_gates_both_paths_before_prior_write() -> None:
    update = ActionNode(
        "SPUpdateItemWithKeyAdapter",
        field_refs=[FieldRef("Status", "Status_x0020_Pola", "Choice")],
    )
    cancel = ActionNode("NWCancelWorkflowAdapter", params={"WorkflowName": "Other"})
    wf, resolver = _workflow([update, cancel])

    data = build_workflow_data(wf, resolver)
    spec = data["apex_workflow_spec"]
    start, guard = spec["standard_activities"][:2]
    assert start["transitions"][0]["target_node_id"] == guard["node_id"] == "migration_guard"
    assert "RAISE_APPLICATION_ERROR" in guard["plsql_code"]
    assert spec["path_a_status"] == "Zablokowana"
    assert spec["path_b_status"] == "Zablokowana"
    assert "RAISE_APPLICATION_ERROR" in spec["path_b"]["plsql_code"]
    assert "update_list_item" not in spec["path_b"]["plsql_code"]
    assert any(step["blocking_reasons"] for step in data["steps"] if step["short_type"] == "NWCancelWorkflowAdapter")
    assert "**Zablokowane (obie ścieżki)**" in build_report(wf, resolver)


def test_colliding_variable_static_ids_block_both_paths() -> None:
    def set_variable(name: str) -> ActionNode:
        return _parse_action(ET.fromstring(f"""<NWActionConfig>
          <Type>SPSetVariableAdapter</Type><Enabled>true</Enabled><Parameters>
            <Parameter Name="VariableName"><Variable Name="{name}" Type="Text" /></Parameter>
            <Parameter Name="Value"><PrimitiveValue Value="test" /></Parameter>
          </Parameters></NWActionConfig>"""))

    update = ActionNode(
        "SPUpdateItemWithKeyAdapter",
        field_refs=[FieldRef("Status", "Status_x0020_Pola", "Choice")],
    )
    wf, resolver = _workflow([update, set_variable("Result A"), set_variable("Result-A")])
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]

    assert spec["path_a_status"] == "Zablokowana"
    assert spec["path_b_status"] == "Zablokowana"
    assert any("RESULT_A" in reason for reason in spec["path_a_blocking_reasons"])
    assert spec["standard_activities"][1]["node_id"] == "migration_guard"
    assert "RAISE_APPLICATION_ERROR" in spec["path_b"]["plsql_code"]
    assert "update_list_item" not in spec["path_b"]["plsql_code"]


def test_sql_reference_template_is_visible_in_markdown_and_portal() -> None:
    action = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWRunSqlAdapter</Type><Enabled>true</Enabled>
      <Parameters><Parameter Name="Query"><PrimitiveValue Value="SELECT A FROM T" /></Parameter></Parameters>
      <ValueStorages><ValueStorageItems>
        <ValueStorage ValueIdentifier="A" VariableName="Results" VariableType="ArrayList" />
      </ValueStorageItems></ValueStorages></NWActionConfig>"""))
    wf, resolver = _workflow([action])

    data = build_workflow_data(wf, resolver)
    step = next(step for step in data["steps"] if step["short_type"] == "NWRunSqlAdapter")
    template = step["reference_template"]
    report = build_report(wf, resolver)
    html = _generate_html([data])

    assert "Szablon referencyjny" in report
    assert "DBMS_HS_PASSTHROUGH.GET_VALUE@" in report
    assert "DBMS_HS_PASSTHROUGH.GET_VALUE@" in html
    assert "step.reference_template" in html
    assert "RAISE_APPLICATION_ERROR" in template
    assert data["apex_workflow_spec"]["path_b_status"] == "Zablokowana"


def test_variable_colliding_with_standard_or_field_id_blocks_execution() -> None:
    for name in ("V_ITEM_ID", "P_PAYLOAD_BODY", "SP_STATUS_X0020_POLA"):
        action = _parse_action(ET.fromstring(f"""<NWActionConfig><Type>SPSetVariableAdapter</Type>
          <Enabled>true</Enabled><Parameters>
            <Parameter Name="VariableName"><Variable Name="{name}" Type="Text" /></Parameter>
            <Parameter Name="Value"><ListLookup LookupType="ThisItemLookup">
              <Field Name="Status_x0020_Pola" Type="Choice" />
            </ListLookup></Parameter>
          </Parameters></NWActionConfig>"""))
        wf, resolver = _workflow([action])
        spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]

        assert any(name in reason and "Kolizja" in reason for reason in spec["path_a_blocking_reasons"])
        assert spec["path_b_status"] == "Zablokowana"
        assert spec["standard_activities"][1]["node_id"] == "migration_guard"


def test_site_workflow_has_manual_start_and_no_list_dispatcher() -> None:
    wf = WorkflowModel(
        title="Site Example",
        description="",
        list_references=[],
        actions=[ActionNode("NWWriteToHistoryListAdapter", params={"Message": "hello"})],
        source_path=Path("site.nwf"),
        workflow_type="Site",
    )
    resolver = FieldResolver([])

    data = build_workflow_data(wf, resolver)
    spec = data["apex_workflow_spec"]
    assert data["workflow_type"] == "Site"
    assert "ręcznej migracji" in spec["migration_status"]
    assert [activity["node_id"] for activity in spec["standard_activities"]] == ["std_start", "migration_guard"]
    assert "RAISE_APPLICATION_ERROR" in spec["standard_activities"][1]["plsql_code"]
    assert "RAISE_APPLICATION_ERROR" in spec["path_b"]["plsql_code"]
    assert not spec["parameters"]
    assert "WHEN 'Site Example' THEN" not in build_dispatcher_package([data])
    report = build_report(wf, resolver)
    assert "Workflow witryny nie jest podłączany do dyspozytora" in report
    assert "harmonogram nie został potwierdzony" in report
    assert "GET_LIST_ITEM" not in report
    html = _generate_html([data])
    assert '"workflow_type": "Site"' in html
    assert '"migration_guard"' in html
    assert "Standardowy przebieg workflow listy w APEX" in html
    assert "Workflow witryny (<code>Site</code>) wymaga ręcznej migracji uruchomienia" in html


def test_missing_or_unknown_workflow_type_is_not_assumed_to_be_a_list() -> None:
    for workflow_type in ("", "Unrecognized"):
        wf, resolver = _workflow([ActionNode("NWWriteToHistoryListAdapter", params={"Message": "hello"})])
        wf.workflow_type = workflow_type

        data = build_workflow_data(wf, resolver)
        spec = data["apex_workflow_spec"]
        report = build_report(wf, resolver)
        assert spec["path_a_status"] == "Zablokowana"
        assert spec["path_b_status"] == "Zablokowana"
        assert [activity["node_id"] for activity in spec["standard_activities"]] == ["std_start", "migration_guard"]
        assert not spec["parameters"]
        assert "GET_LIST_ITEM" not in report
        assert "WHEN 'Test APEX Workflow' THEN" not in build_dispatcher_package([data])
        assert "ręcznej" in report


def test_loop_blocks_only_path_a_before_action_execution() -> None:
    loop = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWForEachLoopAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="Target"><Variable Name="Items" Type="ArrayList" /></Parameter>
        <Parameter Name="Value"><Variable Name="Item" Type="Text" /></Parameter>
        <Parameter Name="Break"><PrimitiveValue Value="false" /><Variable Name="" /></Parameter>
      </Parameters></NWActionConfig>"""))
    wf, resolver = _workflow([loop])
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]

    assert spec["path_a_status"] == "Zablokowana"
    assert spec["path_b_status"] == "Wymaga weryfikacji"
    assert spec["activities"][0]["node_id"] == "path_a_guard"
    assert "RAISE_APPLICATION_ERROR" in spec["activities"][0]["plsql_code"]
    assert spec["standard_activities"][-1]["transitions"][0]["target_node_id"] == "path_a_guard"
    assert "FOR l_nintex_index IN 0" in spec["path_b"]["plsql_code"]


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
    assert "LCDT.SHP_API.update_list_item" in activity["plsql_code"]
    assert "'Kwota' VALUE :SP_KWOTA" in activity["plsql_code"]
    assert "p_item_id     => :V_ITEM_ID" in activity["plsql_code"]
    assert "p_list_title  => :V_LIST_TITLE" in activity["plsql_code"]
    assert spec["shp_query"] == "$select=Kwota"
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
    wf = WorkflowModel("Lookup workflow", "", [source, target], [action], Path("lookup.nwf"), workflow_type="List")
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]
    code = spec["activities"][0]["plsql_code"]

    assert "LCDT.SHP_API.get_list_item(" in code
    assert "p_list_title => 'Lista referencyjna'" in code
    assert "p_item_id    => :SP_LOOKUPID_ID" in code
    assert "p_query      => '$select=Nazwa_x0020_Ref'" in code
    assert ":NAZWAREF := json_value(l_ref_json, '$.data.Nazwa_x0020_Ref')" in code
    assert spec["shp_query"] == "$select=LookupId/Id,LookupId/Title&$expand=LookupId"


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

    assert [param["static_id"] for param in spec["parameters"]] == ["P_PAYLOAD_BODY"]
    assert [activity["node_id"] for activity in spec["standard_activities"]] == [
        "std_start",
        "std_payload",
        "std_get_item",
        "std_parse",
    ]
    assert spec["path_b"]["activity_type"] == "Execute Code"
    assert ":STATUS := 'Gotowy';" in spec["path_b"]["plsql_code"]
    assert "Shared Components > Workflows" in report
    assert "Workflow Parameters" in report
    assert "GET_VARIABLE_VALUE" in report
    assert "Kroki standardowe (1–4)" in report
    assert "RAISE_APPLICATION_ERROR(-20010" in report
    assert "Ścieżka B" in report
    assert "WHEN 'Test APEX Workflow' THEN l_static_id := 'WF_TEST_APEX_WORKFLOW';" in report
    assert "sec-apex-workflows" in html
    assert "apex-path-b" in html
    assert "apex_workflow_spec" in html
