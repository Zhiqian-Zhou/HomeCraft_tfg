"""Civic Clock Tower — tall square tower with clock face + steep pyramid roof.

Source: TFGv2 `tower_variety.py:376-425` (ClockTowerSkill).

1.17+ remap: roof was `deepslate_tile_stairs` → `@stairs` (per-style stair).
"""
from __future__ import annotations

from ..base import AABB, FillHollow, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="clock_tower",
    kind="tower",
    title="Civic Clock Tower",
    description=(
        "Tall square tower with a quartz clock face panel at 2/3 height, a "
        "steep pyramidal roof, and an iron-bars + lantern finial. Civic "
        "centers, town squares, victorian universities."
    ),
    style_affinities=["victorian", "civic", "georgian", "mediterranean"],
    scale_affinities=["medium", "large"],
    typical_footprint=(7, 30, 7),
    cost_blocks=400,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    cx, cz = a.cx, a.cz
    s = min(a.w, a.d)
    s2 = s // 2
    # Reserve top for pyramid + finial.
    shaft_top = a.y1 - 8 if a.h > 14 else max(a.y0 + 6, a.y1 - 4)

    shell = AABB(cx - s2, a.y0, cz - s2,
                 cx + s2 + 1, shaft_top, cz + s2 + 1)
    ops.append(FillHollow(aabb=shell, wall="@primary"))

    # Clock face on the south face at 2/3 height.
    clock_y = a.y0 + (shaft_top - a.y0) * 2 // 3
    for dx in range(-1, 2):
        for dy in range(-1, 2):
            ops.append(PlaceBlock(x=cx + dx, y=clock_y + dy, z=cz - s2,
                                  block="minecraft:quartz_block"))
    ops.append(PlaceBlock(x=cx, y=clock_y, z=cz - s2,
                          block="minecraft:coal_block"))  # hands

    # Steep pyramid roof — uses @stairs (per-style) not the deepslate of TFGv2.
    ops += _geom.pyramid_square(cx, cz, shaft_top, s2 + 1, 6, block="@stairs")
    # Finial.
    ops.append(PlaceBlock(x=cx, y=shaft_top + 6, z=cz, block="minecraft:iron_bars"))
    ops.append(PlaceBlock(x=cx, y=shaft_top + 7, z=cz, block="@lantern"))
    return ops
