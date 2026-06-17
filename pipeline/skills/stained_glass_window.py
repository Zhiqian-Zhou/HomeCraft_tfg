"""Skill: stained_glass_window.

A large decorative stained-glass window set into a wall section. The AABB
describes the wall slab the window occupies — typically a tall, narrow
3×6×1 panel (height > width). The skill builds:

    * @accent jambs (left + right vertical frames)
    * @accent sill across the bottom row
    * @accent arch top — flat @accent ridge with two @stairs at the
      inside corners so the lintel reads as an arched cap
    * Coloured stained-glass pane infill in the interior, with a per-style
      mosaic pattern:
        - medieval: rose-window vibe of red / blue / yellow alternating columns
        - modern:   minimalist white + light-blue geometric stripes
        - fantasy:  mystic purple / magenta / cyan with random scatter

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth. AABB is half-open.

The window is one cell thick (along z by default, along x when the wall
slab is oriented that way). Defensive sizing accepts panels from 2×3×1
(arrow-slit small) up to 5×8×1 (cathedral-tall); inputs outside that
range are clamped — never raised.

Kwargs
------
seed : int, default ``0``
    Seed for the fantasy "random scatter" pattern. The same seed and AABB
    always produce the same pane layout (deterministic).
"""
from __future__ import annotations

import random
from typing import List

from .base import AABB, Materials, Op, PlaceBlock


# Defensive envelope: 2x3x1 .. 5x8x1 (window is always 1-thick).
_MIN_W, _MIN_H, _MIN_D = 2, 3, 1
_MAX_W, _MAX_H, _MAX_D = 5, 8, 1


# 1.16.5 namespaced stained-glass panes used by the mosaics.
# Real block IDs — verified against the 1.16.5 paleta.
_RED       = "minecraft:red_stained_glass_pane"
_BLUE      = "minecraft:blue_stained_glass_pane"
_YELLOW    = "minecraft:yellow_stained_glass_pane"
_WHITE     = "minecraft:white_stained_glass_pane"
_LIGHTBLUE = "minecraft:light_blue_stained_glass_pane"
_PURPLE    = "minecraft:purple_stained_glass_pane"
_MAGENTA   = "minecraft:magenta_stained_glass_pane"
_CYAN      = "minecraft:cyan_stained_glass_pane"


def _clamp_extents(w: int, h: int, d: int) -> tuple[int, int, int]:
    """Clamp (w, h, d) into the [2..5, 3..8, 1] envelope."""
    return (
        max(_MIN_W, min(_MAX_W, w)),
        max(_MIN_H, min(_MAX_H, h)),
        max(_MIN_D, min(_MAX_D, d)),
    )


def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Build a large stained-glass window inside the given wall panel."""
    seed = int(kwargs.get("seed", 0))

    # Decide the "along" axis (window width) vs. the "thickness" axis BEFORE
    # clamping, so a panel like 1x6x3 is recognised as z-along (width 3,
    # thickness 1 along x) rather than being squashed by the clamp.
    along_x = True
    if aabb.w < aabb.d:
        along_x = False

    if along_x:
        # Window width runs along x, thickness along z.
        win_w, win_h, win_d = _clamp_extents(aabb.w, aabb.h, aabb.d)
        u0, u1 = aabb.x0, aabb.x0 + win_w
        v_plane = aabb.z0                  # single-thickness plane (z)
        y0, y1 = aabb.y0, aabb.y0 + win_h

        def at(u: int, y: int) -> tuple[int, int, int]:
            return (u, y, v_plane)
    else:
        # Window width runs along z, thickness along x. Swap w/d before
        # the clamp so width and thickness limits apply to the right axes.
        win_w, win_h, win_d = _clamp_extents(aabb.d, aabb.h, aabb.w)
        u0, u1 = aabb.z0, aabb.z0 + win_w
        v_plane = aabb.x0
        y0, y1 = aabb.y0, aabb.y0 + win_h

        def at(u: int, y: int) -> tuple[int, int, int]:
            return (v_plane, y, u)

    width = u1 - u0
    height = y1 - y0
    if width < _MIN_W or height < _MIN_H:
        return []

    ops: List[Op] = []

    # ── 1) Jambs: @accent on the two outer along-columns, full height. ──
    left_u  = u0
    right_u = u1 - 1
    for y in range(y0, y1):
        lx, ly, lz = at(left_u, y)
        ops.append(PlaceBlock(lx, ly, lz, "@accent"))
        rx, ry, rz = at(right_u, y)
        ops.append(PlaceBlock(rx, ry, rz, "@accent"))

    # ── 2) Sill: @accent across the bottom row, jamb-to-jamb. ──
    for u in range(u0, u1):
        sx, sy, sz = at(u, y0)
        ops.append(PlaceBlock(sx, sy, sz, "@accent"))

    # ── 3) Arch top: flat @accent ridge across the top row, with @stairs
    #     at the inside top corners so the lintel reads as an arched cap.
    #     When the window is only 2-wide there is no interior between the
    #     jambs — the top row is just the two jamb cells already placed,
    #     so we skip the stairs but still ensure the ridge is solid.
    y_top = y1 - 1
    for u in range(u0, u1):
        tx, ty, tz = at(u, y_top)
        ops.append(PlaceBlock(tx, ty, tz, "@accent"))

    # Corner stairs facing inward across the span (only when there's
    # interior space between the jambs, i.e. width >= 3).
    if width >= 3:
        # Facings depend on orientation: for an x-along window the left
        # stair faces east (toward +x) and the right faces west. For a
        # z-along window the left faces south and the right faces north.
        if along_x:
            left_face, right_face = "east", "west"
        else:
            left_face, right_face = "south", "north"
        # Resolve @stairs to the style's stairs block ourselves so we can
        # attach facing state — base._resolve only handles bare `@key`.
        stairs_block = materials.stairs
        inner_left = u0 + 1
        inner_right = u1 - 2
        lx, ly, lz = at(inner_left, y_top - 1)
        ops.append(PlaceBlock(lx, ly, lz,
                              f"{stairs_block}[facing={left_face}]"))
        if inner_right != inner_left:
            rx, ry, rz = at(inner_right, y_top - 1)
            ops.append(PlaceBlock(rx, ry, rz,
                                  f"{stairs_block}[facing={right_face}]"))

    # ── 4) Coloured stained-glass infill ──
    # Interior cells: u in (u0+1 .. u1-1), y in (y0+1 .. y1-2). Skip
    # corners hosting the arch stairs so the glass doesn't clobber them.
    # Note: the corner-stair cells live at y == y_top - 1 in columns
    # inner_left and inner_right; we always overwrite at compose-time via
    # "later wins" — to preserve the stair detail we explicitly skip them.
    pattern = _palette_for_style(style)
    if pattern:
        rng = random.Random(seed)
        for u in range(u0 + 1, u1 - 1):
            for y in range(y0 + 1, y_top):
                # Skip cells already taken by the inside-corner stairs.
                if width >= 3 and y == y_top - 1 and u in (u0 + 1, u1 - 2):
                    continue
                block = _pick_pane(style, pattern, u - u0, y - y0, rng)
                gx, gy, gz = at(u, y)
                ops.append(PlaceBlock(gx, gy, gz, block))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Style → palette + pattern picker
# ────────────────────────────────────────────────────────────────────────

def _palette_for_style(style: str) -> list[str]:
    """Return the pane palette for the given style, or [] if unsupported."""
    s = (style or "").lower()
    if s == "medieval":
        return [_RED, _BLUE, _YELLOW]
    if s == "modern":
        return [_WHITE, _LIGHTBLUE]
    if s == "fantasy":
        return [_PURPLE, _MAGENTA, _CYAN]
    # Unknown style: fall back to a medieval rose-window palette so the
    # window still reads as stained glass.
    return [_RED, _BLUE, _YELLOW]


def _pick_pane(style: str, palette: list[str], du: int, dy: int,
               rng: random.Random) -> str:
    """Pick the pane colour for interior cell (du, dy).

    `du` and `dy` are 1-based offsets from the jamb / sill corner. The
    rule depends on style:

        medieval: R / B / Y cycled along the (du + dy) diagonal so even a
                  1-column-wide interior still shows all three colours.
        modern:   alternating geometric stripes by (du + dy) parity.
        fantasy:  random scatter (deterministic per seed).
    """
    s = (style or "").lower()
    if s == "medieval":
        # Rose-window vibe: columns cycle R / B / Y, but each column also
        # rotates the start index by row so even a 1-interior-column panel
        # shows all three colours stacked vertically.
        return palette[(du - 1 + dy - 1) % len(palette)]
    if s == "modern":
        # 2-tone geometric checker on (du + dy) parity.
        return palette[(du + dy) % len(palette)]
    if s == "fantasy":
        return rng.choice(palette)
    # Default: column-wise cycling like medieval.
    return palette[(du - 1 + dy - 1) % len(palette)]
