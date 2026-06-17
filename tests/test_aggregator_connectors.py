"""Tests for the aggregator's connectors propagation (v2 planner fix).

Before v2, the aggregator emitted ops from design_intent.connectors but
did not copy the connectors block itself into the master_plan. That left
evaluator metrics (main_entrance, voxel_connectivity, light_on_two_sides)
without the input they needed, so they returned null/0.0 regardless of
generated quality. These tests pin the propagation contract.
"""
from __future__ import annotations

import pytest

from pipeline.agents.aggregator import aggregate
from pipeline.agents.schema_utils import make_validator


def _minimal_di(connectors: dict | None = None) -> dict:
    """A schema-valid design_intent with optional connectors override."""
    return {
        "id": "test-gen",
        "prompt": "test",
        "category": "residential",
        "style": "medieval",
        "site_aabb": [0, 0, 0, 8, 6, 8],
        "bot_decomposition": {
            "building": {
                "storeys": [
                    {
                        "id": "s0",
                        "spaces": [
                            {"id": "room-1", "function": "living_room",
                             "aabb": [0, 0, 0, 8, 4, 8]},
                        ],
                    }
                ]
            }
        },
        "connectors": connectors if connectors is not None else {
            "doors": [], "windows": [], "staircases": [],
        },
    }


def _minimal_rp(room_id: str = "room-1") -> dict:
    return {
        "room_id": room_id,
        "aabb": [0, 0, 0, 8, 4, 8],
        "function": "living_room",
        "ops": [{"op": "fill", "aabb": [0, 0, 0, 8, 1, 8],
                 "block_key": "@floor"}],
        "doors_realized": [],
        "windows_realized": [],
    }


def test_aggregator_propagates_connectors_to_master_plan():
    """Aggregator must copy design_intent.connectors into master_plan."""
    doors = [
        {"id": "d1", "between": ["outside", "room-1"], "at": [4, 1, 0],
         "facing": "n", "block_key": "@door"},
    ]
    windows = [
        {"id": "w1", "in_room": "room-1", "wall": "s",
         "aabb": [3, 2, 7, 5, 3, 8], "block_key": "@window"},
    ]
    staircases = []
    di = _minimal_di({"doors": doors, "windows": windows,
                      "staircases": staircases})
    master = aggregate(di, [_minimal_rp()], None, gen_id="agg-test")

    assert "connectors" in master, "master_plan missing connectors block"
    assert master["connectors"]["doors"] == doors
    assert master["connectors"]["windows"] == windows
    assert master["connectors"]["staircases"] == staircases


def test_aggregator_master_plan_is_schema_valid_with_connectors():
    """Output passes master_plan.schema.json strict validation."""
    di = _minimal_di({
        "doors": [
            {"id": "d1", "between": ["outside", "room-1"], "at": [4, 1, 0],
             "facing": "north", "block_key": "@door"},
        ],
        "windows": [], "staircases": [],
    })
    master = aggregate(di, [_minimal_rp()], None, gen_id="agg-schema")
    # If the schema rejects the connectors field, aggregate() raises;
    # this assertion is the explicit double-check.
    make_validator("master_plan.schema.json").validate(master)


def test_aggregator_empty_connectors_still_propagated():
    """Even an empty connectors block must appear so downstream code
    can distinguish 'planner ran but had nothing' from 'planner missing'.
    """
    di = _minimal_di({"doors": [], "windows": [], "staircases": []})
    master = aggregate(di, [_minimal_rp()], None, gen_id="agg-empty")
    assert master["connectors"] == {
        "doors": [], "windows": [], "staircases": [],
    }


def test_aggregator_handles_missing_connectors_gracefully():
    """If design_intent lacks connectors entirely, master_plan gets {}.
    This codepath exists for backward compatibility with old test
    fixtures; new pipeline output always carries the full block.
    """
    di = _minimal_di()
    di.pop("connectors", None)
    master = aggregate(di, [_minimal_rp()], None, gen_id="agg-noconn")
    assert master.get("connectors") == {}


def test_short_form_facing_accepted_by_schema():
    """master_plan.schema.json accepts short facing forms ('n','s','e','w')
    as the design_intent does. The evaluator's _exterior_seeds was
    extended to map both forms to deltas."""
    di = _minimal_di({
        "doors": [
            {"id": "d1", "between": ["outside", "room-1"], "at": [4, 1, 0],
             "facing": "s", "block_key": "@door"},
        ],
        "windows": [], "staircases": [],
    })
    master = aggregate(di, [_minimal_rp()], None, gen_id="agg-short")
    assert master["connectors"]["doors"][0]["facing"] == "s"


def test_evaluator_metric_now_receives_connectors():
    """End-to-end: after aggregation, the evaluator can see doors."""
    di = _minimal_di({
        "doors": [
            {"id": "d1", "between": ["outside", "room-1"], "at": [4, 1, 0],
             "facing": "n", "block_key": "@door"},
        ],
        "windows": [], "staircases": [],
    })
    master = aggregate(di, [_minimal_rp()], None, gen_id="agg-e2e")
    doors_seen = (master.get("connectors") or {}).get("doors") or []
    outside = [d for d in doors_seen if "outside" in d.get("between", [])]
    assert len(outside) == 1, (
        "Aggregator failed to propagate the outside door — the very bug "
        "this test is meant to pin"
    )
