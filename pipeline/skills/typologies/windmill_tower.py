"""Tower Windmill — cylindrical body with pyramid cap + 4 fence-and-wool sails.

Source: TFGv2 `tower_variety.py:496-544` (WindmillTowerSkill).
"""
from __future__ import annotations

from ..base import AABB, Cylinder, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="windmill_tower",
    kind="tower",
    title="Tower Windmill",
    description=(
        "Cylindrical stone body with a wooden conical cap and four "
        "fence-and-wool sails radiating from the cap. The classic "
        "Dutch / rural / farmhouse silhouette."
    ),
    style_affinities=["dutch", "rural", "farmhouse", "medieval"],
    scale_affinities=["medium", "large"],
    typical_footprint=(9, 20, 9),
    cost_blocks=380,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    cx, cz = a.cx, a.cz
    r = max(3, min(a.w, a.d) // 2)
    h = max(10, a.h - 4)

    # Cylindrical body.
    ops.append(Cylinder(cx=cx, cz=cz, y0=a.y0, radius=r, height=h,
                        block="@primary", hollow=True))
    # Cap (small pyramid).
    ops += _geom.pyramid_square(cx, cz, a.y0 + h, r - 1, 3, block="@stairs")

    # Four sails — fence arms + wool fabric perpendicular.
    sail_y = a.y0 + h
    for arm_dx, arm_dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        perp_dx, perp_dz = arm_dz, -arm_dx
        for d in range(1, 6):
            ops.append(PlaceBlock(
                x=cx + arm_dx * d, y=sail_y, z=cz + arm_dz * d,
                block="minecraft:spruce_fence",
            ))
            if 1 < d < 5:
                ops.append(PlaceBlock(
                    x=cx + arm_dx * d + perp_dx, y=sail_y,
                    z=cz + arm_dz * d + perp_dz,
                    block="minecraft:white_wool",
                ))
    return ops
