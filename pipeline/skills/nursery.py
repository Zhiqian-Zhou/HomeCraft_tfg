"""`nursery` skill — a children's room.

Layout strategy (AABB coordinate system in `base.py`):
    * Floor: y == y0, full rectangle of `@floor`.
    * Walls: perimeter from y0+1 .. y1-1 of `@primary`. A beamed ceiling
      (Line ops of `@roof`) closes the top corners and ridge.
    * Child bed (`@bed`): single-block bed against the west wall (a child
      bed — we still use the `@bed` 2-block footprint for visual sake but
      keep it tucked against the corner so the room feels small).
    * Toy chest (`minecraft:chest`): on the floor near the foot of the bed.
    * Small chairs (1-2 `@stairs`): one or two stairs blocks acting as
      pint-sized chairs near the picture-book bookshelf.
    * Bookshelf (`minecraft:bookshelf`): single block along the east wall
      (picture books).
    * Cake (`minecraft:cake`): proxy for a stuffed-animal / toy display —
      placed on the floor at the foot of the bed or against a wall.
    * Carpet rug (`@carpet`): a bright play-mat patch on the centre floor.
      The chosen carpet colour is biased by style (yellow for modern, pink
      for fantasy, red for medieval) — but ultimately drives off `@carpet`
      from the Materials preset chosen by the style pack.
    * Flower pot (`minecraft:flower_pot`): on a windowsill or nightstand.
    * Lanterns (2+ `minecraft:lantern`): warm light — never torches.
    * Window (`@glass`): single 1-wide window on the wall opposite the bed.

Defensive against shrunken AABBs (down to 4x3x4) — clamp interior coords
with `max`/`min` and only place each piece if its target cell is interior.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Line, Materials, Op, PlaceBlock, Rect


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    ops: List[Op] = []

    x0, y0, z0 = aabb.x0, aabb.y0, aabb.z0
    x1, y1, z1 = aabb.x1, aabb.y1, aabb.z1
    w, h, d = aabb.w, aabb.h, aabb.d

    # ───────────────────────── floor ─────────────────────────
    ops.append(Rect(AABB(x0, y0, z0, x1, y0 + 1, z1), "@floor", axis="y", level=y0))

    # ─────────────────── walls (open ceiling) ─────────────────
    wall_top = max(y0 + 2, y1 - 1)
    # north / south / west / east walls
    ops.append(Rect(AABB(x0, y0 + 1, z0, x1, wall_top + 1, z0 + 1), "@primary", axis="z", level=z0))
    ops.append(Rect(AABB(x0, y0 + 1, z1 - 1, x1, wall_top + 1, z1), "@primary", axis="z", level=z1 - 1))
    ops.append(Rect(AABB(x0, y0 + 1, z0, x0 + 1, wall_top + 1, z1), "@primary", axis="x", level=x0))
    ops.append(Rect(AABB(x1 - 1, y0 + 1, z0, x1, wall_top + 1, z1), "@primary", axis="x", level=x1 - 1))

    # ─────────────────── beamed open roof ─────────────────────
    yr = wall_top
    ops.append(Line(x0, yr, z0, x1 - 1, yr, z0, "@roof"))
    ops.append(Line(x0, yr, z1 - 1, x1 - 1, yr, z1 - 1, "@roof"))
    ops.append(Line(x0, yr, z0, x0, yr, z1 - 1, "@roof"))
    ops.append(Line(x1 - 1, yr, z0, x1 - 1, yr, z1 - 1, "@roof"))
    cz = (z0 + z1 - 1) // 2
    ops.append(Line(x0, yr, cz, x1 - 1, yr, cz, "@roof"))
    if w >= 6:
        cx = (x0 + x1 - 1) // 2
        ops.append(Line(cx, yr, z0, cx, yr, z1 - 1, "@roof"))

    # ─────────────────── style-biased carpet ─────────────────
    # Pick a vibrant child-friendly play-mat colour by style. Falls back to
    # `@carpet` so style packs can still override via Materials.
    s = (style or "").lower()
    if s == "modern":
        rug_block = "minecraft:yellow_carpet"
    elif s == "fantasy":
        rug_block = "minecraft:pink_carpet"
    elif s == "medieval":
        rug_block = "minecraft:red_carpet"
    else:
        rug_block = "@carpet"

    # ─────────────────────── window ───────────────────────────
    # On the east wall (opposite the bed). Small (1×1) for a child room.
    win_y = min(y0 + 2, wall_top - 1)
    if win_y >= y0 + 1 and d >= 4:
        win_z = (z0 + z1) // 2
        if z0 < win_z < z1 - 1:
            ops.append(PlaceBlock(x1 - 1, win_y, win_z, "@glass"))

    # ─────────────────────── child bed ────────────────────────
    # Single-style bed against the west wall, head toward the north.
    bx = x0 + 1
    by = y0 + 1
    bed_z_head = z0 + 1
    bed_z_foot = z0 + 2
    if bx < x1 - 1 and bed_z_foot < z1 - 1:
        ops.append(PlaceBlock(bx, by, bed_z_head, "@bed"))
        ops.append(PlaceBlock(bx, by, bed_z_foot, "@bed"))
    elif bx < x1 - 1 and bed_z_head < z1 - 1:
        # Truly tiny room: just a single block of bed at the head cell.
        ops.append(PlaceBlock(bx, by, bed_z_head, "@bed"))
        bed_z_foot = bed_z_head  # collapse references

    # ───────────────── toy chest (foot of bed) ────────────────
    # Place the toy chest just past the foot of the bed; otherwise nearest
    # free interior cell along the west wall.
    chest_x = bx
    chest_z = bed_z_foot + 1
    if chest_x < x1 - 1 and z0 < chest_z < z1 - 1:
        ops.append(PlaceBlock(chest_x, by, chest_z, "minecraft:chest"))
    else:
        # Fallback: south-west interior corner
        cx2 = x0 + 1
        cz2 = z1 - 2
        if cx2 < x1 - 1 and z0 < cz2 < z1 - 1:
            ops.append(PlaceBlock(cx2, by, cz2, "minecraft:chest"))

    # ───────────────── bookshelf (picture books) ──────────────
    # Against the east interior wall, toward the north.
    bs_x = x1 - 2
    bs_z = z0 + 1
    if bs_x > bx and z0 < bs_z < z1 - 1:
        ops.append(PlaceBlock(bs_x, by, bs_z, "minecraft:bookshelf"))

    # ───────────────── small chairs (stairs) ──────────────────
    # 1 or 2 stairs blocks acting as child-scale chairs, sitting next to
    # the bookshelf so the child can "read".
    chair1_x = x1 - 2
    chair1_z = z0 + 2
    chair2_x = x1 - 2
    chair2_z = z0 + 3
    placed_chairs = 0
    if chair1_x > bx and z0 < chair1_z < z1 - 1 and chair1_z != bs_z:
        ops.append(PlaceBlock(chair1_x, by, chair1_z, "@stairs"))
        placed_chairs += 1
    # Only a second chair if the room is roomy enough.
    if d >= 6 and chair2_x > bx and z0 < chair2_z < z1 - 1 and chair2_z != bs_z:
        ops.append(PlaceBlock(chair2_x, by, chair2_z, "@stairs"))
        placed_chairs += 1

    # ─────────────── cake (toy / stuffed-animal proxy) ────────
    # On top of the toy chest is illegal — chests are full blocks but the
    # cake schema works as a placed block of its own. Put the cake along
    # the south wall, slightly toward the centre.
    cake_x = (x0 + x1) // 2
    cake_z = z1 - 2
    if x0 < cake_x < x1 - 1 and z0 < cake_z < z1 - 1:
        ops.append(PlaceBlock(cake_x, by, cake_z, "minecraft:cake"))

    # ─────────────────── flower pot (1+) ──────────────────────
    # On the floor by the window if there's space, else by the bed head.
    fp_x = x1 - 2
    fp_z = (z0 + z1) // 2
    if fp_x > bx and z0 < fp_z < z1 - 1 and fp_z not in (bs_z, chair1_z, chair2_z):
        ops.append(PlaceBlock(fp_x, by, fp_z, "minecraft:flower_pot"))
    else:
        # Fallback: corner next to the bed head
        if bx < x1 - 1 and z0 < bed_z_head < z1 - 1:
            ops.append(PlaceBlock(bx + 1 if bx + 1 < x1 - 1 else bx,
                                  by, bed_z_head, "minecraft:flower_pot"))

    # ───────────────────── carpet rug ─────────────────────────
    # Bright play-mat in the centre, not under the bed.
    rug_x0 = max(bx + 1, x0 + 2)
    rug_x1 = max(rug_x0 + 1, x1 - 2)
    rug_z0 = max(z0 + 1, bed_z_foot + 1)
    rug_z1 = max(rug_z0 + 1, z1 - 2)
    if rug_x1 > rug_x0 and rug_z1 > rug_z0:
        ops.append(
            Rect(
                AABB(rug_x0, y0 + 1, rug_z0, rug_x1, y0 + 2, rug_z1),
                rug_block,
                axis="y",
                level=y0 + 1,
            )
        )

    # ─────────────── lanterns (warm light, 2+) ────────────────
    # Hanging-from-beam style: drop two lanterns near the ceiling beams.
    lant_y = max(y0 + 1, wall_top - 1)
    # Lantern 1: above the bed area (near head)
    lant1_x = bx + 1 if bx + 1 < x1 - 1 else bx
    lant1_z = bed_z_head
    if x0 < lant1_x < x1 - 1 and z0 < lant1_z < z1 - 1 and lant_y > y0 + 1:
        ops.append(PlaceBlock(lant1_x, lant_y, lant1_z, "minecraft:lantern"))
    # Lantern 2: above the play area / centre
    lant2_x = (x0 + x1) // 2
    lant2_z = (z0 + z1) // 2
    if (x0 < lant2_x < x1 - 1 and z0 < lant2_z < z1 - 1
            and lant_y > y0 + 1
            and (lant2_x, lant2_z) != (lant1_x, lant1_z)):
        ops.append(PlaceBlock(lant2_x, lant_y, lant2_z, "minecraft:lantern"))
    # On bigger rooms add a third lantern near the bookshelf.
    if w >= 6 and d >= 6:
        lant3_x = x1 - 2
        lant3_z = z0 + 2
        if (x0 < lant3_x < x1 - 1 and z0 < lant3_z < z1 - 1
                and lant_y > y0 + 1):
            ops.append(PlaceBlock(lant3_x, lant_y, lant3_z, "minecraft:lantern"))

    return ops
