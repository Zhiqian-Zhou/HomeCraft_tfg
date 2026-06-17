"""Watchtower — compact square tower with crenellated viewing platform.

Source: TFGv2 `tower_variety.py:329-369` (WatchtowerSkill).
"""
from __future__ import annotations

from ..base import AABB, FillHollow, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="watchtower",
    kind="tower",
    title="Watchtower",
    description=(
        "Compact square tower with an open crenellated viewing platform on "
        "top, a brazier for signaling fires, and ladder access. The "
        "frontier-keep classic."
    ),
    style_affinities=["medieval", "frontier", "fantasy", "ranger"],
    scale_affinities=["small", "medium"],
    typical_footprint=(5, 14, 5),
    cost_blocks=180,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    cx, cz = a.cx, a.cz
    s = min(a.w, a.d)
    s2 = s // 2

    # Square hollow shell.
    shell = AABB(cx - s2, a.y0, cz - s2,
                 cx + s2 + 1, a.y1, cz + s2 + 1)
    ops.append(FillHollow(aabb=shell, wall="@primary"))

    # Crenellated parapet one course above the shell top.
    parapet = AABB(cx - s2, a.y1, cz - s2,
                   cx + s2 + 1, a.y1 + 1, cz + s2 + 1)
    ops += _geom.crenellated_ring(parapet, block="@primary")

    # Brazier signal fire (1.16.5 cauldron + campfire combo).
    if kwargs.get("brazier", True):
        ops.append(PlaceBlock(x=cx, y=a.y1 - 1, z=cz, block="minecraft:cauldron"))
        ops.append(PlaceBlock(x=cx, y=a.y1, z=cz, block="minecraft:campfire"))

    return ops
