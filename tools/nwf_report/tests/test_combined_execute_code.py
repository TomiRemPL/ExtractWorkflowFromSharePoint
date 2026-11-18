from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tools.nwf_report.action_catalog import _field_json_pair, describe_action
from tools.nwf_report.apex_workflow_guide import _source_field_spec
from tools.nwf_report.combined_execute_code import _field_parse, _rewrite_binds, _safe_number
from tools.nwf_report.metadata_loader import ColumnInfo, FieldResolver, ListInfo, SiteMetadata
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference, WorkflowModel, _parse_action
from tools.nwf_report.report_builder import build_workflow_data


SOURCE_ID = "{AAAAAAAA-1111-2222-3333-444444444444}"


def _resolver(*lists: ListReference) -> FieldResolver:
    metadata = SiteMetadata()
    for ref in lists:
        columns = {
            field.internal_name.lower(): ColumnInfo(
                field.name, field.internal_name, field.field_type, entity_property_name=field.internal_name,
            )
            for field in ref.fields
        }
        info = ListInfo(ref.list_name, ref.list_id, columns)
        metadata.lists_by_id[ref.list_id.strip("{}").lower()] = info
        metadata.lists_by_title[ref.list_name.lower()] = info
    source_id = next((ref.list_id for ref in lists if ref.is_source_list), "")
    return FieldResolver(list(lists), metadata, source_list_id=source_id)


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
    workflow = WorkflowModel("Test", "", [source], actions, Path("test.nwf"), "List")
    return workflow, _resolver(source)


def _declarations(*variables: dict[str, str]) -> ActionNode:
    action = ET.Element("NWActionConfig")
    ET.SubElement(action, "Type").text = "NWWorkflowVariablesAdapter"
    ET.SubElement(action, "Enabled").text = "true"
    declarations = ET.SubElement(action, "WorkflowVariables")
    for variable in variables:
        ET.SubElement(declarations, "Variable", {
            "Type": "Text", "DefaultValue": "", "Initiate": "false", "Direction": "None", **variable
        })
    return _parse_action(action)


def _set_variable(name: str, value: str, nintex_type: str = "Text") -> ActionNode:
    return ActionNode(
        "SPSetVariableAdapter",
        param_elements={
            "VariableName": ET.Element("Variable", {"Name": name, "Type": nintex_type}),
            "Value": ET.Element("PrimitiveValue", {"Value": value}),
        },
    )


def _combined(actions: list[ActionNode]) -> tuple[dict, str]:
    workflow, resolver = _workflow(actions)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    return spec, spec["path_b_combined"]["plsql_code"]


def _assert_guarded(spec: dict, code: str) -> None:
    assert spec["path_b_combined_status"].startswith("Szablon")
    assert code.split("\nBEGIN\n", 1)[1].lstrip().startswith("RAISE_APPLICATION_ERROR(-20090")
    assert spec["path_b_combined_blocking_reasons"]
    assert any("-20090" in note for note in spec["path_b_combined"]["config_notes"])


def _assert_sql_clob_payload(code: str, api: str) -> None:
    declaration = code.index("l_fields_json CLOB;")
    select = code.index("SELECT json_object(")
    returning = code.index("RETURNING CLOB", select)
    into = code.index("INTO l_fields_json", returning)
    dual = code.index("FROM DUAL;", into)
    call = code.index(api, dual)
    assert declaration < select < returning < into < dual < call
    assert "p_fields_json => l_fields_json" in code[call:]
    assert "p_fields_json => json_object(" not in code.lower()


def test_combined_code_parses_fields_and_executes_nested_flow() -> None:
    declarations = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWWorkflowVariablesAdapter</Type><Enabled>true</Enabled>
      <WorkflowVariables><Variable Name="Decyzja" Type="Text" DefaultValue=""
        Initiate="false" Direction="None" /></WorkflowVariables>
    </NWActionConfig>"""))
    set_variable = ActionNode(
        "SPSetVariableAdapter",
        param_elements={
            "VariableName": ET.fromstring('<Variable Name="Decyzja" Type="Text" />'),
            "Value": ET.fromstring(
                '<ListLookup LookupType="ThisItemLookup"><Field Name="Status_x0020_Pola" Type="Choice" /></ListLookup>'
            ),
        },
    )
    condition = ET.fromstring("""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
      <Param Name="left"><Variable Name="Decyzja" Type="Text" /></Param>
      <Param Name="right"><PrimitiveValue Value="Tak" /></Param>
    </Params></Condition>""")
    update = ActionNode("SPUpdateItemWithKeyAdapter", field_refs=[FieldRef("Kwota", "Kwota", "Number")])
    branch = ActionNode(
        "WFIfElseAdapter",
        condition_el=condition,
        children=[
            ActionNode("WFSequenceAdapter", branch_label="Tak", children=[update]),
            ActionNode(
                "WFSequenceAdapter",
                branch_label="Nie",
                children=[ActionNode("NWWriteToHistoryListAdapter", params={"Message": "Inaczej"})],
            ),
        ],
    )
    workflow, resolver = _workflow([declarations, set_variable, branch])

    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    code = spec["path_b_combined"]["plsql_code"]

    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert ":V_SHP_ANSWER" in code
    assert "l_sp_status_x0020_pola" in code.lower()
    assert "l_wf_decyzja := l_sp_status_x0020_pola;" in code.lower()
    assert "IF l_wf_decyzja = 'Tak' THEN" in code
    assert "ELSE" in code
    _assert_sql_clob_payload(code, "LCDT.SHP_API.update_list_item")
    assert ":SP_STATUS_X0020_POLA" not in code
    assert ":DECYZJA" not in code
    assert "EXCEPTION" in code and "RAISE;" in code
    assert "apex_json.does_exist(p_path => 'success'" in code
    assert "apex_json.get_value_kind(p_path => 'success', p_values => l_json_values) <> apex_json.c_true" in code
    assert "apex_json.get_value_kind(p_path => 'data', p_values => l_json_values) <> apex_json.c_object" in code
    assert code.index("apex_json.parse(") < code.index("LCDT.SHP_API.update_list_item")
    assert "TO_CHAR(SQLCODE), DBMS_UTILITY.FORMAT_ERROR_BACKTRACE" in code
    assert "COMMIT;" not in code
    assert spec["path_b_combined"]["transitions"][0]["target_node_id"] == "stop"
    assert set(spec["path_b_combined_required_binds"]) == {
        "V_ITEM_ID", "V_LIST_TITLE", "V_SHP_ANSWER", "V_SITE_URL",
    }


def test_bind_rewriting_preserves_literals_identifiers_and_comments() -> None:
    source = (
        ":A := :AB; :AB := :UNKNOWN;\n"
        "-- :A and :AB\n"
        "/* :A */ :A := ':AB and ''quoted''';\n"
        "l_x := q'[text :A '' :AB]' || NQ'{:AB}';\n"
        'l_y := ":A";'
    )

    rewritten, remaining = _rewrite_binds(source, {"A": "l_a", "AB": "l_ab"})

    assert rewritten == (
        "l_a := l_ab; l_ab := :UNKNOWN;\n"
        "-- :A and :AB\n"
        "/* :A */ l_a := ':AB and ''quoted''';\n"
        "l_x := q'[text :A '' :AB]' || NQ'{:AB}';\n"
        'l_y := ":A";'
    )
    assert remaining == {"UNKNOWN"}


@pytest.mark.parametrize("source", ["'unclosed", "/* unclosed", "q'[unclosed'"])
def test_bind_rewriter_rejects_unterminated_sql(source: str) -> None:
    with pytest.raises(ValueError):
        _rewrite_binds(source, {})


def test_field_parse_checks_missing_null_and_typed_values() -> None:
    fields = [
        _source_field_spec("Amount", "Number"),
        _source_field_spec("Description", "Note"),
        _source_field_spec("When", "DateTime"),
        _source_field_spec("Person", "User"),
        _source_field_spec("Related", "Lookup"),
    ]
    local_names = {static_id: "l_" + static_id.lower() for field in fields for static_id, _, _ in field.variables}

    lines, reasons = _field_parse(fields, local_names)
    code = "\n".join(lines)

    assert not reasons
    assert "apex_json.does_exist(p_path => 'data.Amount'" in code
    assert "l_sp_amount := apex_json.get_number(p_path => 'data.Amount'" in code
    assert "l_sp_description := apex_json.get_clob(p_path => 'data.Description'" in code
    assert "AND apex_json.get_value_kind(p_path => 'data.Description', p_values => l_json_values) <> apex_json.c_null THEN" in code
    assert "ELSE\n        l_sp_description := NULL;\n    END IF;" in code
    assert "TO_TIMESTAMP_TZ(REPLACE(apex_json.get_varchar2(p_path => 'data.When'" in code
    assert "AND apex_json.get_value_kind(p_path => 'data.When', p_values => l_json_values) <> apex_json.c_null THEN" in code
    assert "apex_json.c_object, apex_json.c_null" in code
    assert "apex_json.does_exist(p_path => 'data.Person.EMail'" in code
    assert "l_sp_person_email := apex_json.get_varchar2(p_path => 'data.Person.EMail'" in code
    assert "l_sp_related_id := apex_json.get_number(p_path => 'data.Related.Id'" in code
    assert "AND apex_json.get_value_kind(p_path => 'data.Related.Id', p_values => l_json_values) <> apex_json.c_null THEN" in code
    assert "ELSE\n        l_sp_related_id := NULL;\n    END IF;" in code
    assert "IF l_sp_related_id IS NOT NULL AND (l_sp_related_id < 1 OR l_sp_related_id <> TRUNC(l_sp_related_id)) THEN" in code
    assert "GET_LIST_ITEM: niepoprawne ID pola Related" in code
    assert "IF l_sp_amount IS NOT NULL AND (l_sp_amount < 1" not in code
    assert "AND apex_json.get_value_kind(p_path => 'data.Amount', p_values => l_json_values) <> apex_json.c_null THEN" in code
    assert "ELSE\n        l_sp_amount := NULL;\n    END IF;" in code


@pytest.mark.parametrize(("operator", "comparison"), [("IsEmpty", "IS NULL"), ("NotIsEmpty", "IS NOT NULL")])
def test_lookup_emptiness_checks_id_without_requiring_display_value(operator: str, comparison: str) -> None:
    source = ListReference("List", SOURCE_ID, True, [FieldRef("Supplier", "Supplier", "Lookup")])
    condition = ET.fromstring(f"""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="{operator}" /></Param>
      <Param Name="left"><ListLookup LookupType="ThisItemLookup"><Field Name="Supplier" Type="Lookup" /></ListLookup></Param>
      <Param Name="right"><PrimitiveValue Value="" /></Param>
    </Params></Condition>""")
    action = ActionNode("NWRunIf2Adapter", condition_el=condition, children=[
        ActionNode("NWWriteToHistoryListAdapter", params={"Message": "Supplier check"}),
    ])
    workflow = WorkflowModel("Lookup check", "", [source], [action], Path("lookup.nwf"), "List")
    resolver = _resolver(source)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    code = spec["path_b_combined"]["plsql_code"]

    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert f"IF l_sp_supplier_id {comparison} THEN" in code
    assert "data.Supplier.Id" in code
    assert "brak skladowej data.Supplier.Id" not in code
    assert "ELSE\n        l_sp_supplier_id := NULL;\n    END IF;" in code
    assert "data.Supplier.Title" not in code
    assert "l_sp_supplier VARCHAR2" not in code
    assert f":SP_SUPPLIER {comparison}" in describe_action(action, resolver).plsql_code


def test_lookup_display_value_is_still_checked_when_used_in_a_comparison() -> None:
    source = ListReference("List", SOURCE_ID, True, [FieldRef("Supplier", "Supplier", "Lookup")])
    condition = ET.fromstring("""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
      <Param Name="left"><ListLookup LookupType="ThisItemLookup"><Field Name="Supplier" Type="Lookup" /></ListLookup></Param>
      <Param Name="right"><PrimitiveValue Value="Acme" /></Param>
    </Params></Condition>""")
    action = ActionNode("NWRunIf2Adapter", condition_el=condition, children=[
        ActionNode("NWWriteToHistoryListAdapter", params={"Message": "Supplier check"}),
    ])
    workflow = WorkflowModel("Lookup text", "", [source], [action], Path("lookup.nwf"), "List")
    spec = build_workflow_data(workflow, _resolver(source))["apex_workflow_spec"]
    code = spec["path_b_combined"]["plsql_code"]

    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "IF l_sp_supplier = 'Acme' THEN" in code
    assert "brak skladowej data.Supplier.Title" in code
    assert "data.Supplier.Id" not in code


def test_multivalue_fields_require_template() -> None:
    field = _source_field_spec("People", "UserMulti")
    _, reasons = _field_parse([field], {static_id: "l_" + static_id.lower() for static_id, _, _ in field.variables})
    assert any("wielowartościowe" in reason for reason in reasons)


def test_unsupported_field_type_produces_a_guarded_template() -> None:
    source = ListReference("List", SOURCE_ID, True, [FieldRef("Link", "Link", "URL")])
    actions = [
        _declarations({"Name": "LinkText"}),
        ActionNode("SPSetVariableAdapter", param_elements={
            "VariableName": ET.Element("Variable", {"Name": "LinkText", "Type": "Text"}),
            "Value": ET.fromstring(
                '<ListLookup LookupType="ThisItemLookup"><Field Name="Link" Type="URL" /></ListLookup>'
            ),
        }),
    ]
    workflow = WorkflowModel("Unsupported field", "", [source], actions, Path("field.nwf"), "List")
    resolver = FieldResolver([source], source_list_id=SOURCE_ID)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    _assert_guarded(spec, spec["path_b_combined"]["plsql_code"])
    assert any("typ" in reason.lower() and "Link" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_missing_source_field_type_is_not_assumed_to_be_text() -> None:
    spec, code = _combined([ActionNode(
        "NWWriteToHistoryListAdapter", params={"Message": "{ItemProperty:MissingField}"},
    )])
    _assert_guarded(spec, code)
    assert any("typ" in reason.lower() and "MissingField" in reason
               for reason in spec["path_b_combined_blocking_reasons"])


def test_explicit_nintex_field_type_can_supply_missing_metadata() -> None:
    source = ListReference("List", SOURCE_ID, True, [])
    actions = [
        _declarations({"Name": "Value"}),
        ActionNode("SPSetVariableAdapter", param_elements={
            "VariableName": ET.Element("Variable", {"Name": "Value", "Type": "Text"}),
            "Value": ET.fromstring(
                '<ListLookup LookupType="ThisItemLookup"><Field Name="KnownField" Type="Text" /></ListLookup>'
            ),
        }),
    ]
    workflow = WorkflowModel("Explicit type", "", [source], actions, Path("field.nwf"), "List")
    resolver = FieldResolver([source], source_list_id=SOURCE_ID)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"


def test_conflicting_default_and_explicit_field_type_requires_manual_mapping() -> None:
    source = ListReference("List", SOURCE_ID, True, [])
    actions = [
        _declarations({"Name": "Value"}),
        ActionNode("NWWriteToHistoryListAdapter", params={"Message": "{ItemProperty:KnownField}"}),
        ActionNode("SPSetVariableAdapter", param_elements={
            "VariableName": ET.Element("Variable", {"Name": "Value", "Type": "Text"}),
            "Value": ET.fromstring(
                '<ListLookup LookupType="ThisItemLookup"><Field Name="KnownField" Type="Lookup" /></ListLookup>'
            ),
        }),
    ]
    workflow = WorkflowModel("Conflict", "", [source], actions, Path("field.nwf"), "List")
    spec = build_workflow_data(workflow, _resolver(source))["apex_workflow_spec"]
    _assert_guarded(spec, spec["path_b_combined"]["plsql_code"])
    assert any("niespójny" in reason for reason in spec["path_b_combined_blocking_reasons"])


@pytest.mark.parametrize(
    ("field_type", "value"),
    [
        ("UserMulti", "someone"),
        ("MultiChoice", "selected"),
        ("", "value"),
        ("UnknownType", "value"),
        ("Number", "12.5"),
        ("Lookup", "12"),
        ("DateTime", "2026-01-01"),
        ("Note", "long text"),
    ],
)
def test_unsupported_or_mistyped_write_is_guarded(field_type: str, value: str) -> None:
    source = ListReference("List", SOURCE_ID, True, [FieldRef("Target", "Target", field_type)])
    action = ActionNode("SPSetFieldWithKeyAdapter", params={
        "LookupField": "Target", "LookupFieldType": field_type, "LookupFieldValue": value,
    })
    workflow = WorkflowModel("Write", "", [source], [action], Path("write.nwf"), "List")
    spec = build_workflow_data(workflow, _resolver(source))["apex_workflow_spec"]
    _assert_guarded(spec, spec["path_b_combined"]["plsql_code"])
    assert any("Target" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_number_write_from_number_variable_remains_supported() -> None:
    source = ListReference("List", SOURCE_ID, True, [FieldRef("Amount", "Amount", "Number")])
    actions = [
        _declarations({"Name": "AmountVar", "Type": "Number", "DefaultValue": "0"}),
        _set_variable("AmountVar", "7", "Number"),
        ActionNode("SPSetFieldWithKeyAdapter", params={"LookupField": "Amount", "LookupFieldType": "Number"},
                   param_elements={"LookupFieldValue": ET.Element("Variable", {"Name": "AmountVar", "Type": "Number"})}),
    ]
    workflow = WorkflowModel("Numeric write", "", [source], actions, Path("write.nwf"), "List")
    spec = build_workflow_data(workflow, _resolver(source))["apex_workflow_spec"]
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    code = spec["path_b_combined"]["plsql_code"]
    assert "'Amount' VALUE l_wf_amountvar" in code
    _assert_sql_clob_payload(code, "LCDT.SHP_API.update_list_item")
    legacy_code = describe_action(actions[-1], FieldResolver([source], source_list_id=SOURCE_ID)).plsql_code
    assert "p_fields_json => json_object(" in legacy_code
    assert "RETURNING CLOB" not in legacy_code


def test_target_field_type_uses_the_target_list_not_the_source_list() -> None:
    target_id = "{BBBBBBBB-1111-2222-3333-444444444444}"
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Shared", "Shared", "Text")])
    target = ListReference("Target", target_id, False, [FieldRef("Shared", "Shared", "Lookup")])
    update = _parse_action(ET.fromstring(f"""<NWActionConfig><Type>SPUpdateItemWithKeyAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="ListId"><PrimitiveValue Value="{target_id}" /></Parameter>
        <Parameter Name="LookupField"><PrimitiveValue Value="ID" /></Parameter>
        <Parameter Name="LookupFieldValue"><PrimitiveValue Value="1" /></Parameter>
      </Parameters>
      <FieldReferences>
        <FieldReference Name="Shared" Value="Shared" Type="Text"><Variable Name="RelatedId" Type="SPItemKey" /></FieldReference>
      </FieldReferences>
    </NWActionConfig>"""))
    actions = [_declarations({"Name": "RelatedId", "Type": "SPItemKey", "DefaultValue": "1"}), update]
    workflow = WorkflowModel("List context", "", [source, target], actions, Path("write.nwf"), "List")
    spec = build_workflow_data(workflow, _resolver(source, target))["apex_workflow_spec"]
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "'SharedId' VALUE l_wf_relatedid" in spec["path_b_combined"]["plsql_code"]


@pytest.mark.parametrize(
    ("field_type", "expected"),
    [
        ("Text", "'O''Brien' VALUE l_value"),
        ("Lookup", "'O''BrienId' VALUE l_value"),
        ("User", "'O''BrienId' VALUE LCDT.SHP_API.ensure_user_id(:V_SITE_URL, l_value)"),
    ],
)
def test_field_json_keys_are_sql_quoted(field_type: str, expected: str) -> None:
    assert _field_json_pair("O'Brien", "l_value", field_type) == expected


def test_create_item_payload_returns_clob_in_combined_variant_only() -> None:
    create = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWCreateSiteSpecificItemAdapter</Type><Enabled>true</Enabled><BLabel>Lista testowa</BLabel>
      <FieldReferences>
        <FieldReference Name="Status" Value="Status_x0020_Pola" Type="Choice"><PrimitiveValue Value="Nowy" /></FieldReference>
      </FieldReferences>
    </NWActionConfig>"""))
    spec, code = _combined([create])
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    _assert_sql_clob_payload(code, "LCDT.SHP_API.add_list_item")
    _, resolver = _workflow([create])
    legacy_code = describe_action(create, resolver).plsql_code
    assert "p_fields_json => json_object(" in legacy_code
    assert "RETURNING CLOB" not in legacy_code


def test_repeated_combined_writes_each_construct_their_own_clob_payload() -> None:
    source = ListReference("List", SOURCE_ID, True, [FieldRef("First", "First", "Text"), FieldRef("Second", "Second", "Text")])
    actions = [
        ActionNode("SPSetFieldWithKeyAdapter", params={"LookupField": name, "LookupFieldType": "Text", "LookupFieldValue": value})
        for name, value in (("First", "A"), ("Second", "B"))
    ]
    workflow = WorkflowModel("Repeated writes", "", [source], actions, Path("write.nwf"), "List")
    spec = build_workflow_data(workflow, _resolver(source))["apex_workflow_spec"]
    code = spec["path_b_combined"]["plsql_code"]
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert code.count("l_fields_json CLOB;") == 2
    assert code.count("SELECT json_object(") == 2
    assert code.count("RETURNING CLOB") == 2
    assert code.count("INTO l_fields_json") == 2
    assert code.count("FROM DUAL;") == 2
    assert code.count("p_fields_json => l_fields_json") == 2


def test_created_item_id_is_validated_before_the_flow_continues() -> None:
    create = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWCreateSiteSpecificItemAdapter</Type><Enabled>true</Enabled><BLabel>Lista testowa</BLabel>
      <Parameters><Parameter Name="Output"><Variable Name="NewId" Type="SPItemKey" /></Parameter></Parameters>
      <FieldReferences>
        <FieldReference Name="Status" Value="Status_x0020_Pola" Type="Choice"><PrimitiveValue Value="Nowy" /></FieldReference>
      </FieldReferences>
    </NWActionConfig>"""))
    spec, code = _combined([_declarations({"Name": "NewId", "Type": "SPItemKey", "DefaultValue": "0"}), create])
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "json_value(l_resp, '$.item_id' RETURNING NUMBER ERROR ON ERROR)" in code
    assert "IF l_wf_newid IS NULL OR l_wf_newid < 1 OR l_wf_newid <> TRUNC(l_wf_newid)" in code


TARGET_ID = "{BBBBBBBB-1111-2222-3333-444444444444}"


def _cross_workflow(actions: list[ActionNode], *, source_lookup_list: str = TARGET_ID) -> tuple[WorkflowModel, FieldResolver]:
    source = ListReference("Source", SOURCE_ID, True, [FieldRef("Related", "Related", "Lookup")])
    target = ListReference("Target", TARGET_ID, False, [
        FieldRef("Contract", "Contract", "Lookup"), FieldRef("Status", "Status", "Choice"),
    ])
    source_info = ListInfo("Source", SOURCE_ID, {
        "related": ColumnInfo("Related", "Related", "Lookup", entity_property_name="Related", lookup_field="Title", lookup_list=source_lookup_list),
    })
    target_info = ListInfo("Target", TARGET_ID, {
        "contract": ColumnInfo("Contract", "Contract", "Lookup", entity_property_name="ContractRef", lookup_field="Title"),
        "status": ColumnInfo("Status", "Status", "Choice", entity_property_name="Status"),
        "title": ColumnInfo("Title", "Title", "Text", entity_property_name="Title"),
    })
    metadata = SiteMetadata(
        lists_by_id={SOURCE_ID.strip("{}").lower(): source_info, TARGET_ID.strip("{}").lower(): target_info},
        lists_by_title={"source": source_info, "target": target_info},
    )
    return WorkflowModel("Cross read", "", [source, target], actions, Path("cross.nwf"), "List"), FieldResolver(
        [source, target], metadata, SOURCE_ID,
    )


def _cross_read(variable: str, variable_type: str, target_field: str, field_type: str) -> ActionNode:
    return ActionNode("SPSetVariableAdapter", param_elements={
        "VariableName": ET.Element("Variable", {"Name": variable, "Type": variable_type}),
        "Value": ET.fromstring(f"""<ListLookup LookupType="CrossItemLookup">
          <Lookup LookupType="ThisItemLookup"><ListId>{SOURCE_ID}</ListId><Field Name="Related" Type="Lookup" /></Lookup>
          <Coercion>LookupIdOnlyAsInteger</Coercion><ListId>{TARGET_ID}</ListId>
          <Field Name="{target_field}" Type="{field_type}" /><CompareField Name="ID" Type="Counter" />
        </ListLookup>"""),
    })


def test_cross_lookup_validates_response_and_reads_nullable_numeric_id() -> None:
    actions = [
        _declarations({"Name": "ContractId", "Type": "SPItemKey", "DefaultValue": "0"}),
        _cross_read("ContractId", "SPItemKey", "Contract", "Lookup"),
    ]
    workflow, resolver = _cross_workflow(actions)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    code = spec["path_b_combined"]["plsql_code"]

    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "IF l_sp_related_id IS NULL" in code
    assert code.index("IF l_sp_related_id IS NULL") < code.index("LCDT.SHP_API.get_list_item(")
    assert "p_query      => '$select=ContractRef/Id&$expand=ContractRef'" in code
    assert "l_ref_values.DELETE;" in code
    assert "apex_json.parse(p_values => l_ref_values, p_source => l_ref_json);" in code
    assert "apex_json.does_exist(p_path => 'success', p_values => l_ref_values)" in code
    assert "apex_json.does_exist(p_path => 'data', p_values => l_ref_values)" in code
    assert "apex_json.does_exist(p_path => 'data.ContractRef', p_values => l_ref_values)" in code
    assert "apex_json.does_exist(p_path => 'data.ContractRef.Id', p_values => l_ref_values)" in code
    assert "apex_json.c_number, apex_json.c_null" in code
    assert "l_wf_contractid := apex_json.get_number(p_path => 'data.ContractRef.Id', p_values => l_ref_values);" in code
    assert "l_wf_contractid := NULL;" in code


def test_cross_lookup_checks_target_text_and_reinitializes_each_response() -> None:
    actions = [
        _declarations({"Name": "One"}, {"Name": "Two"}),
        _cross_read("One", "Text", "Status", "Choice"),
        _cross_read("Two", "Text", "Status", "Choice"),
    ]
    workflow, resolver = _cross_workflow(actions)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    code = spec["path_b_combined"]["plsql_code"]

    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert code.count("l_ref_values.DELETE;") == 2
    assert "apex_json.c_varchar2, apex_json.c_null" in code
    assert "l_wf_one := apex_json.get_varchar2(p_path => 'data.Status', p_values => l_ref_values);" in code
    assert "l_wf_two := apex_json.get_varchar2(p_path => 'data.Status', p_values => l_ref_values);" in code


def test_cross_lookup_with_key_from_another_list_stays_guarded() -> None:
    actions = [
        _declarations({"Name": "ContractId", "Type": "SPItemKey", "DefaultValue": "0"}),
        _cross_read("ContractId", "SPItemKey", "Contract", "Lookup"),
    ]
    workflow, resolver = _cross_workflow(actions, source_lookup_list=SOURCE_ID)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    _assert_guarded(spec, spec["path_b_combined"]["plsql_code"])
    assert any("CrossItemLookup" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_cross_item_lookup_requires_response_validation_before_execution() -> None:
    read = ActionNode("SPSetVariableAdapter", param_elements={
        "VariableName": ET.Element("Variable", {"Name": "Result", "Type": "Text"}),
        "Value": ET.fromstring(f"""<ListLookup LookupType="CrossItemLookup">
          <Lookup LookupType="ThisItemLookup"><Field Name="ID" Type="Counter" /></Lookup>
          <ListId>{SOURCE_ID}</ListId><Field Name="Kwota" Type="Number" />
          <CompareField Name="ID" /><Coercion>AsString</Coercion>
        </ListLookup>"""),
    })
    spec, code = _combined([_declarations({"Name": "Result"}), read])
    _assert_guarded(spec, code)
    assert any("CrossItemLookup" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_numeric_literal_assignment_is_independent_of_session_nls() -> None:
    actions = [
        _declarations({"Name": "Amount", "Type": "Number", "DefaultValue": "0"}),
        _set_variable("Amount", "1.25", "Number"),
    ]
    spec, code = _combined(actions)
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "l_wf_amount := 1.25;" in code


@pytest.mark.parametrize("value", ["1,25", "not-a-number", "1e126"])
def test_invalid_numeric_literal_assignment_requires_manual_mapping(value: str) -> None:
    actions = [
        _declarations({"Name": "Amount", "Type": "Number", "DefaultValue": "0"}),
        _set_variable("Amount", value, "Number"),
    ]
    spec, code = _combined(actions)
    _assert_guarded(spec, code)
    assert any("Amount" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_numeric_assignment_from_text_variable_requires_manual_conversion() -> None:
    actions = [
        _declarations({"Name": "Amount", "Type": "Number", "DefaultValue": "0"}, {"Name": "Source"}),
        ActionNode("SPSetVariableAdapter", param_elements={
            "VariableName": ET.Element("Variable", {"Name": "Amount", "Type": "Number"}),
            "Value": ET.Element("Variable", {"Name": "Source", "Type": "Text"}),
        }),
    ]
    spec, code = _combined(actions)
    _assert_guarded(spec, code)
    assert any("Amount" in reason for reason in spec["path_b_combined_blocking_reasons"])


@pytest.mark.parametrize(("literal", "guarded"), [("1.25", False), ("1,25", True), ("1e126", True)])
def test_numeric_condition_handles_literal_without_nls_conversion(literal: str, guarded: bool) -> None:
    condition = ET.fromstring(f"""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="GreaterThan" /></Param>
      <Param Name="left"><Variable Name="Amount" Type="Number" /></Param>
      <Param Name="right"><PrimitiveValue Value="{literal}" /></Param>
    </Params></Condition>""")
    branch = ActionNode("NWRunIf2Adapter", condition_el=condition, children=[
        ActionNode("NWWriteToHistoryListAdapter", params={"Message": "Warunek spełniony"}),
    ])
    spec, code = _combined([_declarations({"Name": "Amount", "Type": "Number", "DefaultValue": "0"}), branch])
    if guarded:
        _assert_guarded(spec, code)
    else:
        assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
        assert "IF l_wf_amount > 1.25 THEN" in code


def test_numeric_condition_against_text_variable_requires_manual_conversion() -> None:
    condition = ET.fromstring("""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
      <Param Name="left"><Variable Name="Amount" Type="Number" /></Param>
      <Param Name="right"><Variable Name="TextValue" Type="Text" /></Param>
    </Params></Condition>""")
    branch = ActionNode("NWRunIf2Adapter", condition_el=condition)
    spec, code = _combined([
        _declarations({"Name": "Amount", "Type": "Number", "DefaultValue": "0"}, {"Name": "TextValue"}),
        branch,
    ])
    _assert_guarded(spec, code)
    assert any("warun" in reason.casefold() for reason in spec["path_b_combined_blocking_reasons"])


def test_inconsistent_variable_reference_type_is_guarded() -> None:
    condition = ET.fromstring("""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="GreaterThan" /></Param>
      <Param Name="left"><Variable Name="Amount" Type="Number" /></Param>
      <Param Name="right"><PrimitiveValue Value="1.25" /></Param>
    </Params></Condition>""")
    spec, code = _combined([
        _declarations({"Name": "Amount", "Type": "Text"}),
        _set_variable("Amount", "1.25", "Text"),
        ActionNode("NWRunIf2Adapter", condition_el=condition),
    ])
    _assert_guarded(spec, code)
    assert any("Amount" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_newlines_in_action_labels_do_not_become_executable_plsql() -> None:
    process = ActionNode("NWBusinessProcessAdapter", b_label="Etap\nRAISE_APPLICATION_ERROR(-20999, 'x');")
    spec, code = _combined([process])
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert not any(line.lstrip().startswith("RAISE_APPLICATION_ERROR(-20999") for line in code.splitlines())
    assert "-- Etap: Etap RAISE_APPLICATION_ERROR" in code


def test_local_initializers_use_original_defaults_and_types() -> None:
    actions = [
        _declarations(
            {"Name": "Amount", "Type": "Number", "DefaultValue": "12.5"},
            {"Name": "TextValue", "DefaultValue": "O'Brien"},
        ),
        _set_variable("Amount", "10", "Number"),
        _set_variable("TextValue", "after"),
    ]
    spec, code = _combined(actions)

    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "l_wf_amount NUMBER := 12.5;" in code
    assert "l_wf_textvalue VARCHAR2(32767) := 'O''Brien';" in code
    assert ":AMOUNT" not in code and ":TEXTVALUE" not in code


@pytest.mark.parametrize(
    ("declared", "used_type", "reason"),
    [
        ({"Name": "Value", "Initiate": "true"}, "Text", "wejścia lub wyjścia"),
        ({"Name": "Value", "DefaultValue": "oops", "Type": "Number"}, "Number", "liczbowa"),
        ({"Name": "Value", "DefaultValue": "2026-01-01", "Type": "DateTime"}, "DateTime", "konwersji"),
        ({"Name": "Value", "DefaultValue": "42", "Type": "Number"}, "Text", "typu"),
        ({"Name": "Value", "DefaultValue": "1e309", "Type": "Number"}, "Number", "liczbowa"),
        ({"Name": "Value", "DefaultValue": "1e-200", "Type": "Number"}, "Number", "liczbowa"),
        ({"Name": "Value", "Type": "UnrecognizedType"}, "UnrecognizedType", "typ"),
        ({"Name": "Value", "Type": "ArrayList"}, "ArrayList", "kolekcji"),
    ],
)
def test_uncertain_initialization_produces_a_guarded_template(
    declared: dict[str, str], used_type: str, reason: str
) -> None:
    spec, code = _combined([_declarations(declared), _set_variable("Value", "example", used_type)])

    _assert_guarded(spec, code)
    assert any(reason in item.lower() for item in spec["path_b_combined_blocking_reasons"])


def test_missing_initial_declaration_is_not_assumed_null() -> None:
    spec, code = _combined([_set_variable("Missing", "value")])
    _assert_guarded(spec, code)
    assert any("Brak deklaracji" in reason for reason in spec["path_b_combined_blocking_reasons"])


@pytest.mark.parametrize(
    ("value", "safe"),
    [
        ("1e-130", True), ("9.99e125", True), ("1e-131", False), ("1e126", False),
        ("12345678901234567890123456789012345678", True),
        ("123456789012345678901234567890123456789", False),
        ("0e99999", True), ("NaN", False),
    ],
)
def test_number_defaults_are_within_oracle_range_and_precision(value: str, safe: bool) -> None:
    assert _safe_number(value) is safe


def test_zero_default_is_canonicalized_even_with_extreme_exponent() -> None:
    spec, code = _combined([
        _declarations({"Name": "Amount", "Type": "Number", "DefaultValue": "0e99999"}),
        _set_variable("Amount", "10", "Number"),
    ])
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "l_wf_amount NUMBER := 0;" in code
    assert "0e99999" not in code


def test_sensitive_initial_default_is_never_embedded() -> None:
    synthetic_secret = "example-sensitive-default"
    spec, code = _combined([
        _declarations({"Name": "Password", "DefaultValue": synthetic_secret}),
        _set_variable("Password", "configured-value"),
    ])
    _assert_guarded(spec, code)
    assert synthetic_secret not in code
    assert any("poufną" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_email_initial_default_is_not_embedded_in_code() -> None:
    email = "example@example.invalid"
    spec, code = _combined([
        _declarations({"Name": "Recipient", "DefaultValue": email}),
        _set_variable("Recipient", "configured-value"),
    ])
    _assert_guarded(spec, code)
    assert email not in code


def test_history_does_not_log_a_sensitive_variable_without_manual_review() -> None:
    spec, code = _combined([
        _declarations({"Name": "Password"}),
        _set_variable("Password", "configured-value"),
        ActionNode("NWWriteToHistoryListAdapter", params={"Message": "{WorkflowVariable:Password}"}),
    ])
    _assert_guarded(spec, code)
    assert any("histori" in reason.lower() or "logowan" in reason.lower()
               for reason in spec["path_b_combined_blocking_reasons"])


def test_supported_foreach_loop_uses_local_collection_and_values() -> None:
    loop = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWForEachLoopAdapter</Type><Enabled>true</Enabled><Parameters>
        <Parameter Name="Target"><Variable Name="Items" Type="ArrayList" /></Parameter>
        <Parameter Name="Value"><Variable Name="Item" Type="Text" /></Parameter>
        <Parameter Name="Index"><Variable Name="Index" Type="Number" /></Parameter>
        <Parameter Name="Break"><PrimitiveValue Value="false" /><Variable Name="" Type="Boolean" /></Parameter>
      </Parameters><ChildActivities><NWActionConfig>
        <Type>NWWriteToHistoryListAdapter</Type><Enabled>true</Enabled><Parameters>
          <Parameter Name="Message"><PrimitiveValue Value="{WorkflowVariable:Item}" /></Parameter>
        </Parameters>
      </NWActionConfig></ChildActivities></NWActionConfig>"""))
    spec, code = _combined([
        _declarations(
            {"Name": "Items", "Type": "ArrayList", "DefaultValue": '["a","b"]'},
            {"Name": "Item"},
            {"Name": "Index", "Type": "Number"},
        ),
        loop,
    ])
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert """l_wf_items CLOB := '["a","b"]';""" in code
    assert "JSON_ARRAY_T.parse(l_wf_items)" in code
    assert "l_wf_index := l_nintex_index;" in code
    assert "l_wf_item :=" in code
    assert ":ITEMS" not in code and ":ITEM" not in code and ":INDEX" not in code


def test_colliding_field_identifiers_produce_a_guarded_template() -> None:
    source = ListReference("List", SOURCE_ID, True, [
        FieldRef("One", "Foo_Bar", "Text"),
        FieldRef("Two", "Foo__Bar", "Text"),
    ])
    actions = [_declarations({"Name": "One"}, {"Name": "Two"})] + [
        ActionNode("SPSetVariableAdapter", param_elements={
            "VariableName": ET.Element("Variable", {"Name": name, "Type": "Text"}),
            "Value": ET.fromstring(
                f'<ListLookup LookupType="ThisItemLookup"><Field Name="{field}" Type="Text" /></ListLookup>'
            ),
        })
        for name, field in (("One", "Foo_Bar"), ("Two", "Foo__Bar"))
    ]
    workflow = WorkflowModel("Collision", "", [source], actions, Path("collision.nwf"), "List")
    resolver = FieldResolver([source], source_list_id=SOURCE_ID)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    code = spec["path_b_combined"]["plsql_code"]
    _assert_guarded(spec, code)
    assert any("Kolizja Static ID" in reason for reason in spec["path_b_combined_blocking_reasons"])
def _parallel(*branches: list[ActionNode]) -> ActionNode:
    return ActionNode(
        "WFParallelAdapter",
        children=[ActionNode("WFSequenceAdapter", children=branch) for branch in branches],
    )


def test_independent_parallel_local_assignments_can_be_serialized() -> None:
    spec, code = _combined([
        _declarations({"Name": "First"}, {"Name": "Second"}),
        _parallel([_set_variable("First", "A")], [_set_variable("Second", "B")]),
    ])

    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert code.index("l_wf_first := 'A';") < code.index("l_wf_second := 'B';")


def _conditional_field_write(condition_field: str, target_field: str, value: str) -> ActionNode:
    condition = ET.fromstring(f"""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="IsEmpty" /></Param>
      <Param Name="left"><ListLookup LookupType="ThisItemLookup"><Field Name="{condition_field}" Type="Text" /></ListLookup></Param>
      <Param Name="right"><PrimitiveValue Value="" /></Param>
    </Params></Condition>""")
    write = ActionNode("SPSetFieldWithKeyAdapter", params={
        "LookupField": target_field, "LookupFieldType": "Text", "LookupFieldValue": value,
    })
    return ActionNode("NWRunIf2Adapter", condition_el=condition, children=[write])


def _parallel_write_spec(first: ActionNode, second: ActionNode) -> tuple[dict, str]:
    source = ListReference("List", SOURCE_ID, True, [
        FieldRef("First", "First", "Text"), FieldRef("Second", "Second", "Text"),
        FieldRef("Display", "Display", "Text"),
    ])
    workflow = WorkflowModel("Parallel writes", "", [source], [_parallel([first], [second])], Path("parallel.nwf"), "List")
    spec = build_workflow_data(workflow, _resolver(source))["apex_workflow_spec"]
    return spec, spec["path_b_combined"]["plsql_code"]


def test_independent_conditional_field_writes_can_be_serialized() -> None:
    spec, code = _parallel_write_spec(
        _conditional_field_write("First", "First", "RKU-{ItemProperty:ID}"),
        _conditional_field_write("Second", "Second", "{ItemProperty:Display}"),
    )
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "IF l_sp_first IS NULL THEN" in code
    assert "IF l_sp_second IS NULL THEN" in code
    assert code.count("LCDT.SHP_API.update_list_item(") == 2
    assert "'First' VALUE 'RKU-' || TO_CHAR(:V_ITEM_ID)" in code
    assert "'Second' VALUE l_sp_display" in code


@pytest.mark.parametrize(("second_condition", "second_target", "second_value"), [
    ("Second", "First", "B"),
    ("First", "Second", "B"),
    ("Second", "Second", "{ItemProperty:First}"),
])
def test_parallel_field_writes_with_conflicts_stay_guarded(
    second_condition: str, second_target: str, second_value: str,
) -> None:
    spec, code = _parallel_write_spec(
        _conditional_field_write("First", "First", "A"),
        _conditional_field_write(second_condition, second_target, second_value),
    )
    _assert_guarded(spec, code)
    assert any("Równoległe gałęzie" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_independent_parallel_cross_item_reads_can_be_serialized() -> None:
    actions = [
        _declarations({"Name": "ContractId", "Type": "SPItemKey", "DefaultValue": "0"}, {"Name": "Status"}),
        _parallel(
            [_cross_read("ContractId", "SPItemKey", "Contract", "Lookup")],
            [_cross_read("Status", "Text", "Status", "Choice")],
        ),
    ]
    workflow, resolver = _cross_workflow(actions)
    spec = build_workflow_data(workflow, resolver)["apex_workflow_spec"]
    code = spec["path_b_combined"]["plsql_code"]
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert code.count("l_ref_values.DELETE;") == 2
    assert "l_wf_contractid := apex_json.get_number" in code
    assert "l_wf_status := apex_json.get_varchar2" in code


def test_parallel_if_else_branch_containers_keep_their_children() -> None:
    parallel = ActionNode("WFParallelAdapter", children=[
        ActionNode("WFIfElseBranchAdapter", children=[_set_variable("First", "A")]),
        ActionNode("WFIfElseBranchAdapter", children=[_set_variable("Second", "B")]),
    ])
    spec, code = _combined([_declarations({"Name": "First"}, {"Name": "Second"}), parallel])
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "l_wf_first := 'A';" in code and "l_wf_second := 'B';" in code


@pytest.mark.parametrize(
    "branches",
    [
        [[_set_variable("First", "{WorkflowVariable:Second}")], [_set_variable("Second", "B")]],
        [[_set_variable("First", "A")], [_set_variable("First", "B")]],
        [[_set_variable("First", "A")], [ActionNode("NWWriteToHistoryListAdapter", params={"Message": "B"})]],
    ],
)
def test_dependent_or_effectful_parallel_branches_are_guarded(branches: list[list[ActionNode]]) -> None:
    spec, code = _combined([
        _declarations({"Name": "First"}, {"Name": "Second"}),
        _parallel(*branches),
    ])

    _assert_guarded(spec, code)
    assert any("Równoległe gałęzie" in reason for reason in spec["path_b_combined_blocking_reasons"])
    assert "-- Galaz rownolegla 1." in code and "-- Galaz rownolegla 2." in code


def test_unknown_nested_action_retains_flow_but_blocks_all_writes() -> None:
    condition = ET.fromstring("""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
      <Param Name="left"><Variable Name="Flag" Type="Text" /></Param>
      <Param Name="right"><PrimitiveValue Value="yes" /></Param>
    </Params></Condition>""")
    branch = ActionNode(
        "WFIfElseAdapter",
        condition_el=condition,
        children=[
            ActionNode("WFSequenceAdapter", branch_label="Tak", children=[
                ActionNode("UnknownExampleAdapter"),
                ActionNode("SPUpdateItemWithKeyAdapter", field_refs=[FieldRef("Kwota", "Kwota", "Number")]),
            ]),
            ActionNode("WFSequenceAdapter", branch_label="Nie", children=[
                ActionNode("NWWriteToHistoryListAdapter", params={"Message": "else branch"}),
            ]),
        ],
    )
    spec, code = _combined([_declarations({"Name": "Flag"}), branch])

    _assert_guarded(spec, code)
    assert "IF l_wf_flag = 'yes' THEN" in code
    assert "ELSE" in code and "else branch" in code
    assert "LCDT.SHP_API.update_list_item" in code
    assert any("UnknownExampleAdapter" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_unknown_container_preserves_children_in_guarded_template() -> None:
    container = ActionNode("UnknownContainerAdapter", children=[
        ActionNode("NWWriteToHistoryListAdapter", params={"Message": "nested action"}),
        _set_variable("ChildValue", "nested value"),
    ])
    spec, code = _combined([_declarations({"Name": "ChildValue"}), container])
    _assert_guarded(spec, code)
    assert "nested action" in code
    assert "l_wf_childvalue VARCHAR2(32767);" in code
    assert "l_wf_childvalue := 'nested value';" in code


def test_unexpected_children_of_a_known_leaf_are_guarded_and_visible() -> None:
    parent = ActionNode("NWWriteToHistoryListAdapter", params={"Message": "parent"}, children=[
        ActionNode("NWWriteToHistoryListAdapter", params={"Message": "unexpected child"}),
    ])
    spec, code = _combined([parent])
    _assert_guarded(spec, code)
    assert "parent" in code and "unexpected child" in code
    assert any("podrzędne" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_disabled_conditional_branch_does_not_execute_its_children() -> None:
    condition = ET.fromstring("""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
      <Param Name="left"><Variable Name="Flag" Type="Text" /></Param>
      <Param Name="right"><PrimitiveValue Value="yes" /></Param>
    </Params></Condition>""")
    branch = ActionNode("WFIfElseAdapter", condition_el=condition, children=[
        ActionNode("WFSequenceAdapter", enabled=False, branch_label="Tak", children=[
            ActionNode("NWWriteToHistoryListAdapter", params={"Message": "disabled child"}),
        ]),
        ActionNode("WFSequenceAdapter", branch_label="Nie", children=[
            ActionNode("NWWriteToHistoryListAdapter", params={"Message": "enabled child"}),
        ]),
    ])
    spec, code = _combined([_declarations({"Name": "Flag"}), branch])
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "disabled child" not in code
    assert "enabled child" in code


@pytest.mark.parametrize(
    "labels",
    [("Tak", "Nie", "Other"), ("Tak", "Tak"), ("Approve", "Reject")],
)
def test_ambiguous_conditional_branches_are_guarded_and_retained(labels: tuple[str, ...]) -> None:
    condition = ET.fromstring("""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
      <Param Name="left"><Variable Name="Flag" Type="Text" /></Param>
      <Param Name="right"><PrimitiveValue Value="yes" /></Param>
    </Params></Condition>""")
    branch = ActionNode("WFIfElseAdapter", condition_el=condition, children=[
        ActionNode("WFSequenceAdapter", branch_label=label, children=[
            ActionNode("NWWriteToHistoryListAdapter", params={"Message": f"branch {index}"}),
        ])
        for index, label in enumerate(labels)
    ])
    spec, code = _combined([_declarations({"Name": "Flag"}), branch])
    _assert_guarded(spec, code)
    assert any("gałęzi" in reason for reason in spec["path_b_combined_blocking_reasons"])
    assert all(f"branch {index}" in code for index in range(len(labels)))


def test_nested_parallel_template_retains_branch_boundaries() -> None:
    condition = ET.fromstring("""<Condition xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
      xsi:type="NWConditionConfig"><Params>
      <Param Name="operator"><PrimitiveValue Value="Equal" /></Param>
      <Param Name="left"><Variable Name="Flag" Type="Text" /></Param>
      <Param Name="right"><PrimitiveValue Value="yes" /></Param>
    </Params></Condition>""")
    parallel = _parallel(
        [ActionNode("NWWriteToHistoryListAdapter", params={"Message": "parallel one"})],
        [ActionNode("NWWriteToHistoryListAdapter", params={"Message": "parallel two"})],
    )
    parallel.branch_label = "Tak"
    branch = ActionNode("WFIfElseAdapter", condition_el=condition, children=[parallel])
    spec, code = _combined([_declarations({"Name": "Flag"}), branch])
    _assert_guarded(spec, code)
    assert "IF l_wf_flag = 'yes' THEN" in code
    assert "-- Galaz rownolegla 1." in code and "-- Galaz rownolegla 2." in code
    assert "parallel one" in code and "parallel two" in code


def test_blocked_loop_keeps_its_children_in_guarded_template() -> None:
    loop = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWForEachLoopAdapter</Type><Enabled>true</Enabled><Parameters>
        <Parameter Name="Target"><Variable Name="Items" Type="ArrayList" /></Parameter>
        <Parameter Name="Value"><Variable Name="Item" Type="Text" /></Parameter>
        <Parameter Name="Break"><PrimitiveValue Value="true" /></Parameter>
      </Parameters><ChildActivities><NWActionConfig>
        <Type>NWWriteToHistoryListAdapter</Type><Enabled>true</Enabled><Parameters>
          <Parameter Name="Message"><PrimitiveValue Value="loop body" /></Parameter>
        </Parameters>
      </NWActionConfig></ChildActivities></NWActionConfig>"""))
    spec, code = _combined([
        _declarations(
            {"Name": "Items", "Type": "ArrayList", "DefaultValue": "[]"},
            {"Name": "Item"},
        ),
        loop,
    ])
    _assert_guarded(spec, code)
    assert "loop body" in code
    assert any("pętli" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_start_time_approximation_requires_manual_mapping() -> None:
    spec, code = _combined([
        _declarations({"Name": "Value"}),
        _set_variable("Value", "{Common:StartDate}"),
    ])
    _assert_guarded(spec, code)
    assert any("StartDate" in reason for reason in spec["path_b_combined_blocking_reasons"])


def test_email_with_unresolved_recipient_is_not_marked_complete() -> None:
    spec, code = _combined([ActionNode("NWSendMessageAdapter")])
    _assert_guarded(spec, code)
    assert any("TODO" in reason or "odbiorc" in reason.lower() for reason in spec["path_b_combined_blocking_reasons"])


def test_additional_data_binds_remain_parameters_in_combined_code() -> None:
    email = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWSendMessageAdapter</Type><Enabled>true</Enabled>
      <Message><Subject>Subject</Subject><Body>Body</Body></Message>
      <Approvers><Approver User="example@example.invalid" /></Approvers>
    </NWActionConfig>"""))
    spec, code = _combined([email])
    assert ":P_EMAIL_FROM" in code and ":P_EMAIL_EXAMPLE" in code
    assert {"P_EMAIL_FROM", "P_EMAIL_EXAMPLE"} <= set(spec["path_b_combined_required_binds"])
    assert "example@example.invalid" not in code
    assert ":SP_EDITOR" not in code


def test_date_calculation_without_output_is_guarded() -> None:
    spec, code = _combined([ActionNode("NWCalculateDateAdapter", params={"Date": "V_ITEM_ID"})])
    _assert_guarded(spec, code)
    assert any("wynik" in reason.lower() or "wyjści" in reason.lower()
               for reason in spec["path_b_combined_blocking_reasons"])


def test_todo_inside_string_literal_does_not_create_a_blocker() -> None:
    spec, code = _combined([ActionNode("NWWriteToHistoryListAdapter", params={"Message": "/* TODO: text */"})])
    assert spec["path_b_combined_status"] == "Wygenerowany — wymaga weryfikacji"
    assert "'/* TODO: text */'" in code
