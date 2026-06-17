"""`bedroom` skill — a room with a bed, nightstand, chest, lighting, and rug.

Layout strategy (AABB coordinate system in `base.py`):
    * Floor: y == y0, full rectangle of `@floor`.
    * Walls: perimeter from y0+1 .. y1-1 of `@primary`. Top is left open;
      a beamed roof (Line ops) closes the corners and ridge with `@roof`.
    * Bed (`@bed`): placed against the west wall, head at z = z0+1
      occupying 2 blocks along z. Resolves to a stylewise-coloured bed
      (red / white / purple) via Materials.for_style.
    * Nightstand: single block of `@primary` next to the bed head,
      with a `minecraft:lantern` on top (or torch as a fallback on small).
    * Chest: against the east wall, near a corner.
    * Crafting table: only if interior allows (w >= 8 -> medium+).
    * Carpet rug (`@carpet`): a small rectangular patch at y0+1 in the
      centre of the room.
    * Window: a 1-wide glass strip on the wall opposite the bed (east).
    * Extra lantern/torch on a wall for general lighting.

Defensive against shrunken AABBs (down to 5x4x5) by clamping interior
coordinates with `max`/`min`.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, FillHollow, Line, Materials, Op, PlaceBlock, Rect


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    ops: List[Op] = []

    x0, y0, z0 = aabb.x0, aabb.y0, aabb.z0
    x1, y1, z1 = aabb.x1, aabb.y1, aabb.z1
    w, h, d = aabb.w, aabb.h, aabb.d

    # ───────────────────────── floor ─────────────────────────
    ops.append(Rect(AABB(x0, y0, z0, x1, y0 + 1, z1), "@floor", axis="y", level=y0))

    # ─────────────────── walls (open ceiling) ─────────────────
    # Hollow shell from y0+1 to y1-1 (no roof plane). FillHollow gives
    # walls + floor + ceiling, but since we slice to just the wall band
    # we feed it an AABB that's only 1-block tall at top and bottom of
    # the wall band; simpler: emit perimeter as 4 Rect ops.
    wall_top = max(y0 + 2, y1 - 1)  # at least one wall layer above the bed
    # north wall (z = z0)
    ops.append(Rect(AABB(x0, y0 + 1, z0, x1, wall_top + 1, z0 + 1), "@primary", axis="z", level=z0))
    # south wall (z = z1-1)
    ops.append(Rect(AABB(x0, y0 + 1, z1 - 1, x1, wall_top + 1, z1), "@primary", axis="z", level=z1 - 1))
    # west wall (x = x0)
    ops.append(Rect(AABB(x0, y0 + 1, z0, x0 + 1, wall_top + 1, z1), "@primary", axis="x", level=x0))
    # east wall (x = x1-1)
    ops.append(Rect(AABB(x1 - 1, y0 + 1, z0, x1, wall_top + 1, z1), "@primary", axis="x", level=x1 - 1))

    # ─────────────────── beamed open roof ─────────────────────
    # Beams along the four top edges + one ridge beam down the middle.
    yr = wall_top  # roof beam Y (top of walls)
    # Perimeter beams (corners get drawn but Line handles duplicates OK)
    ops.append(Line(x0, yr, z0, x1 - 1, yr, z0, "@roof"))
    ops.append(Line(x0, yr, z1 - 1, x1 - 1, yr, z1 - 1, "@roof"))
    ops.append(Line(x0, yr, z0, x0, yr, z1 - 1, "@roof"))
    ops.append(Line(x1 - 1, yr, z0, x1 - 1, yr, z1 - 1, "@roof"))
    # Ridge / cross beams (open beams across the ceiling)
    cz = (z0 + z1 - 1) // 2
    ops.append(Line(x0, yr, cz, x1 - 1, yr, cz, "@roof"))
    # If the room is bigger than minimum, add a second perpendicular beam
    if w >= 8:
        cx = (x0 + x1 - 1) // 2
        ops.append(Line(cx, yr, z0, cx, yr, z1 - 1, "@roof"))

    # ─────────────────────── window ───────────────────────────
    # Wall opposite the bed (east wall x = x1-1). 1-wide strip,
    # centred on z, at eye height (y0 + 2).
    win_y = min(y0 + 2, wall_top - 1)
    if win_y >= y0 + 1 and d >= 5:
        win_z0 = z0 + 2
        win_z1 = z1 - 2
        if win_z1 > win_z0:
            ops.append(
                Rect(
                    AABB(x1 - 1, win_y, win_z0, x1, win_y + 1, win_z1),
                    "@glass",
                    axis="x",
                    level=x1 - 1,
                )
            )

    # ─────────────────────── bed ──────────────────────────────
    # Against west wall (x = x0+1), occupying 2 blocks along +z.
    # head at (x0+1, y0+1, z0+1), foot at (x0+1, y0+1, z0+2).
    bx = x0 + 1
    by = y0 + 1
    bed_z_head = z0 + 1
    bed_z_foot = z0 + 2
    ops.append(PlaceBlock(bx, by, bed_z_head, "@bed"))
    ops.append(PlaceBlock(bx, by, bed_z_foot, "@bed"))

    # ───────────────────── nightstand ─────────────────────────
    # One block of @primary just past the bed head (z0).
    # Place at (bx, by, bed_z_head - 1) if that cell is interior; otherwise
    # at (bx + 1, by, bed_z_head). On a 5-deep room z0+1 - 1 = z0 (wall).
    ns_x = bx + 1
    ns_z = bed_z_head
    if ns_x < x1 - 1:  # inside, not on east wall
        ops.append(PlaceBlock(ns_x, by, ns_z, "@primary"))
        # Lantern on the nightstand
        ops.append(PlaceBlock(ns_x, by + 1, ns_z, "minecraft:lantern"))
    else:
        # Fallback: torch directly on the wall above the bed head
        ops.append(PlaceBlock(bx, by + 1, bed_z_head, "minecraft:torch"))

    # Second nightstand at the foot side if room is medium+
    if w >= 8 and bed_z_foot + 1 < z1 - 1:
        ns2_x = bx + 1
        ns2_z = bed_z_foot
        if ns2_x < x1 - 1:
            ops.append(PlaceBlock(ns2_x, by, ns2_z, "@accent"))

    # ─────────────────────── chest ────────────────────────────
    # Against east wall, near south corner.
    chest_x = x1 - 2
    chest_z = z1 - 2
    # Guard: must be interior.
    if chest_x > bx and chest_z > bed_z_foot:
        ops.append(PlaceBlock(chest_x, by, chest_z, "minecraft:chest"))

    # ─────────────────── crafting table ───────────────────────
    # Only on medium+ rooms (w >= 8). Place near north-east corner,
    # picking a z that doesn't collide with the bed footprint.
    if w >= 8 and d >= 8:
        ct_x = x1 - 2
        # Walk from north toward south to find the first free interior z.
        ct_z = None
        for candidate in range(z0 + 1, z1 - 1):
            if candidate in (bed_z_head, bed_z_foot):
                continue
            if candidate == chest_z:
                continue
            ct_z = candidate
            break
        if ct_z is not None and ct_x > bx:
            ops.append(PlaceBlock(ct_x, by, ct_z, "minecraft:crafting_table"))

    # ────────────────────── carpet rug ────────────────────────
    # Central rectangle, 1 block above the floor (carpets sit on top).
    # Avoid overlapping the bed footprint.
    rug_x0 = max(bx + 1, x0 + 2)
    rug_x1 = max(rug_x0 + 1, x1 - 2)
    rug_z0 = max(z0 + 1, bed_z_foot + 1)
    rug_z1 = max(rug_z0 + 1, z1 - 2)
    if rug_x1 > rug_x0 and rug_z1 > rug_z0:
        ops.append(
            Rect(
                AABB(rug_x0, y0 + 1, rug_z0, rug_x1, y0 + 2, rug_z1),
                "@carpet",
                axis="y",
                level=y0 + 1,
            )
        )

    # ───────────────── extra wall lighting ────────────────────
    # Torch on south wall near the door-ish position (we don't have a
    # door in this skill — that's the entry skill's job — but the room
    # still needs visible lighting). Stick a torch on the south interior
    # facing wall column.
    torch_x = (x0 + x1) // 2
    torch_z = z1 - 2
    torch_y = min(y0 + 2, wall_top - 1)
    if (
        torch_y >= y0 + 1
        and torch_x > x0
        and torch_x < x1 - 1
        and torch_z > z0
        and torch_z < z1 - 1
    ):
        ops.append(PlaceBlock(torch_x, torch_y, torch_z, "minecraft:torch"))

    return ops
