"""Attic skill — the high triangular space under the roof.

The attic sits between a building's top floor ceiling and the ridge of a
gabled roof. Its cross-section is a triangle: wide at the floor (the
ceiling of the room below) and narrowing to a 1-block ridge at the top.
The space is partially obstructed by the slope, which is exactly why
attics are used for storage (chests along the eaves where headroom is
already too low to stand) and the occasional dormer window for light.

Geometry (ridge runs along the longer horizontal axis — same default as
`gabled_roof.py`):

    y = y0          → solid @primary floor (the ceiling-of-the-floor-below)
    y = y0 + 1      → full-footprint hollow shell (@primary walls)
    y = y0 + 2      → shrink AABB by 1 on the short axis each side
    ...             → each level shrinks until it becomes a 1-wide ridge
    y = y0 + peak   → 1-block ridge of @primary (or @glass for a skylight)

Furniture placed defensively from 5×3×5 (peak h = 3) up to 10×5×10
(peak h = 5):
    - 2-4 `minecraft:chest` along the eaves (low headroom, but right
      against the slope = perfect storage).
    - 1 `minecraft:bookshelf` plus stacked @primary as "boxes" along
      the floor.
    - 1+ `minecraft:lantern` hanging from the ridge (under the apex).
    - 1 dormer window: a small gable cut into one of the long pitched
      walls, glazed with @glass.

The skill is defensive: it computes its own peak height from
min(W, D) // 2 (mirroring `gabled_roof.py`), and clamps every furniture
placement to a row that actually has headroom. The AABB's `h` is used
only as an upper bound — if the caller gives an oversized box, we cap
the peak at h - 1 so the ridge stays inside the AABB.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock, Rect, Line


# ────────────────────────────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────────────────────────────


def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Return AST ops that materialize a furnished attic inside `aabb`.

    Kwargs:
        ridge_axis ('x' | 'z'): direction the ridge runs along. Default
            is the longer horizontal side, ties break to 'x'.
        skylight (bool): if True, the 1-wide ridge course is built from
            @glass instead of @primary (turning the apex into a skylight).
            Default False.
    """
    s = (style or "medieval").lower()

    # Defensive on degenerate footprints.
    if aabb.w < 3 or aabb.d < 3 or aabb.h < 2:
        return []

    # Ridge axis selection mirrors gabled_roof.py.
    ridge_axis = kwargs.get("ridge_axis")
    if ridge_axis not in ("x", "z"):
        ridge_axis = "x" if aabb.w >= aabb.d else "z"

    skylight = bool(kwargs.get("skylight", False))

    # Peak: how many layers of taper. From the short axis (perpendicular
    # to the ridge) we lose 2 blocks per step (one on each side). We use
    # short // 2 to mirror gabled_roof.py: for odd short axis the ridge
    # is naturally 1-wide; for even short the top course is 2-wide and
    # treated as a "flat ridge" (solid course of @primary, or @glass when
    # skylight=True).
    short = aabb.d if ridge_axis == "x" else aabb.w
    peak = short // 2
    # Cap by the AABB height (the ridge layer is y0 + peak).
    peak = min(peak, aabb.h - 1)
    if peak < 1:
        # Footprint too narrow to slope — just emit floor + flat cap.
        return _flat_fallback(aabb)

    ops: List[Op] = []
    ops.extend(_floor(aabb))
    ops.extend(_sloped_walls(aabb, ridge_axis, peak, skylight))
    # Order matters under composer "later wins":
    #  - boxes + bookshelf go first so chests/dormer can override them.
    #  - chests next: they sit on the wall ring (replacing wall blocks),
    #    leaving the interior aisle clear for bookshelf/lantern.
    #  - dormer AFTER chests: the @glass dormer punches through whichever
    #    wall blocks (or chests) happen to share its cell — the architectural
    #    feature wins over storage.
    #  - lanterns last: hang from the ridge, clamped to free cells.
    ops.extend(_boxes_and_bookshelf(aabb, ridge_axis))
    ops.extend(_chests_along_eaves(aabb, ridge_axis))
    ops.extend(_dormer(aabb, ridge_axis, peak))
    ops.extend(_lanterns(aabb, ridge_axis, peak))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Floor + sloped shell
# ────────────────────────────────────────────────────────────────────────


def _floor(aabb: AABB) -> List[Op]:
    """Solid @primary floor on y == y0 (= ceiling of the room below)."""
    return [Rect(
        AABB(aabb.x0, aabb.y0, aabb.z0, aabb.x1, aabb.y0 + 1, aabb.z1),
        "@primary", axis="y", level=aabb.y0,
    )]


def _sloped_walls(aabb: AABB, ridge_axis: str, peak: int,
                  skylight: bool) -> List[Op]:
    """Hollow rings stacked with shrinking AABBs on the short axis.

    Each layer above the floor emits only the PERIMETER of a shrinking
    AABB (4 Lines per layer), so the interior stays as air — that is
    the inhabitable attic volume. The short-axis dimension is reduced
    by 2*layer (one block off each side) per level. The top is either
    a 1-block ridge of @primary, or @glass when `skylight=True`.
    """
    ops: List[Op] = []

    for layer in range(1, peak + 1):
        y = aabb.y0 + layer
        if ridge_axis == "x":
            z_lo = aabb.z0 + layer
            z_hi = aabb.z1 - 1 - layer
            x_lo = aabb.x0
            x_hi = aabb.x1 - 1
            if z_lo > z_hi:
                break
            short_size = z_hi - z_lo + 1
        else:
            x_lo = aabb.x0 + layer
            x_hi = aabb.x1 - 1 - layer
            z_lo = aabb.z0
            z_hi = aabb.z1 - 1
            if x_lo > x_hi:
                break
            short_size = x_hi - x_lo + 1

        # Top course of the slope: either 1 wide (odd short) or 2 wide
        # (even short). Both are treated as a solid ridge course.
        is_ridge = short_size <= 2
        if is_ridge:
            block = "@glass" if skylight else "@primary"
            if ridge_axis == "x":
                # Fill a 1-or-2-wide strip along x.
                for z in range(z_lo, z_hi + 1):
                    ops.append(Line(x_lo, y, z, x_hi, y, z, block))
            else:
                for x in range(x_lo, x_hi + 1):
                    ops.append(Line(x, y, z_lo, x, y, z_hi, block))
            continue

        # Hollow ring: 4 perimeter lines around this layer's shrunk AABB.
        ops.append(Line(x_lo, y, z_lo, x_hi, y, z_lo, "@primary"))   # long edge 1
        ops.append(Line(x_lo, y, z_hi, x_hi, y, z_hi, "@primary"))   # long edge 2
        ops.append(Line(x_lo, y, z_lo, x_lo, y, z_hi, "@primary"))   # short edge 1
        ops.append(Line(x_hi, y, z_lo, x_hi, y, z_hi, "@primary"))   # short edge 2

    return ops


def _flat_fallback(aabb: AABB) -> List[Op]:
    """Degenerate fallback: just floor + a flat cap of @primary."""
    ops: List[Op] = []
    ops.extend(_floor(aabb))
    y = aabb.y0 + 1
    if y < aabb.y1:
        ops.append(Rect(
            AABB(aabb.x0, y, aabb.z0, aabb.x1, y + 1, aabb.z1),
            "@primary", axis="y", level=y,
        ))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Dormer window — a small gable cut into one pitched wall
# ────────────────────────────────────────────────────────────────────────


def _dormer(aabb: AABB, ridge_axis: str, peak: int) -> List[Op]:
    """Cut a small dormer (1-2 block glass cluster) into one pitched wall.

    The dormer is centred along the long axis. For tall attics (peak >= 3)
    it sits roughly halfway up the slope; for shallow attics (peak == 2)
    it sits in the lowest sloped layer above the eaves so it always lands
    above the chests rather than colliding with them. Returned ops are
    emitted AFTER the wall rings, so the @glass "later-wins" over the
    @primary perimeter.
    """
    ops: List[Op] = []
    if peak < 1:
        return ops

    # Choose the dormer layer. For peak == 1 we have no slope to cut into
    # (the only layer above the floor IS the ridge), so we skip.
    if peak == 1:
        return ops

    # peak >= 2 → use the lowest sloped layer (layer 1) for shallow attics
    # so the dormer always sits above the eave chests but in the same wall.
    # For tall attics (peak >= 4) use the mid-layer for a real dormer feel.
    layer = 1 if peak <= 3 else peak // 2
    y = aabb.y0 + layer

    if ridge_axis == "x":
        # +z pitched edge at this layer (the south long wall).
        z = aabb.z1 - 1 - layer
        x_mid = (aabb.x0 + aabb.x1 - 1) // 2
        ops.append(PlaceBlock(x_mid, y, z, "@glass"))
        if aabb.w >= 8:
            ops.append(PlaceBlock(x_mid + 1, y, z, "@glass"))
        # A 1-tall row of @glass directly above (small upper light) when
        # there's another sloped layer to cut into.
        if peak - layer >= 2:
            z_up = aabb.z1 - 1 - (layer + 1)
            if z_up > aabb.z0 + (layer + 1):
                ops.append(PlaceBlock(x_mid, y + 1, z_up, "@glass"))
    else:
        x = aabb.x1 - 1 - layer
        z_mid = (aabb.z0 + aabb.z1 - 1) // 2
        ops.append(PlaceBlock(x, y, z_mid, "@glass"))
        if aabb.d >= 8:
            ops.append(PlaceBlock(x, y, z_mid + 1, "@glass"))
        if peak - layer >= 2:
            x_up = aabb.x1 - 1 - (layer + 1)
            if x_up > aabb.x0 + (layer + 1):
                ops.append(PlaceBlock(x_up, y + 1, z_mid, "@glass"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Chests along the eaves
# ────────────────────────────────────────────────────────────────────────


def _chests_along_eaves(aabb: AABB, ridge_axis: str) -> List[Op]:
    """Place 2-4 chests along the low-headroom edge (right against the
    sloped wall on the floor row).

    The "eave" is the first interior row next to the long pitched walls
    on y = y0 + 1. We place chests on both sides (when there's room),
    spaced out along the long axis.
    """
    ops: List[Op] = []
    y = aabb.y0 + 1   # one row above the floor plane

    # Chests sit ON the layer-1 wall ring (where the slope literally meets
    # the floor — the "eave"). Architecturally this is a chest tucked into
    # the lowest part of the slope, and it leaves the interior aisle clear
    # for the bookshelf, boxes, and hanging lantern.
    # Layer-1 long-wall position:
    #   ridge_axis == 'x' → eave at z = z0+1 and z = z1-2
    #   ridge_axis == 'z' → eave at x = x0+1 and x = x1-2
    if ridge_axis == "x":
        long_lo, long_hi = aabb.x0 + 1, aabb.x1 - 2     # interior x range
        z_n = aabb.z0 + 1                                # north eave (on the wall)
        z_s = aabb.z1 - 2                                # south eave (on the wall)
        if long_lo > long_hi or z_n >= z_s:
            return ops
        n_chests_n = 2 if aabb.w < 8 else 3
        n_chests_s = 1 if aabb.w < 8 else 2
        for x in _spaced_positions(long_lo, long_hi, n_chests_n):
            ops.append(PlaceBlock(x, y, z_n, "minecraft:chest[facing=south]"))
        for x in _spaced_positions(long_lo, long_hi, n_chests_s):
            ops.append(PlaceBlock(x, y, z_s, "minecraft:chest[facing=north]"))
    else:
        long_lo, long_hi = aabb.z0 + 1, aabb.z1 - 2
        x_w = aabb.x0 + 1
        x_e = aabb.x1 - 2
        if long_lo > long_hi or x_w >= x_e:
            return ops
        n_chests_w = 2 if aabb.d < 8 else 3
        n_chests_e = 1 if aabb.d < 8 else 2
        for z in _spaced_positions(long_lo, long_hi, n_chests_w):
            ops.append(PlaceBlock(x_w, y, z, "minecraft:chest[facing=east]"))
        for z in _spaced_positions(long_lo, long_hi, n_chests_e):
            ops.append(PlaceBlock(x_e, y, z, "minecraft:chest[facing=west]"))

    return ops


def _spaced_positions(lo: int, hi: int, n: int) -> List[int]:
    """Return up to `n` integer positions spread evenly in [lo, hi]."""
    if n <= 0 or lo > hi:
        return []
    if n == 1:
        return [(lo + hi) // 2]
    span = hi - lo
    return [lo + round(i * span / (n - 1)) for i in range(n)]


# ────────────────────────────────────────────────────────────────────────
#  Boxes + bookshelf
# ────────────────────────────────────────────────────────────────────────


def _boxes_and_bookshelf(aabb: AABB, ridge_axis: str) -> List[Op]:
    """Stack a couple of @primary "boxes" plus a single bookshelf in the
    centre of the attic floor (under the highest headroom).

    Boxes are just stacked @primary blocks (1×1×1 or 1×2×1) — they
    represent crates of stored goods. The bookshelf sits next to them
    to satisfy the requirement.
    """
    ops: List[Op] = []
    y = aabb.y0 + 1
    # Centre of the floor — where the headroom is highest. The bookshelf
    # is offset by 1 along the long axis so the central column under the
    # ridge stays free for the hanging lantern.
    cx = (aabb.x0 + aabb.x1 - 1) // 2
    cz = (aabb.z0 + aabb.z1 - 1) // 2

    if ridge_axis == "x":
        # Bookshelf shifted +x by 1 from centre; boxes shifted -x.
        bs_x = cx + 1 if cx + 1 < aabb.x1 - 1 else cx - 1
        ops.append(PlaceBlock(bs_x, y, cz, "minecraft:bookshelf"))
        for dx, dy_extra in ((-1, 0), (-2, 0), (-1, 1)):
            x = cx + dx
            yy = y + dy_extra
            if aabb.x0 < x < aabb.x1 - 1 and yy < aabb.y1:
                ops.append(PlaceBlock(x, yy, cz, "@primary"))
    else:
        bs_z = cz + 1 if cz + 1 < aabb.z1 - 1 else cz - 1
        ops.append(PlaceBlock(cx, y, bs_z, "minecraft:bookshelf"))
        for dz, dy_extra in ((-1, 0), (-2, 0), (-1, 1)):
            z = cz + dz
            yy = y + dy_extra
            if aabb.z0 < z < aabb.z1 - 1 and yy < aabb.y1:
                ops.append(PlaceBlock(cx, yy, z, "@primary"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Lanterns hanging from the ridge
# ────────────────────────────────────────────────────────────────────────


def _lanterns(aabb: AABB, ridge_axis: str, peak: int) -> List[Op]:
    """Hang at least one lantern from the layer just below the ridge.

    Larger attics get a second lantern offset along the long axis.
    """
    ops: List[Op] = []
    # The ridge itself is at y0 + peak; we hang lanterns one block below
    # the ridge so they appear to dangle from it.
    y_lant = aabb.y0 + peak - 1
    if y_lant <= aabb.y0:
        y_lant = aabb.y0 + 1

    if ridge_axis == "x":
        # ridge runs in x at z = centre (when peak shrinks fully)
        z_ridge = (aabb.z0 + aabb.z1 - 1) // 2
        cx = (aabb.x0 + aabb.x1 - 1) // 2
        ops.append(PlaceBlock(cx, y_lant, z_ridge, "minecraft:lantern[hanging=true]"))
        if aabb.w >= 8:
            ops.append(PlaceBlock(aabb.x0 + 2, y_lant, z_ridge,
                                  "minecraft:lantern[hanging=true]"))
            ops.append(PlaceBlock(aabb.x1 - 3, y_lant, z_ridge,
                                  "minecraft:lantern[hanging=true]"))
    else:
        x_ridge = (aabb.x0 + aabb.x1 - 1) // 2
        cz = (aabb.z0 + aabb.z1 - 1) // 2
        ops.append(PlaceBlock(x_ridge, y_lant, cz, "minecraft:lantern[hanging=true]"))
        if aabb.d >= 8:
            ops.append(PlaceBlock(x_ridge, y_lant, aabb.z0 + 2,
                                  "minecraft:lantern[hanging=true]"))
            ops.append(PlaceBlock(x_ridge, y_lant, aabb.z1 - 3,
                                  "minecraft:lantern[hanging=true]"))

    return ops
