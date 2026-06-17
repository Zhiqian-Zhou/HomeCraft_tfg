"""Skill: arch.

A single freestanding (or doorway-style) arch. The incoming AABB describes
the frame envelope of the arch — typically a thin 5x5x1 slab — and the
skill builds a stone arch INSIDE it whose interior span is left open
(air) so people, doors, or paths can pass under it.

Composition (front view, default 5x5x1):

        K              ← optional keystone @accent at top centre
      P P P            ← flat course of @primary spanning the top
      S   S            ← @stairs facing INWARD at the top corners (curve)
    P       P
    P       P          ← jambs, 2-wide-ish, full height-1 in @primary
    P       P

Coordinates: along-axis = wall width (u), cross-axis = wall depth (v),
y = up. The arch is placed on the v == aabb.z0 plane (or x0 for the
swapped orientation), one cell thick. The jambs sit at the two outermost
along-columns; the top course closes between them; the stairs sit at the
inner side of each top corner so their slope visually rounds the
opening.

Kwargs
------
facing : str, default ``'south'``
    Direction the arch opens toward. Same convention as door_with_frame —
    north/south implies the arch slab runs along X (thin in Z), east/west
    means the slab runs along Z (thin in X). Used to orient the corner
    stair blocks so their slope reads as the inside of the arch.
with_keystone : bool, default ``True``
    Place a single @accent block at the top-centre of the arch.

Defensive sizing: clamped to 3x3x1 .. 7x6x2 along the wall axis. AABBs
that are too small return ``[]`` so the composer leaves the cell empty.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock


# Door facing → wall axis (same convention as door_with_frame).
_AXIS_X = {"south", "north"}
_AXIS_Z = {"east", "west"}

# Corner-stair facing: stairs sit on the INSIDE top corners of the
# arch and face inward across the span. For a wall running along X
# (facing south/north), the left corner stairs face east (toward the
# centre), the right corner stairs face west. For a wall running along
# Z, left faces south, right faces north.
_INWARD_LEFT_X  = "east"
_INWARD_RIGHT_X = "west"
_INWARD_LEFT_Z  = "south"
_INWARD_RIGHT_Z = "north"


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build an arch within the given frame AABB."""
    facing = str(kwargs.get("facing", "south")).lower()
    if facing not in _AXIS_X and facing not in _AXIS_Z:
        facing = "south"
    with_keystone = bool(kwargs.get("with_keystone", True))

    # Decide along/cross axis from facing, with shape-based fallback.
    if facing in _AXIS_X:
        wall_along_x = True
    else:
        wall_along_x = False
    along = aabb.w if wall_along_x else aabb.d
    cross = aabb.d if wall_along_x else aabb.w
    if along < 3 and cross >= 3:
        wall_along_x = not wall_along_x
        if wall_along_x and facing not in _AXIS_X:
            facing = "south"
        elif (not wall_along_x) and facing not in _AXIS_Z:
            facing = "east"

    if wall_along_x:
        u0, u1 = aabb.x0, aabb.x1
        v0, v1 = aabb.z0, aabb.z1
    else:
        u0, u1 = aabb.z0, aabb.z1
        v0, v1 = aabb.x0, aabb.x1

    along = u1 - u0
    cross = v1 - v0
    height = aabb.y1 - aabb.y0

    # Defensive minimum / maximum envelope: 3x3x1 .. 7x6x2.
    if along < 3 or height < 3 or cross < 1:
        return []
    max_along = min(along, 7)
    max_height = min(height, 6)
    # We work on the v == v0 plane (one cell thick). `cross` may be larger
    # than 1 but the arch itself remains a single-thickness ring; the
    # caller may stack arches by passing a deeper AABB and re-invoking.
    wall_v = v0

    y_floor = aabb.y0
    y_top = y_floor + max_height - 1   # top course y
    y_curve = y_top - 1                 # row hosting the corner stairs

    # Centre the arch footprint on the along axis. For odd `max_along` the
    # opening is symmetric; for even widths the centre biases left so the
    # keystone column is well defined.
    left_u = u0
    right_u = u0 + max_along - 1
    # Jambs occupy the 2 outermost along-columns on each side when there's
    # room. For a 3-wide arch the jambs are 1-wide each and the span is 1;
    # for 5-wide the jambs are 2-wide each and the span is 1; for 7-wide
    # the jambs are 2-wide each and the span is 3.
    if max_along >= 5:
        jamb_w = 2
    else:
        jamb_w = 1
    # Jambs height = full height - 1 (top row reserved for stairs+lintel).
    jamb_top_y = y_top - 1  # inclusive

    ops: List[Op] = []

    # ── 1) Two vertical jambs of @primary. ──
    # Left jamb: columns [left_u, left_u + jamb_w)
    # Right jamb: columns [right_u - jamb_w + 1, right_u + 1)
    for ju in range(left_u, left_u + jamb_w):
        if not _in_range(ju, u0, u1):
            continue
        x, z = _uv_to_xz(ju, wall_v, wall_along_x)
        for y in range(y_floor, jamb_top_y + 1):
            ops.append(PlaceBlock(x, y, z, "@primary"))
    for ju in range(right_u - jamb_w + 1, right_u + 1):
        if not _in_range(ju, u0, u1):
            continue
        x, z = _uv_to_xz(ju, wall_v, wall_along_x)
        for y in range(y_floor, jamb_top_y + 1):
            ops.append(PlaceBlock(x, y, z, "@primary"))

    # ── 2) Corner stairs at the top of the opening, facing inward. ──
    # Inner edges of each jamb (the columns adjacent to the open span).
    inner_left_u = left_u + jamb_w
    inner_right_u = right_u - jamb_w
    if wall_along_x:
        left_facing = _INWARD_LEFT_X
        right_facing = _INWARD_RIGHT_X
    else:
        left_facing = _INWARD_LEFT_Z
        right_facing = _INWARD_RIGHT_Z

    # Only place stairs if those inner columns are inside the opening
    # (i.e. the arch is wider than its two jambs combined).
    if inner_left_u <= inner_right_u and y_curve >= y_floor:
        if _in_range(inner_left_u, u0, u1):
            x, z = _uv_to_xz(inner_left_u, wall_v, wall_along_x)
            ops.append(PlaceBlock(x, y_curve, z,
                                  f"@stairs[facing={left_facing}]"))
        if inner_right_u != inner_left_u and _in_range(inner_right_u, u0, u1):
            x, z = _uv_to_xz(inner_right_u, wall_v, wall_along_x)
            ops.append(PlaceBlock(x, y_curve, z,
                                  f"@stairs[facing={right_facing}]"))

    # ── 3) Flat top course of @primary spanning jamb to jamb. ──
    for tu in range(left_u, right_u + 1):
        if not _in_range(tu, u0, u1):
            continue
        x, z = _uv_to_xz(tu, wall_v, wall_along_x)
        ops.append(PlaceBlock(x, y_top, z, "@primary"))

    # ── 4) Optional keystone: single @accent block at top centre. ──
    if with_keystone:
        centre_u = (left_u + right_u) // 2
        if _in_range(centre_u, u0, u1):
            x, z = _uv_to_xz(centre_u, wall_v, wall_along_x)
            ops.append(PlaceBlock(x, y_top, z, "@accent"))

    # ── 5) Ensure the span interior is air. The composer drops air, but
    # if a caller stacked an earlier Fill over this AABB we want the
    # arch opening to remain clear. We DON'T emit air here — the skill
    # only places solid blocks; the opening is simply the absence of
    # placements between the jambs from y_floor up to y_curve - 1.

    return ops


# ────────────────────────────────────────────────────────────────────────
# Helpers (mirror door_with_frame for consistency).
# ────────────────────────────────────────────────────────────────────────

def _in_range(v: int, lo: int, hi: int) -> bool:
    """Half-open range check matching AABB convention."""
    return lo <= v < hi


def _uv_to_xz(u: int, v: int, wall_along_x: bool) -> tuple[int, int]:
    """Map (along, cross) wall-local coords to world (x, z)."""
    if wall_along_x:
        return u, v
    return v, u
