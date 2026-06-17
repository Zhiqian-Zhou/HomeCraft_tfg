"""Hip Roof — 4-slope roof tapering to a central ridge or apex.

Source: TFGv2 `roof_variety.py:116-164` (HipRoofSkillV2).

Every wall slopes inward at each level; the slopes either meet at a
single apex (for square footprints) or at a short ridge along the longer
axis (for rectangular ones). Uses `@stairs[facing=...]` for the slope faces.
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="hip_roof",
    kind="roof",
    title="Hip Roof",
    description=(
        "4-slope hip roof — every wall has a slope, meeting at a central "
        "ridge or apex. The defining roof of Mediterranean villas, "
        "Japanese houses, and suburban ranch homes."
    ),
    style_affinities=["mediterranean", "japanese", "suburban", "ranch",
                      "renaissance"],
    scale_affinities=["small", "medium", "large"],
    typical_footprint=(12, 5, 12),
    cost_blocks=240,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    pitch = kwargs.get("pitch", min(a.h, max(1, min(a.w, a.d) // 2)))

    for level in range(pitch + 1):
        sx0, sx1 = a.x0 + level, a.x1 - 1 - level
        sz0, sz1 = a.z0 + level, a.z1 - 1 - level
        if sx0 > sx1 or sz0 > sz1:
            ops.append(PlaceBlock(x=a.cx, y=a.y0 + level, z=a.cz,
                                  block="@stairs"))
            continue
        for x in range(sx0, sx1 + 1):
            ops.append(PlaceBlock(x=x, y=a.y0 + level, z=sz0,
                                  block="@stairs[facing=north]"))
            ops.append(PlaceBlock(x=x, y=a.y0 + level, z=sz1,
                                  block="@stairs[facing=south]"))
        for z in range(sz0 + 1, sz1):
            ops.append(PlaceBlock(x=sx0, y=a.y0 + level, z=z,
                                  block="@stairs[facing=west]"))
            ops.append(PlaceBlock(x=sx1, y=a.y0 + level, z=z,
                                  block="@stairs[facing=east]"))
    return ops
