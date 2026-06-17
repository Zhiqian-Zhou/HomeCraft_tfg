"""Castle Inner Courtyard — paved bailey with central well + banners.

Source description: TFGv2 `garden.py:134-160` (CastleCourtyardSkill —
stub in original; implemented minimally here).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock, Rect
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="castle_courtyard",
    kind="garden",
    title="Castle Inner Courtyard",
    description=(
        "Enclosed castle bailey inside the curtain walls: stone-paved "
        "floor, central well, occasional banner, and (optionally) one "
        "training armor stand. Working military / residential courtyard, "
        "not a garden."
    ),
    style_affinities=["castle", "medieval", "fortified", "gothic"],
    scale_affinities=["large", "monumental"],
    typical_footprint=(20, 1, 20),
    cost_blocks=300,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a castle courtyard inside `aabb`."""
    ops: list[Op] = []
    a = aabb
    y = a.y0

    # Cobblestone pavement.
    floor = AABB(a.x0, y, a.z0, a.x1, y + 1, a.z1)
    ops.append(Rect(aabb=floor, block="minecraft:cobblestone", axis="y", level=y))

    # Central well — 3x3 stone-bricks ring with a water core.
    if kwargs.get("well", True):
        cx, cz = a.cx, a.cz
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dz == 0:
                    continue
                ops.append(PlaceBlock(x=cx + dx, y=y + 1, z=cz + dz,
                                      block="minecraft:stone_bricks"))
        # Water core + bucket-style raised post.
        ops.append(PlaceBlock(x=cx, y=y + 1, z=cz, block="minecraft:water"))
        ops.append(PlaceBlock(x=cx - 1, y=y + 2, z=cz, block="minecraft:oak_fence"))
        ops.append(PlaceBlock(x=cx + 1, y=y + 2, z=cz, block="minecraft:oak_fence"))
        ops.append(PlaceBlock(x=cx, y=y + 2, z=cz, block="minecraft:dark_oak_slab"))

    # Wall banners (1.16.5-safe red wool blocks as proxy — actual banners
    # need entity data the composer doesn't emit).
    banners = kwargs.get("banners", 4)
    placed = 0
    for x in range(a.x0 + 2, a.x1 - 2, 4):
        if placed >= banners:
            break
        ops.append(PlaceBlock(x=x, y=y + 2, z=a.z0, block="minecraft:red_wool"))
        placed += 1

    return ops
