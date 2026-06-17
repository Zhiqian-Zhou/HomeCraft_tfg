"""Tests for space_planner — LLM patched out."""
from __future__ import annotations

from unittest.mock import patch
import pytest

from pipeline.agents import space_planner


GLOBAL_FAKE = {
    "schema_version": "1.0",
    "prompt": "small cottage",
    "category": "residential",
    "style": "medieval",
    "site_aabb": [0, 0, 0, 12, 8, 12],
    "building_aabb": [0, 0, 0, 10, 6, 10],
    "floors": [{"index": 0, "y0": 0, "y1": 4}],
    "height_intent": {},
    "alexander_rationale": [],
}


VALID_SP = {
    "schema_version": "1.0",
    "rooms": [
        {"id": "entry-1", "role": "entry_hall", "floor": 0,
         "aabb": [0, 0, 0, 4, 4, 4]},
        {"id": "kitchen-1", "role": "kitchen", "floor": 0,
         "aabb": [4, 0, 0, 10, 4, 5]},
        {"id": "bedroom-1", "role": "bedroom", "floor": 0,
         "aabb": [0, 0, 5, 10, 4, 10]},
    ],
    "adjacency_graph": [
        {"from_room": "outside", "to_room": "entry-1", "kind": "door"},
        {"from_room": "entry-1", "to_room": "kitchen-1", "kind": "door"},
        {"from_room": "entry-1", "to_room": "bedroom-1", "kind": "door"},
    ],
}


def test_plan_spaces_happy_path():
    with patch.object(space_planner, "call_llm_json", return_value=dict(VALID_SP)):
        with patch.object(space_planner, "retrieve", return_value=[]):
            doc = space_planner.plan_spaces(GLOBAL_FAKE)
    assert len(doc["rooms"]) == 3
    assert len(doc["adjacency_graph"]) == 3


def test_post_validate_catches_orphan_room():
    """Room with no adjacency edge → reject."""
    bad = dict(VALID_SP)
    bad["adjacency_graph"] = [
        {"from_room": "outside", "to_room": "entry-1", "kind": "door"},
        # bedroom-1 and kitchen-1 are now orphans
    ]
    errs = space_planner._post_validate(bad, GLOBAL_FAKE)
    assert any("orphan" in e for e in errs)


def test_post_validate_catches_overlap():
    bad = dict(VALID_SP)
    bad["rooms"] = [
        {"id": "a", "role": "kitchen", "floor": 0, "aabb": [0, 0, 0, 5, 4, 5]},
        {"id": "b", "role": "bedroom", "floor": 0, "aabb": [3, 0, 0, 8, 4, 5]},  # overlaps a
    ]
    bad["adjacency_graph"] = [
        {"from_room": "outside", "to_room": "a", "kind": "door"},
        {"from_room": "a", "to_room": "b", "kind": "door"},
    ]
    errs = space_planner._post_validate(bad, GLOBAL_FAKE)
    assert any("overlap" in e for e in errs)


def test_post_validate_catches_outside_building():
    bad = dict(VALID_SP)
    bad["rooms"] = [
        {"id": "a", "role": "kitchen", "floor": 0,
         "aabb": [50, 0, 50, 60, 4, 60]},  # way outside
    ]
    bad["adjacency_graph"] = [
        {"from_room": "outside", "to_room": "a", "kind": "door"}
    ]
    errs = space_planner._post_validate(bad, GLOBAL_FAKE)
    assert any("outside building_aabb" in e for e in errs)


def test_post_validate_catches_no_outside_edge():
    """Building must be enterable."""
    bad = dict(VALID_SP)
    bad["adjacency_graph"] = [
        {"from_room": "entry-1", "to_room": "kitchen-1", "kind": "door"},
        {"from_room": "entry-1", "to_room": "bedroom-1", "kind": "door"},
    ]
    errs = space_planner._post_validate(bad, GLOBAL_FAKE)
    assert any("enterable" in e for e in errs)


def test_plan_spaces_raises_on_two_failures():
    bad = {"schema_version": "1.0", "rooms": [], "adjacency_graph": []}
    with patch.object(space_planner, "call_llm_json", side_effect=[bad, bad]):
        with patch.object(space_planner, "retrieve", return_value=[]):
            with pytest.raises((ValueError, RuntimeError)):
                space_planner.plan_spaces(GLOBAL_FAKE)


def test_outside_as_room_id_rejected():
    bad = dict(VALID_SP)
    bad["rooms"] = bad["rooms"] + [{"id": "outside", "role": "kitchen",
                                       "floor": 0, "aabb": [0, 0, 0, 1, 4, 1]}]
    errs = space_planner._post_validate(bad, GLOBAL_FAKE)
    assert any("'outside'" in e and "reserved" in e for e in errs)


def test_schema_validity():
    from pipeline.agents.schema_utils import make_validator
    validator = make_validator("space_plan.schema.json")
    validator.validate(VALID_SP)
