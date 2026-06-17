"""Skill: courtyard_indoor.

An indoor open-air patio — a roofless space surrounded by walls, sitting
inside the building footprint. The skill builds:

  * A paved floor at y0 of @secondary (stone paving) covering the full
    AABB footprint.
  * A central 3x3 patch of `minecraft:grass_block` overriding the pavement
    in the middle — the planted area / soil for the "tree" and pots.
  * Four perimeter walls of @primary going from y0 + 1 up to y1 - 1.
    There is intentionally NO ceiling: the courtyard is open to the sky,
    which is the defining feature of an interior patio.
  * Four columns of @primary at the AABB corners going 2-3 blocks higher
    than the wall top (visual posts framing the patio).
  * A central feature: either a `minecraft:flower_pot` sitting on a 1-tall
    @primary pedestal, or a single `minecraft:lantern` on a fence post.
    Style picks one (medieval / fantasy = pedestal + flower_pot; modern =
    lantern post).
  * Four @stairs benches, one against each of the four walls, facing
    inward toward the centre of the patio.
  * 2-4 `minecraft:flower_pot` arranged symmetrically on the pavement
    near the corners of the central grass patch.
  * 1-2 `minecraft:oak_sapling` planted in the grass — the courtyard's
    "tree(s)".

Defensive sizing: clamps the AABB into the 5x3x5 .. 12x5x12 envelope so
tiny inputs still get a working patio and huge inputs stay readable.
Walls always shrink to 12x12 max; pavement always fills whatever was
clamped.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive footprint clamps per spec (5x3x5 .. 12x5x12).
_MIN_W, _MIN_H, _MIN_D = 5, 3, 5
_MAX_W, _MAX_H, _MAX_D = 12, 5, 12


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [5..12, 3..5, 5..12] envelope.

    Origin is preserved; only the upper corner moves.
    """
    w = max(_MIN_W, min(_MAX_W, aabb.w))
    h = max(_MIN_H, min(_MAX_H, aabb.h))
    d = max(_MIN_D, min(_MAX_D, aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Build an indoor courtyard (roofless patio) inside the clamped AABB."""
    a = _clamp_aabb(aabb)
    s = (style or "medieval").lower()
    ops: List[Op] = []

    ops.extend(_floor(a))
    ops.extend(_central_grass(a))
    ops.extend(_walls(a))
    ops.extend(_corner_columns(a))
    ops.extend(_central_feature(a, s))
    ops.extend(_benches(a, materials))
    ops.extend(_flower_pots(a))
    ops.extend(_saplings(a))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Layout helpers
# ────────────────────────────────────────────────────────────────────────


def _floor(a: AABB) -> List[Op]:
    """Stone paving across the full AABB footprint at y0 (@secondary)."""
    return [Rect(a, "@secondary", axis="y", level=a.y0)]


def _central_grass(a: AABB) -> List[Op]:
    """3x3 patch of `minecraft:grass_block` at the centre of the floor.

    Overrides the pavement (later-wins) so the centre reads as soil.
    Clamped so it never spills beyond the AABB on tiny inputs.
    """
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2
    gx0 = max(a.x0, cx - 1)
    gx1 = min(a.x1, cx + 2)
    gz0 = max(a.z0, cz - 1)
    gz1 = min(a.z1, cz + 2)
    patch = AABB(gx0, a.y0, gz0, gx1, a.y0 + 1, gz1)
    return [Rect(patch, "minecraft:grass_block", axis="y", level=a.y0)]


def _walls(a: AABB) -> List[Op]:
    """Four perimeter walls of @primary — NO ceiling (open to the sky)."""
    y0w = a.y0 + 1
    y1w = max(a.y1, y0w + 2)  # at least 2 rows of wall
    ops: List[Op] = []
    # North (z = z0) and South (z = z1 - 1) full slabs
    ops.append(Fill(AABB(a.x0, y0w, a.z0,
                         a.x1, y1w, a.z0 + 1), "@primary"))
    ops.append(Fill(AABB(a.x0, y0w, a.z1 - 1,
                         a.x1, y1w, a.z1), "@primary"))
    # West (x = x0) and East (x = x1 - 1) full slabs
    ops.append(Fill(AABB(a.x0, y0w, a.z0,
                         a.x0 + 1, y1w, a.z1), "@primary"))
    ops.append(Fill(AABB(a.x1 - 1, y0w, a.z0,
                         a.x1, y1w, a.z1), "@primary"))
    return ops


def _corner_columns(a: AABB) -> List[Op]:
    """Four @primary columns at the AABB corners, rising 2-3 blocks above
    the wall top. They visually mark the patio openings."""
    # Column extra height above the wall top (y1).
    extra = 3 if a.h >= 4 else 2
    cy0 = a.y1            # start one above wall top (half-open already)
    cy1 = a.y1 + extra    # half-open
    ops: List[Op] = []
    for (cx, cz) in (
        (a.x0,     a.z0),
        (a.x1 - 1, a.z0),
        (a.x0,     a.z1 - 1),
        (a.x1 - 1, a.z1 - 1),
    ):
        ops.append(Fill(AABB(cx, cy0, cz, cx + 1, cy1, cz + 1), "@primary"))
    return ops


def _central_feature(a: AABB, style: str) -> List[Op]:
    """Centerpiece: a flower-pot-on-pedestal (medieval/fantasy) or a
    lantern post (modern). Both sit on the central grass cell."""
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2
    y_base = a.y0 + 1     # one above the floor (which is at y0)
    ops: List[Op] = []
    if style == "modern":
        # Lantern post: fence at base, lantern on top.
        ops.append(PlaceBlock(cx, y_base, cz, "@fence"))
        ops.append(PlaceBlock(cx, y_base + 1, cz, "minecraft:lantern"))
    else:
        # Pedestal + flower pot.
        ops.append(PlaceBlock(cx, y_base, cz, "@primary"))
        ops.append(PlaceBlock(cx, y_base + 1, cz, "minecraft:flower_pot"))
    return ops


def _benches(a: AABB, materials: Materials) -> List[Op]:
    """4 stairs benches, one against each wall, facing inward.

    Stair `facing` in Minecraft 1.16.5 is the direction the high (back)
    side points — i.e. the player sits looking AWAY from `facing`. So a
    bench against the north wall (z = z0 + 1) should face NORTH so the
    sitter looks south, into the courtyard.

    `@stairs[facing=...]` would not resolve through the placeholder system
    (the bracket suffix breaks `getattr`), so we pre-resolve the stair
    block id here and emit fully-qualified PlaceBlock ops.
    """
    y = a.y0 + 1
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2
    stair = materials.stairs  # e.g. "minecraft:oak_stairs"
    ops: List[Op] = []
    # North wall — bench against z0 + 1, faces north (back to north wall,
    # sitter looks south into the patio).
    if a.z0 + 1 < a.z1 - 1:
        ops.append(PlaceBlock(cx, y, a.z0 + 1, f"{stair}[facing=north]"))
    # South wall — bench against z1 - 2, faces south.
    if a.z1 - 2 > a.z0:
        ops.append(PlaceBlock(cx, y, a.z1 - 2, f"{stair}[facing=south]"))
    # West wall — bench against x0 + 1, faces west.
    if a.x0 + 1 < a.x1 - 1:
        ops.append(PlaceBlock(a.x0 + 1, y, cz, f"{stair}[facing=west]"))
    # East wall — bench against x1 - 2, faces east.
    if a.x1 - 2 > a.x0:
        ops.append(PlaceBlock(a.x1 - 2, y, cz, f"{stair}[facing=east]"))
    return ops


def _flower_pots(a: AABB) -> List[Op]:
    """2-4 `minecraft:flower_pot` arranged symmetrically near the corners
    of the central grass patch, sitting on the pavement (y0 + 1)."""
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2
    y = a.y0 + 1
    # Diagonal cells one block past the corners of the 3x3 grass patch.
    candidates = [
        (cx - 2, cz - 2),
        (cx + 2, cz - 2),
        (cx - 2, cz + 2),
        (cx + 2, cz + 2),
    ]
    ops: List[Op] = []
    placed = 0
    for (px, pz) in candidates:
        # Stay strictly inside the AABB and avoid the wall ring.
        if not (a.x0 + 1 <= px < a.x1 - 1 and a.z0 + 1 <= pz < a.z1 - 1):
            continue
        # Don't overwrite a bench cell. Benches sit at (cx, z0+1),
        # (cx, z1-2), (x0+1, cz), (x1-2, cz).
        if (px == cx and pz in (a.z0 + 1, a.z1 - 2)):
            continue
        if (pz == cz and px in (a.x0 + 1, a.x1 - 2)):
            continue
        ops.append(PlaceBlock(px, y, pz, "minecraft:flower_pot"))
        placed += 1
        if placed >= 4:
            break
    # Guarantee at least 2: on tiny AABBs the four candidates may all
    # fall onto bench or wall cells, so fall back to two slots adjacent
    # to the central grass patch.
    if placed < 2:
        fallback = [
            (cx - 1, cz - 1),
            (cx + 1, cz + 1),
            (cx + 1, cz - 1),
            (cx - 1, cz + 1),
        ]
        for (px, pz) in fallback:
            if placed >= 2:
                break
            if not (a.x0 + 1 <= px < a.x1 - 1 and a.z0 + 1 <= pz < a.z1 - 1):
                continue
            # These cells are on the grass patch — that's fine, a
            # flower pot can sit on grass.
            ops.append(PlaceBlock(px, y, pz, "minecraft:flower_pot"))
            placed += 1
    return ops


def _saplings(a: AABB) -> List[Op]:
    """1-2 `minecraft:oak_sapling` planted in the grass patch.

    One sapling for small AABBs, two for medium+ (>= 8 wide and deep).
    Saplings sit on the grass blocks at y0 + 1.
    """
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2
    y = a.y0 + 1
    ops: List[Op] = []
    # First sapling: one corner of the grass patch (offset from centre
    # so it doesn't clash with the central pedestal at (cx, cz)).
    sx1, sz1 = cx - 1, cz - 1
    if a.x0 + 1 <= sx1 < a.x1 - 1 and a.z0 + 1 <= sz1 < a.z1 - 1:
        ops.append(PlaceBlock(sx1, y, sz1, "minecraft:oak_sapling"))
    # Second sapling on bigger AABBs.
    if a.w >= 8 and a.d >= 8:
        sx2, sz2 = cx + 1, cz + 1
        if a.x0 + 1 <= sx2 < a.x1 - 1 and a.z0 + 1 <= sz2 < a.z1 - 1:
            ops.append(PlaceBlock(sx2, y, sz2, "minecraft:oak_sapling"))
    return ops
