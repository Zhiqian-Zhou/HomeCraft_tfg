"""Skill: window_bay.

A bay window — a small box that protrudes 1-2 blocks AWAY from a flat wall.
The AABB describes the wall section to which the bay attaches; the bay
itself is a separate box extruded outward along `protrude_axis`.

Layout (looking from outside, '+z' default):

    +-----+      ← @slab cap
    |     |     ← @glass_pane on the 3 exposed faces (front + 2 sides)
    |  L  | ← interior lantern (L) and flower pot
    | .P. |
    +-----+      ← @primary floor of the bay (also the sill)

`protrude_axis` kwarg picks which way the bay sticks out:
    '+x', '-x', '+z', '-z' (default '+z').

Defensive sizing for the wall section AABB:
    min: 3 × 3 × 1   (width × height × depth-of-wall)
    max: 5 × 4 × 2
The bay is always 3 cells wide (centered on the wall section), 2 cells deep
along the protrude axis (so 1-2 blocks of protrusion), and 2-3 cells tall
depending on the wall height available.

Coordinate convention matches `base.py`: x = width, y = height (up), z =
depth, AABB is half-open.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, Fill, PlaceBlock, Rect


# Defensive bounds for the wall section AABB.
_MIN = (3, 3, 1)
_MAX = (5, 4, 2)

# Recognised protrude axes.
_AXES = {"+x", "-x", "+z", "-z"}


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the wall-section AABB into the [3..5, 3..4, 1..2] envelope.

    The lower corner is preserved; the upper corner is shifted to satisfy the
    size constraints. Keeps the bay well-formed even on pathological inputs.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a bay window protruding from a wall section.

    The wall section is given by `aabb`; the bay box is constructed adjacent
    to it along `protrude_axis` (default '+z').
    """
    axis = str(kwargs.get("protrude_axis", "+z"))
    if axis not in _AXES:
        axis = "+z"

    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # Bay footprint: 3 wide on the wall plane, 2 deep along the protrude axis.
    # The "wall plane" depends on which axis we extrude along:
    #   +z / -z  → wall is the x-axis; bay is 3 wide in x, 2 deep in z.
    #   +x / -x  → wall is the z-axis; bay is 3 wide in z, 2 deep in x.
    # The bay height is 3 if the wall section affords it, else 2.
    bay_h = 3 if a.h >= 3 else 2

    if axis in ("+z", "-z"):
        # Bay width along x, centered on the wall section.
        cx = a.cx
        bx0 = cx - 1
        bx1 = cx + 2  # 3 wide
        if axis == "+z":
            bz0 = a.z1            # starts just outside the far wall face
            bz1 = bz0 + 2         # 2-deep protrusion
        else:  # '-z'
            bz1 = a.z0
            bz0 = bz1 - 2
        by0 = a.y0
        by1 = a.y0 + bay_h
        # Front face is the face farthest from the wall on the protrude axis.
        if axis == "+z":
            front_z = bz1 - 1
            side_xs = (bx0, bx1 - 1)
            side_zs = None  # sides span z
            wall_z = bz0 - 1  # plane where the bay meets the wall (just inside the wall)
        else:
            front_z = bz0
            side_xs = (bx0, bx1 - 1)
            side_zs = None
            wall_z = bz1  # plane where the bay meets the wall
    else:
        # Bay width along z, centered on the wall section.
        cz = a.cz
        bz0 = cz - 1
        bz1 = cz + 2
        if axis == "+x":
            bx0 = a.x1
            bx1 = bx0 + 2
        else:  # '-x'
            bx1 = a.x0
            bx0 = bx1 - 2
        by0 = a.y0
        by1 = a.y0 + bay_h
        if axis == "+x":
            front_x = bx1 - 1
            side_zs_xz = (bz0, bz1 - 1)
            wall_x = bx0 - 1
        else:
            front_x = bx0
            side_zs_xz = (bz0, bz1 - 1)
            wall_x = bx1

    # ── 1) Floor of the bay (sill) — @primary along the bay footprint. ──
    if axis in ("+z", "-z"):
        floor_box = AABB(bx0, by0, bz0, bx1, by0 + 1, bz1)
    else:
        floor_box = AABB(bx0, by0, bz0, bx1, by0 + 1, bz1)
    ops.append(Fill(floor_box, "@primary"))

    # ── 2) Top cap — @slab one block above the highest glass row. ──
    cap_y = by1  # cap sits on top of the bay box
    if axis in ("+z", "-z"):
        cap_box = AABB(bx0, cap_y, bz0, bx1, cap_y + 1, bz1)
    else:
        cap_box = AABB(bx0, cap_y, bz0, bx1, cap_y + 1, bz1)
    ops.append(Fill(cap_box, "@slab"))

    # ── 3) Glass on the 3 exposed faces (front + 2 sides). ──
    #     Glass spans the rows above the floor up to (cap_y - 1) inclusive,
    #     i.e. y in [by0 + 1 .. by1 - 1].
    gy0 = by0 + 1
    gy1 = by1  # half-open upper bound for the glass rows
    if gy1 <= gy0:
        gy1 = gy0 + 1  # ensure at least one row of glass

    if axis in ("+z", "-z"):
        # Front face (constant z = front_z): all x in [bx0..bx1)
        for y in range(gy0, gy1):
            for x in range(bx0, bx1):
                ops.append(PlaceBlock(x, y, front_z, "@glass"))
        # Two side faces (constant x = bx0 and x = bx1 - 1): z in (bz0..bz1)
        # but we exclude the wall-attached cell (the cell adjacent to the
        # wall) so glass doesn't punch through the host wall.
        for xc in side_xs:
            for y in range(gy0, gy1):
                for z in range(bz0, bz1):
                    # Skip the cell that touches the host wall plane and the
                    # front-face cell (already placed above).
                    if z == wall_z:
                        continue
                    if z == front_z:
                        continue
                    ops.append(PlaceBlock(xc, y, z, "@glass"))
    else:
        # Front face (constant x = front_x): all z in [bz0..bz1)
        for y in range(gy0, gy1):
            for z in range(bz0, bz1):
                ops.append(PlaceBlock(front_x, y, z, "@glass"))
        # Two side faces (constant z = bz0 and z = bz1 - 1): x in (bx0..bx1)
        for zc in side_zs_xz:
            for y in range(gy0, gy1):
                for x in range(bx0, bx1):
                    if x == wall_x:
                        continue
                    if x == front_x:
                        continue
                    ops.append(PlaceBlock(x, y, zc, "@glass"))

    # ── 4) Interior furniture: 1 flower_pot + 1 lantern. ──
    #     Place both on the bay floor (y = by0 + 1), within the interior
    #     cells (not on the glass perimeter).
    if axis in ("+z", "-z"):
        # Interior cells: x in (bx0, bx1-1) exclusive of side glass; z in
        # (bz0, bz1) excluding the front-glass cell and the wall-attached cell.
        # For a 3-wide × 2-deep bay this gives a 1×0 cross-section after
        # removing perimeter — we relax by placing on the floor row at y0
        # (the floor is solid @primary; we overwrite that cell with the
        # decorative block, which is fine since the floor below remains a
        # single course of @primary at y = by0 - 1 if any; here the floor
        # IS at y = by0, so the flower pot sits at y = by0 + 0 surface).
        # Practical placement: use the floor y0 plane center-front and
        # center-back interior cells; "later wins" composer overrides the
        # @primary floor at those two cells, leaving them as furniture.
        pot_x = bx0 + 1            # middle of the 3-wide front
        pot_z = front_z if axis == "+z" else front_z
        # Pull the pot one cell inward off the front glass so it sits
        # inside the bay, not on the glass column.
        if axis == "+z":
            pot_z = front_z - 1
            lantern_z = front_z - 1
        else:
            pot_z = front_z + 1
            lantern_z = front_z + 1
        # Lantern on the opposite interior cell so the two never collide.
        lantern_x = bx0 + 1
        # If the interior depth allows separating them along x, do so.
        # The bay is 3-wide so we have x in {bx0, bx0+1, bx1-1}; the middle
        # column is the only one not touching the side glass. We put the pot
        # in the middle and place the lantern on top of the slab cap so it
        # lights the alcove without colliding with the pot.
        ops.append(PlaceBlock(pot_x, by0, pot_z, "minecraft:flower_pot"))
        # Hanging lantern under the cap, in the same middle column but one
        # row below the slab cap.
        ops.append(PlaceBlock(lantern_x, cap_y - 1, lantern_z, "minecraft:lantern[hanging=true]"))
    else:
        if axis == "+x":
            pot_x = front_x - 1
            lantern_x = front_x - 1
        else:
            pot_x = front_x + 1
            lantern_x = front_x + 1
        pot_z = bz0 + 1
        lantern_z = bz0 + 1
        ops.append(PlaceBlock(pot_x, by0, pot_z, "minecraft:flower_pot"))
        ops.append(PlaceBlock(lantern_x, cap_y - 1, lantern_z, "minecraft:lantern[hanging=true]"))

    return ops


# Kept so future variants (e.g. a rectangular cap) can use Rect.
_ = Rect
