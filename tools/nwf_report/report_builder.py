import re
from dataclasses import dataclass

from .action_catalog import ActionDescription, describe_action, generate_plsql_statements
from .apex_naming import P_PAYLOAD_BODY, SHP_API, sql_literal, workflow_static_id
from .apex_workflow_guide import format_markdown_apex_section, generate_apex_workflow_spec
from .metadata_loader import FieldResolver
from .nwf_parser import ActionNode, FieldRef, WorkflowModel


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
            if short_type == "NWBusinessProcessAdapter":

                nid = new_id()
                node_id_map[id(node)] = nid
                lines.append(f'  {nid}[["{label_for(node)}"]]')
                connect(current_ends, nid, current_label)
                current_label = ""
                if node.children:
                    current_ends = walk(node.children, [nid], "")
                else:
                    current_ends = [nid]
                continue
            if short_type == "NWForEachLoopAdapter":
                nid = new_id()
                node_id_map[id(node)] = nid
                lines.append(f'  {nid}{{"{label_for(node)}"}}')
                connect(current_ends, nid, current_label)
                current_label = ""
                if node.children:
                    loop_ends = walk(node.children, [nid], "Kolejny element")
                    connect(loop_ends, nid, "Następny")
                current_ends = [nid]
                current_label = "Koniec pętli"
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
            if n.params.get("StartManually", "").lower() == "true":
                triggers.append("ręcznie")
            if n.params.get("StartOnCreate", "").lower() == "true":
                triggers.append("utworzenie elementu")
            if n.params.get("StartOnChange", "").lower() == "true":
                triggers.append("zmiana elementu")
            guid = n.params.get("Id", "")
            break
    return triggers or ["nie ustalono"], guid


# Zgodnosc wsteczna: generator instrukcji PL/SQL przeniesiono do action_catalog (sciezka B).
_generate_plsql_statements = generate_plsql_statements


def build_dispatcher_package(workflows_data: list[dict]) -> str:
    """Generuje pakiet pkg_shp_dispatcher: webhook SharePoint (workflow.xaml) -> apex_workflow.start_workflow."""
    case_branches = []
    for wf in workflows_data:
        if wf.get("workflow_type", "").strip().casefold() != "list":
            continue
        title = wf.get("title", "")
        spec = wf.get("apex_workflow_spec") or {}
        static_id = spec.get("static_id") or workflow_static_id(title or wf.get("source_file", ""))
        case_branches.append(f"            WHEN {sql_literal(title)} THEN l_static_id := {sql_literal(static_id)};")

    case_sql = "\n".join(case_branches) if case_branches else "            WHEN NULL THEN NULL;"

    return f"""CREATE OR REPLACE PACKAGE pkg_shp_dispatcher AS
    /**
     * Glowny punkt wejscia dla webhooka SharePoint Designer 2013 (workflow.xaml).
     * Endpoint ORDS: POST /ords/shp/nintex/main
     * Uruchamia instancje APEX Workflow (Shared Components > Workflows) przekazujac
     * caly payload w parametrze {P_PAYLOAD_BODY}; dalsze kroki (Retrieve Payload,
     * {SHP_API}.GET_LIST_ITEM) wykonuje juz sam workflow.
     *
     * @param p_body           JSON payload przekazany w ciele zadania HTTP POST
     * @param p_status_code    Kod odpowiedzi HTTP zwracany do SharePoint (200 / 400 / 500)
     * @param p_status_message Komunikat zwrotny logowany w historii SharePoint
     */
    PROCEDURE handle_webhook (
        p_body           IN  CLOB,
        p_status_code    OUT NUMBER,
        p_status_message OUT VARCHAR2
    );
END pkg_shp_dispatcher;
/

CREATE OR REPLACE PACKAGE BODY pkg_shp_dispatcher AS

    -- TODO: ustaw ID aplikacji APEX zawierajacej definicje workflow (Shared Components > Workflows).
    c_app_id    CONSTANT NUMBER        := NULL;
    c_page_id   CONSTANT NUMBER        := 1;
    c_apex_user CONSTANT VARCHAR2(255) := 'SHP_WEBHOOK';

    PROCEDURE handle_webhook (
        p_body           IN  CLOB,
        p_status_code    OUT NUMBER,
        p_status_message OUT VARCHAR2
    ) IS
        l_id           NUMBER;
        l_guid         VARCHAR2(64);
        l_title        VARCHAR2(500);
        l_association  VARCHAR2(255);
        l_associator   VARCHAR2(255);
        l_initiator    VARCHAR2(255);
        l_instance     VARCHAR2(64);
        l_list_id      VARCHAR2(64);
        l_list_name    VARCHAR2(255);
        l_url_site     VARCHAR2(1000);
        l_content_type VARCHAR2(100);
        l_static_id    VARCHAR2(255);
        l_params       apex_workflow.t_workflow_parameters;
        l_workflow_id  NUMBER;
    BEGIN
        IF p_body IS NULL THEN
            p_status_code := 400;
            p_status_message := 'Blad: pusty payload JSON';
            RETURN;
        END IF;

        -- Rozpakowanie atrybutow payloadu (workflow.xaml) potrzebnych do routingu i logowania
        l_id           := json_value(p_body, '$.id' RETURNING NUMBER);
        l_guid         := json_value(p_body, '$.guid');
        l_title        := json_value(p_body, '$.title');
        l_association  := json_value(p_body, '$.association');
        l_associator   := json_value(p_body, '$.associator');
        l_initiator    := json_value(p_body, '$.initiator');
        l_instance     := json_value(p_body, '$.instance');
        l_list_id      := json_value(p_body, '$.list');
        l_list_name    := json_value(p_body, '$.list_name');
        l_url_site     := json_value(p_body, '$.url_site');
        l_content_type := json_value(p_body, '$.content_type');

        apex_debug.info('Odebrano webhook z SharePoint: wf=' || l_association ||
                        ', lista=' || l_list_name || ', id=' || l_id || ', user=' || l_initiator);

        -- Zgodnie z workflow.xaml: ignorowanie folderow
        IF l_content_type = 'Folder' THEN
            p_status_code := 200;
            p_status_message := 'Folder Ignored';
            RETURN;
        END IF;

        -- Routing: association (nazwa workflow Nintex) -> Static ID workflow APEX
        CASE l_association
{case_sql}
            ELSE
                apex_debug.warn('Nieznany workflow (association): ' || l_association);
                p_status_code := 200;
                p_status_message := 'Ostrzezenie: brak workflow APEX dla association=' || l_association;
                RETURN;
        END CASE;

        l_params(1).static_id := '{P_PAYLOAD_BODY}';
        l_params(1).value.data_type := apex_session_state.c_data_type_clob;
        l_params(1).value.clob_value := p_body;

        -- Wywolanie z ORDS odbywa sie poza sesja APEX - tworzymy ja na czas startu workflow.
        apex_session.create_session(
            p_app_id   => c_app_id,
            p_page_id  => c_page_id,
            p_username => c_apex_user
        );

        l_workflow_id := apex_workflow.start_workflow(
            p_application_id => c_app_id,
            p_static_id      => l_static_id,
            p_parameters     => l_params,
            p_initiator      => l_initiator,
            p_detail_pk      => TO_CHAR(l_id)
        );

        apex_session.delete_session;

        p_status_code := 200;
        p_status_message := 'OK: workflow ' || l_static_id || ' uruchomiony (workflow_id=' || l_workflow_id || ')';

    EXCEPTION
        WHEN OTHERS THEN
            p_status_code := 500;
            p_status_message := 'Blad wykonania: ' || SQLERRM;
            apex_debug.error('Blad pkg_shp_dispatcher: ' || SQLERRM || ' | ' || DBMS_UTILITY.format_error_backtrace);
            BEGIN
                apex_session.delete_session;
            EXCEPTION
                WHEN OTHERS THEN NULL;
            END;
    END handle_webhook;

END pkg_shp_dispatcher;
/"""


def _collect_report_fields(
    wf: WorkflowModel, steps: list[Step], resolver: FieldResolver
) -> tuple[dict[str, tuple[list[dict], list[dict]]], dict[tuple[str, str], dict]]:
    source = wf.source_list
    source_id = source.list_id if source else ""
    source_name = source.list_name if source else "(nieznana)"
    fields: dict[tuple[str, str], dict] = {}
    step_fields: dict[str, tuple[list[dict], list[dict]]] = {}

    def field_info(ref: FieldRef, fallback_list: str) -> tuple[tuple[str, str], dict]:
        hint = ref.list_id or fallback_list
        normalized = hint.strip("{}").casefold()
        list_ref = next(
            (lr for lr in wf.list_references if normalized and normalized in {
                lr.list_id.strip("{}").casefold(), lr.list_name.casefold()
            }),
            None,
        )
        list_id = (list_ref.list_id or hint) if list_ref else hint
        list_name = list_ref.list_name if list_ref else (resolver.get_list_name(hint) if hint else source_name)
        key = (list_id.strip("{}").casefold(), ref.internal_name.casefold())
        return key, {
            "internal_name": ref.internal_name,
            "display_name": resolver.get_title(ref.internal_name, list_id),
            "field_type": resolver.get_field_type(ref.internal_name, list_id) or ref.field_type,
            "list_id": list_id,
            "list_name": list_name,
        }

    for step in steps:
        reads_info: list[dict] = []
        writes_info: list[dict] = []
        target_id = step.node.params.get("ListId") or source_id
        for refs, fallback, is_read, result in (
            (step.desc.reads, source_id, True, reads_info),
            (step.desc.writes, target_id, False, writes_info),
        ):
            for ref in refs:
                if not ref.internal_name:
                    continue
                key, info = field_info(ref, fallback)
                result.append(info)
                aggregate = fields.setdefault(key, {**info, "is_read": False, "is_written": False})
                aggregate["is_read" if is_read else "is_written"] = True
        step_fields[step.node_id] = (reads_info, writes_info)

    for lr in wf.list_references:
        for ref in lr.fields:
            if ref.internal_name:
                key, info = field_info(ref, lr.list_id or lr.list_name)
                fields.setdefault(key, {**info, "is_read": False, "is_written": False})
    return step_fields, fields


def build_workflow_data(wf: WorkflowModel, resolver: FieldResolver) -> dict:
    """Buduje ustrukturyzowany slownik z danymi workflow do celow serializacji JSON / raportu HTML."""
    mermaid_code, steps = _build_mermaid_with_steps(wf.actions, resolver)
    apex_workflow_spec = generate_apex_workflow_spec(wf, steps, resolver)
    triggers, guid = _extract_triggers_and_guid(wf.actions)
    variables = _extract_variables(wf.actions)

    src = wf.source_list
    is_site = wf.workflow_type.strip().casefold() == "site"
    is_list = wf.workflow_type.strip().casefold() == "list"
    src_name = src.list_name if src else ("(workflow witryny)" if is_site else "(nieznana)")
    src_id = src.list_id if src else ""
    other_lists = [lr.list_name for lr in wf.list_references if not lr.is_source_list]

    step_fields, fields_dict = _collect_report_fields(wf, steps, resolver)

    steps_data: list[dict] = []
    steps_data.append({
        "node_id": "start",
        "label": "Start",
        "type": "WorkflowStart",
        "short_type": "Start",
        "summary": (
            "Uruchomienie workflow witryny wymaga ręcznej migracji."
            if is_site else f"Uruchomienie workflow dla listy {src_name}."
            if is_list else "Typ workflow nie został potwierdzony; uruchomienie wymaga ręcznej migracji."
        ),
        "branch_label": "",
        "depth": 0,
        "condition_text": "",
        "reads": [],
        "writes": [],
        "hint_universal": "Odtwórz te same reguły uruchomienia w docelowym mechanizmie orkiestracji.",
        "hint_apex": (
            "Workflow Site nie ma bieżącego elementu listy; uruchomienie należy zaprojektować ręcznie."
            if is_site else f"Kroki standardowe APEX: Additional Data (NINTEX_PARAMS) → Retrieve Payload → {SHP_API}.GET_LIST_ITEM → Parse V_SHP_ANSWER."
            if is_list else "Nie przypisuj kroków listy przed ręcznym potwierdzeniem typu workflow."
        ),
        "plsql_code": next(
            (activity.plsql_code for activity in apex_workflow_spec.standard_activities if activity.node_id == "std_get_item"),
            "",
        ),
        "technical_lines": ["Triggery: " + ", ".join(triggers), f"Lista źródłowa: {src_name}", f"ID listy: {src_id}"],
        "is_structural": True,
        "enabled": True,
        "migration_status": apex_workflow_spec.migration_status,
        "blocking_reasons": list(dict.fromkeys(apex_workflow_spec.path_a_blocking_reasons + apex_workflow_spec.path_b_blocking_reasons)),
        "path_a_blocking_reasons": apex_workflow_spec.path_a_blocking_reasons,
        "path_b_blocking_reasons": apex_workflow_spec.path_b_blocking_reasons,
    })
    for s in steps:
        short_type = s.node.type.rsplit(".", 1)[-1]
        reads_info, writes_info = step_fields[s.node_id]

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
            "migration_status": (
                "Zablokowana" if s.desc.blocking_reasons else
                "Ograniczona" if s.desc.path_a_blocking_reasons or s.desc.path_b_blocking_reasons else
                "Wymaga weryfikacji"
            ),
            "blocking_reasons": s.desc.blocking_reasons,
            "path_a_blocking_reasons": s.desc.path_a_blocking_reasons,
            "path_b_blocking_reasons": s.desc.path_b_blocking_reasons,
            "reference_template": s.desc.reference_template,
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
        "hint_apex": "Aktywność APEX 'Workflow End' (End State: Completed).",
        "plsql_code": "",
        "technical_lines": ["Węzeł syntetyczny dodany przez generator raportu HTML."],
        "is_structural": True,
        "enabled": True,
    })

    sorted_fields = sorted(fields_dict.values(), key=lambda item: (item["display_name"].casefold(), item["list_name"].casefold()))

    key = "".join(c if c.isalnum() or c in " _-." else "_" for c in (wf.title or wf.source_path.stem)).strip()

    return {
        "key": key,
        "title": wf.title or wf.source_path.stem,
        "description": wf.description,
        "source_file": wf.source_path.name,
        "source_list_name": src_name,
        "source_list_id": src_id,
        "workflow_type": wf.workflow_type,
        "migration_status": apex_workflow_spec.migration_status,
        "other_lists": other_lists,
        "triggers": triggers,
        "workflow_guid": guid,
        "actions_count": len([s for s in steps_data if not s["is_structural"] and s["short_type"] != "NWWorkflowVariablesAdapter"]),
        "mermaid_code": mermaid_code,
        "steps": steps_data,
        "fields": sorted_fields,
        "variables": variables,
        "apex_workflow_spec": apex_workflow_spec.to_dict(),
    }


def build_report(wf: WorkflowModel, resolver: FieldResolver) -> str:
    mermaid_code, steps = _build_mermaid_with_steps(wf.actions, resolver)
    apex_workflow_spec = generate_apex_workflow_spec(wf, steps, resolver)

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
    lines.append(f"- **Typ workflow:** {wf.workflow_type or '(nie ustalono)'}")
    lines.append(f"- **Gotowość migracji:** {apex_workflow_spec.migration_status}")
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
        if step.desc.hint_apex and step.desc.hint_apex != step.desc.plsql_code:
            lines.append(f"{indent}  > **Oracle APEX**: {step.desc.hint_apex}")
        for path, reasons in (
            ("obie ścieżki", step.desc.blocking_reasons),
            ("ścieżka A", step.desc.path_a_blocking_reasons),
            ("ścieżka B", step.desc.path_b_blocking_reasons),
        ):
            if reasons:
                lines.append(f"{indent}  > **Zablokowane ({path})**: {'; '.join(reasons)}")
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
        if step.desc.reference_template:
            lines.append(f"{indent}  <details><summary>Szablon referencyjny — nie uruchamiać bez migracji i testów</summary>")
            lines.append("")
            lines.append(f"{indent}  ```text")
            for template_line in step.desc.reference_template.splitlines():
                lines.append(f"{indent}  {template_line}")
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

    _, report_fields = _collect_report_fields(wf, steps, resolver)
    used_fields = sorted(
        (item for item in report_fields.values() if item["is_read"] or item["is_written"]),
        key=lambda item: (item["internal_name"].casefold(), item["list_name"].casefold()),
    )

    lines.append("## Pola odczytywane / zapisywane")
    lines.append("")
    lines.append("| Pole | Odczyt | Zapis |")
    lines.append("|---|---|---|")
    for item in used_fields:
        readable = resolver.resolve(item["internal_name"], item["list_id"])
        lines.append(f"| {readable} [{item['list_name']}] | {'X' if item['is_read'] else ''} | {'X' if item['is_written'] else ''} |")
    lines.append("")

    lines.append("### Słownik pól i identyfikatory techniczne")
    lines.append("")
    lines.append("| Nazwa biznesowa | SharePoint InternalName | Typ | Odczyt | Zapis |")
    lines.append("|---|---|---|---|---|")
    for item in used_fields:
        lines.append(
            f"| {item['display_name']} [{item['list_name']}] | `{item['internal_name']}` | "
            f"{item['field_type'] or 'Tekst/Ref'} | {'Tak' if item['is_read'] else '-'} | "
            f"{'Tak' if item['is_written'] else '-'} |"
        )
    lines.append("")

    lines.append(format_markdown_apex_section(apex_workflow_spec))
    lines.append("")

    association = wf.title or wf.source_path.stem
    lines.append("## Integracja z wyzwalaczem SharePoint (workflow.xaml) & ORDS")
    lines.append("")
    if wf.workflow_type.strip().casefold() == "site":
        lines.append(
            "Workflow witryny nie jest podłączany do dyspozytora elementów listy. "
            "Uruchomienie należy zmigrować ręcznie; harmonogram nie został potwierdzony."
        )
        lines.append("")
        return "\n".join(lines)
    if wf.workflow_type.strip().casefold() != "list":
        lines.append(
            "Typ workflow nie został potwierdzony. Nie podłączaj go do dyspozytora listy; "
            "uruchomienie wymaga ręcznej weryfikacji i migracji."
        )
        lines.append("")
        return "\n".join(lines)
    lines.append("Po skonfigurowaniu zgodnego wyzwalacza listy SharePoint Designer (`workflow.xaml`) może wysyłać żądanie `POST` do endpointu ORDS:")
    lines.append("- **Endpoint ORDS:** `POST https://ilapex.{Environment}.creditagricole:8082/ords/shp/nintex/main`")
    lines.append(f"- **Klucz powiązania (`association`):** `{association}`")
    lines.append(f"- **Lista źródłowa (`list_name`):** `{src.list_name if src else '(nieznana)'}`")
    lines.append(f"- **Static ID workflow APEX:** `{apex_workflow_spec.static_id}`")
    lines.append(f"- **Konfiguracja `NINTEX_PARAMS`:** skrypt `nintex_params.sql` (wiersz `WORKFLOW_STATIC_ID = '{apex_workflow_spec.static_id}'`)")
    lines.append("")
    lines.append("Fragment routingu w centralnym dyspozytorze `pkg_shp_dispatcher` (cały payload trafia do parametru "
                 f"`{P_PAYLOAD_BODY}`, a instancję uruchamia `apex_workflow.start_workflow`):")
    lines.append("```plsql")
    lines.append(f"WHEN {sql_literal(association)} THEN l_static_id := {sql_literal(apex_workflow_spec.static_id)};")
    lines.append("```")
    lines.append("")

    return "\n".join(lines)
