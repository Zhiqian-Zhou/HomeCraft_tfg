"""Flat Parapet Roof — horizontal deck with optional crenellated parapet.

Source: TFGv2 `roof_variety.py:342-389` (FlatParapetRoofSkill).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock, Rect
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="flat_parapet_roof",
    kind="roof",
    title="Flat Roof with Crenellated Parapet",
    description=(
        "Horizontal roof deck plus a raised parapet border, optionally "
        "crenellated for a fortress feel. Castles, fortresses, Pueblo, "
        "and modern flat-roofed buildings."
    ),
    style_affinities=["castle", "fortress", "modern", "pueblo",
                      "mediterranean"],
    scale_affinities=["medium", "large", "monumental"],
    typical_footprint=(12, 3, 12),
    cost_blocks=160,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    ph = kwargs.get("parapet_h", min(2, max(1, a.h - 1)))
    crenellate = kwargs.get("crenellate", True)

    # Roof deck — single slab plane at y == y0.
    deck = AABB(a.x0, a.y0, a.z0, a.x1, a.y0 + 1, a.z1)
    ops.append(Rect(aabb=deck, block="@slab", axis="y", level=a.y0))

    # Parapet walls (excluding the top course if crenellating).
    parapet_courses = ph - (1 if crenellate else 0)
    for yo in range(parapet_courses):
        y = a.y0 + 1 + yo
        for x in range(a.x0, a.x1):
            ops.append(PlaceBlock(x=x, y=y, z=a.z0,         block="@primary"))
            ops.append(PlaceBlock(x=x, y=y, z=a.z1 - 1,     block="@primary"))
        for z in range(a.z0 + 1, a.z1 - 1):
            ops.append(PlaceBlock(x=a.x0,     y=y, z=z, block="@primary"))
            ops.append(PlaceBlock(x=a.x1 - 1, y=y, z=z, block="@primary"))

    # Crenellated top course.
    if crenellate:
        top = AABB(a.x0, a.y0 + ph, a.z0, a.x1, a.y0 + ph + 1, a.z1)
        ops += _geom.crenellated_ring(top, block="@primary")
    return ops
