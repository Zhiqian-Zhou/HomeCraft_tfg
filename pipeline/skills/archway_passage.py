"""Archway passage skill — corridor with a repeating arch motif overhead.

An archway passage is a hybrid between a `hallway` and a row of `arch`es:
the floor and the two lateral walls form a corridor along the longer
horizontal axis, but instead of a flat ceiling there is a repeating
arch motif. Every 3 blocks along the passage's length axis, a complete
arch is built spanning the corridor's width (two @primary jambs, two
@stairs corner blocks facing inward to fake the curve, a flat top
course of @primary, and an @accent keystone at the centre). Between
arches the span overhead is left fully open so daylight or a higher
storey can spill in — exactly the "open span between arches admits
light" rule referenced by Alexander's *Pools of Light* pattern.

Layout summary
--------------
    1. Floor plane of `@floor` at y0 spanning the whole footprint.
    2. Two lateral walls of `@primary` along the longer (length) axis,
       full height from y0+1 up to y1 exclusive. The short ends stay
       open so the passage connects to its neighbours, like `hallway`.
    3. Arch ribs every 3 blocks along the length axis. Each rib is a
       cross-section of `arch.py` — jambs are the lateral walls (already
       in place), the two top corners host inward-facing `@stairs`, the
       flat top course is `@primary` jamb-to-jamb, and a central
       `@accent` keystone closes the apex.
    4. Lights: a `@light` block sits on top of every keystone (one row
       above the arch apex when there is headroom; otherwise on the
       keystone itself), illuminating the bay below.
    5. Carpet runner(s): 1-2 strips of `@carpet` on the floor — one
       centred runner for narrow passages, two parallel runners when
       the interior is wide enough.

Defensive on AABB sizes from 3x4x6 (minimum width × height × length)
up to 5x5x16 (max). Smaller inputs collapse gracefully (the renderer
just gets fewer arches). The longer of `aabb.w`/`aabb.d` is treated as
the corridor length; the shorter as its width.

Coordinate convention (matches `base.py`):
    x = width, y = height (up), z = depth. AABB is half-open.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Spacing between consecutive arch ribs along the length axis.
_ARCH_SPACING = 3

# Defensive envelope (per spec): 3x4x6 .. 5x5x16.
_MIN_W, _MIN_H, _MIN_D = 3, 4, 6
_MAX_W, _MAX_H, _MAX_D = 5, 5, 16


# Inward stair facings (mirror arch.py's convention).
_INWARD_LEFT_X  = "east"   # wall along x, left jamb faces toward +x
_INWARD_RIGHT_X = "west"
_INWARD_LEFT_Z  = "south"  # wall along z, left jamb faces toward +z
_INWARD_RIGHT_Z = "north"


# ────────────────────────────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────────────────────────────

def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Return AST ops that materialize an archway passage inside `aabb`."""
    a = _clamp(aabb)
    # If the clamp produced something below the minimum useful envelope,
    # bail out rather than emit a broken structure. The check is
    # axis-aware: the LONGER horizontal axis must clear _MIN_D and the
    # shorter one must clear _MIN_W.
    long_d = max(a.w, a.d)
    short_d = min(a.w, a.d)
    if short_d < _MIN_W or a.h < _MIN_H or long_d < _MIN_D:
        return []

    ops: List[Op] = []
    ops.extend(_floor(a))
    ops.extend(_lateral_walls(a))
    arch_positions = _arch_positions(a)
    ops.extend(_arches(a, arch_positions, stairs_block=materials.stairs))
    ops.extend(_keystone_lights(a, arch_positions))
    ops.extend(_carpet_runners(a))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Axis helpers
# ────────────────────────────────────────────────────────────────────────

def _length_axis(aabb: AABB) -> str:
    """Return 'x' if the passage runs along x, else 'z' (ties → z)."""
    return "x" if aabb.w > aabb.d else "z"


def _clamp(aabb: AABB) -> AABB:
    """Clamp `aabb` into [3x4x6 .. 5x5x16] along (width, height, length).

    The clamp respects the corridor's length axis: the LONGER horizontal
    axis is clamped to [_MIN_D, _MAX_D], the shorter horizontal axis to
    [_MIN_W, _MAX_W], and height to [_MIN_H, _MAX_H]. Origin is
    preserved; only the +x/+y/+z corner moves.
    """
    h = max(_MIN_H, min(_MAX_H, aabb.h))
    long_axis_is_x = aabb.w >= aabb.d
    if long_axis_is_x:
        length = max(_MIN_D, min(_MAX_D, aabb.w))   # along x
        width = max(_MIN_W, min(_MAX_W, aabb.d))    # along z
        return AABB(aabb.x0, aabb.y0, aabb.z0,
                    aabb.x0 + length, aabb.y0 + h, aabb.z0 + width)
    else:
        length = max(_MIN_D, min(_MAX_D, aabb.d))   # along z
        width = max(_MIN_W, min(_MAX_W, aabb.w))    # along x
        return AABB(aabb.x0, aabb.y0, aabb.z0,
                    aabb.x0 + width, aabb.y0 + h, aabb.z0 + length)


# ────────────────────────────────────────────────────────────────────────
#  Layout helpers
# ────────────────────────────────────────────────────────────────────────

def _floor(a: AABB) -> List[Op]:
    """Solid floor plane on y == a.y0 using @floor."""
    return [Rect(a, "@floor", axis="y", level=a.y0)]


def _lateral_walls(a: AABB) -> List[Op]:
    """Two lateral walls of @primary along the LONGER axis, full height.

    Short ends are intentionally left open so the passage connects to
    whatever sits at its ends (mirrors `hallway.py`). Walls rise from
    y0+1 up to y1 exclusive — full remaining height, no row reserved
    for a ceiling slab because this skill has no flat ceiling.
    """
    y0w = a.y0 + 1
    y1w = a.y1
    ops: List[Op] = []
    if _length_axis(a) == "x":
        # Passage runs along x → walls at z = z0 and z = z1-1.
        ops.append(Fill(AABB(a.x0, y0w, a.z0,
                             a.x1, y1w, a.z0 + 1), "@primary"))
        ops.append(Fill(AABB(a.x0, y0w, a.z1 - 1,
                             a.x1, y1w, a.z1), "@primary"))
    else:
        # Passage runs along z → walls at x = x0 and x = x1-1.
        ops.append(Fill(AABB(a.x0, y0w, a.z0,
                             a.x0 + 1, y1w, a.z1), "@primary"))
        ops.append(Fill(AABB(a.x1 - 1, y0w, a.z0,
                             a.x1, y1w, a.z1), "@primary"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Arch ribs
# ────────────────────────────────────────────────────────────────────────

def _arch_positions(a: AABB) -> List[int]:
    """Return the integer coords (along the length axis) where arch ribs sit.

    Arches are spaced every `_ARCH_SPACING` blocks. Skip the very first
    and last cells of the length axis so the open short ends remain
    unobstructed by an arch rib flush against the end. We GUARANTEE at
    least 3 arches when the corridor is long enough (>= 6 blocks).
    """
    long_axis = _length_axis(a)
    if long_axis == "x":
        lo, hi = a.x0 + 1, a.x1 - 1   # exclusive of the end cells
    else:
        lo, hi = a.z0 + 1, a.z1 - 1

    if hi - lo < 1:
        return []

    positions = list(range(lo, hi, _ARCH_SPACING))
    # Guarantee >= 3 arches whenever the corridor is long enough (>= 6).
    # For tiny corridors (length 6) the natural spacing yields exactly
    # 2 positions; insert a midpoint so we hit the required_furniture
    # contract of "3+ arches".
    length = (a.x1 - a.x0) if long_axis == "x" else (a.z1 - a.z0)
    if length >= 6 and len(positions) < 3:
        mid = (lo + hi - 1) // 2
        if mid not in positions and lo <= mid < hi:
            positions.append(mid)
            positions.sort()
    return positions


def _arches(a: AABB, positions: List[int], *, stairs_block: str) -> List[Op]:
    """Emit one arch rib at every position along the length axis.

    Each rib spans the corridor's full WIDTH on a single cell of the
    length axis. The rib has:
        - jambs implicit in the lateral walls already placed,
        - inward-facing @stairs at the two top corners,
        - a flat top course of @primary jamb-to-jamb,
        - an @accent keystone at the centre.

    The rib lives on the top row (y = y1 - 1). Lateral walls already
    cover the jamb columns at that row; we overpaint with @primary for
    safety so the rib reads as a continuous lintel band even if a
    future caller changes the wall material. Stairs carry an explicit
    `[facing=…]` blockstate so we resolve `@stairs` to the concrete
    material id up front (the `_resolve` helper can't parse blockstates
    embedded in placeholders).
    """
    ops: List[Op] = []
    long_axis = _length_axis(a)
    y_top = a.y1 - 1
    y_curve = y_top  # stairs sit on the SAME top row as the lintel

    if long_axis == "x":
        # Rib runs perpendicular to x: along z from z0 to z1-1.
        z_left  = a.z0          # left jamb column
        z_right = a.z1 - 1      # right jamb column
        inner_left  = a.z0 + 1
        inner_right = a.z1 - 2
        centre_z = (a.z0 + a.z1 - 1) // 2

        for x in positions:
            if not (a.x0 <= x < a.x1):
                continue
            # 1) Top course of @primary spanning jamb-to-jamb.
            for z in range(z_left, z_right + 1):
                ops.append(PlaceBlock(x, y_top, z, "@primary"))
            # 2) Corner stairs facing inward across the span. Skip any
            # stair that would land on the apex centre — the keystone
            # has priority there.
            if inner_left <= inner_right:
                if inner_left != centre_z:
                    ops.append(PlaceBlock(x, y_curve, inner_left,
                                          f"{stairs_block}[facing={_INWARD_LEFT_Z}]"))
                if inner_right != inner_left and inner_right != centre_z:
                    ops.append(PlaceBlock(x, y_curve, inner_right,
                                          f"{stairs_block}[facing={_INWARD_RIGHT_Z}]"))
            # 3) Keystone @accent at the apex centre (always last so it
            # wins over the top-course @primary; stairs are placed at
            # different cells so they survive composer dedupe).
            ops.append(PlaceBlock(x, y_top, centre_z, "@accent"))
    else:
        # Rib runs perpendicular to z: along x from x0 to x1-1.
        x_left  = a.x0
        x_right = a.x1 - 1
        inner_left  = a.x0 + 1
        inner_right = a.x1 - 2
        centre_x = (a.x0 + a.x1 - 1) // 2

        for z in positions:
            if not (a.z0 <= z < a.z1):
                continue
            for x in range(x_left, x_right + 1):
                ops.append(PlaceBlock(x, y_top, z, "@primary"))
            if inner_left <= inner_right:
                if inner_left != centre_x:
                    ops.append(PlaceBlock(inner_left, y_curve, z,
                                          f"{stairs_block}[facing={_INWARD_LEFT_X}]"))
                if inner_right != inner_left and inner_right != centre_x:
                    ops.append(PlaceBlock(inner_right, y_curve, z,
                                          f"{stairs_block}[facing={_INWARD_RIGHT_X}]"))
            ops.append(PlaceBlock(centre_x, y_top, z, "@accent"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Lights on the keystones
# ────────────────────────────────────────────────────────────────────────

def _keystone_lights(a: AABB, positions: List[int]) -> List[Op]:
    """Place a @light block on (or directly under) each keystone.

    Default: a @light sits on the cell BELOW the keystone (one row
    inside the passage), so it actually illuminates the bay. If the
    passage is too low to fit a separate light row, we drop the light
    on the keystone cell itself — composer is later-wins, so this
    overrides the keystone block at the apex of squat passages.
    """
    ops: List[Op] = []
    long_axis = _length_axis(a)
    y_top = a.y1 - 1
    # Hang the light one row below the keystone when there's headroom
    # (i.e. the passage is at least 4 tall — the spec's minimum).
    y_light = y_top - 1 if a.h >= 4 else y_top

    if long_axis == "x":
        centre_z = (a.z0 + a.z1 - 1) // 2
        for x in positions:
            if a.x0 <= x < a.x1 and a.z0 <= centre_z < a.z1:
                ops.append(PlaceBlock(x, y_light, centre_z, "@light"))
    else:
        centre_x = (a.x0 + a.x1 - 1) // 2
        for z in positions:
            if a.z0 <= z < a.z1 and a.x0 <= centre_x < a.x1:
                ops.append(PlaceBlock(centre_x, y_light, z, "@light"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Carpet runners on the floor
# ────────────────────────────────────────────────────────────────────────

def _carpet_runners(a: AABB) -> List[Op]:
    """1-2 carpet runners of @carpet sitting on top of the floor.

    A narrow passage (interior width <= 2) gets a single centred
    runner. Wider passages get two parallel runners along the interior
    edges so the centre stays clear under the arches/keystones.
    """
    ops: List[Op] = []
    long_axis = _length_axis(a)
    y_c = a.y0 + 1  # carpet sits on top of the floor block

    if long_axis == "x":
        run_lo = a.x0 + 1
        run_hi = a.x1 - 1  # exclusive
        if run_hi <= run_lo:
            return ops
        in_lo = a.z0 + 1
        in_hi = a.z1 - 1
        interior_w = in_hi - in_lo
        if interior_w <= 0:
            return ops
        if interior_w <= 2:
            lanes = [(in_lo + in_hi - 1) // 2]
        else:
            lanes = [in_lo, in_hi - 1]
        for z in lanes:
            for x in range(run_lo, run_hi):
                ops.append(PlaceBlock(x, y_c, z, "@carpet"))
    else:
        run_lo = a.z0 + 1
        run_hi = a.z1 - 1
        if run_hi <= run_lo:
            return ops
        in_lo = a.x0 + 1
        in_hi = a.x1 - 1
        interior_w = in_hi - in_lo
        if interior_w <= 0:
            return ops
        if interior_w <= 2:
            lanes = [(in_lo + in_hi - 1) // 2]
        else:
            lanes = [in_lo, in_hi - 1]
        for x in lanes:
            for z in range(run_lo, run_hi):
                ops.append(PlaceBlock(x, y_c, z, "@carpet"))

    return ops
