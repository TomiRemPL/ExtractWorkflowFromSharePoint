"""Katalog akcji Nintex Workflow: tlumaczenie akcji (NWActionConfig) na jezyk biznesowy.

Kazdy handler otrzymuje ActionNode + FieldResolver i zwraca ActionDescription
(zdanie biznesowe + listy pol odczytywanych/zapisywanych + surowe dane techniczne).
Nieznane typy akcji dostaja opis awaryjny (fallback), zeby narzedzie dzialalo
generycznie takze dla akcji spoza tego zestawu przykladowych plikow.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from .apex_naming import (
    EMAIL_RE,
    P_EMAIL_FROM,
    SHP_API,
    V_ITEM_ID,
    V_LIST_TITLE,
    V_SITE_URL,
    email_param,
    field_variable,
    is_lookup,
    is_user,
    sql_literal,
    variable_static_id,
    workflow_static_id,
)
from .metadata_loader import FieldResolver
from .nwf_parser import ActionNode, FieldRef


@dataclass
class ActionDescription:
    summary: str
    reads: list[FieldRef] = field(default_factory=list)
    writes: list[FieldRef] = field(default_factory=list)
    technical_lines: list[str] = field(default_factory=list)
    is_structural: bool = False  # kontener (sekwencja/rownolegle/galaz warunku) - bez wlasnego opisu
    action_type: str = ""
    label: str = ""
    condition_text: str = ""
    hint_universal: str = ""
    hint_apex: str = ""
    plsql_code: str = ""


_OPERATOR_PL = {
    "Equal": "jest równe",
    "NotEqual": "jest różne od",
    "GreaterThan": "jest większe niż",
    "LessThan": "jest mniejsze niż",
    "GreaterThanOrEqual": "jest większe lub równe",
    "LessThanOrEqual": "jest mniejsze lub równe",
    "Contains": "zawiera",
    "NotContains": "nie zawiera",
    "IsEmpty": "jest puste",
    "IsNotEmpty": "nie jest puste",
    "NotIsEmpty": "nie jest puste",
    "Eq": "jest równe",
    "Neq": "jest różne od",
    "Gt": "jest większe niż",
    "Lt": "jest mniejsze niż",
    "Geq": "jest większe lub równe",
    "Leq": "jest mniejsze lub równe",
    "BeginsWith": "zaczyna się od",
    "IsNull": "jest puste",
    "IsNotNull": "nie jest puste",
}


def _short_type(action_type: str) -> str:
    return action_type.rsplit(".", 1)[-1] if action_type else "?"


def _render_value_expr(el: ET.Element | None, resolver: FieldResolver) -> str:
    """Generyczny renderer wartosci parametru: PrimitiveValue / Variable / ListLookup / inne."""
    if el is None:
        return ""
    tag = el.tag
    if tag == "PrimitiveValue":
        return el.get("Value", "")
    if tag == "Variable":
        return f"zmienna {el.get('Name', '')}"
    if tag == "ListLookup":
        lookup_type = el.get("LookupType", "")
        field_el = el.find("Field")
        field_name = field_el.get("Name", "") if field_el is not None else ""
        target_list_id_el = el.find("ListId")
        target_list_id = target_list_id_el.text if target_list_id_el is not None else ""
        nested_lookup = el.find("Lookup")
        if lookup_type == "ThisItemLookup" or nested_lookup is None:
            field_readable = resolver.resolve(field_name, resolver.source_list_id)
            return f"wartość pola {field_readable} z bieżącego elementu"
        # CrossItemLookup itp.: wartosc pochodzi z elementu innej listy (target_list_id),
        # dopasowanego po polu z biezacego elementu (nested Lookup, zwykle ThisItemLookup).
        field_readable = resolver.resolve(field_name, target_list_id)
        nested_field_el = nested_lookup.find("Field")
        nested_field_name = nested_field_el.get("Name", "") if nested_field_el is not None else ""
        nested_readable = resolver.resolve(nested_field_name, resolver.source_list_id)
        compare_el = el.find("CompareField")
        compare_name = compare_el.get("Name", "") if compare_el is not None else "ID"
        return (
            f"wartość pola {field_readable} z elementu wyszukanego po "
            f"{nested_readable} (dopasowanie po {compare_name})"
        )
    # nieznany typ wezla - zwroc tekst lub nazwe tagu
    return el.text or f"[{tag}]"


def _plsql_var(name: str) -> str:
    """Bind zmiennej APEX Workflow (:STATIC_ID) odpowiadajacej zmiennej Nintex."""
    return f":{variable_static_id(name or 'var')}"


def _item_property_expr(name: str) -> str:
    if name.lower() in ("id", "itemid"):
        return f":{V_ITEM_ID}"
    return f":{field_variable(name)}"


def _this_item_field_expr(field_name: str, field_type: str, coercion: str, resolver: FieldResolver | None) -> str:
    """Wyrazenie dla pola biezacego elementu zasilonego w kroku standardowym 4 (Parse V_SHP_ANSWER)."""
    if not field_name or field_name.lower() in ("id", "itemid"):
        return f":{V_ITEM_ID}"
    resolved_type = (resolver.get_field_type(field_name) if resolver is not None else "") or field_type
    if is_lookup(resolved_type) and ("lookupid" in coercion.lower() or "int" in coercion.lower()):
        return f":{field_variable(field_name, 'ID')}"
    return f":{field_variable(field_name)}"


def _ref_select(field_name: str, field_type: str, id_only: bool = False) -> tuple[str, str]:
    """Zwraca (p_query, sciezka JSON) do odczytu pola z elementu innej listy."""
    if is_lookup(field_type) or is_user(field_type):
        prop = "Id" if id_only else "Title"
        return f"$select={field_name}/{prop}&$expand={field_name}", f"{field_name}.{prop}"
    return f"$select={field_name}", field_name


def _cross_lookup_parts(el: ET.Element, resolver: FieldResolver) -> dict[str, str]:
    """Rozklada CrossItemLookup na wywolanie LCDT.SHP_API i sciezke JSON wyniku."""
    field_el = el.find("Field")
    field_name = field_el.get("Name", "") if field_el is not None else ""
    target_list_el = el.find("ListId")
    target_list_id = (target_list_el.text or "") if target_list_el is not None else ""
    target_list = resolver.get_list_name(target_list_id)
    target_type = resolver.get_field_type(field_name, target_list_id) or (field_el.get("Type", "") if field_el is not None else "")
    coercion = el.findtext("Coercion") or "LookupIdOnlyAsInteger"
    # Coercion "LookupId..." na polu Lookup/User oznacza, ze Nintex zwraca ID powiazanego elementu, a nie jego tytul.
    query, path = _ref_select(field_name, target_type, id_only="lookupid" in coercion.lower())
    nested = el.find("Lookup")
    nested_field_el = nested.find("Field") if nested is not None else None
    nested_name = nested_field_el.get("Name", "") if nested_field_el is not None else ""
    nested_type = nested_field_el.get("Type", "") if nested_field_el is not None else ""
    if nested is not None and nested.get("LookupType", "ThisItemLookup") == "ThisItemLookup":
        key_expr = _this_item_field_expr(nested_name, nested_type, coercion, resolver)
    elif nested is not None and nested.find("Variable") is not None:
        key_expr = _plsql_var(nested.find("Variable").get("Name", ""))
    else:
        key_expr = "NULL /* TODO: klucz wyszukania */"
    compare_el = el.find("CompareField")
    compare = compare_el.get("Name", "ID") if compare_el is not None else "ID"
    if compare.upper() == "ID":
        call = (
            f"{SHP_API}.get_list_item(\n"
            f"    p_site_url   => :{V_SITE_URL},\n"
            f"    p_list_title => {sql_literal(target_list)},\n"
            f"    p_item_id    => {key_expr},\n"
            f"    p_query      => {sql_literal(query)}\n"
            f")"
        )
        json_path = f"$.data.{path}"
    else:
        call = (
            f"{SHP_API}.get_list_items(\n"
            f"    p_site_url   => :{V_SITE_URL},\n"
            f"    p_list_title => {sql_literal(target_list)},\n"
            f"    p_query      => {sql_literal(query + '&$top=1&$filter=' + compare + ' eq ')} || '''' || REPLACE({key_expr}, '''', '''''') || ''''\n"
            f")"
        )
        json_path = f"$.data[0].{path}"
    return {"call": call, "json_path": json_path, "target_list": target_list, "field": field_name}


def _plsql_expr_from_nintex_string(val: str, item_json_var: str = "", resolver: FieldResolver | None = None) -> str:
    """Tłumaczy wyrażenia Nintex (np. RKU-{ItemProperty:ID} lub {ItemProperty:Nazwa}) na wyrażenie PL/SQL z bindami APEX."""
    if not val:
        return "NULL"
    pattern = re.compile(r"\{(ItemProperty|WorkflowVariable):([^}]+)\}")
    tokens = list(pattern.finditer(val))
    if not tokens:
        escaped = val.replace("'", "''")
        return f"'{escaped}'"

    parts: list[str] = []
    last_idx = 0
    for match in tokens:
        start, end = match.span()
        if start > last_idx:
            literal = val[last_idx:start]
            if literal:
                lit_escaped = literal.replace("'", "''")
                parts.append(f"'{lit_escaped}'")
        token_type = match.group(1)
        token_name = match.group(2).strip()
        if token_type == "ItemProperty":
            expr = _item_property_expr(token_name)
            standalone = len(tokens) == 1 and not pattern.sub("", val)
            parts.append(expr if standalone or expr != f":{V_ITEM_ID}" else f"TO_CHAR({expr})")
        elif token_type == "WorkflowVariable":
            parts.append(_plsql_var(token_name))
        last_idx = end

    if last_idx < len(val):
        literal = val[last_idx:]
        if literal:
            lit_escaped = literal.replace("'", "''")
            parts.append(f"'{lit_escaped}'")

    if len(parts) == 1:
        return parts[0]
    return " || ".join(parts)


def _plsql_val_expr(el: ET.Element | None, resolver: FieldResolver, item_json_var: str = "") -> str:
    if el is None:
        return "NULL"
    tag = el.tag
    if tag == "PrimitiveValue":
        return _plsql_expr_from_nintex_string(el.get("Value", ""), item_json_var, resolver)
    if tag == "Variable":
        return _plsql_var(el.get("Name", ""))
    if tag == "ListLookup":
        lookup_type = el.get("LookupType", "")
        field_el = el.find("Field")
        field_name = field_el.get("Name", "") if field_el is not None else ""
        field_type = field_el.get("Type", "") if field_el is not None else ""
        nested_lookup = el.find("Lookup")
        if lookup_type == "ThisItemLookup" or nested_lookup is None:
            return _this_item_field_expr(field_name, field_type, el.findtext("Coercion") or "", resolver)
        parts = _cross_lookup_parts(el, resolver)
        call = re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", re.sub(r"\s*\n\s*", " ", parts["call"])))
        return f"json_value({call}, '{parts['json_path']}')"
    return "NULL"


def _plsql_condition(cond_el: ET.Element | None, resolver: FieldResolver, item_json_var: str = "") -> str:
    if cond_el is None:
        return "TRUE"
    xsi_type = cond_el.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
    if xsi_type == "ConditionPair":
        op = {"And": "AND", "Or": "OR"}.get(cond_el.get("Operator", ""), "AND")
        left = _plsql_condition(cond_el.find("Left"), resolver, item_json_var)
        right = _plsql_condition(cond_el.find("Right"), resolver, item_json_var)
        return f"({left}) {op} ({right})"
    if xsi_type == "NWConditionConfig":
        params_el = cond_el.find("Params")
        params = {p.get("Name"): p for p in params_el.findall("Param")} if params_el is not None else {}
        op_name = ""
        if "operator" in params:
            op_val_el = params["operator"].find("PrimitiveValue")
            op_name = op_val_el.get("Value", "") if op_val_el is not None else ""

        left_el = next(iter(params["left"]), None) if "left" in params else None
        right_el = next(iter(params["right"]), None) if "right" in params else None

        left_expr = _plsql_val_expr(left_el, resolver, item_json_var)
        right_expr = _plsql_val_expr(right_el, resolver, item_json_var)

        if op_name == "Equal":
            return f"{left_expr} = {right_expr}"
        elif op_name == "NotEqual":
            return f"{left_expr} != {right_expr}"
        elif op_name == "GreaterThan":
            return f"{left_expr} > {right_expr}"
        elif op_name == "LessThan":
            return f"{left_expr} < {right_expr}"
        elif op_name == "GreaterThanOrEqual":
            return f"{left_expr} >= {right_expr}"
        elif op_name == "LessThanOrEqual":
            return f"{left_expr} <= {right_expr}"
        elif op_name == "Contains":
            return f"{left_expr} LIKE '%' || {right_expr} || '%'"
        elif op_name == "NotContains":
            return f"{left_expr} NOT LIKE '%' || {right_expr} || '%'"
        elif op_name in ("IsEmpty", "IsNull"):
            return f"{left_expr} IS NULL"
        elif op_name in ("IsNotEmpty", "NotIsEmpty", "IsNotNull"):
            return f"{left_expr} IS NOT NULL"
        return f"{left_expr} = {right_expr}"
    return "TRUE"


def _render_condition(cond_el: ET.Element | None, resolver: FieldResolver) -> str:
    if cond_el is None:
        return ""
    xsi_type = cond_el.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
    if xsi_type == "ConditionPair":
        operator = {"And": "ORAZ", "Or": "LUB"}.get(cond_el.get("Operator", ""), cond_el.get("Operator", ""))
        left = _render_condition(cond_el.find("Left"), resolver)
        right = _render_condition(cond_el.find("Right"), resolver)
        return f"({left}) {operator} ({right})"
    if xsi_type == "NWConditionConfig":
        params_el = cond_el.find("Params")
        params = {p.get("Name"): p for p in params_el.findall("Param")} if params_el is not None else {}
        operator = ""
        left_txt = right_txt = ""
        if "operator" in params:
            op_val_el = params["operator"].find("PrimitiveValue")
            operator = _OPERATOR_PL.get(op_val_el.get("Value", "") if op_val_el is not None else "", "")
        if "left" in params:
            left_txt = _render_value_expr(next(iter(params["left"]), None), resolver)
        if "right" in params:
            right_txt = _render_value_expr(next(iter(params["right"]), None), resolver)
        return f"{left_txt} {operator} {right_txt}".strip()
    return cond_el.get("Name", "") or "warunek"


def _describe_variables_adapter(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    triggers = []
    if node.params.get("StartManually") == "true":
        triggers.append("ręcznie")
    if node.params.get("StartOnCreate") == "true":
        triggers.append("przy utworzeniu elementu")
    if node.params.get("StartOnChange") == "true":
        triggers.append("przy zmianie elementu")
    trig_txt = ", ".join(triggers) if triggers else "brak zdefiniowanych wyzwalaczy"
    name = node.params.get("WorkflowName", "")
    src_list_name = resolver.get_list_name()
    plsql_code = (
        "-- Kroki standardowe APEX Workflow (patrz sekcja 'Kroki standardowe'):\n"
        "--   1. Workflow Start + Additional Data (NINTEX_PARAMS -> P_*)\n"
        f"--   2. Execute Code 'Retrieve Payload' (:P_PAYLOAD_BODY -> :{V_ITEM_ID}, :{V_SITE_URL}, :{V_LIST_TITLE}, :V_EDITOR)\n"
        f"--   3. Invoke API {SHP_API}.GET_LIST_ITEM (lista '{src_list_name}') -> :V_SHP_ANSWER\n"
        "--   4. Execute Code 'Parse' (:V_SHP_ANSWER -> :SP_*)"
    )
    hint_apex = f"Kroki standardowe: Additional Data → Retrieve Payload → {SHP_API}.GET_LIST_ITEM → Parse V_SHP_ANSWER."
    return ActionDescription(
        summary=f"Start workflow '{name}'. Uruchamiane: {trig_txt}.",
        technical_lines=[f"{k} = {v}" for k, v in node.params.items()],
        action_type="NWWorkflowVariablesAdapter",
        label=name or "Start workflow",
        hint_universal=f"Wyzwalacz procesu (Triggers: {trig_txt}). Punkt wejścia przyjmujący parametr itemId.",
        hint_apex=hint_apex,
        plsql_code=plsql_code,
    )


def _extract_condition_fields(cond_el: ET.Element | None) -> list[FieldRef]:
    """Zbiera wszystkie odwolania do pol (elementy <Field Name=... Type=...>) w warunku."""
    if cond_el is None:
        return []
    refs: list[FieldRef] = []
    for field_el in cond_el.iter("Field"):
        name = field_el.get("Name", "")
        if name:
            refs.append(FieldRef(name="", internal_name=name, field_type=field_el.get("Type", "")))
    return refs


def _describe_if_else(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    cond_txt = _render_condition(node.condition_el, resolver)
    label = node.t_label or "Warunek"
    cond_plsql = _plsql_condition(node.condition_el, resolver)
    plsql_code = f"IF {cond_plsql} THEN\n    -- Gałąź Tak\nELSE\n    -- Gałąź Nie\nEND IF;"
    hint_apex = f"IF {cond_plsql} THEN ... ELSE ... END IF;"
    return ActionDescription(
        summary=f"Warunek: JEŻELI {cond_txt}",
        reads=_extract_condition_fields(node.condition_el),
        technical_lines=[f"ConditionUse={node.condition_use}"],
        action_type="WFIfElseAdapter",
        label=label,
        condition_text=cond_txt,
        hint_universal=f"Bramka decyzyjna (Exclusive Gateway / IF): sprawdzenie warunku logicznego: {cond_txt}.",
        hint_apex=hint_apex,
        plsql_code=plsql_code,
    )


def _describe_if_else_branch(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    return ActionDescription(summary="", is_structural=True, action_type="WFIfElseBranchAdapter")


def _describe_write_to_history(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    msg = node.params.get("Message", "")
    short = msg.splitlines()[0] if msg else ""
    msg_expr = _plsql_expr_from_nintex_string(msg, resolver=resolver)
    plsql_code = f"apex_debug.info('Workflow: ' || {msg_expr});"
    return ActionDescription(
        summary=f"Zapisz wpis w historii przepływu: „{short}”" + (" (…)" if len(msg.splitlines()) > 1 else ""),
        technical_lines=[f"Message = {msg}"],
        action_type="NWWriteToHistoryListAdapter",
        label=node.t_label or "Zapis historii",
        hint_universal="Zapis audytowy do dziennika zdarzeń (Audit Log).",
        hint_apex=plsql_code,
        plsql_code=plsql_code,
    )


def _field_json_pair(internal_name: str, value_expr: str, field_type: str) -> str:
    """Para JSON_OBJECT dla REST SharePoint: Lookup -> <Pole>Id, User -> <Pole>Id z ensure_user_id."""
    if is_user(field_type):
        return f"'{internal_name}Id' VALUE {SHP_API}.ensure_user_id(:{V_SITE_URL}, {value_expr})"
    if is_lookup(field_type):
        return f"'{internal_name}Id' VALUE {value_expr}"
    return f"'{internal_name}' VALUE {value_expr}"


def _update_call(list_expr: str, item_expr: str, pairs: list[str]) -> str:
    pairs_str = ",\n        ".join(pairs)
    return (
        f"l_resp := {SHP_API}.update_list_item(\n"
        f"    p_site_url    => :{V_SITE_URL},\n"
        f"    p_list_title  => {list_expr},\n"
        f"    p_item_id     => {item_expr},\n"
        f"    p_fields_json => json_object(\n"
        f"        {pairs_str}\n"
        f"    )\n"
        f");"
    )


def _field_reference_value(node: ActionNode, internal_name: str) -> ET.Element | None:
    """Wartosc przypisywana do pola w SPUpdateItemWithKeyAdapter (dziecko FieldReference)."""
    if node.raw_el is None:
        return None
    for ref in node.raw_el.iter("FieldReference"):
        if ref.get("Value") == internal_name:
            return next((child for child in ref if child.tag != "Coercion"), None)
    return None


def _describe_update_item(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    list_id = node.params.get("ListId", "")
    this_item = node.params.get("ThisItem") == "true" or not list_id or (
        bool(resolver.source_list_id) and list_id.strip("{}").lower() == resolver.source_list_id.strip("{}").lower()
    )
    target_list_name = resolver.get_list_name() if this_item else resolver.get_list_name(list_id)
    target = "w bieżącym elemencie" if this_item else f"w elemencie listy {target_list_name}"
    writes = node.field_refs
    fields_txt = ", ".join(resolver.resolve(f.internal_name, list_id) for f in writes) or "(brak pól)"

    if this_item:
        list_expr, item_expr = f":{V_LIST_TITLE}", f":{V_ITEM_ID}"
    else:
        list_expr = sql_literal(target_list_name)
        key_field = node.params.get("LookupField", "")
        key_value = node.params.get("LookupFieldValue", "")
        if key_field.upper() == "ID" and key_value:
            item_expr = f"TO_NUMBER({_plsql_expr_from_nintex_string(key_value, resolver=resolver)})"
        else:
            item_expr = f"NULL /* TODO: ID elementu wg {key_field or 'klucza'} = {key_value or '?'} */"

    if writes:
        pairs = []
        for f in writes:
            value_el = _field_reference_value(node, f.internal_name)
            value_expr = _plsql_val_expr(value_el, resolver) if value_el is not None else f":{field_variable(f.internal_name)}"
            field_type = resolver.get_field_type(f.internal_name, list_id) or f.field_type
            pairs.append(_field_json_pair(f.internal_name, value_expr, field_type))
        plsql_code = _update_call(list_expr, item_expr, pairs)
        hint_apex = f"l_resp := {SHP_API}.update_list_item(:{V_SITE_URL}, {list_expr}, {item_expr}, json_object(...));"
    else:
        plsql_code = "-- Brak zdefiniowanych pól do zapisu"
        hint_apex = plsql_code

    return ActionDescription(
        summary=f"Zaktualizuj element {target}: ustaw pola {fields_txt}.",
        writes=writes,
        technical_lines=[f"ListId = {list_id}", f"ThisItem = {this_item}"],
        action_type="SPUpdateItemWithKeyAdapter",
        label=node.t_label or "Aktualizacja pól",
        hint_universal=f"Aktualizacja danych elementu ({fields_txt}). W systemie docelowym UPDATE lub REST PATCH/MERGE.",
        hint_apex=hint_apex,
        plsql_code=plsql_code,
    )


def _describe_set_field_with_key(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    field_internal = node.params.get("LookupField", "")
    value = node.params.get("LookupFieldValue", "")
    val_expr = _plsql_expr_from_nintex_string(value, resolver=resolver)
    field_readable = resolver.resolve(field_internal, resolver.source_list_id)
    field_type = resolver.get_field_type(field_internal) or node.params.get("LookupFieldType", "")
    writes = [FieldRef(name=field_readable, internal_name=field_internal, field_type=node.params.get("LookupFieldType", ""))]

    pair = _field_json_pair(field_internal, val_expr, field_type)
    plsql_code = _update_call(f":{V_LIST_TITLE}", f":{V_ITEM_ID}", [pair])
    hint_apex = f"l_resp := {SHP_API}.update_list_item(:{V_SITE_URL}, :{V_LIST_TITLE}, :{V_ITEM_ID}, json_object({pair}));"

    return ActionDescription(
        summary=f"Ustaw pole {field_readable} na wartość: „{value}”.",
        writes=writes,
        technical_lines=[f"{k} = {v}" for k, v in node.params.items()],
        action_type="SPSetFieldWithKeyAdapter",
        label=node.t_label or f"Ustaw {field_readable}",
        hint_universal=f"Ustawienie pola {field_readable} = '{value}'.",
        hint_apex=hint_apex,
        plsql_code=plsql_code,
    )


def _describe_set_variable(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    var_name_el = node.param_elements.get("VariableName")
    var_name = var_name_el.get("Name", "?") if var_name_el is not None else "?"
    var_plsql = _plsql_var(var_name)
    value_el = node.param_elements.get("Value")
    value_txt = _render_value_expr(value_el, resolver)
    label = node.t_label
    prefix = f"{label}: " if label else ""

    if value_el is not None and value_el.tag == "ListLookup":
        lookup_type = value_el.get("LookupType", "")
        nested_lookup = value_el.find("Lookup")
        if lookup_type == "CrossItemLookup" and nested_lookup is not None:
            parts = _cross_lookup_parts(value_el, resolver)
            plsql_code = (
                f"-- Pobranie powiązanego rekordu z {parts['target_list']}:\n"
                f"l_ref_json := {parts['call']};\n"
                f"{var_plsql} := json_value(l_ref_json, '{parts['json_path']}');"
            )
            hint_apex = f"{var_plsql} := json_value({SHP_API}.get_list_item(:{V_SITE_URL}, '{parts['target_list']}', ...), '{parts['json_path']}');"
        else:
            plsql_code = f"{var_plsql} := {_plsql_val_expr(value_el, resolver)};"
            hint_apex = plsql_code
    elif value_el is not None and value_el.tag == "PrimitiveValue":
        val_expr = _plsql_expr_from_nintex_string(value_el.get("Value", ""), resolver=resolver)
        plsql_code = f"{var_plsql} := {val_expr};"
        hint_apex = plsql_code
    elif value_el is not None and value_el.tag == "Variable":
        other_var = _plsql_var(value_el.get("Name", ""))
        plsql_code = f"{var_plsql} := {other_var};"
        hint_apex = plsql_code
    else:
        plsql_code = f"{var_plsql} := NULL;"
        hint_apex = plsql_code

    return ActionDescription(
        summary=f"{prefix}Zapisz w zmiennej '{var_name}' wartość: {value_txt}.",
        reads=_extract_condition_fields(value_el),
        technical_lines=[f"{k} = {v}" for k, v in node.params.items()],
        action_type="SPSetVariableAdapter",
        label=label or f"Zmienna {var_name}",
        hint_universal=f"Obliczenie/odczyt i zapis do zmiennej lokalnej '{var_name}'.",
        hint_apex=hint_apex,
        plsql_code=plsql_code,
    )


def _describe_run_if(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    cond_txt = _render_condition(node.condition_el, resolver)
    summary = f"Wykonaj poniższe kroki TYLKO JEŻELI {cond_txt}" if cond_txt else "Wykonaj warunkowo poniższe kroki"
    cond_plsql = _plsql_condition(node.condition_el, resolver)
    plsql_code = f"IF {cond_plsql} THEN\n    -- Akcje warunkowe\nEND IF;"
    hint_apex = f"IF {cond_plsql} THEN ... END IF;"
    return ActionDescription(
        summary=summary,
        reads=_extract_condition_fields(node.condition_el),
        action_type="NWRunIf2Adapter",
        label=node.t_label or "Wykonaj jeśli",
        condition_text=cond_txt,
        hint_universal=f"Warunek wykonania bloku podrzędnego: IF ({cond_txt}).",
        hint_apex=hint_apex,
        plsql_code=plsql_code,
    )


def _describe_commit(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    plsql_code = f"-- Zmiany są zatwierdzane natychmiast przez {SHP_API}.update_list_item (REST SharePoint)"
    return ActionDescription(
        summary="Zapisz (zatwierdź) zebrane zmiany w elemencie.",
        action_type="NWCommitAdapter",
        label=node.t_label or "Zatwierdzenie transakcji",
        hint_universal="Zatwierdzenie bieżącego stanu transakcji (COMMIT).",
        hint_apex=plsql_code,
        plsql_code=plsql_code,
    )


def _describe_structural(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    return ActionDescription(summary="", is_structural=True, action_type=_short_type(node.type))


def _parse_caml_query_info(query_str: str, resolver: FieldResolver) -> tuple[str, str, list[str]]:
    """Wyciąga tytuł listy, warunek <Where> i pola <FieldRef> z zagnieżdżonego CAML."""
    if not query_str:
        return "", "", []
    try:
        root = ET.fromstring(query_str)
    except Exception:
        return "", "", []

    list_el = root.find(".//List")
    list_name = ""
    if list_el is not None:
        list_name = list_el.get("Title") or ""
        if not list_name and list_el.get("ID"):
            list_name = resolver.get_list_name(list_el.get("ID"))

    fields: list[str] = []
    for f in root.findall(".//FieldRef"):
        fn = f.get("Name")
        if fn and fn not in fields:
            fields.append(fn)

    where_parts: list[str] = []
    for comp in root.findall(".//Where/*"):
        op = comp.tag
        f_el = comp.find("FieldRef")
        v_el = comp.find("Value")
        f_name = f_el.get("Name", "") if f_el is not None else ""
        v_val = v_el.text or "" if v_el is not None else ""
        op_pl = _OPERATOR_PL.get(op, op)
        if f_name and v_val:
            where_parts.append(f"{f_name} {op_pl} '{v_val}'")
        elif f_name:
            where_parts.append(f"{f_name} ({op_pl})")

    where_desc = " AND ".join(where_parts) if where_parts else "wszystkie elementy"
    return list_name, where_desc, fields


def _describe_build_string(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    input_str = node.params.get("Input", "")
    out_var = node.params.get("Output", "")
    out_ident = _plsql_var(out_var) if out_var else ":V_BUILT_STRING"

    expr = _plsql_expr_from_nintex_string(input_str, resolver=resolver)
    plsql_code = f"{out_ident} := {expr};"
    summary = f"Zbuduj ciąg tekstowy i przypisz do zmiennej {out_var or '(brak)'}."
    if input_str:
        summary += f" Wartość: {input_str[:120]}"

    return ActionDescription(
        summary=summary,
        action_type="NWBuildStringAdapter",
        label=node.b_label or node.t_label or "Zbuduj ciąg",
        hint_universal=f"Przypisanie sformatowanego tekstu do zmiennej {out_var}.",
        hint_apex=f"{out_ident} := ...;",
        plsql_code=plsql_code,
        technical_lines=[f"Input = {input_str}", f"Output = {out_var}"],
    )


def _describe_business_process(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    label = node.b_label or node.t_label or "Etap procesu"
    summary = f"Etap biznesowy: {label}."
    plsql_code = f"-- =========================================\n-- Etap: {label}\n-- ========================================="
    return ActionDescription(
        summary=summary,
        action_type="NWBusinessProcessAdapter",
        label=label,
        hint_universal=f"Wydzielony etap procesu biznesowego: {label}.",
        hint_apex=f"-- Etap: {label}",
        plsql_code=plsql_code,
    )


def _describe_calculate_date(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    date_var = node.params.get("Date", "bieżąca data")
    out_var = node.params.get("Output", "")
    out_ident = _plsql_var(out_var) if out_var else "l_calculated_date"
    base_ident = _plsql_var(date_var) if date_var else "SYSDATE"

    parts = []
    days = int(node.params.get("Days") or 0)
    months = int(node.params.get("Months") or 0)
    years = int(node.params.get("Years") or 0)
    hours = int(node.params.get("Hours") or 0)
    minutes = int(node.params.get("Minutes") or 0)

    if years: parts.append(f"{years:+d} lat")
    if months: parts.append(f"{months:+d} mies.")
    if days: parts.append(f"{days:+d} dni")
    if hours: parts.append(f"{hours:+d} godz.")
    if minutes: parts.append(f"{minutes:+d} min")

    offset_desc = ", ".join(parts) if parts else "bez przesunięcia"
    summary = f"Oblicz datę: {date_var} ({offset_desc}) -> zapisz do zmiennej {out_var}."

    calc_expr = base_ident
    if months or years:
        total_months = months + years * 12
        calc_expr = f"ADD_MONTHS({calc_expr}, {total_months})"
    if days:
        calc_expr = f"({calc_expr} + {days})"
    if hours or minutes:
        total_days = hours / 24.0 + minutes / 1440.0
        calc_expr = f"({calc_expr} + {total_days})"

    plsql_code = f"{out_ident} := {calc_expr};"

    return ActionDescription(
        summary=summary,
        action_type="NWCalculateDateAdapter",
        label=node.b_label or node.t_label or "Oblicz datę",
        hint_universal=f"Wyliczenie daty z przesunięciem ({offset_desc}).",
        hint_apex=plsql_code,
        plsql_code=plsql_code,
        technical_lines=[f"Date = {date_var}", f"Offset = {offset_desc}", f"Output = {out_var}"],
    )


def _describe_collection_operation(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    target = node.params.get("Target", "kolekcja")
    op = node.params.get("Operation", "Get")
    out = node.params.get("Output", "")
    idx = node.params.get("Index", "")
    delim = node.params.get("JoinDelimiter", "")

    target_ident = _plsql_var(target)
    out_ident = _plsql_var(out) if out else "l_res"
    idx_ident = _plsql_var(idx) if idx else "1"

    if op.lower() == "get":
        summary = f"Pobierz element z indeksu {idx or '0'} kolekcji {target} do zmiennej {out}."
        plsql_code = f"{out_ident} := {target_ident}({idx_ident});"
    elif op.lower() == "count":
        summary = f"Zlicz liczbę elementów w kolekcji {target} do zmiennej {out}."
        plsql_code = f"{out_ident} := {target_ident}.COUNT;"
    elif op.lower() == "join":
        summary = f"Połącz elementy kolekcji {target} separatorem '{delim}' do zmiennej {out}."
        plsql_code = f"{out_ident} := apex_string.join({target_ident}, '{delim}');"
    else:
        summary = f"Operacja '{op}' na kolekcji {target} -> {out}."
        plsql_code = f"-- Operacja {op} na kolekcji {target_ident}"

    return ActionDescription(
        summary=summary,
        action_type="NWCollectionAdapter",
        label=node.b_label or node.t_label or f"Kolekcja: {op}",
        hint_universal=f"Operacja tablicowa ({op}) na kolekcji {target}.",
        hint_apex=plsql_code,
        plsql_code=plsql_code,
        technical_lines=[f"Target = {target}", f"Operation = {op}", f"Index = {idx}", f"Output = {out}"],
    )


def _describe_create_site_item(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    raw_query = node.params.get("Query", "")
    list_name, where_desc, fields = _parse_caml_query_info(raw_query, resolver)
    if not list_name and node.b_label:
        list_name = node.b_label
    if not list_name:
        list_name = "Lista docelowa"

    out_var = node.params.get("Output", "")
    out_ident = _plsql_var(out_var) if out_var else ":V_NEW_ITEM_ID"

    summary = f"Utwórz nowy element na liście '{list_name}'."
    if out_var:
        summary += f" Nowe ID -> zmienna {out_var}."

    plsql_code = f"""l_resp := {SHP_API}.add_list_item(
    p_site_url    => :{V_SITE_URL},
    p_list_title  => {sql_literal(list_name)},
    p_fields_json => json_object('Title' VALUE 'Nowy element') -- TODO: uzupełnij mapowanie pól
);
{out_ident} := json_value(l_resp, '$.item_id' RETURNING NUMBER);"""

    return ActionDescription(
        summary=summary,
        action_type="NWCreateSiteSpecificItemAdapter",
        label=node.t_label or f"Utwórz element w {list_name}",
        hint_universal=f"Tworzenie nowego rekordu na liście {list_name}.",
        hint_apex=f"l_resp := {SHP_API}.add_list_item(...); {out_ident} := json_value(l_resp, '$.item_id');",
        plsql_code=plsql_code,
        technical_lines=[f"Lista = {list_name}", f"Output = {out_var}"],
    )


def _describe_delay(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    parts = []
    days = int(node.params.get("Days") or 0)
    hours = int(node.params.get("Hours") or 0)
    minutes = int(node.params.get("Minutes") or 0)

    if days: parts.append(f"{days} dni")
    if hours: parts.append(f"{hours} godz.")
    if minutes: parts.append(f"{minutes} min")

    dur_desc = ", ".join(parts) if parts else "5 minut"
    total_sec = days * 86400 + hours * 3600 + minutes * 60
    if not total_sec:
        total_sec = 300

    summary = f"Wstrzymaj wykonanie przepływu o {dur_desc}."
    plsql_code = (
        f"-- Wstrzymanie o {dur_desc}: w APEX użyj natywnej aktywności 'Wait' ({total_sec // 60} min).\n"
        "-- W ścieżce B (jeden Execute Code) podziel kod na dwie aktywności Execute Code rozdzielone aktywnością Wait."
    )

    return ActionDescription(
        summary=summary,
        action_type="NWDelayForAdapter",
        label=node.t_label or f"Wstrzymaj ({dur_desc})",
        hint_universal=f"Opóźnienie wykonania procesu o {dur_desc}.",
        hint_apex=f"Aktywność APEX 'Wait': {total_sec // 60} min.",
        plsql_code=plsql_code,
        technical_lines=[f"Czas = {dur_desc}", f"Sekundy = {total_sec}"],
    )


def _describe_for_each_loop(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    target = node.params.get("Target", "kolekcja")
    val_var = node.params.get("Value", "element")
    target_ident = _plsql_var(target)
    val_ident = _plsql_var(val_var)

    label = node.t_label or f"Dla każdego elementu w {target}"
    summary = f"Pętla: dla każdego elementu w kolekcji {target} (bieżący element -> {val_var})."

    plsql_code = f"""-- Pętla: {label}
FOR i IN 1..{target_ident}.COUNT LOOP
    {val_ident} := {target_ident}(i);"""

    return ActionDescription(
        summary=summary,
        action_type="NWForEachLoopAdapter",
        label=node.b_label or label,
        hint_universal=f"Iteracja pętli po elementach kolekcji {target}.",
        hint_apex=f"FOR i IN 1..{target_ident}.COUNT LOOP",
        plsql_code=plsql_code,
        technical_lines=[f"Target = {target}", f"Value = {val_var}"],
    )


def _describe_query_list(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    raw_query = node.params.get("Query", "")
    list_name, where_desc, fields = _parse_caml_query_info(raw_query, resolver)
    if not list_name and node.b_label:
        list_name = node.b_label
    if not list_name:
        list_name = "Lista SharePoint"

    mappings = []
    if node.raw_el is not None:
        for vs in node.raw_el.findall(".//ValueStorage"):
            var_name = vs.get("VariableName", "")
            val_id = vs.get("ValueIdentifier", "")
            if var_name and val_id:
                mappings.append(f"{val_id} -> {var_name}")

    map_desc = f" (zapis: {', '.join(mappings)})" if mappings else ""
    summary = f"Wyszukaj elementy na liście '{list_name}' wg warunku: {where_desc}{map_desc}."

    reads = [FieldRef(name=f, internal_name=f) for f in fields]

    select = f"$select={','.join(fields)}" if fields else "$select=Id"
    plsql_code = f"""-- Pobranie elementów z listy {list_name} (warunek Nintex: {where_desc}):
l_resp := {SHP_API}.get_list_items(
    p_site_url   => :{V_SITE_URL},
    p_list_title => {sql_literal(list_name)},
    p_query      => {sql_literal(select + '&$filter=')} -- TODO: przepisz warunek CAML na OData $filter
);
-- Wyniki: json_table(l_resp, '$.data[*]' COLUMNS (...))"""

    return ActionDescription(
        summary=summary,
        reads=reads,
        action_type="NWQueryListAdapter",
        label=node.b_label or node.t_label or f"Kwerenda: {list_name}",
        hint_universal=f"Wyszukanie elementów na liście {list_name} (warunek: {where_desc}).",
        hint_apex=f"l_resp := {SHP_API}.get_list_items(:{V_SITE_URL}, '{list_name}', '$select=...&$filter=...');",
        plsql_code=plsql_code,
        technical_lines=[f"Lista = {list_name}", f"Warunek = {where_desc}", f"Mapowania = {mappings}"],
    )


def _describe_send_message(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    subject = "Powiadomienie workflow"
    body_text = ""
    recipients: list[str] = []

    if node.raw_el is not None:
        subj_el = node.raw_el.find(".//Message/Subject")
        if subj_el is not None and subj_el.text:
            subject = subj_el.text
        body_el = node.raw_el.find(".//Message/Body")
        if body_el is not None and body_el.text:
            body_text = re.sub(r"<[^>]+>", "", body_el.text).strip()
        for app in node.raw_el.findall(".//Approvers/Approver"):
            user = app.get("User", "")
            if user:
                recipients.append(user.split("|")[-1])

    recip_str = ", ".join(recipients) if recipients else "użytkownicy"
    summary = f"Wyślij powiadomienie e-mail: temat '{subject}' do: {recip_str}."

    to_parts = [
        f":{email_param(r)}" if EMAIL_RE.fullmatch(r) else _plsql_expr_from_nintex_string(r, resolver=resolver)
        for r in recipients
    ]
    to_expr = " || ',' || ".join(to_parts) if to_parts else f":{field_variable('Editor', 'EMAIL')} /* TODO: potwierdź odbiorcę */"
    plsql_code = f"""-- Wysłanie powiadomienia e-mail (stałe adresy -> parametry P_ z NINTEX_PARAMS):
apex_mail.send(
    p_to   => {to_expr},
    p_from => :{P_EMAIL_FROM},
    p_subj => {_plsql_expr_from_nintex_string(subject, resolver=resolver)},
    p_body => {_plsql_expr_from_nintex_string(body_text or 'Powiadomienie z procesu biznesowego', resolver=resolver)}
);"""

    return ActionDescription(
        summary=summary,
        action_type="NWSendMessageAdapter",
        label=node.b_label or node.t_label or f"E-mail: {subject}",
        hint_universal=f"Wysłanie wiadomości e-mail do: {recip_str} (temat: {subject}).",
        hint_apex="apex_mail.send(...);",
        plsql_code=plsql_code,
        technical_lines=[f"Odbiorcy = {recip_str}", f"Temat = {subject}"],
    )


def _describe_start_workflow(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    wf_name = node.params.get("AssociationId") or node.b_label or "Podproces"
    wait_for = node.params.get("WaitForComplete", "false").lower() == "true"
    wait_str = "synchronicznie - czeka na zakończenie" if wait_for else "asynchronicznie"

    summary = f"Uruchom przepływ pracy '{wf_name}' ({wait_str})."
    child_static_id = workflow_static_id(wf_name)
    plsql_code = (
        f"-- Uruchomienie podprocesu {wf_name}: w APEX użyj aktywności 'Invoke Workflow' (Sub-Workflow)\n"
        f"-- lub wywołaj go z kodu:\n"
        f"DECLARE\n"
        f"    l_params apex_workflow.t_workflow_parameters;\n"
        f"    l_wf_id  NUMBER;\n"
        f"BEGIN\n"
        f"    l_params(1).static_id := 'P_PAYLOAD_BODY';\n"
        f"    l_params(1).value.data_type := apex_session_state.c_data_type_clob;\n"
        f"    l_params(1).value.clob_value := :P_PAYLOAD_BODY;\n"
        f"    l_wf_id := apex_workflow.start_workflow(\n"
        f"        p_static_id  => '{child_static_id}',\n"
        f"        p_parameters => l_params,\n"
        f"        p_detail_pk  => TO_CHAR(:{V_ITEM_ID})\n"
        f"    );\n"
        f"END;"
    )

    return ActionDescription(
        summary=summary,
        action_type="NWStartWorkflow2Adapter",
        label=node.b_label or node.t_label or f"Uruchom: {wf_name}",
        hint_universal=f"Uruchomienie procesu podrzędnego {wf_name}.",
        hint_apex=f"Invoke Workflow '{child_static_id}' (lub apex_workflow.start_workflow).",
        plsql_code=plsql_code,
        technical_lines=[f"Workflow = {wf_name}", f"Czekaj = {wait_for}"],
    )


def _describe_update_multiple_items(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    raw_query = node.params.get("Query", "")
    list_name, where_desc, fields = _parse_caml_query_info(raw_query, resolver)
    if not list_name and node.b_label:
        list_name = node.b_label
    if not list_name:
        list_name = "Lista SharePoint"

    summary = f"Aktualizuj wiele elementów naraz na liście '{list_name}' (warunek: {where_desc})."

    writes = list(node.field_refs)
    if not writes and fields:
        writes = [FieldRef(name=f, internal_name=f) for f in fields]
    reads = [FieldRef(name=f, internal_name=f) for f in fields]

    plsql_code = f"""-- Masowa aktualizacja elementów listy {list_name} (warunek Nintex: {where_desc}):
l_resp := {SHP_API}.get_list_items(
    p_site_url   => :{V_SITE_URL},
    p_list_title => {sql_literal(list_name)},
    p_query      => '$select=Id&$filter=' -- TODO: przepisz warunek CAML na OData $filter
);
FOR r IN (SELECT id FROM json_table(l_resp, '$.data[*]' COLUMNS (id NUMBER PATH '$.Id'))) LOOP
    l_ref_json := {SHP_API}.update_list_item(
        p_site_url    => :{V_SITE_URL},
        p_list_title  => {sql_literal(list_name)},
        p_item_id     => r.id,
        p_fields_json => json_object('Title' VALUE NULL) -- TODO: uzupełnij mapowanie pól
    );
END LOOP;"""

    return ActionDescription(
        summary=summary,
        reads=reads,
        writes=writes,
        action_type="NWUpdateMultipleItemAdapter",
        label=node.b_label or node.t_label or f"Aktualizuj: {list_name}",
        hint_universal=f"Masowa aktualizacja rekordów na liście {list_name} spełniających warunek {where_desc}.",
        hint_apex=f"{SHP_API}.get_list_items(...) + pętla {SHP_API}.update_list_item(...);",
        plsql_code=plsql_code,
        technical_lines=[f"Lista = {list_name}", f"Warunek = {where_desc}"],
    )


TYPE_HANDLERS = {
    "NWWorkflowVariablesAdapter": _describe_variables_adapter,
    "WFIfElseAdapter": _describe_if_else,
    "WFIfElseBranchAdapter": _describe_if_else_branch,
    "NWWriteToHistoryListAdapter": _describe_write_to_history,
    "SPUpdateItemWithKeyAdapter": _describe_update_item,
    "SPSetFieldWithKeyAdapter": _describe_set_field_with_key,
    "SPSetVariableAdapter": _describe_set_variable,
    "NWRunIf2Adapter": _describe_run_if,
    "NWCommitAdapter": _describe_commit,
    "WFParallelAdapter": _describe_structural,
    "WFSequenceAdapter": _describe_structural,
    # Nowe handlery:
    "NWBuildStringAdapter": _describe_build_string,
    "NWBusinessProcessAdapter": _describe_business_process,
    "NWCalculateDateAdapter": _describe_calculate_date,
    "NWCollectionAdapter": _describe_collection_operation,
    "NWCreateSiteSpecificItemAdapter": _describe_create_site_item,
    "NWDelayForAdapter": _describe_delay,
    "NWForEachLoopAdapter": _describe_for_each_loop,
    "NWQueryListAdapter": _describe_query_list,
    "NWSendMessageAdapter": _describe_send_message,
    "NWStartWorkflow2Adapter": _describe_start_workflow,
    "NWUpdateMultipleItemAdapter": _describe_update_multiple_items,
}


# Rejestr typow akcji napotkanych, ale nie majacych dedykowanego handlera - do wglądu/rozbudowy.
UNKNOWN_TYPES_SEEN: set[str] = set()


def describe_action(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    short_type = _short_type(node.type)
    handler = TYPE_HANDLERS.get(short_type)
    if handler is None:
        UNKNOWN_TYPES_SEEN.add(node.type)
        return _describe_fallback(node, resolver)
    return handler(node, resolver)


def _describe_fallback(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    reads = list(node.field_refs)
    fields_txt = ", ".join(resolver.resolve(f.internal_name) for f in reads) if reads else ""
    label = node.t_label or _short_type(node.type)
    summary = f"[Nieopisana akcja: {label}]"
    if fields_txt:
        summary += f" (pola: {fields_txt})"
    plsql_code = f"-- TODO: wywołanie {SHP_API} dla akcji {_short_type(node.type)}"
    return ActionDescription(
        summary=summary,
        reads=reads,
        technical_lines=[f"Type = {node.type}"] + [f"{k} = {v}" for k, v in node.params.items()],
        action_type=_short_type(node.type),
        label=label,
        hint_universal="Niestandardowa akcja Nintex - wymaga analizy parametrów technicznych XML.",
        hint_apex=plsql_code,
        plsql_code=plsql_code,
    )


_LOCAL_DECLARATIONS = {
    "l_resp": "l_resp     CLOB;",
    "l_ref_json": "l_ref_json CLOB;",
}


def generate_plsql_statements(nodes: list[ActionNode], resolver: FieldResolver, indent_level: int = 1) -> list[str]:
    """Sklada fragmenty PL/SQL akcji w jedna sekwencje instrukcji (sciezka B: jeden Execute Code)."""
    lines: list[str] = []
    indent = "    " * indent_level

    def emit(code: str, level: int) -> None:
        pad = "    " * level
        lines.extend(f"{pad}{code_line}" for code_line in code.splitlines())

    for node in nodes:
        if not node.enabled:
            continue
        short_type = _short_type(node.type)
        if short_type == "NWWorkflowVariablesAdapter":
            continue
        if short_type in ("WFSequenceAdapter", "WFParallelAdapter"):
            lines.extend(generate_plsql_statements(node.children, resolver, indent_level))
            continue
        if short_type == "WFIfElseAdapter":
            cond = _plsql_condition(node.condition_el, resolver)
            lines.append(f"{indent}IF {cond} THEN")
            tak_branch = next((c for c in node.children if c.branch_label.lower() in ("tak", "true", "yes")), None)
            nie_branch = next((c for c in node.children if c.branch_label.lower() in ("nie", "false", "no")), None)
            if tak_branch is None and len(node.children) > 1:
                nie_branch, tak_branch = node.children[0], node.children[1]
            elif tak_branch is None and len(node.children) == 1:
                tak_branch = node.children[0]
            tak_lines = generate_plsql_statements(tak_branch.children, resolver, indent_level + 1) if tak_branch else []
            lines.extend(tak_lines or [f"{indent}    NULL;"])
            nie_lines = generate_plsql_statements(nie_branch.children, resolver, indent_level + 1) if nie_branch else []
            if nie_lines:
                lines.append(f"{indent}ELSE")
                lines.extend(nie_lines)
            lines.append(f"{indent}END IF;")
            continue
        if short_type == "NWRunIf2Adapter":
            cond = _plsql_condition(node.condition_el, resolver)
            lines.append(f"{indent}IF {cond} THEN")
            child_lines = generate_plsql_statements(node.children, resolver, indent_level + 1)
            lines.extend(child_lines or [f"{indent}    NULL;"])
            lines.append(f"{indent}END IF;")
            continue
        desc = describe_action(node, resolver)
        if short_type == "NWBusinessProcessAdapter":
            emit(desc.plsql_code, indent_level)
            lines.extend(generate_plsql_statements(node.children, resolver, indent_level))
            continue
        if short_type == "NWForEachLoopAdapter":
            emit(desc.plsql_code, indent_level)
            lines.extend(generate_plsql_statements(node.children, resolver, indent_level + 1))
            lines.append(f"{indent}END LOOP;")
            continue
        if desc.is_structural:
            continue
        if desc.plsql_code:
            emit(desc.plsql_code, indent_level)
    return lines


def wrap_plsql_block(statements: list[str] | str, header_comment: str = "") -> str:
    """Opakowuje instrukcje w anonimowy blok PL/SQL deklarujacy tylko uzywane zmienne lokalne."""
    body = statements if isinstance(statements, str) else "\n".join(statements)
    body = body if body.strip() else "    NULL;"
    if isinstance(statements, str):
        body = "\n".join(f"    {line}" if line else line for line in body.splitlines())
    if all(not line.strip() or line.strip().startswith("--") for line in body.splitlines()):
        body += "\n    NULL;"
    declarations = [
        f"    {decl}" for name, decl in _LOCAL_DECLARATIONS.items() if re.search(rf"\b{name}\b", body)
    ]
    head = f"-- {header_comment}\n" if header_comment else ""
    if declarations:
        return f"{head}DECLARE\n" + "\n".join(declarations) + f"\nBEGIN\n{body}\nEND;"
    return f"{head}BEGIN\n{body}\nEND;"


def build_path_b_code(nodes: list[ActionNode], resolver: FieldResolver, workflow_title: str = "") -> str:
    """Kod jednej aktywnosci Execute Code (sciezka B) realizujacej cala logike workflow Nintex."""
    statements = generate_plsql_statements(nodes, resolver, indent_level=1)
    title = workflow_title.replace("'", "''")
    statements = [
        f"    apex_debug.info('Start logiki workflow: {title}, item_id: ' || :{V_ITEM_ID});",
        *statements,
        f"    apex_debug.info('Koniec logiki workflow: {title}, item_id: ' || :{V_ITEM_ID});",
    ]
    return wrap_plsql_block(statements, "Ścieżka B: cała logika workflow Nintex w jednej aktywności Execute Code")
