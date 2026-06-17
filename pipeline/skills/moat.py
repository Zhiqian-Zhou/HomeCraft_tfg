"""Skill: moat.

A water-filled defensive trench encircling a building's outer footprint.
The AABB defines the OUTER footprint of the moat; the moat itself is a
2-3 block wide ring hugging the outer edge of that AABB, leaving the
interior open for whatever the moat surrounds (curtain wall, keep, etc.).

Composition (bottom to top):

  - **Trench floor**: a 1-block course of @secondary at y0 covering the
    entire ring (2-3 blocks wide). Water needs an impermeable floor or it
    drains through grass/dirt below.
  - **Outer retaining wall**: a 1-block-tall border of @secondary at y0+1
    around the *outer* perimeter, so water doesn't spill outward.
  - **Inner lip**: a 1-block-tall border of @secondary at y0+1 around the
    *inner* edge of the ring (next to the interior), so water is
    contained on both sides — a classic "scarp + counterscarp" stone
    revetment in miniature.
  - **Water**: `minecraft:water` filling the trench between the two
    retaining edges, exactly 1 block deep (y0+1). The composer's
    "later wins" rule lets the water overwrite any earlier fill.
  - **Lily pads**: 2-3 `minecraft:lily_pad` floating on the water at
    y0+2, scattered around the ring (front, back, and a side mid-point).
  - **Corner posts**: 1-block `minecraft:cobblestone_wall` at the four
    outer corners, sitting on top of the outer retaining wall at y0+2,
    as decorative bollards / mooring posts.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Defensive sizing: clamped to 6×2×6 .. 24×3×24. Below 6×6 the ring would
collapse into a solid 2×2 square with no interior, so we enforce the
minimum to guarantee an actual trench.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, Fill, PlaceBlock


# Defensive bounds, per spec.
_MIN = (6, 2, 6)
_MAX = (24, 3, 24)

# Ring width in blocks. Chosen 2 for small AABBs and 3 for larger ones to
# give the moat visual heft without crowding small footprints.
def _ring_width(aabb: AABB) -> int:
    return 3 if min(aabb.w, aabb.d) >= 12 else 2


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [6..24, 2..3, 6..24] envelope.

    Lower corner preserved; upper corner shifted to satisfy the bounds.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def _ring_cells(a: AABB, t: int) -> List[tuple[int, int]]:
    """Enumerate (x, z) cells of the ring of width `t` along the outer edge."""
    out: List[tuple[int, int]] = []
    for x in range(a.x0, a.x1):
        for z in range(a.z0, a.z1):
            in_outer = (x < a.x0 + t or x >= a.x1 - t
                        or z < a.z0 + t or z >= a.z1 - t)
            if in_outer:
                out.append((x, z))
    return out


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a moat: stone-floored ring trench, retaining lips, water, lily
    pads, and corner posts."""
    a = _clamp_aabb(aabb)
    t = _ring_width(a)
    ops: List[Op] = []

    # ────────────────────────────────────────────────────────────────────
    # 1) Trench floor: a ring of @secondary at y0. We emit one PlaceBlock
    #    per ring cell so we don't accidentally floor the interior (which
    #    might already hold a wall or keep).
    # ────────────────────────────────────────────────────────────────────
    ring = _ring_cells(a, t)
    for (x, z) in ring:
        ops.append(PlaceBlock(x, a.y0, z, "@secondary"))

    # ────────────────────────────────────────────────────────────────────
    # 2) Outer retaining wall: 1-block-tall @secondary along the OUTER
    #    perimeter at y0+1. Keeps water from spilling outward.
    # ────────────────────────────────────────────────────────────────────
    y_lip = a.y0 + 1
    for x in range(a.x0, a.x1):
        ops.append(PlaceBlock(x, y_lip, a.z0, "@secondary"))
        ops.append(PlaceBlock(x, y_lip, a.z1 - 1, "@secondary"))
    for z in range(a.z0 + 1, a.z1 - 1):
        ops.append(PlaceBlock(a.x0, y_lip, z, "@secondary"))
        ops.append(PlaceBlock(a.x1 - 1, y_lip, z, "@secondary"))

    # ────────────────────────────────────────────────────────────────────
    # 3) Inner lip: 1-block-tall @secondary around the INNER edge of the
    #    ring at y0+1. Separates the moat from whatever sits in the
    #    interior. Only emitted if the interior is non-empty.
    # ────────────────────────────────────────────────────────────────────
    ix0, iz0 = a.x0 + t, a.z0 + t
    ix1, iz1 = a.x1 - t, a.z1 - t
    if ix1 > ix0 and iz1 > iz0:
        # Inner edge sits 1 block outside the interior, i.e. at ix0 - 1, etc.
        ex0, ez0 = ix0 - 1, iz0 - 1
        ex1, ez1 = ix1, iz1  # inclusive-style last index handled below
        for x in range(ex0, ex1 + 1):
            ops.append(PlaceBlock(x, y_lip, ez0, "@secondary"))
            ops.append(PlaceBlock(x, y_lip, ez1, "@secondary"))
        for z in range(ez0 + 1, ez1):
            ops.append(PlaceBlock(ex0, y_lip, z, "@secondary"))
            ops.append(PlaceBlock(ex1, y_lip, z, "@secondary"))

    # ────────────────────────────────────────────────────────────────────
    # 4) Water: fill the trench between outer wall and inner lip with
    #    `minecraft:water`, exactly 1 block deep at y0+1. We paint over
    #    the whole ring then re-stamp the outer and inner lips above so
    #    "later wins" gives us the right silhouette. Easier: walk the
    #    ring and place water only on cells that are strictly between
    #    the two lips.
    # ────────────────────────────────────────────────────────────────────
    for (x, z) in ring:
        on_outer = (x == a.x0 or x == a.x1 - 1
                    or z == a.z0 or z == a.z1 - 1)
        on_inner_lip = False
        if ix1 > ix0 and iz1 > iz0:
            on_inner_lip = (
                (x == ix0 - 1 and iz0 - 1 <= z <= iz1)
                or (x == ix1 and iz0 - 1 <= z <= iz1)
                or (z == iz0 - 1 and ix0 - 1 <= x <= ix1)
                or (z == iz1 and ix0 - 1 <= x <= ix1)
            )
        if not on_outer and not on_inner_lip:
            ops.append(PlaceBlock(x, y_lip, z, "minecraft:water"))

    # ────────────────────────────────────────────────────────────────────
    # 5) Lily pads: 2-3 floating on top of the water at y0+2. We pick
    #    a handful of points around the ring's mid-axes that we know are
    #    water cells (not on either lip). Skip any that fall outside the
    #    water band.
    # ────────────────────────────────────────────────────────────────────
    y_pad = a.y0 + 2
    candidates: List[tuple[int, int]] = []
    mid_x = (a.x0 + a.x1) // 2
    mid_z = (a.z0 + a.z1) // 2
    # Pick a water cell in the middle of each outer face.
    if t >= 1:
        # north face (z = z0 + (t//2)), south face, west face, east face
        wz = a.z0 + max(1, t // 2 + (0 if t == 2 else 0))
        # Simpler: aim for the row just inside the outer wall (z = z0+1, z1-2).
        candidates.append((mid_x, a.z0 + 1))
        candidates.append((mid_x, a.z1 - 2))
        candidates.append((a.x0 + 1, mid_z))
    placed_pads = 0
    max_pads = 3 if min(a.w, a.d) >= 10 else 2
    for (x, z) in candidates:
        if placed_pads >= max_pads:
            break
        # Verify it really is a water cell: in the ring, not on outer
        # perimeter, not on the inner lip.
        in_ring = (x < a.x0 + t or x >= a.x1 - t
                   or z < a.z0 + t or z >= a.z1 - t)
        on_outer = (x == a.x0 or x == a.x1 - 1
                    or z == a.z0 or z == a.z1 - 1)
        on_inner_lip = False
        if ix1 > ix0 and iz1 > iz0:
            on_inner_lip = (
                (x == ix0 - 1 and iz0 - 1 <= z <= iz1)
                or (x == ix1 and iz0 - 1 <= z <= iz1)
                or (z == iz0 - 1 and ix0 - 1 <= x <= ix1)
                or (z == iz1 and ix0 - 1 <= x <= ix1)
            )
        if in_ring and not on_outer and not on_inner_lip:
            ops.append(PlaceBlock(x, y_pad, z, "minecraft:lily_pad"))
            placed_pads += 1

    # ────────────────────────────────────────────────────────────────────
    # 6) Corner posts: 1-block `cobblestone_wall` at the four outer
    #    corners, sitting on top of the outer retaining wall at y0+2.
    #    Decorative bollards. Skip if h < 3 (no room above the water).
    # ────────────────────────────────────────────────────────────────────
    if a.h >= 3:
        y_post = a.y0 + 2
        for (cx, cz) in ((a.x0, a.z0), (a.x1 - 1, a.z0),
                         (a.x0, a.z1 - 1), (a.x1 - 1, a.z1 - 1)):
            ops.append(PlaceBlock(cx, y_post, cz, "minecraft:cobblestone_wall"))

    return ops


# Silence unused-import warning if a linter loads this module without
# touching `Fill` (kept for future variants with deeper trenches).
_ = Fill
