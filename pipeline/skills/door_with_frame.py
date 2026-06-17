"""Skill: door_with_frame.

A doorway with a framed opening punched into a thin wall section. The
incoming AABB represents the WALL SECTION that hosts the door — usually
a 1-block-thin slab (depth=1 or width=1), although the skill stays well
behaved up to small 5×5×1 slices.

Composition (bottom-up, centered on the wall axis):

    * Door (2 tall) at the bottom-center: ``@door[half=lower,facing=...]``
      below ``@door[half=upper,facing=...]``.
    * Two @accent jambs flanking the door (each 2 tall) — the wall slab
      itself is overwritten with @accent so the frame reads as a single
      surround.
    * A 3-wide @accent lintel directly above the door head.
    * An @stairs "cap" course above the lintel that overhangs outward
      (away from the door's facing direction → the overhang shelters the
      entrance).
    * Optional ``minecraft:lantern`` next to the door at head height
      (kwarg ``with_lantern=True``, on by default).

Kwargs
------
facing : str, default ``'south'``
    Direction the door opens toward. One of north/south/east/west.
    Determines wall axis (north/south → wall runs along X, east/west →
    wall runs along Z) and orients door/stairs accordingly.
with_lantern : bool, default ``True``
    Whether to place the lantern next to the door at head height.

Defensive sizing: clamped to 3×3×1 .. 5×5×1 along the wall axis.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock


# Opposite-facing lookup: stairs cap should overhang outward, so the
# stair block faces back toward the wall (opposite of the door's facing).
_OPPOSITE = {
    "north": "south",
    "south": "north",
    "east":  "west",
    "west":  "east",
}

# Door facing → wall axis. "south"/"north" → wall lies along the X axis
# (door spans X, thin in Z). "east"/"west" → wall lies along the Z axis.
_AXIS_X = {"south", "north"}
_AXIS_Z = {"east", "west"}


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a framed doorway centered in the AABB wall slab."""
    facing = str(kwargs.get("facing", "south")).lower()
    if facing not in _OPPOSITE:
        facing = "south"
    with_lantern = bool(kwargs.get("with_lantern", True))

    # Decide which horizontal axis the wall runs along. Prefer the
    # caller's facing hint; if the AABB shape disagrees (e.g. caller asks
    # for "south" but supplies a slab that's wider along Z than X), fall
    # back to the longer horizontal axis so the door still fits.
    if facing in _AXIS_X:
        wall_along_x = True
    else:
        wall_along_x = False
    # Width along the wall must be ≥ 3 to fit jambs + door.
    along = aabb.w if wall_along_x else aabb.d
    cross = aabb.d if wall_along_x else aabb.w
    if along < 3 and cross >= 3:
        # Caller's facing is incompatible with the slab shape; flip axis.
        wall_along_x = not wall_along_x
        # Re-pick a sensible facing for the new axis.
        if wall_along_x and facing not in _AXIS_X:
            facing = "south"
        elif (not wall_along_x) and facing not in _AXIS_Z:
            facing = "east"

    # Recompute extents on the chosen axis.
    if wall_along_x:
        u0, u1 = aabb.x0, aabb.x1   # along-wall axis range
        v0, v1 = aabb.z0, aabb.z1   # cross-wall (thin) axis range
    else:
        u0, u1 = aabb.z0, aabb.z1
        v0, v1 = aabb.x0, aabb.x1

    along = u1 - u0
    cross = v1 - v0
    height = aabb.y1 - aabb.y0

    # Defensive minimum: need at least 3 along, 3 high, 1 cross.
    if along < 3 or height < 3 or cross < 1:
        return []

    # Clamp along/cross to the supported envelope (5×5×1 max for the
    # framed slice; if the caller gives more we work on the centered
    # 5-wide / 5-tall slab and ignore the rest).
    max_along = min(along, 5)
    max_height = min(height, 5)
    # We treat the wall plane as v == v0 (the "front" of the slab).
    # Stairs cap overhangs outward at v == v0 - 1 in world coords only
    # if v0 > 0; otherwise we project the cap onto v0 itself (defensive
    # for slabs anchored at the origin).
    wall_v = v0

    # Center the 3-wide door+frame footprint on the along axis.
    span = 3  # door (1) + 2 jambs (1 each)
    u_center = u0 + (max_along - 1) // 2
    door_u = u_center
    jamb_left_u = door_u - 1
    jamb_right_u = door_u + 1
    # Lintel covers the 3 columns above the door.
    lintel_us = (jamb_left_u, door_u, jamb_right_u)

    y_floor = aabb.y0
    y_door_lo = y_floor
    y_door_hi = y_floor + 1
    y_lintel = y_floor + 2
    y_cap = y_floor + 3 if max_height >= 4 else None

    ops: List[Op] = []

    # ── 1) Jambs: 2 tall, on each side of the door, in @accent.
    for ju in (jamb_left_u, jamb_right_u):
        if not _in_range(ju, u0, u1):
            continue
        x, z = _uv_to_xz(ju, wall_v, wall_along_x)
        ops.append(PlaceBlock(x, y_door_lo, z, "@accent"))
        ops.append(PlaceBlock(x, y_door_hi, z, "@accent"))

    # ── 2) Lintel: 3-wide @accent course directly above the door head.
    for lu in lintel_us:
        if not _in_range(lu, u0, u1):
            continue
        x, z = _uv_to_xz(lu, wall_v, wall_along_x)
        ops.append(PlaceBlock(x, y_lintel, z, "@accent"))

    # ── 3) Stairs cap: above the lintel, overhanging outward (toward
    # the door's facing direction). The stair block must face BACK
    # toward the wall so its slope sheds outward.
    if y_cap is not None and y_cap < aabb.y1:
        cap_facing = _OPPOSITE[facing]
        # Outward offset in world cross-axis. The "outward" direction is
        # the door's facing direction; we offset the cap one cell out
        # from the wall plane so it visibly overhangs.
        out_dv = _outward_delta(facing)
        cap_v = wall_v + out_dv
        for lu in lintel_us:
            if not _in_range(lu, u0, u1):
                continue
            x, z = _uv_to_xz(lu, cap_v, wall_along_x)
            ops.append(PlaceBlock(x, y_cap, z, f"@stairs[facing={cap_facing}]"))

    # ── 4) Door: 2 tall at the bottom-center, oriented to `facing`.
    dx, dz = _uv_to_xz(door_u, wall_v, wall_along_x)
    ops.append(PlaceBlock(dx, y_door_lo, dz, f"@door[half=lower,facing={facing}]"))
    ops.append(PlaceBlock(dx, y_door_hi, dz, f"@door[half=upper,facing={facing}]"))

    # ── 5) Lantern (optional) next to the door at head height. Prefer
    # the right jamb side; if it's outside the slab fall back to the
    # left side. Lantern hangs from the lintel → use [hanging=true].
    if with_lantern:
        head_y = y_door_hi  # head height = top of the door opening
        # Place lantern in-plane, immediately next to the right jamb's
        # outward face. Since the wall slab is thin we set the lantern
        # in the same wall column as the jamb, one block above the
        # jamb — no, that would clash with the lintel. Instead, hang it
        # from the lintel one tile outboard on the same side, at head
        # height.
        candidates = (jamb_right_u + 1, jamb_left_u - 1)
        for cand_u in candidates:
            if _in_range(cand_u, u0, u1):
                lx, lz = _uv_to_xz(cand_u, wall_v, wall_along_x)
                ops.append(PlaceBlock(lx, head_y, lz,
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
    """Signed delta on the cross axis for the outward direction.

    The wall is thin on the cross axis; the door opens outward in the
    `facing` direction. For "south"/"east" outward is +1, for
    "north"/"west" outward is -1. Returns 0 only for unknown inputs
    (already guarded above).
    """
    if facing in ("south", "east"):
        return 1
    if facing in ("north", "west"):
        return -1
    return 0
