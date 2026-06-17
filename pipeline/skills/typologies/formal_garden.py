"""Formal Hedge Garden — geometric parterre with central path + fountain.

Source description: TFGv2 `garden.py:42-70` (FormalHedgeGardenSkill — stub
in original; implemented minimally here).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock, Rect
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="formal_garden",
    kind="garden",
    title="Formal Hedge Garden (Parterre)",
    description=(
        "Symmetric geometric garden — leaf-block hedges trimmed to a "
        "uniform 1-block height, central gravel path, fountain at the "
        "axis crossing. Georgian / Victorian / French mansion grounds."
    ),
    style_affinities=["georgian", "victorian", "french", "mansion",
                      "mediterranean", "renaissance"],
    scale_affinities=["medium", "large", "monumental"],
    typical_footprint=(20, 1, 20),
    cost_blocks=240,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a parterre filling `aabb`. Hedges + gravel paths + fountain."""
    ops: list[Op] = []
    a = aabb
    y = a.y0
    cx, cz = a.cx, a.cz

    # Grass base.
    bed = AABB(a.x0, y, a.z0, a.x1, y + 1, a.z1)
    ops.append(Rect(aabb=bed, block="minecraft:grass_block", axis="y", level=y))

    # Cross-shaped gravel path through the center (1 block wide).
    for x in range(a.x0, a.x1):
        ops.append(PlaceBlock(x=x, y=y, z=cz, block="minecraft:gravel"))
    for z in range(a.z0, a.z1):
        ops.append(PlaceBlock(x=cx, y=y, z=z, block="minecraft:gravel"))

    # Hedge perimeter (oak_leaves), 1-block tall.
    for x in range(a.x0, a.x1):
        if x != cx:  # leave path entry open at midpoints
            ops.append(PlaceBlock(x=x, y=y + 1, z=a.z0,     block="minecraft:oak_leaves"))
            ops.append(PlaceBlock(x=x, y=y + 1, z=a.z1 - 1, block="minecraft:oak_leaves"))
    for z in range(a.z0 + 1, a.z1 - 1):
        if z != cz:
            ops.append(PlaceBlock(x=a.x0,     y=y + 1, z=z, block="minecraft:oak_leaves"))
            ops.append(PlaceBlock(x=a.x1 - 1, y=y + 1, z=z, block="minecraft:oak_leaves"))

    # Inner hedge quadrants — small L-shapes in each corner of the cross.
    for sx, sz in ((-3, -3), (3, -3), (-3, 3), (3, 3)):
        bx, bz = cx + sx, cz + sz
        if a.x0 <= bx < a.x1 and a.z0 <= bz < a.z1:
            for dxz in (-1, 0, 1):
                if a.x0 <= bx + dxz < a.x1:
                    ops.append(PlaceBlock(x=bx + dxz, y=y + 1, z=bz,
                                          block="minecraft:oak_leaves"))
                if a.z0 <= bz + dxz < a.z1:
                    ops.append(PlaceBlock(x=bx, y=y + 1, z=bz + dxz,
                                          block="minecraft:oak_leaves"))

    # Central fountain — stone bricks ring + water cell.
    if kwargs.get("fountain", True):
        for dxz in (-1, 1):
            ops.append(PlaceBlock(x=cx + dxz, y=y + 1, z=cz,
                                  block="minecraft:stone_bricks"))
            ops.append(PlaceBlock(x=cx, y=y + 1, z=cz + dxz,
                                  block="minecraft:stone_bricks"))
        ops.append(PlaceBlock(x=cx, y=y + 1, z=cz, block="minecraft:water"))
    return ops
