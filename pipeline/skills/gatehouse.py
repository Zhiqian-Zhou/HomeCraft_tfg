"""Skill: gatehouse.

A fortified gate structure — two square towers flanking a central gate, joined
by a battlemented curtain section with a walkway across the top. The classic
castle entry-point silhouette.

Layout (along the AABB's *long axis* — x if w >= d, else z):
    * Two square `FillHollow` towers at the two ends of the long axis. Towers
      are sized to the AABB's short-axis extent (so they're square in plan)
      and run the full height.
    * Connecting wall (`FillHollow`) between the two towers, slightly taller
      than a man so the walkway rides on top. The wall is centred on the short
      axis and is `t_short` blocks thick (the same depth as a tower).
    * Gate opening at the bottom of the middle wall — a 2-3 wide × 2 tall
      slot punched out with `minecraft:air`. The opening sits at the wall's
      mid-length and goes all the way through the wall thickness.
    * Two `@door` blocks placed inside the opening (one on each face of the
      wall) to read as gate doors.
    * Battlements (alternating merlons + crenels) crowning both towers AND
      the connecting wall — one continuous fortified silhouette.
    * 4-6 `@glass` slits in the tower walls, two per tower at mid-height on
      the two outward-facing faces.
    * 2 `minecraft:lantern` flanking the gate, one on each side of the
      opening, mounted at door-head height.
    * Walkway across the top of the connecting wall: `@floor` along the wall
      top with `@fence` railings on both sides — connects the two towers
      so defenders can patrol end-to-end.

Material roles:
    @primary   — tower + wall masonry, merlons
    @secondary — floor course at y0
    @glass     — window slits
    @floor     — walkway planks on top of the wall
    @fence     — walkway railings
    @door      — gate doors

Defensive sizing: clamped to 5x6x3 .. 14x10x5 (long × tall × short).
"""
from __future__ import annotations

from typing import List

from .base import AABB, FillHollow, Materials, Op, PlaceBlock


# Defensive bounds per spec — interpreted as (long_axis, height, short_axis).
_MIN = (5, 6, 3)
_MAX = (14, 10, 5)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB so the long axis lies in [5..14], height in [6..10] and
    the short axis in [3..5]. Reorients the bounds so the gatehouse always
    has a clean long/short pair regardless of caller input.
    """
    w, h, d = aabb.w, aabb.h, aabb.d
    # Decide which horizontal axis is the long one.
    long_is_x = w >= d
    long_extent = w if long_is_x else d
    short_extent = d if long_is_x else w

    long_extent = max(_MIN[0], min(_MAX[0], long_extent))
    short_extent = max(_MIN[2], min(_MAX[2], short_extent))
    h = max(_MIN[1], min(_MAX[1], h))

    if long_is_x:
        return AABB(aabb.x0, aabb.y0, aabb.z0,
                    aabb.x0 + long_extent, aabb.y0 + h, aabb.z0 + short_extent)
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + short_extent, aabb.y0 + h, aabb.z0 + long_extent)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a gatehouse: twin flanking towers + battlemented gate wall."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    long_is_x = a.w >= a.d
    short = a.d if long_is_x else a.w  # short-axis extent

    # ────────────────────────────────────────────────────────────────────
    # 1) Two square towers at the ends of the long axis. Each tower is a
    #    `short x h x short` cube hollow shell. They share the y range with
    #    the wall and bracket it.
    # ────────────────────────────────────────────────────────────────────
    if long_is_x:
        t0 = AABB(a.x0, a.y0, a.z0, a.x0 + short, a.y1, a.z1)
        t1 = AABB(a.x1 - short, a.y0, a.z0, a.x1, a.y1, a.z1)
    else:
        t0 = AABB(a.x0, a.y0, a.z0, a.x1, a.y1, a.z0 + short)
        t1 = AABB(a.x0, a.y0, a.z1 - short, a.x1, a.y1, a.z1)

    for tower in (t0, t1):
        ops.append(FillHollow(
            aabb=tower, wall="@primary", fill=None,
            floor="@secondary", ceiling="@primary",
        ))

    # ────────────────────────────────────────────────────────────────────
    # 2) Connecting wall between the two towers. Lower than the towers by
    #    1 block (so the towers visibly stand taller), with the same
    #    short-axis depth, hollow so we can punch the gate through it.
    # ────────────────────────────────────────────────────────────────────
    wall_top = a.y1 - 1  # one below the tower roof — towers stand a tier above
    if long_is_x:
        wall = AABB(a.x0 + short, a.y0, a.z0,
                    a.x1 - short, wall_top, a.z1)
    else:
        wall = AABB(a.x0, a.y0, a.z0 + short,
                    a.x1, wall_top, a.z1 - short)

    # Only emit the wall if there is actually space for it between the towers.
    has_wall = (wall.w > 0 and wall.d > 0 and wall.h > 0)
    if has_wall:
        ops.append(FillHollow(
            aabb=wall, wall="@primary", fill=None,
            floor="@secondary", ceiling="@primary",
        ))

    # ────────────────────────────────────────────────────────────────────
    # 3) Gate opening (2-3 wide × 2 tall) punched through the middle of
    #    the wall. Centred on the long axis; spans the full wall thickness
    #    on the short axis (so you can walk through it).
    # ────────────────────────────────────────────────────────────────────
    gate_width = 3 if (long_is_x and wall.w >= 5) or ((not long_is_x) and wall.d >= 5) else 2
    if has_wall:
        if long_is_x:
            mid_long = (wall.x0 + wall.x1) // 2
            gx0 = mid_long - gate_width // 2
            gx1 = gx0 + gate_width
            # Clamp inside the wall (keep at least one column of wall at each end).
            gx0 = max(gx0, wall.x0 + 1)
            gx1 = min(gx1, wall.x1 - 1)
            for gy in (a.y0, a.y0 + 1):
                for gx in range(gx0, gx1):
                    for gz in range(wall.z0, wall.z1):
                        ops.append(PlaceBlock(gx, gy, gz, "minecraft:air"))
        else:
            mid_long = (wall.z0 + wall.z1) // 2
            gz0 = mid_long - gate_width // 2
            gz1 = gz0 + gate_width
            gz0 = max(gz0, wall.z0 + 1)
            gz1 = min(gz1, wall.z1 - 1)
            for gy in (a.y0, a.y0 + 1):
                for gz in range(gz0, gz1):
                    for gx in range(wall.x0, wall.x1):
                        ops.append(PlaceBlock(gx, gy, gz, "minecraft:air"))

    # ────────────────────────────────────────────────────────────────────
    # 4) Two gate doors inside the opening — one on each outer face of the
    #    wall. We place a single @door block at y0 (bottom half); on Java
    #    1.16.5 the door block represents the lower half.
    # ────────────────────────────────────────────────────────────────────
    if has_wall:
        if long_is_x:
            door_x = (wall.x0 + wall.x1) // 2
            ops.append(PlaceBlock(door_x, a.y0, wall.z0, "@door"))
            ops.append(PlaceBlock(door_x, a.y0, wall.z1 - 1, "@door"))
        else:
            door_z = (wall.z0 + wall.z1) // 2
            ops.append(PlaceBlock(wall.x0, a.y0, door_z, "@door"))
            ops.append(PlaceBlock(wall.x1 - 1, a.y0, door_z, "@door"))

    # ────────────────────────────────────────────────────────────────────
    # 5) Battlements: alternating merlons on the rim ABOVE every tower top
    #    AND above the wall top — one continuous crenellated silhouette.
    # ────────────────────────────────────────────────────────────────────
    # 5a) Tower battlements: one row above each tower's ceiling.
    for tower in (t0, t1):
        y_rim = tower.y1
        ring = _perimeter_ring(tower.x0, tower.z0, tower.x1 - 1, tower.z1 - 1)
        for i, (rx, rz) in enumerate(ring):
            if i % 2 == 0:
                ops.append(PlaceBlock(rx, y_rim, rz, "@primary"))

    # 5b) Wall battlements: row above the wall ceiling, only on the two
    #     outer faces of the wall (the long-axis-aligned faces). The
    #     short-axis ends abut the towers, so no battlements there.
    if has_wall:
        y_wall_rim = wall.y1  # one above the wall ceiling
        if long_is_x:
            for x in range(wall.x0, wall.x1):
                idx = x - wall.x0
                if idx % 2 == 0:
                    ops.append(PlaceBlock(x, y_wall_rim, wall.z0, "@primary"))
                    ops.append(PlaceBlock(x, y_wall_rim, wall.z1 - 1, "@primary"))
        else:
            for z in range(wall.z0, wall.z1):
                idx = z - wall.z0
                if idx % 2 == 0:
                    ops.append(PlaceBlock(wall.x0, y_wall_rim, z, "@primary"))
                    ops.append(PlaceBlock(wall.x1 - 1, y_wall_rim, z, "@primary"))

    # ────────────────────────────────────────────────────────────────────
    # 6) Window slits — 4-6 @glass blocks in the tower walls. Two per tower
    #    at mid-height on the two outward-facing faces (the side that
    #    points away from the central wall and one of the cardinal sides).
    # ────────────────────────────────────────────────────────────────────
    y_slit = a.y0 + max(2, a.h // 2)
    if y_slit >= a.y1 - 1:
        y_slit = a.y1 - 2
    for tower in (t0, t1):
        # Outer end-face (the one pointing away from the centre of the AABB).
        tcx = (tower.x0 + tower.x1 - 1) // 2
        tcz = (tower.z0 + tower.z1 - 1) // 2
        if long_is_x:
            # End face: x = tower.x0 if it's the left tower, x = tower.x1-1 if right.
            end_x = tower.x0 if tower.x0 == a.x0 else tower.x1 - 1
            ops.append(PlaceBlock(end_x, y_slit, tcz, "@glass"))
            # A side face: -z and +z faces, pick both for 6 total slits.
            ops.append(PlaceBlock(tcx, y_slit, tower.z0, "@glass"))
            ops.append(PlaceBlock(tcx, y_slit, tower.z1 - 1, "@glass"))
        else:
            end_z = tower.z0 if tower.z0 == a.z0 else tower.z1 - 1
            ops.append(PlaceBlock(tcx, y_slit, end_z, "@glass"))
            ops.append(PlaceBlock(tower.x0, y_slit, tcz, "@glass"))
            ops.append(PlaceBlock(tower.x1 - 1, y_slit, tcz, "@glass"))

    # ────────────────────────────────────────────────────────────────────
    # 7) Lanterns flanking the gate — two lanterns at door-head height,
    #    one on each side of the opening (long-axis adjacent to gate).
    # ────────────────────────────────────────────────────────────────────
    if has_wall:
        y_lantern = a.y0 + 2
        if y_lantern >= a.y1 - 1:
            y_lantern = a.y1 - 2
        if long_is_x:
            mid_long = (wall.x0 + wall.x1) // 2
            gx0 = mid_long - gate_width // 2
            gx1 = gx0 + gate_width
            # On the +z face (the "outside") of the wall, one block to each side of the gate.
            left_x = max(gx0 - 1, wall.x0)
            right_x = min(gx1, wall.x1 - 1)
            ops.append(PlaceBlock(left_x, y_lantern, wall.z1 - 1, "minecraft:lantern"))
            ops.append(PlaceBlock(right_x, y_lantern, wall.z1 - 1, "minecraft:lantern"))
        else:
            mid_long = (wall.z0 + wall.z1) // 2
            gz0 = mid_long - gate_width // 2
            gz1 = gz0 + gate_width
            left_z = max(gz0 - 1, wall.z0)
            right_z = min(gz1, wall.z1 - 1)
            ops.append(PlaceBlock(wall.x1 - 1, y_lantern, left_z, "minecraft:lantern"))
            ops.append(PlaceBlock(wall.x1 - 1, y_lantern, right_z, "minecraft:lantern"))

    # ────────────────────────────────────────────────────────────────────
    # 8) Walkway: @floor along the top of the wall (inside the centre
    #    strip), with @fence railings on the two outer edges so it reads
    #    as a parapet walk connecting the two towers.
    # ────────────────────────────────────────────────────────────────────
    if has_wall:
        y_walk = wall.y1 - 1  # the wall's ceiling row — repaint as @floor
        if long_is_x:
            # Floor strip along the entire long axis of the wall, centred on z.
            for x in range(wall.x0, wall.x1):
                for z in range(wall.z0 + 1, wall.z1 - 1):
                    ops.append(PlaceBlock(x, y_walk, z, "@floor"))
            # Fence railings on the two long edges, one row above the floor.
            y_rail = y_walk + 1
            if y_rail <= a.y1 - 1:
                for x in range(wall.x0, wall.x1):
                    # skip merlon positions so the merlons still pop out
                    idx = x - wall.x0
                    if idx % 2 != 0:
                        ops.append(PlaceBlock(x, y_rail, wall.z0, "@fence"))
                        ops.append(PlaceBlock(x, y_rail, wall.z1 - 1, "@fence"))
        else:
            for z in range(wall.z0, wall.z1):
                for x in range(wall.x0 + 1, wall.x1 - 1):
                    ops.append(PlaceBlock(x, y_walk, z, "@floor"))
            y_rail = y_walk + 1
            if y_rail <= a.y1 - 1:
                for z in range(wall.z0, wall.z1):
                    idx = z - wall.z0
                    if idx % 2 != 0:
                        ops.append(PlaceBlock(wall.x0, y_rail, z, "@fence"))
                        ops.append(PlaceBlock(wall.x1 - 1, y_rail, z, "@fence"))

    return ops


def _perimeter_ring(x0: int, z0: int, x1: int, z1: int) -> list[tuple[int, int]]:
    """Return the ring of (x, z) cells around the rectangle (x0,z0)..(x1,z1)
    inclusive, ordered as a single closed walk so neighbouring indices
    correspond to neighbouring cells (used for the alternating merlon
    pattern).
    """
    if x1 < x0 or z1 < z0:
        return []
    cells: list[tuple[int, int]] = []
    for x in range(x0, x1 + 1):
        cells.append((x, z0))
    for z in range(z0 + 1, z1 + 1):
        cells.append((x1, z))
    for x in range(x1 - 1, x0 - 1, -1):
        cells.append((x, z1))
    for z in range(z1 - 1, z0, -1):
        cells.append((x0, z))
    return cells
