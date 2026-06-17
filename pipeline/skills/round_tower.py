"""Skill: round_tower.

A defensive round tower built on a cylindrical footprint inscribed in the
given AABB. Features:

  - Hollow @primary cylinder running from y0 to y0 + H.
  - @secondary floor disc at y0.
  - Battlement crown at the top course: alternating @primary merlons and
    open crenels (air) around the rim.
  - 4 narrow @glass window slits at mid-height on the cardinal directions
    (1-2 blocks tall depending on tower height).
  - A 1x2 door cut on the +z side at y0..y0+1 (cells dropped via
    `minecraft:cave_air`, which the composer strips).
  - A single @light (lantern) inside, hanging near the top.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Defensive sizing: clamped to 5×6×5 .. 14×16×14.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Cylinder, Materials, Op, PlaceBlock, Rect


# Defensive bounds, per spec.
_MIN = (5, 6, 5)
_MAX = (14, 16, 14)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [5..14, 6..16, 5..14] envelope.

    The lower corner is preserved; the upper corner is shifted to satisfy
    the size constraints. This keeps the tower well-formed even when
    callers pass pathological inputs.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a round tower: hollow cylinder + floor + battlement + slits + door + lantern."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # Geometry: radius = min(W, D) // 2; cylinder centered on the AABB's
    # horizontal center. The cylinder is exactly H tall and rises from y0.
    radius = min(a.w, a.d) // 2
    if radius < 2:
        radius = 2
    cx, cz = a.cx, a.cz
    y0 = a.y0
    H = a.h
    y_top = y0 + H - 1  # top course (battlement level)

    # 1) Hollow cylinder wall of @primary, full height.
    ops.append(Cylinder(cx=cx, cz=cz, y0=y0, radius=radius,
                        height=H, block="@primary", hollow=True))

    # 2) Floor disc at y0 of @secondary — overwrite the cylinder's bottom
    #    ring + interior with a solid disc.
    r2 = radius * radius
    for dx in range(-radius, radius + 1):
        for dz in range(-radius, radius + 1):
            if dx * dx + dz * dz <= r2:
                ops.append(PlaceBlock(cx + dx, y0, cz + dz, "@secondary"))

    # 3) Window slits at mid-height, cardinal directions (N/S/E/W).
    #    Replace 1-2 blocks of wall with @glass.
    y_mid = y0 + max(1, H // 2)
    slit_height = 2 if H >= 9 else 1
    # Find the rim block on each cardinal axis (wall cell where d2 == r2_ring).
    # On a hollow cylinder we know cells at (cx ± radius, cz) and
    # (cx, cz ± radius) lie on the rim.
    slit_positions = [
        (cx + radius, cz),  # +x  (east)
        (cx - radius, cz),  # -x  (west)
        (cx, cz + radius),  # +z  (south, will become the door side below)
        (cx, cz - radius),  # -z  (north)
    ]
    for (sx, sz) in slit_positions:
        for k in range(slit_height):
            yy = y_mid + k
            if yy >= y_top:  # don't punch through the battlement
                break
            ops.append(PlaceBlock(sx, yy, sz, "@glass"))

    # 4) Door on +z side at y0..y0+1. The +z slit at (cx, cz+radius) would
    #    overlap the door column, so we drop the door cells AFTER the slit
    #    via `minecraft:cave_air` (composer strips air, removing the wall).
    door_x, door_z = cx, cz + radius
    for k in range(2):
        yy = y0 + k
        if yy < y_top:
            ops.append(PlaceBlock(door_x, yy, door_z, "minecraft:cave_air"))

    # 5) Battlement crown: at the top course (y_top), keep wall cells only
    #    on every-other rim position (merlons), drop the rest to air
    #    (crenels). We walk the outer ring in angular order so alternation
    #    is geometric, not grid-based.
    rim_cells = _outer_ring_cells(cx, cz, radius)
    for i, (rx, rz) in enumerate(rim_cells):
        if i % 2 == 0:
            # Merlon — explicit @primary placement (idempotent w/ cylinder).
            ops.append(PlaceBlock(rx, y_top, rz, "@primary"))
        else:
            # Crenel — drop to air so we see through the gap.
            ops.append(PlaceBlock(rx, y_top, rz, "minecraft:cave_air"))

    # 6) One lantern inside, near the top (but below the battlement).
    lantern_y = max(y0 + 1, y_top - 1)
    ops.append(PlaceBlock(cx, lantern_y, cz, "minecraft:lantern"))

    return ops


def _outer_ring_cells(cx: int, cz: int, radius: int) -> list[tuple[int, int]]:
    """Return the unique outer-ring cells of a discrete hollow cylinder,
    ordered by angle around the center so alternation gives crenellation."""
    r = radius
    r2_outer = r * r
    r2_inner = (r - 1) * (r - 1)
    cells: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    # collect rim cells (matching Cylinder.compile's predicate)
    raw: list[tuple[int, int]] = []
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            d2 = dx * dx + dz * dz
            if d2 > r2_outer:
                continue
            if d2 < r2_inner:
                continue
            raw.append((dx, dz))
    # sort by angle (atan2)
    import math
    raw.sort(key=lambda p: math.atan2(p[1], p[0]))
    for (dx, dz) in raw:
        cell = (cx + dx, cz + dz)
        if cell not in seen:
            seen.add(cell)
            cells.append(cell)
    return cells


# Silence unused-import warning if a linter loads this without using Rect
# (kept available for future variants of the floor/ceiling).
_ = Rect
