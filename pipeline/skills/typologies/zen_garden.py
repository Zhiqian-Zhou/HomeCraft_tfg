"""Zen Rock Garden — minimalist raked-sand area with stone clusters + lantern.

Source description: TFGv2 `garden.py:73-101` (ZenRockGardenSkill — stub
in original; implemented minimally here).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock, Rect
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="zen_garden",
    kind="garden",
    title="Zen Rock Garden",
    description=(
        "Minimalist Japanese garden: a flat field of white concrete (raked "
        "sand effect) with cobblestone stone clusters, bamboo stalks, and "
        "a stone lantern. Meditative low-block presence."
    ),
    style_affinities=["japanese", "modern", "minimalist", "ryokan"],
    scale_affinities=["small", "medium", "large"],
    typical_footprint=(15, 1, 15),
    cost_blocks=80,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a zen garden inside `aabb`."""
    ops: list[Op] = []
    a = aabb
    y = a.y0

    # Raked sand bed.
    bed = AABB(a.x0, y, a.z0, a.x1, y + 1, a.z1)
    ops.append(Rect(aabb=bed, block="minecraft:white_concrete", axis="y", level=y))

    # Stone clusters — deterministic by hash of position.
    stones_target = kwargs.get("stones", min(8, max(3, a.w * a.d // 30)))
    placed = 0
    for x in range(a.x0 + 2, a.x1 - 2):
        for z in range(a.z0 + 2, a.z1 - 2):
            if placed >= stones_target:
                break
            if (x * 13 + z * 7) % 17 == 0:
                ops.append(PlaceBlock(x=x, y=y + 1, z=z,
                                      block="minecraft:cobblestone"))
                # Maybe a second block stacked.
                if (x + z) % 3 == 0:
                    ops.append(PlaceBlock(x=x, y=y + 2, z=z,
                                          block="minecraft:mossy_cobblestone"))
                placed += 1

    # Bamboo stalks in two corners.
    if kwargs.get("bamboo", True):
        for cx, cz in ((a.x0 + 2, a.z0 + 2), (a.x1 - 3, a.z1 - 3)):
            for h in range(3):
                ops.append(PlaceBlock(x=cx, y=y + 1 + h, z=cz,
                                      block="minecraft:bamboo"))

    # Stone lantern at the center.
    if kwargs.get("lantern", True):
        ops.append(PlaceBlock(x=a.cx, y=y + 1, z=a.cz,
                              block="minecraft:stone_bricks"))
        ops.append(PlaceBlock(x=a.cx, y=y + 2, z=a.cz, block="@lantern"))
    return ops
