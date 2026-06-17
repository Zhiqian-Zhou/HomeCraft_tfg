"""Geometry helpers for typologies.

Translate the `geom.*` primitives from TFGv2's variety packs into the
AABB→List[Op] contract of TFGv2Z. The atomic Op classes
(`Fill`, `FillHollow`, `PlaceBlock`, `Outline`, `Cylinder`, ...) already
cover most cases; the helpers below fill in the few that don't.

All helpers return `list[Op]` so they compose with the rest of a
typology's body. Block IDs may use material placeholders ("@primary",
"@accent", ...) which the composer resolves against the active Materials.

The `circle_xz()` function is a coordinate utility — returns (x, z) pairs
— used internally by the cylindrical helpers and exposed for typologies
that need custom Bresenham circle sampling.
"""
from __future__ import annotations

import math

from ..base import AABB, Op, PlaceBlock, Rect


def crenellated_ring(aabb_top: AABB, block: str) -> list[Op]:
    """Single-course crenellated parapet sitting at y == aabb_top.y0.

    Walks the rectangular perimeter of `aabb_top` (assumed thin: h == 1) and
    places `block` at every other position on each edge. The skipped cells
    stay as air — that's the crenel gap. Corner cells are placed once
    (handled by the N/S edge sweep).

    Args:
        aabb_top: the AABB describing the parapet course. Use h=1 — only
            the y == aabb_top.y0 plane is consumed.
        block: block id or placeholder (e.g. "@primary").

    Returns:
        List of `PlaceBlock` ops, one per merlon cell.
    """
    ops: list[Op] = []
    y = aabb_top.y0
    x0, x1 = aabb_top.x0, aabb_top.x1 - 1   # inclusive corners for the ring
    z0, z1 = aabb_top.z0, aabb_top.z1 - 1

    # North and south edges (z == z0 and z == z1): place every-other along x.
    for i, x in enumerate(range(x0, x1 + 1)):
        if i % 2 == 0:
            ops.append(PlaceBlock(x=x, y=y, z=z0, block=block))
            if z1 != z0:
                ops.append(PlaceBlock(x=x, y=y, z=z1, block=block))

    # West and east edges (x == x0 and x == x1): place every-other along z,
    # SKIPPING the corner cells already placed above.
    for j, z in enumerate(range(z0 + 1, z1)):
        if j % 2 == 0:
            ops.append(PlaceBlock(x=x0, y=y, z=z, block=block))
            if x1 != x0:
                ops.append(PlaceBlock(x=x1, y=y, z=z, block=block))

    return ops


def vertical_strip(x: int, z: int, y0: int, height: int,
                   block: str) -> list[Op]:
    """One-block-wide vertical column of `block` from (x, y0, z) up `height`."""
    return [PlaceBlock(x=x, y=y0 + dy, z=z, block=block)
            for dy in range(height)]


def carve_slit(x: int, z: int, y: int, length: int,
               axis: str = "y") -> list[Op]:
    """Carve `length` air blocks starting at (x, y, z), advancing along `axis`.

    Use to punch arrow-slit windows through a wall. The composer drops air
    voxels (later-wins), so emitting air after a Fill effectively carves it.
    """
    ops: list[Op] = []
    for i in range(length):
        if axis == "y":
            ops.append(PlaceBlock(x=x, y=y + i, z=z, block="minecraft:air"))
        elif axis == "x":
            ops.append(PlaceBlock(x=x + i, y=y, z=z, block="minecraft:air"))
        else:  # "z"
            ops.append(PlaceBlock(x=x, y=y, z=z + i, block="minecraft:air"))
    return ops


def hollow_wall_ring(aabb: AABB, block: str) -> list[Op]:
    """Four-wall perimeter ring of `block`, no floor or ceiling.

    Equivalent to a `FillHollow` minus the floor and ceiling planes. Use
    for tower shells where you want the bottom and top open (e.g. a
    cylinder cap will close the top, a separate floor plane the bottom).
    Implemented as four `Rect` planes — one per side — so the composer
    can later-wins-override any cell cheaply.
    """
    a = aabb
    return [
        Rect(aabb=a, block=block, axis="z", level=a.z0),         # south wall
        Rect(aabb=a, block=block, axis="z", level=a.z1 - 1),     # north wall
        Rect(aabb=a, block=block, axis="x", level=a.x0),         # west wall
        Rect(aabb=a, block=block, axis="x", level=a.x1 - 1),     # east wall
    ]


def circle_xz(cx: int, cz: int, r: int) -> list[tuple[int, int]]:
    """Bresenham midpoint circle perimeter cells, deduplicated and sorted.

    Returns (x, z) coordinate pairs — pure utility, not Ops. Useful when a
    typology needs custom per-cell logic (e.g. alternate blocks around a
    spire) instead of a uniform `Cylinder` call.
    """
    cells: set[tuple[int, int]] = set()
    x = r
    z = 0
    err = 0
    while x >= z:
        for dx, dz in ((x, z), (z, x), (-z, x), (-x, z),
                       (-x, -z), (-z, -x), (z, -x), (x, -z)):
            cells.add((cx + dx, cz + dz))
        z += 1
        if err <= 0:
            err += 2 * z + 1
        else:
            x -= 1
            err += 2 * (z - x) + 1
    return sorted(cells)


def crenellated_circle(cx: int, cz: int, y: int, r: int,
                       block: str) -> list[Op]:
    """Alternating merlons on a circular parapet at height `y`.

    Walks the Bresenham circle of radius `r` and places `block` at every
    other cell — the rest stay air (crenel gaps). Used for round towers
    (drum towers, lighthouses, wizard towers).
    """
    return [
        PlaceBlock(x=x, y=y, z=z, block=block)
        for i, (x, z) in enumerate(circle_xz(cx, cz, r))
        if i % 2 == 0
    ]


def conical_spire(cx: int, cz: int, base_y: int, base_radius: int,
                  height: int, block: str,
                  cap_block: str | None = None) -> list[Op]:
    """Tapered conical spire stepping inward as it rises.

    At height-offset `i`, radius = max(0, round(base_radius * (1 - i/(height-1)))).
    The tip is a single `cap_block` (or `block` if cap is None). Used for
    tower roofs (pepperpot, pagoda, observatory), spires, and finials.
    """
    ops: list[Op] = []
    denom = max(1, height - 1)
    for i in range(height):
        t = i / denom
        r = max(0, round(base_radius * (1 - t)))
        if r <= 0:
            # Tip: single cap block.
            ops.append(PlaceBlock(x=cx, y=base_y + i, z=cz,
                                  block=cap_block or block))
            continue
        for (x, z) in circle_xz(cx, cz, r):
            ops.append(PlaceBlock(x=x, y=base_y + i, z=z, block=block))
    return ops


def pyramid_square(cx: int, cz: int, base_y: int, base_half: int,
                   height: int, block: str) -> list[Op]:
    """Stepped square pyramid — perimeter at each layer, narrowing upward.

    `base_half` is the half-side length at y == base_y (so the bottom face
    is `(2 * base_half + 1)` blocks across). Only the perimeter ring at
    each layer is emitted; if you want a solid pyramid stack consecutive
    `Fill` ops instead. Used for pyramidal tower caps and parapet roofs.
    """
    ops: list[Op] = []
    denom = max(1, height - 1)
    for i in range(height):
        t = i / denom
        half = max(0, round(base_half * (1 - t)))
        for x in range(cx - half, cx + half + 1):
            for z in range(cz - half, cz + half + 1):
                if (x in (cx - half, cx + half)
                        or z in (cz - half, cz + half)):
                    ops.append(PlaceBlock(x=x, y=base_y + i, z=z, block=block))
    return ops


def onion_dome(cx: int, cz: int, base_y: int, base_radius: int,
               height: int, block: str,
               finial_block: str | None = None) -> list[Op]:
    """Onion-dome profile (bulged sine) capped with a short spire.

    The main body is `height - 3` blocks tall; radius follows
    `r(t) = base_radius * (0.55 + 1.1 * sin(t * pi))` clamped to ≥1,
    with a small inset near the top. The remaining 3 blocks are the
    centered spire built from `finial_block` (or `block` if None).
    Used for minarets, mosques, fantasy temples.
    """
    ops: list[Op] = []
    spire = 3
    main = max(1, height - spire)
    denom = max(1, main - 1)
    for i in range(main):
        t = i / denom
        # Bulged sine profile — broadens near t=0.5, tapers at the top.
        r = max(1, round(base_radius * (0.55 + 1.1 * math.sin(t * math.pi))))
        if t > 0.85:
            r = max(1, r - 1)
        for (x, z) in circle_xz(cx, cz, r):
            ops.append(PlaceBlock(x=x, y=base_y + i, z=z, block=block))
    # Spire on top.
    for k in range(spire):
        ops.append(PlaceBlock(x=cx, y=base_y + main + k, z=cz,
                              block=finial_block or block))
    return ops
