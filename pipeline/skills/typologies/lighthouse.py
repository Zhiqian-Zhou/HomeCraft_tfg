"""Lighthouse — striped cylindrical tower with lamp room + dome cap.

Source: TFGv2 `tower_variety.py:275-322` (LighthouseSkill).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="lighthouse",
    kind="tower",
    title="Lighthouse",
    description=(
        "Cylindrical striped tower with a glowing lamp room and small dome "
        "cap. Coastal manors, harbor towns, and fantasy ports."
    ),
    style_affinities=["coastal", "modern", "fantasy_port", "victorian"],
    scale_affinities=["medium", "large"],
    typical_footprint=(9, 28, 9),
    cost_blocks=350,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    cx, cz = a.cx, a.cz
    r = max(3, min(a.w, a.d) // 2)
    h = max(10, a.h - 6)
    stripe_a = kwargs.get("stripe_a", "minecraft:white_concrete")
    stripe_b = kwargs.get("stripe_b", "minecraft:red_concrete")

    # Striped body (3-block stripes).
    for y in range(h):
        col = stripe_a if (y // 3) % 2 == 0 else stripe_b
        for (x, z) in _geom.circle_xz(cx, cz, r):
            ops.append(PlaceBlock(x=x, y=a.y0 + y, z=z, block=col))

    # Glass lamp room (2 courses).
    lamp_y = a.y0 + h
    for (x, z) in _geom.circle_xz(cx, cz, r):
        ops.append(PlaceBlock(x=x, y=lamp_y, z=z, block="minecraft:glass"))
        ops.append(PlaceBlock(x=x, y=lamp_y + 1, z=z, block="minecraft:glass"))
    # Central glow + beacon (both 1.16.5-safe).
    ops.append(PlaceBlock(x=cx, y=lamp_y, z=cz, block="minecraft:sea_lantern"))
    ops.append(PlaceBlock(x=cx, y=lamp_y + 1, z=cz, block="minecraft:beacon"))

    # Dome cap.
    ops += _geom.pyramid_square(cx, cz, lamp_y + 2, r, 3,
                                block="minecraft:smooth_stone")
    return ops
