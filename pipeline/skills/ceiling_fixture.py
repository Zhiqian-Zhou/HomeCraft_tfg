"""Skill: ceiling_fixture — a hanging lantern grid + decorative beams.

Universal: applies to ANY room of ANY building tall enough (h ≥ 5). Adds
crossing oak/dark_oak/stone log beams on the ceiling + suspended lanterns
at intersections. Lifts `light_coverage` and visual richness.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Line, Materials, Op, PlaceBlock


_STYLE_BEAM = {
    "medieval":      ("minecraft:dark_oak_log",     "minecraft:lantern"),
    "rustic":        ("minecraft:spruce_log",        "minecraft:lantern"),
    "fantasy":       ("minecraft:purpur_pillar",     "minecraft:soul_lantern"),
    "gothic":        ("minecraft:dark_oak_log",      "minecraft:lantern"),
    "renaissance":   ("minecraft:oak_log",           "minecraft:lantern"),
    "modern":        ("minecraft:smooth_stone",      "minecraft:sea_lantern"),
    "minimalist":    ("minecraft:smooth_stone",      "minecraft:sea_lantern"),
    "japanese":      ("minecraft:dark_oak_log",      "minecraft:lantern"),
    "chinese":       ("minecraft:dark_oak_log",      "minecraft:lantern"),
    "mediterranean": ("minecraft:oak_log",           "minecraft:lantern"),
}


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Cross-beams under the ceiling + suspended lanterns on a 4-cell grid."""
    beam, lantern = _STYLE_BEAM.get(style.lower(),
                                      ("minecraft:oak_log",
                                       "minecraft:lantern"))
    cx_fallback = (aabb.x0 + aabb.x1 - 1) // 2
    cz_fallback = (aabb.z0 + aabb.z1 - 1) // 2
    if aabb.h < 5 or aabb.w < 5 or aabb.d < 5:
        # Tiny room → just one ceiling lantern at centre (always returns ≥1 op).
        return [PlaceBlock(cx_fallback, max(aabb.y0, aabb.y1 - 2),
                            cz_fallback, lantern)]
    y_beam = aabb.y1 - 2
    ops: List[Op] = []
    # Cross beam along x at z = centre
    cz = (aabb.z0 + aabb.z1 - 1) // 2
    ops.append(Line(aabb.x0 + 1, y_beam, cz,
                     aabb.x1 - 2, y_beam, cz, beam))
    # Cross beam along z at x = centre
    cx = (aabb.x0 + aabb.x1 - 1) // 2
    ops.append(Line(cx, y_beam, aabb.z0 + 1,
                     cx, y_beam, aabb.z1 - 2, beam))
    # Lantern at the intersection (one cell below the beam, in air)
    ops.append(PlaceBlock(cx, y_beam - 1, cz, lantern))
    # Additional lanterns on a 4-cell grid (skip the centre we already did)
    for x in range(aabb.x0 + 2, aabb.x1 - 2, 4):
        for z in range(aabb.z0 + 2, aabb.z1 - 2, 4):
            if (x, z) == (cx, cz):
                continue
            ops.append(PlaceBlock(x, y_beam - 1, z, lantern))
    return ops
