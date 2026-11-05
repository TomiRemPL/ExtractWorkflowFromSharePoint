"""Generate Oracle APEX Shared Components > Workflows implementation guides.

Kazdy workflow APEX sklada sie z czterech krokow standardowych (Workflow Start + Additional
Data z NINTEX_PARAMS, Retrieve Payload, Invoke API LCDT.SHP_API.GET_LIST_ITEM, Parse
V_SHP_ANSWER) oraz logiki uzytkownika w jednej z dwoch sciezek:
- sciezka A: jedna aktywnosc APEX na kazda akcje Nintex,
- sciezka B: jedna aktywnosc Execute Code z gotowym kodem PL/SQL.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from .action_catalog import _field_reference_value, _plsql_condition, build_path_b_code, wrap_plsql_block
from .apex_naming import (
    EMAIL_RE,
    P_EMAIL_FROM,
    P_PAYLOAD_BODY,
    SHP_API,
    V_EDITOR,
    V_ITEM_ID,
    V_LIST_TITLE,
    V_SHP_ANSWER,
    V_SITE_URL,
    email_param,
    field_variable,
    identifier,
    is_lookup,
    is_multi,
    is_user,
    sql_literal,
    variable_static_id,
    workflow_static_id,
)
from .metadata_loader import FieldResolver
from .nwf_parser import ActionNode, WorkflowModel

if TYPE_CHECKING:
    from .report_builder import Step

# Zgodnosc wsteczna z wczesniejszymi nazwami pomocniczymi modulu.
_identifier = identifier
_field_variable = field_variable
_variable_static_id = variable_static_id
_sql_literal = sql_literal

NINTEX_PARAMS_VAR_SLOTS = 10
NINTEX_PARAMS_NUM_SLOTS = 10

RETRIEVE_PAYLOAD_CODE = f"""DECLARE
    l_json_text CLOB;
BEGIN
    l_json_text := :{P_PAYLOAD_BODY};
    apex_json.parse(l_json_text);
    :{V_ITEM_ID} := apex_json.get_varchar2(p_path => 'id');
    :{V_SITE_URL} := apex_json.get_varchar2(p_path => 'url_site');
    :{V_LIST_TITLE} := apex_json.get_varchar2(p_path => 'list_name');
    :{V_EDITOR} := apex_json.get_varchar2(p_path => 'updated_by');
    -- Prowokujemy blad, aby flow nie poszedl dalej, tylko skonczyl sie jako FAULTED
    -- W Workflow Console zobaczymy specyficzny blad 20010 z opisem
    IF :{V_ITEM_ID} IS NULL OR :{V_SITE_URL} IS NULL OR :{V_LIST_TITLE} IS NULL OR :{V_EDITOR} IS NULL THEN
        RAISE_APPLICATION_ERROR(-20010, 'Retrieve Payload: Niepoprawny JSON (puste wartosci)');
    END IF;
END;"""


@dataclass
class ApexWorkflowParam:
    static_id: str
    data_type: str
    required: bool
    default_value: str
    description: str


@dataclass
class ApexWorkflowVariable:
    static_id: str
    data_type: str
    role: str
    field_binding: str = ""


@dataclass
class ApexWorkflowTransition:
    condition: str
    target_node_id: str
    target_name: str


@dataclass
class ApexWorkflowActivity:
    node_id: str
    title: str
    activity_type: str
    ui_location: str
    config_notes: list[str] = field(default_factory=list)
    plsql_code: str = ""
    transitions: list[ApexWorkflowTransition] = field(default_factory=list)
    enabled: bool = True
    settings: dict[str, str] = field(default_factory=dict)
    parameter_mapping: list[dict[str, str]] = field(default_factory=list)


@dataclass
class ApexConfigParam:
    alias: str
    column: str
    value: str
    description: str


@dataclass
class ApexAdditionalData:
    sql: str
    merge_sql: str
    params: list[ApexConfigParam]
    notes: list[str] = field(default_factory=list)


@dataclass
class ApexSourceField:
    internal_name: str
    field_type: str
    select: list[str]
    expand: bool
    variables: list[tuple[str, str, str]]  # (static_id, data_type, apex_json path)


@dataclass
class ApexWorkflowSpec:
    name: str
    static_id: str
    category: str
    start_triggers: list[str]
    parameters: list[ApexWorkflowParam]
    variables: list[ApexWorkflowVariable]
    standard_activities: list[ApexWorkflowActivity]
    activities: list[ApexWorkflowActivity]
    path_b: ApexWorkflowActivity
    additional_data: ApexAdditionalData
    shp_query: str
    source_list: str

    def to_dict(self) -> dict:
        return asdict(self)


def _data_type(nintex_type: str) -> str:
    normalized = nintex_type.lower().replace(" ", "")
    if any(token in normalized for token in ("datetime", "timestamp", "time")):
        return "TIMESTAMP"
    if "date" in normalized:
        return "DATE"
    if any(token in normalized for token in ("integer", "number", "decimal", "counter", "currency", "spitemkey")):
        return "NUMBER"
    if any(token in normalized for token in ("memo", "multiline", "clob", "note")):
        return "CLOB"
    return "VARCHAR2"


# --------------------------------------------------------------------------------------------
# Pola biezacego elementu -> p_query (krok 3) i parsowanie V_SHP_ANSWER (krok 4)
# --------------------------------------------------------------------------------------------

_ITEM_PROPERTY_RE = re.compile(r"\{ItemProperty:([^}]+)\}")


def collect_source_fields(actions: list[ActionNode], resolver: FieldResolver) -> dict[str, str]:
    """Zbiera pola biezacego elementu (ThisItemLookup, {ItemProperty:X}) odczytywane przez workflow."""
    fields: dict[str, str] = {}

    def add(name: str | None, field_type: str | None) -> None:
        if not name or name.lower() in ("id", "itemid"):
            return
        fields.setdefault(name, resolver.get_field_type(name) or field_type or "Text")

    def scan_text(text: str | None) -> None:
        for match in _ITEM_PROPERTY_RE.finditer(text or ""):
            add(match.group(1).strip(), "")

    def scan_element(root: ET.Element) -> None:
        for el in root.iter():
            if el.tag in ("ListLookup", "Lookup"):
                lookup_type = el.get("LookupType", "")
                if lookup_type == "ThisItemLookup" or (el.tag == "ListLookup" and not lookup_type and el.find("Lookup") is None):
                    field_el = el.find("Field")
                    if field_el is not None:
                        add(field_el.get("Name"), field_el.get("Type"))
            scan_text(el.text)
            for value in el.attrib.values():
                scan_text(value)

    def walk(nodes: list[ActionNode]) -> None:
        for node in nodes:
            if not node.enabled:
                continue
            if node.raw_el is not None:
                parameters = node.raw_el.find("Parameters")
                if parameters is not None:
                    scan_element(parameters)
            for element in (node.condition_el, *node.param_elements.values()):
                if element is not None:
                    scan_element(element)
            for value in node.params.values():
                scan_text(value)
            if node.type.endswith("NWSendMessageAdapter"):
                add("Editor", "User")
            if node.type.endswith("SPUpdateItemWithKeyAdapter"):
                # Pole zapisywane bez jawnej wartosci trafia do kodu jako :SP_<pole> - musi byc zadeklarowane i pobrane.
                for ref in node.field_refs:
                    if _field_reference_value(node, ref.internal_name) is None:
                        add(ref.internal_name, ref.field_type)
            walk(node.children)

    walk(actions)
    return fields


def _source_field_spec(internal_name: str, field_type: str) -> ApexSourceField:
    base = field_variable(internal_name)
    lowered = field_type.lower()
    if is_user(field_type):
        return ApexSourceField(
            internal_name, field_type,
            [f"{internal_name}/Title", f"{internal_name}/EMail", f"{internal_name}/Name"], True,
            [
                (base, "VARCHAR2", f"data.{internal_name}.Title"),
                (field_variable(internal_name, "EMAIL"), "VARCHAR2", f"data.{internal_name}.EMail"),
                (field_variable(internal_name, "NAME"), "VARCHAR2", f"data.{internal_name}.Name"),
            ],
        )
    if is_lookup(field_type):
        return ApexSourceField(
            internal_name, field_type,
            [f"{internal_name}/Id", f"{internal_name}/Title"], True,
            [
                (base, "VARCHAR2", f"data.{internal_name}.Title"),
                (field_variable(internal_name, "ID"), "NUMBER", f"data.{internal_name}.Id"),
            ],
        )
    if lowered in ("number", "integer", "counter", "currency"):
        data_type = "NUMBER"
    elif lowered == "datetime":
        data_type = "TIMESTAMP WITH TIME ZONE"
    elif lowered == "note":
        data_type = "CLOB"
    else:
        data_type = "VARCHAR2"
    return ApexSourceField(internal_name, field_type, [internal_name], False, [(base, data_type, f"data.{internal_name}")])


def build_shp_query(source_fields: list[ApexSourceField]) -> str:
    select: list[str] = []
    expand: list[str] = []
    for spec in source_fields:
        select.extend(item for item in spec.select if item not in select)
        if spec.expand and spec.internal_name not in expand:
            expand.append(spec.internal_name)
    query = f"$select={','.join(select) if select else 'Id'}"
    if expand:
        query += f"&$expand={','.join(expand)}"
    return query


def _parse_assignment(static_id: str, data_type: str, path: str) -> str:
    if data_type == "NUMBER":
        return f"    :{static_id} := apex_json.get_number(p_path => '{path}');"
    if data_type == "CLOB":
        return f"    :{static_id} := apex_json.get_clob(p_path => '{path}');"
    if data_type.startswith("TIMESTAMP"):
        return (
            f"    :{static_id} := FROM_TZ(TO_TIMESTAMP(apex_json.get_varchar2(p_path => '{path}'), "
            f"'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'), 'UTC');"
        )
    return f"    :{static_id} := apex_json.get_varchar2(p_path => '{path}');"


def build_parse_code(source_fields: list[ApexSourceField]) -> str:
    lines = [
        "DECLARE",
        "    l_json_text CLOB;",
        "BEGIN",
        f"    l_json_text := :{V_SHP_ANSWER};",
        "    apex_json.parse(l_json_text);",
    ]
    for spec in source_fields:
        if is_multi(spec.field_type):
            lines.append(
                f"    -- TODO: {spec.internal_name} ({spec.field_type}) jest wielowartościowe - "
                f"wartości są w data.{spec.internal_name}.results[%d]"
            )
        for static_id, data_type, path in spec.variables:
            lines.append(_parse_assignment(static_id, data_type, path))
    if len(lines) == 5:
        lines.append("    NULL; -- workflow nie odczytuje dodatkowych pól elementu")
    lines.append("END;")
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------
# Additional Data (NINTEX_PARAMS) -> parametry P_
# --------------------------------------------------------------------------------------------

def _collect_config_params(actions: list[ActionNode]) -> list[tuple[str, str, str]]:
    """Zwraca (alias, wartosc, opis) dla stalych konfiguracyjnych wykrytych w workflow."""
    found: dict[str, tuple[str, str, str]] = {}

    def walk(nodes: list[ActionNode]) -> None:
        for node in nodes:
            if node.type.endswith("NWSendMessageAdapter"):
                found.setdefault(P_EMAIL_FROM, (P_EMAIL_FROM, "", "Adres nadawcy wiadomości e-mail (apex_mail p_from)."))
                if node.raw_el is not None:
                    text = ET.tostring(node.raw_el, encoding="unicode")
                    for email in EMAIL_RE.findall(text):
                        alias = email_param(email)
                        found.setdefault(alias, (alias, email, f"Stały adres e-mail użyty w workflow Nintex ({email})."))
            walk(node.children)

    walk(actions)
    return list(found.values())


def build_additional_data(static_id: str, actions: list[ActionNode]) -> ApexAdditionalData:
    detected = _collect_config_params(actions)
    params: list[ApexConfigParam] = []
    notes: list[str] = []
    for index, (alias, value, description) in enumerate(detected, start=1):
        if index > NINTEX_PARAMS_VAR_SLOTS:
            notes.append(f"Brak wolnej kolumny P_VAR_nn dla {alias} - rozszerz tabelę NINTEX_PARAMS.")
            continue
        params.append(ApexConfigParam(alias, f"P_VAR_{index:02d}", value, description))

    if params:
        select_list = ",\n       ".join(f"p.{param.column} AS {param.alias}" for param in params)
        sql = (
            f"SELECT {select_list}\n"
            "  FROM nintex_params p\n"
            "  JOIN apex_workflows w\n"
            "    ON w.workflow_def_static_id = p.workflow_static_id\n"
            " WHERE w.workflow_id = :APEX$WORKFLOW_ID"
        )
        # Puste wartosci (np. nadawca) uzupelnia administrator - ponowne uruchomienie skryptu nie moze ich nadpisac.
        known = [param for param in params if param.value]
        assignments = ",\n            ".join(f"t.{param.column.lower()} = {sql_literal(param.value)}" for param in known)
        matched = f" WHEN MATCHED THEN UPDATE SET\n            {assignments}\n" if known else ""
        columns = ", ".join(param.column.lower() for param in params)
        values = ", ".join(sql_literal(param.value) for param in params)
        merge_sql = (
            "MERGE INTO nintex_params t\n"
            f"USING (SELECT {sql_literal(static_id)} AS workflow_static_id FROM dual) s\n"
            "   ON (t.workflow_static_id = s.workflow_static_id)\n"
            f"{matched}"
            " WHEN NOT MATCHED THEN INSERT (workflow_static_id, " + columns + ")\n"
            f"      VALUES (s.workflow_static_id, {values});"
        )
        if any(not param.value for param in params):
            notes.append("Uzupełnij puste wartości w MERGE (np. adres nadawcy) przed uruchomieniem workflow.")
    else:
        sql = ""
        merge_sql = (
            "MERGE INTO nintex_params t\n"
            f"USING (SELECT {sql_literal(static_id)} AS workflow_static_id FROM dual) s\n"
            "   ON (t.workflow_static_id = s.workflow_static_id)\n"
            " WHEN NOT MATCHED THEN INSERT (workflow_static_id) VALUES (s.workflow_static_id);"
        )
        notes.append(
            "Workflow nie używa stałych konfiguracyjnych - pozostaw Additional Data puste "
            "(albo dodaj zapytanie, gdy pojawią się parametry P_)."
        )
    notes.append("Parametry P_ są niezmienne w czasie trwania przepływu; zmienne V_ i SP_ mogą się zmieniać.")
    return ApexAdditionalData(sql=sql, merge_sql=merge_sql, params=params, notes=notes)


# --------------------------------------------------------------------------------------------
# Zmienne workflow
# --------------------------------------------------------------------------------------------

def _extract_variables(actions: list[ActionNode]) -> dict[str, ApexWorkflowVariable]:
    variables: dict[str, ApexWorkflowVariable] = {}

    def register(name: str, data_type: str, role: str, overwrite: bool = False) -> None:
        if name and (overwrite or name not in variables):
            variables[name] = ApexWorkflowVariable(variable_static_id(name), data_type, role)

    def walk(nodes: list[ActionNode]) -> None:
        for node in nodes:
            if node.type.endswith("SPSetVariableAdapter"):
                variable = node.param_elements.get("VariableName")
                if variable is not None and variable.get("Name"):
                    register(
                        variable.get("Name", ""),
                        _data_type(variable.get("Type", "Text")),
                        variable.get("Description") or node.t_label or "Zmienna workflow Nintex",
                        overwrite=True,
                    )
            if node.raw_el is not None:
                for ref in node.raw_el.iter("FieldReference"):
                    for child in ref:
                        if child.tag == "Variable" and child.get("Name"):
                            register(child.get("Name", ""), _data_type(child.get("Type", "Text")), "Zmienna workflow Nintex zapisywana do pola SharePoint")
            for value in node.params.values():
                for match in re.finditer(r"\{WorkflowVariable:([^}]+)\}", value):
                    register(match.group(1).strip(), "VARCHAR2", "Zmienna używana w wyrażeniu workflow")
            walk(node.children)

    walk(actions)
    return variables


def _standard_variables() -> list[ApexWorkflowVariable]:
    return [
        ApexWorkflowVariable(V_ITEM_ID, "NUMBER", "ID elementu SharePoint (payload: id)"),
        ApexWorkflowVariable(V_SITE_URL, "VARCHAR2", "Adres witryny SharePoint (payload: url_site)"),
        ApexWorkflowVariable(V_LIST_TITLE, "VARCHAR2", "Tytuł listy źródłowej (payload: list_name)"),
        ApexWorkflowVariable(V_EDITOR, "VARCHAR2", "Autor ostatniej zmiany (payload: updated_by)"),
        ApexWorkflowVariable(V_SHP_ANSWER, "CLOB", f"Odpowiedź {SHP_API}.GET_LIST_ITEM (krok 3)"),
    ]


# --------------------------------------------------------------------------------------------
# Aktywnosci
# --------------------------------------------------------------------------------------------

def _standard_activities(
    additional_data: ApexAdditionalData,
    source_list: str,
    shp_query: str,
    parse_code: str,
) -> list[ApexWorkflowActivity]:
    start_notes = [
        "Workflow > Additional Data > Type: SQL Query; kolumny zapytania stają się parametrami P_ "
        "(bind :P_xxx / substytucja &P_xxx.).",
        *additional_data.notes,
    ]
    get_item_mapping = [
        {"parameter": "p_site_url", "source": "Workflow Variable", "value": V_SITE_URL},
        {"parameter": "p_list_title", "source": "Workflow Variable", "value": V_LIST_TITLE},
        {"parameter": "p_item_id", "source": "Workflow Variable", "value": V_ITEM_ID},
        {"parameter": "p_query", "source": "Static Value", "value": shp_query},
        {"parameter": "p_raise_on_error", "source": "Default", "value": "'Y'"},
        {"parameter": "Function Result", "source": "Workflow Variable", "value": V_SHP_ANSWER},
    ]
    return [
        ApexWorkflowActivity(
            node_id="std_start",
            title="Workflow Start + Additional Data",
            activity_type="Workflow Start",
            ui_location="Workflow > Additional Data > SQL Query",
            config_notes=start_notes,
            plsql_code=additional_data.sql,
            transitions=[ApexWorkflowTransition("Next", "std_payload", "Retrieve Payload")],
        ),
        ApexWorkflowActivity(
            node_id="std_payload",
            title="Retrieve Payload",
            activity_type="Execute Code",
            ui_location="Activity Properties > Code > PL/SQL Code",
            config_notes=[
                f"Rozparsowuje standardowy payload SharePoint (:{P_PAYLOAD_BODY}) na zmienne V_.",
                "Błąd -20010 kończy instancję jako FAULTED; komunikat widać w Workflow Console.",
            ],
            plsql_code=RETRIEVE_PAYLOAD_CODE,
            transitions=[ApexWorkflowTransition("Next", "std_get_item", "GET_LIST_ITEM")],
        ),
        ApexWorkflowActivity(
            node_id="std_get_item",
            title="GET_LIST_ITEM",
            activity_type="Invoke API",
            ui_location="Activity Properties > Settings > Type: PL/SQL Package",
            config_notes=[
                f"Lista źródłowa: {source_list}. p_query jest jedynym parametrem wpisywanym ręcznie.",
                "$select wskazuje pobierane pola; $expand pobiera pola złożone (User/Lookup) "
                "bez dodatkowego zapytania do listy słownikowej.",
            ],
            plsql_code=(
                "-- Odpowiednik konfiguracji Invoke API:\n"
                f":{V_SHP_ANSWER} := {SHP_API}.get_list_item(\n"
                f"    p_site_url   => :{V_SITE_URL},\n"
                f"    p_list_title => :{V_LIST_TITLE},\n"
                f"    p_item_id    => :{V_ITEM_ID},\n"
                f"    p_query      => {sql_literal(shp_query)}\n"
                ");"
            ),
            settings={"Owner": "LCDT", "Package": "SHP_API", "Function": "GET_LIST_ITEM"},
            parameter_mapping=get_item_mapping,
            transitions=[ApexWorkflowTransition("Next", "std_parse", "Parse V_SHP_ANSWER")],
        ),
        ApexWorkflowActivity(
            node_id="std_parse",
            title="Parse V_SHP_ANSWER",
            activity_type="Execute Code",
            ui_location="Activity Properties > Code > PL/SQL Code",
            config_notes=["Rozparsowuje odpowiedź GET_LIST_ITEM (envelope {success, data}) na zmienne SP_."],
            plsql_code=parse_code,
        ),
    ]


def _step_activity(step: Step, resolver: FieldResolver) -> tuple[str, str, str, list[str]]:
    node = step.node
    short_type = node.type.rsplit(".", 1)[-1]
    notes: list[str] = []
    if not node.enabled:
        notes.append("Krok wyłączony w źródłowym workflow; nie aktywuj go bez potwierdzenia reguły biznesowej.")

    if short_type in {"WFIfElseAdapter", "NWRunIf2Adapter"}:
        notes.append("Utwórz przejścia dla prawdy/fałszu; mapuj je na gałęzie Nintex.")
        if short_type == "NWRunIf2Adapter":
            notes.append("Nintex ma tylko gałąź warunkową; skonfiguruj przejście domyślne jako pominięcie akcji.")
        return (
            "Switch",
            "Activity Properties > Settings > Switch Type: True False Check (PL/SQL Expression)",
            _plsql_condition(node.condition_el, resolver),
            notes,
        )

    if short_type == "NWDelayForAdapter":
        days = int(node.params.get("Days") or 0)
        hours = int(node.params.get("Hours") or 0)
        minutes = int(node.params.get("Minutes") or 0)
        total_minutes = days * 1440 + hours * 60 + minutes or 5
        notes.append(f"Ustaw czas oczekiwania na {total_minutes} minut; nie używaj DBMS_SESSION.SLEEP.")
        return "Wait", "Activity Properties > Settings > Wait Duration", "", notes

    if short_type == "NWSendMessageAdapter":
        notes.append(f"From: &{P_EMAIL_FROM}. (parametr z NINTEX_PARAMS); To/Subject/Body we właściwościach aktywności.")
        if node.raw_el is not None:
            subject = node.raw_el.find(".//Message/Subject")
            if subject is not None and subject.text:
                notes.append(f"Temat źródłowy: {subject.text}")
        notes.append("Alternatywnie użyj Execute Code z kodem apex_mail.send poniżej.")
        return "Send E-Mail", "Activity Properties > Settings > Email Attributes", wrap_plsql_block(step.desc.plsql_code), notes

    if short_type == "NWStartWorkflow2Adapter":
        notes.append("Wskaż workflow podrzędny (Invoke Workflow / Sub-Workflow) i przekaż P_PAYLOAD_BODY.")
        notes.append("Ustaw oczekiwanie zgodnie z parametrem WaitForComplete.")
        return "Invoke Workflow", "Activity Properties > Settings > Workflow", step.desc.plsql_code, notes

    if short_type == "NWBusinessProcessAdapter":
        notes.append("Etap biznesowy Nintex odwzoruj jako nazwę aktywności lub grupę kroków.")

    code = step.desc.plsql_code
    if not code:
        notes.append(f"Sprawdź semantykę akcji Nintex {short_type} i uzupełnij kod przed aktywacją.")
        code = f"-- TODO: implement Nintex action {short_type}"
    return "Execute Code", "Activity Properties > Code > PL/SQL Code", wrap_plsql_block(code), notes


def _transition_graph(
    nodes: list[ActionNode],
    activities_by_node: dict[int, ApexWorkflowActivity],
) -> None:

    def edge(source: ApexWorkflowActivity, target: ApexWorkflowActivity, condition: str) -> None:
        transition = ApexWorkflowTransition(condition, target.node_id, target.title)
        if transition not in source.transitions:
            source.transitions.append(transition)

    def walk(
        action_nodes: list[ActionNode],
        incoming: list[tuple[ApexWorkflowActivity, str]],
    ) -> list[ApexWorkflowActivity]:
        current = incoming
        for node in action_nodes:
            short_type = node.type.rsplit(".", 1)[-1]
            activity = activities_by_node.get(id(node))
            if short_type in {"WFSequenceAdapter", "WFParallelAdapter", "WFIfElseBranchAdapter"}:
                current = [(end, label) for end in walk(node.children, current) for _, label in current] if node.children else current
                continue
            if activity is None:
                current = [(end, label) for end in walk(node.children, current)] if node.children else current
                continue
            for source, label in current:
                edge(source, activity, label or "Next")
            if short_type in {"WFIfElseAdapter", "NWRunIf2Adapter"} and node.children:
                branch_ends: list[ApexWorkflowActivity] = []
                for index, branch in enumerate(node.children):
                    label = branch.branch_label or ("False" if index == 0 else "True")
                    branch_ends.extend(walk(branch.children or [branch], [(activity, label)]))
                current = [(end, "Next") for end in branch_ends] or [(activity, "Next")]
                continue
            if node.children:
                current = [(end, "Next") for end in walk(node.children, [(activity, "Next")])]
            else:
                current = [(activity, "Next")]
        return [end for end, _ in current]

    walk(nodes, [])


def generate_apex_workflow_spec(
    wf: WorkflowModel,
    steps: list[Step],
    resolver: FieldResolver,
) -> ApexWorkflowSpec:
    """Build the workflow definition and designer instructions for one parsed Nintex workflow."""
    title = wf.title or wf.source_path.stem
    static_id = workflow_static_id(title)
    source = wf.source_list
    source_list = source.list_name if source else resolver.get_list_name()

    source_fields = [_source_field_spec(name, ftype) for name, ftype in collect_source_fields(wf.actions, resolver).items()]
    shp_query = build_shp_query(source_fields)
    additional_data = build_additional_data(static_id, wf.actions)

    variables: list[ApexWorkflowVariable] = _standard_variables()
    used_ids = {variable.static_id for variable in variables}
    for spec in source_fields:
        for var_id, data_type, path in spec.variables:
            if var_id not in used_ids:
                used_ids.add(var_id)
                variables.append(ApexWorkflowVariable(var_id, data_type, f"Pole SharePoint ({path})", spec.internal_name))
    for variable in _extract_variables(wf.actions).values():
        if variable.static_id not in used_ids:
            used_ids.add(variable.static_id)
            variables.append(variable)

    parameters = [
        ApexWorkflowParam(P_PAYLOAD_BODY, "CLOB", True, "", "Oryginalny payload JSON z wyzwalacza SharePoint (workflow.xaml)."),
    ]

    standard = _standard_activities(additional_data, source_list, shp_query, build_parse_code(source_fields))

    activities: list[ApexWorkflowActivity] = []
    activity_by_node: dict[int, ApexWorkflowActivity] = {}
    for step in steps:
        short_type = step.node.type.rsplit(".", 1)[-1]
        if step.desc.is_structural or short_type == "NWWorkflowVariablesAdapter":
            continue
        activity_type, ui_location, code, notes = _step_activity(step, resolver)
        activity = ApexWorkflowActivity(
            node_id=step.node_id,
            title=step.desc.label or step.node.t_label or step.desc.summary or short_type,
            activity_type=activity_type,
            ui_location=ui_location,
            config_notes=notes,
            plsql_code=code,
            enabled=step.node.enabled,
        )
        activities.append(activity)
        activity_by_node[id(step.node)] = activity
    _transition_graph(wf.actions, activity_by_node)

    end_activity = ApexWorkflowActivity(
        node_id="stop",
        title="Koniec workflow",
        activity_type="Workflow End",
        ui_location="Workflow Designer > End Activity",
        config_notes=["Połącz z tym węzłem wszystkie końcowe ścieżki procesu (End State: Completed)."],
    )
    for activity in activities:
        if not activity.transitions:
            activity.transitions.append(ApexWorkflowTransition("End", "stop", end_activity.title))
    first_target = activities[0] if activities else end_activity
    standard[-1].transitions.append(ApexWorkflowTransition("Ścieżka A", first_target.node_id, first_target.title))
    activities.append(end_activity)

    path_b = ApexWorkflowActivity(
        node_id="path_b",
        title="Logika workflow (ścieżka B)",
        activity_type="Execute Code",
        ui_location="Activity Properties > Code > PL/SQL Code",
        config_notes=[
            "Ścieżka B: po kroku 'Parse V_SHP_ANSWER' dodaj jedną aktywność Execute Code z poniższym kodem, "
            "a następnie Workflow End.",
            "Akcje Wait/Send E-Mail/Invoke Workflow z Nintex możesz wydzielić do osobnych aktywności natywnych.",
        ],
        plsql_code=build_path_b_code(wf.actions, resolver, title),
        transitions=[ApexWorkflowTransition("Next", "stop", end_activity.title)],
    )

    trigger_action = next(
        (node for node in wf.actions if node.type.endswith("NWWorkflowVariablesAdapter")),
        None,
    )
    start_triggers = [
        name
        for key, name in (
            ("StartManually", "ręczny"),
            ("StartOnCreate", "utworzenie elementu"),
            ("StartOnChange", "zmiana elementu"),
        )
        if trigger_action is not None and trigger_action.params.get(key, "").lower() == "true"
    ]

    return ApexWorkflowSpec(
        name=f"WF {title}",
        static_id=static_id,
        category="SharePoint / Nintex migration",
        start_triggers=start_triggers or ["ręczny (domyślny)"],
        parameters=parameters,
        variables=variables,
        standard_activities=standard,
        activities=activities,
        path_b=path_b,
        additional_data=additional_data,
        shp_query=shp_query,
        source_list=source_list,
    )


# --------------------------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------------------------

def _format_activity(lines: list[str], heading: str, activity: ApexWorkflowActivity) -> None:
    lines.extend([
        f"#### {heading}. {activity.title} (`{activity.node_id}`)",
        "",
        f"- **Activity Type:** {activity.activity_type}",
        f"- **Miejsce konfiguracji:** {activity.ui_location}",
    ])
    for key, value in activity.settings.items():
        lines.append(f"- **{key}:** `{value}`")
    for note in activity.config_notes:
        lines.append(f"- **Konfiguracja:** {note}")
    if activity.parameter_mapping:
        lines.extend(["", "| Parametr | Źródło | Wartość |", "|---|---|---|"])
        for mapping in activity.parameter_mapping:
            lines.append(f"| `{mapping['parameter']}` | {mapping['source']} | `{mapping['value']}` |")
        lines.append("")
    if activity.transitions:
        lines.append("- **Transitions:**")
        for transition in activity.transitions:
            lines.append(
                f"  - {transition.condition or 'Next'} → `{transition.target_node_id}` ({transition.target_name})"
            )
    if activity.plsql_code:
        fence = "```sql" if activity.activity_type == "Workflow Start" else (
            "```plsql" if activity.activity_type in {"Execute Code", "Invoke API", "Send E-Mail", "Invoke Workflow"} else "```text"
        )
        lines.extend(["", fence, activity.plsql_code, "```"])
    lines.append("")


def format_markdown_apex_section(spec: ApexWorkflowSpec) -> str:
    lines = [
        "## Przygotowanie workflow w Oracle APEX (Shared Components > Workflows)",
        "",
        f"- **Name:** {spec.name}",
        f"- **Static ID:** `{spec.static_id}`",
        f"- **Category:** {spec.category}",
        f"- **Lista źródłowa:** {spec.source_list}",
        f"- **Wyzwalacze źródłowe:** {', '.join(spec.start_triggers)} — w APEX instancję uruchamia "
        "`pkg_shp_dispatcher` (`apex_workflow.start_workflow`) po wywołaniu z SharePoint (workflow.xaml).",
        "",
        "### Workflow Parameters",
        "",
        "| Static ID | Typ | Wymagany | Domyślna wartość | Opis |",
        "|---|---|---|---|---|",
    ]
    for param in spec.parameters:
        lines.append(
            f"| `{param.static_id}` | {param.data_type} | {'Tak' if param.required else 'Nie'} "
            f"| {param.default_value or '—'} | {param.description} |"
        )
    lines.extend(["", "### Additional Data (NINTEX_PARAMS → parametry P_)", ""])
    if spec.additional_data.params:
        lines.extend(["| Parametr | Kolumna NINTEX_PARAMS | Wartość | Opis |", "|---|---|---|---|"])
        for param in spec.additional_data.params:
            lines.append(f"| `{param.alias}` | `{param.column}` | {param.value or '_(uzupełnij)_'} | {param.description} |")
        lines.extend(["", "Zapytanie **Workflow > Additional Data > SQL Query**:", "", "```sql", spec.additional_data.sql, "```", ""])
    for note in spec.additional_data.notes:
        lines.append(f"- {note}")
    lines.extend(["", "Konfiguracja wiersza w `NINTEX_PARAMS` (także w `nintex_params.sql`):", "", "```sql", spec.additional_data.merge_sql, "```", ""])

    lines.extend(["### Workflow Variables", "", "| Static ID | Typ | Rola / mapowanie |", "|---|---|---|"])
    for variable in spec.variables:
        binding = f"`{variable.field_binding}` — " if variable.field_binding else ""
        lines.append(f"| `{variable.static_id}` | {variable.data_type} | {binding}{variable.role} |")
    lines.extend([
        "",
        "> W kodzie aktywności używaj bindów `:STATIC_ID` dla parametrów i zmiennych workflow. "
        "Nie używaj `apex_workflow.get_variable` / `set_variable`: nie są to udokumentowane API APEX 24.2. "
        "`GET_VARIABLE_VALUE` wymaga `p_instance_id`, a `UPDATE_VARIABLES` dotyczy instancji zawieszonych "
        "lub błędnych i wymaga roli administratora.",
        "",
        "### Kroki standardowe (1–4)",
        "",
        f"Każdy workflow zaczyna się tymi samymi czterema krokami. `p_query` dla `{SHP_API}.GET_LIST_ITEM`: "
        f"`{spec.shp_query}`.",
        "",
    ])
    for index, activity in enumerate(spec.standard_activities, start=1):
        _format_activity(lines, str(index), activity)

    lines.extend([
        "### Ścieżka A — odwzorowanie krok po kroku",
        "",
        "Po kroku 4 dodaj aktywności odpowiadające akcjom Nintex (kod korzysta z bindów `:V_*`, `:SP_*`, `:P_*`).",
        "",
    ])
    for index, activity in enumerate(spec.activities, start=1):
        _format_activity(lines, f"A{index}", activity)

    lines.extend([
        "### Ścieżka B — jedna aktywność Execute Code",
        "",
        "Zamiast ścieżki A dodaj po kroku 4 jedną aktywność z gotowym kodem wywołującym funkcje "
        f"`{SHP_API}`, a następnie `Workflow End`.",
        "",
    ])
    _format_activity(lines, "B1", spec.path_b)
    return "\n".join(lines)


def build_nintex_params_script(specs: list[dict]) -> str:
    """Skrypt SQL: definicja tabeli NINTEX_PARAMS i wiersze MERGE dla wszystkich workflow."""
    var_columns = ",\n".join(f"    p_var_{i:02d}            VARCHAR2(4000)" for i in range(1, NINTEX_PARAMS_VAR_SLOTS + 1))
    num_columns = ",\n".join(f"    p_num_{i:02d}            NUMBER" for i in range(1, NINTEX_PARAMS_NUM_SLOTS + 1))
    parts = [
        "-- Parametry konfiguracyjne workflow APEX (Workflow > Additional Data -> parametry P_).",
        "-- Uruchom DDL jednorazowo, jeżeli tabela NINTEX_PARAMS jeszcze nie istnieje.",
        "/*",
        "CREATE TABLE nintex_params (",
        "    workflow_static_id VARCHAR2(255) NOT NULL,",
        f"{var_columns},",
        f"{num_columns},",
        "    CONSTRAINT nintex_params_pk PRIMARY KEY (workflow_static_id)",
        ");",
        "*/",
        "",
    ]
    for spec in specs:
        additional = spec.get("additional_data", {})
        parts.append(f"-- {spec.get('name', '')} ({spec.get('static_id', '')})")
        parts.append(additional.get("merge_sql", ""))
        parts.append("")
    parts.append("COMMIT;")
    return "\n".join(parts) + "\n"
