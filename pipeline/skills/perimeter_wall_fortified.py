"""Skill: perimeter_wall_fortified.

A defensive curtain wall around the AABB perimeter, evoking medieval castle
fortifications. Composed of:

  - **Thick wall**: 2 concentric `FillHollow` shells (radii 0 and -1) of
    @primary, giving a 2-block-thick curtain that is structurally believable.
  - **Walkway (allure)**: a ring of @floor blocks one block in from the outer
    wall, sitting just below the merlon course. This is the wall-walk that
    defenders patrol.
  - **Battlements**: alternating merlons (1-block-tall @primary blocks) and
    crenels (gaps) along the outer top edge. Implemented by placing @primary
    blocks every other position around the top perimeter ring.
  - **Foundation**: a course of @secondary at y0, *one block taller than the
    y0 wall* — i.e. we paint the foundation block over the wall course at
    y0 so the base reads as a stepped stone footing.
  - **Arrow slits**: every 5 blocks along each wall, the wall blocks are
    cleared with `minecraft:cave_air` (a 2-tall vertical slit) at chest
    height. The composer drops air on later-wins, so the slit appears as
    a gap in the curtain.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Defensive sizing: clamped to 6×4×6 .. 30×8×30.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, FillHollow, PlaceBlock, Rect


# Defensive bounds, per spec.
_MIN = (6, 4, 6)
_MAX = (30, 8, 30)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [6..30, 4..8, 6..30] envelope.

    The lower corner is preserved; the upper corner is shifted to satisfy the
    size constraints. This keeps the curtain wall well-formed even when
    callers pass pathological inputs.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a fortified curtain wall with walkway, battlements, foundation,
    and arrow slits."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # ────────────────────────────────────────────────────────────────────
    # 1) Two concentric `FillHollow` ops produce a 2-block-thick curtain.
    #    The outer shell is the full AABB (radius 0); the inner shell is
    #    shrunk by 1 on x/z (radius -1) but spans the full height. Together
    #    they form a hollow box whose walls are 2 blocks thick.
    # ────────────────────────────────────────────────────────────────────
    outer = a
    inner = AABB(a.x0 + 1, a.y0, a.z0 + 1, a.x1 - 1, a.y1, a.z1 - 1)
    ops.append(FillHollow(aabb=outer, wall="@primary", fill=None))
    # Only emit the inner shell if it is still a valid box.
    if inner.w >= 2 and inner.d >= 2:
        ops.append(FillHollow(aabb=inner, wall="@primary", fill=None))

    # ────────────────────────────────────────────────────────────────────
    # 2) Walkway (allure): @floor blocks on the top y-level, *one block in
    #    from the outer wall*. The walkway sits on the inner of the two
    #    wall courses, just below the merlons.
    # ────────────────────────────────────────────────────────────────────
    y_walk = a.y1 - 1  # top course
    # Inner ring (1 block in from the outer wall).
    if a.w >= 4 and a.d >= 4:
        # front/back rows
        for x in range(a.x0 + 1, a.x1 - 1):
            ops.append(PlaceBlock(x, y_walk, a.z0 + 1, "@floor"))
            ops.append(PlaceBlock(x, y_walk, a.z1 - 2, "@floor"))
        # left/right rows
        for z in range(a.z0 + 2, a.z1 - 2):
            ops.append(PlaceBlock(a.x0 + 1, y_walk, z, "@floor"))
            ops.append(PlaceBlock(a.x1 - 2, y_walk, z, "@floor"))

    # ────────────────────────────────────────────────────────────────────
    # 3) Battlements: alternate merlons (@primary) and crenels (air) along
    #    the OUTER edge of the top course. We start by clearing the whole
    #    outer ring at y_walk, then place merlons every other block.
    #    "later wins" lets the air clear first, then merlons overwrite.
    # ────────────────────────────────────────────────────────────────────
    # 3a) Clear the outer top ring with cave_air to form a flat crenel base.
    for x in range(a.x0, a.x1):
        ops.append(PlaceBlock(x, y_walk, a.z0, "minecraft:cave_air"))
        ops.append(PlaceBlock(x, y_walk, a.z1 - 1, "minecraft:cave_air"))
    for z in range(a.z0 + 1, a.z1 - 1):
        ops.append(PlaceBlock(a.x0, y_walk, z, "minecraft:cave_air"))
        ops.append(PlaceBlock(a.x1 - 1, y_walk, z, "minecraft:cave_air"))

    # 3b) Place merlons every other position around the outer ring.
    # Front (z = z0) and back (z = z1-1) edges.
    for x in range(a.x0, a.x1):
        if (x - a.x0) % 2 == 0:
            ops.append(PlaceBlock(x, y_walk, a.z0, "@primary"))
            ops.append(PlaceBlock(x, y_walk, a.z1 - 1, "@primary"))
    # Left (x = x0) and right (x = x1-1) edges.
    for z in range(a.z0, a.z1):
        if (z - a.z0) % 2 == 0:
            ops.append(PlaceBlock(a.x0, y_walk, z, "@primary"))
            ops.append(PlaceBlock(a.x1 - 1, y_walk, z, "@primary"))

    # ────────────────────────────────────────────────────────────────────
    # 4) Stepped foundation: @secondary at y0 along the outer perimeter.
    #    The base reads as 1 block taller than the y0 wall course since
    #    the outer ring of FillHollow at y0 is repainted with @secondary
    #    AND a course of foundation is added on top at y0+1 of the outer
    #    edge to make the stepped foot.
    # ────────────────────────────────────────────────────────────────────
    # 4a) Repaint the outer y0 ring with @secondary (foundation course).
    for x in range(a.x0, a.x1):
        ops.append(PlaceBlock(x, a.y0, a.z0, "@secondary"))
        ops.append(PlaceBlock(x, a.y0, a.z1 - 1, "@secondary"))
    for z in range(a.z0 + 1, a.z1 - 1):
        ops.append(PlaceBlock(a.x0, a.y0, z, "@secondary"))
        ops.append(PlaceBlock(a.x1 - 1, a.y0, z, "@secondary"))

    # 4b) Stepped course: a second ring of @secondary at y0+1, hugging the
    #    outer edge — so the foundation visibly rises 1 block above the
    #    base wall course (the "stepped" part of "stepped foundation").
    y_step = a.y0 + 1
    if y_step < a.y1 - 1:  # don't collide with the merlon course
        for x in range(a.x0, a.x1):
            ops.append(PlaceBlock(x, y_step, a.z0, "@secondary"))
            ops.append(PlaceBlock(x, y_step, a.z1 - 1, "@secondary"))
        for z in range(a.z0 + 1, a.z1 - 1):
            ops.append(PlaceBlock(a.x0, y_step, z, "@secondary"))
            ops.append(PlaceBlock(a.x1 - 1, y_step, z, "@secondary"))

    # ────────────────────────────────────────────────────────────────────
    # 5) Arrow slits: every 5 blocks along each wall, a 2-tall vertical
    #    slit cut into the outer wall. We use `minecraft:cave_air` so the
    #    composer strips it. Slits sit between y_slit0 and y_slit1, above
    #    the stepped foundation and below the merlon course.
    # ────────────────────────────────────────────────────────────────────
    y_slit0 = a.y0 + 2  # above the stepped foundation
    y_slit1 = y_slit0 + 1
    if y_slit1 < y_walk:
        # Front (z=z0) and back (z=z1-1) walls — vary x.
        for z_edge in (a.z0, a.z1 - 1):
            # Start a couple blocks in from the corner so slits don't
            # break the corner stones.
            x = a.x0 + 3
            while x <= a.x1 - 4:
                for yy in (y_slit0, y_slit1):
                    ops.append(PlaceBlock(x, yy, z_edge, "minecraft:cave_air"))
                x += 5
        # Left (x=x0) and right (x=x1-1) walls — vary z.
        for x_edge in (a.x0, a.x1 - 1):
            z = a.z0 + 3
            while z <= a.z1 - 4:
                for yy in (y_slit0, y_slit1):
                    ops.append(PlaceBlock(x_edge, yy, z, "minecraft:cave_air"))
                z += 5

    return ops


# Silence unused-import warnings if a linter ever loads this module without
# touching Rect (kept available for future variants of the walkway floor).
_ = Rect
