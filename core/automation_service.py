"""Czysta logika dla modułu automatyzacji SharePoint (bez zależności od Tkinter)."""
from __future__ import annotations

import getpass
import json
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.sp_automation.catalog import Catalog, FieldRecord, ListRecord, normalize_guid
from tools.sp_automation.comparison import (
    ComparisonPath,
    ComparisonRow,
    compare_paths,
    comparison_paths,
)
from tools.sp_automation.engine import SimulationResult, StepTrace, TraceValue, simulate
from tools.sp_automation.ignored_fields import IgnoredFieldsPolicy, default_ignored_fields
from tools.sp_automation.journal import Approval, JournalError, PreviewJournal, confirmation_phrase
from tools.sp_automation.models import Graph, GraphError
from tools.sp_automation.presentation import load_relations_snapshot
from tools.sp_automation.sharepoint import (
    OnlinePreview,
    OnlineSnapshot,
    SharePointReader,
    build_online_preview,
)
from tools.sp_automation.snapshot_adapter import (
    AdaptedSnapshot,
    _SYSTEM_FIELDS,
    _field_metadata,
    build_simulation_snapshot,
    catalog_graph_fingerprint,
)
from tools.sp_extractor.client import SharePointClient

COMPARISON_STATUS_LABELS: dict[str, str] = {
    "direct_empty": "Pusta relacja bezpośrednia, pośrednia wypełniona",
    "different": "Różne wartości",
    "equal": "Wartości zgodne",
    "both_empty": "Obie wartości puste",
    "indirect_empty": "Pusta relacja pośrednia",
    "no_intermediate": "Brak relacji do listy pośredniej",
    "missing_intermediate": "Brak elementu pośredniego w eksporcie",
    "missing_target": "Brak elementu docelowego w eksporcie",
    "unknown": "Brak pola lub nierozpoznana wartość",
}

NODE_TITLES: dict[str, str] = {
    "start": "Start",
    "lookup": "Odczyt relacji",
    "condition": "Warunek",
    "assign": "Ustaw pole",
    "merge": "Scalenie",
    "skip": "Pomiń",
    "end": "Koniec",
}


@dataclass(frozen=True)
class ListItemView:
    key: str
    title: str
    details: str
    priority: bool = False
    is_system: bool = False
    is_external: bool = False


@dataclass(frozen=True)
class RelationEdgeView:
    key: str
    source: str
    target: str
    label: str
    details: str
    target_title: str = ""
    ignored_reason: str = ""


@dataclass(frozen=True)
class RelationsData:
    lists: list[ListItemView]
    relations: list[RelationEdgeView]
    summary: str
    diagnostics: str
    catalog: Catalog | None = field(default=None, repr=False, compare=False)
    ignored_count: int = 0


@dataclass(frozen=True)
class ComparisonOption:
    index: int
    label: str
    path: ComparisonPath


@dataclass(frozen=True)
class ComparisonReport:
    label: str
    total_rows: int
    status_counts: list[tuple[str, int]]
    rows: list[dict[str, str]]
    truncated: bool


@dataclass(frozen=True)
class SimulationOutcome:
    adapted: AdaptedSnapshot
    result: SimulationResult
    rows: list[dict[str, str]]
    warnings: list[str]
    decisions_count: int
    trace_rows: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class OnlinePreviewOutcome:
    preview: OnlinePreview
    rows: list[dict[str, str]]
    details_lines: list[str]
    total_changes: int


def display_value(value: object) -> str:
    """Skraca wartość do bezpiecznej prezentacji w tabeli."""
    text = "Puste" if value is None else str(value)
    return text if len(text) <= 180 else text[:177] + "..."


def find_paths(
    relations: list[RelationEdgeView],
    source: str,
    target: str,
    max_depth: int = 6,
    max_paths: int = 20,
) -> tuple[list[list[RelationEdgeView]], bool]:
    """Znajduje ścieżki skierowanych lookupów bez przechodzenia cykli."""
    outgoing: dict[str, list[RelationEdgeView]] = defaultdict(list)
    for relation in relations:
        outgoing[relation.source].append(relation)
    pending = deque([(source, [], frozenset([source]))])
    found: list[list[RelationEdgeView]] = []
    examined = 0
    while pending:
        current, path, visited = pending.popleft()
        if len(path) >= max_depth:
            continue
        for relation in outgoing[current]:
            examined += 1
            if examined > 10000:
                return found, True
            if relation.target in visited:
                continue
            next_path = [*path, relation]
            if relation.target == target:
                found.append(next_path)
                if len(found) > max_paths:
                    return found[:max_paths], True
            else:
                pending.append((relation.target, next_path, visited | {relation.target}))
    return found, False


def system_list_reason(record: ListRecord) -> str:
    metadata = record.metadata
    reasons = []
    if metadata.get("Hidden") is True:
        reasons.append("Hidden")
    if metadata.get("IsCatalog") is True:
        reasons.append("IsCatalog")
    template = str(metadata.get("BaseTemplate", ""))
    technical_templates = {
        "112": "User Information",
        "140": "Workflow History",
        "5001": "NintexWorkflows",
    }
    if template in technical_templates:
        reasons.append(f"{technical_templates[template]} (BaseTemplate={template})")
    return ", ".join(reasons)


def build_relations_view(
    lists: list[ListItemView],
    relations: list[RelationEdgeView],
    selected_keys: set[str],
    *,
    auto_related: bool = True,
    show_system: bool = True,
    include_external: bool = False,
    show_ignored_fields: bool = False,
) -> tuple[list[ListItemView], list[RelationEdgeView]]:
    """Wylicza widok z ręcznego wyboru, bez rekurencyjnego dodawania sąsiadów."""
    if not show_ignored_fields:
        relations = [edge for edge in relations if not edge.ignored_reason]
    by_key = {item.key: item for item in lists}
    hidden = {item.key for item in lists if item.is_system and not show_system}
    selected = (selected_keys & by_key.keys()) - hidden
    visible_keys = set(selected)
    if auto_related:
        for edge in relations:
            if edge.source in selected or edge.target in selected:
                visible_keys.update((edge.source, edge.target))
    elif include_external:
        visible_keys.update(edge.target for edge in relations if edge.source in selected)
    visible_keys -= hidden
    edges = [
        edge for edge in relations
        if edge.source in visible_keys and edge.target in visible_keys
        and (auto_related or edge.source in selected)
    ]
    for edge in edges:
        for key, title in ((edge.source, edge.source), (edge.target, edge.target_title or edge.target)):
            if key not in by_key:
                by_key[key] = ListItemView(
                    key, title, "Lista poza katalogiem lub nierozpoznana referencja; typ niepotwierdzony.",
                    is_external=True,
                )
    nodes = sorted(
        (by_key[key] for key in visible_keys if key in by_key),
        key=lambda item: (item.title.casefold(), item.key),
    )
    return nodes, edges


def load_relations(export_dir: str | Path, policy: IgnoredFieldsPolicy | None = None) -> RelationsData:
    """Wczytuje migawkę relacji z lokalnego eksportu SharePoint; przystosowana do `run.io_bound`."""
    path = Path(str(export_dir).strip())
    if not str(path) or str(path) == ".":
        raise ValueError("Wybierz katalog eksportu.")
    policy = policy if policy is not None else default_ignored_fields()
    snapshot = load_relations_snapshot(path)
    fields_by_key = {
        f"{record.id}:{fld.internal_name}": fld
        for record in (snapshot.catalog.lists.values() if snapshot.catalog else ())
        for fld in record.fields.values()
    }
    lists = []
    for item in snapshot.lists:
        record = snapshot.catalog.lists.get(item.key) if snapshot.catalog else None
        reason = system_list_reason(record) if record else ""
        classification = (
            f"Lista systemowa: {reason}."
            if reason else "Brak oznaczenia systemowości w dostępnych metadanych."
        )
        lists.append(ListItemView(
            key=item.key, title=item.title, details=f"{item.details}\n\n{classification}",
            priority=item.priority, is_system=bool(reason),
        ))
    relations = []
    for item in snapshot.relations:
        fld = fields_by_key.get(item.key)
        ignored = policy.reason(fld) if fld is not None else ""
        details = f"{item.details}\n\nPominięte domyślnie: {ignored}." if ignored else item.details
        relations.append(RelationEdgeView(
            key=item.key,
            source=item.source,
            target=item.target,
            label=item.label,
            details=details,
            target_title=item.target_title,
            ignored_reason=ignored,
        ))
    ignored_count = sum(1 for edge in relations if edge.ignored_reason)
    diagnostics = "\n".join(
        part for part in (snapshot.diagnostics, *policy.warnings) if part
    )
    return RelationsData(
        lists=lists,
        relations=relations,
        summary=f"{snapshot.summary} Pominięte relacje pól systemowych: {ignored_count}.",
        diagnostics=diagnostics or "Brak zgłoszonych problemów odczytu.",
        catalog=snapshot.catalog,
        ignored_count=ignored_count,
    )


def format_comparison_path_label(catalog: Catalog, path: ComparisonPath) -> str:
    lists = catalog.lists
    direct, first, second = path.direct, path.first, path.second
    return (
        f"{lists[direct.source_list_id].title} [{direct.source_list_id}]: "
        f"{direct.field.title} [{direct.field.internal_name}] → "
        f"{lists[direct.target_list_id].title} [{direct.target_list_id}] | "
        f"przez {first.field.title} [{first.field.internal_name}] → "
        f"{lists[first.target_list_id].title} [{first.target_list_id}]: "
        f"{second.field.title} [{second.field.internal_name}]"
    )


def list_comparison_options(
    catalog: Catalog, selected: set[str], policy: IgnoredFieldsPolicy | None = None,
) -> list[ComparisonOption]:
    """Wyszukuje dostępne pary ścieżek bezpośrednich i pośrednich do porównania."""
    policy = policy if policy is not None else default_ignored_fields()
    paths = comparison_paths(catalog, set(selected), policy.is_ignored)
    return [
        ComparisonOption(index=idx, label=format_comparison_path_label(catalog, path), path=path)
        for idx, path in enumerate(paths)
    ]


def _render_comparison_rows(label: str, rows: list[ComparisonRow]) -> ComparisonReport:
    counts = Counter(row.status for row in rows)
    status_counts = [
        (status_label, counts[status])
        for status, status_label in COMPARISON_STATUS_LABELS.items()
        if counts[status]
    ]
    show = lambda value: str(value) if value is not None else "—"
    formatted_rows = [
        {
            "source_id": str(row.source_id),
            "intermediate_id": show(row.intermediate_id),
            "direct_id": show(row.direct_id),
            "indirect_id": show(row.indirect_id),
            "status": COMPARISON_STATUS_LABELS[row.status],
        }
        for row in rows[:200]
    ]
    return ComparisonReport(
        label=label,
        total_rows=len(rows),
        status_counts=status_counts,
        rows=formatted_rows,
        truncated=len(rows) > 200,
    )


def run_path_comparison(catalog: Catalog, option: ComparisonOption) -> ComparisonReport:
    """Porównuje wybraną ścieżkę bezpośrednią i pośrednią na lokalnym eksporcie."""
    rows = compare_paths(catalog, option.path)
    return _render_comparison_rows(option.label, rows)


def parse_graph_json(text: str) -> dict[str, Any]:
    """Parsuje JSON grafu ze ścisłą walidacją duplikatów kluczy i stałych liczbowych."""

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"Powtórzony klucz: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError(f"Niepoprawna liczba: {value}")

    data = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)
    if not isinstance(data, dict):
        raise ValueError("Plik grafu musi zawierać obiekt JSON.")
    return data


def new_workflow() -> dict[str, Any]:
    """Tworzy pusty szkic grafu automatyzacji."""
    return {
        "schema_version": 1,
        "text_policy": "exact",
        "id": uuid4().hex,
        "name": "Nowy algorytm",
        "site": "",
        "source_list_id": "",
        "schema_fingerprint": "",
        "max_updates": 0,
        "scope": {"type": "all"},
        "nodes": [{"id": "start", "type": "start"}],
        "edges": [],
        "layout": {"start": {"x": 100, "y": 100}},
    }


def create_node_dict(kind: str, node_id: str) -> dict[str, Any]:
    """Tworzy słownik nowego węzła dla projektanta grafu."""
    result: dict[str, Any] = {"id": node_id, "type": kind}
    if kind == "lookup":
        result.update({"from": "source", "field_id": "", "as": ""})
    elif kind == "condition":
        result.update({"merge": "", "condition": {"op": "exists", "alias": "source"}})
    elif kind == "assign":
        result.update({"alias": "source", "field_id": "", "value": {"kind": "literal", "value": None}})
    return result


_GRAPH_ERROR_HINTS: dict[str, str] = {
    "Site must be an absolute URL without credentials, query or fragment": (
        "Brak lub niepoprawny adres w polu 'Witryna SharePoint' "
        "(wymagany pełny URL http:// lub https:// bez parametrów)."
    ),
    "Condition requires an explicit merge": (
        "Węzeł Warunek (condition) wymaga wskazania węzła Scalenie (merge) "
        "w polu 'Wspólne scalenie (merge)' oraz połączenia obu gałęzi (true/false) z tym węzłem."
    ),
    "Branch does not reach its merge": (
        "Jedna z gałęzi warunku (true/false) nie dociera do wskazanego węzła Scalenie (merge)."
    ),
    "Branches meet before the declared merge": (
        "Gałęzie true i false warunku łączą się przed wskazanym węzłem Scalenie (merge)."
    ),
    "Missing or invalid port": (
        "Niekompletne połączenia węzła: każdy węzeł (poza Koniec/Pomiń) musi mieć wyjście, "
        "a Warunek wymaga obu połączeń true i false."
    ),
    "Unreachable node": "W grafie istnieje węzeł niepołączony ze ścieżką od Start.",
    "Graph cycles are not supported": "Graf zawiera cykl (pętlę), co nie jest obsługiwane.",
}


def validate_graph(data: dict[str, Any], catalog: Catalog | None = None) -> Graph:
    """Waliduje słownik grafu i opcjonalnie uzupełnia fingerprint schematu z katalogu."""
    payload = dict(data)
    nodes_by_id = {
        str(n.get("id")): n for n in payload.get("nodes", []) if isinstance(n, dict) and n.get("id")
    }
    normalized_edges = []
    for edge in payload.get("edges", []):
        if isinstance(edge, dict) and "port" not in edge:
            src_node = nodes_by_id.get(str(edge.get("from", "")))
            if src_node is not None and src_node.get("type") != "condition":
                edge = {**edge, "port": "next"}
        normalized_edges.append(edge)
    if normalized_edges:
        payload["edges"] = normalized_edges

    if not str(payload.get("site") or "").strip():
        raise GraphError(_GRAPH_ERROR_HINTS["Site must be an absolute URL without credentials, query or fragment"])

    has_fingerprint = bool(str(payload.get("schema_fingerprint") or "").strip())
    if not has_fingerprint and catalog is not None and str(payload.get("source_list_id") or "") in catalog.lists:
        payload["schema_fingerprint"] = "pending"

    try:
        graph = Graph.from_dict(payload)
        if not has_fingerprint and catalog is not None:
            source_id = str(payload.get("source_list_id") or "")
            if source_id in catalog.lists:
                payload["schema_fingerprint"] = catalog_graph_fingerprint(catalog, graph)
                graph = Graph.from_dict(payload)
        return graph
    except GraphError as exc:
        hint = _GRAPH_ERROR_HINTS.get(str(exc))
        if hint:
            raise GraphError(f"{hint} ({exc})") from exc
        raise


def load_graph_file(path: Path) -> dict[str, Any]:
    """Wczytuje plik JSON definicji grafu."""
    return parse_graph_json(path.read_text(encoding="utf-8"))


def save_graph_file(path: Path, data: dict[str, Any]) -> None:
    """Zapisuje definicję grafu do pliku JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _format_trace_value(catalog: Catalog, item: TraceValue) -> str:
    """Formatuje zmienną lub wartość odczytaną w kroku symulacji bez surowych GUID-ów."""
    if item.label == "source":
        list_name = resolve_list_label(catalog, item.list_id)
        return f"{item.alias or 'source'} = {list_name} #{item.value}"
    if item.label == "literal":
        return f"stała = {json.dumps(item.value, ensure_ascii=False)}"
    if item.label == "count":
        return f"liczba({item.alias}) = {item.value}"
    if item.label == "exists":
        return f"istnieje({item.alias}) = {'Tak' if item.value else 'Nie'}"
    if item.label == "collection":
        return f"kolekcja {item.alias}: {item.value} szt."
    field_label = resolve_field_label(catalog, item.field_id, item.list_id, internal_name=item.internal_name)
    prefix = "przed: " if item.label == "przed" else ""
    alias_part = f"{item.alias}." if item.alias else ""
    return f"{prefix}{alias_part}{field_label} = {display_value(item.value)}"


def _format_trace_outcome(catalog: Catalog, step: StepTrace) -> str:
    """Formatuje wynik zwrócony przez węzeł grafu w danym kroku symulacji."""
    kind = step.node_type
    out = step.outcome
    if kind == "start":
        list_name = resolve_list_label(catalog, str(out.get("list_id") or ""))
        return f"Start ({list_name} #{out.get('item_id')})"
    if kind == "lookup":
        alias = str(out.get("alias") or "")
        target_name = resolve_list_label(catalog, str(out.get("target_list_id") or ""))
        bound = out.get("bound_ids") or []
        if not bound:
            return f"{alias} = Puste"
        if out.get("many"):
            joined = ", ".join(f"#{i}" for i in bound[:5])
            suffix = ", ..." if len(bound) > 5 else ""
            return f"{alias} = {target_name} [{joined}{suffix}] ({len(bound)} szt.)"
        return f"{alias} = {target_name} #{bound[0]}"
    if kind == "condition":
        matched = bool(out.get("matched"))
        return "PRAWDA (gałąź true)" if matched else "FAŁSZ (gałąź false)"
    if kind == "assign":
        field_label = resolve_field_label(
            catalog,
            str(out.get("field_id") or ""),
            str(out.get("list_id") or ""),
            internal_name=str(out.get("internal_name") or ""),
        )
        alias = str(out.get("alias") or "source")
        old_txt = display_value(out.get("old"))
        new_txt = display_value(out.get("new"))
        if out.get("changed"):
            return f"Propozycja: {alias}.{field_label}: {old_txt} → {new_txt}"
        return f"Bez zmiany ({alias}.{field_label} = {new_txt})"
    if kind == "merge":
        return "Połączenie gałęzi"
    if kind == "skip":
        return f"Pominięto element (odrzucone propozycje: {out.get('dropped', 0)})"
    if kind == "end":
        return f"Koniec (propozycji zmian: {out.get('proposals', 0)})"
    return kind


def run_offline_simulation(catalog: Catalog, graph: Graph) -> SimulationOutcome:
    """Uruchamia offline'ową symulację na lokalnym eksporcie; przystosowana do `run.io_bound`."""
    adapted = build_simulation_snapshot(catalog, graph)
    result = simulate(graph, adapted.data, allow_incomplete=not adapted.complete, record_trace=True)
    rows = [
        {
            "list": resolve_list_label(catalog, change.list_id),
            "item": str(change.item_id),
            "field": resolve_field_label(
                catalog,
                change.field_id,
                change.list_id,
                internal_name=change.internal_name,
            ),
            "old": display_value(change.old_value),
            "new": display_value(change.new_value),
            "sources": ", ".join(map(str, change.source_ids)),
            "steps": ", ".join(change.steps),
        }
        for change in result.changes[:1000]
    ]
    trace_rows = [
        {
            "source_id": str(step.source_id),
            "step_no": str(step.step_no),
            "node": f"{step.node_id} ({NODE_TITLES.get(step.node_type, step.node_type)})",
            "variables": "; ".join(_format_trace_value(catalog, item) for item in step.values) or "—",
            "result": _format_trace_outcome(catalog, step),
            "next_port": step.next_port or "—",
        }
        for step in result.trace[:2000]
    ]
    warnings = [
        "Symulacja jest wyłącznie offline. Nie wysłano żadnego żądania do SharePoint.",
        "Propozycje oparte na eksporcie o niepotwierdzonej kompletności nie są podstawą zapisu.",
        *adapted.warnings,
    ]
    if len(result.changes) > 1000:
        warnings.append(f"Tabela pokazuje 1000 z {len(result.changes)} proponowanych zmian.")
    if len(result.trace) > 2000:
        warnings.append(f"Przebieg krok po kroku pokazuje 2000 z {len(result.trace)} kroków.")
    return SimulationOutcome(
        adapted=adapted,
        result=result,
        rows=rows,
        warnings=warnings,
        decisions_count=len(result.decisions),
        trace_rows=trace_rows,
    )


def default_journal_path(repo_root: Path) -> Path:
    """Lokalizacja dziennika SQLite (poza Git) dla podglądów i zatwierdzeń online."""
    return repo_root / "out_automation" / "journal.sqlite"


def read_with_windows_sso(graph: Graph) -> OnlineSnapshot:
    """Pobiera świeżą migawkę SharePoint wyłącznie żądaniami GET z Windows SSO."""
    client = SharePointClient(graph.to_dict()["site"])
    try:
        return SharePointReader(client).read_snapshot(graph)
    finally:
        client.session.close()


def run_online_preview(graph: Graph, catalog: Catalog | None = None) -> OnlinePreviewOutcome:
    """Buduje podgląd online (tylko GET); przystosowana do `run.io_bound`."""
    snapshot = read_with_windows_sso(graph)
    preview = build_online_preview(graph, snapshot)
    data = preview.to_dict()
    changes = data["result"]["changes"]
    source_list_id = str(graph.to_dict().get("source_list_id") or "")

    def _preview_list_label(list_id: str) -> str:
        resolved = resolve_list_label(catalog, list_id, fallback="")
        if resolved:
            return resolved
        if source_list_id and list_id == source_list_id:
            return "Lista źródłowa"
        return resolve_list_label(catalog, list_id, fallback="Powiązana lista")

    rows = [
        {
            "list": _preview_list_label(str(change["list_id"])),
            "item": str(change["item_id"]),
            "field": resolve_field_label(
                catalog,
                str(change["field_id"]),
                str(change["list_id"]),
                internal_name=str(change["internal_name"]),
            ),
            "old": display_value(change["old_value"]),
            "new": display_value(change["new_value"]),
            "sources": ", ".join(map(str, change["source_ids"])),
        }
        for change in changes[:1000]
    ]
    snap_dict = data["snapshot"]
    scope = snap_dict.get("scope_resolution")
    details = [f"Witryna: {snap_dict['site']}"]
    if scope:
        details.append(
            f"Zakres widoku „{scope['title']}”: {len(scope['ids'])} elementów "
            "(filtr CAML oceniony lokalnie; potwierdź na serwerze)."
        )
    for resource in preview.snapshot.resources:
        details.append(
            f"{resource.resource}: {resource.status}; strony={resource.pages}; rekordy={resource.records}"
        )
    details.extend(snap_dict.get("warnings", []))
    if len(changes) > 1000:
        details.append(f"Tabela pokazuje 1000 z {len(changes)} zmian.")

    return OnlinePreviewOutcome(
        preview=preview,
        rows=rows,
        details_lines=details,
        total_changes=len(changes),
    )


def record_preview_in_journal(preview: OnlinePreview, journal_path: Path) -> None:
    """Zapisuje wygenerowany podgląd online w lokalnym dzienniku SQLite."""
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with PreviewJournal(journal_path) as journal:
        journal.record_preview(preview)


def approve_online_preview(
    preview: OnlinePreview,
    graph: Graph,
    confirmation_text: str,
    journal_path: Path,
    approver: str | None = None,
) -> Approval:
    """Ponawia odczyt GET, sprawdza aktualność ETag/danych i zapisuje zgodę w dzienniku."""
    fresh = read_with_windows_sso(graph)
    if not preview.is_current(graph, fresh):
        raise JournalError(
            "Podgląd jest nieaktualny (zmienione dane, ETag, zakres lub graf). "
            "Wykonaj nowy podgląd; zatwierdzenie jest niemożliwe."
        )
    who = approver or getpass.getuser()
    with PreviewJournal(journal_path) as journal:
        return journal.approve(
            preview.run_id,
            approver=who,
            confirmation=confirmation_text,
            graph=graph,
            fresh_snapshot=fresh,
        )


def expected_confirmation_phrase(run_id: str) -> str:
    """Zwraca wymaganą frazę potwierdzenia dla zatwierdzenia w dzienniku."""
    return confirmation_phrase(run_id)


_GUID_RE = re.compile(
    r"^\{?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\}?$"
)


def is_guid_text(value: str | None) -> bool:
    """Sprawdza, czy tekst ma format identyfikatora GUID."""
    return bool(value and _GUID_RE.fullmatch(value.strip()))


def _unique_labels(items: list[tuple[str, str]]) -> dict[str, str]:
    """Buduje unikalne etykiety bez GUID-ów, dodając (#2), (#3) przy powtórzeniach nazw."""
    counts = Counter(label for _, label in items)
    seen: dict[str, int] = defaultdict(int)
    options: dict[str, str] = {}
    for key, label in items:
        if counts[label] > 1:
            seen[label] += 1
            options[key] = f"{label} (#{seen[label]})" if seen[label] > 1 else label
        else:
            options[key] = label
    return options


def catalog_list_options(catalog: Catalog | None) -> dict[str, str]:
    """Zwraca mapę `{list_id: tytuł}` dla list dostępnych w katalogu (bez surowych GUID-ów)."""
    if catalog is None:
        return {}
    items = sorted(catalog.lists.values(), key=lambda lst: (lst.title or "").lower())
    return _unique_labels([(lst.id, lst.title or "Lista bez nazwy") for lst in items])


def catalog_view_options(catalog: Catalog | None, list_id: str) -> dict[str, str]:
    """Zwraca mapę `{view_id: tytuł}` dla widoków wskazanej listy (bez surowych GUID-ów)."""
    if catalog is None or list_id not in catalog.lists:
        return {}
    views = sorted(catalog.lists[list_id].views, key=lambda v: (v.title or "").lower())
    return _unique_labels([(v.id, v.title or "Widok bez nazwy") for v in views])


def resolve_list_label(
    catalog: Catalog | None,
    list_id: str,
    *,
    fallback: str = "Lista (spoza katalogu)",
) -> str:
    """Zamienia identyfikator listy na czytelny tytuł listy bez pokazywania GUID."""
    raw = str(list_id or "").strip()
    if not raw:
        return ""
    if catalog is not None:
        record = catalog.lists.get(raw)
        if record is None:
            norm = normalize_guid(raw)
            if norm:
                record = catalog.lists.get(norm)
        if record is not None and record.title:
            return record.title
    return fallback if is_guid_text(raw) else raw


def resolve_field_label(
    catalog: Catalog | None,
    field_id: str,
    list_id: str | None = None,
    *,
    internal_name: str = "",
) -> str:
    """Zamienia `field_id` / GUID na czytelną nazwę pola bez pokazywania GUID."""
    raw_id = str(field_id or "").strip()
    raw_internal = str(internal_name or "").strip()
    norm_id = normalize_guid(raw_id) if raw_id else ""

    def _find_in_list(lst) -> Any:
        if raw_id and raw_id in lst.fields:
            return lst.fields[raw_id]
        if raw_internal and raw_internal in lst.fields:
            return lst.fields[raw_internal]
        for fld in lst.fields.values():
            if raw_id and (fld.field_id == raw_id or fld.internal_name == raw_id):
                return fld
            if norm_id and fld.field_id and normalize_guid(fld.field_id) == norm_id:
                return fld
            if raw_internal and fld.internal_name == raw_internal:
                return fld
        return None

    if catalog is not None:
        target_lists = []
        if list_id:
            lst = catalog.lists.get(list_id) or catalog.lists.get(normalize_guid(list_id) or "")
            if lst is not None:
                target_lists.append(lst)
        target_lists.extend(lst for lst in catalog.lists.values() if lst not in target_lists)
        for lst in target_lists:
            fld = _find_in_list(lst)
            if fld is not None:
                if fld.title and fld.internal_name and fld.title != fld.internal_name:
                    return f"{fld.title} [{fld.internal_name}]"
                return fld.title or fld.internal_name

    if raw_internal:
        return raw_internal
    return "" if is_guid_text(raw_id) else raw_id


def format_expression_summary(
    expr: Any,
    graph: dict[str, Any] | None,
    catalog: Catalog | None,
) -> str:
    """Buduje czytelny skrót wyrażenia AST bez surowych GUID-ów."""
    if not isinstance(expr, dict):
        return "?"
    kind = expr.get("kind")
    if kind == "literal":
        return json.dumps(expr.get("value"), ensure_ascii=False)
    if kind == "count":
        alias = str(expr.get("alias") or "source")
        return f"liczba({alias})"
    if kind == "field":
        alias = str(expr.get("alias") or "source")
        field_id = str(expr.get("field_id") or "")
        list_id = resolve_alias_list_id(graph or {}, catalog, alias) if graph is not None else None
        label = resolve_field_label(catalog, field_id, list_id)
        if not label:
            label = "(pole z definicji)" if is_guid_text(field_id) else "(nie wybrano)"
        return f"{alias}.{label}"
    return "?"


_COND_SYMBOL = {
    "eq": "=",
    "ne": "≠",
    "lt": "<",
    "le": "≤",
    "gt": ">",
    "ge": "≥",
}


def format_condition_summary(
    cond: Any,
    graph: dict[str, Any] | None,
    catalog: Catalog | None,
) -> str:
    """Buduje czytelny opis warunku AST w języku biznesowym bez surowych GUID-ów."""
    if not isinstance(cond, dict):
        return "Brak definicji warunku"
    op = str(cond.get("op") or "")
    if op == "exists":
        return f"istnieje({cond.get('alias') or 'source'})"
    if op in ("empty", "not_empty"):
        val = format_expression_summary(cond.get("value"), graph, catalog)
        return f"{'puste' if op == 'empty' else 'niepuste'}({val})"
    if op in _COND_SYMBOL:
        left = format_expression_summary(cond.get("left"), graph, catalog)
        right = format_expression_summary(cond.get("right"), graph, catalog)
        return f"{left} {_COND_SYMBOL[op]} {right}"
    if op == "not":
        return f"NIE ({format_condition_summary(cond.get('condition'), graph, catalog)})"
    if op in ("any", "all"):
        alias = cond.get("alias") or "source"
        inner = format_condition_summary(cond.get("condition"), graph, catalog)
        word = "KTÓRYKOLWIEK" if op == "any" else "WSZYSTKIE"
        return f"{word} z {alias}: ({inner})"
    if op in ("and", "or"):
        joiner = " ORAZ " if op == "and" else " LUB "
        parts = [format_condition_summary(c, graph, catalog) for c in (cond.get("conditions") or [])]
        return "(" + joiner.join(parts) + ")" if parts else op.upper()
    return op or "Brak warunku"


_READABLE_FIELD_TYPES = frozenset({
    "Text", "Note", "Choice", "Number", "Currency", "Boolean", "Lookup", "LookupMulti", "DateTime",
})
_WRITABLE_FIELD_TYPES = frozenset({
    "Text", "Note", "Number", "Currency", "Boolean", "Choice", "DateTime", "Lookup",
})
_LOOKUP_FIELD_TYPES = frozenset({"Lookup", "LookupMulti"})


def _resolved_lookup_target(field: FieldRecord, source_list_id: str | None = None) -> str:
    """Wyznacza docelowe ID listy dla pola Lookup (obsługuje `self` oraz GUID)."""
    raw = str(field.lookup_list or "").strip()
    if not raw:
        return ""
    if raw.casefold() == "self":
        src = str(source_list_id or field.metadata.get("SourceID") or "").strip()
        return normalize_guid(src) or src
    return normalize_guid(raw) or raw


def resolve_field_record(
    catalog: Catalog | None,
    field_id: str,
    list_id: str | None = None,
) -> FieldRecord | None:
    """Zwraca obiekt `FieldRecord` dla podanego `field_id` lub `InternalName`."""
    if catalog is None:
        return None
    raw_id = str(field_id or "").strip()
    if not raw_id:
        return None
    norm_id = normalize_guid(raw_id)
    target_lists = []
    if list_id:
        lst = catalog.lists.get(list_id) or catalog.lists.get(normalize_guid(list_id) or "")
        if lst is not None:
            target_lists.append(lst)
    target_lists.extend(lst for lst in catalog.lists.values() if lst not in target_lists)
    for lst in target_lists:
        if raw_id in lst.fields:
            return lst.fields[raw_id]
        for fld in lst.fields.values():
            if fld.field_id == raw_id or fld.internal_name == raw_id:
                return fld
            if norm_id and fld.field_id and normalize_guid(fld.field_id) == norm_id:
                return fld
    return None


def is_field_eligible(
    field: FieldRecord,
    catalog: Catalog,
    mode: str = "all",
    *,
    list_id: str | None = None,
    lookup_target_list_id: str | None = None,
    compatible_with: FieldRecord | None = None,
    compatible_list_id: str | None = None,
) -> bool:
    """Sprawdza, czy pole jest dopuszczalne w kontekście danej operacji."""
    if mode == "all":
        return True
    raw = field.metadata
    if field.schema_error or field.field_ref or raw.get("IsDependentLookup") is True:
        return False
    if raw.get("Hidden") is True:
        return False

    if mode == "lookup":
        if field.type_as_string not in _LOOKUP_FIELD_TYPES or not field.lookup_list:
            return False
        if default_ignored_fields().is_ignored(field):
            return False
        if lookup_target_list_id:
            want = normalize_guid(lookup_target_list_id) or lookup_target_list_id.strip()
            if _resolved_lookup_target(field, list_id) != want:
                return False
        return True

    if mode == "writable":
        if field.type_as_string not in _WRITABLE_FIELD_TYPES:
            return False
        if field.internal_name.casefold() in _SYSTEM_FIELDS:
            return False
        if raw.get("ReadOnlyField") is True:
            return False
        if "ReadOnlyField" in raw and "Required" in raw:
            return _field_metadata(field, catalog)["writable"] is True
        if raw.get("ValidationFormula") not in (None, "") or raw.get("ValidationMessage") not in (None, ""):
            return False
        if field.type_as_string == "Choice" and raw.get("AllowMultipleValues") is True:
            return False
        if field.type_as_string == "Note" and (raw.get("RichText") is True or raw.get("AppendOnly") is True):
            return False
        if field.type_as_string == "Lookup" and raw.get("AllowMultipleValues") is True:
            return False
        return True

    if mode == "readable":
        if field.type_as_string not in _READABLE_FIELD_TYPES:
            return False
        if compatible_with is not None:
            src_type = field.type_as_string
            dst_type = compatible_with.type_as_string
            if src_type != dst_type and {src_type, dst_type} != {"Number", "Currency"}:
                return False
            if dst_type == "Lookup":
                src_target = _resolved_lookup_target(field, list_id)
                dst_target = _resolved_lookup_target(compatible_with, compatible_list_id)
                if src_target and dst_target and src_target != dst_target:
                    return False
        return True

    return True


def catalog_field_options(
    catalog: Catalog | None,
    list_id: str | None = None,
    *,
    lookup_only: bool = False,
    mode: str = "all",
    lookup_target_list_id: str | None = None,
    compatible_with: FieldRecord | None = None,
    compatible_list_id: str | None = None,
) -> dict[str, str]:
    """Zwraca mapę `{field_id: opis pola}` dla wybranej listy lub całego katalogu."""
    if catalog is None:
        return {}
    effective_mode = "lookup" if lookup_only and mode == "all" else mode
    lists = [catalog.lists[list_id]] if list_id and list_id in catalog.lists else list(catalog.lists.values())
    options: dict[str, str] = {}
    for lst in sorted(lists, key=lambda item: (item.title or "").lower()):
        for fld in sorted(lst.fields.values(), key=lambda f: (f.title or f.internal_name).lower()):
            if not is_field_eligible(
                fld,
                catalog,
                effective_mode,
                list_id=lst.id,
                lookup_target_list_id=lookup_target_list_id,
                compatible_with=compatible_with,
                compatible_list_id=compatible_list_id,
            ):
                continue
            key = fld.field_id or fld.internal_name
            if not key:
                continue
            prefix = f"{lst.title}: " if not list_id else ""
            options[key] = f"{prefix}{fld.title} [{fld.internal_name}] ({fld.type_as_string})"
    return options


def catalog_reverse_lookup_list_options(
    catalog: Catalog | None,
    target_list_id: str | None,
) -> dict[str, str]:
    """Zwraca listy posiadające co najmniej jedno pole Lookup wskazujące na `target_list_id`."""
    if catalog is None:
        return {}
    if not target_list_id:
        return catalog_list_options(catalog)
    items = [
        lst for lst in sorted(catalog.lists.values(), key=lambda item: (item.title or "").lower())
        if any(
            is_field_eligible(
                fld, catalog, mode="lookup", list_id=lst.id, lookup_target_list_id=target_list_id,
            )
            for fld in lst.fields.values()
        )
    ]
    return _unique_labels([(lst.id, lst.title or "Lista bez nazwy") for lst in items])


def resolve_alias_list_id(graph: dict[str, Any], catalog: Catalog | None, alias: str) -> str | None:
    """Wyznacza ID listy SharePoint dla aliasu na podstawie listy źródłowej i węzłów lookup."""
    alias_name = (alias or "").strip() or "source"
    source_list_id = normalize_guid(str(graph.get("source_list_id") or "").strip()) or str(
        graph.get("source_list_id") or ""
    ).strip()
    if alias_name == "source":
        return source_list_id or None
    if catalog is None:
        return None
    alias_lists: dict[str, str] = {}
    if source_list_id:
        alias_lists["source"] = source_list_id
    nodes = [n for n in graph.get("nodes", []) if isinstance(n, dict) and n.get("type") == "lookup"]
    for _ in range(len(nodes)):
        changed = False
        for node in nodes:
            as_name = str(node.get("as") or "").strip()
            if not as_name or as_name in alias_lists:
                continue
            direction = str(node.get("direction") or "forward")
            if direction == "reverse":
                raw_target = str(node.get("target_list_id") or "").strip()
                target_id = normalize_guid(raw_target) or raw_target
                if target_id:
                    alias_lists[as_name] = target_id
                    changed = True
            else:
                from_name = str(node.get("from") or "source").strip() or "source"
                from_list_id = alias_lists.get(from_name)
                field_id = str(node.get("field_id") or "").strip()
                if from_list_id and field_id and from_list_id in catalog.lists:
                    lst = catalog.lists[from_list_id]
                    fld = lst.fields.get(field_id) or next(
                        (f for f in lst.fields.values() if f.field_id == field_id or f.internal_name == field_id),
                        None,
                    )
                    if fld and fld.lookup_list:
                        target_id = (
                            from_list_id
                            if fld.lookup_list.strip().lower() == "self"
                            else (normalize_guid(fld.lookup_list) or fld.lookup_list)
                        )
                        alias_lists[as_name] = target_id
                        changed = True
        if not changed:
            break
    return alias_lists.get(alias_name)
