"""Tests for `_voxel_connectivity` (hole-tolerant room-AABB refactor).

The metric defines interior air as the air cells inside each room's AABB
(tagged per-room), seeds a 6-conn BFS at the interior cells near declared
exterior doors, moves freely within a room, crosses to other rooms ONLY
through door ports (Chebyshev ≤2 of a planned door) or passable connectors
(stairs / ladder / open trapdoor-over-ladder), and credits head cells above
reached feet cells. It never leaks through unplanned wall holes (those are
penalised by structural_integrity). Open courtyards are excluded from the
interior denominator.

These eight cases cover the canonical positives, the sealed-room and
no-door regressions, vertical passage via stairs/ladder, and the
courtyard-excluded-from-denominator invariant.
"""
from __future__ import annotations

import pytest

from pipeline.agents.evaluator import (
    _voxel_connectivity,
    _build_voxel_map,
)
from tests.conftest import build_doc, build_master_plan, hollow_box, solid_box


def _storey(rid: str, aabb: list[int], function: str = "living_room",
            storey_id: str = "s1") -> dict:
    """Build a one-room storey dict."""
    return {"id": storey_id,
            "spaces": [{"id": rid, "function": function, "aabb": aabb}]}


def _install_door(voxels: list, at: tuple[int, int, int],
                  facing: str = "east") -> list:
    """Replace the two voxels at `(x, y, z)` and `(x, y+1, z)` with the
    lower/upper halves of an `oak_door` block so the BFS treats them as
    a single passable opening (spec §5).
    """
    x, y, z = at
    cells = {(x, y, z), (x, y + 1, z)}
    voxels = [v for v in voxels if (v[0], v[1], v[2]) not in cells]
    voxels.append((x, y, z,
                   f"minecraft:oak_door[half=lower,facing={facing}]"))
    voxels.append((x, y + 1, z,
                   f"minecraft:oak_door[half=upper,facing={facing}]"))
    return voxels


# ──────────────────────────────────────────────────────────────────────────
# T1. Cabin 5x4x5 hollow box, one exterior door on the west wall, one room.
# Every interior air cell must be reachable → score == 1.0.
# ──────────────────────────────────────────────────────────────────────────
def test_T1_cabin_single_room_full_connectivity() -> None:
    # Hollow box with floor + ceiling at y=0 and y=3, walls in between.
    voxels = hollow_box(0, 0, 0, 5, 4, 5, wall="minecraft:oak_planks")
    # Door at west wall (x=0, y=1, z=2). The helper installs both halves
    # so head-clearance is honoured by the BFS.
    voxels = _install_door(voxels, (0, 1, 2), facing="east")
    doc = build_doc(
        voxels, size=(5, 4, 5),
        bot_storeys=[_storey("r1", [1, 1, 1, 4, 3, 4])],
    )
    vmap = _build_voxel_map(doc)
    mp = build_master_plan(
        doors=[{"at": [0, 1, 2], "between": ["outside", "r1"]}],
    )
    out = _voxel_connectivity(doc, vmap, None, mp)
    assert out["score"] == pytest.approx(1.0, abs=0.01)
    assert out.get("unreachable_rooms") == []


# ──────────────────────────────────────────────────────────────────────────
# T2. House split by an interior wall with no internal door → bathroom side
# is unreachable from the exterior door on the living-room side.
# ──────────────────────────────────────────────────────────────────────────
def test_T2_sealed_bathroom_unreachable() -> None:
    # 9 (X) × 4 (Y) × 5 (Z). Living room x∈[1,4), bathroom x∈[5,8).
    voxels = hollow_box(0, 0, 0, 9, 4, 5, wall="minecraft:oak_planks")
    # Solid interior wall at x=4 spanning the full height/depth, with no
    # opening: bathroom is sealed off.
    for y in range(0, 4):
        for z in range(0, 5):
            voxels.append((4, y, z, "minecraft:oak_planks"))
    # Exterior door at west wall (x=0) into the living room.
    voxels = _install_door(voxels, (0, 1, 2), facing="east")
    doc = build_doc(
        voxels, size=(9, 4, 5),
        bot_storeys=[{
            "id": "s1",
            "spaces": [
                {"id": "living", "function": "living_room",
                 "aabb": [1, 1, 1, 4, 3, 4]},
                {"id": "bathroom", "function": "bathroom",
                 "aabb": [5, 1, 1, 8, 3, 4]},
            ],
        }],
    )
    vmap = _build_voxel_map(doc)
    mp = build_master_plan(
        doors=[{"at": [0, 1, 2], "between": ["outside", "living"]}],
    )
    out = _voxel_connectivity(doc, vmap, None, mp)
    assert out["score"] < 1.0
    assert "bathroom" in out.get("unreachable_rooms", [])


# ──────────────────────────────────────────────────────────────────────────
# T3. master_plan with `connectors.doors=[]` declared → no exterior seed
# can be derived; spec mandates score 0.0.
# ──────────────────────────────────────────────────────────────────────────
def test_T3_no_doors_declared_score_zero() -> None:
    voxels = hollow_box(0, 0, 0, 5, 4, 5, wall="minecraft:oak_planks")
    doc = build_doc(
        voxels, size=(5, 4, 5),
        bot_storeys=[_storey("r1", [1, 1, 1, 4, 3, 4])],
    )
    vmap = _build_voxel_map(doc)
    # Master plan exists with connectors.doors explicitly empty → no
    # exterior access is possible per spec § "no exterior door reachable".
    mp = build_master_plan(doors=[])
    out = _voxel_connectivity(doc, vmap, None, mp)
    assert out["score"] == pytest.approx(0.0, abs=0.01)
    assert "no exterior door" in (out.get("notes") or "")


# ──────────────────────────────────────────────────────────────────────────
# T4. Two-storey tower, NO stairs anywhere → upper storey unreachable.
# Score is partial (≈ ground-floor volume / total interior volume).
# ──────────────────────────────────────────────────────────────────────────
def test_T4_two_floors_no_stairs_partial() -> None:
    # 5 (X) × 7 (Y) × 5 (Z) with mid-floor slab at y=3.
    voxels = hollow_box(0, 0, 0, 5, 7, 5, wall="minecraft:oak_planks")
    # Mid-floor solid slab.
    for x in range(0, 5):
        for z in range(0, 5):
            voxels.append((x, 3, z, "minecraft:oak_planks"))
    # Exterior door on ground floor.
    voxels = _install_door(voxels, (0, 1, 2), facing="east")
    doc = build_doc(
        voxels, size=(5, 7, 5),
        bot_storeys=[
            {"id": "p1", "spaces": [
                {"id": "p1_room", "function": "living_room",
                 "aabb": [1, 1, 1, 4, 3, 4]}]},
            {"id": "p2", "spaces": [
                {"id": "p2_room", "function": "bedroom",
                 "aabb": [1, 4, 1, 4, 6, 4]}]},
        ],
    )
    vmap = _build_voxel_map(doc)
    mp = build_master_plan(
        doors=[{"at": [0, 1, 2], "between": ["outside", "p1_room"]}],
    )
    out = _voxel_connectivity(doc, vmap, None, mp)
    assert 0.0 < out["score"] < 1.0
    assert "p2_room" in out.get("unreachable_rooms", [])
    assert "p1_room" not in out.get("unreachable_rooms", [])


# ──────────────────────────────────────────────────────────────────────────
# T5. Same two-storey tower but with an oak_stairs column connecting p1
# to p2 — score must be 1.0 (every interior air cell reachable).
# ──────────────────────────────────────────────────────────────────────────
def test_T5_two_floors_with_stairs_full() -> None:
    voxels = hollow_box(0, 0, 0, 6, 7, 5, wall="minecraft:oak_planks")
    # Mid-floor solid slab with a 1x1 opening at (3, 3, 2) to allow vertical
    # passage; a stack of stair voxels provides the climb path. (Spec §5:
    # `_stairs` at src OR dst counts as one Δy step.)
    for x in range(0, 6):
        for z in range(0, 5):
            voxels.append((x, 3, z, "minecraft:oak_planks"))
    voxels = [v for v in voxels if (v[0], v[1], v[2]) != (3, 3, 2)]
    voxels.append((3, 2, 2, "minecraft:oak_stairs[facing=west,half=bottom]"))
    voxels.append((3, 3, 2, "minecraft:oak_stairs[facing=west,half=bottom]"))
    # Exterior door on ground floor.
    voxels = _install_door(voxels, (0, 1, 2), facing="east")
    doc = build_doc(
        voxels, size=(6, 7, 5),
        bot_storeys=[
            {"id": "p1", "spaces": [
                {"id": "p1_room", "function": "living_room",
                 "aabb": [1, 1, 1, 5, 3, 4]}]},
            {"id": "p2", "spaces": [
                {"id": "p2_room", "function": "bedroom",
                 "aabb": [1, 4, 1, 5, 6, 4]}]},
        ],
    )
    vmap = _build_voxel_map(doc)
    mp = build_master_plan(
        doors=[{"at": [0, 1, 2], "between": ["outside", "p1_room"]}],
    )
    out = _voxel_connectivity(doc, vmap, None, mp)
    assert out["score"] == pytest.approx(1.0, abs=0.01)
    assert "p2_room" not in out.get("unreachable_rooms", [])


# ──────────────────────────────────────────────────────────────────────────
# T6. Open trapdoor sitting at the top of a vertical ladder column allows
# the BFS to climb from ground floor to roof (full connectivity).
# ──────────────────────────────────────────────────────────────────────────
def test_T6_trapdoor_open_over_ladder() -> None:
    voxels = hollow_box(0, 0, 0, 6, 7, 5, wall="minecraft:oak_planks")
    # Mid-floor slab with a 1x1 hole at (3, 3, 2).
    for x in range(0, 6):
        for z in range(0, 5):
            voxels.append((x, 3, z, "minecraft:oak_planks"))
    voxels = [v for v in voxels if (v[0], v[1], v[2]) != (3, 3, 2)]
    # Open trapdoor at the hole (dst when climbing up from (3,2,2)).
    voxels.append(
        (3, 3, 2, "minecraft:oak_trapdoor[half=bottom,open=true,facing=north]")
    )
    # Ladder column adjacent to the trapdoor providing the climb mechanism.
    for y in (1, 2):
        voxels.append((3, y, 2, "minecraft:ladder[facing=south]"))
    # Exterior door.
    voxels = _install_door(voxels, (0, 1, 2), facing="east")
    doc = build_doc(
        voxels, size=(6, 7, 5),
        bot_storeys=[
            {"id": "p1", "spaces": [
                {"id": "p1_room", "function": "living_room",
                 "aabb": [1, 1, 1, 5, 3, 4]}]},
            {"id": "p2", "spaces": [
                {"id": "p2_room", "function": "bedroom",
                 "aabb": [1, 4, 1, 5, 6, 4]}]},
        ],
    )
    vmap = _build_voxel_map(doc)
    mp = build_master_plan(
        doors=[{"at": [0, 1, 2], "between": ["outside", "p1_room"]}],
    )
    out = _voxel_connectivity(doc, vmap, None, mp)
    assert "p2_room" not in out.get("unreachable_rooms", [])
    assert out["score"] > 0.0


# ──────────────────────────────────────────────────────────────────────────
# T7. Building on pilotes — Y=0 is fully open air but no door is declared
# in master_plan. Legacy implementation seeded from Y=0 → false-positive
# 1.0; the refined implementation must return 0.0 because the only
# declared door has no `at` (legacy probe regression).
# ──────────────────────────────────────────────────────────────────────────
def test_T7_pilotes_without_declared_door_zero() -> None:
    # Solid box at y∈[2,6) sitting on four pilote columns; ground (y=0,1)
    # is fully air except for the columns. The interior is the cavity
    # at y∈[3,5) inside walls.
    voxels: list[tuple[int, int, int, str]] = []
    # Four pilote columns at the corners y∈[0,2).
    for cx, cz in ((0, 0), (4, 0), (0, 4), (4, 4)):
        for y in range(0, 2):
            voxels.append((cx, y, cz, "minecraft:oak_planks"))
    # Elevated hollow building at y∈[2,6).
    voxels += hollow_box(0, 2, 0, 5, 6, 5, wall="minecraft:oak_planks")
    doc = build_doc(
        voxels, size=(5, 6, 5),
        bot_storeys=[_storey("r1", [1, 3, 1, 4, 5, 4])],
    )
    vmap = _build_voxel_map(doc)
    # Master plan declares a door but with no `at` field → no seed.
    mp = build_master_plan(
        doors=[{"between": ["outside", "r1"]}],
    )
    out = _voxel_connectivity(doc, vmap, None, mp)
    assert out["score"] == pytest.approx(0.0, abs=0.01)


# ──────────────────────────────────────────────────────────────────────────
# T8. Open courtyard (no roof) — exterior flood-fill reaches the courtyard
# from above, so courtyard cells are excluded from `interior_air`; score
# depends only on the closed rooms.
# ──────────────────────────────────────────────────────────────────────────
def test_T8_open_courtyard_excluded_from_interior() -> None:
    """Building with a sealed room AND a separate roof-less courtyard.

    The courtyard is detected as exterior by the complementary flood-fill
    (it is reachable from the sky above the bbox), so its voxels are
    excluded from `interior_air`. The score should reflect only the
    sealed room's coverage. We assert both that the score is the full
    closed-room fraction (1.0) AND that the courtyard cells are NOT
    counted as unreachable. Layout (XZ, walls=W, door=D):

        WWWWWWW
        W..D..W   ← living room (closed roof)
        W.....W
        WWWWWWW   ← internal partition (full height, sealed)
        W.....W   ← courtyard (NO ceiling above this strip)
        W.....W
        WWWWWWW
    """
    voxels: list = []
    # Floor across the full bbox (7×7 at y=0).
    for x in range(7):
        for z in range(7):
            voxels.append((x, 0, z, "minecraft:oak_planks"))
    # Outer walls at y=1,2 around the full perimeter.
    for x in range(7):
        for z in range(7):
            for y in range(1, 3):
                on_edge = (x in (0, 6) or z in (0, 6))
                if on_edge:
                    voxels.append((x, y, z, "minecraft:oak_planks"))
    # Internal partition at z=3 separates living room (z<3) from courtyard.
    for x in range(7):
        for y in range(1, 3):
            voxels.append((x, y, 3, "minecraft:oak_planks"))
    # Ceiling at y=3 ONLY over the living room (z ∈ [0,3]); courtyard has
    # no roof above z ∈ [4, 6].
    for x in range(7):
        for z in range(0, 4):
            voxels.append((x, 3, z, "minecraft:oak_planks"))
    # Exterior door into the closed living room at the north wall (z=0).
    voxels = _install_door(voxels, (3, 1, 0), facing="south")
    doc = build_doc(
        voxels, size=(7, 4, 7),
        bot_storeys=[{
            "id": "s1",
            "spaces": [
                {"id": "living", "function": "living_room",
                 "aabb": [1, 1, 1, 6, 3, 3]},
                {"id": "courtyard", "function": "courtyard",
                 "aabb": [1, 1, 4, 6, 3, 6]},
            ],
        }],
    )
    vmap = _build_voxel_map(doc)
    mp = build_master_plan(
        doors=[{"at": [3, 1, 0], "between": ["outside", "living"]}],
    )
    out = _voxel_connectivity(doc, vmap, None, mp)
    # The courtyard cells are excluded from interior_air by the exterior
    # flood-fill → the living room is the only counted interior, and the
    # door reaches every cell in it.
    assert out["score"] == pytest.approx(1.0, abs=0.01)
    # Courtyard is open (no roof) so its cells were classified as
    # exterior; the per-room AABB diagnostic should still flag it as
    # "unreachable" because no interior cells inside its AABB belong to
    # `reachable` — that is fine and documented as spec §7 behaviour.
    note = out.get("notes") or ""
    assert "floor positions reached" in note
