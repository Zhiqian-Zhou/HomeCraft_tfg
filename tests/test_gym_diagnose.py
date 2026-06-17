"""Tests for tools.gym.diagnose — weak-metric ranking + aggregation."""
from __future__ import annotations

from tools.gym.diagnose import (
    rank_weak_metrics, aggregate_across_builds, top_global_weak,
    METRIC_TO_CATEGORIES, DEFERRED_METRICS,
)


def _make_report(physical: dict, alexander: dict) -> dict:
    """Build a minimal evaluation_report-like dict for testing."""
    return {
        "physical": physical,
        "alexander": alexander,
        "composite": {
            "physical_total": sum(m["score"] for m in physical.values()
                                    if m.get("score") is not None) / max(
                1, len([m for m in physical.values()
                         if m.get("score") is not None])),
            "alexander_total": sum(m["score"] for m in alexander.values()
                                     if m.get("score") is not None) / max(
                1, len([m for m in alexander.values()
                         if m.get("score") is not None])),
            "overall": 0.5,
            "weight_table": {
                "physical": {k: 1.0 / len(physical) for k in physical},
                "alexander": {k: 1.0 / len(alexander) for k in alexander},
            },
        },
    }


def test_rank_skips_high_scores():
    rep = _make_report(
        physical={"voxel_connectivity": {"score": 0.95, "notes": "good"}},
        alexander={"intimacy_gradient": {"score": 0.3, "notes": "weak"}},
    )
    wp = rank_weak_metrics(rep, k=3)
    assert all(w.metric_id != "voxel_connectivity" for w in wp)
    assert any(w.metric_id == "intimacy_gradient" for w in wp)


def test_rank_skips_none_scores():
    rep = _make_report(
        physical={"door_functionality": {"score": None, "notes": "no doors"}},
        alexander={"intimacy_gradient": {"score": 0.4}},
    )
    wp = rank_weak_metrics(rep, k=3)
    assert all(w.metric_id != "door_functionality" for w in wp)


def test_rank_skips_deferred():
    rep = _make_report(
        physical={"structural_integrity": {"score": 0.1},
                  "voxel_connectivity": {"score": 0.4}},
        alexander={},
    )
    wp = rank_weak_metrics(rep, k=3)
    ids = [w.metric_id for w in wp]
    assert "structural_integrity" not in ids
    assert "voxel_connectivity" in ids


def test_rank_returns_top_k_by_severity():
    """severity = family_weight * effective_weight * deficit; orders correctly."""
    rep = _make_report(
        physical={
            "voxel_connectivity": {"score": 0.1},   # 0.55 * 0.5 * 0.9 = 0.2475
            "vertical_clearance": {"score": 0.7},   # 0.55 * 0.5 * 0.3 = 0.0825
        },
        alexander={
            "intimacy_gradient": {"score": 0.2},    # 0.45 * 1.0 * 0.8 = 0.36
        },
    )
    wp = rank_weak_metrics(rep, k=3)
    ids = [w.metric_id for w in wp]
    # Top severities: intimacy_gradient (0.36) > voxel_connectivity (0.2475)
    # > vertical_clearance (0.0825)
    assert ids[0] == "intimacy_gradient"
    assert ids[1] == "voxel_connectivity"
    assert ids[2] == "vertical_clearance"


def test_weak_point_has_affected_categories():
    rep = _make_report(
        physical={"voxel_connectivity": {"score": 0.1}},
        alexander={},
    )
    wp = rank_weak_metrics(rep, k=1)
    assert wp[0].affected_skill_categories == \
        METRIC_TO_CATEGORIES["voxel_connectivity"]


def test_aggregate_counts_weak_builds_per_metric():
    reports = {
        "a": _make_report(
            physical={"voxel_connectivity": {"score": 0.2}},
            alexander={}),
        "b": _make_report(
            physical={"voxel_connectivity": {"score": 0.3}},
            alexander={}),
        "c": _make_report(
            physical={"voxel_connectivity": {"score": 0.9}},
            alexander={}),
    }
    agg = aggregate_across_builds(reports, weak_threshold=0.4)
    g = agg["voxel_connectivity"]
    assert g.affected_count == 2  # a and b, not c
    assert "a" in g.affected_slots and "b" in g.affected_slots
    assert "c" not in g.affected_slots


def test_top_global_weak_min_affected():
    reports = {
        "a": _make_report(physical={"vc": {"score": 0.1}}, alexander={}),
        "b": _make_report(physical={"vc": {"score": 0.95}}, alexander={}),
    }
    agg = aggregate_across_builds(reports, weak_threshold=0.4)
    # only "a" is weak — fails min_affected=2
    assert top_global_weak(agg, k=3, min_affected=2) == []
    # min_affected=1 → returns it
    out = top_global_weak(agg, k=3, min_affected=1)
    assert len(out) == 1 and out[0].metric_id == "vc"


def test_deferred_metrics_in_global_agg():
    rep = {"a": _make_report(
        physical={"block_legitimacy": {"score": 0.0}},
        alexander={})}
    agg = aggregate_across_builds(rep)
    assert "block_legitimacy" not in agg


def test_metric_to_category_covers_all_real_metrics():
    """Every non-deferred metric in the evaluator has a mapping."""
    KNOWN_METRICS = {
        "voxel_connectivity", "vertical_clearance", "door_functionality",
        "light_coverage", "material_consistency", "volume_density",
        "light_on_two_sides", "intimacy_gradient", "common_areas_at_heart",
        "sheltering_roof", "building_edge", "window_place",
        "entrance_transition", "main_entrance", "farmhouse_kitchen",
        "roof_layout",
    }
    for m in KNOWN_METRICS:
        assert m in METRIC_TO_CATEGORIES, f"Missing mapping for {m}"
        assert METRIC_TO_CATEGORIES[m], f"Empty mapping for {m}"
