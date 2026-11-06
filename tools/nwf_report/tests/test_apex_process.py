"""Testy standardowego procesu APEX Workflow (kroki 1-4, NINTEX_PARAMS, sciezki A/B, dyspozytor)."""
from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from tools.nwf_report.action_catalog import describe_action
from tools.nwf_report.apex_naming import email_param, field_variable, identifier, workflow_static_id
from tools.nwf_report.apex_workflow_guide import (
    RETRIEVE_PAYLOAD_CODE,
    _source_field_spec,
    build_additional_data,
    build_nintex_params_script,
    build_parse_code,
    build_shp_query,
)
from tools.nwf_report.metadata_loader import FieldResolver
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference, WorkflowModel
from tools.nwf_report.report_builder import build_dispatcher_package, build_workflow_data

SOURCE_ID = "{AAAAAAAA-1111-2222-3333-444444444444}"
TARGET_ID = "{BBBBBBBB-1111-2222-3333-444444444444}"

SEND_MESSAGE_XML = """
<NWActionConfig>
    <Type>Nintex.Workflow.Activities.Adapters.NWSendMessageAdapter</Type>
    <Approvers>
        <Approver User="jan.kowalski@bank.pl"/>
    </Approvers>
    <Message>
        <Subject>Wniosek {ItemProperty:Title}</Subject>
        <Body>Dzien dobry</Body>
    </Message>
</NWActionConfig>
"""


def _resolver(fields: list[FieldRef]) -> tuple[ListReference, FieldResolver]:
    source = ListReference("Rejestr", SOURCE_ID, True, fields)
    return source, FieldResolver([source], source_list_id=SOURCE_ID)


def test_naming_maps_polish_letters_and_prefixes() -> None:
    assert identifier("Usługi łączone") == "USLUGI_LACZONE"
    assert workflow_static_id("RT0701 Pobranie danych z Kwalifikacji Usługi") == "WF_RT0701_POBRANIE_DANYCH_Z_KWALIFIKACJI_USLUGI"
    assert field_variable("Status_x0020_Pola") == "SP_STATUS_X0020_POLA"
    assert field_variable("Editor", "EMAIL") == "SP_EDITOR_EMAIL"
    assert email_param("jan.kowalski@bank.pl") == "P_EMAIL_JAN_KOWALSKI"
    assert len(email_param("bardzo.dlugi.adres.uzytkownika.systemu@bank.pl")) <= 30


def test_field_type_is_list_aware() -> None:
    source = ListReference("Rejestr", SOURCE_ID, True, [FieldRef("Status", "Status", "Choice")])
    target = ListReference("Slownik", TARGET_ID, False, [FieldRef("Status", "Status", "Lookup")])
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)

    assert resolver.get_field_type("Status") == "Choice"
    assert resolver.get_field_type("Status", TARGET_ID) == "Lookup"


def test_shp_query_uses_select_and_expand_for_complex_fields() -> None:
    fields = [
        _source_field_spec("Od", "DateTime"),
        _source_field_spec("Kwota", "Number"),
        _source_field_spec("Editor", "User"),
        _source_field_spec("Kategoria", "Lookup"),
    ]

    assert build_shp_query(fields) == (
        "$select=Od,Kwota,Editor/Title,Editor/EMail,Editor/Name,Kategoria/Id,Kategoria/Title"
        "&$expand=Editor,Kategoria"
    )
    assert build_shp_query([]) == "$select=Id"


def test_parse_code_reads_shp_answer_into_sp_variables() -> None:
    code = build_parse_code([
        _source_field_spec("Kwota", "Number"),
        _source_field_spec("Editor", "User"),
        _source_field_spec("Kategoria", "Lookup"),
    ])

    assert "l_json_text := :V_SHP_ANSWER;" in code
    assert ":SP_KWOTA := apex_json.get_number(p_path => 'data.Kwota');" in code
    assert ":SP_EDITOR_EMAIL := apex_json.get_varchar2(p_path => 'data.Editor.EMail');" in code
    assert ":SP_EDITOR := apex_json.get_varchar2(p_path => 'data.Editor.Title');" in code
    assert ":SP_KATEGORIA_ID := apex_json.get_number(p_path => 'data.Kategoria.Id');" in code


def test_retrieve_payload_code_matches_standard_step() -> None:
    assert "l_json_text := :P_PAYLOAD_BODY;" in RETRIEVE_PAYLOAD_CODE
    assert ":V_ITEM_ID := apex_json.get_varchar2(p_path => 'id');" in RETRIEVE_PAYLOAD_CODE
    assert ":V_EDITOR := apex_json.get_varchar2(p_path => 'updated_by');" in RETRIEVE_PAYLOAD_CODE
    assert "RAISE_APPLICATION_ERROR(-20010" in RETRIEVE_PAYLOAD_CODE


def test_additional_data_maps_email_constants_to_nintex_params() -> None:
    node = ActionNode(
        "Nintex.Workflow.Activities.Adapters.NWSendMessageAdapter",
        raw_el=ET.fromstring(SEND_MESSAGE_XML),
    )
    data = build_additional_data("WF_TEST", [node])
    aliases = {param.alias: param for param in data.params}

    assert set(aliases) == {"P_EMAIL_FROM", "P_EMAIL_JAN_KOWALSKI"}
    assert aliases["P_EMAIL_JAN_KOWALSKI"].value == "jan.kowalski@bank.pl"
    assert "AS P_EMAIL_JAN_KOWALSKI" in data.sql
    assert "ON w.workflow_def_static_id = p.workflow_static_id" in data.sql
    assert "WHERE w.workflow_id = :APEX$WORKFLOW_ID" in data.sql
    # pusty adres nadawcy nie moze nadpisac wartosci wpisanej przez administratora
    matched = data.merge_sql.split("WHEN NOT MATCHED")[0]
    assert "'jan.kowalski@bank.pl'" in matched
    assert "= ''" not in matched and "= NULL" not in matched

    desc = describe_action(node, FieldResolver([]))
    assert "p_to   => :P_EMAIL_JAN_KOWALSKI" in desc.plsql_code
    assert "p_from => :P_EMAIL_FROM" in desc.plsql_code


def test_additional_data_without_constants_has_empty_sql() -> None:
    data = build_additional_data("WF_TEST", [])

    assert data.sql == ""
    assert data.params == []
    assert "INSERT (workflow_static_id) VALUES (s.workflow_static_id)" in data.merge_sql


def test_nintex_params_script_contains_supplied_schema_and_trigger() -> None:
    source, resolver = _resolver([])
    wf = WorkflowModel("Moj Workflow", "", [source], [], Path("moj.nwf"))
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]

    script = build_nintex_params_script([spec])
    ddl = script.split("MERGE INTO", 1)[0]
    columns = dict(re.findall(r'^--\s+"([A-Z][A-Z0-9_]*)"\s+(.+),$', ddl, re.MULTILINE))
    expected_columns = {
        "ID": "NUMBER GENERATED BY DEFAULT ON NULL AS IDENTITY MINVALUE 1 MAXVALUE 9999999999999999999999999999 INCREMENT BY 1 START WITH 1 CACHE 20 NOORDER NOCYCLE NOKEEP NOSCALE NOT NULL ENABLE",
        "WORKFLOW_STATIC_ID": "VARCHAR2(500)",
        "CREATED": "DATE NOT NULL ENABLE",
        "CREATED_BY": "VARCHAR2(255) NOT NULL ENABLE",
        "UPDATED": "DATE NOT NULL ENABLE",
        "UPDATED_BY": "VARCHAR2(255) NOT NULL ENABLE",
        "RESPONSIBLE": "VARCHAR2(255)",
        "IS_ACTIVE": "NUMBER(1,0) DEFAULT 0 NOT NULL ENABLE",
        **{f"P_VAR_{i:02d}": "VARCHAR2(4000)" for i in range(1, 5)},
        **{f"P_NUM_{i:02d}": "NUMBER" for i in range(1, 5)},
        **{f"P_DATE_{i:02d}": "DATE" for i in range(1, 5)},
        **{f"P_CLOB_{i:02d}": "CLOB" for i in range(1, 3)},
        **{f"C_{kind}_{i:02d}": "VARCHAR2(4000)" for kind in ("VAR", "NUM", "DATE") for i in range(1, 5)},
        **{f"C_CLOB_{i:02d}": "VARCHAR2(4000)" for i in range(1, 3)},
    }
    assert columns == expected_columns
    assert all(not line or line.startswith("--") for line in ddl.splitlines())
    assert 'CREATE TABLE "NINTEX_PARAMS"' in ddl
    assert 'CONSTRAINT "NINTEX_PARAMS_ID_PK" PRIMARY KEY ("ID") USING INDEX ENABLE' in ddl
    assert 'CONSTRAINT "NINTEX_PARAMS_W_STATIC_ID_UNIQUE" UNIQUE ("WORKFLOW_STATIC_ID") USING INDEX ENABLE' in ddl
    assert 'CREATE OR REPLACE EDITIONABLE TRIGGER "NINTEX_PARAMS_BIU"' in ddl
    assert "BEFORE INSERT OR UPDATE ON NINTEX_PARAMS" in ddl.upper()
    assert "IF INSERTING THEN" in ddl.upper()
    assert ":NEW.CREATED := SYSDATE;" in ddl.upper()
    assert ":NEW.CREATED_BY := COALESCE(SYS_CONTEXT('APEX$SESSION', 'APP_USER'), USER);" in ddl.upper()
    assert ":NEW.UPDATED := SYSDATE;" in ddl.upper()
    assert ":NEW.UPDATED_BY := COALESCE(SYS_CONTEXT('APEX$SESSION', 'APP_USER'), USER);" in ddl.upper()
    assert "-- /" in ddl
    assert 'ALTER TRIGGER "NINTEX_PARAMS_BIU" ENABLE;' in ddl
    assert "'WF_MOJ_WORKFLOW' AS workflow_static_id" in script
    assert script.rstrip().endswith("COMMIT;")


@pytest.mark.parametrize("recipient_count", [3, 4, 11])
def test_additional_data_keeps_all_params_and_warns_about_schema_extensions(recipient_count: int) -> None:
    recipients = "".join(f'<Approver User="contact{i:02d}@example.org"/>' for i in range(1, recipient_count + 1))
    node = ActionNode(
        "Nintex.Workflow.Activities.Adapters.NWSendMessageAdapter",
        raw_el=ET.fromstring(f"<NWActionConfig><Approvers>{recipients}</Approvers></NWActionConfig>"),
    )
    data = build_additional_data("WF_TEST", [node])
    action_code = describe_action(node, FieldResolver([])).plsql_code

    assert len(data.params) == recipient_count + 1
    assert [param.column for param in data.params] == [f"P_VAR_{i:02d}" for i in range(1, recipient_count + 2)]
    for param in data.params:
        assert f"p.{param.column} AS {param.alias}" in data.sql
        assert param.column.lower() in data.merge_sql
        if param.value:
            assert f"'{param.value}'" in data.merge_sql
            assert f":{param.alias}" in action_code
    matched = data.merge_sql.split("WHEN NOT MATCHED", 1)[0]
    assert "t.p_var_01 =" not in matched
    assert "is_active" not in data.merge_sql.lower()
    assert "is_active" not in data.sql.lower()
    assert any("IS_ACTIVE" in note and "0" in note for note in data.notes)
    assert any("NINTEX_PARAMS_BIU" in note for note in data.notes)

    extra_columns = [param.column for param in data.params[4:]]
    for column in extra_columns:
        assert any(column in note and "administrator" in note.lower() for note in data.notes)
    spec = {"name": "WF Test", "static_id": "WF_TEST", "additional_data": asdict(data)}
    script = build_nintex_params_script([spec])
    header = script.split("MERGE INTO", 1)[0]
    for column in extra_columns:
        assert f"--   {column} VARCHAR2(4000)" in header
    if not extra_columns:
        assert "kolumny spoza bazowego DDL" not in header.lower()


def test_nintex_params_script_lists_extension_types_without_altering_schema() -> None:
    columns = ["P_VAR_04", "P_NUM_05", "P_DATE_05", "P_CLOB_03", "C_NUM_05", "C_DATE_05", "C_CLOB_03", "P_BOOL_01"]
    additional = {
        "params": [{"column": column} for column in columns],
        "merge_sql": "MERGE INTO nintex_params t USING dual ON (1 = 0) WHEN NOT MATCHED THEN INSERT (workflow_static_id) VALUES ('WF_TEST');",
    }
    script = build_nintex_params_script([
        {"name": "WF Test", "static_id": "WF_TEST", "additional_data": additional},
        {"name": "WF Other", "static_id": "WF_OTHER", "additional_data": additional},
    ])
    header = script.split("MERGE INTO", 1)[0]

    for column, data_type in (
        ("P_NUM_05", "NUMBER"),
        ("P_DATE_05", "DATE"),
        ("P_CLOB_03", "CLOB"),
        ("C_NUM_05", "VARCHAR2(4000)"),
        ("C_DATE_05", "VARCHAR2(4000)"),
        ("C_CLOB_03", "VARCHAR2(4000)"),
        ("P_BOOL_01", "(typ do ustalenia)"),
    ):
        assert header.count(f"--   {column} {data_type}") == 1
    assert "--   P_VAR_04" not in header
    assert all("ALTER TABLE" not in line.upper() for line in script.splitlines() if not line.startswith("--"))


def test_standard_steps_and_path_b_for_workflow() -> None:
    source, resolver = _resolver([FieldRef("Kwota", "Kwota", "Number")])
    set_field = ActionNode(
        "Nintex.Workflow.Activities.Adapters.SPSetFieldWithKeyAdapter",
        params={"LookupField": "Kwota", "LookupFieldValue": "{ItemProperty:Kwota}", "LookupFieldType": "Number"},
    )
    wf = WorkflowModel("Kwota WF", "", [source], [set_field], Path("kwota.nwf"), workflow_type="List")
    spec = build_workflow_data(wf, resolver)["apex_workflow_spec"]

    start, payload, get_item, parse = spec["standard_activities"]
    assert start["activity_type"] == "Workflow Start"
    assert payload["plsql_code"] == RETRIEVE_PAYLOAD_CODE
    assert get_item["activity_type"] == "Invoke API"
    assert get_item["settings"] == {"Owner": "LCDT", "Package": "SHP_API", "Function": "GET_LIST_ITEM"}
    mapping = {m["parameter"]: m["value"] for m in get_item["parameter_mapping"]}
    assert mapping["p_query"] == "$select=Kwota"
    assert mapping["Function Result"] == "V_SHP_ANSWER"
    assert ":SP_KWOTA := apex_json.get_number(p_path => 'data.Kwota');" in parse["plsql_code"]
    assert parse["transitions"][0]["target_node_id"] == spec["activities"][0]["node_id"]

    variables = {v["static_id"]: v["data_type"] for v in spec["variables"]}
    assert variables["V_SHP_ANSWER"] == "CLOB"
    assert variables["SP_KWOTA"] == "NUMBER"

    path_b = spec["path_b"]["plsql_code"]
    assert "LCDT.SHP_API.update_list_item" in path_b
    assert "'Kwota' VALUE :SP_KWOTA" in path_b
    assert spec["path_b"]["transitions"][0]["target_node_id"] == "stop"


def test_cross_lookup_with_lookup_id_coercion_reads_related_id() -> None:
    source = ListReference("Rejestr", SOURCE_ID, True, [FieldRef("Kategoria", "Kategoria", "Lookup")])
    target = ListReference("Kategorie", TARGET_ID, False, [FieldRef("Umowa", "Umowa", "Lookup")])
    resolver = FieldResolver([source, target], source_list_id=SOURCE_ID)
    node = ActionNode(
        "Nintex.Workflow.Activities.Adapters.SPSetVariableAdapter",
        param_elements={
            "VariableName": ET.fromstring('<Variable Name="UmowaId" Type="SPItemKey" />'),
            "Value": ET.fromstring(
                f"""<ListLookup LookupType="CrossItemLookup">
                  <Lookup LookupType="ThisItemLookup"><ListId>{SOURCE_ID}</ListId><Field Name="Kategoria" Type="Lookup" /></Lookup>
                  <Coercion>LookupIdOnlyAsInteger</Coercion>
                  <ListId>{TARGET_ID}</ListId><Field Name="Umowa" Type="Lookup" />
                  <CompareField Name="ID" Type="Counter" />
                </ListLookup>"""
            ),
        },
    )
    code = describe_action(node, resolver).plsql_code

    assert "p_item_id    => :SP_KATEGORIA_ID" in code
    assert "p_query      => '$select=Umowa/Id&$expand=Umowa'" in code
    assert ":UMOWAID := json_value(l_ref_json, '$.data.Umowa.Id');" in code


def test_dispatcher_routes_unknown_association_with_warning() -> None:
    sql = build_dispatcher_package([
        {"title": "Wf O'Brien", "workflow_type": "List", "apex_workflow_spec": {"static_id": "WF_O_BRIEN"}},
    ])

    assert "WHEN 'Wf O''Brien' THEN l_static_id := 'WF_O_BRIEN';" in sql
    assert "Nieznany workflow (association)" in sql
    assert "c_app_id    CONSTANT NUMBER        := NULL;" in sql
    assert "p_detail_pk      => TO_CHAR(l_id)" in sql
