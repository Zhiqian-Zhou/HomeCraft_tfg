"""Tests for connector_planner_v4.materialize_connectors_v4.

The v4 path is fully deterministic — no LLM patches needed. Tests
exercise the synthesizer (proposal generation from upstream artifacts)
and confirm the v3 validator produces sensible connector_plans.
"""
from __future__ import annotations

import pytest

from pipeline.agents import connector_planner_v4 as cp4


GI = {
    "schema_version": "v4",
    "category": "residential",
    "style": "medieval",
    "site_aabb": [0, 0, 0, 14, 14, 12],
    "building_aabb": [0, 0, 0, 12, 8, 10],
    "floors": [
        {"index": 0, "y0": 0, "y1": 4, "name": "ground", "role_hint": "ground"},
        {"index": 1, "y0": 4, "y1": 8, "name": "upper", "role_hint": "upper"},
    ],
    "silhouette_id": "gable-cottage-silhouette",
    "expanded_description": "Two-floor medieval cottage with a kitchen on the ground and bedrooms upstairs.",
    "height_intent": {"per_floor_height": 4, "roof_style": "gable",
                       "roof_pitch": 2, "has_basement": False,
                       "tower_axis": "none"},
    "alexander_rationale": [],
}

SP = {
    "schema_version": "v4",
    "floor_layout_id_per_floor": ["linear-corridor-layout",
                                     "double-loaded-corridor-layout"],
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
        {"id": "living-1",  "role": "living_room",
         "floor": 0, "aabb": [8, 0, 2, 12, 4, 6]},
    ],
    "adjacency_graph": [
        {"from_room": "outside",   "to_room": "entry-1",   "kind": "door"},
        {"from_room": "entry-1",   "to_room": "kitchen-1", "kind": "door"},
        {"from_room": "entry-1",   "to_room": "living-1",  "kind": "opening"},
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
        {"id": "hallway-2", "role": "hallway",
         "floor": 1, "aabb": [4, 4, 0, 8, 8, 6]},
        {"id": "bedroom-1", "role": "bedroom",
         "floor": 1, "aabb": [0, 4, 0, 4, 8, 6]},
    ],
    "adjacency_graph": [
        {"from_room": "hallway-2", "to_room": "bedroom-1", "kind": "door"},
    ],
    "reserved_footprints": [
        {"x0": 9, "z0": 6, "x1": 12, "z1": 9, "kind": "stair",
         "template_id": "dogleg-staircase"},
    ],
}


def test_door_block_for_template_resolves_known():
    assert cp4._door_block_for("formal-front-entrance", "medieval") \
        == "minecraft:oak_door"
    assert cp4._door_block_for("sliding-shoji-door", "japanese") \
        == "minecraft:spruce_door"


def test_door_block_for_template_falls_back_to_style():
    assert cp4._door_block_for(None, "modern") == "minecraft:iron_door"
    # Unknown template_id falls through to style fallback
    assert cp4._door_block_for("unknown-template", "renaissance") \
        == "minecraft:birch_door"


def test_stair_block_for_contrast():
    # El material de la escalera se elige para CONTRASTAR con el muro típico del
    # estilo (si no, se camufla y no se distingue como escalera):
    #   estilos de MADERA → escalera de PIEDRA
    assert cp4._stair_block_for("grand-staircase", "medieval") \
        == "minecraft:stone_brick_stairs"
    #   estilos de PIEDRA (gothic) → escalera de MADERA cálida
    assert cp4._stair_block_for(None, "gothic") \
        == "minecraft:oak_stairs"
    # estilo no mapeado → piedra (el caso común es muro de madera)
    assert cp4._stair_block_for(None, "some-unknown-style") \
        == "minecraft:cobblestone_stairs"


def test_facing_from_side():
    assert cp4._facing_from_side("+x") == "east"
    assert cp4._facing_from_side("-z") == "north"


def test_shape_from_template():
    assert cp4._shape_from_template("spiral-staircase") == "spiral"
    assert cp4._shape_from_template("dogleg-staircase") == "dogleg"
    assert cp4._shape_from_template("grand-staircase") == "straight"


def test_synthesize_proposals_emits_entry_door():
    props = cp4._synthesize_proposals(GI, SP, [FP0, FP1])
    entries = [d for d in props["doors"]
                if d["between"][0] == "outside"]
    assert len(entries) == 1
    assert entries[0]["between"][1] == "entry-1"


def test_synthesize_proposals_emits_interior_door():
    props = cp4._synthesize_proposals(GI, SP, [FP0, FP1])
    interior = [d for d in props["doors"]
                 if "outside" not in d["between"]]
    # entry→kitchen door, hallway→bedroom door, entry→living OPENING (=air)
    assert len(interior) == 3
    pairs = {tuple(sorted(d["between"])) for d in interior}
    assert ("entry-1", "kitchen-1") in pairs
    assert ("bedroom-1", "hallway-2") in pairs


def test_synthesize_proposals_opening_uses_air_block():
    props = cp4._synthesize_proposals(GI, SP, [FP0, FP1])
    air_doors = [d for d in props["doors"]
                  if d.get("block_key") == "minecraft:air"]
    assert len(air_doors) == 1
    assert set(air_doors[0]["between"]) == {"entry-1", "living-1"}


def test_synthesize_proposals_emits_stair():
    props = cp4._synthesize_proposals(GI, SP, [FP0, FP1])
    assert len(props["staircases"]) == 1
    s = props["staircases"][0]
    assert s["from_floor"] == 0 and s["to_floor"] == 1
    assert s["shape"] == "dogleg"
    assert s["aabb"][0] == 9 and s["aabb"][3] == 12


def test_materialize_returns_v3_compatible_plan():
    out = cp4.materialize_connectors_v4(GI, SP, [FP0, FP1])
    assert "connector_plan" in out
    cp = out["connector_plan"]
    assert cp["schema_version"] == "1.0"
    assert "doors" in cp and "staircases" in cp
    # At least the entry door survived validation
    assert len(cp["doors"]) >= 1


def test_materialize_emits_realized_audit():
    out = cp4.materialize_connectors_v4(GI, SP, [FP0, FP1])
    realized = out["connector_templates_realized"]
    # entry door + (validated) interior doors + 1 stair = some entries
    assert len(realized) >= 2
    # The entry's source template_id should be in the audit
    template_ids = [r["template_id"] for r in realized]
    assert "formal-front-entrance" in template_ids
    assert "dogleg-staircase" in template_ids


def test_outside_edge_room_finds_target():
    assert cp4._outside_edge_room([FP0, FP1], 0) == "entry-1"
    assert cp4._outside_edge_room([FP0, FP1], 1) is None


def test_find_stair_reservation():
    rsv = cp4._find_stair_reservation([FP0, FP1], 0, "dogleg-staircase")
    assert rsv is not None
    assert rsv["x0"] == 9
    # Missing floor
    assert cp4._find_stair_reservation([FP0, FP1], 5, "dogleg-staircase") is None


def test_materialize_single_floor_no_stairs():
    """A 1-floor building should emit zero staircases."""
    gi = dict(GI); gi["floors"] = [GI["floors"][0]]
    sp = dict(SP)
    sp["floor_layout_id_per_floor"] = ["linear-corridor-layout"]
    sp["vertical_connections"] = []
    fp = dict(FP0); fp["reserved_footprints"] = []
    out = cp4.materialize_connectors_v4(gi, sp, [fp])
    cp = out["connector_plan"]
    assert cp["staircases"] == []
