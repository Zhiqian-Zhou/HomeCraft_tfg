"""Gambrel Roof — American barn / Dutch colonial two-pitch gable.

Source: TFGv2 `roof_variety.py:244-298` (GambrelRoofSkill).

Like a mansard but only on the two long sides — a gable form with steep
lower slope and shallow upper slope, leaving the short ends as gable
triangles (filled with @primary).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="gambrel_roof",
    kind="roof",
    title="Gambrel Barn Roof",
    description=(
        "Two-pitch gable (like a mansard but only on 2 sides) — steep "
        "lower flank + shallow upper. The classic American barn / Dutch "
        "colonial silhouette."
    ),
    style_affinities=["farmhouse", "dutch_colonial", "rural", "barn"],
    scale_affinities=["medium", "large"],
    typical_footprint=(12, 8, 10),
    cost_blocks=240,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    center_z = (a.z0 + a.z1 - 1) // 2
    half = max(1, (a.z1 - 1 - a.z0) // 2)
    steep = max(1, half // 2)
    shallow = max(1, half - steep)

    # Lower steep (sloping in z).
    for level in range(steep):
        for x in range(a.x0, a.x1):
            ops.append(PlaceBlock(x=x, y=a.y0 + level,
                                  z=center_z - half + level,
                                  block="@stairs[facing=north]"))
            ops.append(PlaceBlock(x=x, y=a.y0 + level,
                                  z=center_z + half - level,
                                  block="@stairs[facing=south]"))

    # Upper shallow.
    for level in range(shallow + 1):
        cz_l = center_z - half + steep + (level // 2)
        cz_r = center_z + half - steep - (level // 2)
        yy = a.y0 + steep + level
        if cz_l >= center_z:
            for x in range(a.x0, a.x1):
                ops.append(PlaceBlock(x=x, y=yy, z=center_z, block="@primary"))
            break
        for x in range(a.x0, a.x1):
            ops.append(PlaceBlock(x=x, y=yy, z=cz_l,
                                  block="@stairs[facing=north]"))
            ops.append(PlaceBlock(x=x, y=yy, z=cz_r,
                                  block="@stairs[facing=south]"))
    return ops
