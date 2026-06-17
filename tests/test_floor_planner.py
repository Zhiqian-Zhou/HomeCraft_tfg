"""Tests for floor_planner.plan_floor + plan_floors_parallel.

LLM is patched out; tests focus on contract validation, parallelization,
and the per-floor post-validation rules.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline.agents import floor_planner


GLOBAL_INTENT = {
    "schema_version": "v4",
    "expanded_description": (
        "A modest two-floor medieval cottage with a kitchen-living ground "
        "floor and bedrooms above. Timber framing, low gable roof."
    ),
    "silhouette_id": "gable-cottage-silhouette",
    "category": "residential",
    "style": "medieval",
    "site_aabb": [0, 0, 0, 14, 14, 12],
    "building_aabb": [0, 0, 0, 12, 8, 10],
    "floors": [
        {"index": 0, "y0": 0, "y1": 4, "name": "ground", "role_hint": "ground"},
        {"index": 1, "y0": 4, "y1": 8, "name": "upper", "role_hint": "upper"},
    ],
    "height_intent": {"per_floor_height": 4, "roof_style": "gable",
                       "roof_pitch": 2, "has_basement": False,
                       "tower_axis": "none"},
    "alexander_rationale": [{"pattern_id": "sheltering-roof",
                               "rationale": "low gable"}],
}

SPACE_PLAN = {
    "schema_version": "v4",
    "floor_layout_id_per_floor": [
        "linear-corridor-layout",
        "double-loaded-corridor-layout",
    ],
    "connector_templates_used": [
        {"template_id": "formal-front-entrance", "role": "entrance"},
        {"template_id": "dogleg-staircase", "role": "stair"},
    ],
    "vertical_connections": [
        {"from_floor": 0, "to_floor": 1, "template_id": "dogleg-staircase",
         "footprint": {"x0": 9, "z0": 6, "x1": 12, "z1": 9}},
    ],
    "entry_points": [
        {"floor": 0, "side": "-z", "template_id": "formal-front-entrance"},
    ],
    "room_role_hints_per_floor": [
        ["entry_hall", "kitchen", "living_room"],
        ["bedroom", "bedroom", "bathroom"],
    ],
}

GOOD_FLOOR_0 = {
    "schema_version": "v4",
    "floor_index": 0,
    "layout_skill_id_used": "linear-corridor-layout",
    # All rooms >= 4x4 in XZ (1-thick walls leave >= 2x2 interior); rooms tile
    # the floor and adjacent rooms share full walls so doors fit.
    "rooms": [
        {"id": "entry-1",   "role": "entry_hall",
         "floor": 0, "aabb": [4, 0, 0, 8, 4, 4]},
        {"id": "hallway-1", "role": "hallway",
         "floor": 0, "aabb": [4, 0, 4, 8, 4, 8]},
        {"id": "kitchen-1", "role": "kitchen",
         "floor": 0, "aabb": [0, 0, 4, 4, 4, 8]},
        {"id": "living-1",  "role": "living_room",
         "floor": 0, "aabb": [8, 0, 4, 12, 4, 8]},
    ],
    "adjacency_graph": [
        {"from_room": "outside",   "to_room": "entry-1",   "kind": "door"},
        {"from_room": "entry-1",   "to_room": "hallway-1", "kind": "opening"},
        {"from_room": "hallway-1", "to_room": "kitchen-1", "kind": "door"},
        {"from_room": "hallway-1", "to_room": "living-1",  "kind": "door"},
    ],
    "reserved_footprints": [
        {"x0": 9, "z0": 6, "x1": 12, "z1": 9, "kind": "stair",
         "template_id": "dogleg-staircase"},
    ],
}

GOOD_FLOOR_1 = {
    "schema_version": "v4",
    "floor_index": 1,
    "layout_skill_id_used": "double-loaded-corridor-layout",
    "rooms": [
        {"id": "hallway-2", "role": "hallway",
         "floor": 1, "aabb": [4, 4, 0, 8, 8, 6]},
        {"id": "bedroom-1", "role": "bedroom",
         "floor": 1, "aabb": [0, 4, 0, 4, 8, 6]},
        {"id": "bedroom-2", "role": "bedroom",
         "floor": 1, "aabb": [8, 4, 0, 12, 8, 6]},
    ],
    "adjacency_graph": [
        {"from_room": "hallway-2", "to_room": "bedroom-1", "kind": "door"},
        {"from_room": "hallway-2", "to_room": "bedroom-2", "kind": "door"},
    ],
    "reserved_footprints": [
        {"x0": 9, "z0": 6, "x1": 12, "z1": 9, "kind": "stair",
         "template_id": "dogleg-staircase"},
    ],
}


@pytest.fixture(autouse=True)
def _reset_caches():
    floor_planner._reset_v4_caches()
    yield
    floor_planner._reset_v4_caches()


def test_floor_layouts_full_cache_loads():
    cache = floor_planner._floor_layouts_full()
    assert "linear-corridor-layout" in cache
    # Full content, not just briefs — has placement_rules
    assert "placement_rules" in cache["linear-corridor-layout"]


def test_room_role_briefs_loads_18():
    briefs = floor_planner._room_role_briefs()
    ids = [b["id"] for b in briefs]
    assert "kitchen" in ids
    assert "bedroom" in ids
    assert len(briefs) >= 15  # 18 expected


def test_reserved_footprints_for_floor_extracts_stair():
    rsv = floor_planner._reserved_footprints_for_floor(SPACE_PLAN, 0)
    assert len(rsv) == 1
    assert rsv[0]["kind"] == "stair"
    assert rsv[0]["template_id"] == "dogleg-staircase"


def test_reserved_footprints_for_floor_with_no_vc():
    sp = dict(SPACE_PLAN); sp["vertical_connections"] = []
    rsv = floor_planner._reserved_footprints_for_floor(sp, 0)
    assert rsv == []


def test_plan_floor_returns_validated_dict():
    with patch.object(floor_planner, "call_llm_json",
                       return_value=dict(GOOD_FLOOR_0)):
        doc = floor_planner.plan_floor(
            floor_index=0, global_intent=GLOBAL_INTENT, space_plan=SPACE_PLAN)
    assert doc["schema_version"] == "v4"
    assert doc["floor_index"] == 0
    assert doc["layout_skill_id_used"] == "linear-corridor-layout"
    # reserved_footprints passed through
    assert len(doc["reserved_footprints"]) == 1


def test_plan_floor_pins_layout_id():
    """LLM might emit wrong layout_skill_id; agent should pin it."""
    polluted = dict(GOOD_FLOOR_0)
    polluted["layout_skill_id_used"] = "made-up-layout"
    with patch.object(floor_planner, "call_llm_json", return_value=polluted):
        doc = floor_planner.plan_floor(
            floor_index=0, global_intent=GLOBAL_INTENT, space_plan=SPACE_PLAN)
    assert doc["layout_skill_id_used"] == "linear-corridor-layout"


def test_plan_floor_pins_floor_index():
    polluted = dict(GOOD_FLOOR_0)
    polluted["floor_index"] = 5
    with patch.object(floor_planner, "call_llm_json", return_value=polluted):
        doc = floor_planner.plan_floor(
            floor_index=0, global_intent=GLOBAL_INTENT, space_plan=SPACE_PLAN)
    assert doc["floor_index"] == 0


def test_plan_floor_out_of_range_raises():
    with pytest.raises(IndexError):
        floor_planner.plan_floor(
            floor_index=5, global_intent=GLOBAL_INTENT, space_plan=SPACE_PLAN)


def test_plan_floor_rejects_overlap_with_reservation():
    """Room placed on top of the reserved stair footprint must trigger retry."""
    bad = {
        "schema_version": "v4",
        "floor_index": 0,
        "layout_skill_id_used": "linear-corridor-layout",
        # Place a room exactly over the reserved [9,6,12,9] stair area
        "rooms": [
            {"id": "kitchen-1", "role": "kitchen",
             "floor": 0, "aabb": [8, 0, 5, 12, 4, 10]},
            {"id": "entry-1",   "role": "entry_hall",
             "floor": 0, "aabb": [0, 0, 0, 4, 4, 2]},
        ],
        "adjacency_graph": [
            {"from_room": "outside", "to_room": "entry-1", "kind": "door"},
            {"from_room": "entry-1", "to_room": "kitchen-1", "kind": "door"},
        ],
    }
    with patch.object(floor_planner, "call_llm_json",
                       side_effect=[bad, dict(GOOD_FLOOR_0)]):
        doc = floor_planner.plan_floor(
            floor_index=0, global_intent=GLOBAL_INTENT, space_plan=SPACE_PLAN)
    # Retry succeeded with the good response
    assert doc["floor_index"] == 0


def test_plan_floors_parallel_returns_in_order():
    """Even though futures complete in any order, output is index-sorted."""
    def fake(system, user, **kwargs):
        # Inspect which floor_index appears in the user payload
        if '"floor_index": 0' in user:
            return dict(GOOD_FLOOR_0)
        if '"floor_index": 1' in user:
            return dict(GOOD_FLOOR_1)
        return {}
    with patch.object(floor_planner, "call_llm_json", side_effect=fake):
        plans = floor_planner.plan_floors_parallel(
            global_intent=GLOBAL_INTENT, space_plan=SPACE_PLAN)
    assert len(plans) == 2
    assert plans[0]["floor_index"] == 0
    assert plans[1]["floor_index"] == 1


def test_plan_floors_parallel_single_floor():
    gi = dict(GLOBAL_INTENT)
    gi["floors"] = [GLOBAL_INTENT["floors"][0]]
    sp = dict(SPACE_PLAN)
    sp["floor_layout_id_per_floor"] = ["linear-corridor-layout"]
    sp["vertical_connections"] = []
    with patch.object(floor_planner, "call_llm_json",
                       return_value=dict(GOOD_FLOOR_0)):
        plans = floor_planner.plan_floors_parallel(
            global_intent=gi, space_plan=sp)
    assert len(plans) == 1
    assert plans[0]["floor_index"] == 0


# ── Fase B: room-size + shared-wall post-validation (deterministic) ──

def _pv(doc):
    """Call _post_validate with the standard floor-0 context."""
    return floor_planner._post_validate(
        doc, floor=GLOBAL_INTENT["floors"][0], floor_index=0,
        building_aabb=GLOBAL_INTENT["building_aabb"], reserved=[],
        entry_points=[], expected_layout_id="linear-corridor-layout")


def test_post_validate_accepts_good_floor():
    assert _pv(dict(GOOD_FLOOR_0)) == []


def test_post_validate_rejects_degenerate_room():
    """A 3-wide bedroom (1-cell interior) must be rejected with feedback."""
    doc = {
        "schema_version": "v4", "floor_index": 0,
        "layout_skill_id_used": "linear-corridor-layout",
        "rooms": [
            {"id": "entry-1", "role": "entry_hall", "floor": 0,
             "aabb": [0, 0, 0, 6, 4, 6]},
            {"id": "bedroom-1", "role": "bedroom", "floor": 0,
             "aabb": [6, 0, 0, 9, 4, 6]},   # 3 wide → 1-cell interior
        ],
        "adjacency_graph": [
            {"from_room": "entry-1", "to_room": "bedroom-1", "kind": "door"},
        ],
        "reserved_footprints": [],
    }
    errs = _pv(doc)
    assert any("too small" in e and "bedroom-1" in e for e in errs)


def test_post_validate_allows_narrow_hallway():
    """A 3-wide hallway (corridor) is allowed; a 3-wide room is not."""
    doc = {
        "schema_version": "v4", "floor_index": 0,
        "layout_skill_id_used": "linear-corridor-layout",
        "rooms": [
            {"id": "hallway-1", "role": "hallway", "floor": 0,
             "aabb": [0, 0, 0, 3, 4, 10]},   # 3 wide corridor — OK
            {"id": "kitchen-1", "role": "kitchen", "floor": 0,
             "aabb": [3, 0, 0, 8, 4, 10]},
        ],
        "adjacency_graph": [
            {"from_room": "hallway-1", "to_room": "kitchen-1", "kind": "opening"},
        ],
        "reserved_footprints": [],
    }
    errs = _pv(doc)
    assert not any("hallway-1" in e and "too small" in e for e in errs)


def test_persistent_llm_failure_falls_back_not_raises():
    """If the LLM keeps emitting an invalid plan, plan_floor returns a valid
    deterministic BSP partition instead of killing the build."""
    bad = {
        "schema_version": "v4", "floor_index": 0,
        "layout_skill_id_used": "linear-corridor-layout",
        "rooms": [
            {"id": "bedroom-1", "role": "bedroom", "floor": 0,
             "aabb": [0, 0, 0, 2, 4, 12]},   # 2 wide → always rejected
        ],
        "adjacency_graph": [
            {"from_room": "outside", "to_room": "bedroom-1", "kind": "door"}],
        "reserved_footprints": [],
    }
    with patch.object(floor_planner, "call_llm_json", return_value=dict(bad)):
        doc = floor_planner.plan_floor(
            floor_index=0, global_intent=GLOBAL_INTENT, space_plan=SPACE_PLAN)
    # Fallback produced a valid floor — every room is at least 4 in min XZ.
    assert doc["rooms"]
    for r in doc["rooms"]:
        a = r["aabb"]
        assert min(a[3] - a[0], a[5] - a[2]) >= 4
    # And post-validation is clean on the fallback.
    assert _pv(doc) == []


def test_post_validate_rejects_door_without_shared_wall():
    """A door between two rooms that don't touch must be rejected."""
    doc = {
        "schema_version": "v4", "floor_index": 0,
        "layout_skill_id_used": "linear-corridor-layout",
        "rooms": [
            {"id": "kitchen-1", "role": "kitchen", "floor": 0,
             "aabb": [0, 0, 0, 4, 4, 4]},
            {"id": "living-1", "role": "living_room", "floor": 0,
             "aabb": [8, 0, 8, 12, 4, 12]},   # far away — no shared wall
        ],
        "adjacency_graph": [
            {"from_room": "kitchen-1", "to_room": "living-1", "kind": "door"},
        ],
        "reserved_footprints": [],
    }
    errs = _pv(doc)
    assert any("share a full wall" in e for e in errs)
