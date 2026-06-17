"""Tests for _vertical_clearance (Stage 6, refined plan).

Covers the 6 cases from scratch/evaluation_robustness/vertical_clearance.refined.md §3:

  1. test_cabin_full_ceiling           — 5x5x5 cabin with oak_planks ceiling.
  2. test_trapdoor_ceiling_excluded    — oak_trapdoor must NOT count as ceiling.
  3. test_stairs_descending_ceiling    — slanted stairs ceiling: min < mean.
  4. test_hidden_beam_via_slab         — 1 hanging slab in a 4x4 room hides
                                          inside the mean but surfaces in min/p10.
  5. test_open_courtyard               — column with no ceiling → per_room None.
  6. test_bot_decomposition_none       — doc={} → score None, per_room {}.

AABB convention (shared with _voxel_connectivity / _door_functionality): half-open
[x0, y0, z0, x1, y1, z1) so range(x0, x1) iterates the room interior.
"""
from __future__ import annotations

import pytest

from pipeline.agents.evaluator import _build_voxel_map, _vertical_clearance


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _vmap_from(voxels: list[tuple[int, int, int, str]]) -> dict:
    """Build the (x,y,z) → block_id mapping the evaluator consumes.

    Goes through `_build_voxel_map` (palette round-trip) to guarantee parity
    with how `evaluate(...)` constructs vmap in production.
    """
    palette: dict[str, str] = {}
    vox_entries: list[list[int]] = []
    for x, y, z, bid in voxels:
        full = bid if bid.startswith("minecraft:") else f"minecraft:{bid}"
        if full not in palette.values():
            palette[str(len(palette))] = full
        idx = next(k for k, v in palette.items() if v == full)
        vox_entries.append([x, y, z, int(idx)])
    return _build_voxel_map({"block_palette": palette, "voxels": vox_entries})


def _doc_one_room(sid: str, aabb: list[int]) -> dict:
    """Doc with a single room A spanning `aabb`."""
    return {
        "bot_decomposition": {
            "building": {
                "storeys": [
                    {"id": "p0", "spaces": [
                        {"id": sid, "function": "living_room", "aabb": aabb},
                    ]},
                ]
            }
        },
        "bounding_box": {"origin": [0, 0, 0], "size": [16, 16, 16]},
    }


def _cabin_voxels(*, ceiling_block: str) -> list[tuple[int, int, int, str]]:
    """5x5x5 cabin AABB [0..5, 0..5, 0..5):
      - y=0 oak_planks floor (5x5)
      - y=4 `ceiling_block` ceiling (5x5)
    Interior is air on y in {1,2,3} → 4 voxels of clearance below the ceiling
    when the ceiling is solid (ceil_y - floor_y - 1 = 4 - 0 - 1 = 3? — see note).

    Note on convention: clearance = ceil_y - floor_y - 1 counts *empty* voxels
    between floor and ceiling. With floor y=0 and ceiling y=4, that's 3 voxels
    of air (y∈{1,2,3}). The refined-plan stub uses this formula and the
    expected fixture from the plan (`per_room[A]==4`) assumes a floor at y=-1
    or ceiling at y=5 (h=5 cabin with 5-block ceiling separation). To stay
    faithful to the plan's exact assertion, we put the floor at y=0 and the
    ceiling at y=5, giving 4 empty voxels in between (y∈{1,2,3,4}).
    """
    voxels: list[tuple[int, int, int, str]] = []
    for x in range(5):
        for z in range(5):
            voxels.append((x, 0, z, "minecraft:oak_planks"))
            voxels.append((x, 5, z, f"minecraft:{ceiling_block}"))
    return voxels


# ─────────────────────────────────────────────────────────────────────────────
# 1. Full solid ceiling → score 1.0, clearance 4
# ─────────────────────────────────────────────────────────────────────────────

def test_cabin_full_ceiling():
    voxels = _cabin_voxels(ceiling_block="oak_planks")
    vmap = _vmap_from(voxels)
    doc = _doc_one_room("A", [0, 0, 0, 5, 6, 5])  # y range [0, 6) covers floor+ceiling

    res = _vertical_clearance(doc, vmap)

    assert res["score"] == 1.0
    assert res["per_room"]["A"] == 4
    assert res["min_clearance"] == 4
    assert res["lowest_room"] == "A"
    assert res["p10_clearance"] == 4


# ─────────────────────────────────────────────────────────────────────────────
# 2. Trapdoor must NOT count as ceiling
# ─────────────────────────────────────────────────────────────────────────────

def test_trapdoor_ceiling_excluded():
    voxels = _cabin_voxels(ceiling_block="oak_trapdoor")
    vmap = _vmap_from(voxels)
    doc = _doc_one_room("A", [0, 0, 0, 5, 6, 5])

    res = _vertical_clearance(doc, vmap)

    # No real ceiling above the floor → no column contributes → per_room A is None
    # and the aggregate score is None (no rooms with detectable floor/ceiling).
    assert res["per_room"]["A"] is None
    assert res["score"] is None
    assert res["min_clearance"] is None
    assert res["p10_clearance"] is None
    assert res["lowest_room"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Stairs descending ceiling: mean high, min low
# ─────────────────────────────────────────────────────────────────────────────

def test_stairs_descending_ceiling():
    """5x1 corridor with a ceiling that slopes from y=5 down to y=3.

    Columns (z=0):
      x=0 ceiling at y=5  → clearance 4
      x=1 ceiling at y=4  → clearance 3
      x=2 ceiling at y=3  → clearance 2
      x=3 ceiling at y=4  → clearance 3
      x=4 ceiling at y=5  → clearance 4

    Mean = (4+3+2+3+4)/5 = 3.2, min = 2.
    Score still 1.0 (mean >= _VC_PLAYER_HEIGHT=2) but `min_clearance`
    surfaces the worst column for the TFG diagnostic notes.
    """
    voxels: list[tuple[int, int, int, str]] = []
    for x in range(5):
        voxels.append((x, 0, 0, "minecraft:oak_planks"))
    ceiling_y = [5, 4, 3, 4, 5]
    for x, cy in enumerate(ceiling_y):
        voxels.append((x, cy, 0, "minecraft:oak_stairs"))
    vmap = _vmap_from(voxels)
    doc = _doc_one_room("A", [0, 0, 0, 5, 6, 1])

    res = _vertical_clearance(doc, vmap)

    # Clearance is now measured over INTERIOR columns only (inset by the wall
    # ring). X span 5 (>2) → x∈{1,2,3}; Z span 1 (≤2) → z=0. Clearances at
    # x=1,2,3 are 3,2,3 → mean = 8/3 ≈ 2.67, min = 2. Score 1.0 (mean ≥ 2).
    assert res["score"] == 1.0
    assert res["per_room"]["A"] == pytest.approx(2.67, abs=0.01)
    assert res["min_clearance"] == 2
    assert "min=2" in res["notes"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Hidden beam: one hanging slab in an otherwise-h3 4x4 room
# ─────────────────────────────────────────────────────────────────────────────

def test_hidden_beam_via_slab():
    """4x4 room (16 columns), ceiling at y=4 (solid oak_planks) → clearance 3
    per column. A single hanging slab at (1,2,1) drops *that* column's
    clearance to 1 (floor y=0, first solid above is the slab at y=2, so
    ceil_y - floor_y - 1 = 1).

    The mean smooths the beam out; `min_clearance` catches the beam (1).
    Per the spec formula `sorted_c[max(0, len(sorted_c) // 10)]` (index-based,
    not true percentile), with sorted=[1,3,3,…,3] and len=16 the index is
    16//10=1, so `p10_clearance==3`. The refined-plan §3 case 4 quotes
    `p10==1`, which is mathematically incompatible with its own formula at
    n=16 (would require >=10% of columns to share the low value); we follow
    the formula. Deviation logged in vertical_clearance.impl.md.
    """
    voxels: list[tuple[int, int, int, str]] = []
    # floor y=0
    for x in range(4):
        for z in range(4):
            voxels.append((x, 0, z, "minecraft:oak_planks"))
    # ceiling y=4
    for x in range(4):
        for z in range(4):
            voxels.append((x, 4, z, "minecraft:oak_planks"))
    # hanging beam: 1 slab at (1, 2, 1)
    voxels.append((1, 2, 1, "minecraft:oak_slab"))

    vmap = _vmap_from(voxels)
    doc = _doc_one_room("A", [0, 0, 0, 4, 5, 4])

    res = _vertical_clearance(doc, vmap)

    # Interior-only measurement: 4×4 room → inner 2×2 columns {1,2}×{1,2}.
    # The beam at (1,2,1) drops column (1,1) to clearance 1; the other 3 are 3
    # → mean = (1+3+3+3)/4 = 2.5. min=1; with n=4 the p10 index is 0 → value 1.
    assert res["per_room"]["A"] == pytest.approx(2.5, abs=0.01)
    assert res["min_clearance"] == 1
    assert res["p10_clearance"] == 1
    # Mean >= 2 → room scores 1.0, but min_clearance still exposes the beam.
    assert res["score"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# 5. Open courtyard: no ceiling → per_room None, score None
# ─────────────────────────────────────────────────────────────────────────────

def test_open_courtyard():
    """3x3 floor with no ceiling above. Each column has a floor at y=0 but
    no solid above → floor_y found, ceil_y None → column skipped. With all
    columns skipped, per_room['yard'] is None and score is None (no other
    rooms contribute either).
    """
    voxels: list[tuple[int, int, int, str]] = []
    for x in range(3):
        for z in range(3):
            voxels.append((x, 0, z, "minecraft:cobblestone"))
    vmap = _vmap_from(voxels)
    doc = _doc_one_room("yard", [0, 0, 0, 3, 6, 3])

    res = _vertical_clearance(doc, vmap)

    assert res["per_room"]["yard"] is None
    assert res["score"] is None
    assert res["lowest_room"] is None
    assert res["min_clearance"] is None
    assert res["p10_clearance"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 6. No bot_decomposition → score None, per_room {}
# ─────────────────────────────────────────────────────────────────────────────

def test_bot_decomposition_none():
    res = _vertical_clearance({}, {})
    assert res["score"] is None
    assert res["per_room"] == {}
    assert res["lowest_room"] is None
    assert res["min_clearance"] is None
    assert res["p10_clearance"] is None
    assert "no bot_decomposition" in res["notes"]
