"""Skill: dovecote.

A small tower for "doves" (a dovecote / palomar). Like a miniature
round tower but with a different program: nesting holes punched into
the upper wall, a conical/pointed roof tapering to a single accent
block, and an optional flagpole topped with a bone-block "dove" proxy.

Features:
  - Hollow @primary cylinder shell, radius = min(W,D)//2.
  - Solid @secondary foundation disc at y0.
  - 8-12 nesting holes in the upper half of the wall, rendered as
    `minecraft:hay_block` (the visible dove holes).
  - Conical roof: stacked stair rings shrinking by 1 in radius per
    Y-step until they converge to a single @accent block at the apex.
  - Optional flagpole: a 1-block fence post above the apex with
    `minecraft:bone_block` as the "dove" proxy on top.
  - One `minecraft:lantern` inside for nighttime visibility.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Defensive sizing: clamped to 3×4×3 .. 5×12×5 (small tower envelope).
"""
from __future__ import annotations

import math
from typing import List

from .base import AABB, Cylinder, Materials, Op, PlaceBlock


# Defensive bounds, per spec.
_MIN = (3, 4, 3)
_MAX = (5, 12, 5)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the small-tower envelope.

    The lower corner is preserved; the upper corner is shifted to satisfy
    the size constraints.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a dovecote: cylinder shell + foundation + nesting holes +
    conical roof + flagpole + interior lantern."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # Geometry: small tower inscribed in the AABB.
    radius = max(1, min(a.w, a.d) // 2)
    cx, cz = a.cx, a.cz
    y0 = a.y0
    H = a.h
    # Reserve top courses for the conical roof: roof_h = radius + 1
    # (one stepping ring per Y plus the apex). Wall covers the rest.
    roof_h = radius + 1
    wall_h = max(2, H - roof_h)
    y_wall_top = y0 + wall_h - 1   # top course of the wall (just below roof)
    y_apex = y0 + wall_h + roof_h - 1  # apex block (single @accent)

    # 1) Hollow @primary cylinder wall, from y0 to top of wall section.
    ops.append(Cylinder(cx=cx, cz=cz, y0=y0, radius=radius,
                        height=wall_h, block="@primary", hollow=True))

    # 2) Solid @secondary foundation disc at y0 — overwrite the cylinder's
    #    bottom course with a solid disc so the base reads as a footing.
    r2 = radius * radius
    for dx in range(-radius, radius + 1):
        for dz in range(-radius, radius + 1):
            if dx * dx + dz * dz <= r2:
                ops.append(PlaceBlock(cx + dx, y0, cz + dz, "@secondary"))

    # 3) Nesting holes — punch 8-12 hay_block cells into the UPPER HALF of
    #    the wall. We pick rim cells, ordered by angle, evenly spaced. The
    #    count scales with wall height (more height ⇒ more rows of holes).
    rim_cells = _outer_ring_cells(cx, cz, radius)
    if rim_cells:
        upper_y0 = y0 + max(1, wall_h // 2)
        upper_y1 = y_wall_top  # exclusive upper bound: don't punch the top course
        # Target hole count: 8..12, clamped by how many rim cells × rows exist.
        rows = max(1, upper_y1 - upper_y0)
        n_holes = max(8, min(12, len(rim_cells)))
        # Reduce if there are very few rim cells (small towers): fall back
        # to at most one hole per rim cell per row.
        max_capacity = len(rim_cells) * rows
        n_holes = min(n_holes, max_capacity)
        # Evenly-spaced rim indices around the circle.
        step = max(1, len(rim_cells) // max(1, n_holes))
        placed = 0
        i = 0
        while placed < n_holes and i < len(rim_cells) * 2:
            (rx, rz) = rim_cells[(i * step) % len(rim_cells)]
            # Spread across available rows.
            yy = upper_y0 + (placed % rows)
            if y0 < yy <= y_wall_top:
                ops.append(PlaceBlock(rx, yy, rz, "minecraft:hay_block"))
                placed += 1
            i += 1

    # 4) Conical roof: each Y-step above the wall shrinks the ring radius
    #    by 1 until it converges to a single block. We use @stairs as the
    #    sloped roof shell and @accent as the apex.
    for k in range(1, roof_h):
        rr = max(0, radius - k)
        ry = y_wall_top + k
        if rr <= 0:
            # Final apex layer collapses to a single accent block (next step
            # places the apex explicitly).
            break
        # Ring of stairs at this radius. The facing rotates around the ring
        # so each step "faces outward" — composer keeps later-wins, and the
        # stairs block string already encodes orientation.
        ring = _outer_ring_cells(cx, cz, rr)
        for (sx, sz) in ring:
            facing = _facing_for(sx - cx, sz - cz)
            ops.append(PlaceBlock(sx, ry, sz, f"@stairs[facing={facing}]"))

    # 5) Apex: a single @accent block at the very top of the cone.
    ops.append(PlaceBlock(cx, y_apex, cz, "@accent"))

    # 6) Flagpole (optional but always present here): a fence post above
    #    the apex with a bone_block "dove" proxy crowning it.
    pole_y = y_apex + 1
    dove_y = y_apex + 2
    ops.append(PlaceBlock(cx, pole_y, cz, "@fence"))
    ops.append(PlaceBlock(cx, dove_y, cz, "minecraft:bone_block"))

    # 7) One lantern inside, hanging near the top of the wall section
    #    (below the apex) so the interior is lit at night.
    lantern_y = max(y0 + 1, y_wall_top - 1)
    ops.append(PlaceBlock(cx, lantern_y, cz, "minecraft:lantern"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────

def _outer_ring_cells(cx: int, cz: int, radius: int) -> list[tuple[int, int]]:
    """Return the unique outer-ring cells of a discrete hollow cylinder,
    ordered by angle around the center. Matches `Cylinder.compile`'s
    rim predicate so placements land exactly on the wall."""
    r = radius
    if r <= 0:
        return [(cx, cz)]
    r2_outer = r * r
    r2_inner = (r - 1) * (r - 1)
    raw: list[tuple[int, int]] = []
    for dx in range(-r, r + 1):
        for dz in range(-r, r + 1):
            d2 = dx * dx + dz * dz
            if d2 > r2_outer:
                continue
            if d2 < r2_inner:
                continue
            raw.append((dx, dz))
    raw.sort(key=lambda p: math.atan2(p[1], p[0]))
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for (dx, dz) in raw:
        cell = (cx + dx, cz + dz)
        if cell not in seen:
            seen.add(cell)
            out.append(cell)
    return out


def _facing_for(dx: int, dz: int) -> str:
    """Pick the cardinal facing for a stair block sitting at (dx, dz) on a
    ring around the center — stair faces "outward" from the center."""
    if abs(dx) >= abs(dz):
        return "east" if dx >= 0 else "west"
    return "south" if dz >= 0 else "north"
