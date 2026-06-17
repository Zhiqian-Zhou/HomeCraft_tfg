"""Cross-Gable Roof — two perpendicular gables crossing at the center.

Source: TFGv2 `roof_variety.py:469-525` (CrossGableRoofSkill).

Produces a + shape: gable A runs along x (sloping in z), gable B runs
along z (sloping in x). Where they cross at the apex, full blocks close
the seam.
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="cross_gable_roof",
    kind="roof",
    title="Cross-Gable Roof",
    description=(
        "Two perpendicular gables intersecting at the center, forming 4 "
        "valleys where they meet. Defines Tudor manors, Victorian houses, "
        "and Gothic cottages."
    ),
    style_affinities=["tudor", "victorian", "gothic", "manor"],
    scale_affinities=["medium", "large"],
    typical_footprint=(14, 6, 14),
    cost_blocks=380,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    half = min(a.w, a.d) // 2
    pitch = kwargs.get("pitch", min(a.h, max(2, half)))
    cx, cz = (a.x0 + a.x1 - 1) // 2, (a.z0 + a.z1 - 1) // 2

    for level in range(pitch + 1):
        # Gable A: along x, sloping in z.
        for x in range(a.x0, a.x1):
            lz = a.z0 + level
            rz = a.z1 - 1 - level
            if level < pitch:
                ops.append(PlaceBlock(x=x, y=a.y0 + level, z=lz,
                                      block="@stairs[facing=north]"))
                ops.append(PlaceBlock(x=x, y=a.y0 + level, z=rz,
                                      block="@stairs[facing=south]"))
            else:
                ops.append(PlaceBlock(x=x, y=a.y0 + level, z=cz,
                                      block="@primary"))
        # Gable B: along z, sloping in x.
        for z in range(a.z0, a.z1):
            lx = a.x0 + level
            rx = a.x1 - 1 - level
            if level < pitch:
                ops.append(PlaceBlock(x=lx, y=a.y0 + level, z=z,
                                      block="@stairs[facing=west]"))
                ops.append(PlaceBlock(x=rx, y=a.y0 + level, z=z,
                                      block="@stairs[facing=east]"))
            else:
                ops.append(PlaceBlock(x=cx, y=a.y0 + level, z=z,
                                      block="@primary"))
    return ops
