"""Italian Campanile — tall square bell tower with arched belfry + pyramid cap.

Source: TFGv2 `tower_variety.py:87-140` (CampanileSkill).
"""
from __future__ import annotations

from ..base import AABB, FillHollow, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="campanile",
    kind="tower",
    title="Italian Campanile",
    description=(
        "Tall square bell tower with blind arcading along the shaft and an "
        "open arched belfry near the top. Capped with a low pyramid and "
        "iron-bars finial."
    ),
    style_affinities=["italian", "medieval", "renaissance", "church"],
    scale_affinities=["medium", "large", "monumental"],
    typical_footprint=(7, 36, 7),
    cost_blocks=600,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    s = min(a.w, a.d)
    cx, cz = a.cx, a.cz
    s2 = s // 2

    # Shaft (reserve top 4 blocks for cap + finial).
    shaft_top = a.y1 - 4
    shaft_aabb = AABB(cx - s2, a.y0, cz - s2,
                      cx + s2 + 1, shaft_top, cz + s2 + 1)
    ops.append(FillHollow(aabb=shaft_aabb, wall="@primary"))

    # Belfry: open arch windows on all 4 faces near the top of the shaft.
    belfry_y = shaft_top - 4
    if belfry_y > a.y0 + 1:
        for x in range(cx - s2 + 1, cx + s2):
            for yo in range(3):
                ops.append(PlaceBlock(x=x, y=belfry_y + yo, z=cz - s2,
                                      block="minecraft:air"))
                ops.append(PlaceBlock(x=x, y=belfry_y + yo, z=cz + s2,
                                      block="minecraft:air"))
        for z in range(cz - s2 + 1, cz + s2):
            for yo in range(3):
                ops.append(PlaceBlock(x=cx - s2, y=belfry_y + yo, z=z,
                                      block="minecraft:air"))
                ops.append(PlaceBlock(x=cx + s2, y=belfry_y + yo, z=z,
                                      block="minecraft:air"))
        # Central bell.
        ops.append(PlaceBlock(x=cx, y=belfry_y + 1, z=cz, block="minecraft:bell"))

    # Low pyramid cap.
    ops += _geom.pyramid_square(cx, cz, shaft_top, s2, 3, block="@accent")
    # Finial.
    ops.append(PlaceBlock(x=cx, y=shaft_top + 3, z=cz, block="minecraft:iron_bars"))
    return ops
