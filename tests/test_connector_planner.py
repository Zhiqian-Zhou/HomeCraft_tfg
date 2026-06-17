"""Tests for connector_planner — LLM patched out; validator wiring is real."""
from __future__ import annotations

from unittest.mock import patch
import pytest

from pipeline.agents import connector_planner


GLOBAL = {
    "schema_version": "1.0",
    "prompt": "cottage",
    "category": "residential",
    "style": "medieval",
    "site_aabb": [0, 0, 0, 12, 6, 12],
    "building_aabb": [0, 0, 0, 10, 4, 10],
    "floors": [{"index": 0, "y0": 0, "y1": 4}],
    "height_intent": {},
    "alexander_rationale": [],
}

SPACE = {
    "schema_version": "1.0",
    "rooms": [
        {"id": "entry-1", "role": "entry_hall", "floor": 0,
         "aabb": [0, 0, 0, 5, 4, 5]},
        {"id": "kitchen-1", "role": "kitchen", "floor": 0,
         "aabb": [5, 0, 0, 10, 4, 5]},
    ],
    "adjacency_graph": [
        {"from_room": "outside", "to_room": "entry-1", "kind": "door"},
        {"from_room": "entry-1", "to_room": "kitchen-1", "kind": "door"},
    ],
}


def test_plan_connectors_validator_repairs_y_zero():
    """LLM emits door at y=0; validator clamps to y=1."""
    bad_llm = {
        "doors": [
            {"id": "d1", "between": ["entry-1", "kitchen-1"],
             "at": [4, 0, 2], "facing": "n"},
        ],
        "windows": [],
        "staircases": [],
    }
    with patch.object(connector_planner, "call_llm_json", return_value=bad_llm):
        plan = connector_planner.plan_connectors(GLOBAL, SPACE)

    assert len(plan["doors"]) == 1
    door = plan["doors"][0]
    assert door["validated"]["at"][1] == 1  # y clamped
    # warnings should record clamp + snap-to-wall + facing
    codes = {w["code"] for w in door["warnings"]}
    assert "clamped_axis" in codes


def test_plan_connectors_empty_llm_output_handled():
    """If LLM returns nothing useful, return empty plan."""
    with patch.object(connector_planner, "call_llm_json",
                        return_value={"doors": [], "windows": [], "staircases": []}):
        plan = connector_planner.plan_connectors(GLOBAL, SPACE)
    assert plan["doors"] == []
    assert plan["windows"] == []
    assert plan["staircases"] == []


def test_plan_connectors_retries_on_format_error():
    """First LLM call returns garbage; second is valid."""
    good = {"doors": [], "windows": [], "staircases": []}
    with patch.object(connector_planner, "call_llm_json",
                        side_effect=["not a dict", good]):
        plan = connector_planner.plan_connectors(GLOBAL, SPACE)
    assert "doors" in plan


def test_plan_connectors_carve_ops_emitted():
    """Repaired door gets carve_ops attached."""
    llm = {
        "doors": [
            {"id": "d1", "between": ["outside", "entry-1"],
             "at": [0, 1, 2], "facing": "w"},
        ],
        "windows": [], "staircases": [],
    }
    with patch.object(connector_planner, "call_llm_json", return_value=llm):
        plan = connector_planner.plan_connectors(GLOBAL, SPACE)
    door = plan["doors"][0]
    assert len(door["carve_ops"]) == 6
    assert all(op["block"] == "minecraft:air" for op in door["carve_ops"])


def test_plan_connectors_summary_present():
    llm = {"doors": [
        {"id": "d1", "between": ["entry-1", "kitchen-1"],
         "at": [4, 0, 2], "facing": "n"},
    ], "windows": [], "staircases": []}
    with patch.object(connector_planner, "call_llm_json", return_value=llm):
        plan = connector_planner.plan_connectors(GLOBAL, SPACE)
    assert "summary" in plan
    assert "warning_codes" in plan["summary"]


def test_plan_connectors_output_is_schema_valid():
    from pipeline.agents.schema_utils import make_validator
    validator = make_validator("connector_plan.schema.json")
    llm = {"doors": [
        {"id": "d1", "between": ["outside", "entry-1"],
         "at": [0, 0, 2], "facing": "w"},
    ], "windows": [], "staircases": []}
    with patch.object(connector_planner, "call_llm_json", return_value=llm):
        plan = connector_planner.plan_connectors(GLOBAL, SPACE)
    validator.validate(plan)
