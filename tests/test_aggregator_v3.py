"""Tests for aggregator.aggregate_v3 — consumes 4 streams, produces master_plan."""
from __future__ import annotations

import pytest

from pipeline.agents.aggregator import aggregate_v3, _v3_connector_ops, _strip_envelope_tags


GI = {
    "schema_version": "1.0",
    "prompt": "small cottage",
    "category": "residential",
    "style": "medieval",
    "site_aabb": [0, 0, 0, 12, 6, 12],
    "building_aabb": [0, 0, 0, 10, 4, 10],
    "floors": [{"index": 0, "y0": 0, "y1": 4}],
    "height_intent": {},
    "alexander_rationale": [],
}

SP = {
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

AP = {
    "schema_version": "1.0",
    "ops": [
        {"kind": "fill_hollow", "envelope_role": "wall", "room_id": "entry-1",
         "shared_with": ["kitchen-1"], "aabb": [0, 0, 0, 5, 4, 5],
         "wall_block": "minecraft:oak_planks",
         "floor_block": "minecraft:oak_planks",
         "ceiling_block": "minecraft:oak_planks"},
    ],
    "materials_used": [],
    "generated_by": {"deterministic": True, "module": "x", "version": "1.0"},
}

CP = {
    "schema_version": "1.0",
    "doors": [
        {"id": "d1",
         "proposal": {},
         "validated": {"between": ["outside", "entry-1"],
                         "at": [0, 1, 2], "facing": "w",
                         "block_key": "@door"},
         "warnings": [],
         "carve_ops": [
             {"kind": "place", "at": [0, 1, 2], "block": "minecraft:air"}
         ]},
    ],
    "windows": [], "staircases": [], "dropped": [],
    "summary": {"passthrough": 1, "auto_fixed": 0, "dropped": 0, "warning_codes": {}},
}


def test_aggregate_v3_produces_master_plan():
    master = aggregate_v3(GI, SP, AP, CP, [], None, gen_id="smoke-v3")
    assert master["id"] == "smoke-v3"
    assert master["style"] == "medieval"
    assert master["site_aabb"] == [0, 0, 0, 12, 6, 12]
    assert "ops" in master and len(master["ops"]) > 0
    assert "connectors" in master
    assert len(master["connectors"]["doors"]) == 1


def test_aggregate_v3_op_order_carve_before_materialize():
    """The carve_op for door d1 must appear BEFORE the door's
    place ops (lower + upper) in master.ops.
    """
    master = aggregate_v3(GI, SP, AP, CP, [], None, gen_id="order-v3")
    carve_idx = next(i for i, op in enumerate(master["ops"])
                       if op.get("kind") == "place"
                       and op.get("block") == "minecraft:air")
    door_idx = next(i for i, op in enumerate(master["ops"])
                      if op.get("kind") == "place"
                      and isinstance(op.get("block"), str)
                      and "door" in op["block"])
    assert carve_idx < door_idx, "carve must precede door materialization"


def test_aggregate_v3_strips_envelope_tags():
    """The composer never sees room_id / envelope_role fields."""
    master = aggregate_v3(GI, SP, AP, CP, [], None, gen_id="strip-v3")
    fh_ops = [op for op in master["ops"] if op.get("kind") == "fill_hollow"]
    for op in fh_ops:
        assert "room_id" not in op
        assert "envelope_role" not in op
        assert "shared_with" not in op
        # Composer expects 'wall' field, not 'wall_block'
        assert "wall" in op
        assert "wall_block" not in op


def test_aggregate_v3_connectors_compat_for_evaluator():
    """master_plan.connectors must have v2.6-shaped doors[] with between/at/facing."""
    master = aggregate_v3(GI, SP, AP, CP, [], None, gen_id="compat-v3")
    doors = master["connectors"]["doors"]
    assert len(doors) == 1
    d = doors[0]
    assert d["between"] == ["outside", "entry-1"]
    assert "at" in d
    assert "facing" in d


def test_aggregate_v3_dropped_connectors_surface_as_warnings():
    cp = dict(CP)
    cp["dropped"] = [{"id": "d2", "kind": "door",
                       "drop_code": "no_valid_wall",
                       "details": "ghost"}]
    master = aggregate_v3(GI, SP, AP, cp, [], None, gen_id="drop-v3")
    assert any("dropped" in w for w in master["warnings"])


def test_strip_envelope_tags_unit():
    op = {"kind": "fill_hollow", "envelope_role": "wall",
           "room_id": "r1", "shared_with": ["r2"],
           "aabb": [0, 0, 0, 1, 1, 1],
           "wall_block": "minecraft:stone"}
    out = _strip_envelope_tags(op)
    assert "envelope_role" not in out
    assert "room_id" not in out
    assert out["wall"] == "minecraft:stone"


def test_v3_connector_ops_emit_door_pair():
    cp = {"doors": [{"id": "d", "validated": {
        "between": ["outside", "a"], "at": [5, 1, 0],
        "facing": "n", "block_key": "@door"}}],
          "windows": [], "staircases": []}
    ops = _v3_connector_ops(cp)
    assert len(ops) == 2
    assert all(op["kind"] == "place" for op in ops)
    assert "facing=north" in ops[0]["block"]


def test_aggregate_v3_master_plan_schema_valid():
    from pipeline.agents.schema_utils import make_validator
    validator = make_validator("master_plan.schema.json")
    master = aggregate_v3(GI, SP, AP, CP, [], None, gen_id="valid-v3")
    validator.validate(master)
