"""Skill: balcony.

A small balcony that protrudes 2-3 blocks AWAY from a flat wall section.
The AABB describes the wall section where the balcony attaches; the balcony
itself is a separate floor slab extruded outward along `protrude_axis`,
ringed by a railing on the 3 free edges, with decorative corbelling
underneath and a small overhang with a hanging lantern above.

Layout (looking from outside, '+z' default):

       L              ← @lantern hanging from a small @primary overhang
       ┌─P────P─┐     ← @primary overhang stub, @flower_pot on rail corners
       │  fence │     ← @fence ring on 3 free edges
       │   G    │     ← @fence_gate centred on the far edge (optional access)
       ┌────────┐     ← @floor rectangle (balcony deck)
        \\      /     ← @stairs underside corbel (decorative)

`protrude_axis` kwarg picks which way the balcony sticks out:
    '+x', '-x', '+z', '-z' (default '+z').

Defensive sizing for the wall section AABB:
    min: 3 × 3 × 2   (width × height × depth-of-wall)
    max: 6 × 4 × 3
The deck is centred 3-5 cells wide along the wall plane and 2-3 cells deep
along the protrude axis. Out-of-range AABBs are clamped, never raised.

Coordinate convention matches `base.py`: x = width, y = height (up), z =
depth, AABB is half-open.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, Fill, PlaceBlock, Rect


# Defensive bounds for the wall-section AABB.
_MIN = (3, 3, 2)
_MAX = (6, 4, 3)

# Recognised protrude axes.
_AXES = {"+x", "-x", "+z", "-z"}


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the wall-section AABB into the [3..6, 3..4, 2..3] envelope.

    The lower corner is preserved; the upper corner is shifted to satisfy
    the size constraints. Keeps the balcony well-formed on pathological
    inputs.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


# Maps the outward normal to the stairs `facing` value to use for the
# decorative underside corbel. The corbel sits one row below the deck and
# faces back toward the wall, so its half-block step reads like a bracket
# carrying the floor.
_CORBEL_FACING = {
    "+z": "north",   # corbel under a +z balcony faces back toward -z (wall)
    "-z": "south",
    "+x": "west",
    "-x": "east",
}


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a balcony protruding from a wall section.

    The wall section is given by `aabb`; the deck is constructed adjacent to
    it along `protrude_axis` (default '+z').
    """
    axis = str(kwargs.get("protrude_axis", "+z"))
    if axis not in _AXES:
        axis = "+z"

    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # Deck width along the wall plane: use the available wall width (3..5),
    # capped at 5 so the deck stays human-scale even on a 6-wide section.
    deck_w_on_wall = min(5, max(3, a.w if axis in ("+z", "-z") else a.d))
    # Deck depth along the protrude axis: 2..3 blocks of protrusion.
    deck_depth = 3 if a.h >= 4 else 2

    # The deck is anchored one row above the AABB floor (y0 + 1) so the
    # corbel sits below it at y0. This gives the visual support reading.
    deck_y = a.y0 + 1
    # Overhang/lantern row sits 2 rows above the deck (giving headroom).
    overhang_y = deck_y + 2

    if axis in ("+z", "-z"):
        # Centre the deck along x relative to the wall section.
        cx = a.cx
        bx0 = cx - (deck_w_on_wall // 2)
        bx1 = bx0 + deck_w_on_wall
        if axis == "+z":
            bz0 = a.z1                # just outside the far wall face
            bz1 = bz0 + deck_depth
            wall_side_z = bz0         # edge of the deck that touches the wall
            far_z = bz1 - 1           # edge of the deck farthest from wall
        else:  # '-z'
            bz1 = a.z0
            bz0 = bz1 - deck_depth
            wall_side_z = bz1 - 1
            far_z = bz0
    else:
        cz = a.cz
        bz0 = cz - (deck_w_on_wall // 2)
        bz1 = bz0 + deck_w_on_wall
        if axis == "+x":
            bx0 = a.x1
            bx1 = bx0 + deck_depth
            wall_side_x = bx0
            far_x = bx1 - 1
        else:  # '-x'
            bx1 = a.x0
            bx0 = bx1 - deck_depth
            wall_side_x = bx1 - 1
            far_x = bx0

    # ── 1) Deck: a rectangle of @floor at y = deck_y. ──
    deck_box = AABB(bx0, deck_y, bz0, bx1, deck_y + 1, bz1)
    ops.append(Fill(deck_box, "@floor"))

    # ── 2) Underside corbel: @stairs facing back toward the wall, sitting
    #       one row below the deck along the far edge (and the two side
    #       edges) so the deck looks bracket-supported. We use raw
    #       PlaceBlock with a stair facing-state so the half-step reads as
    #       a corbel rather than a step you'd walk on. ──
    facing = _CORBEL_FACING[axis]
    stairs_block = f"@stairs[facing={facing},half=top]"
    corbel_y = deck_y - 1
    if axis in ("+z", "-z"):
        # Place corbels along the far edge (the protruding edge) of the deck.
        for x in range(bx0, bx1):
            ops.append(PlaceBlock(x, corbel_y, far_z, stairs_block))
        # And a couple along each side edge so the bracket wraps the corner.
        side_zs = [bz0, bz1 - 1]
        for sz in side_zs:
            # Skip the wall-side cell — that's flush against the host wall.
            if sz == wall_side_z:
                continue
            # We have one or two side corbels (depending on deck_depth);
            # face them sideways so they bracket the side edge.
            side_face = "east" if axis in ("+z", "-z") else facing  # noqa: F841
            side_stairs_l = f"@stairs[facing=east,half=top]"
            side_stairs_r = f"@stairs[facing=west,half=top]"
            ops.append(PlaceBlock(bx0, corbel_y, sz, side_stairs_l))
            ops.append(PlaceBlock(bx1 - 1, corbel_y, sz, side_stairs_r))
    else:
        for z in range(bz0, bz1):
            ops.append(PlaceBlock(far_x, corbel_y, z, stairs_block))
        side_xs = [bx0, bx1 - 1]
        for sx in side_xs:
            if sx == wall_side_x:
                continue
            side_stairs_n = f"@stairs[facing=north,half=top]"
            side_stairs_s = f"@stairs[facing=south,half=top]"
            ops.append(PlaceBlock(sx, corbel_y, bz0, side_stairs_n))
            ops.append(PlaceBlock(sx, corbel_y, bz1 - 1, side_stairs_s))

    # ── 3) Railing: @fence on the 3 free edges, one row above the deck. ──
    rail_y = deck_y + 1
    if axis in ("+z", "-z"):
        # Far edge (parallel to wall): full row of fence with a gate in the middle.
        gate_x = (bx0 + bx1 - 1) // 2
        for x in range(bx0, bx1):
            block = "@fence" if x != gate_x else "minecraft:oak_fence_gate"
            # Style-specific gate: use a stylable token via @ would be ideal,
            # but Materials has no fence_gate slot; we fall back to oak.
            ops.append(PlaceBlock(x, rail_y, far_z, block))
        # Two side edges: fence along z from wall_side_z to far_z, excluding
        # the wall-side cell and the corner already placed on the far edge.
        for xc in (bx0, bx1 - 1):
            for z in range(bz0, bz1):
                if z == wall_side_z:
                    continue  # leave the wall-side open for access
                if z == far_z and (xc == bx0 or xc == bx1 - 1):
                    # Corners on the far edge: already placed above as fence.
                    continue
                ops.append(PlaceBlock(xc, rail_y, z, "@fence"))
    else:
        gate_z = (bz0 + bz1 - 1) // 2
        for z in range(bz0, bz1):
            block = "@fence" if z != gate_z else "minecraft:oak_fence_gate"
            ops.append(PlaceBlock(far_x, rail_y, z, block))
        for zc in (bz0, bz1 - 1):
            for x in range(bx0, bx1):
                if x == wall_side_x:
                    continue
                if x == far_x and (zc == bz0 or zc == bz1 - 1):
                    continue
                ops.append(PlaceBlock(x, rail_y, zc, "@fence"))

    # ── 4) Flower pots on the two far-edge railing corners. ──
    #       Pots sit on TOP of the corner fence posts (rail_y + 1) so they
    #       read as planters along the balcony rim.
    pot_y = rail_y + 1
    if axis in ("+z", "-z"):
        ops.append(PlaceBlock(bx0,     pot_y, far_z, "minecraft:flower_pot"))
        ops.append(PlaceBlock(bx1 - 1, pot_y, far_z, "minecraft:flower_pot"))
    else:
        ops.append(PlaceBlock(far_x, pot_y, bz0,     "minecraft:flower_pot"))
        ops.append(PlaceBlock(far_x, pot_y, bz1 - 1, "minecraft:flower_pot"))

    # ── 5) Small overhang above the deck with a lantern hanging from it. ──
    #       The overhang is a single @primary stub at the deck centre, at
    #       `overhang_y`, with a hanging lantern one block below it. The
    #       stub anchors against the host wall column (one cell out from
    #       the wall) so it reads as a bracketed canopy.
    if axis in ("+z", "-z"):
        oh_x = (bx0 + bx1 - 1) // 2
        # Stub sits just out from the wall, over the deck.
        oh_z = wall_side_z if axis == "+z" else wall_side_z
        # Pull the stub one cell outward off the wall plane so it is
        # visibly cantilevered (and so the lantern doesn't sit on the wall).
        if axis == "+z":
            oh_z = wall_side_z + 1 if (wall_side_z + 1) < bz1 else wall_side_z
        else:
            oh_z = wall_side_z - 1 if (wall_side_z - 1) >= bz0 else wall_side_z
        ops.append(PlaceBlock(oh_x, overhang_y, oh_z, "@primary"))
        ops.append(PlaceBlock(oh_x, overhang_y - 1, oh_z, "minecraft:lantern[hanging=true]"))
    else:
        oh_z = (bz0 + bz1 - 1) // 2
        if axis == "+x":
            oh_x = wall_side_x + 1 if (wall_side_x + 1) < bx1 else wall_side_x
        else:
            oh_x = wall_side_x - 1 if (wall_side_x - 1) >= bx0 else wall_side_x
        ops.append(PlaceBlock(oh_x, overhang_y, oh_z, "@primary"))
        ops.append(PlaceBlock(oh_x, overhang_y - 1, oh_z, "minecraft:lantern[hanging=true]"))

    return ops


# Kept for future variants (e.g. tiled deck patterns).
_ = Rect
