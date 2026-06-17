"""Skill: perimeter_wall_with_windows.

A solid perimeter wall around the AABB (top/bottom inclusive), with:
  - Window openings every 4 blocks along each wall (2-tall columns of @glass).
  - Foundation course at y0 of @secondary (stone foundation).
  - Cornice at y_top - 1 of @accent slabs (use @slab).

The interior is left empty (air); only the perimeter shell is emitted.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Defensive sizing: clamped to 4×4×4 .. 20×10×20.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, FillHollow, PlaceBlock, Rect


# Defensive bounds, per spec.
_MIN = (4, 4, 4)
_MAX = (20, 10, 20)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [4..20, 4..10, 4..20] envelope.

    The lower corner is preserved; the upper corner is shifted to satisfy the
    size constraints. This keeps the wall well-formed even when callers pass
    pathological inputs.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a perimeter wall with window openings, foundation, and cornice."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # 1) Solid perimeter shell of @primary, hollow interior (no fill).
    #    FillHollow paints floor, ceiling, and the 4 wall faces. We then
    #    override the floor (y0) and the ceiling-1 with foundation/cornice,
    #    and cut window openings.
    ops.append(FillHollow(aabb=a, wall="@primary", fill=None))

    # 2) Foundation course of @secondary at y == y0 along the perimeter only.
    #    We rewrite the four edges to keep the interior of the floor as air.
    y_found = a.y0
    # x-edges (front/back walls), z = z0 and z = z1-1
    for z_edge in (a.z0, a.z1 - 1):
        for x in range(a.x0, a.x1):
            ops.append(PlaceBlock(x, y_found, z_edge, "@secondary"))
    # z-edges (left/right walls), x = x0 and x = x1-1
    for x_edge in (a.x0, a.x1 - 1):
        for z in range(a.z0 + 1, a.z1 - 1):
            ops.append(PlaceBlock(x_edge, y_found, z, "@secondary"))

    # 3) Cornice at y_top - 1 (a == y1 - 1) using @slab along the perimeter.
    y_corn = a.y1 - 1
    for z_edge in (a.z0, a.z1 - 1):
        for x in range(a.x0, a.x1):
            ops.append(PlaceBlock(x, y_corn, z_edge, "@slab"))
    for x_edge in (a.x0, a.x1 - 1):
        for z in range(a.z0 + 1, a.z1 - 1):
            ops.append(PlaceBlock(x_edge, y_corn, z, "@slab"))

    # 4) Window openings: every 4 blocks along each wall, 2-tall column of
    #    @glass starting one above the foundation. Skip if the wall is too
    #    short to host one safely (need clearance from corners).
    #
    #    Window vertical span: [y_glass0, y_glass1]
    #    - y_glass0 = y0 + 1 (above the foundation)
    #    - y_glass1 = y_glass0 + 1 (2-tall total)
    #    Only emit if y_glass1 < y_corn (don't punch through the cornice).
    y_g0 = a.y0 + 1
    y_g1 = y_g0 + 1
    if y_g1 < y_corn:
        # Walls running along X (front: z=z0, back: z=z1-1)
        # Use offsets along x at every 4 blocks, starting at x0 + 2 to keep
        # away from the corners.
        for z_edge in (a.z0, a.z1 - 1):
            x = a.x0 + 2
            while x <= a.x1 - 3:
                for yy in (y_g0, y_g1):
                    ops.append(PlaceBlock(x, yy, z_edge, "@glass"))
                x += 4

        # Walls running along Z (left: x=x0, right: x=x1-1)
        for x_edge in (a.x0, a.x1 - 1):
            z = a.z0 + 2
            while z <= a.z1 - 3:
                for yy in (y_g0, y_g1):
                    ops.append(PlaceBlock(x_edge, yy, z, "@glass"))
                z += 4

    return ops


# Silence unused-import warnings if a linter ever loads this module without
# touching Rect (kept available for future variants of the cornice).
_ = Rect
