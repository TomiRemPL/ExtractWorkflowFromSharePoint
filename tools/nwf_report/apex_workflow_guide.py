"""Generate Oracle APEX Shared Components > Workflows implementation guides."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING
from xml.etree import ElementTree as ET

from .metadata_loader import FieldResolver
from .nwf_parser import ActionNode, WorkflowModel

if TYPE_CHECKING:
    from .report_builder import Step


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


@dataclass
class ApexWorkflowSpec:
    name: str
    static_id: str
    category: str
    start_triggers: list[str]
    parameters: list[ApexWorkflowParam]
    variables: list[ApexWorkflowVariable]
    activities: list[ApexWorkflowActivity]

    def to_dict(self) -> dict:
        return asdict(self)


def _identifier(value: str, prefix: str = "", max_length: int = 120) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    clean = re.sub(r"[^A-Za-z0-9]+", "_", ascii_value).strip("_").upper()
    clean = re.sub(r"_+", "_", clean)
    if not clean:
        clean = "WORKFLOW"
    if clean[0].isdigit():
        clean = f"_{clean}"
    return f"{prefix}{clean}"[:max_length]


def _data_type(nintex_type: str) -> str:
    normalized = nintex_type.lower().replace(" ", "")
    if any(token in normalized for token in ("datetime", "timestamp", "time")):
        return "TIMESTAMP"
    if "date" in normalized:
        return "DATE"
    if any(token in normalized for token in ("integer", "number", "decimal", "counter")):
        return "NUMBER"
    if any(token in normalized for token in ("memo", "multiline", "clob")):
        return "CLOB"
    return "VARCHAR2"


def _field_variable(internal_name: str) -> str:
    return _identifier(internal_name, "SP_")


def _variable_static_id(name: str) -> str:
    return _identifier(name)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _bind_expression(value: str) -> str:
    pattern = re.compile(r"\{(ItemProperty|WorkflowVariable):([^}]+)\}")
    parts: list[str] = []
    offset = 0
    for match in pattern.finditer(value):
        if match.start() > offset:
            parts.append(_sql_literal(value[offset:match.start()]))
        token_type = match.group(1)
        name = match.group(2).strip()
        if token_type == "ItemProperty":
            parts.append(":P_ITEM_ID" if name.lower() in {"id", "itemid"} else f":{_field_variable(name)}")
        else:
            parts.append(f":{_variable_static_id(name)}")
        offset = match.end()
    if offset < len(value):
        parts.append(_sql_literal(value[offset:]))
    if not parts:
        return "NULL"
    return " || ".join(parts)


def _extract_variables(actions: list[ActionNode]) -> dict[str, ApexWorkflowVariable]:
    variables: dict[str, ApexWorkflowVariable] = {}

    def walk(nodes: list[ActionNode]) -> None:
        for node in nodes:
            if node.type.endswith("SPSetVariableAdapter"):
                variable = node.param_elements.get("VariableName")
                if variable is not None and variable.get("Name"):
                    name = variable.get("Name", "")
                    variables[name] = ApexWorkflowVariable(
                        static_id=_variable_static_id(name),
                        data_type=_data_type(variable.get("Type", "Text")),
                        role=variable.get("Description") or node.t_label or "Zmienna workflow Nintex",
                    )
            for value in node.params.values():
                for match in re.finditer(r"\{WorkflowVariable:([^}]+)\}", value):
                    name = match.group(1).strip()
                    variables.setdefault(
                        name,
                        ApexWorkflowVariable(
                            static_id=_variable_static_id(name),
                            data_type="VARCHAR2",
                            role="Zmienna używana w wyrażeniu workflow",
                        ),
                    )
            walk(node.children)

    walk(actions)
    return variables


def _field_variables(steps: list[Step]) -> dict[str, ApexWorkflowVariable]:
    fields: dict[str, ApexWorkflowVariable] = {}
    for step in steps:
        for field_ref in step.desc.reads + step.desc.writes:
            if field_ref.internal_name:
                fields.setdefault(
                    field_ref.internal_name,
                    ApexWorkflowVariable(
                        static_id=_field_variable(field_ref.internal_name),
                        data_type=_data_type(field_ref.field_type),
                        role="Wartość pola SharePoint używana lub ustawiana w kroku",
                        field_binding=field_ref.internal_name,
                    ),
                )
    return fields


def _condition_value(value: ET.Element | None) -> str:
    if value is None:
        return "NULL"
    if value.tag == "PrimitiveValue":
        return _bind_expression(value.get("Value", ""))
    if value.tag == "Variable":
        return f":{_variable_static_id(value.get('Name', ''))}"
    if value.tag == "ListLookup":
        field = value.find("Field")
        name = field.get("Name", "") if field is not None else ""
        return f":{_field_variable(name)}" if name else "NULL"
    return "NULL"


def _switch_expression(condition: ET.Element | None) -> str:
    if condition is None:
        return "TRUE"
    xsi_type = condition.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
    if xsi_type == "ConditionPair":
        operator = {"And": "AND", "Or": "OR"}.get(condition.get("Operator", ""), "AND")
        left = _switch_expression(condition.find("Left"))
        right = _switch_expression(condition.find("Right"))
        return f"({left}) {operator} ({right})"
    if xsi_type != "NWConditionConfig":
        return "TRUE"

    params_el = condition.find("Params")
    params = {param.get("Name", ""): param for param in params_el.findall("Param")} if params_el is not None else {}
    op_el = params.get("operator")
    op_value = op_el.find("PrimitiveValue") if op_el is not None else None
    operator = op_value.get("Value", "") if op_value is not None else ""
    left = _condition_value(next(iter(params["left"]), None)) if "left" in params else "NULL"
    right = _condition_value(next(iter(params["right"]), None)) if "right" in params else "NULL"
    operators = {
        "Equal": f"{left} = {right}",
        "NotEqual": f"{left} <> {right}",
        "GreaterThan": f"{left} > {right}",
        "LessThan": f"{left} < {right}",
        "GreaterThanOrEqual": f"{left} >= {right}",
        "LessThanOrEqual": f"{left} <= {right}",
        "Contains": f"INSTR({left}, {right}) > 0",
        "NotContains": f"INSTR({left}, {right}) = 0",
        "IsEmpty": f"{left} IS NULL",
        "IsNotEmpty": f"{left} IS NOT NULL",
        "IsNull": f"{left} IS NULL",
        "IsNotNull": f"{left} IS NOT NULL",
    }
    return operators.get(operator, f"{left} = {right}")


def _lookup_code(
    value: ET.Element,
    variable_id: str,
    wf: WorkflowModel,
    resolver: FieldResolver,
) -> str:
    lookup_type = value.get("LookupType", "")
    field_el = value.find("Field")
    target_field = field_el.get("Name", "") if field_el is not None else ""
    source = wf.source_list
    source_name = source.list_name if source else resolver.get_list_name()
    source_name_lit = _sql_literal(source_name)

    if lookup_type != "CrossItemLookup":
        return f"""DECLARE
    l_item_json CLOB;
BEGIN
    l_item_json := shp_api.get_list_item(
        p_site_url   => :P_SITE_URL,
        p_list_title => :P_LIST_TITLE,
        p_item_id    => :P_ITEM_ID
    );
    :{variable_id} := json_value(l_item_json, '$.data.{target_field}');
END;"""

    nested_lookup = value.find("Lookup")
    nested_field = nested_lookup.find("Field") if nested_lookup is not None else None
    lookup_field = nested_field.get("Name", "ID") if nested_field is not None else "ID"
    target_list_el = value.find("ListId")
    target_list_id = target_list_el.text if target_list_el is not None else ""
    target_list_name = resolver.get_list_name(target_list_id)
    target_list_lit = _sql_literal(target_list_name)
    return f"""DECLARE
    l_item_json CLOB;
    l_ref_json CLOB;
    l_ref_id NUMBER;
BEGIN
    l_item_json := shp_api.get_list_item(
        p_site_url   => :P_SITE_URL,
        p_list_title => {source_name_lit},
        p_item_id    => :P_ITEM_ID
    );
    l_ref_id := json_value(l_item_json, '$.data.{lookup_field}' RETURNING NUMBER);
    l_ref_json := shp_api.get_list_item(
        p_site_url   => :P_SITE_URL,
        p_list_title => {target_list_lit},
        p_item_id    => l_ref_id
    );
    :{variable_id} := json_value(l_ref_json, '$.data.{target_field}');
END;"""


def _step_code(step: Step, wf: WorkflowModel, resolver: FieldResolver) -> tuple[str, str, str, list[str]]:
    node = step.node
    short_type = node.type.rsplit(".", 1)[-1]
    title = step.desc.label or node.t_label or step.desc.summary or short_type
    notes: list[str] = []
    if not node.enabled:
        notes.append("Krok wyłączony w źródłowym workflow; nie aktywuj go bez potwierdzenia reguły biznesowej.")

    if short_type in {"WFIfElseAdapter", "NWRunIf2Adapter"}:
        expression = _switch_expression(node.condition_el)
        notes.append("Utwórz przejścia dla prawdy/fałszu; mapuj je na gałęzie Nintex.")
        if short_type == "NWRunIf2Adapter":
            notes.append("Nintex ma tylko gałąź warunkową; skonfiguruj przejście domyślne jako pominięcie akcji.")
        return (
            "Switch",
            "Activity Properties > Settings > Switch Condition (PL/SQL Expression)",
            expression,
            notes,
        )

    if short_type == "NWDelayForAdapter":
        days = int(node.params.get("Days") or 0)
        hours = int(node.params.get("Hours") or 0)
        minutes = int(node.params.get("Minutes") or 0)
        total_minutes = days * 1440 + hours * 60 + minutes
        if not total_minutes:
            total_minutes = 5
        notes.append(f"Ustaw czas oczekiwania na {total_minutes} minut; nie używaj DBMS_SESSION.SLEEP.")
        return "Wait", "Activity Properties > Settings > Wait Duration", "", notes

    if short_type == "NWSendMessageAdapter":
        notes.append("Ustaw To, From, Subject i Body we właściwościach aktywności.")
        raw_el = node.raw_el
        if raw_el is not None:
            subject = raw_el.find(".//Message/Subject")
            if subject is not None and subject.text:
                notes.append(f"Temat źródłowy: {subject.text}")
        return "Send E-Mail", "Activity Properties > Settings > Email Attributes", "", notes

    if short_type == "NWStartWorkflow2Adapter":
        child_name = node.params.get("AssociationId") or node.b_label or "Podworkflow"
        notes.append(f"Wskaż workflow podrzędny o identyfikatorze: {child_name}.")
        notes.append("Przekaż wymagane parametry; ustaw oczekiwanie zgodnie z WaitForComplete.")
        return "Sub-Workflow", "Activity Properties > Settings > Workflow", "", notes

    if short_type == "NWWorkflowVariablesAdapter":
        return "Execute Code", "Definicja workflow > Parameters / Workflow Variables", "", [
            "Wyzwalacze Nintex skonfiguruj w Page Process lub Automation uruchamiającym instancję APEX."
        ]

    if short_type == "SPSetVariableAdapter":
        variable = node.param_elements.get("VariableName")
        value = node.param_elements.get("Value")
        name = variable.get("Name", "") if variable is not None else ""
        target = _variable_static_id(name)
        if value is not None and value.tag == "ListLookup":
            code = _lookup_code(value, target, wf, resolver)
            notes.append("Skonfiguruj zmienną workflow o Static ID zgodnym z nazwą po prawej stronie.")
        elif value is not None and value.tag == "Variable":
            source_id = _variable_static_id(value.get("Name", ""))
            code = f"BEGIN\n    :{target} := :{source_id};\nEND;"
        elif value is not None and value.tag == "PrimitiveValue":
            expr = _bind_expression(value.get("Value", ""))
            code = f"BEGIN\n    :{target} := {expr};\nEND;"
        else:
            code = f"BEGIN\n    :{target} := NULL;\nEND;"
        notes.append("Wewnątrz Execute Code czytaj i zapisuj zmienne workflow przez bindy :STATIC_ID.")
        return "Execute Code", "Activity Properties > PL/SQL Code", code, notes

    if short_type in {"SPUpdateItemWithKeyAdapter", "SPSetFieldWithKeyAdapter"}:
        list_id = node.params.get("ListId", "")
        list_name = resolver.get_list_name(list_id) if list_id else (wf.source_list.list_name if wf.source_list else "")
        if short_type == "SPSetFieldWithKeyAdapter":
            field_name = node.params.get("LookupField", "")
            raw_value = node.params.get("LookupFieldValue", "")
            field_refs = [(field_name, _bind_expression(raw_value))]
        else:
            field_refs = [
                (field.internal_name, f":{_field_variable(field.internal_name)}")
                for field in node.field_refs
                if field.internal_name
            ]
        if field_refs:
            pairs = ",\n        ".join(
                f"{_sql_literal(field_name)} VALUE {expression}" for field_name, expression in field_refs
            )
            code = f"""DECLARE
    l_response CLOB;
BEGIN
    l_response := shp_api.update_list_item(
        p_site_url    => :P_SITE_URL,
        p_list_title  => {_sql_literal(list_name)},
        p_item_id     => :P_ITEM_ID,
        p_fields_json => json_object(
        {pairs}
        )
    );
END;"""
        else:
            code = "-- TODO: map the Nintex field values to APEX workflow variables."
        notes.append(f"Potwierdź docelową listę ({list_name}) oraz mapowanie wartości pól.")
        notes.append("Dla aktualizacji cross-list potwierdź, że P_ITEM_ID wskazuje właściwy element docelowy.")
        notes.append("Utwórz zmienne SP_<InternalName> dla wartości w JSON_OBJECT.")
        return "Execute Code", "Activity Properties > PL/SQL Code", code, notes

    if short_type == "NWWriteToHistoryListAdapter":
        message = node.params.get("Message", "")
        code = f"BEGIN\n    apex_debug.info({_sql_literal(message)});\nEND;"
        return "Execute Code", "Activity Properties > PL/SQL Code", code, notes

    if short_type in {"WFSequenceAdapter", "WFParallelAdapter", "WFIfElseBranchAdapter"}:
        return "Execute Code", "Workflow Designer > Transitions", "", [
            "Kontener strukturalny Nintex; odwzoruj go jako kolejność aktywności i przejścia."
        ]

    if short_type == "NWBusinessProcessAdapter":
        notes.append("Etap biznesowy Nintex odwzoruj jako nazwę aktywności lub grupę kroków.")
        return "Execute Code", "Activity Properties > Identification", f"-- {title}", notes

    notes.append(f"Sprawdź semantykę akcji Nintex {short_type} i uzupełnij kod przed aktywacją.")
    return (
        "Execute Code",
        "Activity Properties > PL/SQL Code",
        f"-- TODO: implement Nintex action {short_type}",
        notes,
    )


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
    name = f"WF {title}"
    static_id = _identifier(title, "WF_", 120)
    source = wf.source_list
    variables = _extract_variables(wf.actions)
    field_variables = _field_variables(steps)
    for static_id_in_use in {variable.static_id for variable in variables.values()}:
        field_variables = {
            key: value for key, value in field_variables.items() if value.static_id != static_id_in_use
        }
    parameters = [
        ApexWorkflowParam("P_ITEM_ID", "NUMBER", True, "", "SharePoint ID elementu źródłowego."),
        ApexWorkflowParam("P_SITE_URL", "VARCHAR2", False, "", "Adres witryny SharePoint."),
        ApexWorkflowParam("P_LIST_TITLE", "VARCHAR2", False, source.list_name if source else "", "Lista źródłowa."),
        ApexWorkflowParam("P_INITIATOR", "VARCHAR2", False, "", "Użytkownik uruchamiający workflow."),
        ApexWorkflowParam("P_PAYLOAD", "CLOB", False, "", "Oryginalny payload JSON; opcjonalny."),
    ]

    activities: list[ApexWorkflowActivity] = []
    activity_by_node: dict[int, ApexWorkflowActivity] = {}
    for step in steps:
        short_type = step.node.type.rsplit(".", 1)[-1]
        if step.desc.is_structural or short_type == "NWWorkflowVariablesAdapter":
            continue
        activity_type, ui_location, code, notes = _step_code(step, wf, resolver)
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
        config_notes=["Połącz z tym węzłem wszystkie końcowe ścieżki procesu."],
    )
    for activity in activities:
        if not activity.transitions:
            activity.transitions.append(ApexWorkflowTransition("End", "stop", end_activity.title))
    activities.append(end_activity)

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
        name=name,
        static_id=static_id,
        category="SharePoint / Nintex migration",
        start_triggers=start_triggers or ["ręczny (domyślny)"],
        parameters=parameters,
        variables=list(variables.values()) + list(field_variables.values()),
        activities=activities,
    )


def format_markdown_apex_section(spec: ApexWorkflowSpec) -> str:
    lines = [
        "## Przygotowanie workflow w Oracle APEX (Shared Components > Workflows)",
        "",
        f"- **Name:** {spec.name}",
        f"- **Static ID:** `{spec.static_id}`",
        f"- **Category:** {spec.category}",
        f"- **Wyzwalacze źródłowe:** {', '.join(spec.start_triggers)} (w APEX skonfiguruj Page Process lub Automation).",
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
    lines.extend(["", "### Workflow Variables", "", "| Static ID | Typ | Rola / mapowanie |", "|---|---|---|"])
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
        "Utwórz zmienne `SP_<InternalName>` dla wartości pól używanych w warunkach i aktualizacjach. "
        "Zasil je z SharePoint przez `SHP_API` lub mapowanie wejściowe przed użyciem w aktywnościach.",
        "",
        "### Aktywności Workflow Designer",
        "",
    ])
    if not spec.activities:
        lines.append("Brak aktywności do odwzorowania; wyzwalacz Nintex skonfiguruj jako Page Process lub Automation.")
        lines.append("")
    for index, activity in enumerate(spec.activities, start=1):
        lines.extend([
            f"#### {index}. {activity.title} (`{activity.node_id}`)",
            "",
            f"- **Activity Type:** {activity.activity_type}",
            f"- **Miejsce konfiguracji:** {activity.ui_location}",
        ])
        for note in activity.config_notes:
            lines.append(f"- **Konfiguracja:** {note}")
        if activity.transitions:
            lines.extend(["- **Transitions:**"])
            for transition in activity.transitions:
                lines.append(
                    f"  - {transition.condition or 'Next'} → `{transition.target_node_id}` "
                    f"({transition.target_name})"
                )
        if activity.plsql_code:
            lines.extend(["", "```plsql" if activity.activity_type == "Execute Code" else "```text", activity.plsql_code, "```"])
        lines.append("")
    return "\n".join(lines)
