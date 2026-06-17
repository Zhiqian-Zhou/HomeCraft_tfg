"""Skill: gabled_roof — a two-pitch (a dos aguas) roof.

The AABB defines the BASE of the roof. The roof rises ABOVE the AABB by
`floor(min(W, D) / 2)` levels until reaching the ridge (peak).

Geometry per layer y_off in [0, peak]:
    ridge along the long axis (default = longer of W vs D; overridable
    with the `ridge_axis` kwarg, 'x' or 'z'). At each layer above the
    base, the roof contracts one block on each side perpendicular to
    the ridge axis. The two long edges of every layer are pitched
    stair blocks facing inward toward the ridge. The interior between
    the two stair rows is air (hollow attic). The ridge top course (and
    the layer just below the apex, when min(W,D) is even) is filled
    with solid @roof blocks. The two short ends (gable walls) are filled
    vertically with @accent for the triangular infill.

The skill is defensive on small AABBs (4x?x4) up to 16x?x20: it computes
its own height from min(W, D); the caller does NOT have to size the
AABB's height. The roof voxels extend ABOVE aabb.y1 — the composer
computes the final bounding box from the actual voxel coordinates.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Emit ops for a gabled (two-pitch) roof sitting on top of `aabb`.

    Kwargs:
        ridge_axis ('x' | 'z'): direction the ridge runs along. Default
            is the longer of the two horizontal axes (W vs D); ties
            break to 'x'.
    """
    w, d = aabb.w, aabb.d

    # Defensive on tiny footprints.
    if w < 2 or d < 2:
        return []

    # Pick ridge axis: default = the longer horizontal side; kwarg overrides.
    ridge_axis = kwargs.get("ridge_axis")
    if ridge_axis not in ("x", "z"):
        ridge_axis = "x" if w >= d else "z"

    # Peak height — measured from the BASE layer (y_off = 0) of the roof.
    # The "short" dimension (perpendicular to the ridge) decides the peak.
    short = d if ridge_axis == "x" else w
    peak = short // 2  # floor(min(W, D) / 2)
    if peak < 1:
        # Footprint too narrow for even one slope course; emit a flat cap.
        return _flat_cap(aabb)

    ops: List[Op] = []
    y_base = aabb.y1  # roof base layer sits immediately above the AABB top

    if ridge_axis == "x":
        ops.extend(_build_x_ridge(aabb, y_base, peak))
    else:
        ops.extend(_build_z_ridge(aabb, y_base, peak))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Ridge along X — pitches face north (-z) and south (+z)
# ────────────────────────────────────────────────────────────────────────

def _build_x_ridge(aabb: AABB, y_base: int, peak: int) -> List[Op]:
    ops: List[Op] = []
    x0, x1 = aabb.x0, aabb.x1
    z0, z1 = aabb.z0, aabb.z1

    for y_off in range(peak + 1):
        y = y_base + y_off
        z_lo = z0 + y_off          # north edge of this layer
        z_hi = z1 - 1 - y_off       # south edge of this layer
        if z_lo > z_hi:
            break

        if z_lo == z_hi:
            # Single-block-wide ridge — solid roof course.
            for x in range(x0, x1):
                ops.append(PlaceBlock(x, y, z_lo, "@roof"))
        elif z_lo + 1 == z_hi:
            # Two-wide apex (even short side) — solid course.
            for x in range(x0, x1):
                ops.append(PlaceBlock(x, y, z_lo, "@roof"))
                ops.append(PlaceBlock(x, y, z_hi, "@roof"))
        else:
            # Pitched edges: stairs face inward toward the ridge.
            for x in range(x0, x1):
                # North edge stair faces south (slope rises toward ridge).
                ops.append(PlaceBlock(x, y, z_lo, "@stairs[facing=south]"))
                # South edge stair faces north.
                ops.append(PlaceBlock(x, y, z_hi, "@stairs[facing=north]"))
            # Interior of the layer (between the two stair rows) stays air.

        # Gable infill — vertical triangular walls at the two short ends.
        # Place AFTER stairs so later-wins replaces the gable-end stairs
        # with a solid accent block (the gable wall is a vertical infill).
        for z in range(z_lo, z_hi + 1):
            ops.append(PlaceBlock(x0,     y, z, "@accent"))
            ops.append(PlaceBlock(x1 - 1, y, z, "@accent"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Ridge along Z — pitches face west (-x) and east (+x)
# ────────────────────────────────────────────────────────────────────────

def _build_z_ridge(aabb: AABB, y_base: int, peak: int) -> List[Op]:
    ops: List[Op] = []
    x0, x1 = aabb.x0, aabb.x1
    z0, z1 = aabb.z0, aabb.z1

    for y_off in range(peak + 1):
        y = y_base + y_off
        x_lo = x0 + y_off          # west edge of this layer
        x_hi = x1 - 1 - y_off       # east edge of this layer
        if x_lo > x_hi:
            break

        if x_lo == x_hi:
            for z in range(z0, z1):
                ops.append(PlaceBlock(x_lo, y, z, "@roof"))
        elif x_lo + 1 == x_hi:
            for z in range(z0, z1):
                ops.append(PlaceBlock(x_lo, y, z, "@roof"))
                ops.append(PlaceBlock(x_hi, y, z, "@roof"))
        else:
            for z in range(z0, z1):
                # West edge stair faces east; east edge stair faces west.
                ops.append(PlaceBlock(x_lo, y, z, "@stairs[facing=east]"))
                ops.append(PlaceBlock(x_hi, y, z, "@stairs[facing=west]"))

        # Gable infill at the two short ends (z = z0 and z = z1-1).
        for x in range(x_lo, x_hi + 1):
            ops.append(PlaceBlock(x, y, z0,     "@accent"))
            ops.append(PlaceBlock(x, y, z1 - 1, "@accent"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Degenerate fallback
# ────────────────────────────────────────────────────────────────────────

def _flat_cap(aabb: AABB) -> List[Op]:
    """For footprints too narrow to pitch, emit a single flat @roof course."""
    ops: List[Op] = []
    y = aabb.y1
    for x in range(aabb.x0, aabb.x1):
        for z in range(aabb.z0, aabb.z1):
            ops.append(PlaceBlock(x, y, z, "@roof"))
    return ops
