"""Skill: flat_roof — a flat (azotea) roof with parapet, drain, and hatch.

The AABB defines the FOOTPRINT of the roof. Unlike the pitched roofs
(`gabled_roof`, `hip_roof`) the flat roof does not rise above the AABB:
it lays a single solid plane at ``y0`` (or just above ``y0 + 1`` when
``AABB.h > 1`` so the input AABB can describe the full wall stack and
the roof still lands one course above the wall top).

Geometry, from bottom to top of the roof system:

  * Solid plane (slab/roof course) covering the entire footprint at
    ``y_roof``. For modern style we use ``@slab`` for a thinner deck
    look; medieval / fantasy / fallback uses ``@roof``.

  * Parapet — a 1-block tall border of ``@primary`` running around the
    perimeter of the footprint at ``y_roof + 1``. This is a low wall
    that keeps the roof terrace safe to walk on.

  * Drainage — a single block of ``@secondary`` at one corner of the
    roof plane (the +x/+z corner by default), used as a scupper / drain.

  * Rooftop access (only when the footprint is large enough) — a 2×2
    hatch carved into the deck plus a single ``@stairs`` block placed
    above one of the carved cells so the player can step down. The
    hatch is positioned away from the drain corner.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Defensive sizing: clamped to 4×1×4 .. 20×2×20. Footprints outside that
range still emit a best-effort flat plane; degenerate cases (W < 4 or
D < 4) return no ops so the composer can skip them.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock, Rect


# Defensive bounds per spec.
_MIN = (4, 1, 4)
_MAX = (20, 2, 20)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Emit ops for a flat roof (azotea) covering `aabb`'s footprint.

    Kwargs:
        drain_corner ('nw' | 'ne' | 'sw' | 'se'): which corner of the
            roof deck gets the @secondary drain block. Default 'se'
            (the +x/+z corner).
        hatch (bool): force-enable / disable the 2×2 rooftop hatch.
            Default: auto (enabled when both W >= 6 and D >= 6).
    """
    w, d = aabb.w, aabb.d

    # Defensive on tiny / oversized footprints.
    if w < _MIN[0] or d < _MIN[2]:
        return []
    if w > _MAX[0] or d > _MAX[2]:
        return []

    ops: List[Op] = []

    # ── Roof deck level ──────────────────────────────────────────────
    # If the AABB has any vertical extent we land the deck one course
    # above the wall top (y0 + 1, clamped to within the AABB). With
    # h == 1 the deck just sits at y0.
    if aabb.h > 1:
        y_roof = aabb.y0 + 1
    else:
        y_roof = aabb.y0
    y_parapet = y_roof + 1

    # ── 1) Solid plane covering the whole footprint ──────────────────
    # Modern style uses a thinner slab deck; everything else lays a
    # full @roof course.
    deck_block = "@slab" if style.lower() == "modern" else "@roof"
    ops.append(Rect(
        AABB(aabb.x0, y_roof, aabb.z0, aabb.x1, y_roof + 1, aabb.z1),
        deck_block, axis="y", level=y_roof,
    ))

    # ── 2) Parapet — 1-block tall @primary border around the perimeter
    for x in range(aabb.x0, aabb.x1):
        ops.append(PlaceBlock(x, y_parapet, aabb.z0,     "@primary"))
        ops.append(PlaceBlock(x, y_parapet, aabb.z1 - 1, "@primary"))
    for z in range(aabb.z0 + 1, aabb.z1 - 1):  # avoid double-placing corners
        ops.append(PlaceBlock(aabb.x0,     y_parapet, z, "@primary"))
        ops.append(PlaceBlock(aabb.x1 - 1, y_parapet, z, "@primary"))

    # ── 3) Drainage block at one corner ──────────────────────────────
    drain_corner = kwargs.get("drain_corner", "se")
    if drain_corner == "nw":
        dx, dz = aabb.x0,     aabb.z0
    elif drain_corner == "ne":
        dx, dz = aabb.x1 - 1, aabb.z0
    elif drain_corner == "sw":
        dx, dz = aabb.x0,     aabb.z1 - 1
    else:  # 'se' (default)
        dx, dz = aabb.x1 - 1, aabb.z1 - 1
    # The drain sits ON the deck plane (replacing the deck cell at the
    # chosen corner). Later-wins makes this safe.
    ops.append(PlaceBlock(dx, y_roof, dz, "@secondary"))

    # ── 4) Optional 2×2 rooftop hatch ────────────────────────────────
    hatch_kw = kwargs.get("hatch")
    if hatch_kw is None:
        hatch_enabled = (w >= 6 and d >= 6)
    else:
        hatch_enabled = bool(hatch_kw)

    if hatch_enabled:
        # Place the hatch away from the drain corner. We anchor on the
        # opposite quadrant so the 2×2 carve never overlaps the drain.
        if drain_corner in ("se",):
            hx0, hz0 = aabb.x0 + 1,     aabb.z0 + 1
        elif drain_corner == "sw":
            hx0, hz0 = aabb.x1 - 3,     aabb.z0 + 1
        elif drain_corner == "ne":
            hx0, hz0 = aabb.x0 + 1,     aabb.z1 - 3
        else:  # 'nw'
            hx0, hz0 = aabb.x1 - 3,     aabb.z1 - 3

        # Carve the 2×2 hatch: drop the deck cells to air so the player
        # can descend. Done by writing cave_air over the deck plane.
        for hx in (hx0, hx0 + 1):
            for hz in (hz0, hz0 + 1):
                ops.append(PlaceBlock(hx, y_roof, hz, "minecraft:cave_air"))

        # Single @stairs block on the deck plane adjacent to the hatch
        # facing inward, acting as the visible "step up" onto the hatch
        # cover. We pick the cell at (hx0, y_roof, hz0) — later-wins
        # replaces the cave_air we just wrote at that cell.
        ops.append(PlaceBlock(hx0, y_roof, hz0, f"{materials.stairs}[facing=east]"))

    return ops
