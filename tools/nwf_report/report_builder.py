"""Budowanie raportu Markdown (+ diagram Mermaid) dla pojedynczego workflow."""
from __future__ import annotations

from dataclasses import dataclass

from .action_catalog import ActionDescription, describe_action
from .metadata_loader import FieldResolver
from .nwf_parser import ActionNode, WorkflowModel


@dataclass
class Step:
    node: ActionNode
    desc: ActionDescription
    depth: int
    node_id: str


def _collect_steps(actions: list[ActionNode], resolver: FieldResolver, counter: list[int], depth: int = 0) -> list[Step]:
    steps: list[Step] = []
    for node in actions:
        counter[0] += 1
        node_id = f"n{counter[0]}"
        desc = describe_action(node, resolver)
        steps.append(Step(node=node, desc=desc, depth=depth, node_id=node_id))
        steps.extend(_collect_steps(node.children, resolver, counter, depth + 1))
    return steps


def _mermaid_label(text: str, max_len: int = 60) -> str:
    text = text.replace('"', "'").replace("\n", " ")
    if len(text) > max_len:
        text = text[: max_len - 1] + "…"
    return text


def _build_mermaid(actions: list[ActionNode], resolver: FieldResolver) -> str:
    """Buduje diagram flowchart. Rekurencja zwraca liste 'otwartych koncow' (id wezlow
    bez wychodzacej strzalki), do ktorych podlaczy sie kolejny krok w sekwencji."""
    lines = ["flowchart TD", "  start((Start))"]
    counter = [0]

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
            lines.append(f'  {nid}["{label_for(node)}"]')
            connect(current_ends, nid, current_label)
            current_label = ""
            current_ends = [nid]
        return current_ends

    final_ends = walk(actions, ["start"])
    lines.append("  stop((Koniec))")
    connect(final_ends, "stop")
    return "\n".join(lines)



def build_report(wf: WorkflowModel, resolver: FieldResolver) -> str:
    counter = [0]
    steps = _collect_steps(wf.actions, resolver, counter)

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
    lines.append(_build_mermaid(wf.actions, resolver))
    lines.append("```")
    lines.append("")

    lines.append("## Kroki workflow")
    lines.append("")
    for step in steps:
        if step.desc.is_structural:
            continue
        indent = "  " * step.depth
        branch_prefix = f"**[{step.node.branch_label}]** " if step.node.branch_label else ""
        status = "" if step.node.enabled else " _(wyłączona)_"
        lines.append(f"{indent}- {branch_prefix}{step.desc.summary}{status}")
        if step.desc.technical_lines:
            lines.append(f"{indent}  <details><summary>Szczegóły techniczne</summary>")
            lines.append("")
            lines.append(f"{indent}  ```")
            for tl in step.desc.technical_lines:
                lines.append(f"{indent}  {tl}")
            lines.append(f"{indent}  ```")
            lines.append(f"{indent}  </details>")
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

    return "\n".join(lines)
