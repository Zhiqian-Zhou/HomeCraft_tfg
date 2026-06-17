"""Living room skill.

Builds a defensive, schema-valid living-room interior inside `aabb` using AST
ops from `pipeline.skills.base`. The result is an open-ceiling room (lintels
only) with: floor, perimeter walls, big south-facing windows, a fireplace on
the longest wall, a stairs-built sofa facing the center, a coffee table, a
bookshelf, carpets, and torches/lanterns.

Scaling envelope (defensive): 6x4x6 up to 12x5x12 — anything beyond is clamped
internally; anything below the floor of 6x4x6 still yields a usable mini-room.

Coordinate convention (from base.AABB): x = width, y = height (up), z = depth.
Floor sits at y=y0; walls extend up through y=y1-1. The "open ceiling" rule
means we do not fill a ceiling plane; we drop a single ring of lintel blocks
at the wall top so the silhouette reads as a room and not as an open pen.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# ────────────────────────────────────────────────────────────────────────
#  Public entry point
# ────────────────────────────────────────────────────────────────────────

def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Return the list of AST ops that materialize a living room into `aabb`."""
    # Defensive clamp — preserves the lower-NW corner, shrinks toward the user.
    a = _clamp(aabb)

    ops: List[Op] = []

    # Order matters: composer applies LATER-WINS dedupe, so we paint the
    # shell first, then the floor-level finishes (carpets), then furniture
    # that should visibly sit ON the carpets (sofa, table, bookshelf), and
    # finally the small detail blocks (lights).

    # 1) Shell: solid floor + perimeter walls, no ceiling.
    ops.extend(_shell(a))

    # 2) Big south-facing windows (z = z1-1 wall), with @glass panes.
    ops.extend(_south_windows(a))

    # 3) Carpets on the floor surface — placed early so furniture overrides
    #    them at any shared coord (the rug visually sits under the chairs).
    ops.extend(_carpets(a))

    # 4) Fireplace on the longest interior wall.
    ops.extend(_fireplace(a))

    # 5) Sofa (3+ stairs facing the room center) on the wall opposite the
    #    fireplace; coffee table in front of it. Stairs need their actual
    #    block id (not just the `@stairs` placeholder) so we can append the
    #    `[facing=…]` blockstate.
    ops.extend(_sofa_and_table(a, stairs_block=materials.stairs))

    # 6) Bookshelf against a side wall.
    ops.extend(_bookshelf(a))

    # 7) At least two lights (wall lanterns / torches).
    ops.extend(_lights(a))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Defensive size clamp
# ────────────────────────────────────────────────────────────────────────

def _clamp(a: AABB) -> AABB:
    """Clamp the working AABB to the supported envelope [6x4x6 .. 12x5x12].

    Smaller inputs still build (degenerate cases handled by guards below);
    larger inputs are truncated from the +x/+y/+z side, preserving the lower
    corner — this keeps the floor plan anchored at the AABB's NW corner.
    """
    max_w, max_h, max_d = 12, 5, 12
    x0, y0, z0 = a.x0, a.y0, a.z0
    x1 = min(a.x1, x0 + max_w)
    y1 = min(a.y1, y0 + max_h)
    z1 = min(a.z1, z0 + max_d)
    return AABB(x0, y0, z0, x1, y1, z1)


# ────────────────────────────────────────────────────────────────────────
#  Shell: floor + walls (open ceiling, lintels only)
# ────────────────────────────────────────────────────────────────────────

def _shell(a: AABB) -> List[Op]:
    ops: List[Op] = []

    # Floor plane at y = y0.
    ops.append(Rect(a, "@floor", axis="y", level=a.y0))

    # Four wall slabs (rising from y0+1 to y1-1) — we leave the floor row
    # intact and do not paint a ceiling. The lintel ring at the top
    # (y = y1-1) gives the room its eyebrow without closing the ceiling.
    h_y0 = a.y0 + 1
    h_y1 = a.y1  # exclusive
    if h_y1 <= h_y0:
        return ops  # too short to have walls

    # North wall (z = z0)
    ops.append(Fill(AABB(a.x0, h_y0, a.z0, a.x1, h_y1, a.z0 + 1), "@primary"))
    # South wall (z = z1-1)
    ops.append(Fill(AABB(a.x0, h_y0, a.z1 - 1, a.x1, h_y1, a.z1), "@primary"))
    # West wall (x = x0)
    ops.append(Fill(AABB(a.x0, h_y0, a.z0, a.x0 + 1, h_y1, a.z1), "@primary"))
    # East wall (x = x1-1)
    ops.append(Fill(AABB(a.x1 - 1, h_y0, a.z0, a.x1, h_y1, a.z1), "@primary"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  South-wall windows
# ────────────────────────────────────────────────────────────────────────

def _south_windows(a: AABB) -> List[Op]:
    """Carve a 3- or 4-wide window band into the south wall and fill with @glass.

    Window sits at the second wall row from the floor (head-height); for tall
    enough rooms (h >= 4 above floor) we make it 2 blocks tall.
    """
    ops: List[Op] = []
    if a.w < 5 or a.h < 3:
        return ops  # too small to spare room for a real window

    interior_w = a.w - 2  # excludes the two corner columns
    win_w = 4 if interior_w >= 4 else 3
    win_w = min(win_w, interior_w)
    if win_w < 2:
        return ops

    x0 = a.x0 + 1 + (interior_w - win_w) // 2
    x1 = x0 + win_w
    z = a.z1 - 1  # south wall

    # Window height: sits in row y0+2 (above the dado) and, when there's
    # vertical headroom, extends one row higher.
    win_y0 = a.y0 + 2
    win_y1 = min(a.y1 - 1, win_y0 + 2)
    if win_y1 <= win_y0:
        win_y1 = win_y0 + 1
    if win_y1 > a.y1 - 1:
        win_y1 = a.y1 - 1
    if win_y1 <= win_y0:
        return ops

    ops.append(Fill(AABB(x0, win_y0, z, x1, win_y1, z + 1), "@glass"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Fireplace on the longest interior wall
# ────────────────────────────────────────────────────────────────────────

def _fireplace(a: AABB) -> List[Op]:
    """Place a fireplace: 2x1 netherrack hearth flush with the wall, with a
    campfire on top (the safer alternative to `minecraft:fire`)."""
    ops: List[Op] = []

    # "Longest wall" — prefer the east-west wall (along x) if x >= z, else
    # the north-south wall (along z). To keep the room legible we put the
    # fireplace on the NORTH wall when w >= d (so the sofa can sit on the
    # south side / by the window), and on the WEST wall otherwise.
    interior_w = a.w - 2
    interior_d = a.d - 2
    if min(interior_w, interior_d) < 2:
        return ops  # no interior to host the hearth

    if a.w >= a.d:
        # Fireplace on the north wall (z = z0), centered along x.
        cx = a.x0 + a.w // 2
        # 2-wide hearth: choose x-pair (cx-1, cx) so it stays centered.
        fx0 = max(a.x0 + 1, cx - 1)
        fx1 = min(a.x1 - 1, fx0 + 2)
        if fx1 - fx0 < 2:
            fx0 = max(a.x0 + 1, fx1 - 2)
        if fx1 - fx0 < 2:
            return ops
        # Hearth (netherrack base) sits at y0, immediately in front of the
        # wall (z = z0 + 1). That way the wall stays intact and the fire is
        # entirely interior — safer for renderers that don't model fire.
        z_hearth = a.z0 + 1
        ops.append(Fill(
            AABB(fx0, a.y0, z_hearth, fx1, a.y0 + 1, z_hearth + 1),
            "minecraft:netherrack",
        ))
        # Campfire blocks sitting on the netherrack base.
        for x in range(fx0, fx1):
            ops.append(PlaceBlock(x, a.y0 + 1, z_hearth, "minecraft:campfire"))
    else:
        # Fireplace on the west wall (x = x0), centered along z.
        cz = a.z0 + a.d // 2
        fz0 = max(a.z0 + 1, cz - 1)
        fz1 = min(a.z1 - 1, fz0 + 2)
        if fz1 - fz0 < 2:
            fz0 = max(a.z0 + 1, fz1 - 2)
        if fz1 - fz0 < 2:
            return ops
        x_hearth = a.x0 + 1
        ops.append(Fill(
            AABB(x_hearth, a.y0, fz0, x_hearth + 1, a.y0 + 1, fz1),
            "minecraft:netherrack",
        ))
        for z in range(fz0, fz1):
            ops.append(PlaceBlock(x_hearth, a.y0 + 1, z, "minecraft:campfire"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Sofa + coffee table
# ────────────────────────────────────────────────────────────────────────

def _sofa_and_table(a: AABB, stairs_block: str) -> List[Op]:
    """Place a 3-block sofa (stairs facing the room center) and a coffee
    table one block in front of it. Sofa is positioned on the wall opposite
    the fireplace so the seating "faces" the hearth.

    `stairs_block` is the already-resolved namespaced id (e.g.
    `minecraft:oak_stairs`) so we can append blockstate suffixes — the
    `@stairs` placeholder cannot carry suffixes through `_resolve`.
    """
    ops: List[Op] = []
    interior_w = a.w - 2
    interior_d = a.d - 2
    if min(interior_w, interior_d) < 2:
        return ops

    sofa_y = a.y0 + 1  # one block above the floor

    if a.w >= a.d:
        # Fireplace lives on north wall → sofa on south, facing north.
        sofa_z = a.z1 - 2
        # Center 3 stairs along x; clamp to interior columns.
        sofa_len = 3 if interior_w >= 3 else max(2, interior_w)
        sx0 = a.x0 + 1 + max(0, (interior_w - sofa_len) // 2)
        sx1 = min(a.x1 - 1, sx0 + sofa_len)
        for x in range(sx0, sx1):
            ops.append(PlaceBlock(
                x, sofa_y, sofa_z,
                f"{stairs_block}[facing=north]",
            ))
        # Coffee table one block in front (toward the fireplace).
        table_x = sx0 + (sx1 - sx0) // 2
        table_z = sofa_z - 2
        if table_z > a.z0 and table_z < a.z1 - 1:
            ops.append(PlaceBlock(table_x, sofa_y, table_z, "minecraft:crafting_table"))
    else:
        # Fireplace on west wall → sofa on east, facing west.
        sofa_x = a.x1 - 2
        sofa_len = 3 if interior_d >= 3 else max(2, interior_d)
        sz0 = a.z0 + 1 + max(0, (interior_d - sofa_len) // 2)
        sz1 = min(a.z1 - 1, sz0 + sofa_len)
        for z in range(sz0, sz1):
            ops.append(PlaceBlock(
                sofa_x, sofa_y, z,
                f"{stairs_block}[facing=west]",
            ))
        table_z = sz0 + (sz1 - sz0) // 2
        table_x = sofa_x - 2
        if table_x > a.x0 and table_x < a.x1 - 1:
            ops.append(PlaceBlock(table_x, sofa_y, table_z, "minecraft:crafting_table"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Bookshelf
# ────────────────────────────────────────────────────────────────────────

def _bookshelf(a: AABB) -> List[Op]:
    """Drop a bookshelf against a side wall (perpendicular to the fireplace
    wall) so it does not block the sofa or hearth."""
    ops: List[Op] = []
    if a.w < 4 or a.d < 4 or a.h < 3:
        return ops

    y = a.y0 + 1
    if a.w >= a.d:
        # Side wall = east wall (x = x1-1). Place against it from the inside.
        x = a.x1 - 2
        z = a.z0 + 1  # near the fireplace-side corner
        ops.append(PlaceBlock(x, y, z, "minecraft:bookshelf"))
    else:
        # Side wall = north wall (z = z0). Place against it.
        x = a.x0 + 1
        z = a.z0 + 1
        # If fireplace took (x0+1, *) already, nudge east.
        ops.append(PlaceBlock(x + 1 if a.w >= 4 else x, y, z, "minecraft:bookshelf"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Carpets (>= 2)
# ────────────────────────────────────────────────────────────────────────

def _carpets(a: AABB) -> List[Op]:
    """At least two @carpet patches on the floor surface (y = y0 + 1 above
    the floor block). Sized to room dimensions, avoiding the wall ring."""
    ops: List[Op] = []
    interior_w = a.w - 2
    interior_d = a.d - 2
    if interior_w < 2 or interior_d < 2:
        return ops

    y_carpet = a.y0 + 1  # carpet sits on top of the floor

    # Rug 1: under the coffee table area, between sofa and fireplace.
    if a.w >= a.d:
        rw = min(3, interior_w)
        rd = min(3, interior_d - 2)
        rx0 = a.x0 + 1 + max(0, (interior_w - rw) // 2)
        rz0 = a.z0 + 2  # leave hearth row clear, center between sofa & fireplace
        rx1 = rx0 + rw
        rz1 = min(a.z1 - 2, rz0 + max(1, rd))
        ops.append(Fill(AABB(rx0, y_carpet, rz0, rx1, y_carpet + 1, rz1), "@carpet"))

        # Rug 2: a smaller secondary rug near the bookshelf corner.
        sec_x = a.x1 - 3 if a.x1 - 3 > a.x0 + 1 else a.x0 + 1
        sec_z = a.z1 - 3 if a.z1 - 3 > a.z0 + 1 else a.z0 + 1
        ops.append(PlaceBlock(sec_x, y_carpet, sec_z, "@carpet"))
        ops.append(PlaceBlock(sec_x, y_carpet, max(sec_z - 1, a.z0 + 1), "@carpet"))
    else:
        rd = min(3, interior_d)
        rw = min(3, interior_w - 2)
        rz0 = a.z0 + 1 + max(0, (interior_d - rd) // 2)
        rx0 = a.x0 + 2
        rz1 = rz0 + rd
        rx1 = min(a.x1 - 2, rx0 + max(1, rw))
        ops.append(Fill(AABB(rx0, y_carpet, rz0, rx1, y_carpet + 1, rz1), "@carpet"))

        sec_x = a.x1 - 3 if a.x1 - 3 > a.x0 + 1 else a.x0 + 1
        sec_z = a.z1 - 3 if a.z1 - 3 > a.z0 + 1 else a.z0 + 1
        ops.append(PlaceBlock(sec_x, y_carpet, sec_z, "@carpet"))
        ops.append(PlaceBlock(max(sec_x - 1, a.x0 + 1), y_carpet, sec_z, "@carpet"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Lights (>= 2)
# ────────────────────────────────────────────────────────────────────────

def _lights(a: AABB) -> List[Op]:
    """Two interior light blocks (@light) on opposite interior corners just
    below the lintel. Falls back gracefully on tiny rooms."""
    ops: List[Op] = []
    if a.h < 3 or a.w < 3 or a.d < 3:
        return ops

    y_light = a.y1 - 2  # one block under the lintel row
    if y_light <= a.y0:
        y_light = a.y0 + 1

    # Two diagonally opposite interior corner cells.
    ops.append(PlaceBlock(a.x0 + 1, y_light, a.z0 + 1, "@light"))
    ops.append(PlaceBlock(a.x1 - 2, y_light, a.z1 - 2, "@light"))

    # Bonus light only when the room is medium+ — keeps small rooms tidy.
    if a.w >= 8 and a.d >= 8:
        ops.append(PlaceBlock(a.x1 - 2, y_light, a.z0 + 1, "@light"))
        ops.append(PlaceBlock(a.x0 + 1, y_light, a.z1 - 2, "@light"))

    return ops
