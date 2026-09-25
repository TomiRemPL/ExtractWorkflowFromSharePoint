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
    """Konwertuje dowolna nazwe zmiennej lub pola SharePoint na poprawny identyfikator zmiennej PL/SQL."""
    clean = re.sub(r"[^a-zA-Z0-9_]", "_", name).strip("_").lower()
    clean = re.sub(r"_+", "_", clean)
    if not clean:
        clean = "var"
    if not clean.startswith("l_"):
        clean = f"l_{clean}"
    return clean


def _plsql_expr_from_nintex_string(val: str, item_json_var: str = "l_item_json") -> str:
    """Tłumaczy wyrażenia Nintex (np. RKU-{ItemProperty:ID} lub {ItemProperty:Nazwa}) na wyrażenie PL/SQL."""
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
            if token_name.lower() in ("id", "itemid"):
                parts.append("TO_CHAR(p_item_id)")
            else:
                parts.append(f"json_value({item_json_var}, '$.data.{token_name}')")
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


def _plsql_val_expr(el: ET.Element | None, resolver: FieldResolver, item_json_var: str = "l_item_json") -> str:
    if el is None:
        return "NULL"
    tag = el.tag
    if tag == "PrimitiveValue":
        return _plsql_expr_from_nintex_string(el.get("Value", ""), item_json_var)
    if tag == "Variable":
        return _plsql_var(el.get("Name", ""))
    if tag == "ListLookup":
        lookup_type = el.get("LookupType", "")
        field_el = el.find("Field")
        field_name = field_el.get("Name", "") if field_el is not None else ""
        nested_lookup = el.find("Lookup")
        if lookup_type == "ThisItemLookup" or nested_lookup is None:
            return f"json_value({item_json_var}, '$.data.{field_name}')"
        return f"json_value(l_ref_json, '$.data.{field_name}')"
    return "NULL"


def _plsql_condition(cond_el: ET.Element | None, resolver: FieldResolver, item_json_var: str = "l_item_json") -> str:
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
        elif op_name == "IsEmpty":
            return f"{left_expr} IS NULL"
        elif op_name == "IsNotEmpty":
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
        f"-- Pobranie bieżącego elementu przed rozpoczęciem logiki workflow:\n"
        f"l_item_json := shp_api.get_list_item(\n"
        f"    p_site_url   => c_site_url,\n"
        f"    p_list_title => '{src_list_name}',\n"
        f"    p_item_id    => p_item_id\n"
        f");"
    )
    hint_apex = f"l_item_json := shp_api.get_list_item(c_site_url, '{src_list_name}', p_item_id);"
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
    msg_expr = _plsql_expr_from_nintex_string(msg)
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


def _describe_update_item(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    list_id = node.params.get("ListId", "")
    this_item = node.params.get("ThisItem") == "true"
    target_list_name = resolver.get_list_name() if this_item else resolver.get_list_name(list_id)
    target = "w bieżącym elemencie" if this_item else f"w elemencie listy {target_list_name}"
    writes = node.field_refs
    fields_txt = ", ".join(resolver.resolve(f.internal_name, list_id) for f in writes) or "(brak pól)"

    if writes:
        pairs = []
        for f in writes:
            v_name = _plsql_var(f.name or f.internal_name)
            pairs.append(f"'{f.internal_name}' value {v_name}")
        pairs_str = ",\n        ".join(pairs)
        plsql_code = (
            f"l_resp := shp_api.update_list_item(\n"
            f"    p_site_url    => c_site_url,\n"
            f"    p_list_title  => '{target_list_name}',\n"
            f"    p_item_id     => p_item_id,\n"
            f"    p_fields_json => json_object(\n"
            f"        {pairs_str}\n"
            f"    )\n"
            f");"
        )
        hint_apex = f"l_resp := shp_api.update_list_item(c_site_url, '{target_list_name}', p_item_id, json_object(...));"
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
    src_list_name = resolver.get_list_name()
    val_expr = _plsql_expr_from_nintex_string(value)
    field_readable = resolver.resolve(field_internal, resolver.source_list_id)
    writes = [FieldRef(name=field_readable, internal_name=field_internal, field_type=node.params.get("LookupFieldType", ""))]

    plsql_code = (
        f"l_resp := shp_api.update_list_item(\n"
        f"    p_site_url    => c_site_url,\n"
        f"    p_list_title  => '{src_list_name}',\n"
        f"    p_item_id     => p_item_id,\n"
        f"    p_fields_json => json_object('{field_internal}' value {val_expr})\n"
        f");"
    )
    hint_apex = f"l_resp := shp_api.update_list_item(c_site_url, '{src_list_name}', p_item_id, json_object('{field_internal}' value {val_expr}));"

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
        field_el = value_el.find("Field")
        field_name = field_el.get("Name", "") if field_el is not None else ""
        nested_lookup = value_el.find("Lookup")
        if lookup_type == "CrossItemLookup" and nested_lookup is not None:
            target_list_id_el = value_el.find("ListId")
            target_list_id = target_list_id_el.text if target_list_id_el is not None else ""
            target_list_name = resolver.get_list_name(target_list_id)
            nested_field_el = nested_lookup.find("Field")
            nested_field_name = nested_field_el.get("Name", "") if nested_field_el is not None else "ID"

            plsql_code = (
                f"-- Pobranie powiązanego rekordu z {target_list_name}:\n"
                f"l_ref_json := shp_api.get_list_item(\n"
                f"    p_site_url   => c_site_url,\n"
                f"    p_list_title => '{target_list_name}',\n"
                f"    p_item_id    => json_value(l_item_json, '$.data.{nested_field_name}')\n"
                f");\n"
                f"{var_plsql} := json_value(l_ref_json, '$.data.{field_name}');"
            )
            hint_apex = f"{var_plsql} := json_value(shp_api.get_list_item(c_site_url, '{target_list_name}', ...), '$.data.{field_name}');"
        else:
            plsql_code = f"{var_plsql} := json_value(l_item_json, '$.data.{field_name}');"
            hint_apex = plsql_code
    elif value_el is not None and value_el.tag == "PrimitiveValue":
        val_expr = _plsql_expr_from_nintex_string(value_el.get("Value", ""))
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
    plsql_code = "-- Zmiany zatwierdzone przez shp_api.update_list_item"
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
    out_ident = _plsql_var(out_var) if out_var else "l_built_string"

    expr = _plsql_expr_from_nintex_string(input_str)
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
    out_ident = _plsql_var(out_var) if out_var else "l_new_item_id"

    summary = f"Utwórz nowy element na liście '{list_name}'."
    if out_var:
        summary += f" Nowe ID -> zmienna {out_var}."

    plsql_code = f"""{out_ident} := shp_api.create_list_item(
    p_site_url    => c_site_url,
    p_list_title  => '{list_name}',
    p_fields_json => JSON_OBJECT('Title' VALUE 'Nowy element')
);"""

    return ActionDescription(
        summary=summary,
        action_type="NWCreateSiteSpecificItemAdapter",
        label=node.t_label or f"Utwórz element w {list_name}",
        hint_universal=f"Tworzenie nowego rekordu na liście {list_name}.",
        hint_apex=f"{out_ident} := shp_api.create_list_item(...);",
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
    plsql_code = f"-- Wstrzymanie wykonania o {dur_desc}:\nDBMS_SESSION.SLEEP({total_sec});"

    return ActionDescription(
        summary=summary,
        action_type="NWDelayForAdapter",
        label=node.t_label or f"Wstrzymaj ({dur_desc})",
        hint_universal=f"Opóźnienie wykonania procesu o {dur_desc}.",
        hint_apex=f"DBMS_SESSION.SLEEP({total_sec});",
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

    plsql_code = f"""-- Pobranie elementów z listy {list_name}:
l_resp := shp_api.get_list_items(
    p_site_url   => c_site_url,
    p_list_title => '{list_name}',
    p_caml_query => '<Query><Where>...</Where></Query>'
);"""

    return ActionDescription(
        summary=summary,
        reads=reads,
        action_type="NWQueryListAdapter",
        label=node.b_label or node.t_label or f"Kwerenda: {list_name}",
        hint_universal=f"Wyszukanie elementów na liście {list_name} (warunek: {where_desc}).",
        hint_apex="l_resp := shp_api.get_list_items(...);",
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

    plsql_code = f"""-- Wysłanie powiadomienia e-mail:
apex_mail.send(
    p_to   => '{recip_str}',
    p_from => 'noreply@domain.com',
    p_subj => '{subject}',
    p_body => 'Powiadomienie z procesu biznesowego'
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
    clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", wf_name).strip("_").lower()
    clean_name = re.sub(r"_+", "_", clean_name)
    plsql_code = f"-- Uruchomienie podprocesu {wf_name}:\nprocess_wf_{clean_name}(p_item_id => p_item_id);"

    return ActionDescription(
        summary=summary,
        action_type="NWStartWorkflow2Adapter",
        label=node.b_label or node.t_label or f"Uruchom: {wf_name}",
        hint_universal=f"Uruchomienie procesu podrzędnego {wf_name}.",
        hint_apex=f"process_wf_{clean_name}(p_item_id);",
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

    plsql_code = f"""-- Masowa aktualizacja elementów listy {list_name}:
-- Warunek: {where_desc}
shp_api.update_list_item(
    p_site_url    => c_site_url,
    p_list_title  => '{list_name}',
    p_item_id     => l_target_item_id,
    p_fields_json => JSON_OBJECT(...)
);"""

    return ActionDescription(
        summary=summary,
        reads=reads,
        writes=writes,
        action_type="NWUpdateMultipleItemAdapter",
        label=node.b_label or node.t_label or f"Aktualizuj: {list_name}",
        hint_universal=f"Masowa aktualizacja rekordów na liście {list_name} spełniających warunek {where_desc}.",
        hint_apex="shp_api.update_list_item(...);",
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
    plsql_code = f"-- Wywołanie shp_api dla akcji {_short_type(node.type)}"
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

