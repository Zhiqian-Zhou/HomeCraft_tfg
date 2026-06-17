"""Staircase skill — a structural climb from y0 to y1.

Builds a single-flight staircase that rises along one horizontal axis
(`direction` kwarg: 'east', 'west', 'north', 'south'). For each rise step
we place:

    * a @stairs block (oriented to face the direction of travel),
    * a @primary support directly underneath it (so the steps never
      float when the build is dropped into empty space),
    * a @fence column on the open side, acting as the banister.

A 2×2 landing of @primary is laid at the top so the user can step off
safely. The skill is defensive for AABBs as narrow as 4×4×3 (W×H×D) and
as large as 10×8×6 — when the rise needs more steps than the AABB
height allows, we cap the climb to fit.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock, Fill


# Direction → unit step vector (dx, dz) along the path of travel.
_DIR_VECTORS = {
    "east":  (1, 0),
    "west":  (-1, 0),
    "south": (0, 1),
    "north": (0, -1),
}


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    direction = str(kwargs.get("direction", "east")).lower()
    if direction not in _DIR_VECTORS:
        direction = "east"
    dx, dz = _DIR_VECTORS[direction]

    ops: List[Op] = []

    # The vertical climb is the full AABB height minus the floor level
    # (we step ONTO blocks placed at y0..y1-2 and land at y1-1).
    H = max(0, aabb.h - 1)
    if H <= 0:
        return ops

    # Horizontal run available along the chosen axis.
    run_axis = aabb.w if dx != 0 else aabb.d
    # We need one step per Y. If the run isn't long enough, cap the climb.
    # Reserve 2 cells at the top for the landing footprint along the axis.
    usable_run = max(1, run_axis - 2)
    steps = min(H, usable_run)
    if steps <= 0:
        return ops

    # The transverse axis hosts the banister; pick the floor column.
    # We anchor the flight at the "low" corner of the AABB so it rises
    # toward the opposite corner.
    if dx > 0:
        x_start = aabb.x0
    elif dx < 0:
        x_start = aabb.x1 - 1
    else:
        x_start = aabb.x0 + max(0, (aabb.w - 1) // 2)

    if dz > 0:
        z_start = aabb.z0
    elif dz < 0:
        z_start = aabb.z1 - 1
    else:
        z_start = aabb.z0 + max(0, (aabb.d - 1) // 2)

    # Banister offset: perpendicular to direction of travel.
    # If we travel along +x, banister sits at +z (and vice versa).
    if dx != 0:
        ban_dx, ban_dz = 0, 1 if (aabb.z0 + aabb.d - 1) > z_start else -1
    else:
        ban_dx, ban_dz = (1 if (aabb.x0 + aabb.w - 1) > x_start else -1), 0

    # Emit each step: support below + stair on top + banister beside.
    for i in range(steps):
        sx = x_start + dx * i
        sz = z_start + dz * i
        sy = aabb.y0 + i

        # Support pillar under the step keeps the staircase grounded.
        # Fill from y0 up to sy - 1 so even tall steps stay supported.
        if sy - 1 >= aabb.y0:
            ops.append(
                Fill(
                    AABB(sx, aabb.y0, sz, sx + 1, sy, sz + 1),
                    "@primary",
                )
            )

        # Stair block — encode facing in the block id so the AST stays simple.
        ops.append(PlaceBlock(sx, sy, sz, f"@stairs[facing={direction}]"))

        # Banister column: a single @fence at the same height on the open side.
        bx, bz = sx + ban_dx, sz + ban_dz
        if aabb.contains(bx, sy, bz):
            ops.append(PlaceBlock(bx, sy, bz, "@fence"))

    # Landing: a 2×2 of @primary at the top of the flight so the player
    # has somewhere to stand. The landing sits one cell past the last step,
    # at the same y as the last step (the walking surface).
    top_y = aabb.y0 + steps  # walking surface above the final stair block
    if top_y < aabb.y1:
        lx = x_start + dx * steps
        lz = z_start + dz * steps
        # Two cells along travel axis × two cells along banister axis.
        if dx != 0:
            x0 = min(lx, lx + dx)  # extend in the travel direction
            x1 = x0 + 2
            z0 = min(lz, lz + ban_dz)
            z1 = z0 + 2
        else:
            z0 = min(lz, lz + dz)
            z1 = z0 + 2
            x0 = min(lx, lx + ban_dx)
            x1 = x0 + 2

        # Clamp landing to AABB so we never spill outside.
        x0 = max(aabb.x0, x0)
        x1 = min(aabb.x1, x1)
        z0 = max(aabb.z0, z0)
        z1 = min(aabb.z1, z1)
        if x1 > x0 and z1 > z0:
            ops.append(Fill(AABB(x0, top_y, z0, x1, top_y + 1, z1), "@primary"))

    return ops
