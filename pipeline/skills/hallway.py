"""Hallway skill — corridor connecting two rooms.

A hallway is a tubular space: a floor, two long lateral walls along the
longer horizontal axis (the corridor's length axis), a flat ceiling that
encloses it, and two open short ends so the corridor can connect to the
rooms it joins. Decorated with ceiling lights spaced every 3-4 blocks, one
or two carpet runners on the floor, and (when there's room) flower-pot
niches every 5 blocks on one side wall.

Layout summary:
    - Floor plane of `@floor` at y0.
    - Lateral walls of `@primary` along the longer axis (full height, top
      row excluded — that's where the ceiling sits). Short ends are LEFT
      OPEN (no end walls) so the hallway is a true connector.
    - Ceiling at y_top: a flat plane of `@slab`. (Fantasy-style very long
      corridors get beams every 2 blocks of `@primary` instead of an
      uninterrupted slab plane, evoking a vaulted passage.)
    - Lights: alternating `@light` blocks every 3-4 blocks along the
      centre of the ceiling — at least 2 lights even for tiny corridors.
    - Carpet runners: 1-2 strips of `@carpet` on the floor (centred for
      narrow halls; offset for wider ones).
    - Niches: every 5 blocks along one side wall, a `minecraft:flower_pot`
      sits in a small alcove (cut wall block + pot).

Defensive on AABB sizes from 3x3x6 (short, narrow corridor) up to
4x4x16 (long, taller corridor) and the preview default boxes
(6x4x6 small, 12x6x12 medium). The longer of `aabb.w` / `aabb.d` is
treated as the corridor's length; the shorter as its width.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# ────────────────────────────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────────────────────────────


def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Return AST ops that materialize a hallway inside `aabb`."""
    s = (style or "medieval").lower()

    ops: List[Op] = []
    ops.extend(_floor(aabb))
    ops.extend(_lateral_walls(aabb))
    ops.extend(_ceiling(aabb, s))
    ops.extend(_lights(aabb))
    ops.extend(_carpet_runners(aabb))
    ops.extend(_niches(aabb))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Axis helpers
# ────────────────────────────────────────────────────────────────────────


def _length_axis(aabb: AABB) -> str:
    """Return 'x' if the corridor runs along x, else 'z' (when equal, prefer z)."""
    return "x" if aabb.w > aabb.d else "z"


# ────────────────────────────────────────────────────────────────────────
#  Layout helpers
# ────────────────────────────────────────────────────────────────────────


def _floor(aabb: AABB) -> List[Op]:
    """Solid floor plane on y == aabb.y0 using @floor."""
    floor_plane = AABB(aabb.x0, aabb.y0, aabb.z0, aabb.x1, aabb.y0 + 1, aabb.z1)
    return [Rect(floor_plane, "@floor", axis="y", level=aabb.y0)]


def _lateral_walls(aabb: AABB) -> List[Op]:
    """Two lateral walls of @primary along the LONGER axis.

    Short-end walls are intentionally OMITTED so the corridor connects.
    The walls go from y0+1 (above the floor) up to y1-1 exclusive
    (leaving the top row for the ceiling slab).
    """
    y0w = aabb.y0 + 1
    y1w = max(aabb.y1 - 1, y0w + 1)  # at least one wall row
    ops: List[Op] = []
    if _length_axis(aabb) == "x":
        # Corridor runs along x → walls on z = z0 and z = z1-1
        ops.append(Fill(AABB(aabb.x0, y0w, aabb.z0,
                             aabb.x1, y1w, aabb.z0 + 1), "@primary"))
        ops.append(Fill(AABB(aabb.x0, y0w, aabb.z1 - 1,
                             aabb.x1, y1w, aabb.z1), "@primary"))
    else:
        # Corridor runs along z → walls on x = x0 and x = x1-1
        ops.append(Fill(AABB(aabb.x0, y0w, aabb.z0,
                             aabb.x0 + 1, y1w, aabb.z1), "@primary"))
        ops.append(Fill(AABB(aabb.x1 - 1, y0w, aabb.z0,
                             aabb.x1, y1w, aabb.z1), "@primary"))
    return ops


def _ceiling(aabb: AABB, style: str) -> List[Op]:
    """Ceiling at y_top.

    Default: a flat plane of @slab covering the full footprint. For
    fantasy long corridors we instead drop @primary beams every 2 blocks
    along the length axis, leaving the bays between them open.
    """
    if aabb.h < 3:
        return []  # too short — no ceiling fits

    y_top = aabb.y1 - 1
    long_axis = _length_axis(aabb)
    length = aabb.w if long_axis == "x" else aabb.d

    # Beam variant: fantasy + long corridor (length >= 8).
    if style == "fantasy" and length >= 8:
        ops: List[Op] = []
        if long_axis == "x":
            # Beams are perpendicular to the corridor's length, every 2 blocks.
            for x in range(aabb.x0, aabb.x1, 2):
                ops.append(Fill(AABB(x, y_top, aabb.z0,
                                     x + 1, y_top + 1, aabb.z1), "@primary"))
        else:
            for z in range(aabb.z0, aabb.z1, 2):
                ops.append(Fill(AABB(aabb.x0, y_top, z,
                                     aabb.x1, y_top + 1, z + 1), "@primary"))
        return ops

    # Default: solid slab plane.
    ceiling_plane = AABB(aabb.x0, y_top, aabb.z0, aabb.x1, y_top + 1, aabb.z1)
    return [Rect(ceiling_plane, "@slab", axis="y", level=y_top)]


def _lights(aabb: AABB) -> List[Op]:
    """Alternating @light blocks every 3-4 blocks along the ceiling centre.

    Lights sit just below the ceiling so they illuminate the corridor.
    For very short halls we still guarantee at least 2 lights.
    """
    ops: List[Op] = []
    if aabb.h < 3:
        # Can't fit a separate light row below the ceiling — drop them on
        # the floor as a degenerate fallback.
        y_light = aabb.y0 + 1
    else:
        y_light = aabb.y1 - 2  # one row below the ceiling

    long_axis = _length_axis(aabb)
    spacing = 3  # every 3 blocks along the corridor

    if long_axis == "x":
        z_c = (aabb.z0 + aabb.z1 - 1) // 2
        positions = list(range(aabb.x0 + 1, aabb.x1 - 1, spacing))
        # Ensure at least 2 lights — even tiny halls get bookends.
        if len(positions) < 2:
            positions = [aabb.x0 + 1, max(aabb.x0 + 2, aabb.x1 - 2)]
        for x in positions:
            ops.append(PlaceBlock(x, y_light, z_c, "@light"))
    else:
        x_c = (aabb.x0 + aabb.x1 - 1) // 2
        positions = list(range(aabb.z0 + 1, aabb.z1 - 1, spacing))
        if len(positions) < 2:
            positions = [aabb.z0 + 1, max(aabb.z0 + 2, aabb.z1 - 2)]
        for z in positions:
            ops.append(PlaceBlock(x_c, y_light, z, "@light"))

    return ops


def _carpet_runners(aabb: AABB) -> List[Op]:
    """1-2 carpet runners of @carpet along the floor.

    A narrow corridor (interior width <= 2) gets a single centred runner.
    A wider corridor (interior width >= 3) gets two parallel runners.
    """
    ops: List[Op] = []
    long_axis = _length_axis(aabb)
    y_c = aabb.y0 + 1  # carpets sit on top of the floor block

    if long_axis == "x":
        interior_x_start = aabb.x0 + 1
        interior_x_end = aabb.x1 - 1   # exclusive
        if interior_x_end <= interior_x_start:
            return ops
        # Interior z range (between the two lateral walls).
        in_z0 = aabb.z0 + 1
        in_z1 = aabb.z1 - 1            # exclusive
        interior_w = in_z1 - in_z0
        if interior_w <= 0:
            return ops
        if interior_w <= 2:
            z_lanes = [(in_z0 + in_z1 - 1) // 2]
        else:
            z_lanes = [in_z0, in_z1 - 1]
        for z in z_lanes:
            for x in range(interior_x_start, interior_x_end):
                ops.append(PlaceBlock(x, y_c, z, "@carpet"))
    else:
        interior_z_start = aabb.z0 + 1
        interior_z_end = aabb.z1 - 1
        if interior_z_end <= interior_z_start:
            return ops
        in_x0 = aabb.x0 + 1
        in_x1 = aabb.x1 - 1
        interior_w = in_x1 - in_x0
        if interior_w <= 0:
            return ops
        if interior_w <= 2:
            x_lanes = [(in_x0 + in_x1 - 1) // 2]
        else:
            x_lanes = [in_x0, in_x1 - 1]
        for x in x_lanes:
            for z in range(interior_z_start, interior_z_end):
                ops.append(PlaceBlock(x, y_c, z, "@carpet"))

    return ops


def _niches(aabb: AABB) -> List[Op]:
    """Flower-pot niches every 5 blocks along one side wall.

    Only emitted when the corridor is long enough (>= 6 blocks along its
    length axis) and tall enough (>= 3) to keep the pot above the carpet
    and below the ceiling. The niche occupies the interior cell of the
    wall (one block inset), with the pot block placed at floor + 1.
    """
    if aabb.h < 3:
        return []
    long_axis = _length_axis(aabb)
    length = aabb.w if long_axis == "x" else aabb.d
    if length < 6:
        return []

    ops: List[Op] = []
    y_pot = aabb.y0 + 1
    spacing = 5

    if long_axis == "x":
        # Mount on the north interior wall (z = z0 + 1).
        z_n = aabb.z0 + 1
        # Skip 1st and last blocks so pots don't sit at the open ends.
        positions = list(range(aabb.x0 + 2, aabb.x1 - 2, spacing))
        for x in positions:
            ops.append(PlaceBlock(x, y_pot, z_n, "minecraft:flower_pot"))
    else:
        x_w = aabb.x0 + 1
        positions = list(range(aabb.z0 + 2, aabb.z1 - 2, spacing))
        for z in positions:
            ops.append(PlaceBlock(x_w, y_pot, z, "minecraft:flower_pot"))

    return ops
