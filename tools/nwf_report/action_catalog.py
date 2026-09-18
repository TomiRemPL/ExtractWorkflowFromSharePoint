"""Katalog akcji Nintex Workflow: tlumaczenie akcji (NWActionConfig) na jezyk biznesowy.

Kazdy handler otrzymuje ActionNode + FieldResolver i zwraca ActionDescription
(zdanie biznesowe + listy pol odczytywanych/zapisywanych + surowe dane techniczne).
Nieznane typy akcji dostaja opis awaryjny (fallback), zeby narzedzie dzialalo
generycznie takze dla akcji spoza tego zestawu przykladowych plikow.
"""
from __future__ import annotations

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
    return ActionDescription(
        summary=f"Start workflow '{name}'. Uruchamiane: {trig_txt}.",
        technical_lines=[f"{k} = {v}" for k, v in node.params.items()],
        action_type="NWWorkflowVariablesAdapter",
        label=name or "Start workflow",
        hint_universal=f"Wyzwalacz procesu (Triggers: {trig_txt}). Punkt wejścia przyjmujący parametr itemId.",
        hint_apex="Wywołanie z endpointu REST / ORDS lub trigger bazodanowy / start procesu w Flows for APEX.",
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
    return ActionDescription(
        summary=f"Warunek: JEŻELI {cond_txt}",
        reads=_extract_condition_fields(node.condition_el),
        technical_lines=[f"ConditionUse={node.condition_use}"],
        action_type="WFIfElseAdapter",
        label=label,
        condition_text=cond_txt,
        hint_universal=f"Bramka decyzyjna (Exclusive Gateway / IF): sprawdzenie warunku logicznego: {cond_txt}.",
        hint_apex=f"Instrukcja IF ... THEN ... ELSIF w PL/SQL lub Exclusive Gateway w Flows for APEX.",
    )


def _describe_if_else_branch(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    return ActionDescription(summary="", is_structural=True, action_type="WFIfElseBranchAdapter")


def _describe_write_to_history(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    msg = node.params.get("Message", "")
    short = msg.splitlines()[0] if msg else ""
    return ActionDescription(
        summary=f"Zapisz wpis w historii przepływu: „{short}”" + (" (…)" if len(msg.splitlines()) > 1 else ""),
        technical_lines=[f"Message = {msg}"],
        action_type="NWWriteToHistoryListAdapter",
        label=node.t_label or "Zapis historii",
        hint_universal="Zapis audytowy do dziennika zdarzeń (Audit Log).",
        hint_apex="APEX_DEBUG.INFO() lub INSERT INTO t_workflow_history(run_id, item_id, message, created_at);",
    )


def _describe_update_item(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    list_id = node.params.get("ListId", "")
    this_item = node.params.get("ThisItem") == "true"
    target = "w bieżącym elemencie" if this_item else f"w elemencie listy {list_id}"
    writes = node.field_refs
    fields_txt = ", ".join(resolver.resolve(f.internal_name, list_id) for f in writes) or "(brak pól)"
    return ActionDescription(
        summary=f"Zaktualizuj element {target}: ustaw pola {fields_txt}.",
        writes=writes,
        technical_lines=[f"ListId = {list_id}", f"ThisItem = {this_item}"],
        action_type="SPUpdateItemWithKeyAdapter",
        label=node.t_label or "Aktualizacja pól",
        hint_universal=f"Aktualizacja danych elementu ({fields_txt}). W systemie docelowym UPDATE lub REST PATCH/MERGE.",
        hint_apex="UPDATE tabela SET ... WHERE id = :id; lub REST MERGE z nagłówkiem If-Match (weryfikacja ETag).",
    )


def _describe_set_field_with_key(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    field_internal = node.params.get("LookupField", "")
    value = node.params.get("LookupFieldValue", "")
    field_readable = resolver.resolve(field_internal, resolver.source_list_id)
    writes = [FieldRef(name=field_readable, internal_name=field_internal, field_type=node.params.get("LookupFieldType", ""))]
    return ActionDescription(
        summary=f"Ustaw pole {field_readable} na wartość: „{value}”.",
        writes=writes,
        technical_lines=[f"{k} = {v}" for k, v in node.params.items()],
        action_type="SPSetFieldWithKeyAdapter",
        label=node.t_label or f"Ustaw {field_readable}",
        hint_universal=f"Ustawienie pola {field_readable} = '{value}'.",
        hint_apex=f"UPDATE tabela SET {field_internal} = '{value}' WHERE id = :id;",
    )


def _describe_set_variable(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    var_name_el = node.param_elements.get("VariableName")
    var_name = var_name_el.get("Name", "?") if var_name_el is not None else "?"
    value_el = node.param_elements.get("Value")
    value_txt = _render_value_expr(value_el, resolver)
    label = node.t_label
    prefix = f"{label}: " if label else ""
    return ActionDescription(
        summary=f"{prefix}Zapisz w zmiennej '{var_name}' wartość: {value_txt}.",
        reads=_extract_condition_fields(value_el),
        technical_lines=[f"{k} = {v}" for k, v in node.params.items()],
        action_type="SPSetVariableAdapter",
        label=label or f"Zmienna {var_name}",
        hint_universal=f"Obliczenie/odczyt i zapis do zmiennej lokalnej '{var_name}'.",
        hint_apex=f"l_{var_name.replace('-', '_')} := {value_txt}; lub flow_process.set_var(p_process_id, '{var_name}', ...);",
    )


def _describe_run_if(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    cond_txt = _render_condition(node.condition_el, resolver)
    summary = f"Wykonaj poniższe kroki TYLKO JEŻELI {cond_txt}" if cond_txt else "Wykonaj warunkowo poniższe kroki"
    return ActionDescription(
        summary=summary,
        reads=_extract_condition_fields(node.condition_el),
        action_type="NWRunIf2Adapter",
        label=node.t_label or "Wykonaj jeśli",
        condition_text=cond_txt,
        hint_universal=f"Warunek wykonania bloku podrzędnego: IF ({cond_txt}).",
        hint_apex=f"IF {cond_txt} THEN ... END IF;",
    )


def _describe_commit(node: ActionNode, resolver: FieldResolver) -> ActionDescription:
    return ActionDescription(
        summary="Zapisz (zatwierdź) zebrane zmiany w elemencie.",
        action_type="NWCommitAdapter",
        label=node.t_label or "Zatwierdzenie transakcji",
        hint_universal="Zatwierdzenie bieżącego stanu transakcji (COMMIT).",
        hint_apex="COMMIT; lub przejście etapu procesu BPMN.",
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
    return ActionDescription(
        summary=summary,
        reads=reads,
        technical_lines=[f"Type = {node.type}"] + [f"{k} = {v}" for k, v in node.params.items()],
        action_type=_short_type(node.type),
        label=label,
        hint_universal="Niestandardowa akcja Nintex - wymaga analizy parametrów technicznych XML.",
        hint_apex="Do zaimplementowania jako dedykowany moduł PL/SQL lub wywołanie REST.",
    )

