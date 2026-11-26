import json

import pytest

from tools.sp_automation.engine import SimulationError, preview_is_current, simulate
from tools.sp_automation.models import Graph, GraphError


SOURCE = "00000000-0000-0000-0000-000000000001"
TARGET = "00000000-0000-0000-0000-000000000002"
REL = "00000000-0000-0000-0000-000000000011"
GOAL = "00000000-0000-0000-0000-000000000012"
RELATED_GOAL = "00000000-0000-0000-0000-000000000013"


def snapshot():
    return {
        "site": "https://example.test/sites/test",
        "schema_fingerprint": "schema-1",
        "lists": {
            SOURCE: {"complete": True, "fields": {
                REL: {"internal_name": "Mechanism", "entity_property_name": "Mechanism", "type": "Lookup", "lookup_list_id": TARGET},
                GOAL: {"internal_name": "Goal", "entity_property_name": "GoalRest", "type": "Lookup", "lookup_list_id": TARGET, "writable": True, "constraints_verified": True, "required": False},
            }, "items": [{"ID": 1, "Mechanism": 10, "Goal": None}, {"ID": 2, "Mechanism": 11, "Goal": 12}]},
            TARGET: {"complete": True, "fields": {
                RELATED_GOAL: {"internal_name": "Goal", "entity_property_name": "Goal", "type": "Lookup", "lookup_list_id": TARGET},
            }, "items": [{"ID": 10, "Goal": 12}, {"ID": 11, "Goal": 10}, {"ID": 12, "Goal": None}]},
        },
    }


def graph():
    field = lambda alias, field_id: {"kind": "field", "alias": alias, "field_id": field_id}
    return {
        "schema_version": 1, "id": "example", "name": "Example", "site": "https://example.test/sites/test",
        "source_list_id": SOURCE, "schema_fingerprint": "schema-1", "max_updates": 10, "text_policy": "exact",
        "scope": {"type": "all"},
        "nodes": [
            {"id": "start", "type": "start"},
            {"id": "read", "type": "lookup", "from": "source", "field_id": REL, "as": "mechanism"},
            {"id": "if", "type": "condition", "merge": "merge", "condition": {"op": "and", "conditions": [
                {"op": "exists", "alias": "mechanism"},
                {"op": "empty", "value": field("source", GOAL)},
                {"op": "not_empty", "value": field("mechanism", RELATED_GOAL)},
            ]}},
            {"id": "set", "type": "assign", "alias": "source", "field_id": GOAL, "value": field("mechanism", RELATED_GOAL)},
            {"id": "merge", "type": "merge"}, {"id": "end", "type": "end"},
        ],
        "edges": [
            {"from": "start", "port": "next", "to": "read"}, {"from": "read", "port": "next", "to": "if"},
            {"from": "if", "port": "true", "to": "set"}, {"from": "if", "port": "false", "to": "merge"},
            {"from": "set", "port": "next", "to": "merge"}, {"from": "merge", "port": "next", "to": "end"},
        ],
        "layout": {"start": {"x": 1, "y": 2}},
    }


def test_read_only_lookup_proposal_and_json_roundtrip():
    data = snapshot()
    before = json.dumps(data, sort_keys=True)
    definition = Graph.from_json(json.dumps(graph()))
    assert Graph.from_json(definition.to_json()).to_json() == definition.to_json()
    result = simulate(definition, data)
    assert simulate(definition, data) == result
    assert [(change.item_id, change.field_id, change.old_value, change.new_value) for change in result.changes] == [(1, GOAL, None, 12)]
    assert result.changes[0].entity_property_name == "GoalRest"
    assert json.dumps(data, sort_keys=True) == before


def test_preview_invalidation_and_noop_on_new_snapshot():
    data = snapshot()
    definition = Graph.from_dict(graph())
    result = simulate(definition, data)
    assert preview_is_current(result, definition, data)
    data["lists"][SOURCE]["items"][0]["Goal"] = 12
    assert not preview_is_current(result, definition, data)
    assert not simulate(definition, data).changes
    changed_graph = graph()
    changed_graph["layout"]["start"]["x"] = 50
    assert not preview_is_current(result, Graph.from_dict(changed_graph), snapshot())


@pytest.mark.parametrize("mutation", [
    lambda g: g["edges"][2].update(port="wrong"),
    lambda g: g["edges"].pop(3),
    lambda g: g["edges"][5].update(to="start"),
    lambda g: g["nodes"].append({"id": "orphan", "type": "end"}),
    lambda g: g["nodes"][2].update(merge="end"),
    lambda g: g["nodes"][3].update(value={"kind": "python", "value": "print(1)"}),
    lambda g: g.update(schema_version=True),
    lambda g: g.update(text_policy="case-insensitive"),
])
def test_graph_rejects_invalid_structure(mutation):
    value = graph()
    mutation(value)
    with pytest.raises(GraphError):
        Graph.from_dict(value)


def test_reject_duplicate_json_keys_and_credential_url():
    with pytest.raises(GraphError):
        Graph.from_json('{"schema_version":1,"schema_version":1}')
    value = graph()
    value["site"] = "https://user:password@example.test"
    with pytest.raises(GraphError):
        Graph.from_dict(value)


def test_null_differs_from_missing_and_dangling_lookup():
    definition = Graph.from_dict(graph())
    data = snapshot()
    data["lists"][SOURCE]["items"][0]["Mechanism"] = None
    assert not simulate(definition, data).changes
    del data["lists"][SOURCE]["items"][0]["Mechanism"]
    with pytest.raises(SimulationError, match="absent"):
        simulate(definition, data)
    data["lists"][SOURCE]["items"][0]["Mechanism"] = 999
    with pytest.raises(SimulationError, match="missing"):
        simulate(definition, data)


@pytest.mark.parametrize("property,value", [("writable", False), ("readonly", True), ("system", True), ("field_ref", "other"), ("constraints_verified", False), ("type", "Calculated"), ("lookup_list_id", None)])
def test_unsafe_fields_fail_closed(property, value):
    data = snapshot()
    data["lists"][SOURCE]["fields"][GOAL][property] = value
    with pytest.raises(SimulationError):
        simulate(Graph.from_dict(graph()), data)


def test_scope_fingerprint_limit_and_completeness_are_checked():
    definition = graph()
    data = snapshot()
    definition["max_updates"] = 0
    with pytest.raises(SimulationError, match="limit"):
        simulate(Graph.from_dict(definition), data)
    definition["max_updates"] = 10
    definition["schema_fingerprint"] = "outdated"
    with pytest.raises(SimulationError, match="fingerprint"):
        simulate(Graph.from_dict(definition), data)
    definition["schema_fingerprint"] = "schema-1"
    definition["scope"] = {"type": "ids", "ids": [999]}
    with pytest.raises(SimulationError, match="Selected"):
        simulate(Graph.from_dict(definition), data)
    definition["scope"] = {"type": "all"}
    data["lists"][TARGET]["complete"] = False
    with pytest.raises(SimulationError, match="complete"):
        simulate(Graph.from_dict(definition), data)


def test_incomplete_snapshot_requires_opt_in_and_is_marked_advisory():
    definition = Graph.from_dict(graph())
    data = snapshot()
    data["lists"][TARGET]["complete"] = False
    with pytest.raises(SimulationError, match="complete"):
        simulate(definition, data)
    result = simulate(definition, data, allow_incomplete=True)
    assert not result.snapshot_complete
    assert result.changes[0].new_value == 12
    with pytest.raises(SimulationError, match="boolean"):
        simulate(definition, data, allow_incomplete=1)


def test_sequential_assignments_see_working_state_and_skip_discards_them():
    value = graph()
    value["nodes"].insert(4, {"id": "second", "type": "assign", "alias": "source", "field_id": GOAL,
        "value": {"kind": "field", "alias": "source", "field_id": GOAL}})
    value["edges"][4]["to"] = "second"
    value["edges"].append({"from": "second", "port": "next", "to": "merge"})
    change = simulate(Graph.from_dict(value), snapshot()).changes[0]
    assert change.new_value == 12 and change.steps == ("set", "second")
    value["nodes"][-1]["type"] = "skip"
    assert not simulate(Graph.from_dict(value), snapshot()).changes


def test_conflicting_cross_source_proposals_fail_instead_of_last_wins():
    value = graph()
    value["nodes"][2]["condition"] = {"op": "exists", "alias": "mechanism"}
    value["nodes"][3].update(alias="mechanism", field_id=RELATED_GOAL,
        value={"kind": "field", "alias": "source", "field_id": GOAL})
    data = snapshot()
    data["lists"][TARGET]["fields"][RELATED_GOAL].update(writable=True, constraints_verified=True, required=False)
    data["lists"][SOURCE]["items"] = [
        {"ID": 1, "Mechanism": 10, "Goal": 11}, {"ID": 2, "Mechanism": 10, "Goal": 12}]
    with pytest.raises(SimulationError, match="Conflicting"):
        simulate(Graph.from_dict(value), data)


def test_three_proposals_and_six_diagnostic_branches():
    data = snapshot()
    data["lists"][SOURCE]["items"] = [
        {"ID": i, "Mechanism": 10, "Goal": None if i <= 3 else 11 if i <= 9 else 12}
        for i in range(1, 11)]
    result = simulate(Graph.from_dict(graph()), data)
    assert [c.item_id for c in result.changes] == [1, 2, 3]
    diagnostic = graph()
    diagnostic["nodes"][2]["condition"] = {"op": "ne", "left": {"kind": "field", "alias": "source", "field_id": GOAL},
        "right": {"kind": "field", "alias": "mechanism", "field_id": RELATED_GOAL}}
    diagnostic["nodes"][3]["type"] = "merge"
    for key in ("alias", "field_id", "value"):
        del diagnostic["nodes"][3][key]
    diagnostic["scope"] = {"type": "ids", "ids": list(range(4, 11))}
    result = simulate(Graph.from_dict(diagnostic), data)
    assert len([d for d in result.decisions if d.matched]) == 6
    assert not result.changes


@pytest.mark.parametrize("operator,expected", [("any", False), ("all", True)])
def test_empty_collection_quantifiers(operator, expected):
    value = graph()
    value["nodes"][1].update(direction="reverse", many=True, target_list_id=SOURCE, field_id=REL, **{"as": "children"})
    value["nodes"][2]["condition"] = {"op": operator, "alias": "children", "condition": {
        "op": "empty", "value": {"kind": "field", "alias": "item", "field_id": GOAL}}}
    value["nodes"][3]["type"] = "merge"
    for key in ("alias", "field_id", "value"):
        del value["nodes"][3][key]
    data = snapshot()
    data["lists"][SOURCE]["fields"][REL]["lookup_list_id"] = SOURCE
    data["lists"][SOURCE]["items"] = [{"ID": 1, "Mechanism": None, "Goal": None}]
    result = simulate(Graph.from_dict(value), data)
    assert result.decisions[0].matched is expected
    value["nodes"][2]["condition"] = {"op": "eq", "left": {"kind": "count", "alias": "children"}, "right": {"kind": "literal", "value": 0}}
    assert simulate(Graph.from_dict(value), data).decisions[0].matched


def test_type_mismatch_is_not_coerced_and_zero_is_not_empty():
    value = graph()
    value["nodes"][2]["condition"] = {"op": "eq", "left": {"kind": "field", "alias": "source", "field_id": GOAL},
        "right": {"kind": "literal", "value": "12"}}
    data = snapshot()
    data["lists"][SOURCE]["items"][0]["Goal"] = 12
    with pytest.raises(SimulationError, match="Invalid Lookup value"):
        simulate(Graph.from_dict(value), data)
    value["nodes"][2]["condition"] = {"op": "empty", "value": {"kind": "literal", "value": 0}}
    assert not simulate(Graph.from_dict(value), data).decisions[0].matched


def test_untaken_branch_is_preflighted_even_for_empty_scope():
    value = graph()
    value["scope"] = {"type": "ids", "ids": []}
    data = snapshot()
    data["lists"][SOURCE]["fields"][GOAL]["writable"] = False
    with pytest.raises(SimulationError, match="writable"):
        simulate(Graph.from_dict(value), data)
    data["lists"][SOURCE]["fields"][GOAL]["writable"] = True
    value["nodes"][3]["field_id"] = RELATED_GOAL
    with pytest.raises(SimulationError, match="list context"):
        simulate(Graph.from_dict(value), data)


def test_collection_reverse_any_and_all_and_missing_fields():
    value = graph()
    value["nodes"][1].update(direction="reverse", many=True, target_list_id=SOURCE, field_id=REL, **{"as": "children"})
    value["nodes"][2]["condition"] = {"op": "any", "alias": "children", "condition": {
        "op": "not_empty", "value": {"kind": "field", "alias": "item", "field_id": GOAL}}}
    value["nodes"][3]["type"] = "merge"
    for key in ("alias", "field_id", "value"):
        del value["nodes"][3][key]
    value["scope"] = {"type": "ids", "ids": [1]}
    data = snapshot()
    data["lists"][SOURCE]["fields"][REL]["lookup_list_id"] = SOURCE
    data["lists"][SOURCE]["items"] = [
        {"ID": 1, "Mechanism": None, "Goal": None},
        {"ID": 2, "Mechanism": 1, "Goal": 12},
        {"ID": 3, "Mechanism": 1, "Goal": None},
    ]
    assert simulate(Graph.from_dict(value), data).decisions[0].matched
    value["nodes"][2]["condition"]["op"] = "all"
    assert not simulate(Graph.from_dict(value), data).decisions[0].matched
    del data["lists"][SOURCE]["items"][1]["Mechanism"]
    with pytest.raises(SimulationError, match="absent"):
        simulate(Graph.from_dict(value), data)


def test_relation_traversal_uses_snapshot_not_new_assignments():
    value = graph()
    value["nodes"].insert(1, {"id": "change-relation", "type": "assign", "alias": "source", "field_id": REL,
        "value": {"kind": "literal", "value": 11}})
    value["edges"][0]["to"] = "change-relation"
    value["edges"].append({"from": "change-relation", "port": "next", "to": "read"})
    data = snapshot()
    data["lists"][SOURCE]["fields"][REL].update(writable=True, constraints_verified=True, required=False)
    value["scope"] = {"type": "ids", "ids": [1]}
    result = simulate(Graph.from_dict(value), data)
    assert {(c.field_id, c.new_value) for c in result.changes} == {(REL, 11), (GOAL, 12)}


def test_datetime_normalization_and_number_noop():
    value = graph()
    value["nodes"][2]["condition"] = {"op": "eq", "left": {"kind": "field", "alias": "source", "field_id": GOAL},
        "right": {"kind": "literal", "value": "2026-01-01T01:00:00+01:00"}}
    value["nodes"][3]["value"] = {"kind": "literal", "value": "2026-01-01T01:00:00+01:00"}
    value["scope"] = {"type": "ids", "ids": [1]}
    data = snapshot()
    data["lists"][SOURCE]["fields"][GOAL]["type"] = "DateTime"
    data["lists"][SOURCE]["items"][0]["Goal"] = "2026-01-01T00:00:00Z"
    result = simulate(Graph.from_dict(value), data)
    assert result.decisions[0].matched and not result.changes
    value["nodes"][2]["condition"]["right"]["value"] = "2026-01-01T01:00:00"
    with pytest.raises(SimulationError, match="timezone"):
        simulate(Graph.from_dict(value), data)
    data["lists"][SOURCE]["fields"][GOAL]["type"] = "Number"
    data["lists"][SOURCE]["items"][0]["Goal"] = 1
    value["nodes"][2]["condition"]["right"]["value"] = 1.0
    value["nodes"][3]["value"]["value"] = 1.0
    assert not simulate(Graph.from_dict(value), data).changes


def test_assignments_enforce_choice_required_and_number_constraints():
    value = graph()
    value["scope"] = {"type": "ids", "ids": [1]}
    value["nodes"][3]["value"] = {"kind": "literal", "value": "Approved"}
    data = snapshot()
    meta = data["lists"][SOURCE]["fields"][GOAL]
    meta.update(type="Choice", choices=["Approved", "Rejected"], required=True)
    assert simulate(Graph.from_dict(value), data).changes[0].new_value == "Approved"
    value["nodes"][3]["value"]["value"] = "Other"
    with pytest.raises(SimulationError, match="Choice"):
        simulate(Graph.from_dict(value), data)
    value["nodes"][3]["value"]["value"] = None
    with pytest.raises(SimulationError, match="Required"):
        simulate(Graph.from_dict(value), data)
    meta.update(type="Number", minimum=0, maximum=10, required=False)
    value["nodes"][3]["value"]["value"] = 11
    with pytest.raises(SimulationError, match="range"):
        simulate(Graph.from_dict(value), data)
    value["nodes"][3]["value"]["value"] = 0
    assert simulate(Graph.from_dict(value), data).changes[0].new_value == 0


def test_forward_multilookup_requires_quantifier_and_valid_ids():
    value = graph()
    value["nodes"][1].update(many=True, **{"as": "mechanisms"})
    value["nodes"][2]["condition"] = {"op": "any", "alias": "mechanisms", "condition": {
        "op": "eq", "left": {"kind": "field", "alias": "item", "field_id": RELATED_GOAL},
        "right": {"kind": "literal", "value": 12}}}
    value["nodes"][3]["type"] = "merge"
    for key in ("alias", "field_id", "value"):
        del value["nodes"][3][key]
    data = snapshot()
    data["lists"][SOURCE]["fields"][REL]["type"] = "LookupMulti"
    data["lists"][SOURCE]["items"][0]["Mechanism"] = [11, 10]
    data["lists"][SOURCE]["items"][1]["Mechanism"] = []
    decisions = simulate(Graph.from_dict(value), data).decisions
    assert [d.matched for d in decisions] == [True, False]
    data["lists"][SOURCE]["items"][0]["Mechanism"] = [10, 10]
    with pytest.raises(SimulationError, match="Invalid LookupMulti"):
        simulate(Graph.from_dict(value), data)
    value["nodes"][1]["many"] = False
    with pytest.raises(SimulationError, match="cardinality"):
        simulate(Graph.from_dict(value), data)


def test_simulate_records_step_trace_only_when_enabled():
    data = snapshot()
    definition = Graph.from_dict(graph())

    plain = simulate(definition, data)
    assert plain.trace == ()

    traced = simulate(definition, data, record_trace=True)
    assert traced.changes == plain.changes
    assert traced.decisions == plain.decisions

    item1_steps = [s for s in traced.trace if s.source_id == 1]
    assert [s.node_id for s in item1_steps] == ["start", "read", "if", "set", "merge", "end"]
    assert [s.step_no for s in item1_steps] == [1, 2, 3, 4, 5, 6]
    assert item1_steps[1].outcome["bound_ids"] == [10]
    assert item1_steps[2].outcome == {"matched": True}
    assert item1_steps[2].next_port == "true"
    assert [v.value for v in item1_steps[2].values] == [True, None, 12]
    assert item1_steps[3].outcome["old"] is None
    assert item1_steps[3].outcome["new"] == 12
    assert item1_steps[3].outcome["changed"] is True

    item2_steps = [s for s in traced.trace if s.source_id == 2]
    assert [s.node_id for s in item2_steps] == ["start", "read", "if", "merge", "end"]
    assert item2_steps[2].outcome == {"matched": False}
    assert item2_steps[2].next_port == "false"
