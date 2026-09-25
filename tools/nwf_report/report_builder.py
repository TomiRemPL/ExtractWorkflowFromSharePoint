import re
from dataclasses import dataclass

from .action_catalog import ActionDescription, _plsql_condition, _plsql_var, describe_action
from .metadata_loader import FieldResolver
from .nwf_parser import ActionNode, WorkflowModel


@dataclass
class Step:
    node: ActionNode
    desc: ActionDescription
    depth: int
    node_id: str


def _mermaid_label(text: str, max_len: int = 60) -> str:
    text = text.replace('"', "'").replace("\n", " ")
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def _build_mermaid_with_steps(actions: list[ActionNode], resolver: FieldResolver) -> tuple[str, list[Step]]:
    """Buduje diagram flowchart oraz liste krokow Step z identycznymi identyfikatorami wezlow (n1, n2...)."""
    lines = ["flowchart TD", "  start((Start))"]
    counter = [0]
    node_id_map: dict[int, str] = {}
    steps: list[Step] = []

    def new_id() -> str:
        counter[0] += 1
        return f"n{counter[0]}"

    def label_for(node: ActionNode) -> str:
        desc = describe_action(node, resolver)
        return _mermaid_label(desc.summary or node.t_label or node.type.rsplit(".", 1)[-1])

    def connect(from_ids: list[str], to_id: str, label: str = "") -> None:
        arrow = f" -- {label} -->" if label else " -->"
        for fid in from_ids:
            lines.append(f"  {fid}{arrow} {to_id}")

    def walk_tree_for_steps(nodes: list[ActionNode], depth: int = 0) -> None:
        for node in nodes:
            short_type = node.type.rsplit(".", 1)[-1]
            desc = describe_action(node, resolver)
            nid = node_id_map.get(id(node), "")
            steps.append(Step(node=node, desc=desc, depth=depth, node_id=nid))
            walk_tree_for_steps(node.children, depth + 1)

    def walk(nodes: list[ActionNode], entry_ids: list[str], entry_label: str = "") -> list[str]:
        current_ends = entry_ids
        current_label = entry_label
        for node in nodes:
            short_type = node.type.rsplit(".", 1)[-1]
            if short_type in ("WFSequenceAdapter", "WFParallelAdapter", "WFIfElseBranchAdapter"):
                current_ends = walk(node.children, current_ends, current_label)
                current_label = ""
                continue
            if short_type == "WFIfElseAdapter":
                nid = new_id()
                node_id_map[id(node)] = nid
                lines.append(f'  {nid}{{"{label_for(node)}"}}')
                connect(current_ends, nid, current_label)
                current_label = ""
                branch_ends: list[str] = []
                for child in node.children:
                    if child.children:
                        branch_ends.extend(walk(child.children, [nid], child.branch_label))
                    else:
                        branch_ends.append(nid)  # pusta galaz - laczy sie bezposrednio dalej
                current_ends = branch_ends or [nid]
                continue
            nid = new_id()
            node_id_map[id(node)] = nid
            lines.append(f'  {nid}["{label_for(node)}"]')
            connect(current_ends, nid, current_label)
            current_label = ""
            current_ends = [nid]
        return current_ends

    final_ends = walk(actions, ["start"])
    lines.append("  stop((Koniec))")
    connect(final_ends, "stop")

    # Po zarejestrowaniu ID wezlow w node_id_map zbieramy pelne drzewo krokow
    walk_tree_for_steps(actions, 0)

    return "\n".join(lines), steps


def _collect_steps(actions: list[ActionNode], resolver: FieldResolver, counter: list[int], depth: int = 0) -> list[Step]:
    """Zachowane dla kompatybilnosci wstecznej z istniejacymi testami jednostkowymi."""
    steps: list[Step] = []
    for node in actions:
        counter[0] += 1
        node_id = f"n{counter[0]}"
        desc = describe_action(node, resolver)
        steps.append(Step(node=node, desc=desc, depth=depth, node_id=node_id))
        steps.extend(_collect_steps(node.children, resolver, counter, depth + 1))
    return steps


def _build_mermaid(actions: list[ActionNode], resolver: FieldResolver) -> str:
    """Buduje diagram flowchart. Zachowane dla kompatybilnosci wstecznej."""
    mermaid_code, _ = _build_mermaid_with_steps(actions, resolver)
    return mermaid_code


def _extract_variables(actions: list[ActionNode]) -> list[dict[str, str]]:
    """Wyszukuje definicje i uzycia zmiennych workflow w akcjach."""
    variables: dict[str, dict[str, str]] = {}

    def walk(nodes: list[ActionNode]):
        for n in nodes:
            if n.type.endswith("SPSetVariableAdapter"):
                var_el = n.param_elements.get("VariableName")
                if var_el is not None:
                    name = var_el.get("Name", "")
                    if name:
                        variables[name] = {
                            "name": name,
                            "type": var_el.get("Type", "Text"),
                            "description": var_el.get("Description", "") or n.t_label or "Zmienna robocza",
                        }
            for p_val in n.params.values():
                if "{WorkflowVariable:" in p_val:
                    for part in p_val.split("{WorkflowVariable:")[1:]:
                        v_name = part.split("}")[0].strip()
                        if v_name and v_name not in variables:
                            variables[v_name] = {
                                "name": v_name,
                                "type": "Text",
                                "description": "Używana w wyrażeniach warunkowych/komunikatach",
                            }
            walk(n.children)

    walk(actions)
    return [variables[k] for k in sorted(variables.keys())]


def _extract_triggers_and_guid(actions: list[ActionNode]) -> tuple[list[str], str]:
    triggers = []
    guid = ""
    for n in actions:
        if n.type.endswith("NWWorkflowVariablesAdapter"):
            if n.params.get("StartManually") == "true":
                triggers.append("ręcznie")
            if n.params.get("StartOnCreate") == "true":
                triggers.append("utworzenie elementu")
            if n.params.get("StartOnChange") == "true":
                triggers.append("zmiana elementu")
            guid = n.params.get("Id", "")
            break
    return triggers or ["ręcznie"], guid


def _generate_plsql_statements(nodes: list[ActionNode], resolver: FieldResolver, indent_level: int = 1) -> list[str]:
    lines: list[str] = []
    indent = "    " * indent_level
    for node in nodes:
        if not node.enabled:
            continue
        short_type = node.type.rsplit(".", 1)[-1]
        if short_type == "NWWorkflowVariablesAdapter":
            continue
        if short_type in ("WFSequenceAdapter", "WFParallelAdapter"):
            lines.extend(_generate_plsql_statements(node.children, resolver, indent_level))
            continue
        if short_type == "WFIfElseAdapter":
            cond = _plsql_condition(node.condition_el, resolver)
            lines.append(f"{indent}IF {cond} THEN")
            tak_branch = next((c for c in node.children if c.branch_label.lower() in ("tak", "true")), None)
            nie_branch = next((c for c in node.children if c.branch_label.lower() in ("nie", "false")), None)
            if tak_branch is None and len(node.children) > 1:
                nie_branch, tak_branch = node.children[0], node.children[1]
            elif tak_branch is None and len(node.children) == 1:
                tak_branch = node.children[0]

            if tak_branch and tak_branch.children:
                lines.extend(_generate_plsql_statements(tak_branch.children, resolver, indent_level + 1))
            else:
                lines.append(f"{indent}    NULL;")

            if nie_branch and nie_branch.children:
                lines.append(f"{indent}ELSE")
                lines.extend(_generate_plsql_statements(nie_branch.children, resolver, indent_level + 1))
            lines.append(f"{indent}END IF;")
            continue
        if short_type == "NWRunIf2Adapter":
            cond = _plsql_condition(node.condition_el, resolver)
            lines.append(f"{indent}IF {cond} THEN")
            if node.children:
                lines.extend(_generate_plsql_statements(node.children, resolver, indent_level + 1))
            else:
                lines.append(f"{indent}    NULL;")
            lines.append(f"{indent}END IF;")
            continue

        desc = describe_action(node, resolver)
        if desc.is_structural:
            continue
        if desc.plsql_code:
            for code_line in desc.plsql_code.splitlines():
                lines.append(f"{indent}{code_line}")
    return lines


def build_plsql_procedure(wf: WorkflowModel, resolver: FieldResolver) -> str:
    """Buduje kompletna, minimalistyczna i gotowa do kompilacji procedure PL/SQL orkiestrujaca workflow za pomoca SHP_API."""
    raw_name = wf.title or wf.source_path.stem
    safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", raw_name).strip("_").lower()
    safe_name = re.sub(r"_+", "_", safe_name)
    proc_name = f"process_wf_{safe_name}"

    src = wf.source_list
    src_name = src.list_name if src else resolver.source_list_name or "Lista_Zrodlowa"

    variables = _extract_variables(wf.actions)
    var_lines = []
    seen_vars = set()
    for v in variables:
        v_ident = _plsql_var(v["name"])
        if v_ident not in seen_vars:
            seen_vars.add(v_ident)
            v_type = "NUMBER" if v["type"].lower() in ("integer", "number") else "VARCHAR2(4000)"
            var_lines.append(f"    {v_ident:<30} {v_type};")

    var_decls = "\n".join(var_lines)
    if var_decls:
        var_decls = f"    -- Zmienne workflow:\n{var_decls}\n"

    body_lines = _generate_plsql_statements(wf.actions, resolver, indent_level=1)
    body_text = "\n".join(body_lines) if body_lines else "    NULL;"

    return f"""CREATE OR REPLACE PROCEDURE {proc_name} (
    p_item_id IN NUMBER
) AS
    c_site_url CONSTANT VARCHAR2(400) := 'https://sharepoint.domain.com/sites/...';
    l_item_json CLOB;
    l_resp      CLOB;
    l_ref_json  CLOB;
{var_decls}BEGIN
    apex_debug.info('Start workflow: {wf.title}, item_id: ' || p_item_id);

    -- 1. Pobranie danych biezacego elementu
    l_item_json := shp_api.get_list_item(
        p_site_url   => c_site_url,
        p_list_title => '{src_name}',
        p_item_id    => p_item_id
    );

    -- 2. Logika biznesowa workflow
{body_text}

    apex_debug.info('Koniec workflow: {wf.title}, item_id: ' || p_item_id);
END {proc_name};
/"""


def build_workflow_data(wf: WorkflowModel, resolver: FieldResolver) -> dict:
    """Buduje ustrukturyzowany slownik z danymi workflow do celow serializacji JSON / raportu HTML."""
    mermaid_code, steps = _build_mermaid_with_steps(wf.actions, resolver)
    triggers, guid = _extract_triggers_and_guid(wf.actions)
    variables = _extract_variables(wf.actions)

    src = wf.source_list
    src_name = src.list_name if src else "(nieznana)"
    src_id = src.list_id if src else ""
    other_lists = [lr.list_name for lr in wf.list_references if not lr.is_source_list]

    all_reads: dict[str, dict] = {}
    all_writes: dict[str, dict] = {}

    steps_data: list[dict] = []
    steps_data.append({
        "node_id": "start",
        "label": "Start",
        "type": "WorkflowStart",
        "short_type": "Start",
        "summary": f"Uruchomienie workflow dla listy {src_name}.",
        "branch_label": "",
        "depth": 0,
        "condition_text": "",
        "reads": [],
        "writes": [],
        "hint_universal": "Odtwórz te same reguły uruchomienia w docelowym mechanizmie orkiestracji.",
        "hint_apex": f"l_item_json := shp_api.get_list_item(c_site_url, '{src_name}', p_item_id);",
        "plsql_code": f"-- Pobranie bieżącego elementu listy źródłowej:\nl_item_json := shp_api.get_list_item(\n    p_site_url   => c_site_url,\n    p_list_title => '{src_name}',\n    p_item_id    => p_item_id\n);",
        "technical_lines": ["Triggery: " + ", ".join(triggers), f"Lista źródłowa: {src_name}", f"ID listy: {src_id}"],
        "is_structural": True,
        "enabled": True,
    })
    for s in steps:
        short_type = s.node.type.rsplit(".", 1)[-1]
        reads_info = []
        for r in s.desc.reads:
            if not r.internal_name:
                continue
            title = resolver.get_title(r.internal_name, src_id)
            reads_info.append({
                "internal_name": r.internal_name,
                "display_name": title,
                "field_type": r.field_type,
                "list_id": src_id,
                "list_name": src_name,
            })
            all_reads[r.internal_name] = reads_info[-1]

        writes_info = []
        target_list_id = s.node.params.get("ListId") or src_id
        target_list_name = src_name if target_list_id == src_id else target_list_id
        for w in s.desc.writes:
            if not w.internal_name:
                continue
            title = resolver.get_title(w.internal_name, target_list_id)
            writes_info.append({
                "internal_name": w.internal_name,
                "display_name": title,
                "field_type": w.field_type,
                "list_id": target_list_id,
                "list_name": target_list_name,
            })
            all_writes[w.internal_name] = writes_info[-1]

        steps_data.append({
            "node_id": s.node_id,
            "label": s.desc.label or s.node.t_label or short_type,
            "type": s.node.type,
            "short_type": short_type,
            "summary": s.desc.summary,
            "branch_label": s.node.branch_label,
            "depth": s.depth,
            "condition_text": s.desc.condition_text,
            "reads": reads_info,
            "writes": writes_info,
            "hint_universal": s.desc.hint_universal,
            "hint_apex": s.desc.hint_apex,
            "plsql_code": s.desc.plsql_code,
            "technical_lines": s.desc.technical_lines,
            "is_structural": s.desc.is_structural,
            "enabled": s.node.enabled,
        })
    steps_data.append({
        "node_id": "stop",
        "label": "Koniec",
        "type": "WorkflowStop",
        "short_type": "Koniec",
        "summary": "Zakończenie ścieżki workflow po wykonaniu poprzednich akcji.",
        "branch_label": "",
        "depth": 0,
        "condition_text": "",
        "reads": [],
        "writes": [],
        "hint_universal": "Zamknij proces bez dodatkowej akcji, jeżeli wcześniejsze kroki zakończyły się poprawnie.",
        "hint_apex": "apex_debug.info('Koniec workflow: ' || p_item_id);",
        "plsql_code": "apex_debug.info('Koniec workflow: ' || p_item_id);",
        "technical_lines": ["Węzeł syntetyczny dodany przez generator raportu HTML."],
        "is_structural": True,
        "enabled": True,
    })

    # Zbiorczy slownik pol
    fields_dict: dict[str, dict] = {}
    for internal_name in set(all_reads) | set(all_writes):
        read_obj = all_reads.get(internal_name)
        write_obj = all_writes.get(internal_name)
        base = read_obj or write_obj
        fields_dict[internal_name] = {
            "internal_name": internal_name,
            "display_name": base["display_name"] if base else resolver.get_title(internal_name),
            "list_name": base["list_name"] if base else src_name,
            "list_id": base["list_id"] if base else src_id,
            "field_type": base.get("field_type", "") if base else "",
            "is_read": internal_name in all_reads,
            "is_written": internal_name in all_writes,
        }

    # Dolaczenie pol ze zdefiniowanych list references
    for lr in wf.list_references:
        for f in lr.fields:
            if f.internal_name and f.internal_name not in fields_dict:
                fields_dict[f.internal_name] = {
                    "internal_name": f.internal_name,
                    "display_name": f.name or resolver.get_title(f.internal_name, lr.list_id),
                    "list_name": lr.list_name,
                    "list_id": lr.list_id,
                    "field_type": f.field_type,
                    "is_read": False,
                    "is_written": False,
                }

    sorted_fields = [fields_dict[k] for k in sorted(fields_dict.keys(), key=lambda x: fields_dict[x]["display_name"].lower())]

    key = "".join(c if c.isalnum() or c in " _-." else "_" for c in (wf.title or wf.source_path.stem)).strip()

    return {
        "key": key,
        "title": wf.title or wf.source_path.stem,
        "description": wf.description,
        "source_file": wf.source_path.name,
        "source_list_name": src_name,
        "source_list_id": src_id,
        "other_lists": other_lists,
        "triggers": triggers,
        "workflow_guid": guid,
        "actions_count": len([s for s in steps_data if not s["is_structural"] and s["short_type"] != "NWWorkflowVariablesAdapter"]),
        "mermaid_code": mermaid_code,
        "steps": steps_data,
        "fields": sorted_fields,
        "variables": variables,
        "plsql_procedure": build_plsql_procedure(wf, resolver),
    }


def build_report(wf: WorkflowModel, resolver: FieldResolver) -> str:
    mermaid_code, steps = _build_mermaid_with_steps(wf.actions, resolver)

    lines: list[str] = []
    lines.append(f"# {wf.title}")
    lines.append("")
    if wf.description:
        lines.append(f"> {wf.description.replace(chr(10), chr(10) + '> ')}")
        lines.append("")

    src = wf.source_list
    lines.append("## Podstawowe informacje")
    lines.append("")
    lines.append(f"- **Lista źródłowa:** {src.list_name if src else '(nieznana)'}")
    lines.append(f"- **Plik źródłowy:** `{wf.source_path.name}`")
    other_lists = [lr.list_name for lr in wf.list_references if not lr.is_source_list]
    if other_lists:
        lines.append(f"- **Inne listy używane przez workflow:** {', '.join(other_lists)}")
    lines.append("")

    lines.append("## Diagram przepływu")
    lines.append("")
    lines.append("```mermaid")
    lines.append(mermaid_code)
    lines.append("```")
    lines.append("")

    lines.append("## Kroki workflow")
    lines.append("")
    for step in steps:
        if step.desc.is_structural:
            continue
        indent = "  " * step.depth
        branch_prefix = f"**[{step.node.branch_label}]** " if step.node.branch_label else ""
        node_id_badge = f"`[{step.node_id}]` " if step.node_id else ""
        status = "" if step.node.enabled else " _(wyłączona)_"
        lines.append(f"{indent}- {node_id_badge}{branch_prefix}{step.desc.summary}{status}")
        if step.desc.hint_universal:
            lines.append(f"{indent}  > **Wskazówka migracji**: {step.desc.hint_universal}")
        if step.desc.plsql_code:
            lines.append(f"{indent}  ```plsql")
            for tl in step.desc.plsql_code.splitlines():
                lines.append(f"{indent}  {tl}")
            lines.append(f"{indent}  ```")
        if step.desc.technical_lines:
            lines.append(f"{indent}  <details><summary>Szczegóły techniczne</summary>")
            lines.append("")
            lines.append(f"{indent}  ```")
            for tl in step.desc.technical_lines:
                lines.append(f"{indent}  {tl}")
            lines.append(f"{indent}  ```")
            lines.append(f"{indent}  </details>")
    lines.append("")

    variables = _extract_variables(wf.actions)
    if variables:
        lines.append("## Zmienne przepływu pracy")
        lines.append("")
        lines.append("| Zmienna | Typ | Opis / Rola |")
        lines.append("|---|---|---|")
        for v in variables:
            lines.append(f"| `{v['name']}` | {v['type']} | {v['description']} |")
        lines.append("")

    all_reads = {f.internal_name: f for s in steps for f in s.desc.reads if f.internal_name}
    all_writes = {f.internal_name: f for s in steps for f in s.desc.writes if f.internal_name}

    lines.append("## Pola odczytywane / zapisywane")
    lines.append("")
    lines.append("| Pole | Odczyt | Zapis |")
    lines.append("|---|---|---|")
    for internal_name in sorted(set(all_reads) | set(all_writes)):
        readable = resolver.resolve(internal_name)
        lines.append(f"| {readable} | {'X' if internal_name in all_reads else ''} | {'X' if internal_name in all_writes else ''} |")
    lines.append("")

    lines.append("### Słownik pól i identyfikatory techniczne")
    lines.append("")
    lines.append("| Nazwa biznesowa | SharePoint InternalName | Typ | Odczyt | Zapis |")
    lines.append("|---|---|---|---|---|")
    for internal_name in sorted(set(all_reads) | set(all_writes)):
        title = resolver.get_title(internal_name)
        lines.append(f"| {title} | `{internal_name}` | Tekst/Ref | {'Tak' if internal_name in all_reads else '-'} | {'Tak' if internal_name in all_writes else '-'} |")
    lines.append("")

    plsql_proc = build_plsql_procedure(wf, resolver)
    lines.append("## Kompletna procedura orkiestracji PL/SQL (Oracle APEX / SHP_API)")
    lines.append("")
    lines.append("Poniższy kod stanowi gotowy, kompletny szkielet procedury PL/SQL do wdrożenia w Oracle APEX, realizujący całą logikę workflow za pośrednictwem pakietu `SHP_API`:")
    lines.append("")
    lines.append("```plsql")
    lines.append(plsql_proc)
    lines.append("```")
    lines.append("")

    return "\n".join(lines)

