"""Tests for `_light_on_two_sides` (APL #159).

Covers the 3 refined-plan fixes:
  - FIX 1: index `master_plan.connectors.windows` (with `_GLASS_RX` fallback)
  - FIX 2: weight=0.5 for rooms <3 wide in either XZ dimension
  - FIX 3: `is_exterior_wall` compares by `rid` (not by AABB value)

Plus a `_norm_wall(s)` helper normalising direction tokens
(``north``/``N``/``n`` → ``n``).

Schema note: window connectors carry ``in_room`` + ``wall`` (or the
synonyms ``room``/``facing``). Walls accept north/south/east/west and
N/S/E/W case-insensitively.
"""
from __future__ import annotations

import pytest

from pipeline.agents.evaluator import _light_on_two_sides, _norm_wall


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _doc(spaces, *, bbox_size=(20, 8, 20)):
    """Wrap spaces into a minimal doc with bot_decomposition + bounding_box."""
    return {
        "bot_decomposition": {
            "building": {"storeys": [{"id": "p0", "spaces": spaces}]},
        },
        "bounding_box": {"origin": [0, 0, 0], "size": list(bbox_size)},
    }


def _mp(windows=None):
    """Build a minimal master_plan with the given windows connectors."""
    return {"connectors": {"doors": [], "windows": windows or [], "staircases": []}}


def _glass_wall_vmap(aabb, walls, *, glass_id="minecraft:glass"):
    """Build a vmap that places ONE glass block in the centre of each
    requested wall of `aabb`, avoiding corners so each glass voxel
    belongs unambiguously to a single wall.

    `walls` is an iterable from {"n","s","e","w"}. AABBs must have
    XZ dims ≥3 to leave at least one non-corner cell per wall.
    """
    a = aabb
    cx = (a[0] + a[3]) // 2
    cz = (a[2] + a[5]) // 2
    cy = (a[1] + a[4]) // 2
    out: dict = {}
    if "n" in walls:
        out[(cx, cy, a[2])] = glass_id
    if "s" in walls:
        out[(cx, cy, a[5] - 1)] = glass_id
    if "w" in walls:
        out[(a[0], cy, cz)] = glass_id
    if "e" in walls:
        out[(a[3] - 1, cy, cz)] = glass_id
    return out


# ---------------------------------------------------------------------------
# T1 — glass in N+S walls → score=1.0, source=glass_scan
# ---------------------------------------------------------------------------
def test_windows_two_walls_score_10():
    aabb = [0, 0, 0, 5, 3, 5]
    spaces = [{"id": "A", "function": "living_room", "aabb": aabb}]
    vmap = _glass_wall_vmap(aabb, walls=("n", "s"))
    result = _light_on_two_sides(_doc(spaces), vmap, None)
    assert result["score"] == 1.0, result
    assert result["per_room"]["A"]["source"] == "glass_scan"
    assert result["per_room"]["A"]["n_walls_with_windows"] == 2
    assert result["pattern_id"] == "light-on-two-sides"


# ---------------------------------------------------------------------------
# T2 — glass in ONE wall only → score=0.5
# ---------------------------------------------------------------------------
def test_one_wall_score_05():
    aabb = [0, 0, 0, 5, 3, 5]
    spaces = [{"id": "A", "function": "living_room", "aabb": aabb}]
    vmap = _glass_wall_vmap(aabb, walls=("n",))
    result = _light_on_two_sides(_doc(spaces), vmap, None)
    assert result["score"] == 0.5, result
    assert result["per_room"]["A"]["n_walls_with_windows"] == 1


# ---------------------------------------------------------------------------
# T3 — no glass anywhere → score=0.0
# ---------------------------------------------------------------------------
def test_no_windows_score_00():
    aabb = [0, 0, 0, 5, 3, 5]
    spaces = [{"id": "A", "function": "living_room", "aabb": aabb}]
    result = _light_on_two_sides(_doc(spaces), {}, None)
    assert result["score"] == 0.0, result
    assert result["per_room"]["A"]["n_walls_with_windows"] == 0


# ---------------------------------------------------------------------------
# T4 — interior room (all 4 walls shared with neighbours) is excluded from
# the average and tagged with note="interior room, excluded".
# Layout: a central room surrounded by N/S/E/W neighbours.
# ---------------------------------------------------------------------------
def test_interior_room_excluded():
    # Central room X is fully surrounded.
    spaces = [
        {"id": "X",  "function": "hallway",  "aabb": [5, 0, 5, 10, 3, 10]},
        {"id": "N",  "function": "bedroom",  "aabb": [5, 0, 0, 10, 3,  5]},
        {"id": "S",  "function": "kitchen",  "aabb": [5, 0,10, 10, 3, 15]},
        {"id": "W",  "function": "living_room", "aabb": [0, 0, 5,  5, 3, 10]},
        {"id": "E",  "function": "library",  "aabb": [10,0, 5, 15, 3, 10]},
    ]
    # Put glass on the outer walls of the surrounding rooms so the overall
    # score is well-defined; the interior `X` should not contribute.
    vmap = {}
    vmap.update(_glass_wall_vmap([5, 0, 0, 10, 3, 5], walls=("n",)))
    vmap.update(_glass_wall_vmap([5, 0,10, 10, 3,15], walls=("s",)))
    vmap.update(_glass_wall_vmap([0, 0, 5, 5, 3,10], walls=("w",)))
    vmap.update(_glass_wall_vmap([10,0, 5,15, 3,10], walls=("e",)))
    result = _light_on_two_sides(_doc(spaces), vmap, None)
    assert result["per_room"]["X"]["room_score"] is None
    assert result["per_room"]["X"]["note"] == "interior room, excluded"
    # Surrounding rooms each have 3 exterior walls; the central X is NOT
    # in the "X rooms evaluated" count.
    assert "5 rooms evaluated" not in result["notes"]
    assert "4 rooms evaluated" in result["notes"]


# ---------------------------------------------------------------------------
# T5 — narrow room (XZ <3) gets weight=0.5. With one 2x4 narrow room
# scoring rs=1.0 and one 5x5 wide room scoring rs=0.0, the weighted
# average is (1.0*0.5 + 0.0*1.0) / (0.5 + 1.0) ≈ 0.333, NOT 0.5.
# ---------------------------------------------------------------------------
def test_narrow_room_weight_05():
    # Narrow room A (2x4) with N+S glass → rs=1.0
    aabb_a = [0, 0, 0, 2, 3, 4]
    # Wide room B (5x5) with no glass → rs=0.0, placed far away so its
    # walls are all exterior and don't touch A.
    aabb_b = [10, 0, 0, 15, 3, 5]
    spaces = [
        {"id": "A", "function": "closet",      "aabb": aabb_a},
        {"id": "B", "function": "living_room", "aabb": aabb_b},
    ]
    vmap = _glass_wall_vmap(aabb_a, walls=("n", "s"))
    result = _light_on_two_sides(_doc(spaces), vmap, None)
    assert result["per_room"]["A"]["weight"] == 0.5
    assert result["per_room"]["B"]["weight"] == 1.0
    assert result["per_room"]["A"]["room_score"] == 1.0
    assert result["per_room"]["B"]["room_score"] == 0.0
    # weighted avg = (1.0*0.5 + 0.0*1.0) / 1.5 = 1/3
    assert result["score"] == pytest.approx(0.333, abs=0.01), result


# ---------------------------------------------------------------------------
# T6 — master_plan override: even though the whole S wall is solid glass,
# master_plan only declares a window on N, so windows_walls==1 and
# score=0.5. Source must be "master_plan".
# ---------------------------------------------------------------------------
def test_master_plan_override():
    aabb = [0, 0, 0, 5, 3, 5]
    spaces = [{"id": "A", "function": "living_room", "aabb": aabb}]
    # Glass on BOTH n and s in voxels (glass_scan would say 2 walls).
    vmap = _glass_wall_vmap(aabb, walls=("n", "s"))
    master_plan = _mp(windows=[
        {"id": "w-A-n", "in_room": "A", "wall": "n", "at": [2, 1, 0]},
    ])
    result = _light_on_two_sides(_doc(spaces), vmap, master_plan)
    assert result["per_room"]["A"]["source"] == "master_plan"
    assert result["per_room"]["A"]["n_walls_with_windows"] == 1
    assert result["score"] == 0.5


# ---------------------------------------------------------------------------
# T7 — fallback to glass_scan when master_plan has no connectors / empty
# windows. Both forms must produce the SAME score as T1 (iter05 no-regression).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("mp", [
    None,
    {},
    {"connectors": {}},
    {"connectors": {"windows": []}},
])
def test_fallback_when_no_connectors(mp):
    aabb = [0, 0, 0, 5, 3, 5]
    spaces = [{"id": "A", "function": "living_room", "aabb": aabb}]
    vmap = _glass_wall_vmap(aabb, walls=("n", "s"))
    result = _light_on_two_sides(_doc(spaces), vmap, mp)
    assert result["score"] == 1.0
    assert result["per_room"]["A"]["source"] == "glass_scan"


# ---------------------------------------------------------------------------
# T8 — degenerate: two rooms with identical AABBs but distinct rids must
# each be evaluated independently (regression for the `ob == a` bug, which
# made every room consider itself a neighbour via value equality).
# ---------------------------------------------------------------------------
def test_degenerate_duplicate_aabb_distinct_rid():
    """Two rooms sharing the *same* AABB but distinct rids must each be
    evaluated independently. Regression: the v1 `ob == a` test made every
    room treat its AABB-twin as identity and the duplicate-twin as a
    neighbour, never both. The rid-based FIX 3 only skips self, so the
    AABB-twins are not treated as neighbours (they only overlap, they do
    not share a face), and each room is evaluated normally.
    """
    aabb = [0, 0, 0, 5, 3, 5]
    spaces = [
        {"id": "A", "function": "living_room", "aabb": list(aabb)},
        {"id": "B", "function": "library",     "aabb": list(aabb)},
    ]
    # Glass on N+S of the shared AABB → both rooms must see windows in
    # both walls and score rs=1.0 (NOT silently skipped, NOT excluded as
    # interior).
    vmap = _glass_wall_vmap(aabb, walls=("n", "s"))
    result = _light_on_two_sides(_doc(spaces), vmap, None)
    assert "A" in result["per_room"]
    assert "B" in result["per_room"]
    assert result["per_room"]["A"]["room_score"] == 1.0
    assert result["per_room"]["B"]["room_score"] == 1.0
    assert result["per_room"]["A"]["n_exterior_walls"] == 4
    assert result["per_room"]["B"]["n_exterior_walls"] == 4
    assert result["score"] == 1.0


# ---------------------------------------------------------------------------
# Extra (parametrised, not counted in the 8): _norm_wall normalisation.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("inp,exp", [
    ("n", "n"), ("N", "n"), ("north", "n"), ("NORTH", "n"), (" North ", "n"),
    ("s", "s"), ("S", "s"), ("south", "s"), ("SOUTH", "s"),
    ("e", "e"), ("E", "e"), ("east", "e"), ("EAST", "e"),
    ("w", "w"), ("W", "w"), ("west", "w"), ("WEST", "w"),
    ("", ""),
    (None, ""),
])
def test_wall_enum_normalization(inp, exp):
    assert _norm_wall(inp) == exp
