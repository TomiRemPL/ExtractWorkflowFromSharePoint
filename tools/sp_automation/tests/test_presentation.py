import os
from collections import Counter
from pathlib import Path

import pytest

from tools.sp_automation.catalog import Catalog, FieldRecord, ListRecord
from tools.sp_automation.comparison import compare_paths, comparison_paths
from tools.sp_automation.presentation import load_relations_snapshot


def test_snapshot_displays_relation_stats_and_sample_items(monkeypatch) -> None:
    source_id = "435dadf3-ab5d-4d56-a38e-f7bb8e837c53"
    target_id = "460a09d4-cece-45d6-ac46-05ea92255cc0"
    source = ListRecord(
        id=source_id, title="Kontrole",
        fields={"Mechanizm": FieldRecord("Mechanizm", "Mechanizm", "Lookup",
                                         entity_property_name="Mechanizm", lookup_list=target_id,
                                         lookup_field="Title")},
        rows=[{"Id": 1, "Title": "Kontrola", "MechanizmId": 2},
              {"Id": 3, "Title": "Druga", "MechanizmId": None}],
    )
    target = ListRecord(
        id=target_id, title="Mechanizmy",
        fields={"Title": FieldRecord("Title", "Tytuł", "Text", entity_property_name="Title")},
        rows=[{"Id": 2, "Title": "Mechanizm A"}],
    )
    monkeypatch.setattr("tools.sp_automation.presentation.load_catalog", lambda _path: Catalog(
        lists={source_id: source, target_id: target}, timestamp="2026-01-01",
    ))
    snapshot = load_relations_snapshot(Path("unused"))
    assert len(snapshot.relations) == 1
    details = snapshot.relations[0].details
    assert "wypełnione: 1; puste: 1" in details
    assert "#1 Kontrola → #2 Mechanizm A" in details
    assert "offline" in snapshot.summary.lower()


@pytest.mark.skipif(os.environ.get("CHECK_SP_005") != "1", reason="local snapshot verification is opt-in")
def test_optional_real_005_presentation():
    root = Path("DaneZeSkryptu_005")
    if not (root / "extraction_manifest.json").is_file():
        pytest.skip("local export 005 unavailable")
    snapshot = load_relations_snapshot(root)
    selected = {item.key for item in snapshot.lists if item.priority}
    edges = [edge for edge in snapshot.relations if edge.source in selected and edge.target in selected]
    assert len(selected) == 6
    assert len(edges) == 7


@pytest.mark.skipif(os.environ.get("CHECK_SP_005") != "1", reason="local snapshot verification is opt-in")
def test_optional_real_005_compares_control_goal_via_mechanism():
    root = Path("DaneZeSkryptu_005")
    if not (root / "extraction_manifest.json").is_file():
        pytest.skip("local export 005 unavailable")
    catalog = load_relations_snapshot(root).catalog
    assert catalog is not None
    selected = {
        "435dadf3-ab5d-4d56-a38e-f7bb8e837c53",
        "460a09d4-cece-45d6-ac46-05ea92255cc0",
        "9de40d46-5804-43c1-a74c-f3ddd4327b73",
    }
    paths = [path for path in comparison_paths(catalog, selected)
             if path.direct.field.internal_name == "Cel_x0020_SKW"
             and path.first.field.internal_name == "Mechanizm_x0020_kontrolny"]
    assert len(paths) == 1
    counts = Counter(row.status for row in compare_paths(catalog, paths[0]))
    assert counts["direct_empty"] == 3
    assert counts["different"] == 6
