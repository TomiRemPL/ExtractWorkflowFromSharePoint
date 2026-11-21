from copy import deepcopy
from dataclasses import replace
import os
from pathlib import Path

import pytest

from tools.sp_automation.catalog import Catalog, FieldRecord, ListRecord, load_catalog
from tools.sp_automation.engine import simulate
from tools.sp_automation.models import Graph
from tools.sp_automation.snapshot_adapter import (
    SnapshotAdapterError,
    build_simulation_snapshot,
    catalog_graph_fingerprint,
)
from tools.sp_automation.tests.test_engine import GOAL, REL, RELATED_GOAL, SOURCE, TARGET, graph


def catalog() -> Catalog:
    def lookup(name, field_id, target):
        return FieldRecord(
            name, name, "Lookup", field_id=field_id, entity_property_name=name,
            lookup_list=target,
            metadata={"ReadOnlyField": False, "Required": False, "AllowMultipleValues": False},
        )

    return Catalog(
        site_url="https://example.test/sites/test/",
        lists={
            SOURCE: ListRecord(
                SOURCE, "Source",
                fields={
                    "Mechanism": lookup("Mechanism", REL, TARGET),
                    "Goal": lookup("Goal", GOAL, TARGET),
                },
                rows=[
                    {"ID": 1, "MechanismId": 10, "GoalId": None},
                    {"ID": 2, "MechanismId": 11, "GoalId": 12},
                ],
                definition_status="unconfirmed", data_status="unconfirmed",
                item_count=3, schema_fingerprint="source-schema",
            ),
            TARGET: ListRecord(
                TARGET, "Target",
                fields={"Goal": lookup("Goal", RELATED_GOAL, TARGET)},
                rows=[{"ID": 10, "GoalId": 12}, {"ID": 11, "GoalId": 10}, {"ID": 12, "GoalId": None}],
                definition_status="unconfirmed", data_status="unconfirmed",
                schema_fingerprint="target-schema",
            ),
        },
    )


def ready_graph(source_catalog: Catalog) -> Graph:
    definition = graph()
    definition["schema_fingerprint"] = catalog_graph_fingerprint(source_catalog, definition)
    return Graph.from_dict(definition)


def test_historical_catalog_adapts_to_explicitly_incomplete_advisory_simulation():
    source_catalog = catalog()
    definition = ready_graph(source_catalog)
    adapted = build_simulation_snapshot(source_catalog, definition)
    assert adapted.complete is False
    assert len(adapted.warnings) == 3
    assert adapted.data["lists"][SOURCE]["complete"] is False
    assert adapted.data["lists"][SOURCE]["items"][0]["Mechanism"] == 10
    assert adapted.data["lists"][SOURCE]["items"][0]["Goal"] is None
    assert adapted.data["lists"][SOURCE]["fields"][GOAL]["writable"] is True
    result = simulate(definition, adapted.data, allow_incomplete=True)
    assert result.snapshot_complete is False
    assert [(change.item_id, change.new_value) for change in result.changes] == [(1, 12)]


def test_catalog_fingerprint_changes_with_referenced_list_schema():
    source_catalog = catalog()
    definition = ready_graph(source_catalog)
    old_fingerprint = definition.to_dict()["schema_fingerprint"]
    source_catalog.lists[TARGET].schema_fingerprint = "changed"
    with pytest.raises(SnapshotAdapterError, match="Fingerprint"):
        build_simulation_snapshot(source_catalog, definition)
    assert catalog_graph_fingerprint(source_catalog, definition) != old_fingerprint


@pytest.mark.parametrize("mutation,match", [
    (lambda value: setattr(value, "site_url", "https://other.example.test/sites/test"), "Adres witryny"),
    (lambda value: setattr(value.lists[TARGET], "rows", None), "Brak wyeksportowanych danych"),
    (lambda value: setattr(value.lists[TARGET], "definition_status", "identity_error"), "Brakuje schematu"),
])
def test_adapter_fails_closed_for_site_missing_data_and_schema_changes(mutation, match):
    source_catalog = catalog()
    definition = ready_graph(source_catalog)
    changed = deepcopy(source_catalog)
    mutation(changed)
    with pytest.raises(SnapshotAdapterError, match=match):
        build_simulation_snapshot(changed, definition)


def test_adapter_rejects_missing_or_ambiguous_relationship_field():
    source_catalog = catalog()
    definition = graph()
    definition["nodes"][1]["field_id"] = "00000000-0000-0000-0000-000000000099"
    with pytest.raises(SnapshotAdapterError, match="Pole grafu"):
        catalog_graph_fingerprint(source_catalog, definition)


def test_assignment_lookup_target_is_included_in_snapshot_even_without_lookup_node():
    source_catalog = catalog()
    extra_id = "00000000-0000-0000-0000-000000000099"
    source_catalog.lists[extra_id] = ListRecord(
        extra_id, "Other target", rows=[{"ID": 30}],
        definition_status="unconfirmed", data_status="unconfirmed",
        schema_fingerprint="other-schema",
    )
    goal = source_catalog.lists[SOURCE].fields["Goal"]
    source_catalog.lists[SOURCE].fields["Goal"] = replace(
        goal, lookup_list=extra_id, metadata={**goal.metadata, "LookupList": extra_id},
    )
    definition = graph()
    definition["nodes"][3]["value"] = {"kind": "literal", "value": 30}
    definition["schema_fingerprint"] = catalog_graph_fingerprint(source_catalog, definition)
    adapted = build_simulation_snapshot(source_catalog, Graph.from_dict(definition))
    assert extra_id in adapted.data["lists"]


@pytest.mark.skipif(os.environ.get("CHECK_SP_005") != "1", reason="local snapshot verification is opt-in")
def test_optional_real_005_simulates_control_goal_proposals_as_incomplete():
    root = Path(os.environ.get("SP_EXPORT_DIR", "DaneZeSkryptu_005"))
    if not (root / "extraction_manifest.json").is_file():
        pytest.skip("local export 005 unavailable")
    source_id = "435dadf3-ab5d-4d56-a38e-f7bb8e837c53"
    mechanism_field = "c4c4746c-30a8-4743-a137-20c8ef4f4158"
    source_goal_field = "9d656282-a5c3-4db8-8caa-0f88ac86ebd8"
    mechanism_goal_field = "e06cc6ab-b8b4-481f-9aba-4e873a449870"
    source_catalog = load_catalog(root)
    definition = {
        "schema_version": 1, "id": "r0011-goal-preview", "name": "R0011 — cel przez mechanizm",
        "site": source_catalog.site_url, "source_list_id": source_id,
        "schema_fingerprint": "pending", "max_updates": 99, "text_policy": "exact",
        "scope": {"type": "all"},
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "mechanism", "type": "lookup", "from": "source", "field_id": mechanism_field, "as": "mechanism"},
            {"id": "condition", "type": "condition", "merge": "merge", "condition": {"op": "and", "conditions": [
                {"op": "exists", "alias": "mechanism"},
                {"op": "empty", "value": {"kind": "field", "alias": "source", "field_id": source_goal_field}},
                {"op": "not_empty", "value": {"kind": "field", "alias": "mechanism", "field_id": mechanism_goal_field}},
            ]}},
            {"id": "assign", "type": "assign", "alias": "source", "field_id": source_goal_field,
             "value": {"kind": "field", "alias": "mechanism", "field_id": mechanism_goal_field}},
            {"id": "merge", "type": "merge"}, {"id": "end", "type": "end"},
        ],
        "edges": [
            {"from": "start", "port": "next", "to": "mechanism"},
            {"from": "mechanism", "port": "next", "to": "condition"},
            {"from": "condition", "port": "true", "to": "assign"},
            {"from": "condition", "port": "false", "to": "merge"},
            {"from": "assign", "port": "next", "to": "merge"},
            {"from": "merge", "port": "next", "to": "end"},
        ],
    }
    definition["schema_fingerprint"] = catalog_graph_fingerprint(source_catalog, definition)
    adapted = build_simulation_snapshot(source_catalog, Graph.from_dict(definition))
    result = simulate(Graph.from_dict(definition), adapted.data, allow_incomplete=True)
    expected_complete = all(
        source_catalog.lists[list_id].data_status == "complete"
        and source_catalog.lists[list_id].definition_status == "complete"
        for list_id in adapted.data["lists"]
    )
    assert adapted.complete is expected_complete
    assert result.snapshot_complete is expected_complete
    assert len(result.changes) == 3
