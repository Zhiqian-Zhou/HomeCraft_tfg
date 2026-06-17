"""Tests for inter_floor_validator.validate — pure deterministic checker."""
from __future__ import annotations

import pytest

from pipeline.agents.inter_floor_validator import (
    validate, InterFloorValidationError, FixReport,
    _rect_iou,
)


GI = {
    "schema_version": "v4",
    "expanded_description": (
        "A modest two-floor medieval cottage with a kitchen-living ground "
        "floor and bedrooms above. Timber framing, low gable roof."
    ),
    "silhouette_id": "gable-cottage-silhouette",
    "category": "residential", "style": "medieval",
    "site_aabb": [0, 0, 0, 14, 14, 12],
    "building_aabb": [0, 0, 0, 12, 8, 10],
    "floors": [
        {"index": 0, "y0": 0, "y1": 4, "name": "ground", "role_hint": "ground"},
        {"index": 1, "y0": 4, "y1": 8, "name": "upper", "role_hint": "upper"},
    ],
    "height_intent": {"per_floor_height": 4, "roof_style": "gable",
                       "roof_pitch": 2, "has_basement": False,
                       "tower_axis": "none"},
    "alexander_rationale": [],
}

SP = {
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
        {"from_floor": 0, "to_floor": 1, "template_id": "dogleg-staircase"},
    ],
    "entry_points": [
        {"floor": 0, "side": "-z", "template_id": "formal-front-entrance"},
    ],
}

FP0 = {
    "schema_version": "v4",
    "floor_index": 0,
    "layout_skill_id_used": "linear-corridor-layout",
    "rooms": [
        {"id": "entry-1",   "role": "entry_hall",
         "floor": 0, "aabb": [4, 0, 0, 8, 4, 2]},
        {"id": "kitchen-1", "role": "kitchen",
         "floor": 0, "aabb": [0, 0, 2, 4, 4, 6]},
    ],
    "adjacency_graph": [
        {"from_room": "outside",   "to_room": "entry-1",   "kind": "door"},
        {"from_room": "entry-1",   "to_room": "kitchen-1", "kind": "door"},
    ],
    "reserved_footprints": [
        {"x0": 9, "z0": 6, "x1": 12, "z1": 9, "kind": "stair",
         "template_id": "dogleg-staircase"},
    ],
}

FP1 = {
    "schema_version": "v4",
    "floor_index": 1,
    "layout_skill_id_used": "double-loaded-corridor-layout",
    "rooms": [
        {"id": "bedroom-1", "role": "bedroom",
         "floor": 1, "aabb": [0, 4, 0, 4, 8, 6]},
        {"id": "bedroom-2", "role": "bedroom",
         "floor": 1, "aabb": [4, 4, 0, 8, 8, 6]},
    ],
    "adjacency_graph": [
        {"from_room": "bedroom-1", "to_room": "bedroom-2", "kind": "opening"},
    ],
    "reserved_footprints": [
        {"x0": 9, "z0": 6, "x1": 12, "z1": 9, "kind": "stair",
         "template_id": "dogleg-staircase"},
    ],
}


def test_rect_iou_identical():
    a = {"x0": 0, "z0": 0, "x1": 4, "z1": 4}
    assert _rect_iou(a, a) == 1.0


def test_rect_iou_disjoint():
    a = {"x0": 0, "z0": 0, "x1": 2, "z1": 2}
    b = {"x0": 10, "z0": 10, "x1": 12, "z1": 12}
    assert _rect_iou(a, b) == 0.0


def test_validate_happy_path():
    fps = [dict(FP0), dict(FP1)]
    out, report = validate(global_intent=GI, space_plan=SP, floor_plans=fps)
    assert len(out) == 2
    assert isinstance(report, FixReport)
    assert report.total == 0


def test_validate_floor_index_mismatch_raises():
    fp1_bad = dict(FP1); fp1_bad["floor_index"] = 99
    with pytest.raises(InterFloorValidationError, match="floor_index"):
        validate(global_intent=GI, space_plan=SP, floor_plans=[FP0, fp1_bad])


def test_validate_layout_id_mismatch_raises():
    fp1_bad = dict(FP1)
    fp1_bad["layout_skill_id_used"] = "different-layout"
    with pytest.raises(InterFloorValidationError, match="layout_skill_id_used"):
        validate(global_intent=GI, space_plan=SP, floor_plans=[FP0, fp1_bad])


def test_validate_stair_misaligned_hard_error():
    """IoU < 0.2 between paired stair reservations → hard error."""
    fp1_bad = dict(FP1)
    fp1_bad["reserved_footprints"] = [
        {"x0": 0, "z0": 0, "x1": 3, "z1": 3, "kind": "stair",
         "template_id": "dogleg-staircase"},  # nowhere near floor 0's [9,6,12,9]
    ]
    with pytest.raises(InterFloorValidationError, match="misaligned"):
        validate(global_intent=GI, space_plan=SP, floor_plans=[FP0, fp1_bad])


def test_validate_stair_partial_overlap_auto_snaps():
    """IoU in [0.2, 0.5) → snap floor B's footprint to floor A's."""
    fp1_off = dict(FP1)
    # Offset by (1,1) — substantial IoU but not perfect
    fp1_off["reserved_footprints"] = [
        {"x0": 10, "z0": 7, "x1": 13, "z1": 10, "kind": "stair",
         "template_id": "dogleg-staircase"},
    ]
    iou = _rect_iou({"x0": 9, "z0": 6, "x1": 12, "z1": 9},
                     {"x0": 10, "z0": 7, "x1": 13, "z1": 10})
    assert 0.2 <= iou < 0.5, f"IoU={iou:.3f} not in snap range"
    fps, report = validate(global_intent=GI, space_plan=SP,
                              floor_plans=[FP0, fp1_off])
    assert len(report.snapped_stairs) == 1
    # Floor 1's stair was snapped to floor 0's
    assert fps[1]["reserved_footprints"][0]["x0"] == 9
    assert fps[1]["reserved_footprints"][0]["x1"] == 12


def test_validate_missing_entry_point_edge_autofix():
    """Floor 0 has no 'outside' edge but space_plan has an entry_point."""
    fp0_no_outside = dict(FP0)
    fp0_no_outside["adjacency_graph"] = [
        {"from_room": "entry-1", "to_room": "kitchen-1", "kind": "door"},
    ]
    fps, report = validate(global_intent=GI, space_plan=SP,
                              floor_plans=[fp0_no_outside, FP1])
    assert len(report.synthesized_outside_edges) == 1
    # Verify an outside edge was added
    has_outside = any(
        e.get("from_room") == "outside" or e.get("to_room") == "outside"
        for e in fps[0]["adjacency_graph"])
    assert has_outside


def test_validate_room_id_collision_renamed():
    """Two floors share 'bedroom-1' → floor B's gets renamed with suffix."""
    fp0_collision = dict(FP0)
    fp0_collision["rooms"] = [
        {"id": "bedroom-1", "role": "bedroom",
         "floor": 0, "aabb": [0, 0, 0, 4, 4, 4]},
        {"id": "entry-1", "role": "entry_hall",
         "floor": 0, "aabb": [4, 0, 0, 8, 4, 4]},
    ]
    fp0_collision["adjacency_graph"] = [
        {"from_room": "outside", "to_room": "entry-1", "kind": "door"},
        {"from_room": "entry-1", "to_room": "bedroom-1", "kind": "door"},
    ]
    fps, report = validate(global_intent=GI, space_plan=SP,
                              floor_plans=[fp0_collision, FP1])
    # Floor 1's bedroom-1 was renamed
    assert len(report.renamed_room_ids) >= 1
    assert any(old == "bedroom-1" for old, new, fi in report.renamed_room_ids)


def test_validate_wrong_n_floors_raises():
    with pytest.raises(InterFloorValidationError, match="length"):
        validate(global_intent=GI, space_plan=SP, floor_plans=[FP0])


def test_validate_vertical_connection_missing_reservation():
    """Floor without a stair reservation for the declared VC → hard error."""
    fp1_no_stair = dict(FP1); fp1_no_stair["reserved_footprints"] = []
    with pytest.raises(InterFloorValidationError, match="reserved_footprint"):
        validate(global_intent=GI, space_plan=SP,
                  floor_plans=[FP0, fp1_no_stair])
