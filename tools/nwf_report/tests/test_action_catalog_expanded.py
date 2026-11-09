from __future__ import annotations

import xml.etree.ElementTree as ET
import pytest

from tools.nwf_report.action_catalog import build_path_b_code, describe_action
from tools.nwf_report.metadata_loader import FieldResolver
from tools.nwf_report.nwf_parser import ActionNode, FieldRef, ListReference, _parse_action


@pytest.fixture
def empty_resolver() -> FieldResolver:
    return FieldResolver({}, {})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ConnectionString", "Server=test;UID=synthetic_user;PWD=synthetic_password"),
        ("connection_string", "Server=test;Password=synthetic_password"),
        ("Password", "synthetic_password"),
        ("Pwd", "synthetic_password"),
        ("User ID", "synthetic_user"),
        ("UID", "synthetic_user"),
        ("Details", "Server=test;UID=synthetic_user;PWD=synthetic_password"),
    ],
)
def test_connection_string_redacted(
    empty_resolver: FieldResolver, name: str, value: str
) -> None:
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.UnknownAdapter",
        params={name: value, "Operation": "Get"},
    )

    desc = describe_action(node, empty_resolver)
    rendered = repr(desc)

    assert value not in rendered
    assert "synthetic_password" not in rendered
    assert "synthetic_user" not in rendered
    assert "Operation = Get" in rendered


def test_describe_build_string(empty_resolver: FieldResolver) -> None:
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWBuildStringAdapter",
        enabled=True,
        params={"Input": "PREFIX-{WorkflowVariable:Numer}-SUFFIX", "Output": "ZmiennaTekstowa"},
    )
    desc = describe_action(node, empty_resolver)
    assert "ZmiennaTekstowa" in desc.summary
    assert "PREFIX-{WorkflowVariable:Numer}-SUFFIX" in desc.summary
    assert ":ZMIENNATEKSTOWA :=" in desc.plsql_code


def test_describe_business_process(empty_resolver: FieldResolver) -> None:
    child = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWWriteToHistoryListAdapter",
        enabled=True,
        params={"Message": "Krok 1"},
    )
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWBusinessProcessAdapter",
        enabled=True,
        t_label="Etap 1: Inicjalizacja",
        params={},
        children=[child],
    )
    desc = describe_action(node, empty_resolver)
    assert "Etap 1: Inicjalizacja" in desc.summary
    assert "Etap: Etap 1: Inicjalizacja" in desc.plsql_code


def test_describe_calculate_date(empty_resolver: FieldResolver) -> None:
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWCalculateDateAdapter",
        enabled=True,
        params={
            "Date": "Current Date",
            "Days": "5",
            "Months": "1",
            "Years": "0",
            "Hours": "2",
            "Minutes": "0",
            "Output": "TerminRealizacji",
        },
    )
    desc = describe_action(node, empty_resolver)
    assert "TerminRealizacji" in desc.summary
    assert "+1 mies." in desc.summary
    assert "+5 dni" in desc.summary
    assert "+2 godz." in desc.summary
    assert ":TERMINREALIZACJI :=" in desc.plsql_code
    assert "ADD_MONTHS" in desc.plsql_code


def test_describe_collection(empty_resolver: FieldResolver) -> None:
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWCollectionAdapter",
        enabled=True,
        params={
            "Operation": "Count",
            "Target": "ListaKierownikow",
            "Output": "LiczbaKierownikow",
        },
    )
    desc = describe_action(node, empty_resolver)
    assert "Zlicz" in desc.summary
    assert "ListaKierownikow" in desc.summary
    assert "LiczbaKierownikow" in desc.summary
    assert "JSON_ARRAY_T.parse(:LISTAKIEROWNIKOW)" in desc.plsql_code
    assert ":LICZBAKIEROWNIKOW := l_collection.get_size;" in desc.plsql_code


def test_collection_get_reads_variable_parameters_and_zero_index(empty_resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWCollectionAdapter</Type><Enabled>true</Enabled><Parameters>
        <Parameter Name="Operation"><PrimitiveValue Value="Get" /></Parameter>
        <Parameter Name="Target"><Variable Name="Items" Type="ArrayList" /></Parameter>
        <Parameter Name="Index"><Variable Name="CurrentIndex" Type="Number" /></Parameter>
        <Parameter Name="Output"><Variable Name="Result" Type="Text" /></Parameter>
      </Parameters></NWActionConfig>"""))

    desc = describe_action(node, empty_resolver)
    assert "Items" in desc.summary and "CurrentIndex" in desc.summary and "Result" in desc.summary
    assert "JSON_ARRAY_T.parse(:ITEMS)" in desc.plsql_code
    assert "l_index < 0 OR l_index >= l_collection.get_size" in desc.plsql_code
    assert "l_element.is_null" in desc.plsql_code
    assert "l_element.is_string" in desc.plsql_code
    assert """l_element.to_string = '""'""" in desc.plsql_code
    assert "RAISE_APPLICATION_ERROR(-20092" in desc.plsql_code
    assert "RAISE_APPLICATION_ERROR(-20093" in desc.plsql_code
    assert ":RESULT := l_collection.get_string(l_index);" in desc.plsql_code
    assert not desc.blocking_reasons


def test_datetime_collection_get_is_blocked(empty_resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWCollectionAdapter</Type><Enabled>true</Enabled><Parameters>
        <Parameter Name="Operation"><PrimitiveValue Value="Get" /></Parameter>
        <Parameter Name="Target"><Variable Name="Items" Type="ArrayList" /></Parameter>
        <Parameter Name="Index"><PrimitiveValue Value="0" /></Parameter>
        <Parameter Name="Output"><Variable Name="Result" Type="DateTime" /></Parameter>
      </Parameters></NWActionConfig>"""))
    desc = describe_action(node, empty_resolver)
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code


def test_describe_create_site_specific_item(empty_resolver: FieldResolver) -> None:
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWCreateSiteSpecificItemAdapter",
        enabled=True,
        b_label="Zadania_DORA",
        params={"Output": "NoweZadanieID"},
        raw_el=ET.fromstring(
            '<NWActionConfig><FieldReferences><FieldReference Value="Title" Type="Text">'
            '<PrimitiveValue Value="Test" /></FieldReference></FieldReferences></NWActionConfig>'
        ),
    )
    desc = describe_action(node, empty_resolver)
    assert "Zadania_DORA" in desc.summary
    assert "NoweZadanieID" in desc.summary
    assert "l_resp := LCDT.SHP_API.add_list_item(" in desc.plsql_code
    assert ":NOWEZADANIEID := json_value(l_resp, '$.item_id' RETURNING NUMBER);" in desc.plsql_code
    assert "p_list_title  => 'Zadania_DORA'" in desc.plsql_code


def test_describe_delay_for(empty_resolver: FieldResolver) -> None:
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWDelayForAdapter",
        enabled=True,
        params={"Days": "0", "Hours": "3", "Minutes": "15"},
    )
    desc = describe_action(node, empty_resolver)
    assert "3 godz., 15 min" in desc.summary
    assert "DBMS_SESSION.SLEEP" not in desc.plsql_code
    assert "Wait" in desc.plsql_code
    assert "(195 min)" in desc.plsql_code


def test_describe_for_each_loop(empty_resolver: FieldResolver) -> None:
    child = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWWriteToHistoryListAdapter",
        enabled=True,
        params={"Message": "Item loop"},
    )
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWForEachLoopAdapter",
        enabled=True,
        params={
            "Target": "KolekcjaAdresatow",
            "Value": "BiezacyAdresat",
        },
        children=[child],
    )
    desc = describe_action(node, empty_resolver)
    assert "KolekcjaAdresatow" in desc.summary
    assert "BiezacyAdresat" in desc.summary
    assert desc.path_a_blocking_reasons
    assert desc.path_b_blocking_reasons
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code


def test_for_each_path_b_uses_zero_based_json_array(empty_resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWForEachLoopAdapter</Type><Enabled>true</Enabled><Parameters>
        <Parameter Name="Target"><Variable Name="Items" Type="ArrayList" /></Parameter>
        <Parameter Name="Value"><Variable Name="Item" Type="Text" /></Parameter>
        <Parameter Name="Index"><Variable Name="Index" Type="Number" /></Parameter>
        <Parameter Name="Break"><PrimitiveValue Value="false" /><Variable Name="" Type="Boolean" /></Parameter>
      </Parameters></NWActionConfig>"""))

    desc = describe_action(node, empty_resolver)
    code = build_path_b_code([node], empty_resolver)
    assert desc.path_a_blocking_reasons
    assert not desc.path_b_blocking_reasons
    assert "IF l_nintex_items.get_size > 0 THEN" in code
    assert "FOR l_nintex_index IN 0 .. l_nintex_items.get_size - 1 LOOP" in code
    assert ":INDEX := l_nintex_index;" in code
    assert "l_nintex_element.is_null" in code
    assert "l_nintex_element.is_string" in code
    assert """l_nintex_element.to_string = '""'""" in code
    assert "RAISE_APPLICATION_ERROR(-20092" in code
    assert "RAISE_APPLICATION_ERROR(-20093" in code
    assert ":ITEM := l_nintex_items.get_string(l_nintex_index);" in code
    assert "END LOOP;" in code


def test_for_each_break_variable_blocks_path_b(empty_resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWForEachLoopAdapter</Type><Enabled>true</Enabled><Parameters>
        <Parameter Name="Target"><Variable Name="Items" Type="ArrayList" /></Parameter>
        <Parameter Name="Value"><Variable Name="Item" Type="Text" /></Parameter>
        <Parameter Name="Break"><PrimitiveValue Value="true" /><Variable Name="Stop" Type="Boolean" /></Parameter>
      </Parameters></NWActionConfig>"""))
    assert "RAISE_APPLICATION_ERROR" in build_path_b_code([node], empty_resolver)


def test_run_sql_maps_reversed_34_columns_by_name_without_credentials(
    empty_resolver: FieldResolver,
) -> None:
    projection = ", ".join(f"C{number}" for number in range(1, 35))
    mappings = "".join(
        f'<ValueStorage ValueIdentifier="C{number}" VariableName="Out{number}" VariableType="ArrayList" />'
        for number in range(34, 0, -1)
    )
    node = _parse_action(ET.fromstring(f"""<NWActionConfig><Type>NWRunSqlAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="Provider"><PrimitiveValue Value="MsSql" /></Parameter>
        <Parameter Name="Query"><PrimitiveValue Value="SELECT {projection} FROM SyntheticTable" /></Parameter>
        <Parameter Name="ConnectionString"><PrimitiveValue Value="Server=test;UID=synthetic_user;PWD=synthetic_password" /></Parameter>
      </Parameters><ValueStorages><ValueStorageItems>{mappings}</ValueStorageItems></ValueStorages>
    </NWActionConfig>"""))

    desc = describe_action(node, empty_resolver)
    assert "34 mapowań" in desc.summary
    assert "Kolumna C34 (pozycja SELECT 34) -> kolekcja Out34" in desc.technical_lines
    assert "Kolumna C1 (pozycja SELECT 1) -> kolekcja Out1" in desc.technical_lines
    assert "DBMS_HS_PASSTHROUGH" in desc.hint_apex
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code
    assert desc.blocking_reasons
    template = desc.reference_template
    assert template.count("OPEN_CURSOR@") == 1
    assert template.count("FETCH_ROW@") == 1
    assert template.count("GET_VALUE@") == 34
    assert "l_cursor, 34, l_value" in template
    assert "l_cursor, 1, l_value" in template
    assert "l_collection_01.append_null;" in template
    assert ":OUT34 := l_collection_01.to_clob;" in template
    assert template.count("CLOSE_CURSOR@") == 2
    assert template.count("WHEN OTHERS THEN") == 2
    assert "apex_debug.error(" in template and "RAISE;" in template
    assert "RAISE_APPLICATION_ERROR" in template
    assert "SyntheticTable" not in template
    assert "synthetic_user" not in repr(desc)
    assert "synthetic_password" not in repr(desc)


def test_run_sql_rejects_ambiguous_column_aliases(empty_resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWRunSqlAdapter</Type><Enabled>true</Enabled>
      <Parameters><Parameter Name="Query"><PrimitiveValue Value="SELECT A AS X, B AS X FROM T" /></Parameter></Parameters>
      <ValueStorages><ValueStorageItems><ValueStorage ValueIdentifier="X" VariableName="Result" VariableType="ArrayList" />
      </ValueStorageItems></ValueStorages></NWActionConfig>"""))
    desc = describe_action(node, empty_resolver)
    assert any("Powtarzająca" in reason for reason in desc.blocking_reasons)
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code


def test_run_sql_rejects_collection_names_with_colliding_static_ids(empty_resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWRunSqlAdapter</Type><Enabled>true</Enabled>
      <Parameters><Parameter Name="Query"><PrimitiveValue Value="SELECT A, B FROM T" /></Parameter></Parameters>
      <ValueStorages><ValueStorageItems>
        <ValueStorage ValueIdentifier="A" VariableName="Result A" VariableType="ArrayList" />
        <ValueStorage ValueIdentifier="B" VariableName="Result-A" VariableType="ArrayList" />
      </ValueStorageItems></ValueStorages></NWActionConfig>"""))
    desc = describe_action(node, empty_resolver)
    assert any("kolekcja" in reason for reason in desc.blocking_reasons)
    assert not desc.reference_template


def test_run_sql_maps_five_aliased_columns_in_one_cursor(empty_resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWRunSqlAdapter</Type><Enabled>true</Enabled>
      <Parameters><Parameter Name="Query"><PrimitiveValue
        Value="SELECT A AS X, B AS Y, C AS Z, D AS W, E AS V FROM T" /></Parameter></Parameters>
      <ValueStorages><ValueStorageItems>
        <ValueStorage ValueIdentifier="V" VariableName="ResultV" VariableType="ArrayList" />
        <ValueStorage ValueIdentifier="X" VariableName="ResultX" VariableType="ArrayList" />
        <ValueStorage ValueIdentifier="Y" VariableName="ResultY" VariableType="ArrayList" />
        <ValueStorage ValueIdentifier="Z" VariableName="ResultZ" VariableType="ArrayList" />
        <ValueStorage ValueIdentifier="W" VariableName="ResultW" VariableType="ArrayList" />
      </ValueStorageItems></ValueStorages></NWActionConfig>"""))

    desc = describe_action(node, empty_resolver)
    template = desc.reference_template
    assert "Kolumna V (pozycja SELECT 5) -> kolekcja ResultV" in desc.technical_lines
    assert "Kolumna X (pozycja SELECT 1) -> kolekcja ResultX" in desc.technical_lines
    assert template.count("OPEN_CURSOR@") == 1
    assert template.count("FETCH_ROW@") == 1
    assert template.count("GET_VALUE@") == 5
    assert template.count(".append_null;") == 5
    assert ":RESULTV := l_collection_01.to_clob;" in template
    assert desc.blocking_reasons


def test_create_content_type_reports_all_field_mappings_for_target_list() -> None:
    source = ListReference("Source", "source", True, [FieldRef("Source title", "Shared", "Text")])
    target = ListReference("Target", "target", False, [FieldRef("Target title", "Shared", "Choice")])
    resolver = FieldResolver([source, target], source_list_id="source")
    node = _parse_action(ET.fromstring("""<NWActionConfig>
      <Type>NWCreateItemWithContentTypesAdapter</Type><Enabled>true</Enabled><Parameters>
        <Parameter Name="ListId"><PrimitiveValue Value="target" /></Parameter>
        <Parameter Name="ContentType"><PrimitiveValue Value="0x0101" /></Parameter>
        <Parameter Name="Overwrite"><PrimitiveValue Value="false" /></Parameter>
        <Parameter Name="Output"><Variable Name="" /></Parameter>
      </Parameters><FieldReferences>
        <FieldReference Name="Target title" Value="Shared" Type="Choice">
          <Variable Name="ValueA" Type="Text" /><Coercion>AsDNString</Coercion>
        </FieldReference>
        <FieldReference Name="Number" Value="Amount" Type="Number">
          <Variable Name="ValueB" Type="Number" /><Coercion>AsDNDouble</Coercion>
        </FieldReference>
      </FieldReferences></NWActionConfig>"""))

    desc = describe_action(node, resolver)
    assert "Target" in desc.summary and "2 mapowaniami" in desc.summary
    assert "Shared = zmienna ValueA (konwersja: AsDNString)" in desc.technical_lines
    assert "Amount = zmienna ValueB (konwersja: AsDNDouble)" in desc.technical_lines
    assert "Output = (brak)" in desc.technical_lines
    assert [field.internal_name for field in desc.writes] == ["Shared", "Amount"]
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code
    assert desc.blocking_reasons
    assert "LCDT.SHP_API.add_list_item(" in desc.reference_template
    assert "'Shared' VALUE :VALUEA" in desc.reference_template
    assert "'Amount' VALUE NULL /* TODO: potwierdź wartość i konwersję */" in desc.reference_template
    assert "DOCELOWY_CONTENT_TYPE_ID" in desc.reference_template
    assert "item_id" not in desc.reference_template


def test_math_mod_uses_variable_operands_and_guards_zero(empty_resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>SPMathAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="VariableName"><Variable Name="BatchEnd" Type="Number" /></Parameter>
        <Parameter Name="Operator"><PrimitiveValue Value="mod" /></Parameter>
        <Parameter Name="Operand1"><Variable Name="CurrentIndex" Type="Number" /><Coercion>AsDNDouble</Coercion></Parameter>
        <Parameter Name="Operand2"><PrimitiveValue Value="30" /></Parameter>
      </Parameters></NWActionConfig>"""))

    desc = describe_action(node, empty_resolver)
    assert ":BATCHEND := MOD(:CURRENTINDEX, 30);" in desc.plsql_code
    assert "30 <= 0" in desc.plsql_code
    assert not desc.blocking_reasons


def test_math_unsupported_operator_is_blocked(empty_resolver: FieldResolver) -> None:
    node = _parse_action(ET.fromstring("""<NWActionConfig><Type>SPMathAdapter</Type><Enabled>true</Enabled>
      <Parameters><Parameter Name="Operator"><PrimitiveValue Value="divide" /></Parameter></Parameters>
    </NWActionConfig>"""))
    desc = describe_action(node, empty_resolver)
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code


def test_delete_multiple_reports_filter_and_blocks_without_api() -> None:
    resolver = FieldResolver([ListReference("Target", "target", False, [])])
    node = ActionNode(
        "NWDeleteMultipleItemAdapter",
        params={
            "Query": (
                "<Query><List ID='target' /><Where><Eq><FieldRef Name='Status' />"
                "<Value Type='Text'>Expired</Value></Eq></Where></Query>"
            )
        },
    )
    desc = describe_action(node, resolver)
    assert "Target" in desc.summary
    assert "Status jest równe 'Expired'" in desc.summary
    assert "nie udostępnia usuwania" in desc.hint_apex
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code


def test_collect_data_reports_answers_and_blocks_before_prior_write(empty_resolver: FieldResolver) -> None:
    collect = _parse_action(ET.fromstring("""<NWActionConfig><Type>NWCollectDataAdapter</Type><Enabled>true</Enabled>
      <Parameters>
        <Parameter Name="TaskName"><PrimitiveValue Value="Review" /></Parameter>
        <Parameter Name="TaskID"><Variable Name="TaskId" /></Parameter>
        <Parameter Name="HumanWorkflowID"><Variable Name="ActionId" /></Parameter>
        <Parameter Name="DaysReminder"><PrimitiveValue Value="14" /></Parameter>
      </Parameters><FieldReferences>
        <FieldReference Name="Approved" Type="Choice"><Variable Name="Answer" /><Choice>Yes</Choice><Choice>No</Choice></FieldReference>
        <FieldReference Name="Notes" Type="Text"><Variable Name="Comment" /></FieldReference>
      </FieldReferences><Approvers><Approver User="reviewer" PrincipalType="User" /></Approvers></NWActionConfig>"""))
    prior_write = ActionNode(
        "SPUpdateItemWithKeyAdapter",
        field_refs=[FieldRef("Title", "Title", "Text")],
    )
    desc = describe_action(collect, empty_resolver)
    code = build_path_b_code([prior_write, collect], empty_resolver)

    assert "zaczekaj" in desc.summary
    assert any("Approved" in line and "Choice" in line and "Answer" in line for line in desc.technical_lines)
    assert any("Notes" in line and "Text" in line and "Comment" in line for line in desc.technical_lines)
    assert "DaysReminder = 14" in desc.technical_lines
    assert "TaskID -> TaskId" in desc.technical_lines
    assert "RAISE_APPLICATION_ERROR" in code
    assert "update_list_item" not in code


def test_cancel_specific_workflow_is_blocked_until_identity_and_commit_verified(
    empty_resolver: FieldResolver,
) -> None:
    node = ActionNode("NWCancelWorkflowAdapter", params={"WorkflowName": "Review", "Message": "Stop"})
    desc = describe_action(node, empty_resolver)
    assert "Review" in desc.summary
    assert "bieżącego elementu" in desc.summary
    assert "commit" in desc.hint_universal
    assert "p_instance_id" in desc.hint_apex
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code
    assert "APEX_WORKFLOW.TERMINATE(" not in desc.plsql_code


@pytest.mark.parametrize("query", ["", "<Query><Where>", "<Query><Where><Unknown /></Where></Query>"])
def test_invalid_caml_does_not_claim_unfiltered_success(empty_resolver: FieldResolver, query: str) -> None:
    node = ActionNode("NWDeleteMultipleItemAdapter", params={"Query": query})
    desc = describe_action(node, empty_resolver)
    assert "wszystkie elementy" not in desc.summary
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code


def test_describe_query_list(empty_resolver: FieldResolver) -> None:
    xml_str = """
    <NWActionConfig>
        <Type>Nintex.Workflow.Activities.Adapters.NWQueryListAdapter</Type>
        <BLabel>Slownik_Statusow</BLabel>
        <Parameters>
            <Parameter Name="Query"><PrimitiveValue Value="&lt;Query&gt;&lt;Where&gt;&lt;Eq&gt;&lt;FieldRef Name=&quot;Aktywny&quot;/&gt;&lt;Value Type=&quot;Boolean&quot;&gt;1&lt;/Value&gt;&lt;/Eq&gt;&lt;/Where&gt;&lt;/Query&gt;"/></Parameter>
        </Parameters>
        <ValueStorages>
            <ValueStorageItems>
                <ValueStorage VariableName="vStatusID" ValueIdentifier="ID"/>
                <ValueStorage VariableName="vNazwaStatusu" ValueIdentifier="Title"/>
            </ValueStorageItems>
        </ValueStorages>
    </NWActionConfig>
    """
    raw_el = ET.fromstring(xml_str)
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWQueryListAdapter",
        enabled=True,
        b_label="Slownik_Statusow",
        params={"Query": "<Query><Where><Eq><FieldRef Name=\"Aktywny\"/><Value Type=\"Boolean\">1</Value></Eq></Where></Query>"},
        raw_el=raw_el,
    )
    desc = describe_action(node, empty_resolver)
    assert "Slownik_Statusow" in desc.summary
    assert "Aktywny jest równe '1'" in desc.summary
    assert "vStatusID" in desc.summary
    assert "vNazwaStatusu" in desc.summary
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code
    assert desc.blocking_reasons
    assert len(desc.reads) == 1
    assert desc.reads[0].internal_name == "Aktywny"


def test_describe_send_message(empty_resolver: FieldResolver) -> None:
    xml_str = """
    <NWActionConfig>
        <Type>Nintex.Workflow.Activities.Adapters.NWSendMessageAdapter</Type>
        <Approvers>
            <Approver User="jan.kowalski@bank.pl"/>
            <Approver User="{WorkflowVariable:Kierownik}"/>
        </Approvers>
        <Message>
            <Subject>Powiadomienie o wniosku</Subject>
            <Body>&lt;div&gt;Dzien dobry, wniosek zostal zlozony.&lt;/div&gt;</Body>
        </Message>
    </NWActionConfig>
    """
    raw_el = ET.fromstring(xml_str)
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWSendMessageAdapter",
        enabled=True,
        raw_el=raw_el,
    )
    desc = describe_action(node, empty_resolver)
    assert "Powiadomienie o wniosku" in desc.summary
    assert "jan.kowalski@bank.pl" in desc.summary
    assert "apex_mail.send" in desc.plsql_code
    assert "p_subj => 'Powiadomienie o wniosku'" in desc.plsql_code


def test_describe_start_workflow2(empty_resolver: FieldResolver) -> None:
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWStartWorkflow2Adapter",
        enabled=True,
        b_label="Akceptacja_Kierownika",
        params={"WaitForComplete": "false"},
    )
    desc = describe_action(node, empty_resolver)
    assert "Akceptacja_Kierownika" in desc.summary
    assert "apex_workflow.start_workflow(" in desc.plsql_code
    assert "'WF_AKCEPTACJA_KIEROWNIKA'" in desc.plsql_code
    assert "'P_PAYLOAD_BODY'" in desc.plsql_code


def test_describe_update_multiple_item(empty_resolver: FieldResolver) -> None:
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWUpdateMultipleItemAdapter",
        enabled=True,
        b_label="RejestrWnioskow",
        params={"Query": "<Query><Where><Eq><FieldRef Name=\"Status\"/><Value>Nowy</Value></Eq></Where></Query>"},
    )
    desc = describe_action(node, empty_resolver)
    assert "RejestrWnioskow" in desc.summary
    assert "Status jest równe 'Nowy'" in desc.summary
    assert "RAISE_APPLICATION_ERROR" in desc.plsql_code
    assert "$filter=" not in desc.plsql_code
    assert "Title' VALUE NULL" not in desc.plsql_code
    assert desc.blocking_reasons
    assert not desc.writes
    assert desc.reads[0].internal_name == "Status"


@pytest.mark.parametrize("action_type", ["NWQueryListAdapter", "NWUpdateMultipleItemAdapter"])
@pytest.mark.parametrize("query", [
    "",
    "<Query><Where>",
    "<Query><Where><Unknown /></Where></Query>",
    "<Query><Where><Eq><FieldRef Name='Status' /><Value Type='Text'>Active</Value></Eq></Where></Query>",
])
def test_bulk_operations_refuse_execution_even_for_valid_filters_without_pagination(
    empty_resolver: FieldResolver, action_type: str, query: str
) -> None:
    prior_write = ActionNode("SPUpdateItemWithKeyAdapter", field_refs=[FieldRef("Title", "Title", "Text")])
    node = ActionNode(action_type, params={"Query": query})
    desc = describe_action(node, empty_resolver)
    code = build_path_b_code([prior_write, node], empty_resolver)

    assert "next_url" in desc.hint_apex
    assert desc.blocking_reasons
    assert "RAISE_APPLICATION_ERROR" in code
    assert "get_list_items(" not in code
    assert "update_list_item(" not in code
    assert "$filter=" not in code
