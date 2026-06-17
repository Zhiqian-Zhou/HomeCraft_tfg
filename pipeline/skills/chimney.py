"""Skill: chimney — exterior chimney stack + interior fireplace.

The AABB defines a tall, narrow vertical slot (typically 2×H×2 or 3×H×3)
that runs from the interior floor of a building up through the roof. The
skill emits two coupled subsystems:

  * Interior fireplace at y0..y0+1: a 3-wide × 2-tall hearth opening with
    a @secondary stone surround on three sides, a `minecraft:netherrack`
    floor (so the fire is permanent), and `minecraft:fire` (or
    `minecraft:campfire` if the AABB is too cramped for an open flame
    cell) burning on top. An optional `minecraft:lantern` is placed
    adjacent to the hearth for ambient light.

  * Exterior stack from y0+2 up to y_top-1: a hollow 2×2 (or full-cross
    section for thicker AABBs) shaft of @secondary stone wrapped around
    a clear flue. The flue is left as air so smoke can vent. A small
    @slab cap is laid on the top course with a 1-block gap above the
    flue so smoke escapes.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Defensive sizing: clamped to 2×4×2 .. 4×16×4. The skill picks a sensible
hearth orientation and falls back to a campfire when the slot is too
narrow to host a 3-wide opening.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, FillHollow, Materials, Op, PlaceBlock


# Defensive bounds per spec.
_MIN = (2, 4, 2)
_MAX = (4, 16, 4)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [2..4, 4..16, 2..4] envelope."""
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a fireplace + chimney stack inside `aabb`.

    Kwargs:
        flame ('fire' | 'campfire'): force the hearth flame type. Default
            picks `fire` for boxes ≥ 3 wide and `campfire` otherwise.
    """
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # Hearth flame choice: fire needs a 3-wide opening to look right;
    # otherwise we drop in a campfire (single block, decorative smoke).
    style_l = style.lower()
    flame_kw = kwargs.get("flame")
    if flame_kw in ("fire", "campfire"):
        flame = flame_kw
    else:
        flame = "fire" if min(a.w, a.d) >= 3 else "campfire"
    # Fantasy variant uses soul fire (cooler-tinted flame) when possible.
    if style_l == "fantasy" and flame == "fire":
        flame_block = "minecraft:soul_fire"
    elif flame == "campfire":
        flame_block = "minecraft:soul_campfire" if style_l == "fantasy" else "minecraft:campfire"
    else:
        flame_block = "minecraft:fire"

    y_hearth0 = a.y0       # netherrack pad / hearth floor row
    y_hearth1 = a.y0 + 1   # fire / opening row
    y_top = a.y1 - 1       # top course of the AABB (cap level)

    # ───────────────────────────────────────────────────────────────
    # 1) Interior fireplace shell (the bottom two rows of the AABB).
    #    Build it as a hollow shell of @secondary so we get a full
    #    stone surround on 3 sides + floor + ceiling. Then carve the
    #    opening on the "front" face (the +z face is conventionally
    #    interior-facing).
    # ───────────────────────────────────────────────────────────────
    hearth_box = AABB(a.x0, y_hearth0, a.z0, a.x1, y_hearth1 + 1, a.z1)
    ops.append(FillHollow(aabb=hearth_box, wall="@secondary"))

    # 2) Netherrack pad on the hearth floor (overrides the @secondary floor
    #    inside the hearth box, leaving a 1-cell border on each side as the
    #    stone surround). For a 3-wide box the interior pad is 1×1; for a
    #    2-wide box we still want a netherrack patch, so we paint the full
    #    floor with netherrack on the inner cells.
    pad_x0 = a.x0 + 1 if a.w >= 3 else a.x0
    pad_x1 = a.x1 - 1 if a.w >= 3 else a.x1
    pad_z0 = a.z0 + 1 if a.d >= 3 else a.z0
    pad_z1 = a.z1 - 1 if a.d >= 3 else a.z1
    if pad_x1 > pad_x0 and pad_z1 > pad_z0:
        ops.append(Fill(
            AABB(pad_x0, y_hearth0, pad_z0, pad_x1, y_hearth0 + 1, pad_z1),
            "minecraft:netherrack",
        ))
        # 3) Flame on top of the netherrack pad.
        for x in range(pad_x0, pad_x1):
            for z in range(pad_z0, pad_z1):
                ops.append(PlaceBlock(x, y_hearth1, z, flame_block))

    # 4) Carve the hearth opening on the +z face so the interior of the room
    #    can see the fire. We drop the front-face wall cells to air at the
    #    flame row (y_hearth1) only; the floor row stays as netherrack/stone.
    front_z = a.z1 - 1
    for x in range(a.x0, a.x1):
        # Skip the corner columns so the surround stays continuous (only
        # when the box is wide enough to have non-corner cells).
        if a.w >= 3 and (x == a.x0 or x == a.x1 - 1):
            continue
        ops.append(PlaceBlock(x, y_hearth1, front_z, "minecraft:cave_air"))

    # 5) Lantern adjacent to the hearth (just outside the +z face at the
    #    flame row, if we have room above the hearth box). Falls back to a
    #    torch placement on the side wall when there's no exterior cell.
    lantern_x = a.x0 + a.w // 2
    lantern_y = y_hearth1
    lantern_z = front_z  # sits on the carved opening cell
    # Place lantern hanging from the ceiling cell just above (y_hearth1 + 1
    # would be the start of the stack); to keep it visible we drop a
    # lantern at the opening cell. Carved-air placement happens later in
    # the list above, so we have to re-add the lantern after — composer
    # is later-wins, so order in this ops list matters.
    ops.append(PlaceBlock(lantern_x, lantern_y, lantern_z, "minecraft:lantern"))

    # ───────────────────────────────────────────────────────────────
    # 6) Exterior stack: hollow shell of @secondary from y_hearth1+1 up
    #    to y_top-1. The interior is left as air (the flue). We use
    #    FillHollow with no fill and no special floor/ceiling — but we
    #    must also override the hearth ceiling (already painted by the
    #    hearth_box FillHollow as @secondary) so the flue is open.
    # ───────────────────────────────────────────────────────────────
    stack_y0 = y_hearth1 + 1
    stack_y1 = y_top  # half-open: shell spans [stack_y0, stack_y1)
    if stack_y1 > stack_y0:
        stack_box = AABB(a.x0, stack_y0, a.z0, a.x1, stack_y1, a.z1)
        ops.append(FillHollow(aabb=stack_box, wall="@secondary"))
        # Clear the flue interior so smoke vents (in case FillHollow's
        # implicit floor at stack_y0 picked up the @secondary).
        if a.w >= 3 and a.d >= 3:
            flue_box = AABB(a.x0 + 1, stack_y0, a.z0 + 1,
                            a.x1 - 1, stack_y1, a.z1 - 1)
            ops.append(Fill(flue_box, "minecraft:cave_air"))
        else:
            # 2×2 stack — the FillHollow has no interior, but it does have
            # floor/ceiling planes. Clear the first row above the hearth
            # so the flue connects to the fireplace below.
            for x in range(a.x0, a.x1):
                for z in range(a.z0, a.z1):
                    # Only clear the interior cells (away from the corners)
                    # of a 2×2 stack — every cell IS a corner, so we instead
                    # punch a 1×1 hole in the center of the floor plane to
                    # vent. For a 2×2 box the "center" is ambiguous; pick
                    # the cell closest to the hearth pad.
                    if (x, z) == (a.x0, a.z0):
                        ops.append(PlaceBlock(x, stack_y0, z, "minecraft:cave_air"))

    # ───────────────────────────────────────────────────────────────
    # 7) Cap: @slab course at y_top with a 1-block gap centered on the
    #    flue so smoke can escape. Slab placement is delegated to the
    #    material resolver.
    # ───────────────────────────────────────────────────────────────
    if y_top >= stack_y0:
        # Center cell(s) of the flue — leave as air for venting.
        vent_x = a.x0 + a.w // 2
        vent_z = a.z0 + a.d // 2
        for x in range(a.x0, a.x1):
            for z in range(a.z0, a.z1):
                if (x, z) == (vent_x, vent_z):
                    # Vent gap — drop to air explicitly so the slab below
                    # doesn't cover it.
                    ops.append(PlaceBlock(x, y_top, z, "minecraft:cave_air"))
                else:
                    ops.append(PlaceBlock(x, y_top, z, "@slab"))

    return ops
