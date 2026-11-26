import json
import logging
from dataclasses import asdict

import pytest

from core.automation_service import (
    RelationEdgeView, catalog_field_options, catalog_list_options,
    catalog_view_options, create_node_dict, find_paths, new_workflow, parse_graph_json,
)
from core.config_service import GuiConfig, detect_latest_dirs, load_config, remember_url, save_config
from core.logging_service import LineWriter, LogBuffer, LogSession
from core.report_service import ReportRequest, resolve_portal_path, run_report_generation
from tools.sp_automation.catalog import Catalog, FieldRecord, ListRecord, ViewRecord


def test_config_round_trip_and_detected_defaults(tmp_path):
    (tmp_path / "DaneZeSkryptu_002").mkdir()
    path = tmp_path / "settings" / "config.json"
    detected = load_config(path, tmp_path)
    assert (detected.report_in, detected.report_out) == ("DaneZeSkryptu_002", "out_002")
    assert detected.relations_in == str(tmp_path / "DaneZeSkryptu_002")
    config = GuiConfig(
        active_tab=2, sharepoint_url="https://example.test/web",
        sharepoint_urls=["https://example.test/old"], auto_dir=False,
        custom_dir="eksport", include_data=True, report_in="wejscie", report_out="wynik",
        relations_in="relacje",
    )
    save_config(config, path)
    assert asdict(load_config(path, tmp_path)) == asdict(config)
    assert json.loads(path.read_text(encoding="utf-8"))["sharepoint_urls"][0] == config.sharepoint_url


def test_config_corrupt_json_logs_warning_and_keeps_detected_defaults(tmp_path, caplog):
    (tmp_path / "DaneZeSkryptu").mkdir()
    path = tmp_path / "config.json"
    path.write_text("{", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        config = load_config(path, tmp_path)
    assert config.report_in == "DaneZeSkryptu"
    assert "Nie udało się wczytać konfiguracji" in caplog.text


def test_config_filters_history_and_invalid_types(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "sharepoint_urls": [" https://example.test/a ", None, "", "https://example.test/a"],
        "sharepoint_url": " https://example.test/b ",
        "auto_dir": "false", "active_tab": "2", "report_in": " ",
    }), encoding="utf-8")
    config = load_config(path, tmp_path)
    assert config.sharepoint_urls == ["https://example.test/b", "https://example.test/a"]
    assert config.auto_dir is True
    assert config.active_tab == 0
    assert config.report_in == GuiConfig().report_in


def test_remember_url_deduplicates_trims_limits_and_does_not_mutate():
    history = ["a", "b", "c"]
    assert remember_url(history, " b ", limit=2) == ["b", "a"]
    assert remember_url(history, " ") == history
    assert remember_url(history, " ") is not history
    assert history == ["a", "b", "c"]


def test_detect_latest_dirs_ignores_files_and_pairs_suffix(tmp_path):
    assert detect_latest_dirs(tmp_path) is None
    (tmp_path / "DaneZeSkryptu").mkdir()
    assert detect_latest_dirs(tmp_path) == ("DaneZeSkryptu", "out")
    for name in ("DaneZeSkryptu_001", "DaneZeSkryptu_009", "DaneZeSkryptu_002"):
        (tmp_path / name).mkdir()
    (tmp_path / "DaneZeSkryptu_999").write_text("", encoding="utf-8")
    assert detect_latest_dirs(tmp_path) == ("DaneZeSkryptu_009", "out_009")


def test_log_buffer_eviction_incremental_reads_and_clear():
    buffer = LogBuffer(maxlen=2)
    assert buffer.get_since(0) == (0, [])
    first = buffer.append("pierwsza")
    second = buffer.append("druga")
    third = buffer.append("trzecia")
    assert buffer.get_since(first) == (third, ["druga", "trzecia"])
    assert buffer.get_since(second) == (third, ["trzecia"])
    buffer.clear()
    assert buffer.get_since(third) == (third, [])
    assert buffer.append("nowa") > third


def test_line_writer_handles_fragments_blank_lines_prefix_and_flush():
    lines = []
    writer = LineWriter(lines.append, prefix="[blad] ")
    assert writer.write("pier") == 4
    writer.write("wsza\n \n\nostatnia")
    assert lines == ["[blad] pierwsza"]
    writer.flush()
    writer.flush()
    assert lines == ["[blad] pierwsza", "[blad] ostatnia"]


def test_log_session_file_buffer_and_handler_cleanup(tmp_path):
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    console = logging.getLogger("dora.web.konsola")
    console_level, propagate = console.level, console.propagate
    session = LogSession(tmp_path)
    try:
        session.start()
        handlers = list(root.handlers)
        session.start()
        assert root.handlers == handlers
        session.log("wiadomosc testowa")
        logging.getLogger("test.dora.services").warning("ostrzezenie testowe")
        assert session.log_file_path is not None
        text = session.log_file_path.read_text(encoding="utf-8")
        assert "wiadomosc testowa" in text and "ostrzezenie testowe" in text
        _, lines = session.buffer.get_since(0)
        assert sum("wiadomosc testowa" in line for line in lines) == 1
    finally:
        session.close()
        root.setLevel(original_level)
        console.setLevel(console_level)
        console.propagate = propagate
    assert root.handlers == original_handlers
    session.close()


def test_resolve_portal_path_supports_relative_and_absolute_paths(tmp_path):
    expected = tmp_path / "wynik" / "workflow-migration-manual.html"
    assert resolve_portal_path(" wynik ", tmp_path) == expected
    assert resolve_portal_path(str(tmp_path / "wynik"), tmp_path) == expected


@pytest.mark.parametrize("input_dir,output_dir", [("", "out"), ("in", " "), (" ", "")])
def test_report_rejects_empty_paths_before_invoking_generator(tmp_path, monkeypatch, input_dir, output_dir):
    def unexpected_call(*args):
        pytest.fail("Generator nie powinien być wywołany.")

    monkeypatch.setattr("core.report_service.generate_report_main", unexpected_call)
    with pytest.raises(ValueError, match="Podaj katalog"):
        run_report_generation(ReportRequest(input_dir, output_dir, tmp_path))


def test_find_paths_cycles_depth_and_truncation():
    def edge(source, target):
        return RelationEdgeView(source + target, source, target, "Relacja", "")

    direct, first, second, cycle = edge("a", "c"), edge("a", "b"), edge("b", "c"), edge("b", "a")
    relations = [direct, first, second, cycle]
    assert find_paths(relations, "a", "c") == ([[direct], [first, second]], False)
    assert find_paths(relations, "a", "c", max_depth=1) == ([[direct]], False)
    assert find_paths(relations, "a", "c", max_paths=1) == ([[direct]], True)
    assert find_paths(relations, "c", "a") == ([], False)


def test_relations_view_adds_incoming_and_outgoing_neighbors_only_once():
    from core.automation_service import ListItemView, build_relations_view

    lists = [ListItemView(key, key.upper(), "") for key in "abcd"]
    edges = [
        RelationEdgeView("ab", "a", "b", "AB", ""),
        RelationEdgeView("ca", "c", "a", "CA", ""),
        RelationEdgeView("bd", "b", "d", "BD", ""),
        RelationEdgeView("ba", "b", "a", "BA", ""),
        RelationEdgeView("ab2", "a", "b", "Another lookup", ""),
    ]
    selected = {"a"}
    nodes, visible = build_relations_view(lists, edges, selected)
    assert [item.key for item in nodes] == ["a", "b", "c"]
    assert [edge.key for edge in visible] == ["ab", "ca", "ba", "ab2"]
    assert selected == {"a"}
    nodes, visible = build_relations_view(lists, edges, {"a", "b"})
    assert [item.key for item in nodes] == ["a", "b", "c", "d"]
    assert visible == edges
    assert build_relations_view(lists, edges, set()) == ([], [])


@pytest.mark.parametrize("metadata,reason", [
    ({"Hidden": True}, "Hidden"),
    ({"IsCatalog": True}, "IsCatalog"),
    ({"BaseTemplate": 112}, "User Information"),
    ({"BaseTemplate": "140"}, "Workflow History"),
    ({"BaseTemplate": 5001}, "NintexWorkflows"),
    ({"BaseTemplate": 101, "Hidden": False}, ""),
    ({"BaseTemplate": 100, "IsApplicationList": True}, ""),
    ({"Hidden": "false", "IsCatalog": False}, ""),
    ({}, ""),
])
def test_system_list_classification_uses_explicit_metadata(metadata, reason):
    from core.automation_service import system_list_reason

    actual = system_list_reason(ListRecord("a", "Business", metadata=metadata))
    assert reason in actual if reason else actual == ""


def test_relations_view_filters_system_nodes_and_preserves_unknown_targets():
    from core.automation_service import ListItemView, build_relations_view

    lists = [
        ListItemView("a", "A", ""),
        ListItemView("b", "B", "", is_system=True),
        ListItemView("c", "C", ""),
    ]
    edges = [
        RelationEdgeView("ab", "a", "b", "AB", ""),
        RelationEdgeView("ca", "c", "a", "CA", ""),
        RelationEdgeView("ax", "a", "unknown", "AX", "", "External"),
    ]
    nodes, visible = build_relations_view(lists, edges, {"a", "b"}, show_system=False)
    assert [node.key for node in nodes] == ["a", "c", "unknown"]
    assert [edge.key for edge in visible] == ["ca", "ax"]
    assert nodes[-1].is_external and not nodes[-1].is_system
    assert build_relations_view(lists, edges, {"b"}, show_system=False) == ([], [])
    nodes, visible = build_relations_view(lists, edges, {"a"}, auto_related=False)
    assert [node.key for node in nodes] == ["a"]
    assert visible == []
    nodes, visible = build_relations_view(
        lists, edges, {"a"}, auto_related=False, include_external=True,
    )
    assert [node.key for node in nodes] == ["a", "b", "unknown"]
    assert [edge.key for edge in visible] == ["ab", "ax"]


def test_load_relations_exposes_system_classification_without_changing_catalog(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core.automation_service import ListItemView, load_relations

    catalog = Catalog(lists={"a": ListRecord("a", "History", metadata={"BaseTemplate": 140})})
    snapshot = SimpleNamespace(
        lists=[ListItemView("a", "History", "Original details", priority=True)],
        relations=[], summary="Summary", diagnostics="", catalog=catalog,
    )
    monkeypatch.setattr("core.automation_service.load_relations_snapshot", lambda _path: snapshot)
    data = load_relations(tmp_path)
    assert data.catalog is catalog
    assert data.lists[0].is_system and data.lists[0].priority
    assert data.lists[0].details.startswith("Original details")
    assert "Workflow History (BaseTemplate=140)" in data.lists[0].details
    assert catalog.lists["a"].metadata == {"BaseTemplate": 140}


def test_ignored_fields_policy_config_rule_and_fallbacks(tmp_path):
    from tools.sp_automation.ignored_fields import load_ignored_fields

    guid = "22222222-2222-4222-8222-222222222222"
    lookup = lambda name, target, base=False: FieldRecord(
        name, name, "Lookup", "", lookup_list=target, metadata={"FromBaseType": base},
    )
    path = tmp_path / "ignored.json"
    path.write_text(json.dumps({"ignored_fields": {"Grupa": ["predecessors", 7]}}), encoding="utf-8")
    policy = load_ignored_fields(path)
    assert policy.is_ignored(lookup("Predecessors", guid))
    assert policy.is_ignored(lookup("FileRef", "Docs", base=True))
    assert policy.is_ignored(lookup("AppAuthor", "AppPrincipals", base=True))
    assert not policy.is_ignored(lookup("Builtin", guid, base=True))
    assert not policy.is_ignored(lookup("Parent", "Self", base=True))
    assert not policy.is_ignored(lookup("FileRef", "Docs"))
    assert len(policy.warnings) == 1

    path.write_text(json.dumps({"ignore_base_type_non_list_targets": False}), encoding="utf-8")
    assert not load_ignored_fields(path).is_ignored(lookup("FileRef", "Docs", base=True))

    path.write_text("{", encoding="utf-8")
    broken = load_ignored_fields(path)
    missing = load_ignored_fields(tmp_path / "missing.json")
    for fallback in (broken, missing):
        assert fallback.warnings and fallback.is_ignored(lookup("FileRef", "Docs", base=True))
        assert not fallback.is_ignored(lookup("Predecessors", guid))


def test_relations_view_hides_ignored_fields_unless_requested():
    from core.automation_service import ListItemView, build_relations_view

    lists = [ListItemView("a", "A", ""), ListItemView("b", "B", "")]
    edges = [
        RelationEdgeView("ab", "a", "b", "AB", ""),
        RelationEdgeView("a:FileRef", "a", "invalid:a:FileRef", "Ścieżka", "", "Nieznana", "systemowe"),
    ]
    nodes, visible = build_relations_view(lists, edges, {"a"})
    assert [node.key for node in nodes] == ["a", "b"] and [edge.key for edge in visible] == ["ab"]
    nodes, visible = build_relations_view(lists, edges, {"a"}, show_ignored_fields=True)
    assert [edge.key for edge in visible] == ["ab", "a:FileRef"]
    assert nodes[-1].is_external


def test_load_relations_marks_ignored_fields_and_reports_policy_warnings(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core.automation_service import ListItemView, load_relations
    from tools.sp_automation.ignored_fields import IgnoredFieldsPolicy

    fields = {
        "FileRef": FieldRecord("FileRef", "Ścieżka", "Lookup", "", lookup_list="Docs", metadata={"FromBaseType": True}),
        "Link": FieldRecord("Link", "Link", "Lookup", "", lookup_list="b"),
    }
    catalog = Catalog(lists={"a": ListRecord("a", "A", fields=fields)})
    snapshot = SimpleNamespace(
        lists=[ListItemView("a", "A", "")],
        relations=[
            RelationEdgeView("a:FileRef", "a", "invalid:a:FileRef", "Ścieżka", "Szczegóły"),
            RelationEdgeView("a:Link", "a", "b", "Link", "Szczegóły"),
        ],
        summary="Summary.", diagnostics="", catalog=catalog,
    )
    monkeypatch.setattr("core.automation_service.load_relations_snapshot", lambda _path: snapshot)
    data = load_relations(tmp_path, IgnoredFieldsPolicy(warnings=("Brak pliku.",)))
    assert [bool(edge.ignored_reason) for edge in data.relations] == [True, False]
    assert "Pominięte domyślnie" in data.relations[0].details
    assert data.ignored_count == 1 and "pól systemowych: 1" in data.summary
    assert data.diagnostics == "Brak pliku."


def test_designer_lookup_options_and_comparisons_skip_ignored_fields():
    from tools.sp_automation.comparison import comparison_paths
    from tools.sp_automation.ignored_fields import IgnoredFieldsPolicy

    a, b, c = (f"{n}{n}{n}{n}{n}{n}{n}{n}-0000-4000-8000-000000000000" for n in (1, 2, 3))
    lookup = lambda name, target, **meta: FieldRecord(name, name, "Lookup", name, lookup_list=target, metadata=meta)
    catalog = Catalog(lists={
        a: ListRecord(a, "A", fields={
            "ToC": lookup("ToC", c), "ToB": lookup("ToB", b),
            "AppAuthor": lookup("AppAuthor", "AppPrincipals", FromBaseType=True),
            "Predecessors": lookup("Predecessors", a),
        }),
        b: ListRecord(b, "B", fields={"BToC": lookup("BToC", c)}),
        c: ListRecord(c, "C"),
    })
    assert set(catalog_field_options(catalog, a, mode="lookup")) == {"ToC", "ToB"}
    assert len(comparison_paths(catalog, {a, b, c})) == 1
    skip_b = IgnoredFieldsPolicy(frozenset({"tob"}))
    assert comparison_paths(catalog, {a, b, c}, skip_b.is_ignored) == []


def test_workflow_drafts_are_independent_and_can_be_parsed():
    first, second = new_workflow(), new_workflow()
    first["nodes"].append(create_node_dict("assign", "assign_1"))
    first["scope"]["type"] = "view"
    assert len(second["nodes"]) == 1 and second["scope"] == {"type": "all"}
    assert first["id"] != second["id"]
    assert parse_graph_json(json.dumps(first)) == first


@pytest.mark.parametrize("kind,attributes", [
    ("lookup", {"from": "source", "field_id": "", "as": ""}),
    ("condition", {"merge": "", "condition": {"op": "exists", "alias": "source"}}),
    ("assign", {"alias": "source", "field_id": "", "value": {"kind": "literal", "value": None}}),
    ("merge", {}), ("end", {}),
])
def test_create_node_draft_contract(kind, attributes):
    assert create_node_dict(kind, "node") == {"id": "node", "type": kind, **attributes}


@pytest.mark.parametrize("text,message", [
    ('{"id":1,"id":2}', "Powtórzony klucz"),
    ('{"condition":{"op":"eq","op":"ne"}}', "Powtórzony klucz"),
    ('{"value":NaN}', "Niepoprawna liczba"),
    ('{"value":Infinity}', "Niepoprawna liczba"),
    ('[]', "obiekt JSON"),
])
def test_graph_parser_rejects_ambiguous_and_invalid_json(text, message):
    with pytest.raises(ValueError, match=message):
        parse_graph_json(text)


def test_catalog_options_filter_sort_and_handle_missing_catalog():
    lookup = FieldRecord("Link", "Relacja", "Lookup", "lookup-id", lookup_list="target")
    title = FieldRecord("Title", "Tytuł", "Text", "title-id")
    fallback = FieldRecord("Manual", "Ręczne", "Text")
    catalog = Catalog(lists={
        "z": ListRecord("z", "Zeta"),
        "a": ListRecord("a", "Alfa", fields={"Title": title, "Link": lookup, "Manual": fallback},
                        views=[ViewRecord("z-view", "Zeta"), ViewRecord("a-view", "Alfa")]),
    })
    assert list(catalog_list_options(catalog)) == ["a", "z"]
    assert list(catalog_view_options(catalog, "a")) == ["a-view", "z-view"]
    assert catalog_view_options(catalog, "missing") == {}
    assert catalog_field_options(catalog, lookup_only=True) == {
        "lookup-id": "Alfa: Relacja [Link] (Lookup)",
    }
    assert catalog_field_options(catalog, "a")["title-id"] == "Tytuł [Title] (Text)"
    assert "Manual" in catalog_field_options(catalog)
    assert catalog_list_options(None) == {}
    assert catalog_view_options(None, "a") == {}
    assert catalog_field_options(None) == {}


def test_validate_graph_reports_clear_errors_and_fills_fingerprint():
    from core.automation_service import new_workflow, validate_graph
    from tools.sp_automation.models import GraphError

    list_guid = "7cb6c650-ee85-45f2-93c5-4eadc8382043"
    catalog = Catalog(lists={
        list_guid: ListRecord(
            list_guid,
            "Lista",
            fields={"Title": FieldRecord("Title", "Tytuł", "Text", "d340fca5-f503-4baa-bae9-90f1447ebff6")},
            definition_status="complete",
            schema_fingerprint="fp-1",
        ),
    })
    raw = new_workflow()
    raw["source_list_id"] = list_guid
    raw["nodes"].append({"id": "end_1", "type": "end"})
    raw["edges"].append({"from": "start", "to": "end_1"})
    raw["layout"]["end_1"] = {"x": 300, "y": 100}

    with pytest.raises(GraphError, match="Witryna SharePoint"):
        validate_graph(raw, catalog)

    raw["site"] = "https://example.test/sites/dora"
    validated = validate_graph(raw, catalog)
    assert validated.to_dict()["schema_fingerprint"]
    assert validated.to_dict()["edges"][0]["port"] == "next"


def test_catalog_options_and_summaries_hide_guids_and_disambiguate_titles():
    from core.automation_service import (
        format_condition_summary,
        resolve_field_label,
        resolve_list_label,
    )

    guid_a = "7cb6c650-ee85-45f2-93c5-4eadc8382043"
    guid_b = "d340fca5-f503-4baa-bae9-90f1447ebff6"
    view_a = "11111111-1111-4111-8111-111111111111"
    view_b = "22222222-2222-4222-8222-222222222222"
    field_guid = "33333333-3333-4333-8333-333333333333"
    unknown_guid = "44444444-4444-4444-8444-444444444444"

    catalog = Catalog(lists={
        guid_a: ListRecord(
            guid_a,
            "Wspólna nazwa",
            fields={"Status": FieldRecord("Status", "Status oceny", "Text", field_guid)},
            views=[ViewRecord(view_a, "Widok"), ViewRecord(view_b, "Widok")],
        ),
        guid_b: ListRecord(guid_b, "Wspólna nazwa"),
    })

    list_opts = catalog_list_options(catalog)
    assert set(list_opts) == {guid_a, guid_b}
    assert all(guid_a not in label and guid_b not in label for label in list_opts.values())
    assert set(list_opts.values()) == {"Wspólna nazwa", "Wspólna nazwa (#2)"}

    view_opts = catalog_view_options(catalog, guid_a)
    assert set(view_opts) == {view_a, view_b}
    assert all(view_a not in label and view_b not in label for label in view_opts.values())
    assert set(view_opts.values()) == {"Widok", "Widok (#2)"}

    assert resolve_list_label(catalog, guid_a) == "Wspólna nazwa"
    assert resolve_list_label(catalog, unknown_guid) == "Lista (spoza katalogu)"
    assert unknown_guid not in resolve_list_label(catalog, unknown_guid)
    assert resolve_field_label(catalog, field_guid, guid_a) == "Status oceny [Status]"
    assert resolve_field_label(catalog, unknown_guid, guid_a) == ""

    summary = format_condition_summary(
        {
            "op": "and",
            "conditions": [
                {"op": "eq", "left": {"kind": "field", "alias": "source", "field_id": field_guid}, "right": {"kind": "literal", "value": "OK"}},
                {"op": "not_empty", "value": {"kind": "field", "alias": "source", "field_id": unknown_guid}},
            ],
        },
        {"source_list_id": guid_a, "nodes": []},
        catalog,
    )
    assert "Status oceny [Status]" in summary
    assert "(pole z definicji)" in summary
    assert field_guid not in summary
    assert unknown_guid not in summary


def test_simulation_and_online_preview_rows_hide_guids(monkeypatch):
    from core.automation_service import run_offline_simulation, run_online_preview
    from tools.sp_automation.models import Graph
    from tools.sp_automation.tests.test_engine import GOAL, SOURCE, graph
    from tools.sp_automation.tests.test_sharepoint import setup_reader
    from tools.sp_automation.tests.test_snapshot_adapter import catalog as sim_catalog, ready_graph

    cat = sim_catalog()
    sim_outcome = run_offline_simulation(cat, ready_graph(cat))
    assert sim_outcome.rows
    for row in sim_outcome.rows:
        assert SOURCE not in row["list"]
        assert GOAL not in row["field"]
    assert sim_outcome.trace_rows
    for trace_row in sim_outcome.trace_rows:
        assert SOURCE not in trace_row["variables"]
        assert SOURCE not in trace_row["result"]
        assert GOAL not in trace_row["variables"]
        assert GOAL not in trace_row["result"]
    assert any("PRAWDA" in row["result"] for row in sim_outcome.trace_rows)
    assert any("Propozycja:" in row["result"] for row in sim_outcome.trace_rows)

    reader, _ = setup_reader()
    fresh = reader.refresh_schema(Graph.from_dict(graph()))
    monkeypatch.setattr("core.automation_service.read_with_windows_sso", lambda _g: reader.read_snapshot(fresh))
    online_outcome = run_online_preview(fresh, catalog=None)
    assert online_outcome.rows
    for row in online_outcome.rows:
        assert SOURCE not in row["list"]
        assert GOAL not in row["field"]
    assert "site " not in online_outcome.details_lines[0]
    assert "web " not in online_outcome.details_lines[0]


def test_catalog_options_filter_by_operation_context():
    from core.automation_service import catalog_reverse_lookup_list_options

    source_id = "11111111-1111-4111-8111-111111111111"
    target_id = "22222222-2222-4222-8222-222222222222"
    other_id = "33333333-3333-4333-8333-333333333333"

    def _id(n: int) -> str:
        return f"{n:08d}-0000-4000-8000-000000000000"

    fields = {
        "Title": FieldRecord("Title", "Symbol kategorii", "Text", _id(1), metadata={"ReadOnlyField": False, "Required": True, "MaxLength": 255}),
        "LinkTitleNoMenu": FieldRecord("LinkTitleNoMenu", "Symbol kategorii", "Computed", _id(2), metadata={"ReadOnlyField": True, "Required": False}),
        "Calc": FieldRecord("Calc", "Wyliczane", "Calculated", _id(3), metadata={"ReadOnlyField": True, "Required": False}),
        "ID": FieldRecord("ID", "ID", "Counter", _id(4), metadata={"ReadOnlyField": True, "Required": False, "FromBaseType": True}),
        "Author": FieldRecord("Author", "Utworzył", "User", _id(5), lookup_list="UserInfo", metadata={"ReadOnlyField": True, "Required": False, "FromBaseType": True}),
        "ReadOnlyText": FieldRecord("ReadOnlyText", "Tylko odczyt", "Text", _id(6), metadata={"ReadOnlyField": True, "Required": False, "MaxLength": 100}),
        "HiddenText": FieldRecord("HiddenText", "Ukryte", "Text", _id(7), metadata={"ReadOnlyField": False, "Required": False, "MaxLength": 100, "Hidden": True}),
        "RichNote": FieldRecord("RichNote", "Opis HTML", "Note", _id(8), metadata={"ReadOnlyField": False, "Required": False, "RichText": True, "AppendOnly": False}),
        "PlainNote": FieldRecord("PlainNote", "Opis zwykły", "Note", _id(9), metadata={"ReadOnlyField": False, "Required": False, "RichText": False, "AppendOnly": False}),
        "MultiChoice": FieldRecord("MultiChoice", "Wybór wielokrotny", "Choice", _id(10), metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": True, "Choices": ["A", "B"]}),
        "SingleChoice": FieldRecord("SingleChoice", "Status", "Choice", _id(11), metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": False, "Choices": ["Nowy", "OK"]}),
        "Amount": FieldRecord("Amount", "Kwota", "Currency", _id(12), metadata={"ReadOnlyField": False, "Required": False}),
        "CountNum": FieldRecord("CountNum", "Liczba", "Number", _id(13), metadata={"ReadOnlyField": False, "Required": False}),
        "RefTarget": FieldRecord("RefTarget", "Kategoria", "Lookup", _id(14), lookup_list=target_id, metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": False}),
        "RefTargetProj": FieldRecord("RefTargetProj", "Kategoria:Opis", "Lookup", _id(15), lookup_list=target_id, field_ref="RefTarget", metadata={"ReadOnlyField": True, "Required": False, "IsDependentLookup": True}),
        "RefMulti": FieldRecord("RefMulti", "Wiele kategorii", "LookupMulti", _id(16), lookup_list=target_id, metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": True}),
        "RefOther": FieldRecord("RefOther", "Inna lista", "Lookup", _id(17), lookup_list=other_id, metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": False}),
    }
    catalog = Catalog(lists={
        source_id: ListRecord(source_id, "Źródło", fields=fields),
        target_id: ListRecord(target_id, "Docelowa", fields={
            "BackToSource": FieldRecord("BackToSource", "Powiązane źródło", "Lookup", _id(20), lookup_list=source_id, metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": False}),
            "TitleT": FieldRecord("Title", "Nazwa", "Text", _id(21), metadata={"ReadOnlyField": False, "Required": False, "MaxLength": 255}),
        }),
        other_id: ListRecord(other_id, "Niepowiązana", fields={
            "TitleO": FieldRecord("Title", "Nazwa", "Text", _id(22), metadata={"ReadOnlyField": False, "Required": False, "MaxLength": 255}),
        }),
    })

    writable = catalog_field_options(catalog, source_id, mode="writable")
    assert set(writable) == {_id(1), _id(9), _id(11), _id(12), _id(13), _id(14), _id(17)}

    readable = catalog_field_options(catalog, source_id, mode="readable")
    assert _id(2) not in readable  # Computed
    assert _id(3) not in readable  # Calculated
    assert _id(4) not in readable  # Counter
    assert _id(5) not in readable  # User
    assert _id(7) not in readable  # Hidden
    assert _id(15) not in readable  # Dependent FieldRef
    assert {_id(1), _id(6), _id(8), _id(9), _id(10), _id(11), _id(12), _id(13), _id(14), _id(16), _id(17)} == set(readable)

    # Type compatibility filtering for expression target
    assert set(catalog_field_options(catalog, source_id, mode="readable", compatible_with=fields["Amount"])) == {_id(12), _id(13)}
    assert set(catalog_field_options(catalog, source_id, mode="readable", compatible_with=fields["RefTarget"], compatible_list_id=source_id)) == {_id(14)}

    # Lookup mode excludes User(UserInfo) and dependent FieldRef
    lookups = catalog_field_options(catalog, source_id, mode="lookup")
    assert set(lookups) == {_id(14), _id(16), _id(17)}
    assert set(catalog_field_options(catalog, source_id, mode="lookup", lookup_target_list_id=target_id)) == {_id(14), _id(16)}

    # Reverse lookup lists only include lists pointing to source_id
    assert set(catalog_reverse_lookup_list_options(catalog, source_id)) == {target_id}
