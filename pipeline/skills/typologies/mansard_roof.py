"""Mansard Roof — steep French two-pitch roof, lower skirt + shallow upper.

Source: TFGv2 `roof_variety.py:171-237` (MansardRoofSkill).

1.17+ remap: `deepslate_tile_stairs` → `@stairs` (per-style stair block).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="mansard_roof",
    kind="roof",
    title="Mansard Roof",
    description=(
        "Two-pitch French roof: steep lower skirt + shallow upper hip. "
        "Maximizes attic space; the defining roof of Second Empire and "
        "Victorian mansions."
    ),
    style_affinities=["french", "victorian", "mansion", "chateau"],
    scale_affinities=["medium", "large", "monumental"],
    typical_footprint=(14, 7, 14),
    cost_blocks=320,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    lp = kwargs.get("lower_pitch", min(3, a.h // 2))
    up = kwargs.get("upper_pitch", min(2, max(1, a.h - lp - 1)))

    # Lower steep skirt — 4 sloped walls.
    for level in range(lp):
        sx0, sx1 = a.x0 + level, a.x1 - 1 - level
        sz0, sz1 = a.z0 + level, a.z1 - 1 - level
        if sx0 > sx1 or sz0 > sz1:
            break
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

    # Break course — accent perimeter at the transition.
    sx0, sx1 = a.x0 + lp, a.x1 - 1 - lp
    sz0, sz1 = a.z0 + lp, a.z1 - 1 - lp
    for x in range(sx0, sx1 + 1):
        for z in range(sz0, sz1 + 1):
            if x in (sx0, sx1) or z in (sz0, sz1):
                ops.append(PlaceBlock(x=x, y=a.y0 + lp, z=z, block="@accent"))

    # Upper shallow hip.
    for i in range(up + 1):
        ux0, ux1 = sx0 + i, sx1 - i
        uz0, uz1 = sz0 + i, sz1 - i
        if ux0 > ux1 or uz0 > uz1:
            ops.append(PlaceBlock(x=a.cx, y=a.y0 + lp + 1 + i, z=a.cz,
                                  block="@stairs"))
            continue
        for x in range(ux0, ux1 + 1):
            for z in range(uz0, uz1 + 1):
                if x in (ux0, ux1) or z in (uz0, uz1):
                    ops.append(PlaceBlock(x=x, y=a.y0 + lp + 1 + i, z=z,
                                          block="@stairs"))
    return ops
