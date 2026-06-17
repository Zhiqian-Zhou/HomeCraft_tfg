"""Skill: double_door.

A wide, grand entrance with two doors placed side by side, surrounded by a
single shared frame. The incoming AABB describes a thin wall section that
hosts the double entry — typically a 5x4x1 slab, though the skill is
defensive across 4x3x1 to 7x6x1.

Composition (bottom-up, centered on the wall axis):

    * Two ``@door`` blocks (2 halves each) placed adjacent at the
      bottom-center. The LEFT door has ``hinge=left`` and the RIGHT door
      has ``hinge=right`` so they swing open outward into a symmetric
      grand opening.
    * Two ``@accent`` jambs flanking the door pair (one cell on each
      side, 2 tall).
    * A 4-wide ``@accent`` lintel directly above the door pair, spanning
      jamb-to-jamb across both doors.
    * Optional ``@accent`` capstones at the two ends of the lintel
      course (one cell above the jambs), when room permits.
    * A row of ``@stairs`` above the lintel, overhanging outward (away
      from the door facing) so the slope sheds rain off the entry.
    * Two ``minecraft:lantern`` blocks flanking the doors at head
      height, one outboard of each jamb.

Kwargs
------
facing : str, default ``'south'``
    Direction the doors open toward (north/south/east/west).
with_lanterns : bool, default ``True``
    Whether to flank the entry with two lanterns at head height.
with_capstones : bool, default ``True``
    Whether to place decorative accent capstones at lintel ends.

Defensive sizing: clamped to 4x3x1 .. 7x6x1 along the wall axis.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock


# Stairs cap should overhang outward, so the stair block faces back
# toward the wall (opposite of the door's facing).
_OPPOSITE = {
    "north": "south",
    "south": "north",
    "east":  "west",
    "west":  "east",
}

# Door facing → wall axis. "south"/"north" → wall lies along X; "east"/
# "west" → wall lies along Z.
_AXIS_X = {"south", "north"}
_AXIS_Z = {"east", "west"}


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a grand double-door entrance centered in the AABB wall slab."""
    facing = str(kwargs.get("facing", "south")).lower()
    if facing not in _OPPOSITE:
        facing = "south"
    with_lanterns = bool(kwargs.get("with_lanterns", True))
    with_capstones = bool(kwargs.get("with_capstones", True))

    # Choose wall axis from caller's facing, falling back to the longer
    # horizontal axis when the AABB shape disagrees.
    if facing in _AXIS_X:
        wall_along_x = True
    else:
        wall_along_x = False
    along = aabb.w if wall_along_x else aabb.d
    cross = aabb.d if wall_along_x else aabb.w
    if along < 4 and cross >= 4:
        wall_along_x = not wall_along_x
        if wall_along_x and facing not in _AXIS_X:
            facing = "south"
        elif (not wall_along_x) and facing not in _AXIS_Z:
            facing = "east"

    if wall_along_x:
        u0, u1 = aabb.x0, aabb.x1   # along-wall axis range
        v0, v1 = aabb.z0, aabb.z1   # cross-wall (thin) axis range
    else:
        u0, u1 = aabb.z0, aabb.z1
        v0, v1 = aabb.x0, aabb.x1

    along = u1 - u0
    cross = v1 - v0
    height = aabb.y1 - aabb.y0

    # Defensive minimum: 4 along (jamb + door + door + jamb), 3 high, 1 cross.
    if along < 4 or height < 3 or cross < 1:
        return []

    # Clamp to the supported envelope (7 wide x 6 tall x 1 thin).
    max_along = min(along, 7)
    max_height = min(height, 6)

    wall_v = v0  # wall plane in world cross coord

    # Footprint = jamb + door_left + door_right + jamb = 4 cells.
    # Center it on the along axis.
    span = 4
    start_u = u0 + (max_along - span) // 2
    jamb_left_u   = start_u
    door_left_u   = start_u + 1
    door_right_u  = start_u + 2
    jamb_right_u  = start_u + 3
    lintel_us = (jamb_left_u, door_left_u, door_right_u, jamb_right_u)

    y_floor   = aabb.y0
    y_door_lo = y_floor
    y_door_hi = y_floor + 1
    y_lintel  = y_floor + 2
    y_cap     = y_floor + 3 if max_height >= 4 else None
    y_cstop   = y_floor + 3 if max_height >= 4 else None

    ops: List[Op] = []

    # ── 1) Jambs (2 tall, @accent on each flank).
    for ju in (jamb_left_u, jamb_right_u):
        if not _in_range(ju, u0, u1):
            continue
        x, z = _uv_to_xz(ju, wall_v, wall_along_x)
        ops.append(PlaceBlock(x, y_door_lo, z, "@accent"))
        ops.append(PlaceBlock(x, y_door_hi, z, "@accent"))

    # ── 2) Wide lintel (4 wide, @accent), spanning jamb to jamb above
    # the heads of both doors.
    for lu in lintel_us:
        if not _in_range(lu, u0, u1):
            continue
        x, z = _uv_to_xz(lu, wall_v, wall_along_x)
        ops.append(PlaceBlock(x, y_lintel, z, "@accent"))

    # ── 3) Stairs cap overhang above the lintel, facing back toward the
    # wall so the slope sheds outward over the entry.
    if y_cap is not None and y_cap < aabb.y1:
        cap_facing = _OPPOSITE[facing]
        out_dv = _outward_delta(facing)
        cap_v = wall_v + out_dv
        for lu in lintel_us:
            if not _in_range(lu, u0, u1):
                continue
            x, z = _uv_to_xz(lu, cap_v, wall_along_x)
            ops.append(PlaceBlock(x, y_cap, z,
                                  f"@stairs[facing={cap_facing}]"))

    # ── 4) Optional decorative capstones at the lintel ends — a single
    # accent block above each jamb, in-plane with the wall.
    if with_capstones and y_cstop is not None and y_cstop < aabb.y1:
        for ju in (jamb_left_u, jamb_right_u):
            if not _in_range(ju, u0, u1):
                continue
            x, z = _uv_to_xz(ju, wall_v, wall_along_x)
            ops.append(PlaceBlock(x, y_cstop, z, "@accent"))

    # ── 5) Doors: two 2-tall doors side by side, symmetric hinges so the
    # pair opens like a grand entrance (left door hinge=left swings left,
    # right door hinge=right swings right).
    lxz = _uv_to_xz(door_left_u, wall_v, wall_along_x)
    rxz = _uv_to_xz(door_right_u, wall_v, wall_along_x)
    ops.append(PlaceBlock(lxz[0], y_door_lo, lxz[1],
                          f"@door[half=lower,facing={facing},hinge=left]"))
    ops.append(PlaceBlock(lxz[0], y_door_hi, lxz[1],
                          f"@door[half=upper,facing={facing},hinge=left]"))
    ops.append(PlaceBlock(rxz[0], y_door_lo, rxz[1],
                          f"@door[half=lower,facing={facing},hinge=right]"))
    ops.append(PlaceBlock(rxz[0], y_door_hi, rxz[1],
                          f"@door[half=upper,facing={facing},hinge=right]"))

    # ── 6) Flanking lanterns (2): one outboard of each jamb at head
    # height. Fall back to the in-jamb column if the outboard cell is
    # outside the slab.
    if with_lanterns:
        head_y = y_door_hi
        left_candidates  = (jamb_left_u - 1, jamb_left_u)
        right_candidates = (jamb_right_u + 1, jamb_right_u)
        for cand_u in left_candidates:
            if _in_range(cand_u, u0, u1):
                lx, lz = _uv_to_xz(cand_u, wall_v, wall_along_x)
                # Skip if this cell is already taken by a jamb/door — we
                # only fall through to the in-jamb column when the
                # outboard cell is out of range.
                if cand_u == jamb_left_u:
                    # In-jamb fallback: place lantern one cell above the
                    # jamb (at lintel level) to avoid overwriting jamb.
                    if y_lintel + 0 < aabb.y1:
                        ops.append(PlaceBlock(lx, head_y, lz,
                                              "minecraft:lantern[hanging=false]"))
                else:
                    ops.append(PlaceBlock(lx, head_y, lz,
                                          "minecraft:lantern[hanging=false]"))
                break
        for cand_u in right_candidates:
            if _in_range(cand_u, u0, u1):
                rx, rz = _uv_to_xz(cand_u, wall_v, wall_along_x)
                if cand_u == jamb_right_u:
                    if y_lintel + 0 < aabb.y1:
                        ops.append(PlaceBlock(rx, head_y, rz,
                                              "minecraft:lantern[hanging=false]"))
                else:
                    ops.append(PlaceBlock(rx, head_y, rz,
                                          "minecraft:lantern[hanging=false]"))
                break

    return ops


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────

def _in_range(v: int, lo: int, hi: int) -> bool:
    """Half-open range check matching AABB convention."""
    return lo <= v < hi


def _uv_to_xz(u: int, v: int, wall_along_x: bool) -> tuple[int, int]:
    """Map (along, cross) wall-local coords to world (x, z)."""
    if wall_along_x:
        return u, v
    return v, u


def _outward_delta(facing: str) -> int:
    """Signed delta on the cross axis for the outward direction."""
    if facing in ("south", "east"):
        return 1
    if facing in ("north", "west"):
        return -1
    return 0
