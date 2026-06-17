"""Tests for the `_main_entrance` Alexander pattern metric (APL #110).

The implementation determines the building's PRIMARY facades (the long
walls; all four if the footprint is square), reports the actual wall the
door sits on (north/south/east/west), counts decorative markers within an
L∞ radius around the door, and returns the max-score among all `outside`
doors. Scoring: primary facade + markers → 1.0; primary, no markers → 0.7;
secondary (short) wall + markers → 0.6, else 0.4; door not near any wall →
0.3. There is no arbitrary geometric "back" penalty — prominence is judged
by markers, since which long wall is the true front cannot be known from
geometry alone. Tests use the shared conftest helpers.
"""
from __future__ import annotations

from tests.conftest import build_doc, solid_box, build_master_plan
from pipeline.agents.evaluator import _main_entrance, _build_voxel_map


def _doc_for(voxels):
    """Wrap voxel list in a synthetic ReferenceBuilding doc + voxel map."""
    doc = build_doc(voxels)
    vmap = _build_voxel_map(doc)
    return doc, vmap


def _plan(doors):
    """Build a master_plan with the given list of (at, between) door tuples."""
    return build_master_plan(
        doors=[{"at": list(at), "between": bw} for at, bw in doors]
    )


def test_front_with_markers():
    """Door on a primary (long, south) wall with a lantern within R → 1.0."""
    voxels = solid_box(0, 0, 0, 7, 3, 5, "minecraft:stone")
    # Add a lantern 1 voxel south of the door, well within R.
    voxels.append((3, 1, 5, "minecraft:lantern"))
    doc, vmap = _doc_for(voxels)
    plan = _plan([((3, 1, 4), ["outside", "r1"])])
    r = _main_entrance(doc, vmap, plan)
    assert r["score"] == 1.0
    assert r["door_wall"] == "south"
    assert r["on_primary_facade"] is True
    assert r["n_markers_nearby"] >= 1


def test_front_without_markers():
    """Door on a primary wall but no markers nearby → 0.7."""
    voxels = solid_box(0, 0, 0, 7, 3, 5, "minecraft:stone")
    doc, vmap = _doc_for(voxels)
    plan = _plan([((3, 1, 4), ["outside", "r1"])])
    r = _main_entrance(doc, vmap, plan)
    assert r["score"] == 0.7
    assert r["door_wall"] == "south"
    assert r["n_markers_nearby"] == 0


def test_lateral_door():
    """Door on a short (secondary) wall, no markers → 0.4."""
    voxels = solid_box(0, 0, 0, 10, 3, 6, "minecraft:stone")
    doc, vmap = _doc_for(voxels)
    plan = _plan([((9, 1, 3), ["outside", "r1"])])  # east (short) wall
    r = _main_entrance(doc, vmap, plan)
    assert r["score"] == 0.4
    assert r["door_wall"] == "east"
    assert r["on_primary_facade"] is False


def test_secondary_wall_with_markers():
    """Door on a short wall WITH markers → 0.6 (more than bare 0.4)."""
    voxels = solid_box(0, 0, 0, 10, 3, 6, "minecraft:stone")
    voxels.append((10, 1, 3, "minecraft:lantern"))  # marker east of the door
    doc, vmap = _doc_for(voxels)
    plan = _plan([((9, 1, 3), ["outside", "r1"])])
    r = _main_entrance(doc, vmap, plan)
    assert r["score"] == 0.6
    assert r["door_wall"] == "east"


def test_opposite_long_wall_still_primary():
    """A door on the wall opposite the marked one is STILL a primary facade
    (no arbitrary geometric back-penalty): no markers → 0.7."""
    voxels = solid_box(0, 0, 0, 7, 3, 5, "minecraft:stone")
    doc, vmap = _doc_for(voxels)
    plan = _plan([((3, 1, 0), ["outside", "r1"])])
    r = _main_entrance(doc, vmap, plan)
    assert r["score"] == 0.7
    assert r["door_wall"] == "north"


def test_multi_door_picks_max():
    """With two primary-wall doors, the metric returns the higher score."""
    voxels = solid_box(0, 0, 0, 7, 3, 5, "minecraft:stone")
    voxels.append((3, 1, 5, "minecraft:lantern"))  # marker by the south door
    doc, vmap = _doc_for(voxels)
    plan = _plan([
        ((3, 1, 0), ["outside", "r1"]),  # north, no markers → 0.7
        ((3, 1, 4), ["outside", "r2"]),  # south, marked → 1.0
    ])
    r = _main_entrance(doc, vmap, plan)
    assert r["score"] == 1.0
    assert r["door_wall"] == "south"


def test_square_footprint_all_primary():
    """Square footprint → all facades primary; note says so, door scores 0.7."""
    voxels = solid_box(0, 0, 0, 6, 3, 6, "minecraft:stone")
    doc, vmap = _doc_for(voxels)
    plan = _plan([((3, 1, 5), ["outside", "r1"])])
    r = _main_entrance(doc, vmap, plan)
    assert r["door_wall"] == "south"
    assert r["on_primary_facade"] is True
    assert "square" in r["notes"]


def test_translated_building():
    """Bounding box not at the origin → footprint is still computed correctly."""
    voxels = solid_box(100, 0, 200, 107, 3, 205, "minecraft:stone")
    doc, vmap = _doc_for(voxels)
    plan = _plan([((103, 1, 204), ["outside", "r1"])])
    r = _main_entrance(doc, vmap, plan)
    assert r["door_wall"] == "south"
    assert r["on_primary_facade"] is True


def test_no_outside_door_returns_none():
    """Doors between two interior rooms (no 'outside') → score None."""
    voxels = solid_box(0, 0, 0, 7, 3, 5, "minecraft:stone")
    doc, vmap = _doc_for(voxels)
    plan = _plan([((3, 1, 4), ["r1", "r2"])])  # purely interior door
    r = _main_entrance(doc, vmap, plan)
    assert r["score"] is None


def test_stair_facing_door_counts_as_marker():
    """A `_stairs` block whose `facing` points at the door counts as a marker."""
    voxels = solid_box(0, 0, 0, 7, 3, 5, "minecraft:stone")
    # Stair sits just south of the door at z=5, facing=north (toward door)
    voxels.append((3, 1, 5, "minecraft:oak_stairs[facing=north]"))
    doc, vmap = _doc_for(voxels)
    plan = _plan([((3, 1, 4), ["outside", "r1"])])
    r = _main_entrance(doc, vmap, plan)
    assert r["n_markers_nearby"] >= 1
    assert r["score"] == 1.0


def test_stair_facing_away_ignored():
    """A `_stairs` block facing away from the door must NOT count."""
    voxels = solid_box(0, 0, 0, 7, 3, 5, "minecraft:stone")
    voxels.append((3, 1, 5, "minecraft:oak_stairs[facing=south]"))  # away from door
    doc, vmap = _doc_for(voxels)
    plan = _plan([((3, 1, 4), ["outside", "r1"])])
    r = _main_entrance(doc, vmap, plan)
    assert r["n_markers_nearby"] == 0
    assert r["score"] == 0.7
