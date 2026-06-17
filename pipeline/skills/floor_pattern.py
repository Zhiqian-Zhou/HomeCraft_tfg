"""Skill: floor_pattern — a decorative floor treatment for ANY room.

Universal: works in any room of any building. Lays a style-varied pattern
across the room's floor (y0+0 layer): central rug, alternating slabs, mosaic,
or geometric border. Auto-scales to the room AABB.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock, Fill


# style → (centre_block, border_block)
_STYLE_PATTERNS = {
    "medieval":      ("minecraft:red_carpet",       "minecraft:dark_oak_planks"),
    "rustic":        ("minecraft:brown_carpet",     "minecraft:spruce_planks"),
    "fantasy":       ("minecraft:purple_carpet",    "minecraft:purpur_block"),
    "gothic":        ("minecraft:black_carpet",     "minecraft:stone_bricks"),
    "renaissance":   ("minecraft:white_carpet",     "minecraft:smooth_sandstone"),
    "modern":        ("minecraft:gray_carpet",      "minecraft:polished_andesite"),
    "minimalist":    ("minecraft:white_carpet",     "minecraft:white_concrete"),
    "japanese":      ("minecraft:white_carpet",     "minecraft:dark_oak_log"),
    "chinese":       ("minecraft:red_carpet",       "minecraft:dark_oak_planks"),
    "mediterranean": ("minecraft:lime_carpet",      "minecraft:smooth_sandstone"),
}


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Lay a central rug + perimeter border at y0 (within the room interior)."""
    centre_b, border_b = _STYLE_PATTERNS.get(style.lower(),
                                              ("minecraft:gray_carpet",
                                               "minecraft:oak_planks"))
    ops: List[Op] = []
    x0, z0 = aabb.x0 + 1, aabb.z0 + 1
    x1, z1 = aabb.x1 - 1, aabb.z1 - 1
    if x1 - x0 < 2 or z1 - z0 < 2:
        return ops
    y = aabb.y0 + 1
    # Border ring (decorative inset 1 cell from the wall)
    for x in range(x0, x1):
        ops.append(PlaceBlock(x, y, z0, border_b))
        ops.append(PlaceBlock(x, y, z1 - 1, border_b))
    for z in range(z0 + 1, z1 - 1):
        ops.append(PlaceBlock(x0, y, z, border_b))
        ops.append(PlaceBlock(x1 - 1, y, z, border_b))
    # Central rug
    if x1 - x0 > 4 and z1 - z0 > 4:
        ops.append(Fill(AABB(x0 + 1, y, z0 + 1, x1 - 1, y + 1, z1 - 1), centre_b))
    return ops
