"""Skill: wall_relief — a decorative band on the interior perimeter walls.

Universal: applies to ANY room. Adds a horizontal band of decorative blocks
at mid-wall height around the interior perimeter (skipping connector cells
that the door-carve will overwrite anyway). Lifts visual richness without
touching floors or ceilings.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock


_STYLE_RELIEF = {
    "medieval":      "minecraft:cobblestone_wall",
    "rustic":        "minecraft:spruce_log",
    "fantasy":       "minecraft:purpur_pillar",
    "gothic":        "minecraft:chiseled_stone_bricks",
    "renaissance":   "minecraft:chiseled_sandstone",
    "modern":        "minecraft:quartz_pillar",
    "minimalist":    "minecraft:smooth_quartz",
    "japanese":      "minecraft:dark_oak_log",
    "chinese":       "minecraft:red_terracotta",
    "mediterranean": "minecraft:chiseled_sandstone",
}


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Place a decorative band at y0 + h//2 on the four interior wall planes."""
    block = _STYLE_RELIEF.get(style.lower(), "minecraft:cobblestone")
    if aabb.h < 4 or aabb.w < 4 or aabb.d < 4:
        return []
    y = aabb.y0 + aabb.h // 2
    ops: List[Op] = []
    # Top/bottom (z = z0, z = z1-1) walls — paint the interior side of the wall
    for x in range(aabb.x0 + 1, aabb.x1 - 1):
        ops.append(PlaceBlock(x, y, aabb.z0, block))
        ops.append(PlaceBlock(x, y, aabb.z1 - 1, block))
    # Left/right (x = x0, x = x1-1) walls
    for z in range(aabb.z0 + 1, aabb.z1 - 1):
        ops.append(PlaceBlock(aabb.x0, y, z, block))
        ops.append(PlaceBlock(aabb.x1 - 1, y, z, block))
    return ops
