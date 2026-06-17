"""Kitchen skill.

Builds a furnished kitchen inside the given AABB:
    - Floor plane (Rect at y0 using @floor).
    - Perimeter walls using @primary, with glass-pane windows on at
      least two opposite sides.
    - No full ceiling — only lintel beams along the top of the walls
      (so the composer can stack roof skills on top later).
    - Cooking station against an exterior wall: furnace + smoker /
      blast-furnace pair, plus a crafting table for prep.
    - Sink represented by a cauldron with water (under a window).
    - Storage barrels along an interior wall.
    - Two or more lights (torches or lanterns).

Style differentiation (medieval / modern / fantasy) tweaks the cook-line
appliances and the glazing density. The composer resolves the `@primary`,
`@floor`, `@glass`, `@light`, `@accent` placeholders into concrete blocks
based on `Materials.for_style(style)`.

The function is defensive: it scales the furniture count to AABB size so
tiny rooms (5x4x5) still get the must-have blocks while big rooms
(12x6x12) gain extra barrels and a longer counter.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock, Rect, Fill, Line


# ────────────────────────────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────────────────────────────


def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Return AST ops that materialize a furnished kitchen inside `aabb`."""
    s = (style or "medieval").lower()

    ops: List[Op] = []
    ops.extend(_floor(aabb))
    ops.extend(_walls(aabb))
    ops.extend(_windows(aabb, s))
    ops.extend(_lintel(aabb))
    ops.extend(_cook_line(aabb, s))
    ops.extend(_sink(aabb))
    ops.extend(_prep_and_storage(aabb, s))
    ops.extend(_lighting(aabb, s))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Layout helpers
# ────────────────────────────────────────────────────────────────────────


def _floor(aabb: AABB) -> List[Op]:
    """Solid floor plane on y == aabb.y0 using @floor."""
    floor_plane = AABB(aabb.x0, aabb.y0, aabb.z0, aabb.x1, aabb.y0 + 1, aabb.z1)
    return [Rect(floor_plane, "@floor", axis="y", level=aabb.y0)]


def _walls(aabb: AABB) -> List[Op]:
    """Perimeter walls (only the 4 vertical faces) using @primary.

    Walls span y from aabb.y0+1 (above the floor) up to aabb.y1-1
    (leaving the top row for the lintel beams).
    """
    y0w = aabb.y0 + 1
    y1w = max(aabb.y1 - 1, y0w + 1)   # always at least 1 wall row
    ops: List[Op] = []
    # North (z = aabb.z0) and South (z = aabb.z1-1) full slabs
    ops.append(Fill(AABB(aabb.x0, y0w, aabb.z0,
                         aabb.x1, y1w, aabb.z0 + 1), "@primary"))
    ops.append(Fill(AABB(aabb.x0, y0w, aabb.z1 - 1,
                         aabb.x1, y1w, aabb.z1), "@primary"))
    # West (x = aabb.x0) and East (x = aabb.x1-1) full slabs
    ops.append(Fill(AABB(aabb.x0, y0w, aabb.z0,
                         aabb.x0 + 1, y1w, aabb.z1), "@primary"))
    ops.append(Fill(AABB(aabb.x1 - 1, y0w, aabb.z0,
                         aabb.x1, y1w, aabb.z1), "@primary"))
    return ops


def _lintel(aabb: AABB) -> List[Op]:
    """Top-of-wall beam ring (no full ceiling).

    A 1-block-high band of @accent around the perimeter at the very top.
    Leaves the cavity open above so a roof skill can sit on top.
    """
    if aabb.h < 3:
        return []
    y = aabb.y1 - 1
    return [
        Line(aabb.x0, y, aabb.z0, aabb.x1 - 1, y, aabb.z0, "@accent"),
        Line(aabb.x0, y, aabb.z1 - 1, aabb.x1 - 1, y, aabb.z1 - 1, "@accent"),
        Line(aabb.x0, y, aabb.z0, aabb.x0, y, aabb.z1 - 1, "@accent"),
        Line(aabb.x1 - 1, y, aabb.z0, aabb.x1 - 1, y, aabb.z1 - 1, "@accent"),
    ]


def _windows(aabb: AABB, style: str) -> List[Op]:
    """Glass-pane windows on at least two opposite walls.

    The window row sits one block above the counter (y = y0 + 2)
    when the wall is tall enough; otherwise at y0+1.
    Modern style gets denser glazing (a continuous strip), medieval and
    fantasy get individual punched-out windows.
    """
    ops: List[Op] = []
    glass = "@glass"
    y_win = aabb.y0 + 2 if aabb.h >= 4 else aabb.y0 + 1
    if y_win >= aabb.y1 - 1:
        y_win = aabb.y1 - 2

    # interior x range (skip corners)
    xs = list(range(aabb.x0 + 1, aabb.x1 - 1))
    zs = list(range(aabb.z0 + 1, aabb.z1 - 1))
    if not xs or not zs:
        return ops

    if style == "modern":
        # continuous glazing band on north + south walls
        for x in xs:
            ops.append(PlaceBlock(x, y_win, aabb.z0, glass))
            ops.append(PlaceBlock(x, y_win, aabb.z1 - 1, glass))
        # plus a single window each on east + west walls
        zc = (aabb.z0 + aabb.z1 - 1) // 2
        ops.append(PlaceBlock(aabb.x0,     y_win, zc, glass))
        ops.append(PlaceBlock(aabb.x1 - 1, y_win, zc, glass))
    else:
        # Punched windows: every other x on north + south
        step = 2 if len(xs) >= 3 else 1
        for x in xs[::step]:
            ops.append(PlaceBlock(x, y_win, aabb.z0, glass))
            ops.append(PlaceBlock(x, y_win, aabb.z1 - 1, glass))
        # one window on each side (east / west) to satisfy "≥ 2 sides"
        zc = (aabb.z0 + aabb.z1 - 1) // 2
        ops.append(PlaceBlock(aabb.x0,     y_win, zc, glass))
        ops.append(PlaceBlock(aabb.x1 - 1, y_win, zc, glass))

    return ops


def _cook_line(aabb: AABB, style: str) -> List[Op]:
    """Cooking station against the north (z = z0+1) interior wall.

    - Furnace (always present — medieval / fantasy primary cooker).
    - Smoker (modern primary) or blast_furnace (fantasy variant).
    - Crafting table next to them as the prep counter.

    Blocks sit at y = y0 + 1 (directly on the floor, one row up because
    y0 itself is the floor block).
    """
    ops: List[Op] = []
    y = aabb.y0 + 1
    z = aabb.z0 + 1                # interior, against north wall
    # Place from x0+1 outward to the east — at least 3 contiguous spots.
    x_start = aabb.x0 + 1
    # ensure we don't run into the east wall (x1-1)
    max_x = aabb.x1 - 2

    # Style-dependent appliance order along the cook line.
    if style == "modern":
        line = [
            "minecraft:smoker[facing=south]",
            "minecraft:furnace[facing=south]",
            "minecraft:crafting_table",
        ]
    elif style == "fantasy":
        line = [
            "minecraft:furnace[facing=south]",
            "minecraft:blast_furnace[facing=south]",
            "minecraft:crafting_table",
        ]
    else:  # medieval (default)
        line = [
            "minecraft:furnace[facing=south]",
            "minecraft:smoker[facing=south]",
            "minecraft:crafting_table",
        ]

    for i, block in enumerate(line):
        x = x_start + i
        if x > max_x:
            break
        ops.append(PlaceBlock(x, y, z, block))

    return ops


def _sink(aabb: AABB) -> List[Op]:
    """Cauldron filled with water — the 'sink'.

    Placed against the south wall (z = z1-2), under a window. We pick the
    centre-x so the window above it lines up with the punched-window grid
    when possible.
    """
    y = aabb.y0 + 1
    z = aabb.z1 - 2                # interior, against south wall
    if z <= aabb.z0:               # tiny room fallback
        z = aabb.z0 + 1
    # pick a centred x
    x = (aabb.x0 + aabb.x1 - 1) // 2
    # cauldron with level=3 water (1.16.5 blockstate)
    return [PlaceBlock(x, y, z, "minecraft:cauldron[level=3]")]


def _prep_and_storage(aabb: AABB, style: str) -> List[Op]:
    """Barrel storage along the east wall, optional extras for big rooms.

    At least one barrel always. Bigger AABBs get more barrels stacked
    along the wall, and a second crafting-table-style counter is added
    on the west wall when there's room.
    """
    ops: List[Op] = []
    y = aabb.y0 + 1

    # Barrels along the east wall (x = x1-2), going from z0+1 -> z1-2.
    x_e = aabb.x1 - 2
    if x_e <= aabb.x0:
        x_e = aabb.x0 + 1

    # Number of barrels scales with the depth of the room.
    # Always at least 1 — strict requirement.
    available = max(1, aabb.d - 4)   # leave corners + cook line slot
    n_barrels = min(max(1, available // 2 + 1), aabb.d - 2)

    # Spread them out along z, starting two cells in from the north wall.
    z_start = aabb.z0 + 2
    placed = 0
    for i in range(n_barrels):
        z = z_start + i
        if z >= aabb.z1 - 2:        # don't sit on the sink row
            break
        # avoid clashing with the cook line (z = z0+1) — already offset
        ops.append(PlaceBlock(x_e, y, z, "minecraft:barrel[facing=west]"))
        placed += 1
    if placed == 0:
        # tiny room fallback: drop one barrel in any free spot near east wall
        ops.append(PlaceBlock(x_e, y, max(aabb.z0 + 1, aabb.z1 - 2),
                              "minecraft:barrel[facing=west]"))

    # Large room: add a small prep counter (slabs) along the west wall.
    if aabb.w >= 8 and aabb.d >= 8:
        x_w = aabb.x0 + 1
        for z in range(aabb.z0 + 2, aabb.z1 - 2):
            ops.append(PlaceBlock(x_w, y, z, "@slab"))
        # accent block (modern: smithing_table, medieval: smithing_table too;
        # we use it as a 'butcher block') in the middle of that counter.
        z_mid = (aabb.z0 + aabb.z1 - 1) // 2
        ops.append(PlaceBlock(x_w, y, z_mid, "minecraft:smithing_table"))

    return ops


def _lighting(aabb: AABB, style: str) -> List[Op]:
    """At least 2 light sources.

    - One torch / lantern near the cooking station.
    - One on the opposite side of the room.
    - For big rooms, a fourth light in the centre of the ceiling beam.
    """
    ops: List[Op] = []
    light = "@light"
    # We mostly want them at y = y_top (just under the lintel) so they
    # illuminate the whole space. Clamp strictly into the interior
    # [y0+1, y1-1] of the half-open AABB (avoids placing a light at or
    # above the ceiling in short rooms).
    y_light = min(aabb.y1 - 1, max(aabb.y0 + 1, aabb.y1 - 2))

    # Lantern near the cook line (north side, centre-x).
    x_c = (aabb.x0 + aabb.x1 - 1) // 2
    z_n = aabb.z0 + 1
    z_s = aabb.z1 - 2
    if z_n >= aabb.z1 - 1:
        z_n = aabb.z0 + 1
    if z_s <= aabb.z0:
        z_s = aabb.z1 - 2

    ops.append(PlaceBlock(x_c, y_light, z_n, light))
    ops.append(PlaceBlock(x_c, y_light, z_s, light))

    # Big rooms: add two more lights at the cross corners.
    if aabb.w >= 8 and aabb.d >= 8:
        ops.append(PlaceBlock(aabb.x0 + 2, y_light, aabb.z0 + 2, light))
        ops.append(PlaceBlock(aabb.x1 - 3, y_light, aabb.z1 - 3, light))

    return ops
