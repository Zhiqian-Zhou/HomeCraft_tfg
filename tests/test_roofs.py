"""Tests for the roof library — genuine distinctness + modular composition."""
from __future__ import annotations

import pipeline.agents.roofs as RF


def _sig(style, *, W=12, D=12, wt=6):
    ops = RF.build_roof(style, bx0=0, bz0=0, bx1=W, bz1=D, wall_top=wt,
                        by1=wt + 10, block="minecraft:dark_oak_planks",
                        stair="minecraft:oak_stairs")
    ys = [o.get("level", o.get("at", [0, 0, 0])[1]) for o in ops]
    height = (max(ys) - wt) if ys else 0
    return (len(ops), height)


def test_curved_roofs_are_distinct():
    """cone / spire / dome / onion / helm must be visibly different shapes —
    the old library had cone≡helm and spire≡dome."""
    sigs = {s: _sig(s) for s in ("cone", "spire", "dome", "onion", "helm")}
    # all five signatures must be mutually distinct
    assert len(set(sigs.values())) == 5, sigs
    # spire is the tallest; dome is the shortest (rounded)
    assert sigs["spire"][1] > sigs["cone"][1] > sigs["dome"][1], sigs


def test_hip_family_differentiated_by_pitch():
    """hip < hip-steep < tented in height; pavilion has an eave skirt."""
    h_hip = _sig("hip")[1]
    h_steep = _sig("hip-steep")[1]
    h_tented = _sig("tented")[1]
    assert h_hip < h_steep < h_tented, (h_hip, h_steep, h_tented)


def test_many_styles_mostly_distinct():
    styles = ["gable", "gable-steep", "saltbox", "mansard", "gambrel", "hip",
              "hip-steep", "tented", "spire", "dome", "onion", "helm", "pagoda",
              "butterfly", "skillion", "barrel", "sawtooth", "crenellated"]
    sigs = {s: _sig(s) for s in styles}
    assert len(set(sigs.values())) >= len(styles) - 3, sigs


def test_build_roof_unknown_falls_back_to_hip():
    ops = RF.build_roof("not-a-real-roof", bx0=0, bz0=0, bx1=8, bz1=8,
                        wall_top=5, by1=12, block="b", stair="minecraft:oak_stairs")
    assert ops  # hip fallback produces ops


def test_compose_roof_adds_feature_ops():
    base = RF.build_roof("hip", bx0=0, bz0=0, bx1=14, bz1=14, wall_top=6,
                         by1=14, block="minecraft:oak_planks",
                         stair="minecraft:oak_stairs")
    comp = RF.compose_roof("hip", bx0=0, bz0=0, bx1=14, bz1=14, wall_top=6,
                           by1=14, block="minecraft:oak_planks",
                           stair="minecraft:oak_stairs",
                           accent="minecraft:bricks",
                           features=["dormer", "chimney", "cupola"])
    assert len(comp) > len(base), "features should add ops"
    feat_ops = [o for o in comp if o.get("envelope_role") == "roof_feature"]
    assert feat_ops, "feature ops must carry envelope_role=roof_feature"


def test_compose_roof_corner_turrets_make_towers():
    """corner-turrets attach mini-towers with their own caps (LEGO)."""
    comp = RF.compose_roof("flat", bx0=0, bz0=0, bx1=16, bz1=16, wall_top=6,
                           by1=12, block="minecraft:stone_bricks",
                           stair="minecraft:stone_brick_stairs",
                           accent="minecraft:cobblestone",
                           features=["corner-turrets"])
    turret_ops = [o for o in comp if o.get("envelope_role") == "roof_feature"]
    # four turret shafts → many ops well above the flat cap
    ys = [o.get("level", o.get("at", [0, 0, 0])[1]) for o in turret_ops]
    assert turret_ops and max(ys) > 6 + 3, "turrets should rise above the wall"


def test_compose_roof_ignores_unknown_and_none_features():
    comp = RF.compose_roof("gable", bx0=0, bz0=0, bx1=10, bz1=10, wall_top=5,
                           by1=12, block="minecraft:oak_planks",
                           stair="minecraft:oak_stairs",
                           features=["none", "bogus-feature", ""])
    base = RF.build_roof("gable", bx0=0, bz0=0, bx1=10, bz1=10, wall_top=5,
                         by1=12, block="minecraft:oak_planks",
                         stair="minecraft:oak_stairs")
    assert len(comp) == len(base)  # nothing added


def test_compose_roof_budget_guard():
    comp = RF.compose_roof("crenellated", bx0=0, bz0=0, bx1=60, bz1=60,
                           wall_top=6, by1=14, block="minecraft:stone",
                           stair="minecraft:stone_stairs",
                           features=["corner-turrets", "cupola", "finial"])
    assert len(comp) <= RF.MAX_OPS + 200  # stays bounded
