"""Skill: corner_accent — decorative vertical accents at room corners.

Universal: applies to ANY room of ANY building. Places 4 style-varied
elements at the four interior corners. Helps with `intimacy_gradient` and
visual richness.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock


_STYLE_CORNER = {
    "medieval":      ("minecraft:cobblestone_wall",  3),
    "rustic":        ("minecraft:oak_fence",          3),
    "fantasy":       ("minecraft:purpur_pillar",      4),
    "gothic":        ("minecraft:chiseled_stone_bricks", 4),
    "renaissance":   ("minecraft:smooth_sandstone",   4),
    "modern":        ("minecraft:smooth_quartz",      3),
    "minimalist":    ("minecraft:white_concrete",     3),
    "japanese":      ("minecraft:dark_oak_log",       4),
    "chinese":       ("minecraft:red_concrete",       4),
    "mediterranean": ("minecraft:smooth_sandstone",   3),
}


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Stack a 3-4 block accent at each of the 4 interior corners."""
    block, height = _STYLE_CORNER.get(style.lower(),
                                        ("minecraft:cobblestone_wall", 3))
    if aabb.w < 4 or aabb.d < 4 or aabb.h < height + 1:
        # Tiny room → one accent block in one corner so the skill always
        # returns ≥1 op (harness contract).
        return [PlaceBlock(aabb.x0, aabb.y0 + 1, aabb.z0, block)]
    corners = [
        (aabb.x0 + 1, aabb.z0 + 1),
        (aabb.x1 - 2, aabb.z0 + 1),
        (aabb.x0 + 1, aabb.z1 - 2),
        (aabb.x1 - 2, aabb.z1 - 2),
    ]
    ops: List[Op] = []
    for (cx, cz) in corners:
        for k in range(height):
            ops.append(PlaceBlock(cx, aabb.y0 + 1 + k, cz, block))
    return ops
