"""Shared geometry primitives for the 150 universal generated skills.

Each helper returns a list of `Op` (PlaceBlock/Fill) that the generated skill
wrapper returns directly. None of these helpers commit to a building category —
they are pure shapes parametrised on `AABB`, `Materials`, `style`, and an
optional `params` dict.

The leading underscore is intentional: `pipeline/skills/__init__.list_skills()`
filters out modules starting with `_`, so this file is never treated as a skill.

Coordinate convention (matches `base.py`):
    x = width, y = up, z = depth; AABB is half-open `[x0,x1) × [y0,y1) × [z0,z1)`.
"""
from __future__ import annotations

from typing import List, Optional

from .base import AABB, Fill, Materials, Op, PlaceBlock


# ── safe block whitelist (subset of rag/materials/ that we use in recipes) ───
# These are the only literal block IDs the generated skills may reference.
# Materials role placeholders (@primary, @stairs, etc.) bypass this set
# because they are resolved at composer time against the runtime Materials.

# Role names that the generator emits
ROLES = ("@primary", "@secondary", "@accent", "@floor", "@roof",
         "@stairs", "@fence", "@slab", "@carpet", "@light",
         "@glass", "@bookshelf", "@lantern", "@flower_pot", "@glass_pane")


# ── tiny utilities ──────────────────────────────────────────────────────────

def _ok(a: AABB, w: int, d: int, h: int) -> bool:
    return a.w >= w and a.d >= d and a.h >= h


def _floor_y(a: AABB) -> int:
    """Y coordinate of the floor layer (the bottom-most usable y)."""
    return a.y0


def _ceiling_y(a: AABB) -> int:
    """Y coordinate of the topmost interior layer (under the ceiling)."""
    return a.y1 - 1


def _interior(a: AABB, inset: int = 1) -> AABB:
    """Walls-stripped interior with `inset` cells off each wall side, same y range."""
    return AABB(a.x0 + inset, a.y0, a.z0 + inset,
                a.x1 - inset, a.y1, a.z1 - inset)


# ── FLOOR family ────────────────────────────────────────────────────────────

def floor_checker(a: AABB, m: Materials, style: str, *,
                  a_block: str = "@primary", b_block: str = "@accent",
                  y_off: int = 0) -> List[Op]:
    """Checkerboard tile pattern across the floor at y = y0+y_off."""
    y = a.y0 + y_off
    ops: List[Op] = []
    for x in range(a.x0 + 1, a.x1 - 1):
        for z in range(a.z0 + 1, a.z1 - 1):
            ops.append(PlaceBlock(x, y, z,
                                   a_block if (x + z) % 2 == 0 else b_block))
    return ops or [PlaceBlock(a.cx, a.y0, a.cz, a_block)]


def floor_stripes(a: AABB, m: Materials, style: str, *,
                  a_block: str = "@primary", b_block: str = "@accent",
                  axis: str = "x", y_off: int = 0) -> List[Op]:
    """Alternating-stripe floor along x or z."""
    y = a.y0 + y_off
    ops: List[Op] = []
    for x in range(a.x0 + 1, a.x1 - 1):
        for z in range(a.z0 + 1, a.z1 - 1):
            i = x if axis == "x" else z
            ops.append(PlaceBlock(x, y, z, a_block if i % 2 == 0 else b_block))
    return ops or [PlaceBlock(a.cx, a.y0, a.cz, a_block)]


def floor_concentric(a: AABB, m: Materials, style: str, *,
                     outer: str = "@primary", inner: str = "@accent",
                     core: str = "@secondary", y_off: int = 0) -> List[Op]:
    """Three concentric rings on the floor (outer / inner / core)."""
    y = a.y0 + y_off
    cx, cz = a.cx, a.cz
    r_out = max(2, min(a.w, a.d) // 2 - 1)
    r_in = max(1, r_out - 2)
    ops: List[Op] = []
    for x in range(a.x0 + 1, a.x1 - 1):
        for z in range(a.z0 + 1, a.z1 - 1):
            d2 = (x - cx) ** 2 + (z - cz) ** 2
            if d2 <= 1:
                blk = core
            elif d2 <= r_in ** 2:
                blk = inner
            elif d2 <= r_out ** 2:
                blk = outer
            else:
                continue
            ops.append(PlaceBlock(x, y, z, blk))
    return ops or [PlaceBlock(cx, y, cz, core)]


def floor_center_inset(a: AABB, m: Materials, style: str, *,
                       base: str = "@primary", inset_blk: str = "@carpet",
                       inset: int = 2, y_off: int = 0) -> List[Op]:
    """Solid floor + a smaller rectangle of `inset_blk` centred on it."""
    y = a.y0 + y_off
    ops: List[Op] = []
    inner = _interior(a, inset)
    if inner.w < 1 or inner.d < 1:
        return [PlaceBlock(a.cx, y, a.cz, inset_blk)]
    for x in range(inner.x0, inner.x1):
        for z in range(inner.z0, inner.z1):
            ops.append(PlaceBlock(x, y, z, inset_blk))
    return ops or [PlaceBlock(a.cx, y, a.cz, inset_blk)]


# ── WALL family ─────────────────────────────────────────────────────────────

def wall_band(a: AABB, m: Materials, style: str, *,
              block: str = "@accent", y_frac: float = 0.5,
              one_block_in: bool = True) -> List[Op]:
    """Single-Y horizontal band of `block` running around the perimeter."""
    y = a.y0 + max(1, min(a.h - 2, int(a.h * y_frac)))
    ops: List[Op] = []
    ix0 = a.x0 + (1 if one_block_in else 0)
    iz0 = a.z0 + (1 if one_block_in else 0)
    ix1 = a.x1 - (1 if one_block_in else 0)
    iz1 = a.z1 - (1 if one_block_in else 0)
    for x in range(ix0, ix1):
        ops.append(PlaceBlock(x, y, iz0, block))
        ops.append(PlaceBlock(x, y, iz1 - 1, block))
    for z in range(iz0 + 1, iz1 - 1):
        ops.append(PlaceBlock(ix0, y, z, block))
        ops.append(PlaceBlock(ix1 - 1, y, z, block))
    return ops or [PlaceBlock(a.x0, y, a.z0, block)]


def wall_pilasters(a: AABB, m: Materials, style: str, *,
                   block: str = "@accent", every: int = 3,
                   one_block_in: bool = True) -> List[Op]:
    """Vertical pilaster columns at regular intervals on the four interior walls."""
    inset = 1 if one_block_in else 0
    y_lo = a.y0 + 1
    y_hi = a.y1 - 1
    ops: List[Op] = []
    every = max(2, every)
    for x in range(a.x0 + inset, a.x1 - inset, every):
        for y in range(y_lo, y_hi):
            ops.append(PlaceBlock(x, y, a.z0 + inset, block))
            ops.append(PlaceBlock(x, y, a.z1 - 1 - inset, block))
    for z in range(a.z0 + inset, a.z1 - inset, every):
        for y in range(y_lo, y_hi):
            ops.append(PlaceBlock(a.x0 + inset, y, z, block))
            ops.append(PlaceBlock(a.x1 - 1 - inset, y, z, block))
    return ops or [PlaceBlock(a.x0, y_lo, a.z0, block)]


def wall_niche(a: AABB, m: Materials, style: str, *,
               block: str = "@accent", count: int = 2) -> List[Op]:
    """Carved-niche markers — accent blocks at chest height on the long walls."""
    y = a.y0 + max(1, a.h // 2)
    n = max(1, min(count, max(1, a.w // 4)))
    ops: List[Op] = []
    for i in range(n):
        cx = a.x0 + 1 + int((i + 1) * (a.w - 2) / (n + 1))
        ops.append(PlaceBlock(cx, y, a.z0 + 1, block))
        ops.append(PlaceBlock(cx, y, a.z1 - 2, block))
    return ops or [PlaceBlock(a.x0, y, a.z0, block)]


def wall_lattice(a: AABB, m: Materials, style: str, *,
                 block: str = "@glass_pane") -> List[Op]:
    """Decorative lattice — pane-blocks across every other interior wall cell."""
    y_mid = a.y0 + max(1, a.h // 2)
    ops: List[Op] = []
    for x in range(a.x0 + 1, a.x1 - 1, 2):
        ops.append(PlaceBlock(x, y_mid, a.z0, block))
        ops.append(PlaceBlock(x, y_mid, a.z1 - 1, block))
    for z in range(a.z0 + 1, a.z1 - 1, 2):
        ops.append(PlaceBlock(a.x0, y_mid, z, block))
        ops.append(PlaceBlock(a.x1 - 1, y_mid, z, block))
    return ops or [PlaceBlock(a.x0, y_mid, a.z0, block)]


# ── CEILING family ──────────────────────────────────────────────────────────

def ceiling_grid(a: AABB, m: Materials, style: str, *,
                 block: str = "@secondary", every: int = 3) -> List[Op]:
    """Cross-beam grid one Y below the ceiling."""
    y = a.y1 - 2
    if y <= a.y0:
        return [PlaceBlock(a.cx, a.y0, a.cz, block)]
    ops: List[Op] = []
    every = max(2, every)
    for x in range(a.x0 + 1, a.x1 - 1):
        if (x - a.x0) % every == 0:
            for z in range(a.z0 + 1, a.z1 - 1):
                ops.append(PlaceBlock(x, y, z, block))
    for z in range(a.z0 + 1, a.z1 - 1):
        if (z - a.z0) % every == 0:
            for x in range(a.x0 + 1, a.x1 - 1):
                ops.append(PlaceBlock(x, y, z, block))
    return ops or [PlaceBlock(a.cx, y, a.cz, block)]


def ceiling_center_fixture(a: AABB, m: Materials, style: str, *,
                            top: str = "@accent", chain: str = "@fence",
                            light: str = "@lantern",
                            drop: int = 2) -> List[Op]:
    """Single hanging fixture from the ceiling centre."""
    y_top = a.y1 - 1
    cx, cz = a.cx, a.cz
    ops: List[Op] = [PlaceBlock(cx, y_top, cz, top)]
    for k in range(1, max(1, drop) + 1):
        ops.append(PlaceBlock(cx, y_top - k, cz, chain))
    ops.append(PlaceBlock(cx, y_top - max(1, drop) - 1, cz, light))
    return ops


def ceiling_radial(a: AABB, m: Materials, style: str, *,
                   block: str = "@secondary") -> List[Op]:
    """Four radial beams from centre out to each wall, one Y below ceiling."""
    y = a.y1 - 2
    if y <= a.y0:
        return [PlaceBlock(a.cx, a.y0, a.cz, block)]
    cx, cz = a.cx, a.cz
    ops: List[Op] = []
    for x in range(a.x0 + 1, a.x1 - 1):
        ops.append(PlaceBlock(x, y, cz, block))
    for z in range(a.z0 + 1, a.z1 - 1):
        ops.append(PlaceBlock(cx, y, z, block))
    return ops or [PlaceBlock(cx, y, cz, block)]


def ceiling_coffer(a: AABB, m: Materials, style: str, *,
                   edge: str = "@secondary", panel: str = "@accent") -> List[Op]:
    """Coffered ceiling: 2x2 panels with edge frames."""
    y = a.y1 - 1
    ops: List[Op] = []
    for x in range(a.x0 + 1, a.x1 - 1):
        for z in range(a.z0 + 1, a.z1 - 1):
            on_edge = ((x - a.x0) % 3 == 0) or ((z - a.z0) % 3 == 0)
            ops.append(PlaceBlock(x, y, z, edge if on_edge else panel))
    return ops or [PlaceBlock(a.cx, y, a.cz, panel)]


def ceiling_skylight(a: AABB, m: Materials, style: str, *,
                     glass: str = "@glass") -> List[Op]:
    """Glass square set into the ceiling centre."""
    y = a.y1 - 1
    inner = _interior(a, max(2, min(a.w, a.d) // 3))
    if inner.w < 1 or inner.d < 1:
        return [PlaceBlock(a.cx, y, a.cz, glass)]
    ops: List[Op] = []
    for x in range(inner.x0, inner.x1):
        for z in range(inner.z0, inner.z1):
            ops.append(PlaceBlock(x, y, z, glass))
    return ops


# ── CORNER family ───────────────────────────────────────────────────────────

def corner_posts(a: AABB, m: Materials, style: str, *,
                 block: str = "@accent", cap: Optional[str] = "@light",
                 height: Optional[int] = None) -> List[Op]:
    """Vertical column in each of the four interior corners."""
    h = height or max(2, a.h - 1)
    y_lo = a.y0
    y_hi = y_lo + h
    inset = 1
    ops: List[Op] = []
    for (cx, cz) in [(a.x0 + inset, a.z0 + inset),
                      (a.x1 - 1 - inset, a.z0 + inset),
                      (a.x0 + inset, a.z1 - 1 - inset),
                      (a.x1 - 1 - inset, a.z1 - 1 - inset)]:
        for y in range(y_lo, min(y_hi, a.y1)):
            ops.append(PlaceBlock(cx, y, cz, block))
        if cap is not None and y_hi - 1 < a.y1:
            ops.append(PlaceBlock(cx, min(y_hi, a.y1 - 1), cz, cap))
    return ops or [PlaceBlock(a.x0, y_lo, a.z0, block)]


def corner_accents(a: AABB, m: Materials, style: str, *,
                   block: str = "@accent") -> List[Op]:
    """Single-block accent at each of the 4 interior floor corners."""
    y = a.y0 + 1
    ops: List[Op] = []
    for (cx, cz) in [(a.x0 + 1, a.z0 + 1), (a.x1 - 2, a.z0 + 1),
                      (a.x0 + 1, a.z1 - 2), (a.x1 - 2, a.z1 - 2)]:
        ops.append(PlaceBlock(cx, y, cz, block))
    return ops


# ── FURNITURE family ────────────────────────────────────────────────────────

def perimeter_bench(a: AABB, m: Materials, style: str, *,
                    block: str = "@stairs") -> List[Op]:
    """Inward-facing stair bench along each of the four interior walls."""
    y = a.y0 + 1
    ops: List[Op] = []
    for x in range(a.x0 + 2, a.x1 - 2):
        ops.append(PlaceBlock(x, y, a.z0 + 1, f"{block}[facing=south]"))
        ops.append(PlaceBlock(x, y, a.z1 - 2, f"{block}[facing=north]"))
    for z in range(a.z0 + 2, a.z1 - 2):
        ops.append(PlaceBlock(a.x0 + 1, y, z, f"{block}[facing=east]"))
        ops.append(PlaceBlock(a.x1 - 2, y, z, f"{block}[facing=west]"))
    return ops or [PlaceBlock(a.x0 + 1, y, a.z0 + 1, block)]


def center_table(a: AABB, m: Materials, style: str, *,
                 top: str = "@slab", post: str = "@fence") -> List[Op]:
    """1x1 table at room centre — fence post + slab top."""
    cx, cz = a.cx, a.cz
    y = a.y0 + 1
    ops: List[Op] = [PlaceBlock(cx, y, cz, post)]
    if y + 1 < a.y1:
        ops.append(PlaceBlock(cx, y + 1, cz, top))
    return ops


def row_of_shelves(a: AABB, m: Materials, style: str, *,
                   block: str = "@bookshelf",
                   side: str = "north") -> List[Op]:
    """Row of bookshelves stacked 2 high along one wall."""
    ops: List[Op] = []
    y0 = a.y0 + 1
    y1 = min(y0 + 2, a.y1 - 1)
    if side == "north":
        z = a.z0 + 1
        for x in range(a.x0 + 1, a.x1 - 1):
            for y in range(y0, y1):
                ops.append(PlaceBlock(x, y, z, block))
    elif side == "south":
        z = a.z1 - 2
        for x in range(a.x0 + 1, a.x1 - 1):
            for y in range(y0, y1):
                ops.append(PlaceBlock(x, y, z, block))
    elif side == "west":
        x = a.x0 + 1
        for z in range(a.z0 + 1, a.z1 - 1):
            for y in range(y0, y1):
                ops.append(PlaceBlock(x, y, z, block))
    else:
        x = a.x1 - 2
        for z in range(a.z0 + 1, a.z1 - 1):
            for y in range(y0, y1):
                ops.append(PlaceBlock(x, y, z, block))
    return ops or [PlaceBlock(a.x0 + 1, y0, a.z0 + 1, block)]


def cushion_set(a: AABB, m: Materials, style: str, *,
                block: str = "@carpet") -> List[Op]:
    """Carpet cushions in a regular grid on the floor."""
    y = a.y0 + 1
    ops: List[Op] = []
    for x in range(a.x0 + 2, a.x1 - 2, 2):
        for z in range(a.z0 + 2, a.z1 - 2, 2):
            ops.append(PlaceBlock(x, y, z, block))
    return ops or [PlaceBlock(a.cx, y, a.cz, block)]


# ── LIGHT family ────────────────────────────────────────────────────────────

def perimeter_lanterns(a: AABB, m: Materials, style: str, *,
                       block: str = "@lantern", every: int = 3) -> List[Op]:
    """Lantern markers along the four interior walls one Y below the ceiling."""
    y = a.y1 - 2
    if y <= a.y0:
        return [PlaceBlock(a.cx, a.y0, a.cz, block)]
    ops: List[Op] = []
    every = max(2, every)
    for x in range(a.x0 + 1, a.x1 - 1, every):
        ops.append(PlaceBlock(x, y, a.z0 + 1, block))
        ops.append(PlaceBlock(x, y, a.z1 - 2, block))
    for z in range(a.z0 + 1, a.z1 - 1, every):
        ops.append(PlaceBlock(a.x0 + 1, y, z, block))
        ops.append(PlaceBlock(a.x1 - 2, y, z, block))
    return ops or [PlaceBlock(a.x0 + 1, y, a.z0 + 1, block)]


def torch_ring(a: AABB, m: Materials, style: str, *,
                block: str = "minecraft:torch") -> List[Op]:
    """Ring of torches on the floor near the perimeter."""
    y = a.y0 + 1
    ops: List[Op] = []
    for x in range(a.x0 + 2, a.x1 - 2, 3):
        ops.append(PlaceBlock(x, y, a.z0 + 2, block))
        ops.append(PlaceBlock(x, y, a.z1 - 3, block))
    for z in range(a.z0 + 2, a.z1 - 2, 3):
        ops.append(PlaceBlock(a.x0 + 2, y, z, block))
        ops.append(PlaceBlock(a.x1 - 3, y, z, block))
    return ops or [PlaceBlock(a.x0 + 1, y, a.z0 + 1, block)]


def candle_circle(a: AABB, m: Materials, style: str, *,
                  block: str = "minecraft:torch") -> List[Op]:
    """Small ring of light blocks around the centre."""
    cx, cz = a.cx, a.cz
    y = a.y0 + 1
    r = max(2, min(a.w, a.d) // 3)
    ops: List[Op] = []
    for x in range(a.x0 + 1, a.x1 - 1):
        for z in range(a.z0 + 1, a.z1 - 1):
            d2 = (x - cx) ** 2 + (z - cz) ** 2
            if abs(d2 - r * r) <= max(1, r):
                ops.append(PlaceBlock(x, y, z, block))
    return ops or [PlaceBlock(cx, y, cz, block)]


# ── ROOF DETAIL family (sit on top, y = y1) ─────────────────────────────────

def vertical_spire(a: AABB, m: Materials, style: str, *,
                    block: str = "@accent", cap: Optional[str] = None,
                    height: int = 3) -> List[Op]:
    """Vertical mast above the centre of the AABB top, optional cap block."""
    cx, cz = a.cx, a.cz
    base_y = a.y1
    ops: List[Op] = []
    for k in range(max(1, height)):
        ops.append(PlaceBlock(cx, base_y + k, cz, block))
    if cap is not None:
        ops.append(PlaceBlock(cx, base_y + max(1, height), cz, cap))
    return ops


def chimney_cluster(a: AABB, m: Materials, style: str, *,
                    block: str = "@secondary",
                    smoke: Optional[str] = "minecraft:campfire",
                    count: int = 2, height: int = 3) -> List[Op]:
    """Cluster of chimneys above the roof."""
    base_y = a.y1
    ops: List[Op] = []
    spots = [(a.x0 + max(1, a.w // 4), a.z0 + max(1, a.d // 4)),
             (a.x1 - 1 - max(1, a.w // 4), a.z1 - 1 - max(1, a.d // 4)),
             (a.cx, a.cz)]
    for i, (cx, cz) in enumerate(spots[:max(1, count)]):
        for k in range(max(2, height)):
            ops.append(PlaceBlock(cx, base_y + k, cz, block))
        if smoke is not None:
            ops.append(PlaceBlock(cx, base_y + max(2, height), cz, smoke))
    return ops


def ridge_band(a: AABB, m: Materials, style: str, *,
                block: str = "@accent") -> List[Op]:
    """Decorative band of `block` along the longer roof ridge."""
    base_y = a.y1
    ops: List[Op] = []
    if a.w >= a.d:
        cz = a.cz
        for x in range(a.x0, a.x1):
            ops.append(PlaceBlock(x, base_y, cz, block))
    else:
        cx = a.cx
        for z in range(a.z0, a.z1):
            ops.append(PlaceBlock(cx, base_y, z, block))
    return ops or [PlaceBlock(a.cx, base_y, a.cz, block)]


def cupola_small(a: AABB, m: Materials, style: str, *,
                  body: str = "@accent", glass: str = "@glass_pane",
                  cap: str = "@accent") -> List[Op]:
    """Small windowed lantern (1x1 base, 1 glass, 1 cap) at the roof centre."""
    cx, cz = a.cx, a.cz
    by = a.y1
    return [PlaceBlock(cx, by, cz, body),
            PlaceBlock(cx, by + 1, cz, glass),
            PlaceBlock(cx, by + 2, cz, cap)]


# ── FOUNTAIN family (exterior / patio) ─────────────────────────────────────

def fountain_single_basin(a: AABB, m: Materials, style: str, *,
                          rim: str = "@accent", water: str = "minecraft:water",
                          spout: str = "@secondary") -> List[Op]:
    """Square basin of rim + interior water + tall spout column at centre."""
    y = a.y0
    ops: List[Op] = []
    # Basin ring at y0
    for x in range(a.x0 + 1, a.x1 - 1):
        ops.append(PlaceBlock(x, y, a.z0 + 1, rim))
        ops.append(PlaceBlock(x, y, a.z1 - 2, rim))
    for z in range(a.z0 + 1, a.z1 - 1):
        ops.append(PlaceBlock(a.x0 + 1, y, z, rim))
        ops.append(PlaceBlock(a.x1 - 2, y, z, rim))
    # Water inside
    for x in range(a.x0 + 2, a.x1 - 2):
        for z in range(a.z0 + 2, a.z1 - 2):
            ops.append(PlaceBlock(x, y, z, water))
    # Central spout
    cx, cz = a.cx, a.cz
    for k in range(min(2, a.h)):
        ops.append(PlaceBlock(cx, y + 1 + k, cz, spout))
    return ops or [PlaceBlock(a.cx, y, a.cz, water)]


def fountain_tiered(a: AABB, m: Materials, style: str, *,
                    base: str = "@accent", water: str = "minecraft:water",
                    crown: str = "@secondary") -> List[Op]:
    """Tiered fountain: large basin, smaller basin above, jet column at top."""
    y = a.y0
    ops: List[Op] = []
    # Tier 1 (large, low)
    for x in range(a.x0 + 1, a.x1 - 1):
        for z in range(a.z0 + 1, a.z1 - 1):
            on_edge = (x in (a.x0 + 1, a.x1 - 2) or z in (a.z0 + 1, a.z1 - 2))
            if on_edge:
                ops.append(PlaceBlock(x, y, z, base))
            else:
                ops.append(PlaceBlock(x, y, z, water))
    # Tier 2 (smaller, higher)
    inner = _interior(a, 2)
    if inner.w >= 2 and inner.d >= 2 and y + 2 < a.y1:
        for x in range(inner.x0, inner.x1):
            for z in range(inner.z0, inner.z1):
                on_edge = (x in (inner.x0, inner.x1 - 1)
                            or z in (inner.z0, inner.z1 - 1))
                if on_edge:
                    ops.append(PlaceBlock(x, y + 2, z, base))
                else:
                    ops.append(PlaceBlock(x, y + 2, z, water))
    # Central crown
    cx, cz = a.cx, a.cz
    if y + 3 < a.y1:
        ops.append(PlaceBlock(cx, y + 3, cz, crown))
    return ops or [PlaceBlock(a.cx, y, a.cz, water)]


def fountain_wall_mounted(a: AABB, m: Materials, style: str, *,
                          wall: str = "@accent", water: str = "minecraft:water",
                          basin: str = "@stairs") -> List[Op]:
    """Wall fountain on the +X face: vertical accent wall + 1-block basin
    sticking out at the bottom + water at top."""
    y0 = a.y0
    x_wall = a.x1 - 1
    ops: List[Op] = []
    cz = a.cz
    for y in range(y0, a.y1):
        ops.append(PlaceBlock(x_wall, y, cz, wall))
    if x_wall - 1 >= a.x0:
        ops.append(PlaceBlock(x_wall - 1, y0 + 1, cz, f"{basin}[facing=west]"))
        ops.append(PlaceBlock(x_wall - 1, a.y1 - 1, cz, water))
    return ops or [PlaceBlock(x_wall, y0, cz, wall)]


# ── GARDEN family (exterior, low to ground) ─────────────────────────────────

def garden_parterre(a: AABB, m: Materials, style: str, *,
                    edge: str = "@accent",
                    bed: str = "minecraft:grass_block",
                    flower: str = "minecraft:poppy") -> List[Op]:
    """Geometric flowerbed: edges of `edge`, interior of `bed`, flowers on top."""
    y = a.y0
    ops: List[Op] = []
    for x in range(a.x0, a.x1):
        for z in range(a.z0, a.z1):
            on_edge = (x in (a.x0, a.x1 - 1) or z in (a.z0, a.z1 - 1))
            if on_edge:
                ops.append(PlaceBlock(x, y, z, edge))
            else:
                ops.append(PlaceBlock(x, y, z, bed))
                if (x + z) % 2 == 0 and y + 1 < a.y1:
                    ops.append(PlaceBlock(x, y + 1, z, flower))
    return ops or [PlaceBlock(a.cx, y, a.cz, flower)]


def garden_zen(a: AABB, m: Materials, style: str, *,
               gravel: str = "minecraft:gravel",
               rock: str = "minecraft:cobblestone") -> List[Op]:
    """Karesansui-style gravel bed with scattered cobble rocks."""
    y = a.y0
    ops: List[Op] = []
    for x in range(a.x0, a.x1):
        for z in range(a.z0, a.z1):
            ops.append(PlaceBlock(x, y, z, gravel))
    cx, cz = a.cx, a.cz
    spots = [(cx, cz), (cx - 2, cz - 1), (cx + 1, cz + 2)]
    for (rx, rz) in spots:
        if a.x0 <= rx < a.x1 and a.z0 <= rz < a.z1 and y + 1 < a.y1:
            ops.append(PlaceBlock(rx, y + 1, rz, rock))
    return ops


def garden_flowerbed(a: AABB, m: Materials, style: str, *,
                     bed: str = "minecraft:grass_block",
                     flowers=("minecraft:poppy", "minecraft:dandelion",
                              "minecraft:blue_orchid")) -> List[Op]:
    """Solid grass bed with alternating flower species on top."""
    y = a.y0
    ops: List[Op] = []
    flist = list(flowers)
    for x in range(a.x0, a.x1):
        for z in range(a.z0, a.z1):
            ops.append(PlaceBlock(x, y, z, bed))
            if y + 1 < a.y1 and (x + z) % 2 == 0:
                ops.append(PlaceBlock(x, y + 1, z,
                                       flist[(x + z) % len(flist)]))
    return ops or [PlaceBlock(a.cx, y, a.cz, bed)]


def garden_pond(a: AABB, m: Materials, style: str, *,
                rim: str = "@accent", water: str = "minecraft:water") -> List[Op]:
    """Sunken pond: rim around perimeter, water filling interior at y0."""
    y = a.y0
    ops: List[Op] = []
    for x in range(a.x0, a.x1):
        for z in range(a.z0, a.z1):
            on_edge = (x in (a.x0, a.x1 - 1) or z in (a.z0, a.z1 - 1))
            ops.append(PlaceBlock(x, y, z, rim if on_edge else water))
    return ops or [PlaceBlock(a.cx, y, a.cz, water)]


def garden_hedge_rows(a: AABB, m: Materials, style: str, *,
                      hedge: str = "minecraft:oak_leaves") -> List[Op]:
    """Parallel hedges of leaves running along the long axis."""
    y = a.y0
    ops: List[Op] = []
    if a.w >= a.d:
        for x in range(a.x0, a.x1):
            for z in range(a.z0 + 1, a.z1 - 1, 3):
                if y + 1 < a.y1:
                    ops.append(PlaceBlock(x, y + 1, z, hedge))
    else:
        for z in range(a.z0, a.z1):
            for x in range(a.x0 + 1, a.x1 - 1, 3):
                if y + 1 < a.y1:
                    ops.append(PlaceBlock(x, y + 1, z, hedge))
    return ops or [PlaceBlock(a.cx, y, a.cz, hedge)]


def garden_bonsai_collection(a: AABB, m: Materials, style: str, *,
                             pot: str = "@flower_pot",
                             leaf: str = "minecraft:oak_leaves") -> List[Op]:
    """Row of small "bonsai" mounds — leaves on pots on the floor."""
    y = a.y0
    ops: List[Op] = []
    for x in range(a.x0 + 1, a.x1 - 1, 2):
        for z in range(a.z0 + 1, a.z1 - 1, 2):
            ops.append(PlaceBlock(x, y, z, pot))
            if y + 1 < a.y1:
                ops.append(PlaceBlock(x, y + 1, z, leaf))
    return ops or [PlaceBlock(a.cx, y, a.cz, pot)]


# ── EXTERIOR STRUCTURE family ───────────────────────────────────────────────

def pergola_arch(a: AABB, m: Materials, style: str, *,
                 post: str = "@fence", beam: str = "@secondary",
                 vine: Optional[str] = "minecraft:oak_leaves") -> List[Op]:
    """Open pergola: four corner posts + crossbeams + optional vine canopy."""
    y0 = a.y0
    y1 = a.y1 - 1
    ops: List[Op] = []
    corners = [(a.x0, a.z0), (a.x1 - 1, a.z0),
               (a.x0, a.z1 - 1), (a.x1 - 1, a.z1 - 1)]
    for (cx, cz) in corners:
        for y in range(y0, y1):
            ops.append(PlaceBlock(cx, y, cz, post))
    for x in range(a.x0, a.x1):
        ops.append(PlaceBlock(x, y1, a.z0, beam))
        ops.append(PlaceBlock(x, y1, a.z1 - 1, beam))
    for z in range(a.z0, a.z1):
        ops.append(PlaceBlock(a.x0, y1, z, beam))
        ops.append(PlaceBlock(a.x1 - 1, y1, z, beam))
    if vine is not None:
        for x in range(a.x0 + 1, a.x1 - 1, 2):
            for z in range(a.z0 + 1, a.z1 - 1, 2):
                ops.append(PlaceBlock(x, y1, z, vine))
    return ops or [PlaceBlock(a.x0, y0, a.z0, post)]


def gazebo_open(a: AABB, m: Materials, style: str, *,
                 post: str = "@fence", roof: str = "@roof",
                 floor_blk: str = "@floor") -> List[Op]:
    """Open gazebo: 4 posts, a closed roof, and a floor pad."""
    y0 = a.y0
    y1 = a.y1 - 1
    ops: List[Op] = []
    for x in range(a.x0, a.x1):
        for z in range(a.z0, a.z1):
            ops.append(PlaceBlock(x, y0, z, floor_blk))
    for (cx, cz) in [(a.x0, a.z0), (a.x1 - 1, a.z0),
                      (a.x0, a.z1 - 1), (a.x1 - 1, a.z1 - 1)]:
        for y in range(y0 + 1, y1):
            ops.append(PlaceBlock(cx, y, cz, post))
    for x in range(a.x0, a.x1):
        for z in range(a.z0, a.z1):
            ops.append(PlaceBlock(x, y1, z, roof))
    return ops


def statue_pedestal(a: AABB, m: Materials, style: str, *,
                    base: str = "@accent", body: str = "@secondary",
                    head: str = "@accent") -> List[Op]:
    """Small column on a base block — a stylised statue."""
    cx, cz = a.cx, a.cz
    y = a.y0
    ops: List[Op] = []
    # base 1x1
    ops.append(PlaceBlock(cx, y, cz, base))
    # body up to half of available height
    h = max(1, min(a.h - 2, 4))
    for k in range(1, 1 + h):
        ops.append(PlaceBlock(cx, y + k, cz, body))
    ops.append(PlaceBlock(cx, y + 1 + h, cz, head))
    return ops


def freestanding_column(a: AABB, m: Materials, style: str, *,
                         shaft: str = "@accent",
                         cap: str = "@secondary") -> List[Op]:
    """Single column at centre — shaft of `shaft` capped with `cap`."""
    cx, cz = a.cx, a.cz
    y = a.y0
    ops: List[Op] = []
    h = max(2, a.h - 1)
    for k in range(h):
        ops.append(PlaceBlock(cx, y + k, cz, shaft))
    ops.append(PlaceBlock(cx, y + h, cz, cap))
    return ops


def column_pair(a: AABB, m: Materials, style: str, *,
                shaft: str = "@accent", cap: str = "@secondary") -> List[Op]:
    """Two parallel columns spanning the longer axis."""
    y0 = a.y0
    h = max(2, a.h - 1)
    ops: List[Op] = []
    if a.w >= a.d:
        c1, c2 = a.x0 + 1, a.x1 - 2
        cz = a.cz
        for cx in (c1, c2):
            for k in range(h):
                ops.append(PlaceBlock(cx, y0 + k, cz, shaft))
            ops.append(PlaceBlock(cx, y0 + h, cz, cap))
    else:
        c1, c2 = a.z0 + 1, a.z1 - 2
        cx = a.cx
        for cz in (c1, c2):
            for k in range(h):
                ops.append(PlaceBlock(cx, y0 + k, cz, shaft))
            ops.append(PlaceBlock(cx, y0 + h, cz, cap))
    return ops


def triumphal_arch(a: AABB, m: Materials, style: str, *,
                    block: str = "@accent") -> List[Op]:
    """Single freestanding gateway arch spanning the longer axis."""
    ops: List[Op] = []
    y0 = a.y0
    h = max(3, a.h - 1)
    if a.w >= a.d:
        cz = a.cz
        ax0, ax1 = a.x0 + 1, a.x1 - 2
        # uprights
        for y in range(y0, y0 + h):
            ops.append(PlaceBlock(ax0, y, cz, block))
            ops.append(PlaceBlock(ax1, y, cz, block))
        # arch
        for x in range(ax0, ax1 + 1):
            ops.append(PlaceBlock(x, y0 + h, cz, block))
    else:
        cx = a.cx
        ay0, ay1 = a.z0 + 1, a.z1 - 2
        for y in range(y0, y0 + h):
            ops.append(PlaceBlock(cx, y, ay0, block))
            ops.append(PlaceBlock(cx, y, ay1, block))
        for z in range(ay0, ay1 + 1):
            ops.append(PlaceBlock(cx, y0 + h, z, block))
    return ops or [PlaceBlock(a.cx, y0, a.cz, block)]


# ── PATHWAY / BOUNDARY family ───────────────────────────────────────────────

def pathway_line(a: AABB, m: Materials, style: str, *,
                 block: str = "@accent") -> List[Op]:
    """Single-cell-wide path of `block` along the longer axis at y0."""
    y = a.y0
    ops: List[Op] = []
    if a.w >= a.d:
        cz = a.cz
        for x in range(a.x0, a.x1):
            ops.append(PlaceBlock(x, y, cz, block))
    else:
        cx = a.cx
        for z in range(a.z0, a.z1):
            ops.append(PlaceBlock(cx, y, z, block))
    return ops or [PlaceBlock(a.cx, y, a.cz, block)]


def pathway_with_lanterns(a: AABB, m: Materials, style: str, *,
                          path: str = "@accent",
                          lantern: str = "@lantern") -> List[Op]:
    """Single-cell path along the long axis with lantern posts every 3 cells."""
    y = a.y0
    ops = pathway_line(a, m, style, block=path)
    if a.w >= a.d:
        cz = a.cz
        for x in range(a.x0 + 1, a.x1 - 1, 3):
            ops.append(PlaceBlock(x, y + 1, cz - 1, lantern))
            ops.append(PlaceBlock(x, y + 1, cz + 1, lantern))
    else:
        cx = a.cx
        for z in range(a.z0 + 1, a.z1 - 1, 3):
            ops.append(PlaceBlock(cx - 1, y + 1, z, lantern))
            ops.append(PlaceBlock(cx + 1, y + 1, z, lantern))
    return ops


def stepping_stones(a: AABB, m: Materials, style: str, *,
                    block: str = "minecraft:cobblestone") -> List[Op]:
    """Discrete stones at intervals along the long axis."""
    y = a.y0
    ops: List[Op] = []
    if a.w >= a.d:
        cz = a.cz
        for x in range(a.x0 + 1, a.x1 - 1, 2):
            ops.append(PlaceBlock(x, y, cz, block))
    else:
        cx = a.cx
        for z in range(a.z0 + 1, a.z1 - 1, 2):
            ops.append(PlaceBlock(cx, y, z, block))
    return ops or [PlaceBlock(a.cx, y, a.cz, block)]


def boundary_wall(a: AABB, m: Materials, style: str, *,
                   block: str = "@secondary") -> List[Op]:
    """Low (1-block tall) perimeter wall."""
    y = a.y0
    ops: List[Op] = []
    for x in range(a.x0, a.x1):
        ops.append(PlaceBlock(x, y, a.z0, block))
        ops.append(PlaceBlock(x, y, a.z1 - 1, block))
    for z in range(a.z0 + 1, a.z1 - 1):
        ops.append(PlaceBlock(a.x0, y, z, block))
        ops.append(PlaceBlock(a.x1 - 1, y, z, block))
    if a.h >= 2:
        for x in range(a.x0, a.x1):
            ops.append(PlaceBlock(x, y + 1, a.z0, block))
            ops.append(PlaceBlock(x, y + 1, a.z1 - 1, block))
        for z in range(a.z0 + 1, a.z1 - 1):
            ops.append(PlaceBlock(a.x0, y + 1, z, block))
            ops.append(PlaceBlock(a.x1 - 1, y + 1, z, block))
    return ops or [PlaceBlock(a.x0, y, a.z0, block)]


def hedge_boundary(a: AABB, m: Materials, style: str, *,
                    hedge: str = "minecraft:oak_leaves") -> List[Op]:
    """1-block tall hedge along perimeter (leaves)."""
    y = a.y0
    ops: List[Op] = []
    for x in range(a.x0, a.x1):
        ops.append(PlaceBlock(x, y, a.z0, hedge))
        ops.append(PlaceBlock(x, y, a.z1 - 1, hedge))
    for z in range(a.z0 + 1, a.z1 - 1):
        ops.append(PlaceBlock(a.x0, y, z, hedge))
        ops.append(PlaceBlock(a.x1 - 1, y, z, hedge))
    return ops or [PlaceBlock(a.x0, y, a.z0, hedge)]


def iron_railing(a: AABB, m: Materials, style: str, *,
                  block: str = "minecraft:iron_bars") -> List[Op]:
    """Iron-bar railing along perimeter."""
    return boundary_wall(a, m, style, block=block)


# ── MISC family ─────────────────────────────────────────────────────────────

def alcove_seat(a: AABB, m: Materials, style: str, *,
                seat: str = "@stairs", back: str = "@accent") -> List[Op]:
    """Single inset seat against the -Z wall."""
    y = a.y0 + 1
    cx = a.cx
    ops: List[Op] = []
    if a.z0 + 1 < a.z1:
        ops.append(PlaceBlock(cx, y, a.z0 + 1, f"{seat}[facing=south]"))
        ops.append(PlaceBlock(cx, y + 1, a.z0 + 1, back))
    return ops or [PlaceBlock(cx, y, a.cz, back)]


def arch_opening(a: AABB, m: Materials, style: str, *,
                  block: str = "@accent") -> List[Op]:
    """Arch shape carved into the -Z wall (purely decorative — places `block`
    around an opening)."""
    y0 = a.y0
    h = max(3, min(a.h - 1, 5))
    cx = a.cx
    z = a.z0
    ops: List[Op] = []
    for y in range(y0, y0 + h):
        ops.append(PlaceBlock(cx - 1, y, z, block))
        ops.append(PlaceBlock(cx + 1, y, z, block))
    for x in (cx - 1, cx, cx + 1):
        ops.append(PlaceBlock(x, y0 + h, z, block))
    return ops or [PlaceBlock(cx, y0, z, block)]


def mirror_wall(a: AABB, m: Materials, style: str, *,
                 block: str = "@glass") -> List[Op]:
    """Solid glass plane along one interior wall (`-Z`)."""
    z = a.z0 + 1
    ops: List[Op] = []
    for x in range(a.x0 + 1, a.x1 - 1):
        for y in range(a.y0 + 1, a.y1 - 1):
            ops.append(PlaceBlock(x, y, z, block))
    return ops or [PlaceBlock(a.cx, a.y0 + 1, z, block)]


def carpet_runner(a: AABB, m: Materials, style: str, *,
                   block: str = "@carpet") -> List[Op]:
    """3-cell-wide carpet down the long axis."""
    y = a.y0 + 1
    ops: List[Op] = []
    if a.w >= a.d:
        for x in range(a.x0 + 1, a.x1 - 1):
            for dz in (-1, 0, 1):
                z = a.cz + dz
                if a.z0 < z < a.z1 - 1:
                    ops.append(PlaceBlock(x, y, z, block))
    else:
        for z in range(a.z0 + 1, a.z1 - 1):
            for dx in (-1, 0, 1):
                x = a.cx + dx
                if a.x0 < x < a.x1 - 1:
                    ops.append(PlaceBlock(x, y, z, block))
    return ops or [PlaceBlock(a.cx, y, a.cz, block)]
