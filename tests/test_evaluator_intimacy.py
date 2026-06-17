"""Tests for _intimacy_gradient (APL #127, Spearman ρ over privacy/depth).

Covers the 4 refined-plan fixes:
  - cascade entry detection (outside-door → entry-function → boundary → max-deg)
  - graph from master_plan.connectors.doors (fallback to AABB face-share)
  - score=null when >50% of functions are unknown (no spurious 0.5)
  - Spearman with average-rank ties (scipy.stats.rankdata)

Schema note: door connectors use ``between: [room_a_id, room_b_id]``.
"""
from __future__ import annotations

import pytest

from pipeline.agents.evaluator import _intimacy_gradient


def _doc(spaces, *, bbox_size=(20, 8, 20)):
    """Wrap spaces into a minimal doc with bot_decomposition + bounding_box."""
    return {
        "bot_decomposition": {
            "building": {"storeys": [{"id": "p0", "spaces": spaces}]},
        },
        "bounding_box": {"origin": [0, 0, 0], "size": list(bbox_size)},
    }


def _door(a, b):
    return {"id": f"d-{a}-{b}", "between": [a, b],
            "at": [0, 0, 0], "facing": "n"}


def _mp(doors):
    return {"connectors": {"doors": doors, "windows": [], "staircases": []}}


# ---------------------------------------------------------------------------
# T1 — Linear ideal: entry_hall → living → kitchen → bedroom; ρ ≈ +1
# ---------------------------------------------------------------------------
def test_t1_linear_ideal_high_score():
    spaces = [
        {"id": "hall",    "function": "entry_hall",  "aabb": [0, 0, 0,  5, 4,  5]},
        {"id": "living",  "function": "living_room", "aabb": [5, 0, 0, 10, 4,  5]},
        {"id": "kitchen", "function": "kitchen",     "aabb": [5, 0, 5, 10, 4, 10]},
        {"id": "bedroom", "function": "bedroom",     "aabb": [0, 0, 5,  5, 4, 10]},
    ]
    doors = [
        _door("hall", "living"),
        _door("living", "kitchen"),
        _door("kitchen", "bedroom"),
    ]
    result = _intimacy_gradient(_doc(spaces), _mp(doors))
    assert result["score"] is not None
    assert result["score"] >= 0.95, result
    assert "graph_source=doors" in result["notes"]


# ---------------------------------------------------------------------------
# T2 — Anti-pattern: bedroom adjacent to entry; high-priv close, low-priv far.
# With the entry anchored at (priv-rank=1, dist-rank=1) a strict ρ=−1 is
# mathematically infeasible, but the score must be clearly worse than the
# linear-ideal score from T1.
# ---------------------------------------------------------------------------
def test_t2_anti_pattern_lower_than_ideal():
    ideal_spaces = [
        {"id": "hall",    "function": "entry_hall",  "aabb": [0, 0, 0,  5, 4,  5]},
        {"id": "living",  "function": "living_room", "aabb": [5, 0, 0, 10, 4,  5]},
        {"id": "kitchen", "function": "kitchen",     "aabb": [5, 0, 5, 10, 4, 10]},
        {"id": "bedroom", "function": "bedroom",     "aabb": [0, 0, 5,  5, 4, 10]},
    ]
    ideal_doors = [
        _door("hall", "living"),
        _door("living", "kitchen"),
        _door("kitchen", "bedroom"),
    ]
    ideal = _intimacy_gradient(_doc(ideal_spaces), _mp(ideal_doors))

    anti_spaces = [
        {"id": "hall",    "function": "entry_hall",  "aabb": [0, 0, 0,  5, 4,  5]},
        {"id": "bedroom", "function": "bedroom",     "aabb": [5, 0, 0, 10, 4,  5]},
        {"id": "kitchen", "function": "kitchen",     "aabb": [5, 0, 5, 10, 4, 10]},
        {"id": "living",  "function": "living_room", "aabb": [0, 0, 5,  5, 4, 10]},
    ]
    anti_doors = [
        _door("hall", "bedroom"),
        _door("bedroom", "kitchen"),
        _door("kitchen", "living"),
    ]
    anti = _intimacy_gradient(_doc(anti_spaces), _mp(anti_doors))
    assert anti["score"] is not None and ideal["score"] is not None
    assert anti["score"] < ideal["score"] - 0.2, (anti, ideal)
    # also reflects the anti-pattern via negative-ish spearman component:
    assert anti["spearman"] < ideal["spearman"], (anti, ideal)


# ---------------------------------------------------------------------------
# T3 — One room → score=None
# ---------------------------------------------------------------------------
def test_t3_single_room_returns_none():
    spaces = [{"id": "hall", "function": "entry_hall",
               "aabb": [0, 0, 0, 5, 4, 5]}]
    result = _intimacy_gradient(_doc(spaces), None)
    assert result["score"] is None
    assert result["notes"] == "<2 rooms"


# ---------------------------------------------------------------------------
# T4 — Majority unknown functions → score=None (no spurious 0.5)
# ---------------------------------------------------------------------------
def test_t4_unknowns_dominate_returns_none():
    spaces = [
        {"id": "r1", "function": "roof-terrace", "aabb": [0, 0, 0, 5, 4, 5]},
        {"id": "r2", "function": "void",          "aabb": [5, 0, 0,10, 4, 5]},
        {"id": "r3", "function": "garage",        "aabb": [0, 0, 5, 5, 4,10]},
        {"id": "r4", "function": "balcony",       "aabb": [5, 0, 5,10, 4,10]},
        {"id": "r5", "function": "kitchen",       "aabb": [0, 0,10, 5, 4,15]},
    ]
    result = _intimacy_gradient(_doc(spaces), None)
    assert result["score"] is None
    assert "unknown functions dominate" in result["notes"]


# ---------------------------------------------------------------------------
# T5 — No doors: AABB face-share fallback; linear room chain
# ---------------------------------------------------------------------------
def test_t5_geometry_fallback_linear():
    spaces = [
        {"id": "hall",    "function": "entry_hall",  "aabb": [0, 0, 0, 5, 4,  5]},
        {"id": "living",  "function": "living_room", "aabb": [5, 0, 0,10, 4,  5]},
        {"id": "kitchen", "function": "kitchen",     "aabb": [10,0, 0,15, 4,  5]},
        {"id": "bedroom", "function": "bedroom",     "aabb": [15,0, 0,20, 4,  5]},
    ]
    # No master_plan / sin puertas → grafo por adyacencia geométrica
    result = _intimacy_gradient(_doc(spaces), None)
    assert result["score"] is not None
    assert "graph_source=geometry" in result["notes"]


# ---------------------------------------------------------------------------
# T6 — Multi-storey door (staircase-style); privacy grows with floor
# ---------------------------------------------------------------------------
def test_t6_multi_storey_connected_via_door():
    storeys = [
        {"id": "p0", "spaces": [
            {"id": "hall-p0",    "function": "entry_hall", "aabb": [0,0,0, 5, 4, 5]},
            {"id": "living-p0",  "function": "living_room","aabb": [5,0,0,10, 4, 5]},
        ]},
        {"id": "p1", "spaces": [
            {"id": "hall-p1",    "function": "hallway",    "aabb": [0,4,0, 5, 8, 5]},
            {"id": "bedroom-p1", "function": "bedroom",    "aabb": [5,4,0,10, 8, 5]},
        ]},
    ]
    doc = {
        "bot_decomposition": {"building": {"storeys": storeys}},
        "bounding_box": {"origin": [0, 0, 0], "size": [10, 8, 5]},
    }
    doors = [
        _door("hall-p0", "living-p0"),
        _door("hall-p0", "hall-p1"),     # staircase-style cross-floor
        _door("hall-p1", "bedroom-p1"),
    ]
    result = _intimacy_gradient(doc, _mp(doors))
    assert result["score"] is not None
    assert result["score"] >= 0.5, result


# ---------------------------------------------------------------------------
# T7 — scipy.stats.rankdata average-rank: ρ matches reference scipy.spearmanr
# on a fixture with genuine ties (priv=1 across multiple rooms, dist ties too).
# ---------------------------------------------------------------------------
def test_t7_spearman_matches_scipy_reference():
    spaces = [
        {"id": "hall",    "function": "entry_hall",  "aabb": [0, 0, 0, 5, 4, 5]},
        {"id": "living",  "function": "living_room", "aabb": [5, 0, 0,10, 4, 5]},
        {"id": "kitchen", "function": "kitchen",     "aabb": [0, 0, 5, 5, 4,10]},
        {"id": "library", "function": "library",     "aabb": [5, 0, 5,10, 4,10]},
    ]
    # hall → {living, kitchen} dist=1; library dist=2 via either
    doors = [
        _door("hall", "living"),
        _door("hall", "kitchen"),
        _door("living", "library"),
    ]
    result = _intimacy_gradient(_doc(spaces), _mp(doors))
    assert result["score"] is not None
    # Reconstruct (priv, dist) pairs in the deterministic iteration order
    # used internally and compare to scipy.stats.spearmanr (which uses
    # average-rank under the hood).
    from scipy.stats import spearmanr
    pv = [0, 1, 1, 1]   # hall, living, kitchen, library
    dv = [0, 1, 1, 2]
    ref_rho, _ = spearmanr(pv, dv)
    assert result["spearman"] == pytest.approx(float(ref_rho), abs=1e-3)
    # And the score is the affine transform of rho:
    assert result["score"] == pytest.approx((ref_rho + 1) / 2, abs=1e-3)


# ---------------------------------------------------------------------------
# T8 — Outside-door cascade chooses entry, NOT min(priv).
# `hall` here has function=storage (priv=1) so it would lose under min(priv)
# heuristic, but the door to outside marks it as entry.
# ---------------------------------------------------------------------------
def test_t8_outside_door_picks_entry():
    spaces = [
        {"id": "hall",    "function": "storage",     "aabb": [0, 0, 0, 5, 4, 5]},
        {"id": "living",  "function": "living_room", "aabb": [5, 0, 0,10, 4, 5]},
        {"id": "bedroom", "function": "bedroom",     "aabb": [5, 0, 5,10, 4,10]},
    ]
    doors = [
        {"id": "d-ext",   "between": ["hall", "outside"],
         "at": [0, 0, 0], "facing": "n"},
        _door("hall", "living"),
        _door("living", "bedroom"),
    ]
    result = _intimacy_gradient(_doc(spaces), _mp(doors))
    assert result["score"] is not None
    # Entry must be "hall" → per_room[hall].graph_distance == 0
    assert result["per_room"]["hall"]["graph_distance"] == 0
    assert "entry=hall" in result["notes"]
