"""Skill: courtyard_well.

A small monumental well centered in an open courtyard. The skill draws:

  * A pavement of @floor across the whole AABB ground plane (y0). Anything
    larger than the 3x3 well footprint stays as ground, so the well always
    sits in a plaza of its own material.
  * A 3x3 well rim at y0 — eight blocks of `minecraft:cobblestone_wall`
    (or @secondary in non-medieval styles) around a single
    `minecraft:water` source at the very center.
  * 4 corner posts of @primary rising 3 blocks (4 for taller AABBs) above
    the rim corners — the supports for the roof above.
  * A 3x3 pyramid roof above the posts: 4 @stairs blocks facing inward on
    the sides and one @roof apex block at the centre.
  * A single `minecraft:lantern` hanging from the underside of the apex
    block, lighting the water below ("Pools of Light").

Defensive sizing: works for any AABB from 3x3x3 up to 7x6x7. Smaller
boxes are padded to 3x3x3; larger ones keep the well at the geometric
centre and pave the remainder with @floor.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive footprint clamps for this skill.
_MIN_W, _MIN_H, _MIN_D = 3, 3, 3
_MAX_W, _MAX_H, _MAX_D = 7, 6, 7


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [3..7, 3..6, 3..7] envelope.

    Origin is preserved; only the upper corner moves to satisfy bounds.
    """
    w = max(_MIN_W, min(_MAX_W, aabb.w))
    h = max(_MIN_H, min(_MAX_H, aabb.h))
    d = max(_MIN_D, min(_MAX_D, aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a courtyard well centred inside the (clamped) AABB."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    y_floor = a.y0

    # 1) Pavement across the entire footprint at y_floor — courtyard ground.
    ops.append(Rect(a, "@floor", axis="y", level=y_floor))

    # 2) Locate the 3x3 well footprint centred inside the AABB.
    #    Using integer centres so we always emit a 3x3 ring even when the
    #    AABB is exactly the minimum size (3x_x3).
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2
    wx0, wx1 = cx - 1, cx + 2  # half-open 3-wide span
    wz0, wz1 = cz - 1, cz + 2

    # Clamp the well so it never spills outside the AABB even when the
    # caller passes a pathological corner (cx near the edge).
    wx0 = max(a.x0, wx0); wx1 = min(a.x1, wx1)
    wz0 = max(a.z0, wz0); wz1 = min(a.z1, wz1)

    # 3) Well rim — a 3x3 ring at y_floor: cobblestone_wall on the edges,
    #    a single water source at the centre. Medieval style uses
    #    `minecraft:cobblestone_wall` for the rim; other styles fall back
    #    to @secondary blocks so the rim still reads as masonry.
    rim_block = (
        "minecraft:cobblestone_wall"
        if style.lower() == "medieval"
        else "@secondary"
    )
    for x in range(wx0, wx1):
        for z in range(wz0, wz1):
            if x == cx and z == cz:
                # Water source at the well centre.
                ops.append(PlaceBlock(x, y_floor, z, "minecraft:water"))
            else:
                ops.append(PlaceBlock(x, y_floor, z, rim_block))

    # 4) Four corner posts of @primary rising from y_floor + 1 to roof y.
    #    Post height = 3 (default) or 4 when the AABB is tall enough.
    post_height = 4 if a.h >= 5 else 3
    post_y0 = y_floor + 1
    post_y1 = post_y0 + post_height  # half-open

    post_corners: list[tuple[int, int]] = []
    for px in (wx0, wx1 - 1):
        for pz in (wz0, wz1 - 1):
            post_corners.append((px, pz))
    # Deduplicate in case the clamp collapsed the rim corners.
    post_corners = list({(px, pz) for (px, pz) in post_corners})

    for (px, pz) in post_corners:
        ops.append(
            Fill(AABB(px, post_y0, pz, px + 1, post_y1, pz + 1), "@primary")
        )

    # 5) Pyramid roof above the posts: 4 stairs facing inward + apex.
    #    Roof plane sits at y_roof = post_y1 (one above the top of the posts).
    y_roof = post_y1
    # The 3x3 roof footprint mirrors the well rim.
    # Inward facing stairs sit on the 4 cardinal edge midpoints.
    # Corners of the roof are kept as the rim corners (left as @roof for
    # solidity, so the pyramid reads as a closed cap).
    #
    #   z↓   x→   wx0     cx     wx1-1
    #   wz0       roof    N-stair roof
    #   cz        W-stair APEX    E-stair
    #   wz1-1     roof    S-stair roof

    # Roof corner caps (solid @roof blocks).
    for (px, pz) in post_corners:
        ops.append(PlaceBlock(px, y_roof, pz, "@roof"))

    # Cardinal edge stairs facing toward the centre.
    # Stair "facing" in Minecraft 1.16.5 points where the player would step
    # off the stair (the high side). So a stair on the -x edge (west edge)
    # facing east will rise toward the centre.
    edge_stairs = [
        # (x, z, facing)
        (cx, wz0,       "south"),  # north edge, faces south (toward centre)
        (cx, wz1 - 1,   "north"),  # south edge, faces north
        (wx0, cz,       "east"),   # west edge, faces east
        (wx1 - 1, cz,   "west"),   # east edge, faces west
    ]
    for (sx, sz, facing) in edge_stairs:
        # Skip if the stair would land on a corner we already filled
        # (happens only when the rim collapsed under heavy clamping).
        if (sx, sz) in {(px, pz) for (px, pz) in post_corners}:
            continue
        ops.append(PlaceBlock(sx, y_roof, sz, f"@stairs[facing={facing}]"))

    # Apex block on top of the pyramid centre.
    ops.append(PlaceBlock(cx, y_roof, cz, "@roof"))

    # 6) Lantern hanging from the underside of the apex — i.e. one block
    #    below the apex, in the open space between the posts. In Java
    #    1.16.5 a hanging lantern is `minecraft:lantern[hanging=true]`.
    lantern_y = y_roof - 1
    if lantern_y > y_floor:  # always true given post_height >= 3
        ops.append(
            PlaceBlock(cx, lantern_y, cz, "minecraft:lantern[hanging=true]")
        )

    return ops
