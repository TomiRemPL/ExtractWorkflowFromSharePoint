"""Generowanie alternatywnej aktywności Execute Code po GET_LIST_ITEM."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator
from xml.etree import ElementTree as ET

from .action_catalog import (
    _COMPARISON_SQL,
    _EMPTY_OPERATORS,
    _NOT_EMPTY_OPERATORS,
    _XSI_TYPE,
    _condition_parts,
    _field_reference_value,
    _is_numeric_reference,
    _is_source_list,
    _short_type,
    _supported_cross_item_read,
    collect_blocking_reasons,
    describe_action,
    generate_plsql_statements,
)
from .apex_naming import (
    EMAIL_RE,
    P_PAYLOAD_BODY,
    V_EDITOR,
    V_ITEM_ID,
    V_LIST_TITLE,
    V_SHP_ANSWER,
    V_SITE_URL,
    is_lookup,
    is_multi,
    is_user,
    nintex_data_type,
    oracle_number_literal,
    sql_literal,
    variable_static_id,
)
from .metadata_loader import FieldResolver
from .nwf_parser import ActionNode, FieldRef
from .sensitive_data import REDACTED, contains_credential_assignment, is_sensitive_name

if TYPE_CHECKING:
    from .apex_workflow_guide import ApexSourceField, ApexWorkflowVariable


_BIND = re.compile(r":([A-Za-z0-9_][A-Za-z0-9_$#]*)")
_JSON_PATH = re.compile(r"data(?:\.[A-Za-z0-9_]+)+\Z")
_TOKEN = re.compile(r"\{([A-Za-z]+):([^}]+)\}")
_STANDARD_BINDS = {P_PAYLOAD_BODY, V_ITEM_ID, V_SITE_URL, V_LIST_TITLE, V_EDITOR, V_SHP_ANSWER}
_SUPPORTED_VARIABLE_TYPES = {
    "text", "string", "singlelineoftext", "choice",
    "number", "integer", "decimal", "counter", "currency", "spitemkey",
    "datetime", "timestamp", "date", "time",
    "memo", "multiline", "multilineoftext", "clob", "note",
    "arraylist", "collection",
}
_SUPPORTED_FIELD_TYPES = {
    "text", "choice", "note", "number", "integer", "counter", "currency", "datetime", "user", "lookup",
}
_CONTAINER_TYPES = {
    "WFSequenceAdapter", "WFParallelAdapter", "WFIfElseBranchAdapter", "WFIfElseAdapter",
    "NWRunIf2Adapter", "NWBusinessProcessAdapter", "NWForEachLoopAdapter",
}


@dataclass(frozen=True)
class CombinedExecuteCode:
    plsql_code: str
    blocking_reasons: list[str]
    required_binds: list[str]


def _enabled_nodes(nodes: list[ActionNode]) -> Iterator[ActionNode]:
    for node in nodes:
        if node.enabled:
            yield node
            yield from _enabled_nodes(node.children)


def _rewrite_binds(
    code: str, locals_by_bind: dict[str, str], *, comments: list[str] | None = None
) -> tuple[str, set[str]]:
    """Mapuje tokeny bindów, pozostawiając literały, identyfikatory i komentarze bez zmian."""
    parts: list[str] = []
    remaining: set[str] = set()
    index = 0
    length = len(code)
    while index < length:
        if code.startswith("--", index):
            end = code.find("\n", index)
            end = length if end < 0 else end
            if comments is not None:
                comments.append(code[index:end])
        elif code.startswith("/*", index):
            closing = code.find("*/", index + 2)
            if closing < 0:
                raise ValueError("Niezamknięty komentarz w wygenerowanym PL/SQL.")
            end = closing + 2
            if comments is not None:
                comments.append(code[index:end])
        else:
            quote_offset = 0
            if code[index:index + 2].lower() == "q'":
                quote_offset = 1
            elif code[index:index + 3].lower() == "nq'":
                quote_offset = 2
            if quote_offset and (index == 0 or not (code[index - 1].isalnum() or code[index - 1] in "_$#")):
                delimiter_index = index + quote_offset + 1
                if delimiter_index >= length:
                    raise ValueError("Niepoprawny literał q w wygenerowanym PL/SQL.")
                opening = code[delimiter_index]
                closing = {"[": "]", "{": "}", "(": ")", "<": ">"}.get(opening, opening)
                end_quote = code.find(closing + "'", delimiter_index + 1)
                if end_quote < 0:
                    raise ValueError("Niezamknięty literał q w wygenerowanym PL/SQL.")
                end = end_quote + 2
            elif code[index] in ("'", '"'):
                quote = code[index]
                end = index + 1
                while end < length:
                    if code[end] == quote:
                        if end + 1 < length and code[end + 1] == quote:
                            end += 2
                            continue
                        end += 1
                        break
                    end += 1
                else:
                    raise ValueError("Niezamknięty literał w wygenerowanym PL/SQL.")
            else:
                match = _BIND.match(code, index)
                if match is not None:
                    bind = match.group(1).upper()
                    replacement = locals_by_bind.get(bind)
                    if replacement is None:
                        remaining.add(bind)
                        parts.append(match.group(0))
                    else:
                        parts.append(replacement)
                    index = match.end()
                    continue
                parts.append(code[index])
                index += 1
                continue
        parts.append(code[index:end])
        index = end
    return "".join(parts), remaining


def _parallel_field_keys(fields: list[FieldRef], resolver: FieldResolver) -> set[str] | None:
    keys: set[str] = set()
    for field in fields:
        name = field.internal_name.strip()
        if not name:
            return None
        list_hint = field.list_id or resolver.source_list_id or resolver.source_list_name
        if not list_hint:
            return None
        list_key = (
            resolver.source_list_id or resolver.source_list_name
            if _is_source_list(list_hint, resolver) else list_hint
        ).strip().strip("{}").casefold()
        if name.casefold() in {"id", "itemid"}:
            keys.add(f"field:{list_key}:id")
            continue
        field_type = resolver.get_field_type(name, list_hint) or field.field_type
        mapping = resolver.resolve_rest_field(name, list_hint, lookup=is_lookup(field_type))
        if not field_type or mapping.error or mapping.warnings:
            return None
        keys.add(f"field:{list_key}:{mapping.property_name.casefold()}")
    return keys


def _parallel_variable_reads(root: ET.Element | None, text: str = "") -> set[str] | None:
    reads: set[str] = set()
    texts = [text]
    if root is not None:
        for element in root.iter():
            if element.tag == "Variable" and element.get("Name"):
                reads.add("variable:" + variable_static_id(element.get("Name", "")))
            texts.extend((element.text or "", *element.attrib.values()))
    for value in texts:
        for match in _TOKEN.finditer(value):
            if match.group(1) == "WorkflowVariable":
                reads.add("variable:" + variable_static_id(match.group(2).strip()))
            elif match.group(1) != "ItemProperty":
                return None
    return reads


def _parallel_branch(node: ActionNode, resolver: FieldResolver) -> tuple[set[str], set[str]] | None:
    if not node.enabled:
        return set(), set()
    short_type = _short_type(node.type)
    if short_type in {"WFSequenceAdapter", "WFIfElseBranchAdapter", "NWRunIf2Adapter"}:
        reads: set[str] = set()
        writes: set[str] = set()
        if short_type == "NWRunIf2Adapter":
            if node.condition_el is None or any(
                lookup.get("LookupType") != "ThisItemLookup" or lookup.find("Lookup") is not None
                for lookup in node.condition_el.iter("ListLookup")
            ):
                return None
            description = describe_action(node, resolver)
            field_reads = _parallel_field_keys(description.reads, resolver)
            variable_reads = _parallel_variable_reads(node.condition_el)
            if description.blocking_reasons or field_reads is None or variable_reads is None:
                return None
            reads.update(field_reads | variable_reads)
        for child in node.children:
            signature = _parallel_branch(child, resolver)
            if signature is None:
                return None
            reads.update(signature[0])
            writes.update(signature[1])
        return reads, writes
    if short_type not in {"SPSetVariableAdapter", "SPSetFieldWithKeyAdapter"} or node.children:
        return None
    description = describe_action(node, resolver)
    if description.blocking_reasons or description.path_b_blocking_reasons:
        return None
    value = node.param_elements.get("Value" if short_type == "SPSetVariableAdapter" else "LookupFieldValue")
    target = node.param_elements.get("VariableName")
    if short_type == "SPSetVariableAdapter" and (target is None or value is None or not target.get("Name")):
        return None
    if value is not None and value.tag == "ListLookup":
        if value.get("LookupType") == "CrossItemLookup":
            read = _supported_cross_item_read(value, resolver)
            if target is None or read is None or nintex_data_type(target.get("Type", "")) != read.result_type:
                return None
        elif value.get("LookupType", "") not in {"", "ThisItemLookup"} or value.find("Lookup") is not None:
            return None
    elif value is not None and value.tag not in {"PrimitiveValue", "Variable"}:
        return None
    field_reads = _parallel_field_keys(description.reads, resolver)
    variable_reads = _parallel_variable_reads(value, node.params.get("LookupFieldValue", ""))
    if field_reads is None or variable_reads is None:
        return None
    if short_type == "SPSetVariableAdapter":
        assert target is not None
        writes = {"variable:" + variable_static_id(target.get("Name", ""))}
    else:
        if len(description.writes) != 1 or description.writes[0].internal_name.casefold() in {"id", "itemid"}:
            return None
        field_writes = _parallel_field_keys(description.writes, resolver)
        if field_writes is None:
            return None
        writes = field_writes
    return field_reads | variable_reads, writes


def _parallel_reasons(
    nodes: list[ActionNode], resolver: FieldResolver, trace_steps: dict[int, str]
) -> list[str]:
    reasons: list[str] = []
    for node in _enabled_nodes(nodes):
        branches = [child for child in node.children if child.enabled]
        if _short_type(node.type) != "WFParallelAdapter" or len(branches) < 2:
            continue
        signatures = [_parallel_branch(branch, resolver) for branch in branches]
        unsafe = any(signature is None for signature in signatures)
        if not unsafe:
            for left_index, left in enumerate(signatures):
                assert left is not None
                for right_index, right in enumerate(signatures):
                    assert right is not None
                    if left_index != right_index and left[1] & (right[0] | right[1]):
                        unsafe = True
        if unsafe:
            step_id = trace_steps.get(id(node), "WFParallel")
            reasons.append(
                f"Równoległe gałęzie {step_id} nie mają potwierdzonej niezależności; "
                "wymagana ręczna migracja lub dowód równoważności kolejnego wykonania."
            )
    return reasons


def _logging_reasons(nodes: list[ActionNode]) -> list[str]:
    for node in _enabled_nodes(nodes):
        if _short_type(node.type) != "NWWriteToHistoryListAdapter":
            continue
        message = node.params.get("Message", "")
        for token in _TOKEN.finditer(message):
            name = token.group(2).strip()
            normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
            if token.group(1) in {"WorkflowVariable", "ItemProperty"} and (
                is_sensitive_name(name) or normalized in {"payload", "payloadbody", "ppayloadbody"}
            ):
                return ["Historia odwołuje się do potencjalnie poufnej wartości; wymagane bezpieczne logowanie."]
    return []


def _nested_action_reasons(nodes: list[ActionNode]) -> list[str]:
    return [
        f"Akcje podrzędne {_short_type(node.type)} wymagają ręcznego ustalenia kolejności i semantyki."
        for node in _enabled_nodes(nodes)
        if _short_type(node.type) not in _CONTAINER_TYPES and any(child.enabled for child in node.children)
    ]


def _conditional_structure_reasons(nodes: list[ActionNode]) -> list[str]:
    reasons: list[str] = []
    true_labels = {"tak", "true", "yes"}
    false_labels = {"nie", "false", "no"}
    for node in _enabled_nodes(nodes):
        if _short_type(node.type) != "WFIfElseAdapter":
            continue
        labels = [child.branch_label.lower() for child in node.children]
        if (
            len(labels) > 2
            or sum(label in true_labels for label in labels) > 1
            or sum(label in false_labels for label in labels) > 1
            or any(label and label not in true_labels | false_labels for label in labels)
        ):
            reasons.append("Nie ustalono jednoznacznego przypisania gałęzi warunku; wymagana ręczna migracja.")
    return reasons


def _action_mapping_reasons(nodes: list[ActionNode]) -> list[str]:
    reasons = [
        "Obliczenie daty wymaga ustalenia zmiennej wynikowej."
        for node in _enabled_nodes(nodes)
        if _short_type(node.type) == "NWCalculateDateAdapter" and not node.params.get("Output", "").strip()
    ]
    for node in _enabled_nodes(nodes):
        if _short_type(node.type) != "SPSetFieldWithKeyAdapter":
            continue
        value = node.param_elements.get("LookupFieldValue")
        if value is not None and value.tag == "PrimitiveValue" and node.params.get("LookupFieldValue") != value.get("Value", ""):
            reasons.append("Niespójna wartość pola aktualizacji wymaga ręcznego mapowania.")
    return reasons


def _action_value_roots(node: ActionNode) -> list[ET.Element | None]:
    roots = [node.condition_el, *node.param_elements.values()]
    if node.raw_el is not None:
        roots.extend(node.raw_el.find(name) for name in ("Parameters", "FieldReferences"))
        if _short_type(node.type) == "NWSendMessageAdapter":
            roots.extend(node.raw_el.find(f".//{name}") for name in ("Message", "Approvers"))
    return roots


def _cross_lookup_reasons(nodes: list[ActionNode], resolver: FieldResolver) -> list[str]:
    for node in _enabled_nodes(nodes):
        value = node.param_elements.get("Value")
        target = node.param_elements.get("VariableName")
        read = _supported_cross_item_read(value, resolver) if _short_type(node.type) == "SPSetVariableAdapter" else None
        supported = read is not None and target is not None and nintex_data_type(target.get("Type", "")) == read.result_type
        for root in _action_value_roots(node):
            if root is None:
                continue
            for lookup in root.iter("ListLookup"):
                if lookup.get("LookupType") != "CrossItemLookup" or lookup.find("Lookup") is None:
                    continue
                if supported and lookup is value:
                    continue
                return ["CrossItemLookup wymaga sprawdzenia odpowiedzi i obecności odczytywanego pola przed użyciem."]
    return []


def _variable_reference_reasons(
    nodes: list[ActionNode], workflow_variables: dict[str, ApexWorkflowVariable],
) -> list[str]:
    reasons: list[str] = []
    for node in _enabled_nodes(nodes):
        for root in _action_value_roots(node):
            if root is None:
                continue
            for reference in root.iter("Variable"):
                name = reference.get("Name", "")
                reference_type = reference.get("Type", "").strip()
                variable = workflow_variables.get(name)
                if not name or not reference_type or variable is None:
                    continue
                normalized = reference_type.casefold().replace(" ", "")
                if normalized not in _SUPPORTED_VARIABLE_TYPES or nintex_data_type(reference_type) != variable.data_type.upper():
                    reasons.append(f"Niespójny lub nieobsługiwany typ odwołania do zmiennej Nintex {name}.")
    return reasons


def _source_value_type(name: str, source_fields: list[ApexSourceField], *, lookup_id: bool = False) -> str:
    if not name or name.lower() in {"id", "itemid"}:
        return "NUMBER"
    for field in source_fields:
        if field.internal_name.lower() == name.lower():
            if lookup_id and is_lookup(field.field_type):
                return field.variables[1][1]
            return field.variables[0][1]
    return ""


def _token_value_type(
    token: re.Match[str],
    source_fields: list[ApexSourceField],
    workflow_variables: dict[str, ApexWorkflowVariable],
) -> str:
    kind, name = token.group(1), token.group(2).strip()
    if kind == "ItemProperty":
        return _source_value_type(name, source_fields)
    if kind == "WorkflowVariable":
        variable = workflow_variables.get(name)
        return variable.data_type.upper() if variable else ""
    if kind == "Common" and name in {"WebUrl", "ItemUrl"}:
        return "VARCHAR2"
    return ""


def _text_value_type(
    value: str, source_fields: list[ApexSourceField], workflow_variables: dict[str, ApexWorkflowVariable],
) -> str:
    if not value:
        return "NULL"
    tokens = list(_TOKEN.finditer(value))
    if len(tokens) == 1 and tokens[0].span() == (0, len(value)):
        return _token_value_type(tokens[0], source_fields, workflow_variables)
    if any(_token_value_type(token, source_fields, workflow_variables) == "CLOB" for token in tokens):
        return "CLOB"
    return "VARCHAR2"


def _write_value_type(
    node: ActionNode,
    internal_name: str,
    source_fields: list[ApexSourceField],
    workflow_variables: dict[str, ApexWorkflowVariable],
) -> str:
    if _short_type(node.type) == "SPSetFieldWithKeyAdapter":
        value = node.param_elements.get("LookupFieldValue")
        if value is None or value.tag == "PrimitiveValue":
            return _text_value_type(node.params.get("LookupFieldValue", ""), source_fields, workflow_variables)
    elif _short_type(node.type) == "NWCreateSiteSpecificItemAdapter" and node.raw_el is not None:
        ref = next(
            (ref for ref in node.raw_el.findall("FieldReferences/FieldReference") if ref.get("Value") == internal_name),
            None,
        )
        value = next((child for child in ref if child.tag != "Coercion"), None) if ref is not None else None
    else:
        value = _field_reference_value(node, internal_name)
        if value is None and node.raw_el is None:
            return _source_value_type(internal_name, source_fields)
    return _element_value_type(value, source_fields, workflow_variables)


def _element_value_type(
    value: ET.Element | None,
    source_fields: list[ApexSourceField],
    workflow_variables: dict[str, ApexWorkflowVariable],
) -> str:
    if value is None:
        return ""
    if value.tag == "PrimitiveValue":
        return _text_value_type(value.get("Value", ""), source_fields, workflow_variables)
    if value.tag == "Variable":
        variable = workflow_variables.get(value.get("Name", ""))
        return variable.data_type.upper() if variable else ""
    if value.tag == "ListLookup":
        if value.get("LookupType", "") != "ThisItemLookup" and value.find("Lookup") is not None:
            return "VARCHAR2"
        field = value.find("Field")
        name = field.get("Name", "") if field is not None else ""
        coercion = (value.findtext("Coercion") or "").lower()
        return _source_value_type(name, source_fields, lookup_id="lookupid" in coercion or "int" in coercion)
    return ""


def _variable_assignment_reasons(
    nodes: list[ActionNode],
    resolver: FieldResolver,
    source_fields: list[ApexSourceField],
    workflow_variables: dict[str, ApexWorkflowVariable],
) -> list[str]:
    reasons: list[str] = []
    for node in _enabled_nodes(nodes):
        if _short_type(node.type) != "SPSetVariableAdapter":
            continue
        target = node.param_elements.get("VariableName")
        name = target.get("Name", "") if target is not None else ""
        variable = workflow_variables.get(name)
        if variable is None or variable.data_type.upper() != "NUMBER":
            continue
        value = node.param_elements.get("Value")
        value_type = _element_value_type(value, source_fields, workflow_variables)
        checked_read = _supported_cross_item_read(value, resolver)
        if checked_read is not None:
            value_type = checked_read.result_type
        if value is not None and value.tag == "PrimitiveValue" and oracle_number_literal(value.get("Value", "")) is not None:
            value_type = "NUMBER"
        if value_type not in {"NUMBER", "NULL"}:
            reasons.append(f"Zmienna liczbowa {name} wymaga bezpiecznej konwersji wartości do NUMBER.")
    return reasons


def _condition_type_reasons(
    nodes: list[ActionNode],
    resolver: FieldResolver,
    source_fields: list[ApexSourceField],
    workflow_variables: dict[str, ApexWorkflowVariable],
) -> list[str]:
    reasons: list[str] = []
    for node in _enabled_nodes(nodes):
        if node.condition_el is None:
            continue
        for condition in node.condition_el.iter():
            if condition.get(_XSI_TYPE, "") != "NWConditionConfig":
                continue
            operator, left, right = _condition_parts(condition)
            left_type = _element_value_type(left, source_fields, workflow_variables)
            right_type = _element_value_type(right, source_fields, workflow_variables)
            if "NUMBER" not in {left_type, right_type} or operator in _EMPTY_OPERATORS | _NOT_EMPTY_OPERATORS:
                continue
            if operator not in _COMPARISON_SQL:
                reasons.append("Warunek liczbowy wymaga ręcznego ustalenia operatora.")
                continue
            for value, value_type, other, other_type in (
                (left, left_type, right, right_type), (right, right_type, left, left_type),
            ):
                if value_type in {"NUMBER", "NULL"}:
                    continue
                if (
                    value is not None and value.tag == "PrimitiveValue"
                    and oracle_number_literal(value.get("Value", "")) is not None
                    and other_type == "NUMBER" and _is_numeric_reference(other, resolver)
                ):
                    continue
                reasons.append("Warunek liczbowy wymaga bezpiecznej konwersji porównywanej wartości.")
    return reasons


def _write_reasons(
    nodes: list[ActionNode],
    resolver: FieldResolver,
    source_fields: list[ApexSourceField],
    workflow_variables: dict[str, ApexWorkflowVariable],
) -> list[str]:
    reasons: list[str] = []
    for node in _enabled_nodes(nodes):
        action_type = _short_type(node.type)
        if action_type not in {"SPSetFieldWithKeyAdapter", "SPUpdateItemWithKeyAdapter", "NWCreateSiteSpecificItemAdapter"}:
            continue
        for field in describe_action(node, resolver).writes:
            list_hint = "" if action_type == "SPSetFieldWithKeyAdapter" else field.list_id or node.params.get("ListId", "")
            field_type = (resolver.get_field_type(field.internal_name, list_hint) or field.field_type).strip().lower()
            label = field.internal_name or "?"
            if is_multi(field_type) or field_type not in _SUPPORTED_FIELD_TYPES:
                reasons.append(f"Pole zapisu {label} ma nieobsługiwany lub nieustalony typ {field_type or '?'}; wymagane ręczne mapowanie JSON.")
                continue
            metadata_type = resolver.get_metadata_field_type(field.internal_name, list_hint).strip().lower()
            if metadata_type and metadata_type != field_type:
                reasons.append(f"Niespójny typ pola zapisu {label} w definicji workflow i metadanych listy.")
                continue
            rest_mapping = resolver.resolve_rest_field(field.internal_name, list_hint)
            if rest_mapping.error or rest_mapping.warnings:
                reasons.append(f"Nie potwierdzono EntityPropertyName pola zapisu {label} dla listy docelowej.")
                continue
            if is_lookup(field_type):
                lookup_mapping = resolver.resolve_rest_field(field.internal_name, list_hint, lookup=True)
                if (
                    lookup_mapping.error or any("FieldRef" in warning for warning in lookup_mapping.warnings)
                    or lookup_mapping.property_name != rest_mapping.property_name
                ):
                    reasons.append(f"Pole Lookup {label} wymaga ręcznego ustalenia zapisywalnego pola relacji.")
                    continue
            if field_type in {"user", "datetime", "note"}:
                reasons.append(f"Pole zapisu {label} typu {field_type} wymaga ręcznego potwierdzenia wartości i formatu JSON.")
                continue
            value_type = _write_value_type(node, field.internal_name, source_fields, workflow_variables)
            expected = "NUMBER" if field_type in {"number", "integer", "counter", "currency", "lookup"} else "VARCHAR2"
            if value_type not in {expected, "NULL"}:
                reasons.append(f"Pole zapisu {label} wymaga wartości JSON typu {expected}; typ wyrażenia {value_type or '?'} wymaga ręcznego mapowania.")
    return reasons


def _safe_number(value: str) -> bool:
    return oracle_number_literal(value) is not None


def _initial_values(
    nodes: list[ActionNode],
    workflow_variables: dict[str, ApexWorkflowVariable],
    used_binds: set[str],
) -> tuple[dict[str, str], list[str]]:
    declarations: dict[str, ET.Element] = {}
    reasons: list[str] = []
    for node in _enabled_nodes(nodes):
        if _short_type(node.type) != "NWWorkflowVariablesAdapter" or node.raw_el is None:
            continue
        for element in node.raw_el.findall("WorkflowVariables/Variable"):
            name = element.get("Name", "").strip()
            if not name:
                continue
            key = name.casefold()
            if key in declarations:
                reasons.append(f"Powtórzona deklaracja zmiennej Nintex {name}.")
            else:
                declarations[key] = element

    initializers: dict[str, str] = {}
    for name, variable in workflow_variables.items():
        if variable.static_id.upper() not in used_binds:
            continue
        element = declarations.get(name.casefold())
        if element is None:
            reasons.append(f"Brak deklaracji wartości początkowej zmiennej Nintex {name}.")
            continue
        declared_type = element.get("Type", "").strip()
        if declared_type.casefold().replace(" ", "") not in _SUPPORTED_VARIABLE_TYPES:
            reasons.append(f"Nieobsługiwany typ zmiennej Nintex {name}; wymagane ręczne mapowanie.")
            continue
        if nintex_data_type(declared_type) != variable.data_type.upper():
            reasons.append(f"Niezgodność typu zmiennej Nintex {name}; wymagane ręczne mapowanie.")
            continue
        initiate = element.get("Initiate", "").strip().casefold()
        direction = element.get("Direction", "").strip().casefold()
        if initiate not in {"false", "0"} or direction != "none":
            reasons.append(f"Zmienna Nintex {name} wymaga ustalenia wejścia lub wyjścia workflow.")
        default = element.get("DefaultValue")
        if default is None:
            reasons.append(f"Brak wartości początkowej zmiennej Nintex {name}.")
            continue
        if not default:
            if declared_type.casefold() in {"arraylist", "collection"}:
                reasons.append(f"Pusta wartość początkowa kolekcji {name} wymaga ręcznego ustalenia.")
            continue
        if is_sensitive_name(name) or default == REDACTED or contains_credential_assignment(default) or EMAIL_RE.search(default):
            reasons.append("Pominięto poufną wartość początkową; wymagana bezpieczna konfiguracja.")
            continue
        if _TOKEN.search(default) or len(default.encode("utf-8")) > 32767:
            reasons.append(f"Wartość początkowa zmiennej Nintex {name} wymaga ręcznego odwzorowania.")
            continue
        data_type = variable.data_type.upper()
        if data_type == "NUMBER":
            number_literal = oracle_number_literal(default)
            if number_literal is not None:
                initializers[variable.static_id.upper()] = number_literal
            else:
                reasons.append(f"Niepoprawna wartość liczbowa zmiennej Nintex {name}.")
        elif data_type in {"VARCHAR2", "CLOB"}:
            if data_type == "CLOB" and element.get("Type", "").casefold() in {"arraylist", "collection"}:
                try:
                    parsed = json.loads(default)
                except json.JSONDecodeError:
                    reasons.append(f"Kolekcja początkowa {name} nie jest tablicą JSON.")
                    continue
                if not isinstance(parsed, list):
                    reasons.append(f"Kolekcja początkowa {name} nie jest tablicą JSON.")
                    continue
            initializers[variable.static_id.upper()] = sql_literal(default)
        else:
            reasons.append(f"Wartość początkowa zmiennej Nintex {name} wymaga konwersji typu {data_type}.")
    return initializers, reasons


def _declaration_type(data_type: str) -> str:
    if data_type == "VARCHAR2":
        return "VARCHAR2(32767)"
    if data_type in {"NUMBER", "CLOB", "DATE", "TIMESTAMP", "TIMESTAMP WITH TIME ZONE"}:
        return data_type
    raise ValueError(f"Nieobsługiwany typ lokalnej zmiennej PL/SQL: {data_type}")


def _field_parse(source_fields: list[ApexSourceField], locals_by_bind: dict[str, str]) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    reasons: list[str] = []
    checked_roots: set[str] = set()
    checked_paths: set[str] = set()
    for field in source_fields:
        root = f"data.{field.rest_name or field.internal_name}"
        if field.mapping_error:
            reasons.append(field.mapping_error)
        if is_multi(field.field_type):
            reasons.append(f"Pole wielowartościowe {field.internal_name} wymaga ręcznego mapowania.")
        elif field.field_type.casefold() not in _SUPPORTED_FIELD_TYPES:
            reasons.append(f"Nieobsługiwany typ pola {field.internal_name}: {field.field_type or '?'}.")
        used_variables = [variable for variable in field.variables if variable[0].upper() in locals_by_bind]
        if not used_variables:
            continue
        if not _JSON_PATH.fullmatch(root) or any(not _JSON_PATH.fullmatch(path) for _, _, path in used_variables):
            reasons.append(f"Ścieżka JSON pola {field.internal_name} wymaga ręcznego mapowania.")
            continue
        root_literal = sql_literal(root)
        if root not in checked_roots:
            lines.extend([
                f"    IF NOT apex_json.does_exist(p_path => {root_literal}, p_values => l_json_values) THEN",
                f"        RAISE_APPLICATION_ERROR(-20097, {sql_literal('GET_LIST_ITEM: brak pola ' + field.internal_name)});",
                "    END IF;",
            ])
            checked_roots.add(root)
        complex_field = is_user(field.field_type) or is_lookup(field.field_type)
        if complex_field:
            lines.extend([
                f"    IF apex_json.get_value_kind(p_path => {root_literal}, p_values => l_json_values)",
                "       NOT IN (apex_json.c_object, apex_json.c_null) THEN",
                f"        RAISE_APPLICATION_ERROR(-20097, {sql_literal('GET_LIST_ITEM: niepoprawne pole ' + field.internal_name)});",
                "    END IF;",
            ])
        for static_id, data_type, path in used_variables:
            path_literal = sql_literal(path)
            optional_lookup_id = is_lookup(field.field_type) and data_type == "NUMBER" and path == f"{root}.Id"
            if complex_field and path != root and path not in checked_paths and not optional_lookup_id:
                lines.extend([
                    f"    IF apex_json.get_value_kind(p_path => {root_literal}, p_values => l_json_values) = apex_json.c_object",
                    f"       AND NOT apex_json.does_exist(p_path => {path_literal}, p_values => l_json_values) THEN",
                    f"        RAISE_APPLICATION_ERROR(-20097, {sql_literal('GET_LIST_ITEM: brak skladowej ' + path)});",
                    "    END IF;",
                ])
                checked_paths.add(path)
            target = locals_by_bind.get(static_id.upper())
            if target is None:
                continue
            getter = "get_number" if data_type == "NUMBER" else "get_clob" if data_type == "CLOB" else "get_varchar2"
            value = f"apex_json.{getter}(p_path => {path_literal}, p_values => l_json_values)"
            if data_type.startswith("TIMESTAMP"):
                value = (
                    f"TO_TIMESTAMP_TZ(REPLACE({value}, 'Z', '+00:00'), "
                    f"CASE WHEN INSTR({value}, '.') > 0 "
                    "THEN 'YYYY-MM-DD\"T\"HH24:MI:SS.FFTZH:TZM' "
                    "ELSE 'YYYY-MM-DD\"T\"HH24:MI:SSTZH:TZM' END)"
                )
            lines.extend([
                f"    IF apex_json.does_exist(p_path => {path_literal}, p_values => l_json_values)",
                f"       AND apex_json.get_value_kind(p_path => {path_literal}, p_values => l_json_values) <> apex_json.c_null THEN",
                f"        {target} := {value};",
                "    ELSE",
                f"        {target} := NULL;",
                "    END IF;",
            ])
            if data_type == "NUMBER" and is_lookup(field.field_type) and path == f"{root}.Id":
                lines.extend([
                    f"    IF {target} IS NOT NULL AND ({target} < 1 OR {target} <> TRUNC({target})) THEN",
                    f"        RAISE_APPLICATION_ERROR(-20097, {sql_literal('GET_LIST_ITEM: niepoprawne ID pola ' + field.internal_name)});",
                    "    END IF;",
                ])
    return lines, reasons


def build_combined_execute_code(
    nodes: list[ActionNode],
    resolver: FieldResolver,
    source_fields: list[ApexSourceField],
    workflow_variables: dict[str, ApexWorkflowVariable],
    additional_binds: set[str],
    extra_blocking_reasons: list[str],
    trace_steps: dict[int, str],
    workflow_id: str,
    is_list: bool,
) -> CombinedExecuteCode:
    reasons = [
        *extra_blocking_reasons,
        *collect_blocking_reasons(nodes, resolver, "B"),
        *_parallel_reasons(nodes, resolver, trace_steps),
        *_logging_reasons(nodes),
        *_nested_action_reasons(nodes),
        *_conditional_structure_reasons(nodes),
        *_action_mapping_reasons(nodes),
        *_cross_lookup_reasons(nodes, resolver),
        *_variable_reference_reasons(nodes, workflow_variables),
        *_variable_assignment_reasons(nodes, resolver, source_fields, workflow_variables),
        *_condition_type_reasons(nodes, resolver, source_fields, workflow_variables),
        *_write_reasons(nodes, resolver, source_fields, workflow_variables),
    ]
    for field in source_fields:
        metadata_type = resolver.get_metadata_field_type(field.internal_name).strip().casefold()
        if metadata_type and field.field_type.strip() and metadata_type != field.field_type.strip().casefold():
            reasons.append(f"Niespójny typ pola źródłowego {field.internal_name} w definicji workflow i metadanych listy.")
    statements = generate_plsql_statements(
        nodes, resolver, trace_steps=trace_steps, preserve_structure=True, strict_json=True,
    )
    body = "\n".join(statements)
    comments: list[str] = []
    _, used_binds = _rewrite_binds(body, {}, comments=comments)
    if any("TODO:" in comment for comment in comments):
        reasons.append("Kod zawiera nieuzupełnione TODO wymagające ręcznej migracji.")
    if any("przybliżenie: czas wykonania kroku, nie startu workflow" in comment for comment in comments):
        reasons.append("StartDate wymaga wiarygodnego czasu rozpoczęcia workflow zamiast czasu kroku.")
    initializers, initial_reasons = _initial_values(nodes, workflow_variables, used_binds)
    reasons.extend(initial_reasons)

    locals_by_bind: dict[str, str] = {}
    declarations: dict[str, str] = {}
    for field in source_fields:
        for static_id, data_type, _ in field.variables:
            bind = static_id.upper()
            local = "l_" + bind.lower()
            if bind not in used_binds or bind in locals_by_bind:
                continue
            locals_by_bind[bind] = local
            declarations[local] = _declaration_type(data_type)
    for name, variable in workflow_variables.items():
        bind = variable.static_id.upper()
        if bind not in used_binds:
            continue
        if bind in locals_by_bind or bind in _STANDARD_BINDS or bind in additional_binds:
            reasons.append(f"Kolizja zmiennej lokalnej Nintex {name} z innym identyfikatorem {bind}.")
            continue
        local = "l_wf_" + bind.lower()
        locals_by_bind[bind] = local
        declaration = _declaration_type(variable.data_type.upper())
        if bind in initializers:
            declaration += f" := {initializers[bind]}"
        declarations[local] = declaration

    parse_lines, field_reasons = _field_parse(source_fields, locals_by_bind)
    reasons.extend(field_reasons)
    body, remaining_binds = _rewrite_binds(body, locals_by_bind)
    unknown_binds = remaining_binds - _STANDARD_BINDS - {bind.upper() for bind in additional_binds}
    for bind in sorted(unknown_binds):
        reasons.append(f"Brak bezpiecznego mapowania bindu :{bind}.")
    reasons = list(dict.fromkeys(reasons))
    if reasons:
        body = "\n".join(generate_plsql_statements(
            nodes, resolver, trace_steps=trace_steps, template=True, preserve_structure=True, strict_json=True,
        ))
        body, remaining_binds = _rewrite_binds(body, locals_by_bind)

    required_binds = sorted(
        remaining_binds | ({V_ITEM_ID, V_SITE_URL, V_LIST_TITLE, V_SHP_ANSWER} if is_list else set())
    )
    lines = [
        (
            "-- Po kroku 3 GET_LIST_ITEM: Parse i cala logika workflow w jednym Execute Code."
            if is_list else
            "-- Szablon wymaga recznego ustalenia kontekstu i sposobu uruchomienia workflow."
        ),
        "DECLARE",
        "    l_json_values apex_json.t_values;",
        "    l_nintex_step VARCHAR2(255) := 'start';",
    ]
    for local, declaration in declarations.items():
        lines.append(f"    {local} {declaration};")
    if re.search(r"\bl_resp\b", body):
        lines.append("    l_resp CLOB;")
    if re.search(r"\bl_ref_json\b", body):
        lines.append("    l_ref_json CLOB;")
    if re.search(r"\bl_ref_values\b", body):
        lines.append("    l_ref_values apex_json.t_values;")
    lines.append("BEGIN")
    if reasons:
        lines.append("    RAISE_APPLICATION_ERROR(-20090, 'Szablon wymaga recznego uzupelnienia przed wykonaniem.');")
    if is_list:
        lines.extend([
            f"    apex_debug.info('Start workflow %s, element %s', {sql_literal(workflow_id)}, TO_CHAR(:{V_ITEM_ID}));",
            "    l_nintex_step := 'GET_LIST_ITEM';",
            f"    IF :{V_ITEM_ID} IS NULL OR :{V_SITE_URL} IS NULL OR :{V_LIST_TITLE} IS NULL OR :{V_SHP_ANSWER} IS NULL THEN",
            "        RAISE_APPLICATION_ERROR(-20096, 'Brak kontekstu lub odpowiedzi GET_LIST_ITEM.');",
            "    END IF;",
            f"    apex_json.parse(p_values => l_json_values, p_source => :{V_SHP_ANSWER});",
            "    IF NOT apex_json.does_exist(p_path => 'success', p_values => l_json_values) THEN",
            "        RAISE_APPLICATION_ERROR(-20096, 'GET_LIST_ITEM: brak statusu success.');",
            "    ELSIF apex_json.get_value_kind(p_path => 'success', p_values => l_json_values) <> apex_json.c_true THEN",
            "        RAISE_APPLICATION_ERROR(-20096, 'GET_LIST_ITEM: odpowiedz nie oznacza sukcesu.');",
            "    END IF;",
            "    IF NOT apex_json.does_exist(p_path => 'data', p_values => l_json_values) THEN",
            "        RAISE_APPLICATION_ERROR(-20096, 'GET_LIST_ITEM: brak danych elementu.');",
            "    ELSIF apex_json.get_value_kind(p_path => 'data', p_values => l_json_values) <> apex_json.c_object THEN",
            "        RAISE_APPLICATION_ERROR(-20096, 'GET_LIST_ITEM: dane elementu nie sa obiektem.');",
            "    END IF;",
            *parse_lines,
        ])
    else:
        lines.append(f"    apex_debug.info('Start workflow %s', {sql_literal(workflow_id)});")
    lines.extend([
        body or "    NULL;",
        (
            f"    apex_debug.info('Koniec workflow %s, element %s', {sql_literal(workflow_id)}, TO_CHAR(:{V_ITEM_ID}));"
            if is_list else f"    apex_debug.info('Koniec workflow %s', {sql_literal(workflow_id)});"
        ),
        "EXCEPTION",
        "    WHEN OTHERS THEN",
        "        apex_debug.error('Workflow %s, krok %s, SQLCODE %s, backtrace %s',",
        f"            {sql_literal(workflow_id)}, l_nintex_step, TO_CHAR(SQLCODE), DBMS_UTILITY.FORMAT_ERROR_BACKTRACE);",
        "        RAISE;",
        "END;",
    ])
    return CombinedExecuteCode("\n".join(lines), reasons, required_binds)
