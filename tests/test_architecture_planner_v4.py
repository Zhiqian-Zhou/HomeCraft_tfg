"""Tests for architecture_planner.plan_architecture_v4 — v4 deterministic path.

No LLM; tests focus on aggregation of floor_plans, stair_void cuts in
slabs, schema validity, and the wall_fittings_applied audit (style map +
conditional predicates + exclusions).
"""
from __future__ import annotations

import json
from pathlib import Path

from pipeline.agents import architecture_planner as ap
from pipeline.agents.schema_utils import make_validator


GI_MEDIEVAL = {
    "schema_version": "v4",
    "expanded_description": "A modest two-floor medieval cottage with a kitchen-living ground floor and bedrooms above. Timber framing.",
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
    "alexander_rationale": [],
}

FP0 = {
    "schema_version": "v4",
    "floor_index": 0,
    "layout_skill_id_used": "linear-corridor-layout",
    "rooms": [
        {"id": "kitchen-1", "role": "kitchen",
         "floor": 0, "aabb": [0, 0, 0, 4, 4, 5]},
        {"id": "living-1",  "role": "living_room",
         "floor": 0, "aabb": [4, 0, 0, 12, 4, 5]},
    ],
    "adjacency_graph": [
        {"from_room": "outside", "to_room": "kitchen-1", "kind": "door"},
        {"from_room": "kitchen-1", "to_room": "living-1", "kind": "door"},
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
         "floor": 1, "aabb": [0, 4, 0, 6, 8, 6]},
        {"id": "bedroom-2", "role": "bedroom",
         "floor": 1, "aabb": [6, 4, 0, 12, 8, 6]},
    ],
    "adjacency_graph": [
        {"from_room": "bedroom-1", "to_room": "bedroom-2", "kind": "opening"},
    ],
    "reserved_footprints": [
        {"x0": 9, "z0": 6, "x1": 12, "z1": 9, "kind": "stair",
         "template_id": "dogleg-staircase"},
    ],
}


def test_plan_architecture_v4_returns_valid_doc():
    doc = ap.plan_architecture_v4(GI_MEDIEVAL, [FP0, FP1])
    validator = make_validator("architecture_plan_v4.schema.json")
    errs = list(validator.iter_errors(doc))
    assert not errs, f"schema errors: {errs[:2]}"
    assert doc["schema_version"] == "v4"


def test_plan_v4_emits_one_fill_hollow_per_room():
    doc = ap.plan_architecture_v4(GI_MEDIEVAL, [FP0, FP1])
    fhs = [o for o in doc["ops"] if o["kind"] == "fill_hollow"
            and o["envelope_role"] == "wall"]
    assert len(fhs) == 4  # 2 rooms on floor 0 + 2 on floor 1


def test_plan_v4_emits_stair_void_for_upper_floor_only():
    doc = ap.plan_architecture_v4(GI_MEDIEVAL, [FP0, FP1])
    voids = [o for o in doc["ops"] if o["envelope_role"] == "stair_void"]
    # Only floor 1 (idx>0) gets a stair_void cut; floor 0 doesn't
    assert len(voids) == 1
    assert voids[0]["block"] == "minecraft:air"
    # The void is at y=4 (top of floor 0 = bottom of floor 1's slab)
    assert voids[0]["aabb"][1] == 4


def test_plan_v4_emits_slab_per_floor_plus_roof():
    doc = ap.plan_architecture_v4(GI_MEDIEVAL, [FP0, FP1])
    slabs = [o for o in doc["ops"] if o["envelope_role"] == "floor_slab"
              and o["kind"] == "rect"]
    roofs = [o for o in doc["ops"] if o["envelope_role"] == "roof"]
    # one slab rect per floor for a rectangular footprint
    assert len(slabs) == 2
    # a roof is present; pitched styles (gable/hip/spire) now emit several
    # layers as they rise above the walls, so it is no longer a single op.
    assert len(roofs) >= 1


def test_plan_v4_style_palette_populated():
    doc = ap.plan_architecture_v4(GI_MEDIEVAL, [FP0, FP1])
    assert doc["style_palette"]["primary"] == "minecraft:oak_planks"
    assert doc["style_palette"]["roof"] == "minecraft:dark_oak_planks"


def test_plan_v4_materials_usage_keyed_by_block():
    doc = ap.plan_architecture_v4(GI_MEDIEVAL, [FP0, FP1])
    mu = doc["materials_usage"]
    assert "minecraft:oak_planks" in mu
    assert mu["minecraft:oak_planks"]["palette_slot"] == "@primary"


def test_plan_v4_adjacency_per_floor_preserved():
    doc = ap.plan_architecture_v4(GI_MEDIEVAL, [FP0, FP1])
    agpf = doc["adjacency_graph_per_floor"]
    assert len(agpf) == 2
    assert len(agpf[0]) == 2
    assert len(agpf[1]) == 1


def test_wall_fittings_medieval_gable_residential():
    """Medieval + gable + residential triggers half-timber, stacked-stone,
    lintel-flat, gable-end-wall, eaves-overhang."""
    fittings = ap.select_wall_fittings(
        style="medieval",
        height_intent={"roof_style": "gable"},
        category="residential",
        floors_count=2,
        max_room_height=4,
    )
    ids = {f["fitting_id"] for f in fittings}
    assert "half-timber-wall" in ids
    assert "stacked-stone-corner" in ids
    assert "lintel-flat" in ids
    assert "gable-end-wall" in ids
    assert "eaves-overhang" in ids


def test_wall_fittings_modern_flat_drops_eaves():
    """Modern flat-roof building should NOT include eaves-overhang."""
    fittings = ap.select_wall_fittings(
        style="modern",
        height_intent={"roof_style": "flat"},
        category="residential",
        floors_count=2,
    )
    ids = {f["fitting_id"] for f in fittings}
    assert "flat-parapet" in ids
    assert "eaves-overhang" not in ids


def test_wall_fittings_fantasy_castle_picks_crenellated_drops_gable():
    """Crenellated-parapet excludes gable-end-wall (EXCLUSIONS)."""
    fittings = ap.select_wall_fittings(
        style="fantasy",
        height_intent={"roof_style": "gable"},
        category="castle",
        floors_count=3,
    )
    ids = {f["fitting_id"] for f in fittings}
    assert "crenellated-parapet" in ids
    assert "gable-end-wall" not in ids  # excluded


def test_wall_fittings_dormer_conditional_on_floors():
    """dormer-window requires ≥2 floors."""
    # fantasy doesn't list dormer-window; medieval doesn't either. Use
    # the conditional predicate directly.
    assert ap.CONDITIONAL_FITTINGS["dormer-window"](
        {"roof_style": "gable", "floors_count": 2}) is True
    assert ap.CONDITIONAL_FITTINGS["dormer-window"](
        {"roof_style": "gable", "floors_count": 1}) is False


def test_wall_fittings_deferred_flag_set():
    """All audit entries have deferred=True (voxel materialization deferred)."""
    fittings = ap.select_wall_fittings(
        style="medieval", height_intent={"roof_style": "gable"},
        category="residential", floors_count=1)
    assert all(f.get("deferred") is True for f in fittings)


def test_wall_fittings_japanese_minimal_set():
    fittings = ap.select_wall_fittings(
        style="japanese", height_intent={"roof_style": "hip"},
        category="residential", floors_count=1)
    ids = {f["fitting_id"] for f in fittings}
    # japanese maps to {eaves-overhang, plinth-base}; both should apply
    # (hip roof != flat → eaves OK; plinth has no condition).
    assert "eaves-overhang" in ids
    assert "plinth-base" in ids


def test_plan_v4_single_floor_no_stair_voids():
    """A 1-floor building should have no stair_void ops."""
    gi = dict(GI_MEDIEVAL)
    gi["floors"] = [gi["floors"][0]]
    fp = dict(FP0); fp["reserved_footprints"] = []  # no stairs
    doc = ap.plan_architecture_v4(gi, [fp])
    voids = [o for o in doc["ops"] if o["envelope_role"] == "stair_void"]
    assert voids == []


def test_v3_plan_architecture_still_works():
    """Sanity: the v3 plan_architecture is untouched."""
    assert callable(ap.plan_architecture)
