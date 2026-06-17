"""Tests for `_structural_integrity` (Pipeline v2 robustness refactor).

Covers the three independent signals: (a) connected-components / floating
clusters, (b) gravity check for falling blocks (incl. scaffolding chain),
(c) flood-fill wall holes vs master_plan.connectors.
"""
from __future__ import annotations

import pytest

from pipeline.agents.evaluator import _structural_integrity, _build_voxel_map
from tests.conftest import build_doc, build_master_plan, solid_box, hollow_box


# ──────────────────────────────────────────────────────────────────────────
# 1. Solid 5x5x5 with one planned door → perfect score, no violations.
# ──────────────────────────────────────────────────────────────────────────
def test_solid_5x5x5_stone_no_holes() -> None:
    voxels = solid_box(0, 0, 0, 5, 5, 5, block="minecraft:stone")
    doc = build_doc(voxels, size=(5, 5, 5))
    vmap = _build_voxel_map(doc)
    mp = build_master_plan(doors=[{"at": [0, 1, 2], "between": ["outside", "r1"]}])
    out = _structural_integrity(doc, vmap, mp)
    assert out["score"] == 1.0
    assert out["violations"] == []


# ──────────────────────────────────────────────────────────────────────────
# 2. Main block + isolated 3-stone cluster → floats detected (regression vs v1).
# ──────────────────────────────────────────────────────────────────────────
def test_floating_cluster_of_three() -> None:
    voxels = solid_box(0, 0, 0, 5, 5, 5, block="minecraft:stone")
    # Add a 3-block stone cluster floating away (X-line so they are 6-conn to each other)
    voxels += [
        (10, 8, 10, "minecraft:stone"),
        (11, 8, 10, "minecraft:stone"),
        (12, 8, 10, "minecraft:stone"),
    ]
    doc = build_doc(voxels, size=(15, 10, 15))
    vmap = _build_voxel_map(doc)
    out = _structural_integrity(doc, vmap, None)
    assert "float=3" in out["notes"]
    assert out["score"] < 1.0
    assert len(out["violations"]) >= 3


# ──────────────────────────────────────────────────────────────────────────
# 3. Sand pyramid suspended over a single base block — gravity violations.
# ──────────────────────────────────────────────────────────────────────────
def test_unsupported_sand_pyramid() -> None:
    voxels = [
        # Stone foundation column at (0,0,0) only
        (0, 0, 0, "minecraft:stone"),
        # Four sand blocks at y=3 with NO solid directly under them
        (5, 3, 5, "minecraft:sand"),
        (5, 3, 6, "minecraft:sand"),
        (6, 3, 5, "minecraft:sand"),
        (6, 3, 6, "minecraft:sand"),
    ]
    doc = build_doc(voxels, size=(10, 10, 10))
    vmap = _build_voxel_map(doc)
    out = _structural_integrity(doc, vmap, None)
    assert "grav=4" in out["notes"]
    assert out["score"] < 1.0


# ──────────────────────────────────────────────────────────────────────────
# 4. Scaffolding chain with column on ground → lateral BFS support.
# ──────────────────────────────────────────────────────────────────────────
def test_scaffolding_lateral_support_ok() -> None:
    # Ground stone at (0,0,0), a scaffolding column anchored on it,
    # plus a horizontal chain at y=3 reaching out laterally ≤6.
    voxels = [(0, 0, 0, "minecraft:stone")]
    # Vertical scaffolding column at (0, 1..3, 0): each one supports the next via y-1.
    for y in range(1, 4):
        voxels.append((0, y, 0, "minecraft:scaffolding"))
    # Lateral chain at y=3: extend out 5 blocks; each laterally reaches a scaffolding
    # whose column has support at the ground.
    for x in range(1, 6):
        voxels.append((x, 3, 0, "minecraft:scaffolding"))
    doc = build_doc(voxels, size=(8, 5, 5))
    vmap = _build_voxel_map(doc)
    out = _structural_integrity(doc, vmap, None)
    assert "grav=0" in out["notes"]


# ──────────────────────────────────────────────────────────────────────────
# 5. Hollow box with one unplanned wall hole → hole violation registered.
# ──────────────────────────────────────────────────────────────────────────
def test_wall_hole_unplanned_penalized() -> None:
    voxels = hollow_box(0, 0, 0, 5, 5, 5, wall="minecraft:stone")
    # Remove one wall block to introduce a hole at (0, 2, 2).
    voxels = [v for v in voxels if (v[0], v[1], v[2]) != (0, 2, 2)]
    doc = build_doc(voxels, size=(5, 5, 5))
    vmap = _build_voxel_map(doc)
    # Door declared on a *different* wall (not at the hole).
    mp = build_master_plan(doors=[{"at": [4, 1, 2], "between": ["outside", "r1"]}])
    out = _structural_integrity(doc, vmap, mp)
    assert "holes=" in out["notes"]
    nh = int(out["notes"].split("holes=")[1].split()[0])
    assert nh >= 1
    assert out["score"] < 1.0


# ──────────────────────────────────────────────────────────────────────────
# 6. Same hole, but declared as a planned door at that coord → no hole.
# ──────────────────────────────────────────────────────────────────────────
def test_wall_hole_matches_door_connector() -> None:
    voxels = hollow_box(0, 0, 0, 5, 5, 5, wall="minecraft:stone")
    voxels = [v for v in voxels if (v[0], v[1], v[2]) != (0, 2, 2)]
    doc = build_doc(voxels, size=(5, 5, 5))
    vmap = _build_voxel_map(doc)
    mp = build_master_plan(doors=[{"at": [0, 2, 2], "between": ["outside", "r1"]}])
    out = _structural_integrity(doc, vmap, mp)
    assert "holes=0" in out["notes"]


# ──────────────────────────────────────────────────────────────────────────
# 7. Combined violations: 1 float + 1 gravity + 1 hole.
# ──────────────────────────────────────────────────────────────────────────
def test_mixed_violations_combined() -> None:
    voxels = hollow_box(0, 0, 0, 5, 5, 5, wall="minecraft:stone")
    # Remove one wall block (unplanned hole at (0, 2, 2))
    voxels = [v for v in voxels if (v[0], v[1], v[2]) != (0, 2, 2)]
    # Add a floating single stone far away (cluster of 1).
    voxels.append((10, 8, 10, "minecraft:stone"))
    # Add a sand block suspended in mid-air (no solid below).
    voxels.append((10, 5, 12, "minecraft:sand"))
    doc = build_doc(voxels, size=(15, 10, 15))
    vmap = _build_voxel_map(doc)
    mp = build_master_plan(doors=[{"at": [4, 1, 2], "between": ["outside", "r1"]}])
    out = _structural_integrity(doc, vmap, mp)
    # Float count includes the lone stone AND the lone sand (both off-cluster).
    # We assert each signal fired at least once and combine penalties bring score < 1.
    notes = out["notes"]
    assert "float=" in notes and "grav=" in notes and "holes=" in notes
    nf = int(notes.split("float=")[1].split()[0])
    ng = int(notes.split("grav=")[1].split()[0])
    nh = int(notes.split("holes=")[1].split()[0])
    assert nf >= 1
    assert ng >= 1
    assert nh >= 1
    assert out["score"] < 1.0
