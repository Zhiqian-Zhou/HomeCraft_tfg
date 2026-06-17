"""Skill: square_tower.

A square defensive tower with battlements, four window slits, a door on the
+z side, and a small interior with a lantern and chest.

Layout (within the clamped AABB):
    * FillHollow shell — @primary walls, @secondary floor at y0, hollow inside.
    * Battlement ring at y == y_top: alternating @primary merlons + air gaps
      around the entire top perimeter; the row beneath the rim stays solid so
      the merlons sit on a parapet walk.
    * Window slits — 1-2 blocks of @glass at mid-height on each of the four
      faces, single-block-wide.
    * Door — two blocks of air (minecraft:air) at y0..y0+1 centered on the +z
      face, so the tower has an obvious entrance.
    * Interior — one minecraft:lantern hanging from the inner wall and one
      minecraft:chest on the floor near the back corner.

Material roles:
    @primary    — tower walls + merlons
    @secondary  — floor course at y0
    @glass      — window slit panes
    @light      — fallback if `lantern` were a role (we hard-code lantern)

Defensive sizing: clamped to 4x6x4 .. 12x14x12.
"""
from __future__ import annotations

from typing import List

from .base import AABB, FillHollow, Materials, Op, PlaceBlock


# Defensive bounds per spec.
_MIN = (4, 6, 4)
_MAX = (12, 14, 12)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [4..12, 6..14, 4..12] envelope.

    The lower corner is preserved; the upper corner moves to satisfy the
    size constraints so the tower stays well-formed for any caller input.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a square defensive tower into the given AABB."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # 1) Hollow shell: @primary walls + ceiling, @secondary floor at y0.
    #    Interior is left as air so we can populate the room afterwards.
    ops.append(FillHollow(
        aabb=a,
        wall="@primary",
        fill=None,
        floor="@secondary",
        ceiling="@primary",
    ))

    # 2) Battlement at the top ring. FillHollow already painted the ceiling
    #    at y == y1-1 as @primary. We KEEP that as the parapet walk and add
    #    the merlons one row above on the rim (y == y1) — that way the
    #    crenellation rises ABOVE the tower top instead of cutting holes
    #    through the ceiling.
    y_rim = a.y1  # one above the top ceiling row
    perimeter = _perimeter_ring(a.x0, a.z0, a.x1 - 1, a.z1 - 1)
    for i, (x, z) in enumerate(perimeter):
        # Alternating merlon + air: even index = merlon, odd = gap (already air).
        if i % 2 == 0:
            ops.append(PlaceBlock(x, y_rim, z, "@primary"))

    # 3) Window slits — one 1-block-wide column of @glass at mid-height on
    #    each of the four sides. We use a 2-block-tall slit when there is
    #    vertical room (h >= 7), else fall back to a single block.
    y_mid_lo = a.y0 + max(2, a.h // 2 - 1)
    y_mid_hi = y_mid_lo + 1 if a.h >= 7 else y_mid_lo
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2

    # Avoid placing a slit on the door face (+z) at a height that intersects
    # the doorway. The door is only at y0..y0+1, slits are at y_mid_lo+, so
    # they never collide; still, we keep all four slits.
    slits = [
        (cx, a.z0),         # -z face
        (cx, a.z1 - 1),     # +z face
        (a.x0, cz),         # -x face
        (a.x1 - 1, cz),     # +x face
    ]
    for (sx, sz) in slits:
        ops.append(PlaceBlock(sx, y_mid_lo, sz, "@glass"))
        if y_mid_hi != y_mid_lo and y_mid_hi < a.y1 - 1:
            ops.append(PlaceBlock(sx, y_mid_hi, sz, "@glass"))

    # 4) Door on the +z face — punch a 1-wide, 2-tall opening at the
    #    centerline of the +z wall. We overwrite the two wall cells with
    #    minecraft:air so the composer drops them and leaves an opening.
    door_x = cx
    door_z = a.z1 - 1
    for dy in (a.y0, a.y0 + 1):
        if dy < a.y1 - 1:  # don't punch through the ceiling
            ops.append(PlaceBlock(door_x, dy, door_z, "minecraft:air"))

    # 5) Interior fittings — one lantern + one chest.
    #    Lantern: just below the ceiling, near the centre.
    lantern_y = a.y1 - 2
    if lantern_y > a.y0:
        ops.append(PlaceBlock(cx, lantern_y, cz, "minecraft:lantern"))

    # Chest: on the floor against a back-interior corner (away from the door).
    # The door is on +z (z1-1); place the chest near -z so they don't overlap.
    chest_x = a.x0 + 1
    chest_z = a.z0 + 1
    chest_y = a.y0 + 1
    if chest_x < a.x1 - 1 and chest_z < a.z1 - 1 and chest_y < a.y1 - 1:
        ops.append(PlaceBlock(chest_x, chest_y, chest_z, "minecraft:chest"))

    return ops


def _perimeter_ring(x0: int, z0: int, x1: int, z1: int) -> list[tuple[int, int]]:
    """Return the ring of (x, z) cells around the rectangle (x0,z0)..(x1,z1)
    inclusive, ordered as a single closed walk so neighbouring indices
    correspond to neighbouring cells (used for the alternating merlon
    pattern).
    """
    if x1 < x0 or z1 < z0:
        return []
    cells: list[tuple[int, int]] = []
    # Top edge: z = z0, x from x0..x1
    for x in range(x0, x1 + 1):
        cells.append((x, z0))
    # Right edge: x = x1, z from z0+1..z1
    for z in range(z0 + 1, z1 + 1):
        cells.append((x1, z))
    # Bottom edge: z = z1, x from x1-1..x0
    for x in range(x1 - 1, x0 - 1, -1):
        cells.append((x, z1))
    # Left edge: x = x0, z from z1-1..z0+1
    for z in range(z1 - 1, z0, -1):
        cells.append((x0, z))
    return cells
