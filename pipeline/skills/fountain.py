"""Skill: fountain — a central plaza fountain.

A monument piece that anchors an open plaza. The skill draws:

  * Outer basin: a hollow ring of `minecraft:cobblestone_wall` (or
    @secondary in non-medieval styles) at y0. The ring scales with the
    AABB: 5x5 on small footprints, 7x7 on larger ones, with the larger
    spans truncated to an odd side so the ring stays centred.
  * Inner basin: a single layer of `minecraft:water` filling the inside
    of the ring at y0 — the pool itself.
  * Central pedestal: a 1×1 column of @accent rising 2-3 blocks tall at
    the geometric centre, emerging out of the water.
  * Central spout: a `minecraft:water` block one block above the pedestal
    cap — the decorative "spraying" water at the top.
  * Four directional spouts: `minecraft:water` blocks placed next to the
    pedestal at y0+1 on each cardinal direction (N/S/E/W), simulating
    water running down the pedestal sides into the basin.
  * Corner lanterns: four 2-tall @fence posts capped with
    `minecraft:lantern` at the basin corners — light at night, and a
    "Pools of Light" effect over the water.

Defensive sizing: works for any AABB from 5×3×5 up to 9×5×9. Smaller
inputs are padded; larger inputs are clipped so the fountain stays at
a tractable scale and the inner basin always has an odd width.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock


# Defensive footprint clamps for this skill.
_MIN_W, _MIN_H, _MIN_D = 5, 3, 5
_MAX_W, _MAX_H, _MAX_D = 9, 5, 9


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [5..9, 3..5, 5..9] envelope.

    Origin is preserved; only the upper corner moves to satisfy bounds.
    The horizontal sides are also snapped to an odd number so the ring
    has a clear geometric centre and 4-way symmetry.
    """
    w = max(_MIN_W, min(_MAX_W, aabb.w))
    h = max(_MIN_H, min(_MAX_H, aabb.h))
    d = max(_MIN_D, min(_MAX_D, aabb.d))
    # Snap horizontal sides down to the nearest odd number so the
    # fountain has a perfectly centred 1×1 pedestal.
    if w % 2 == 0:
        w -= 1
    if d % 2 == 0:
        d -= 1
    # Re-clamp after the odd snap in case we fell below the floor.
    w = max(_MIN_W, w)
    d = max(_MIN_D, d)
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def _ring_side(aabb: AABB) -> int:
    """Choose the side of the basin ring: 5 for small, 7 for large.

    The ring is always odd-sided and centred inside the AABB. We use a
    7-wide ring when the AABB can comfortably fit it (>=7 on both
    horizontal axes); otherwise we fall back to 5.
    """
    if aabb.w >= 7 and aabb.d >= 7:
        return 7
    return 5


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a central plaza fountain centred inside the (clamped) AABB."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    y0 = a.y0
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2

    # 1) Ring geometry — odd side centred on (cx, cz).
    side = _ring_side(a)
    half = side // 2  # 5 → 2, 7 → 3
    rx0, rx1 = cx - half, cx + half + 1   # half-open span of the ring
    rz0, rz1 = cz - half, cz + half + 1

    # Clamp the ring to the AABB defensively (should already fit after
    # _clamp_aabb, but caller could have passed a tiny AABB that the
    # clamp grew via the (x0, x0+w) reseat — still safe).
    rx0 = max(a.x0, rx0); rx1 = min(a.x1, rx1)
    rz0 = max(a.z0, rz0); rz1 = min(a.z1, rz1)

    # 2) Outer basin ring — cobblestone_wall on each cell of the rim.
    #    Medieval style uses literal `minecraft:cobblestone_wall`; other
    #    styles fall back to @secondary so the rim still reads as masonry.
    rim_block = (
        "minecraft:cobblestone_wall"
        if style.lower() == "medieval"
        else "@secondary"
    )
    rim_cells: list[tuple[int, int]] = []
    for x in range(rx0, rx1):
        for z in range(rz0, rz1):
            on_edge = (x == rx0 or x == rx1 - 1
                       or z == rz0 or z == rz1 - 1)
            if on_edge:
                ops.append(PlaceBlock(x, y0, z, rim_block))
                rim_cells.append((x, z))

    # 3) Inner basin — single layer of water filling the inside of the ring.
    if rx1 - rx0 > 2 and rz1 - rz0 > 2:
        ops.append(Fill(
            AABB(rx0 + 1, y0, rz0 + 1, rx1 - 1, y0 + 1, rz1 - 1),
            "minecraft:water",
        ))

    # 4) Central pedestal — 1×1 column of @accent, 2 or 3 blocks tall.
    #    Height = 3 when the AABB allows (h >= 4), else 2. The pedestal
    #    starts at y0 (overwriting the water at its cell, later wins).
    pedestal_height = 3 if a.h >= 4 else 2
    pedestal_y0 = y0
    pedestal_y1 = y0 + pedestal_height  # half-open
    ops.append(Fill(
        AABB(cx, pedestal_y0, cz, cx + 1, pedestal_y1, cz + 1),
        "@accent",
    ))

    # 5) Central spout — water one block above the pedestal cap (the
    #    decorative "spraying" water).
    spout_y = pedestal_y1  # one above the topmost pedestal block
    if spout_y < a.y0 + a.h:
        ops.append(PlaceBlock(cx, spout_y, cz, "minecraft:water"))

    # 6) Four directional spouts — water blocks at y0+1 on each
    #    cardinal neighbour of the pedestal, simulating water running
    #    down the pedestal sides.
    side_spout_y = y0 + 1
    if side_spout_y < a.y0 + a.h:
        for (dx, dz) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            sx, sz = cx + dx, cz + dz
            # Only place if the neighbour is inside the inner basin
            # (i.e. not on the rim and inside the AABB).
            if not a.contains(sx, side_spout_y, sz):
                continue
            if (sx, sz) in rim_cells:
                continue
            ops.append(PlaceBlock(sx, side_spout_y, sz, "minecraft:water"))

    # 7) Corner lantern posts — 2-tall @fence with a lantern on top,
    #    at the four corners of the basin ring. Skipped if there is no
    #    vertical room (h < 3).
    if a.h >= 3:
        lantern_corners = [
            (rx0,     rz0),
            (rx1 - 1, rz0),
            (rx0,     rz1 - 1),
            (rx1 - 1, rz1 - 1),
        ]
        # Deduplicate in case the ring collapsed under heavy clamping.
        lantern_corners = list({(px, pz) for (px, pz) in lantern_corners})
        post_y0 = y0 + 1
        post_y1 = post_y0 + 2  # half-open: 2-tall fence
        lantern_y = post_y1
        for (px, pz) in lantern_corners:
            # Fence post stacks above the rim cell (later wins, so the
            # rim's wall block at y0 stays as the base of the post).
            ops.append(Fill(
                AABB(px, post_y0, pz, px + 1, post_y1, pz + 1),
                "@fence",
            ))
            if lantern_y < a.y0 + a.h:
                ops.append(PlaceBlock(px, lantern_y, pz, "minecraft:lantern"))

    return ops
