from __future__ import annotations

import xml.etree.ElementTree as ET
import pytest

from tools.nwf_report.action_catalog import describe_action
from tools.nwf_report.metadata_loader import FieldResolver
from tools.nwf_report.nwf_parser import ActionNode


@pytest.fixture
def empty_resolver() -> FieldResolver:
    return FieldResolver({}, {})


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
    assert ":LICZBAKIEROWNIKOW := :LISTAKIEROWNIKOW.COUNT;" in desc.plsql_code


def test_describe_create_site_specific_item(empty_resolver: FieldResolver) -> None:
    node = ActionNode(
        type="Nintex.Workflow.Activities.Adapters.NWCreateSiteSpecificItemAdapter",
        enabled=True,
        b_label="Zadania_DORA",
        params={"Output": "NoweZadanieID"},
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
    assert "FOR i IN 1..:KOLEKCJAADRESATOW.COUNT LOOP" in desc.plsql_code


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
    assert "LCDT.SHP_API.get_list_items" in desc.plsql_code
    assert "p_list_title => 'Slownik_Statusow'" in desc.plsql_code
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
    assert "LCDT.SHP_API.update_list_item" in desc.plsql_code
    assert "LCDT.SHP_API.get_list_items" in desc.plsql_code
    assert len(desc.writes) == 1
    assert desc.writes[0].internal_name == "Status"
