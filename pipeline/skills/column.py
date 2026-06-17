"""Skill: column — a single column with base, shaft, and capital.

The AABB defines the FOOTPRINT of the column on the ground plane (typically
1×H×1 for a slim pillar, 2×H×2 for a chunky one, or 3×H×3 for a monumental
order). The skill emits three coupled subsystems:

  * Base: the bottom course (y == y0). For footprints wider than 1×1 it is
    a flat pad of @accent that is slightly wider than the shaft above it
    (the whole AABB cross-section). For a true 1-wide footprint there is
    no room to be "wider", so we fall back to a single @primary block to
    keep the silhouette honest.
  * Shaft: a solid vertical Fill of @primary from y0+1 up to y_top-1. The
    shaft footprint is the AABB inset by 1 cell on every side when the
    AABB is ≥ 3 wide (so the base genuinely sticks out); otherwise the
    shaft inherits the full footprint.
  * Capital: a crown at y_top that varies with `style_variant`:
        - 'doric'      : a flat @accent slab/cap matching the base footprint.
        - 'ionic'      : @accent footprint plus a ring of @stairs facing
                         outward on each side (the volute-like flare).
        - 'corinthian' : @accent footprint plus stairs on all four sides
                         AND a second smaller @accent cap one block higher
                         (when there is vertical room) to suggest the
                         foliate stacking of the Corinthian order.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Defensive sizing: clamped to 1×3×1 .. 3×12×3.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock


# Defensive bounds per spec.
_MIN = (1, 3, 1)
_MAX = (3, 12, 3)

_VARIANTS = ("doric", "ionic", "corinthian")


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [1..3, 3..12, 1..3] envelope.

    The lower corner is preserved; the upper corner is shifted so the
    column footprint and height stay inside the allowed range. We also
    snap the footprint to be square-ish when the input is asymmetric
    (the wider of the two horizontal extents wins, then is clamped),
    because columns are visually square in plan.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    # Square the footprint: a column should look round-ish in plan, so we
    # take the larger of (w, d) and clamp once more.
    side = max(w, d)
    side = max(_MIN[0], min(_MAX[0], side))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + side, aabb.y0 + h, aabb.z0 + side)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a column inside `aabb`.

    Kwargs:
        style_variant ('doric' | 'ionic' | 'corinthian'): order of the
            capital. Defaults to 'doric'. Unknown values are coerced to
            'doric' so the skill always emits a valid column.
    """
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    variant = str(kwargs.get("style_variant", "doric")).lower()
    if variant not in _VARIANTS:
        variant = "doric"

    y_base = a.y0
    y_top = a.y1 - 1
    # Shaft span: from one above the base to one below the capital.
    shaft_y0 = y_base + 1
    shaft_y1 = y_top  # half-open, so shaft occupies [shaft_y0, shaft_y1)

    is_thin = (a.w == 1 or a.d == 1)

    # ───────────────────────────────────────────────────────────────
    # 1) Base course at y_base.
    #    - For footprints ≥ 2-wide: a flat @accent pad that occupies the
    #      whole AABB cross-section (it visually flares wider than the
    #      shaft above, which is inset by 1 when ≥ 3-wide).
    #    - For 1-wide footprints: a single @primary block (no room to
    #      flare).
    # ───────────────────────────────────────────────────────────────
    if is_thin:
        # 1×H×1 column — base is just one @primary block on the ground.
        ops.append(PlaceBlock(a.x0, y_base, a.z0, "@primary"))
    else:
        ops.append(Fill(
            AABB(a.x0, y_base, a.z0, a.x1, y_base + 1, a.z1),
            "@accent",
        ))

    # ───────────────────────────────────────────────────────────────
    # 2) Shaft: solid vertical Fill of @primary.
    #    - For ≥ 3-wide footprints, inset by 1 on each horizontal side
    #      so the base is genuinely wider than the shaft.
    #    - Otherwise the shaft inherits the full footprint.
    # ───────────────────────────────────────────────────────────────
    if shaft_y1 > shaft_y0:
        if a.w >= 3 and a.d >= 3:
            shaft_box = AABB(a.x0 + 1, shaft_y0, a.z0 + 1,
                             a.x1 - 1, shaft_y1, a.z1 - 1)
        else:
            shaft_box = AABB(a.x0, shaft_y0, a.z0, a.x1, shaft_y1, a.z1)
        if shaft_box.w > 0 and shaft_box.d > 0:
            ops.append(Fill(shaft_box, "@primary"))

    # ───────────────────────────────────────────────────────────────
    # 3) Capital at y_top — geometry depends on `style_variant`.
    # ───────────────────────────────────────────────────────────────
    if y_top >= shaft_y0 or y_top == y_base + 1:
        # Doric base cap = flat @accent slab over the full footprint
        # (or a single @accent block for 1-wide columns).
        if is_thin:
            ops.append(PlaceBlock(a.x0, y_top, a.z0, "@accent"))
        else:
            ops.append(Fill(
                AABB(a.x0, y_top, a.z0, a.x1, y_top + 1, a.z1),
                "@accent",
            ))

        # Ionic / Corinthian add a flared ring of stairs facing outward
        # on each side. Only meaningful for footprints ≥ 2-wide AND when
        # there is at least one cell of space above the shaft (otherwise
        # the stairs would overwrite the base on a degenerate column).
        if variant in ("ionic", "corinthian") and not is_thin:
            # Stairs are placed at y_top facing outward from each edge.
            # For a 2×2 footprint every cell is a corner, so we still
            # emit "facing" hints based on which face the cell sits on.
            for x in range(a.x0, a.x1):
                for z in range(a.z0, a.z1):
                    on_west = (x == a.x0)
                    on_east = (x == a.x1 - 1)
                    on_north = (z == a.z0)
                    on_south = (z == a.z1 - 1)
                    if not (on_west or on_east or on_north or on_south):
                        # Interior of the capital — leave the @accent slab
                        # already placed by the doric pass.
                        continue
                    # Pick a primary facing: prefer the side with the
                    # longest run (so a 3×3 column's corners face out
                    # diagonally via the east/west axis preferentially).
                    if on_east:
                        facing = "east"
                    elif on_west:
                        facing = "west"
                    elif on_south:
                        facing = "south"
                    else:
                        facing = "north"
                    ops.append(PlaceBlock(x, y_top, z, f"@stairs[facing={facing}]"))

        # Corinthian: stack a second smaller @accent cap one cell above
        # the first, if the AABB still has vertical room. This evokes
        # the layered abacus + foliate cushion of the Corinthian order.
        if variant == "corinthian" and not is_thin:
            y_top2 = y_top + 1
            if y_top2 < a.y1:
                # One-cell-inset cap so it visibly steps inward.
                cx0 = a.x0 + 1 if a.w >= 3 else a.x0
                cx1 = a.x1 - 1 if a.w >= 3 else a.x1
                cz0 = a.z0 + 1 if a.d >= 3 else a.z0
                cz1 = a.z1 - 1 if a.d >= 3 else a.z1
                if cx1 > cx0 and cz1 > cz0:
                    ops.append(Fill(
                        AABB(cx0, y_top2, cz0, cx1, y_top2 + 1, cz1),
                        "@accent",
                    ))

    return ops
