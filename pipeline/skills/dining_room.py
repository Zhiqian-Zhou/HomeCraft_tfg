"""Dining room skill — a communal eating space.

Builds a rectangular dining hall with:

    * a @floor plane,
    * @primary walls,
    * an open beamed ceiling (a sparse grid of @primary beams instead of
      a solid roof) so the room feels airy,
    * a central table laid along the long horizontal axis — a row of
      @primary blocks at y = y0 + 1 (so the table-top sits one block
      above the floor),
    * @stairs chairs flanking the long sides of the table, facing in
      toward the diners,
    * a chandelier above the table center: a small cluster of @primary
      blocks attached to the ceiling with a `minecraft:lantern` hanging
      below them,
    * at least one `minecraft:flower_pot` as a table-top centerpiece,
    * a `minecraft:barrel` against a wall for tableware/storage.

Defensive on AABBs from 6×4×6 up to 12×5×14 — the table length and chair
count scale with the long axis; tiny rooms still receive a 1-block table,
2 chairs, a lantern (no ceiling cluster if the ceiling is too low), a
flower pot, and a barrel.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock, Fill, Rect


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    ops: List[Op] = []

    if aabb.w < 3 or aabb.d < 3 or aabb.h < 3:
        # Too small to be a meaningful dining room.
        return ops

    # ── Shell ──────────────────────────────────────────────────────────
    # Floor: a full @floor plane at y0.
    ops.append(Rect(aabb, "@floor", axis="y", level=aabb.y0))

    # Walls: a 1-block-thick @primary border for every y above the floor
    # and below the ceiling. Walls span y0 .. y1-1 inclusive.
    for y in range(aabb.y0 + 1, aabb.y1):
        # North / south walls (z = z0 and z = z1-1).
        ops.append(Fill(AABB(aabb.x0, y, aabb.z0,
                              aabb.x1, y + 1, aabb.z0 + 1), "@primary"))
        ops.append(Fill(AABB(aabb.x0, y, aabb.z1 - 1,
                              aabb.x1, y + 1, aabb.z1), "@primary"))
        # East / west walls (x = x0 and x = x1-1).
        ops.append(Fill(AABB(aabb.x0, y, aabb.z0,
                              aabb.x0 + 1, y + 1, aabb.z1), "@primary"))
        ops.append(Fill(AABB(aabb.x1 - 1, y, aabb.z0,
                              aabb.x1, y + 1, aabb.z1), "@primary"))

    # ── Open beamed ceiling ────────────────────────────────────────────
    # Instead of a solid lid we lay beams every 3 cells along the long
    # axis. This keeps the room visually open.
    ceil_y = aabb.y1 - 1
    long_along_x = aabb.w >= aabb.d
    if long_along_x:
        # Beams run along z (full depth), spaced along x.
        for x in range(aabb.x0 + 1, aabb.x1 - 1, 3):
            ops.append(Fill(AABB(x, ceil_y, aabb.z0 + 1,
                                  x + 1, ceil_y + 1, aabb.z1 - 1),
                            "@primary"))
    else:
        # Beams run along x, spaced along z.
        for z in range(aabb.z0 + 1, aabb.z1 - 1, 3):
            ops.append(Fill(AABB(aabb.x0 + 1, ceil_y, z,
                                  aabb.x1 - 1, ceil_y + 1, z + 1),
                            "@primary"))

    # ── Central table ──────────────────────────────────────────────────
    # The table is one block tall, one block wide, laid along the long
    # axis, centered between the walls and clear of them. We leave at
    # least one cell between the table and the long walls so chairs fit.
    table_y = aabb.y0 + 1
    if long_along_x:
        # Run table along x; center along z.
        t_x0 = aabb.x0 + 2
        t_x1 = aabb.x1 - 2
        t_z = aabb.cz
        if t_x1 <= t_x0:
            # Tiny room: fall back to a single-block table at center.
            t_x0, t_x1 = aabb.cx, aabb.cx + 1
        table_aabb = AABB(t_x0, table_y, t_z,
                          t_x1, table_y + 1, t_z + 1)
        ops.append(Fill(table_aabb, "@primary"))
        table_len = t_x1 - t_x0
        table_axis = "x"
        table_center = (
            (t_x0 + t_x1 - 1) // 2,
            table_y,
            t_z,
        )
    else:
        # Run table along z; center along x.
        t_z0 = aabb.z0 + 2
        t_z1 = aabb.z1 - 2
        t_x = aabb.cx
        if t_z1 <= t_z0:
            t_z0, t_z1 = aabb.cz, aabb.cz + 1
        table_aabb = AABB(t_x, table_y, t_z0,
                          t_x + 1, table_y + 1, t_z1)
        ops.append(Fill(table_aabb, "@primary"))
        table_len = t_z1 - t_z0
        table_axis = "z"
        table_center = (
            t_x,
            table_y,
            (t_z0 + t_z1 - 1) // 2,
        )

    # ── Chairs (stairs blocks facing the table) ────────────────────────
    # Place up to ⌈table_len / 2⌉ chairs per long side, but cap at 2 per
    # side for the smallest rooms (per the brief).
    chairs_per_side = max(2, table_len // 2)
    chair_y = aabb.y0  # chair sits on the floor; stair seat at y0
    if table_axis == "x":
        # Chairs sit at z = table_z - 1 (facing south, toward +z) and
        # at z = table_z + 1 (facing north, toward -z).
        table_z = table_aabb.z0
        # Distribute chair x positions evenly inside the table run.
        x_positions = _spread(table_aabb.x0, table_aabb.x1, chairs_per_side)
        for cx in x_positions:
            # North-side chair (smaller z), seat facing +z (south).
            nz = table_z - 1
            if aabb.contains(cx, chair_y, nz) and nz > aabb.z0:
                ops.append(PlaceBlock(cx, chair_y, nz, "@stairs[facing=south]"))
            # South-side chair, seat facing -z (north).
            sz = table_z + 1
            if aabb.contains(cx, chair_y, sz) and sz < aabb.z1 - 1:
                ops.append(PlaceBlock(cx, chair_y, sz, "@stairs[facing=north]"))
    else:
        table_x = table_aabb.x0
        z_positions = _spread(table_aabb.z0, table_aabb.z1, chairs_per_side)
        for cz in z_positions:
            wx = table_x - 1
            if aabb.contains(wx, chair_y, cz) and wx > aabb.x0:
                ops.append(PlaceBlock(wx, chair_y, cz, "@stairs[facing=east]"))
            ex = table_x + 1
            if aabb.contains(ex, chair_y, cz) and ex < aabb.x1 - 1:
                ops.append(PlaceBlock(ex, chair_y, cz, "@stairs[facing=west]"))

    # ── Chandelier (lantern hanging from ceiling above table center) ───
    # We anchor a tiny cluster of @primary blocks to the ceiling beam
    # above the table center, then hang a lantern one cell below.
    ccx, _, ccz = table_center
    # Hide the cluster one row below the ceiling so the lantern dangles
    # in mid-air rather than sitting flush with the lid.
    cluster_y = ceil_y - 1
    if cluster_y > table_y:
        # Small cluster: just the center cell. (Bigger rooms get a 3-cell
        # cluster along the long axis.)
        if table_len >= 4 and cluster_y >= aabb.y0 + 2:
            if table_axis == "x":
                ops.append(Fill(AABB(ccx - 1, cluster_y, ccz,
                                      ccx + 2, cluster_y + 1, ccz + 1),
                                "@primary"))
            else:
                ops.append(Fill(AABB(ccx, cluster_y, ccz - 1,
                                      ccx + 1, cluster_y + 1, ccz + 2),
                                "@primary"))
        else:
            ops.append(PlaceBlock(ccx, cluster_y, ccz, "@primary"))

        # Lantern hangs one cell below the cluster.
        lantern_y = cluster_y - 1
        if lantern_y > table_y:
            ops.append(PlaceBlock(ccx, lantern_y, ccz,
                                  "minecraft:lantern[hanging=true]"))

    # ── Flower pot centerpiece ─────────────────────────────────────────
    # One flower pot sitting on top of the table. We pick the table's
    # own center (or one off-center if the chandelier is right above it
    # in a small room).
    pot_y = table_y + 1
    pot_x, pot_z = table_center[0], table_center[2]
    if table_axis == "x" and table_len >= 3:
        # Offset so the chandelier doesn't sit directly above the pot.
        pot_x = pot_x - 1 if pot_x - 1 >= table_aabb.x0 else pot_x + 1
    elif table_axis == "z" and table_len >= 3:
        pot_z = pot_z - 1 if pot_z - 1 >= table_aabb.z0 else pot_z + 1
    if aabb.contains(pot_x, pot_y, pot_z):
        ops.append(PlaceBlock(pot_x, pot_y, pot_z, "minecraft:flower_pot"))

    # ── Barrel (tableware storage) ─────────────────────────────────────
    # Place against an interior wall corner so it doesn't crowd the
    # table. We pick the (x0+1, y0, z0+1) corner.
    barrel_x = aabb.x0 + 1
    barrel_z = aabb.z0 + 1
    if aabb.contains(barrel_x, aabb.y0, barrel_z):
        ops.append(PlaceBlock(barrel_x, aabb.y0, barrel_z, "minecraft:barrel"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────

def _spread(lo: int, hi: int, n: int) -> list[int]:
    """Return `n` integer positions evenly spread inside [lo, hi).

    Always returns at least 1 position. When n >= hi-lo, returns each
    cell in the range. Used to evenly distribute chairs along a table.
    """
    span = hi - lo
    if span <= 0:
        return []
    n = max(1, min(n, span))
    if n == 1:
        return [lo + span // 2]
    step = span / n
    return [int(lo + step * (i + 0.5)) for i in range(n)]
