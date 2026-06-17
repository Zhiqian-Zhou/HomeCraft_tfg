"""Skill: gazebo.

A small round/octagonal outdoor pavilion. The skill draws:

  * An octagonal floor (5-wide, with cut corners) of @floor at y0. The
    floor stays inside the AABB and is centred on (cx, cz).
  * Six to eight corner posts of @primary rising 3 blocks from the
    octagon's outer vertices.
  * A pyramidal roof above the posts: @stairs blocks on the cardinal
    edges facing inward toward the apex, with @roof corner caps and a
    single @roof apex block in the centre.
  * A single `minecraft:lantern[hanging=true]` hanging from the
    underside of the apex, lighting the open pavilion below.
  * Perimeter benches: 4 (or up to 6) @stairs blocks placed against the
    posts and facing inward toward the centre.
  * 1-2 `minecraft:flower_pot` decorations on the floor between the
    benches.

Defensive sizing: works for any AABB from 5x4x5 up to 9x6x9. Smaller
boxes are padded; larger ones keep the gazebo centred and pad the
remainder with @floor.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive footprint clamps for this skill.
_MIN_W, _MIN_H, _MIN_D = 5, 4, 5
_MAX_W, _MAX_H, _MAX_D = 9, 6, 9


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [5..9, 4..6, 5..9] envelope.

    Origin is preserved; only the upper corner moves to satisfy bounds.
    """
    w = max(_MIN_W, min(_MAX_W, aabb.w))
    h = max(_MIN_H, min(_MAX_H, aabb.h))
    d = max(_MIN_D, min(_MAX_D, aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build an octagonal gazebo centred inside the (clamped) AABB."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    y_floor = a.y0

    # 1) Octagonal floor of side 5: a 5x5 square with the 4 corners
    #    knocked off, giving an 8-sided footprint.
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2
    # 5x5 span centred on (cx, cz)
    fx0, fx1 = cx - 2, cx + 3  # half-open
    fz0, fz1 = cz - 2, cz + 3
    # Clamp to AABB
    fx0 = max(a.x0, fx0); fx1 = min(a.x1, fx1)
    fz0 = max(a.z0, fz0); fz1 = min(a.z1, fz1)

    # Place the octagonal floor cell by cell, skipping the 4 corners of
    # the 5x5 square.
    for x in range(fx0, fx1):
        for z in range(fz0, fz1):
            is_corner = (
                (x == fx0 and z == fz0) or
                (x == fx0 and z == fz1 - 1) or
                (x == fx1 - 1 and z == fz0) or
                (x == fx1 - 1 and z == fz1 - 1)
            )
            if is_corner:
                continue
            ops.append(PlaceBlock(x, y_floor, z, "@floor"))

    # 2) Eight corner posts of @primary rising from y_floor + 1.
    #    Posts sit on the eight non-corner perimeter cells of the 5x5
    #    bounding square — i.e. the four edge midpoints and the four
    #    cells adjacent to each missing corner. Falling back to six
    #    posts on heavily clamped footprints.
    post_height = 3
    post_y0 = y_floor + 1
    post_y1 = post_y0 + post_height  # half-open

    # Octagon vertices: the 8 cells around the perimeter of the 5x5
    # square minus its 4 corners. We use the four cardinal edge
    # midpoints (axis posts) and the two cells flanking each corner
    # collapsed to one — picking 8 distinct vertices for the octagon.
    post_candidates: list[tuple[int, int]] = [
        (cx,     fz0),       # N edge midpoint
        (cx,     fz1 - 1),   # S edge midpoint
        (fx0,    cz),        # W edge midpoint
        (fx1 - 1, cz),       # E edge midpoint
        (fx0 + 1, fz0),      # NW vertex (one step in from corner)
        (fx1 - 2, fz0),      # NE vertex
        (fx0 + 1, fz1 - 1),  # SW vertex
        (fx1 - 2, fz1 - 1),  # SE vertex
    ]
    # Dedupe in case the clamp collapsed neighbours together.
    post_corners = list({(px, pz) for (px, pz) in post_candidates})
    # If clamping killed two of them, we still want at least 6 posts.
    if len(post_corners) < 6:
        post_corners = list({(px, pz) for (px, pz) in [
            (fx0, fz0 + 1), (fx0, fz1 - 2),
            (fx1 - 1, fz0 + 1), (fx1 - 1, fz1 - 2),
            *post_corners,
        ]})

    for (px, pz) in post_corners:
        ops.append(
            Fill(AABB(px, post_y0, pz, px + 1, post_y1, pz + 1), "@primary")
        )

    # 3) Pyramidal roof above the posts. Roof plane sits at y_roof =
    #    post_y1. Inner ring of @stairs facing inward + outer ring of
    #    @roof corner caps + @roof apex block on top.
    y_roof = post_y1

    # 3a) Outer roof ring — a @roof cap on each post column, closing
    #     the pyramid's lower edge.
    for (px, pz) in post_corners:
        ops.append(PlaceBlock(px, y_roof, pz, "@roof"))

    # 3b) Cardinal-edge stairs facing inward (one block above the
    #     roof ring, stepping up toward the apex). Skip if the position
    #     overlaps a corner cap already placed.
    cap_set = set(post_corners)
    edge_stairs = [
        (cx, fz0 + 1, "south"),     # N stair, faces south
        (cx, fz1 - 2, "north"),     # S stair, faces north
        (fx0 + 1, cz, "east"),      # W stair, faces east
        (fx1 - 2, cz, "west"),      # E stair, faces west
    ]
    y_stairs = y_roof + 1
    for (sx, sz, facing) in edge_stairs:
        if not a.contains(sx, y_stairs, sz):
            continue
        ops.append(PlaceBlock(sx, y_stairs, sz, f"@stairs[facing={facing}]"))

    # 3c) Apex block on top of the pyramid centre, one block above the
    #     ring of stairs.
    y_apex = y_stairs + 1 if a.contains(cx, y_stairs + 1, cz) else y_stairs
    ops.append(PlaceBlock(cx, y_apex, cz, "@roof"))

    # 4) Central hanging lantern from the underside of the apex.
    lantern_y = y_apex - 1
    if lantern_y > y_floor:
        ops.append(
            PlaceBlock(cx, lantern_y, cz, "minecraft:lantern[hanging=true]")
        )

    # 5) Perimeter benches: @stairs facing inward, sat one step in from
    #    the cardinal edge posts so people sitting on the bench look
    #    toward the centre.
    bench_y = y_floor + 1
    benches = [
        # (x, z, facing)
        (cx, fz0 + 1, "south"),   # N bench faces south
        (cx, fz1 - 2, "north"),   # S bench faces north
        (fx0 + 1, cz, "east"),    # W bench faces east
        (fx1 - 2, cz, "west"),    # E bench faces west
    ]
    bench_placed: list[tuple[int, int]] = []
    for (bx, bz, facing) in benches:
        # Skip if this lands on a post column (the post already
        # occupies that cell) or outside the AABB.
        if (bx, bz) in cap_set:
            continue
        if not a.contains(bx, bench_y, bz):
            continue
        ops.append(PlaceBlock(bx, bench_y, bz, f"@stairs[facing={facing}]"))
        bench_placed.append((bx, bz))

    # Two more diagonal benches for AABBs that are big enough to host
    # them without colliding with the posts.
    extra_benches = [
        (fx0 + 1, fz0 + 1, "south"),
        (fx1 - 2, fz1 - 2, "north"),
    ]
    for (bx, bz, facing) in extra_benches:
        if (bx, bz) in cap_set or (bx, bz) in bench_placed:
            continue
        if not a.contains(bx, bench_y, bz):
            continue
        # Only add diagonal benches when the AABB has room (>=7 wide)
        # so they don't crowd the lantern column.
        if a.w < 7 or a.d < 7:
            continue
        ops.append(PlaceBlock(bx, bench_y, bz, f"@stairs[facing={facing}]"))
        bench_placed.append((bx, bz))

    # 6) Flower-pot decorations on the floor, tucked against the
    #    cardinal posts where there are no benches.
    pot_candidates = [
        (cx - 1, fz0 + 1),
        (cx + 1, fz1 - 2),
    ]
    pots_placed = 0
    for (px, pz) in pot_candidates:
        if pots_placed >= 2:
            break
        if (px, pz) in cap_set or (px, pz) in bench_placed:
            continue
        if not a.contains(px, bench_y, pz):
            continue
        # Don't drop a pot on the lantern column.
        if (px, pz) == (cx, cz):
            continue
        ops.append(PlaceBlock(px, bench_y, pz, "minecraft:flower_pot"))
        pots_placed += 1

    return ops
