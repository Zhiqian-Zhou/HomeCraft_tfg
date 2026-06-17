"""Library skill — bookshelf-lined reading room with lectern and reading table.

Layout:
    - Floor @floor (full plane at y0).
    - Walls @primary (hollow shell, no ceiling block fill — top open).
    - Bookshelf perimeter 2-3 blocks tall lining the interior side of every
      wall, with gaps for the door (south wall, center) and one window
      (north wall, center).
    - One lectern at the geometric center of the room.
    - One reading table (3 blocks long @primary slab on a row) flanked by
      two stair-block chairs.
    - 2+ lanterns mounted on the top corners of the walls.
    - Fantasy style: enchanting table next to the lectern.
    - Ladder on one interior wall if the room is "multi-floor friendly"
      (h >= 5 and floor area >= 8x8).

Defensive on 6×4×6 to 14×6×14. For very small AABBs we degrade gracefully
(shorter bookshelf bands, single chair, no ladder).
"""
from __future__ import annotations

from .base import AABB, Fill, FillHollow, Materials, Op, PlaceBlock, Rect


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []

    # Clamp height for inside calculations.
    inside_h = max(2, aabb.h - 1)  # leave top row free for lanterns / sky
    # Bookshelf stack height: 2 for short rooms, 3 for taller.
    shelf_h = 3 if inside_h >= 4 else 2

    # ── 1) Floor + walls ────────────────────────────────────────────────
    # Floor plane at y0.
    ops.append(Rect(
        AABB(aabb.x0, aabb.y0, aabb.z0, aabb.x1, aabb.y0 + 1, aabb.z1),
        "@floor", axis="y", level=aabb.y0,
    ))
    # Walls as a hollow shell from y0+1 up to y1-1 (no ceiling/floor overrides).
    wall_top = aabb.y1  # exclusive
    if wall_top - (aabb.y0 + 1) >= 1:
        ops.append(FillHollow(
            AABB(aabb.x0, aabb.y0 + 1, aabb.z0, aabb.x1, wall_top, aabb.z1),
            wall="@primary",
            floor="@primary",   # blocks at y0+1 ring (door opening cut later)
            ceiling="@primary",
        ))

    # ── 2) Door opening (south wall, z = z1-1, centered in x) ──────────
    door_x = (aabb.x0 + aabb.x1 - 1) // 2
    door_z = aabb.z1 - 1
    door_h = min(2, aabb.h - 1)
    for dy in range(door_h):
        ops.append(PlaceBlock(door_x, aabb.y0 + 1 + dy, door_z, "minecraft:air"))

    # ── 3) Window opening (north wall, z = z0, centered) ───────────────
    win_x = (aabb.x0 + aabb.x1 - 1) // 2
    win_z = aabb.z0
    win_y = aabb.y0 + 1 + max(1, (aabb.h - 2) // 2)
    if win_y < aabb.y1 - 1:
        ops.append(PlaceBlock(win_x, win_y, win_z, "@glass"))

    # ── 4) Bookshelf perimeter ─────────────────────────────────────────
    # Inner ring is one block inside each wall.
    in_x0, in_x1 = aabb.x0 + 1, aabb.x1 - 1
    in_z0, in_z1 = aabb.z0 + 1, aabb.z1 - 1
    base_y = aabb.y0 + 1
    top_y = min(base_y + shelf_h, aabb.y1 - 1)  # leave 1 row for lanterns

    def _skip(x: int, z: int) -> bool:
        # Gap directly in front of door (south side) and window (north side).
        if z == in_z1 - 1 and x == door_x:
            return True
        if z == in_z0 and x == win_x:
            return True
        return False

    # North band (z = in_z0) — runs along x.
    for x in range(in_x0, in_x1):
        if _skip(x, in_z0):
            continue
        for y in range(base_y, top_y):
            ops.append(PlaceBlock(x, y, in_z0, "minecraft:bookshelf"))
    # South band (z = in_z1 - 1).
    for x in range(in_x0, in_x1):
        if _skip(x, in_z1 - 1):
            continue
        for y in range(base_y, top_y):
            ops.append(PlaceBlock(x, y, in_z1 - 1, "minecraft:bookshelf"))
    # West band (x = in_x0) — skip corners already placed.
    for z in range(in_z0 + 1, in_z1 - 1):
        for y in range(base_y, top_y):
            ops.append(PlaceBlock(in_x0, y, z, "minecraft:bookshelf"))
    # East band (x = in_x1 - 1).
    for z in range(in_z0 + 1, in_z1 - 1):
        for y in range(base_y, top_y):
            ops.append(PlaceBlock(in_x1 - 1, y, z, "minecraft:bookshelf"))

    # ── 5) Center lectern(s) ───────────────────────────────────────────
    cx = aabb.cx
    cz = aabb.cz
    ops.append(PlaceBlock(cx, aabb.y0 + 1, cz, "minecraft:lectern"))
    # If the room is large enough, add a second lectern.
    if aabb.w >= 10 and aabb.d >= 10:
        ops.append(PlaceBlock(cx + 2, aabb.y0 + 1, cz, "minecraft:lectern"))

    # ── 6) Reading table + chairs ──────────────────────────────────────
    # Place table along z (up to 3 blocks long) offset from the center
    # along x so it doesn't collide with the central lectern.
    # Pick a table_x distinct from cx (lectern column).
    if in_x0 + 1 != cx and in_x0 + 1 < in_x1 - 1:
        table_x = in_x0 + 1
    elif in_x1 - 2 != cx and in_x1 - 2 > in_x0:
        table_x = in_x1 - 2
    else:
        table_x = max(in_x0, cx - 1)

    table_len = min(3, max(1, (in_z1 - 1) - (in_z0 + 1) - 2))
    # Center table along z, but leave at least one cell at each end for chairs.
    span_cells_avail = (in_z1 - 1) - (in_z0 + 1)
    if span_cells_avail >= table_len + 2:
        table_z0 = in_z0 + 2
    else:
        # Tight room: place table flush so chairs land on bookshelf cells
        # (which will be overridden by later-wins).
        table_z0 = in_z0 + 1
    table_z1 = table_z0 + table_len
    for tz in range(table_z0, table_z1):
        # Avoid stomping on the lectern coord.
        if (table_x, aabb.y0 + 1, tz) == (cx, aabb.y0 + 1, cz):
            continue
        ops.append(PlaceBlock(table_x, aabb.y0 + 1, tz, "@primary"))

    # Chairs: stairs at the ends of the table facing the table.
    chair_z_a = table_z0 - 1
    chair_z_b = table_z1
    # Allow chairs to land inside the interior bounds (in_z0 .. in_z1-1).
    if in_z0 <= chair_z_a <= in_z1 - 1 and chair_z_a != cz:
        ops.append(PlaceBlock(table_x, aabb.y0 + 1, chair_z_a, "@stairs[facing=south]"))
    if in_z0 <= chair_z_b <= in_z1 - 1 and chair_z_b != cz:
        ops.append(PlaceBlock(table_x, aabb.y0 + 1, chair_z_b, "@stairs[facing=north]"))

    # ── 7) Lanterns (2+ on walls) ──────────────────────────────────────
    lantern_y = aabb.y1 - 2  # one below the top wall row
    if lantern_y < aabb.y0 + 1:
        lantern_y = aabb.y0 + 1
    # Two diagonal corners (interior side).
    lantern_spots = [
        (in_x0, lantern_y, in_z0),
        (in_x1 - 1, lantern_y, in_z1 - 1),
    ]
    if aabb.w >= 10 and aabb.d >= 10:
        lantern_spots.append((in_x1 - 1, lantern_y, in_z0))
        lantern_spots.append((in_x0, lantern_y, in_z1 - 1))
    for (lx, ly, lz) in lantern_spots:
        ops.append(PlaceBlock(lx, ly, lz, "minecraft:lantern"))

    # ── 8) Enchanting table (fantasy only) ─────────────────────────────
    if style.lower() == "fantasy":
        # Place next to (one block east of) the lectern, if free.
        ench_x = min(cx + 1, in_x1 - 1)
        if ench_x != cx:
            ops.append(PlaceBlock(ench_x, aabb.y0 + 1, cz, "minecraft:enchanting_table"))

    # ── 9) Ladder (multi-floor friendly rooms) ─────────────────────────
    if aabb.h >= 5 and aabb.w >= 8 and aabb.d >= 8:
        # Attach a ladder to the east interior wall, opposite the door.
        ladder_x = in_x1 - 1
        ladder_z = cz
        for ly in range(aabb.y0 + 1, aabb.y1 - 1):
            ops.append(PlaceBlock(ladder_x, ly, ladder_z, "minecraft:ladder[facing=west]"))

    return ops
