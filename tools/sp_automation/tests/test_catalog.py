"""Synthetic, offline catalog and lookup relation tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from tools.sp_automation import CatalogError, build_relations, load_catalog
from tools.sp_automation.comparison import ComparisonError, compare_paths, comparison_paths


IDS = [f"00000000-0000-0000-0000-{i:012d}" for i in range(1, 8)]


@pytest.fixture
def snapshot(tmp_path):
    return tmp_path


def write(root, name, data):
    (root / name).write_text(json.dumps(data), encoding="utf-8")


def make_list(root, index, fields=(), rows=(), *, views=()):
    name = f"list{index}"
    write(root, f"10_lista_{name}.json", {
        "lista": {"Id": IDS[index], "Title": name, "ItemCount": len(rows) if rows is not None else 0},
        "kolumny": list(fields), "widoki": list(views),
    })
    if rows is not None:
        write(root, f"20_dane_{name}.json", list(rows))
    return {"id": IDS[index], "title": name, "safe_title": name}


def lookup(name, target, *, field_id=None, field_ref=None, kind="Lookup") -> dict[str, Any]:
    return {
        "Id": field_id or str(uuid4()), "InternalName": name,
        "Title": name, "TypeAsString": kind, "LookupList": target,
        "SchemaXml": f'<Field Type="{kind}"' + (f' FieldRef="{field_ref}"' if field_ref else "") + "/>",
    }


def manifest(root, entries, include_data=True):
    write(root, "extraction_manifest.json", {
        "site_url": "https://example.invalid/site", "lists": entries,
        "options": {"include_data": include_data},
    })


def test_seven_relations_and_projected_user_fields(snapshot):
    edges = [(3, 0), (3, 2), (3, 1), (3, 4), (2, 0), (2, 1), (1, 5)]
    fields = [[] for _ in range(6)]
    for i, (src, dst) in enumerate(edges):
        fields[src].append(lookup(f"relation{i}", IDS[dst]))
    parent_id = fields[3][0]["Id"]
    fields[3].extend([
        lookup("projected", IDS[0], field_ref=parent_id),
        lookup("user", IDS[6], kind="User"),
    ])
    entries = []
    for i in range(6):
        row = {"Id": 1}
        row.update({f["InternalName"] + "Id": 1 for f in fields[i]})
        entries.append(make_list(snapshot, i, fields[i], [row]))
    manifest(snapshot, entries)
    catalog = load_catalog(snapshot)
    relations = build_relations(catalog)
    assert len(relations) == 7
    assert {(r.source_list_id, r.target_list_id) for r in relations} == {
        (IDS[src], IDS[dst]) for src, dst in edges
    }
    assert all(r.stats.dangling == 0 for r in relations)
    assert catalog.lists[IDS[3]].fields["projected"].field_ref == parent_id
    assert all(r.stats.populated == 1 for r in relations)


def test_compare_direct_and_two_hop_paths_without_treating_missing_as_empty(snapshot):
    direct = lookup("Direct", IDS[2])
    first = lookup("Via", IDS[1])
    second = lookup("Indirect", IDS[2])
    entries = [
        make_list(snapshot, 0, [direct, first], [
            {"Id": 1, "DirectId": None, "ViaId": 10},
            {"Id": 2, "DirectId": 20, "ViaId": 11},
            {"Id": 3, "DirectId": 21, "ViaId": 10},
            {"Id": 4, "DirectId": None, "ViaId": None},
            {"Id": 5, "ViaId": 10},
            {"Id": 6, "DirectId": None, "ViaId": 999},
            {"Id": 7, "DirectId": 999, "ViaId": 10},
            {"Id": 8, "DirectId": None, "ViaId": 12},
            {"Id": 9, "DirectId": 20, "ViaId": 12},
            {"Id": 10, "DirectId": 20, "ViaId": 10},
        ]),
        make_list(snapshot, 1, [second], [
            {"Id": 10, "IndirectId": 20}, {"Id": 11, "IndirectId": 21},
            {"Id": 12, "IndirectId": None},
        ]),
        make_list(snapshot, 2, rows=[{"Id": 20}, {"Id": 21}]),
    ]
    manifest(snapshot, entries)
    catalog = load_catalog(snapshot)
    assert not comparison_paths(catalog, set(IDS[:2]))
    paths = comparison_paths(catalog, set(IDS[:3]))
    assert len(paths) == 1
    result = compare_paths(catalog, paths[0])
    assert [(r.source_id, r.status) for r in result] == [
        (1, "direct_empty"), (2, "different"), (3, "different"),
        (4, "no_intermediate"), (5, "unknown"), (6, "missing_intermediate"),
        (7, "missing_target"), (8, "both_empty"), (9, "indirect_empty"),
        (10, "equal"),
    ]
    assert result[0].indirect_id == 20
    catalog.lists[IDS[1]].rows = None
    with pytest.raises(ComparisonError, match="Brak danych"):
        compare_paths(catalog, paths[0])


def test_comparison_rejects_duplicate_or_ambiguous_item_ids(snapshot):
    entries = [
        make_list(snapshot, 0, [lookup("Direct", IDS[2]), lookup("Via", IDS[1])],
                  [{"Id": 1, "ID": 2, "DirectId": 20, "ViaId": 10}]),
        make_list(snapshot, 1, [lookup("Indirect", IDS[2])], [{"Id": 10, "IndirectId": 20}]),
        make_list(snapshot, 2, rows=[{"Id": 20}]),
    ]
    manifest(snapshot, entries)
    catalog = load_catalog(snapshot)
    path = comparison_paths(catalog, set(IDS[:3]))[0]
    with pytest.raises(ComparisonError, match="ID"):
        compare_paths(catalog, path)
    catalog.lists[IDS[0]].rows = [{"Id": 1}, {"Id": 1}]
    with pytest.raises(ComparisonError, match="ID"):
        compare_paths(catalog, path)


def test_comparison_reports_conflicting_rest_ids_as_unknown(snapshot):
    direct = lookup("Direct", IDS[2])
    direct["EntityPropertyName"] = "RestDirect"
    entries = [
        make_list(snapshot, 0, [direct, lookup("Via", IDS[1])], [
            {"Id": 1, "RestDirectId": 20, "DirectId": 21, "ViaId": 10},
            {"Id": 2, "RestDirectId": False, "ViaId": 10},
        ]),
        make_list(snapshot, 1, [lookup("Indirect", IDS[2])], [{"Id": 10, "IndirectId": 20}]),
        make_list(snapshot, 2, rows=[{"Id": 20}, {"Id": 21}]),
    ]
    manifest(snapshot, entries)
    catalog = load_catalog(snapshot)
    path = comparison_paths(catalog, set(IDS[:3]))[0]
    assert [row.status for row in compare_paths(catalog, path)] == ["unknown", "unknown"]


def test_missing_manifest_is_explicit(snapshot):
    with pytest.raises(CatalogError, match="manifest"):
        load_catalog(snapshot)
    write(snapshot, "extraction_manifest.json", {"lists": {}})
    with pytest.raises(CatalogError, match="manifest"):
        load_catalog(snapshot)


def test_manifest_identity_missing_and_invalid_files(snapshot):
    a = make_list(snapshot, 0, rows=[{"Id": 1}])
    b = make_list(snapshot, 1, rows=[])
    c = make_list(snapshot, 2, rows=[])
    d = make_list(snapshot, 3, rows=[])
    # A data filename cannot identify a list if its definition belongs elsewhere.
    write(snapshot, "10_lista_list0.json", {"lista": {"Id": IDS[1]}, "kolumny": []})
    (snapshot / "10_lista_list1.json").unlink()
    (snapshot / "20_dane_list2.json").unlink()
    (snapshot / "20_dane_list3.json").write_text("{secret", encoding="utf-8")
    manifest(snapshot, [a, b, c, d])
    catalog = load_catalog(snapshot)
    assert catalog.lists[IDS[0]].definition_status == "identity_error"
    assert catalog.lists[IDS[0]].rows is None
    assert catalog.lists[IDS[1]].definition_status == "missing"
    assert catalog.lists[IDS[1]].data_status == "identity_error"
    assert catalog.lists[IDS[2]].data_status == "missing"
    assert catalog.lists[IDS[3]].data_status == "error"
    assert "secret" not in repr(catalog)
    assert {i.code for i in catalog.issues} >= {
        "identity_mismatch", "missing_definition", "missing_data", "invalid_data"
    }


def test_collision_traversal_duplicate_guid_and_unexported(snapshot):
    a = make_list(snapshot, 0, rows=[{"Id": 1}])
    b = make_list(snapshot, 1, rows=[{"Id": 2}])
    c = make_list(snapshot, 2, rows=[{"Id": 3}])
    unsafe = {"id": IDS[3], "title": "unsafe", "safe_title": "..\\outside"}
    collision = {"id": IDS[4], "title": "collision", "safe_title": "LIST0"}
    duplicate = {"id": IDS[1].upper(), "title": "duplicate", "safe_title": "other"}
    manifest(snapshot, [a, b, c, unsafe, collision, duplicate], include_data=False)
    catalog = load_catalog(snapshot)
    assert IDS[1] not in catalog.lists
    assert catalog.lists[IDS[0]].definition_status == "identity_error"
    assert catalog.lists[IDS[4]].definition_status == "identity_error"
    assert catalog.lists[IDS[3]].data_status == "identity_error"
    assert catalog.lists[IDS[2]].data_status == "not_exported"
    assert catalog.lists[IDS[2]].rows is None


def test_lookup_stats_unknown_missing_empty_and_dangling(snapshot):
    col = lookup("Link", IDS[1])
    col["EntityPropertyName"] = "RestLink"
    rows = [
        {"Id": 1, "RestLinkId": 10},
        {"Id": 2, "RestLinkId": 11},
        {"Id": 3, "RestLinkId": None},
        {"Id": 4},
        {"Id": 5, "RestLinkId": False},
        {"Id": 6, "RestLinkId": 10, "LinkId": 11},
        {"Id": 7, "RestLinkId": 0},
    ]
    entries = [make_list(snapshot, 0, [col], rows), make_list(snapshot, 1, rows=[{"Id": 10}])]
    manifest(snapshot, entries)
    catalog = load_catalog(snapshot)
    relation = build_relations(catalog)[0]
    assert (relation.stats.total, relation.stats.populated, relation.stats.empty,
            relation.stats.missing, relation.stats.unknown, relation.stats.dangling) == (7, 2, 1, 1, 3, 1)
    assert relation.reverse_index == {10: (1,), 11: (2,)}
    assert "RestLinkId" not in repr(catalog)


def test_multi_external_missing_and_invalid_target_ids(snapshot):
    fields = [lookup("Multi", IDS[1], kind="LookupMulti"), lookup("Outside", IDS[6])]
    entries = [
        make_list(snapshot, 0, fields, [
            {"Id": 1, "MultiId": {"results": [1, 2]}, "OutsideId": 33},
            {"Id": 2, "MultiId": {"results": []}, "OutsideId": None},
            {"Id": 3, "MultiId": [1, "bad"]},
        ]),
        make_list(snapshot, 1, rows=[{"Id": 1}]),
    ]
    manifest(snapshot, entries)
    catalog = load_catalog(snapshot)
    multi, external = build_relations(catalog)
    assert (multi.stats.populated, multi.stats.empty, multi.stats.unknown, multi.stats.dangling) == (1, 1, 1, 1)
    assert multi.reverse_index == {1: (1,), 2: (1,)}
    assert external.target_status == "external"
    assert external.stats.dangling is None
    catalog.lists[IDS[1]].rows = None
    catalog.lists[IDS[1]].data_status = "missing"
    multi = build_relations(catalog)[0]
    assert multi.target_status == "missing" and multi.stats.dangling is None
    catalog.lists[IDS[1]].rows = [{"Id": 1}, {"Id": 1}]
    multi = build_relations(catalog)[0]
    assert multi.target_status == "invalid_item_ids" and multi.stats.dangling is None
    catalog.lists[IDS[1]].rows = [{"Id": 1}, {}]
    multi = build_relations(catalog)[0]
    assert multi.target_status == "invalid_item_ids" and multi.stats.dangling is None
    catalog.lists[IDS[0]].rows = None
    multi = build_relations(catalog)[0]
    assert multi.stats.total is None and multi.stats.missing is None and multi.stats.dangling is None


def test_projection_parent_errors_and_schema_errors_do_not_create_edges(snapshot):
    parent = lookup("parent", IDS[1])
    fields = [
        lookup("missing_parent", IDS[1], field_ref=str(uuid4())),
        lookup("bad_schema", IDS[1]),
        lookup("broken_reference", "not-a-guid"),
        lookup("people", IDS[1], kind="UserMulti"),
        parent,
        lookup("wrong_target", IDS[2], field_ref=parent["Id"]),
    ]
    fields[1]["SchemaXml"] = "<Field"
    manifest(snapshot, [make_list(snapshot, 0, fields, []), make_list(snapshot, 1, rows=[])])
    catalog = load_catalog(snapshot)
    assert {i.code for i in catalog.issues} >= {
        "missing_lookup_parent", "invalid_field_schema", "lookup_parent_mismatch"
    }
    relations = build_relations(catalog)
    assert len(relations) == 2 and relations[0].target_status == "invalid_reference"


@pytest.mark.parametrize("field_ref", ["ID", "DocId"])
def test_system_field_ref_is_main_lookup_and_valid_projection_parent(snapshot, field_ref):
    parent = lookup("parent", IDS[1], field_ref=field_ref)
    projection = lookup("projection", IDS[1], field_ref=parent["Id"])
    manifest(snapshot, [
        make_list(snapshot, 0, [parent, projection], [{"Id": 1, "parentId": 1}]),
        make_list(snapshot, 1, rows=[{"Id": 1}]),
    ])
    catalog = load_catalog(snapshot)
    relations = build_relations(catalog)
    assert [r.field.internal_name for r in relations] == ["parent"]
    assert relations[0].stats.populated == 1
    assert relations[0].stats.dangling == 0
    assert not any(i.code == "missing_lookup_parent" for i in catalog.issues)
    assert any(i.code == "system_field_ref" and i.severity == "warning" for i in catalog.issues)


def test_system_field_refs_are_grouped_per_list(snapshot):
    fields = [lookup("FileRef", IDS[1], field_ref="ID"), lookup("FileDirRef", IDS[1], field_ref="ID")]
    manifest(snapshot, [make_list(snapshot, 0, fields, []), make_list(snapshot, 1, rows=[])])
    issues = [i for i in load_catalog(snapshot).issues if i.code == "system_field_ref"]
    assert len(issues) == 1
    assert issues[0].field_name == "FileRef, FileDirRef"


def test_self_lookup_and_xml_only_multivalue_type(snapshot):
    col = {
        "InternalName": "SelfRef",
        "SchemaXml": '<Field Type="Lookup" Mult="TRUE" List="Self" />',
    }
    manifest(snapshot, [make_list(snapshot, 0, [col], [
        {"Id": 1, "SelfRefId": {"results": [2]}}, {"Id": 2, "SelfRefId": []}
    ])])
    relation = build_relations(load_catalog(snapshot))[0]
    assert relation.kind == "lookupmulti"
    assert relation.target_list_id == IDS[0]
    assert (relation.stats.populated, relation.stats.empty, relation.stats.dangling) == (1, 1, 0)


def test_ambiguous_fields_and_options_do_not_guess(snapshot):
    a = make_list(snapshot, 0, [lookup("Link", IDS[1]), lookup("LINK", IDS[2])], [{"Id": 1}])
    manifest(snapshot, [a])
    catalog = load_catalog(snapshot)
    assert "duplicate_field" in {i.code for i in catalog.issues}
    assert not build_relations(catalog)
    write(snapshot, "extraction_manifest.json", {"lists": [a], "options": {"include_data": "false"}})
    catalog = load_catalog(snapshot)
    assert catalog.lists[IDS[0]].data_status == "error"
    assert catalog.lists[IDS[0]].rows is None
    assert "invalid_manifest_options" in {i.code for i in catalog.issues}


def test_views_and_fingerprint_are_schema_based(snapshot):
    col = lookup("Link", IDS[1])
    view = {"Id": IDS[6], "Title": "Selected", "ServerRelativeUrl": "/a.aspx",
            "ViewQuery": "<Where/>", "KolumnyWidoku": ["Title", "Link"]}
    entry = make_list(snapshot, 0, [col], [{"Id": 1, "secret": "sensitive"}], views=[view])
    manifest(snapshot, [entry])
    catalog = load_catalog(snapshot)
    rec = catalog.lists[IDS[0]]
    assert rec.views_status == "unconfirmed"
    assert rec.views[0].view_query == "<Where/>"
    assert rec.views[0].fields == ("Title", "Link")
    assert "sensitive" not in repr(rec)
    old = rec.schema_fingerprint
    write(snapshot, "20_dane_list0.json", [{"Id": 2}])
    assert load_catalog(snapshot).lists[IDS[0]].schema_fingerprint == old
    col["Required"] = True
    make_list(snapshot, 0, [col], [{"Id": 1}], views=[view])
    assert load_catalog(snapshot).lists[IDS[0]].schema_fingerprint != old


@pytest.mark.skipif(os.environ.get("CHECK_SP_005") != "1", reason="local snapshot verification is opt-in")
def test_optional_real_005_aggregate_only():
    # This never writes the snapshot, logs rows, or contacts SharePoint.
    root = Path(os.environ.get("SP_EXPORT_DIR", "DaneZeSkryptu_005"))
    if not (root / "extraction_manifest.json").is_file():
        pytest.skip("local export 005 unavailable")
    expected = {
        "d5670805-4592-4ef6-9b55-54252ac07e12": 53,
        "9de40d46-5804-43c1-a74c-f3ddd4327b73": 29,
        "460a09d4-cece-45d6-ac46-05ea92255cc0": 42,
        "435dadf3-ab5d-4d56-a38e-f7bb8e837c53": 99,
        "fa878eea-2434-4dec-b5df-52ce112ce654": 47,
        "01ed4d26-26f1-4f67-9ade-9994464b14bb": 113,
    }
    catalog = load_catalog(root)
    assert {key: catalog.lists[key].row_count for key in expected} == expected
    edges = [r for r in build_relations(catalog)
             if r.source_list_id in expected and r.target_list_id in expected]
    assert len(edges) == 7
    assert all(r.stats.dangling == 0 for r in edges)
    processes = catalog.lists["d5670805-4592-4ef6-9b55-54252ac07e12"]
    domains = catalog.lists["fa878eea-2434-4dec-b5df-52ce112ce654"]
    assert processes.workflow_associations is not None and processes.event_receivers is not None
    assert domains.workflow_associations is not None and domains.event_receivers is not None
    assert sum(w.get("AutoStartChange") is True for w in processes.workflow_associations) == 3
    assert len(processes.event_receivers) == 5
    assert sum(w.get("AutoStartChange") is True for w in domains.workflow_associations) == 1
    assert len(domains.event_receivers) == 5
