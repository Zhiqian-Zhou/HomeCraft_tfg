"""Tuscan Courtyard — terracotta-tiled patio with cypresses + fountain.

Source description: TFGv2 `garden.py:103-131` (TuscanCourtyardSkill —
stub in original; implemented minimally here).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock, Rect
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="tuscan_courtyard",
    kind="garden",
    title="Tuscan Courtyard",
    description=(
        "Mediterranean villa courtyard: terracotta-tiled patio bordered by "
        "low stone walls, dark cypress-style trees, and a central fountain. "
        "Architectural rather than wild."
    ),
    style_affinities=["mediterranean", "tuscan", "spanish", "italian",
                      "villa", "renaissance"],
    scale_affinities=["medium", "large", "monumental"],
    typical_footprint=(15, 1, 15),
    cost_blocks=180,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a Tuscan courtyard inside `aabb`."""
    ops: list[Op] = []
    a = aabb
    y = a.y0

    # Terracotta tile floor.
    floor = AABB(a.x0, y, a.z0, a.x1, y + 1, a.z1)
    ops.append(Rect(aabb=floor, block="minecraft:terracotta", axis="y", level=y))

    # Low stone perimeter wall (1 block tall, with gaps at the midpoints).
    cx, cz = a.cx, a.cz
    for x in range(a.x0, a.x1):
        if x != cx:
            ops.append(PlaceBlock(x=x, y=y + 1, z=a.z0,     block="minecraft:smooth_stone"))
            ops.append(PlaceBlock(x=x, y=y + 1, z=a.z1 - 1, block="minecraft:smooth_stone"))
    for z in range(a.z0 + 1, a.z1 - 1):
        if z != cz:
            ops.append(PlaceBlock(x=a.x0,     y=y + 1, z=z, block="minecraft:smooth_stone"))
            ops.append(PlaceBlock(x=a.x1 - 1, y=y + 1, z=z, block="minecraft:smooth_stone"))

    # Cypress trees at the 4 inner corners (dark_oak log with sparse leaves).
    for sx, sz in ((-3, -3), (3, -3), (-3, 3), (3, 3)):
        tx, tz = cx + sx, cz + sz
        if a.x0 < tx < a.x1 - 1 and a.z0 < tz < a.z1 - 1:
            for h in range(4):
                ops.append(PlaceBlock(x=tx, y=y + 1 + h, z=tz,
                                      block="minecraft:dark_oak_log"))
            # Sparse leaf top.
            ops.append(PlaceBlock(x=tx, y=y + 5, z=tz,
                                  block="minecraft:dark_oak_leaves"))

    # Central fountain.
    if kwargs.get("fountain", True):
        for dxz in (-1, 1):
            ops.append(PlaceBlock(x=cx + dxz, y=y + 1, z=cz,
                                  block="minecraft:smooth_stone"))
            ops.append(PlaceBlock(x=cx, y=y + 1, z=cz + dxz,
                                  block="minecraft:smooth_stone"))
        ops.append(PlaceBlock(x=cx, y=y + 1, z=cz, block="minecraft:water"))
    return ops
