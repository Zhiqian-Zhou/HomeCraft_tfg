"""Skill: stable.

A covered structure for animals (horses, cows, etc.). The front face is left
open so animals can walk in/out; the other three sides are solid walls. A
simple shed-style sloped roof of stairs faces inward toward the back of the
stable, evoking a lean-to barn silhouette.

Layout (in AABB local coords; `front` = +x face, `back` = -x face by default):
    * Floor: a full plane of @floor at y0, with `minecraft:hay_block` patches
      scattered as straw bedding (1 per stall + a couple extras).
    * Walls (3 of 4): @primary slabs spanning the wall height on north,
      south and back faces. The front face (x = x1-1) is intentionally left
      open for animal access.
    * Sloped roof: a row of @stairs at y = y1-1 along the back of the
      structure facing inward (toward the open front), with a flat ridge of
      @roof along the front edge — gives the silhouette of a lean-to shed.
    * Stall partitions: the interior depth (z axis) is subdivided into 2-3
      stalls using @fence partitions running perpendicular to the open
      front. Each partition is 1 block wide and 2 high.
    * Per stall (deterministic offsets):
        - 1 `minecraft:hay_block` near the back wall (food / bedding).
        - 1 `minecraft:cauldron[level=3]` (water source).
        - 1 `minecraft:barrel[facing=up]` (tack / feed storage).
    * Rafters: 1-2 `minecraft:lantern` hanging from the underside of the
      roof along the central long axis.
    * Saddle holders: 1+ `minecraft:armor_stand` placed near the front of
      each stall as a proxy for a saddle / tack rack.

Defensive sizing: clamped to 6×4×4 .. 14×5×6 (width × height × depth). The
short axis (depth) controls the number of stalls (2 or 3); the long axis
controls how deep each stall goes.

Material role usage:
    @primary  — solid walls (3 sides)
    @floor    — floor plane (hay patches override)
    @roof     — flat ridge along the open front
    @stairs   — sloped roof course facing inward
    @fence    — stall partitions
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive bounds per spec: (width, height, depth).
_MIN = (6, 4, 4)
_MAX = (14, 5, 6)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the defensive envelope.

    Keeps the lower corner fixed; shifts the upper corner so the size
    constraints hold. Tiny inputs grow to 6x4x4; huge inputs shrink to
    14x5x6.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def _roof_block_for_style(style: str) -> str:
    """Style-aware roof block.

    medieval / default → dark_oak roofing planks (rustic shed feel)
    modern             → smooth_stone (clean monolithic shed)
    fantasy            → dark_oak with purpur accent (handled in build)
    """
    s = (style or "").lower()
    if s == "modern":
        return "minecraft:smooth_stone"
    if s == "fantasy":
        return "minecraft:dark_oak_planks"
    return "minecraft:dark_oak_planks"


def _stair_block_for_style(style: str) -> str:
    """Style-aware stairs block used for the sloped roof."""
    s = (style or "").lower()
    if s == "modern":
        return "minecraft:smooth_stone_stairs[facing=east,half=bottom]"
    if s == "fantasy":
        return "minecraft:dark_oak_stairs[facing=east,half=bottom]"
    return "minecraft:dark_oak_stairs[facing=east,half=bottom]"


def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Build a stable / animal shelter inside `aabb`.

    Open front (+x face) for animal access, 3 walls, sloped shed roof,
    interior stalls with hay + water + storage, lanterns and saddle stands.
    """
    a = _clamp_aabb(aabb)
    s = (style or "medieval").lower()
    ops: List[Op] = []

    x0, y0, z0 = a.x0, a.y0, a.z0
    x1, y1, z1 = a.x1, a.y1, a.z1
    w, h, d = a.w, a.h, a.d

    # ──────────────────────── 1) Floor + hay patches ────────────────────
    # Solid floor plane at y0.
    ops.append(
        Rect(AABB(x0, y0, z0, x1, y0 + 1, z1),
             "@floor", axis="y", level=y0)
    )
    # Hay patches: scatter a handful on top of the floor (later-wins).
    # We place hay near the back third of the stable to read as bedding.
    hay_x_back = x0 + 1  # one block in from the back wall
    for z in range(z0 + 1, z1 - 1, 2):
        ops.append(PlaceBlock(hay_x_back, y0, z, "minecraft:hay_block"))
    # Plus one extra patch in the middle column for visual variety.
    mid_x = (x0 + x1 - 1) // 2
    mid_z = (z0 + z1 - 1) // 2
    ops.append(PlaceBlock(mid_x, y0, mid_z, "minecraft:hay_block"))

    # ──────────────────────── 2) Three walls (open front) ───────────────
    # Front is the +x face (x = x1-1) — left open. The other three faces
    # (back, north, south) are solid @primary slabs from y0+1 up to y1-1
    # so the top row is reserved for the roof course.
    y0w = y0 + 1
    y1w = max(y1 - 1, y0w + 1)

    # Back wall (x = x0)
    ops.append(Fill(AABB(x0, y0w, z0, x0 + 1, y1w, z1), "@primary"))
    # North wall (z = z0) — spans the full x range so the corner aligns
    # with the back wall (later-wins keeps the @primary block on shared
    # cells).
    ops.append(Fill(AABB(x0, y0w, z0, x1, y1w, z0 + 1), "@primary"))
    # South wall (z = z1 - 1)
    ops.append(Fill(AABB(x0, y0w, z1 - 1, x1, y1w, z1), "@primary"))
    # Front (x = x1 - 1) is intentionally NOT walled.

    # Front-top header: a single row of @primary across the open front at
    # the very top of the walls, so the roof has something to land on and
    # we keep the side wall corners visually closed.
    # (One block at each of the front corners, then the front-top ridge
    # is provided by the roof course below.)
    ops.append(PlaceBlock(x1 - 1, y1w - 1, z0, "@primary"))
    ops.append(PlaceBlock(x1 - 1, y1w - 1, z1 - 1, "@primary"))

    # ──────────────────────── 3) Sloped shed roof ───────────────────────
    # A simple shed roof: a flat ridge of @roof along the back top edge,
    # plus a row of @stairs facing east (toward the open front) at the
    # next row down on the front side. This evokes a lean-to slope from
    # back-high to front-low.
    y_roof_top = y1 - 1            # top course (back, high)
    roof_block = _roof_block_for_style(s)
    stair_block = _stair_block_for_style(s)

    # Ridge plank along the back (covers the back top row).
    for z in range(z0, z1):
        ops.append(PlaceBlock(x0, y_roof_top, z, roof_block))

    # Slope: stairs facing east at the same Y across the middle of the
    # width. They sit one block forward of the ridge.
    for x in range(x0 + 1, x1):
        for z in range(z0, z1):
            # The stair tier descends as x increases; we keep them all on
            # the same y_roof_top for a single-pitch lean-to (engine will
            # render the stair triangle anyway).
            ops.append(PlaceBlock(x, y_roof_top, z, stair_block))

    # Fantasy: drop a purpur accent at the central front of the ridge.
    if s == "fantasy":
        ops.append(PlaceBlock(x1 - 1, y_roof_top, (z0 + z1 - 1) // 2,
                              "minecraft:purpur_block"))

    # ──────────────────────── 4) Stall partitions (fences) ──────────────
    # Subdivide the interior depth into 2 or 3 stalls. Each stall is a
    # band of full-width interior space between two z-cut partitions.
    # Pick number of stalls from the depth:
    #   d == 4  → 2 stalls
    #   d == 5  → 2 stalls
    #   d == 6  → 3 stalls
    n_stalls = 3 if d >= 6 else 2

    # Compute stall z bands evenly partitioning [z0+1, z1-1).
    interior_z0 = z0 + 1
    interior_z1 = z1 - 1
    interior_depth = max(1, interior_z1 - interior_z0)
    # Boundaries between stalls (z values where partitions sit).
    # For n_stalls we have n_stalls-1 internal partitions.
    partitions_z: list[int] = []
    for i in range(1, n_stalls):
        pz = interior_z0 + (i * interior_depth) // n_stalls
        # Don't sit right on the outer walls.
        if interior_z0 < pz < interior_z1:
            partitions_z.append(pz)

    # Each partition: a 1-block-wide fence row running along x from the
    # back wall (x0+1) toward the open front (x1-1), 2 blocks tall.
    fence_y0 = y0 + 1
    fence_y1 = min(y0 + 2, y1 - 2)  # cap to leave a row under the roof
    for pz in partitions_z:
        for fx in range(x0 + 1, x1 - 1):
            ops.append(PlaceBlock(fx, fence_y0, pz, "@fence"))
            if fence_y1 > fence_y0:
                ops.append(PlaceBlock(fx, fence_y1, pz, "@fence"))

    # Build the z-band for each stall so we can place per-stall furniture.
    bounds = [interior_z0] + partitions_z + [interior_z1]
    stalls: list[tuple[int, int]] = []
    for i in range(len(bounds) - 1):
        sz0 = bounds[i] + (1 if i > 0 else 0)   # skip the partition row
        sz1 = bounds[i + 1]
        if sz1 > sz0:
            stalls.append((sz0, sz1))

    # ──────────────────────── 5) Per-stall furniture ────────────────────
    # In each stall: hay (food) by the back wall, water cauldron beside
    # it, barrel for storage near the front. Armor stand near the front
    # as a saddle holder.
    yfurn = y0 + 1
    for (sz0, sz1) in stalls:
        # Centre z within the stall band.
        scz = (sz0 + sz1 - 1) // 2

        # Hay (food) one column in from the back wall.
        hx = x0 + 1
        ops.append(PlaceBlock(hx, yfurn - 1, scz, "minecraft:hay_block"))
        # (yfurn - 1 == y0: replaces the floor block with hay — bedding.)

        # Water cauldron, next column forward.
        wx = min(x0 + 2, x1 - 2)
        ops.append(PlaceBlock(wx, yfurn, scz, "minecraft:cauldron[level=3]"))

        # Barrel storage near the front of the stall (one column behind
        # the open face), facing up so the lid reads from above.
        bx = max(x0 + 3, x1 - 2)
        if bx >= x1 - 1:
            bx = x1 - 2
        # Place barrel slightly off-centre so it doesn't fight the armor
        # stand. Use sz0 for predictability.
        bz = sz0
        if bz >= sz1:
            bz = sz0
        ops.append(PlaceBlock(bx, yfurn, bz, "minecraft:barrel[facing=up]"))

        # Armor stand (saddle holder) at the very front of the stall.
        ax = x1 - 2
        az = sz1 - 1 if sz1 - 1 >= sz0 else sz0
        ops.append(PlaceBlock(ax, yfurn, az, "minecraft:armor_stand"))

    # ──────────────────────── 6) Lanterns under the roof ────────────────
    # 1-2 lanterns hanging from the underside of the roof course along the
    # central x line of the stable. We pick the y just under the roof top.
    y_lantern = y_roof_top - 1
    if y_lantern < y0 + 1:
        y_lantern = y0 + 1
    # First lantern: middle-front (close to the open face, lights the
    # entrance).
    lcx = max(x0 + 1, x1 - 3)
    lcz = (z0 + z1 - 1) // 2
    ops.append(PlaceBlock(lcx, y_lantern, lcz, "minecraft:lantern"))
    # Second lantern: for deeper stables (d >= 5) add one toward the back
    # to light the food/water area.
    if d >= 5:
        lbx = x0 + 2
        ops.append(PlaceBlock(lbx, y_lantern, lcz, "minecraft:lantern"))

    return ops


# Keep Materials import referenced in the public signature even though
# we mostly drive material choice through `@…` placeholders; some future
# variants may inspect material slots directly.
_ = Materials
