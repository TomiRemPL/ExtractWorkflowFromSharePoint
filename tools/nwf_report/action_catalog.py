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

