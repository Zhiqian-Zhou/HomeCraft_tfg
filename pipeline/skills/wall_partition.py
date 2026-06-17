"""Skill: wall_partition.

An interior partition wall: a 1-block-thick slab of @primary that divides
two rooms inside a building. Unlike the perimeter walls, a partition has
**no foundation course** (it sits on whatever floor the room already
provides — usually @floor laid down by an adjoining room skill) and no
cornice. It is purely a vertical screen of @primary.

Composition (bottom-up):

  - **Wall slab**: solid Fill of @primary, 1-block-thick along the SHORTER
    horizontal axis of the incoming AABB. The wall RUNS along the longer
    horizontal axis. Tie-break: if W == D the wall runs along Z (thin in X
    is unusual, so the default favors the conventional N-S partition).
  - **Door opening**: a 1-wide × 2-tall gap at the AABB center along the
    wall axis (kwarg ``door_opening_at_center``, default ``True``). The
    gap is rendered with ``minecraft:cave_air`` placeholders; the composer
    drops air, so the gap appears as a real hole in the slab.
  - **Window above door**: a single @glass pane one block directly above
    the door head (kwarg ``window_above_door``, default ``True``). Only
    emitted if the wall has enough height clearance.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Kwargs
------
door_opening_at_center : bool, default ``True``
    Whether to cut a 1×2 doorway at the center of the wall axis.
door_height : int, default ``2``
    Height of the door opening (in blocks). Clamped to ``[1, h - 1]``.
window_above_door : bool, default ``True``
    Whether to place a single @glass pane one block above the door head.

Defensive sizing: clamped to 1×3×3 .. 1×6×16 (wall along Z, thin in X) or
3×3×1 .. 16×6×1 (wall along X, thin in Z). If the input AABB is not
already 1-thick, the wall is centered along the shorter axis and the AABB
is collapsed to 1-thick at that midline.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, Fill, PlaceBlock


# Defensive bounds on the wall's RUN length and HEIGHT.
# Thin axis is always 1; long axis ∈ [3, 16]; height ∈ [3, 6].
_MIN_LONG = 3
_MAX_LONG = 16
_MIN_H = 3
_MAX_H = 6


def _orient_and_clamp(aabb: AABB) -> tuple[AABB, bool]:
    """Normalize the AABB to a 1-block-thick wall.

    Returns ``(slab_aabb, wall_along_x)``:
      * ``slab_aabb`` — a 1-thick AABB; thin axis collapsed to the midline.
      * ``wall_along_x`` — True if the wall runs along X (thin in Z),
        False if it runs along Z (thin in X).

    Sizing rules:
      * Choose long axis = longer of (W, D). Tie (W == D): use Z (wall
        along Z, thin in X) per spec default.
      * Long-axis length clamped to ``[3, 16]``.
      * Height clamped to ``[3, 6]``.
      * Lower corner of the slab is anchored at the original AABB's lower
        corner on the long & vertical axes. The thin axis is collapsed to
        the AABB's midline on that axis so the wall sits in the middle of
        whatever bounding box the caller supplied.
    """
    w = aabb.w
    d = aabb.d
    h = aabb.h

    # "wall along Z if W < D, along X if W > D"; tie → along Z.
    if w > d:
        wall_along_x = True
    else:
        wall_along_x = False  # covers w < d AND w == d

    if wall_along_x:
        long_len = max(_MIN_LONG, min(_MAX_LONG, w))
        height = max(_MIN_H, min(_MAX_H, h))
        # Thin axis is Z: collapse to midline of original AABB on z.
        z_mid = (aabb.z0 + aabb.z1 - 1) // 2
        return (AABB(
            aabb.x0, aabb.y0, z_mid,
            aabb.x0 + long_len, aabb.y0 + height, z_mid + 1,
        ), True)
    else:
        long_len = max(_MIN_LONG, min(_MAX_LONG, d))
        height = max(_MIN_H, min(_MAX_H, h))
        # Thin axis is X: collapse to midline of original AABB on x.
        x_mid = (aabb.x0 + aabb.x1 - 1) // 2
        return (AABB(
            x_mid, aabb.y0, aabb.z0,
            x_mid + 1, aabb.y0 + height, aabb.z0 + long_len,
        ), False)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a 1-block-thick interior partition wall with optional doorway
    and overhead window."""
    door_opening_at_center = bool(kwargs.get("door_opening_at_center", True))
    window_above_door = bool(kwargs.get("window_above_door", True))
    door_height = int(kwargs.get("door_height", 2))

    a, wall_along_x = _orient_and_clamp(aabb)
    ops: List[Op] = []

    # 1) Solid wall slab of @primary — the full 1-thick fill.
    ops.append(Fill(aabb=a, block="@primary"))

    # No foundation course (interior partition): leave y0 painted by the
    # Fill above, since the room/floor skill that pairs with the partition
    # is responsible for the floor underneath.

    # 2) Door opening — 1 wide × door_height tall, centered on the long axis.
    if door_opening_at_center:
        # Long-axis center index (matches the AABB.cx/cz convention).
        if wall_along_x:
            door_long = (a.x0 + a.x1 - 1) // 2
            x_d, z_d = door_long, a.z0
        else:
            door_long = (a.z0 + a.z1 - 1) // 2
            x_d, z_d = a.x0, door_long

        # Clamp door height to leave at least 1 block of header above
        # (so the wall remains visually a wall, not a frame missing top).
        dh = max(1, min(door_height, a.h - 1))
        for dy in range(dh):
            ops.append(PlaceBlock(x_d, a.y0 + dy, z_d, "minecraft:cave_air"))

        # 3) Window above door — 1 @glass pane, one block above the door head.
        if window_above_door:
            y_win = a.y0 + dh + 1  # one block of header between door & window
            # Only emit if it fits beneath the top course of the wall
            # (leave at least 1 block of header above the window too).
            if y_win < a.y1 - 1:
                ops.append(PlaceBlock(x_d, y_win, z_d, "@glass"))

    return ops
