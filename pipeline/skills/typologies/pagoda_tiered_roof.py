"""Pagoda Tiered Roof — stacked hip tiers with upturned eave corners.

Source: TFGv2 `roof_variety.py:396-462` (PagodaTieredRoofSkill).

1.17+ remap: `end_rod` cap on the spire → `@lantern` (per-style light).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="pagoda_tiered_roof",
    kind="roof",
    title="Pagoda Tiered Roof",
    description=(
        "Stacked hip tiers with deep overhangs and upturned corner blocks "
        "suggesting flying-eave tips. Asian temples, pavilions, fantasy "
        "castle crowns."
    ),
    style_affinities=["japanese", "chinese", "asian", "fantasy"],
    scale_affinities=["small", "medium", "large"],
    typical_footprint=(11, 12, 11),
    cost_blocks=350,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    tiers = kwargs.get("tiers", min(3, max(2, a.h // 3)))
    tier_h = kwargs.get("tier_h", 3)

    cur_x0, cur_z0 = a.x0, a.z0
    cur_x1, cur_z1 = a.x1 - 1, a.z1 - 1

    for i in range(tiers):
        ex0, ez0 = cur_x0 - 1, cur_z0 - 1
        ex1, ez1 = cur_x1 + 1, cur_z1 + 1
        ey = a.y0 + i * tier_h
        # Eave overhang (1-block-wider perimeter).
        for x in range(ex0, ex1 + 1):
            ops.append(PlaceBlock(x=x, y=ey, z=ez0,
                                  block="@stairs[facing=north]"))
            ops.append(PlaceBlock(x=x, y=ey, z=ez1,
                                  block="@stairs[facing=south]"))
        for z in range(ez0 + 1, ez1):
            ops.append(PlaceBlock(x=ex0, y=ey, z=z,
                                  block="@stairs[facing=west]"))
            ops.append(PlaceBlock(x=ex1, y=ey, z=z,
                                  block="@stairs[facing=east]"))
        # Upturned corner tips.
        for cx_o, cz_o in ((ex0, ez0), (ex0, ez1), (ex1, ez0), (ex1, ez1)):
            ops.append(PlaceBlock(x=cx_o, y=ey + 1, z=cz_o, block="@stairs"))
        # Accent body course.
        for x in range(cur_x0, cur_x1 + 1):
            for z in range(cur_z0, cur_z1 + 1):
                if x in (cur_x0, cur_x1) or z in (cur_z0, cur_z1):
                    ops.append(PlaceBlock(x=x, y=ey + 1, z=z, block="@accent"))
        # Shrink for next tier.
        cur_x0 += 1; cur_z0 += 1; cur_x1 -= 1; cur_z1 -= 1
        if cur_x0 >= cur_x1 or cur_z0 >= cur_z1:
            break

    # Central spire.
    ops += _geom.conical_spire(
        a.cx, a.cz, a.y0 + tiers * tier_h, 2, 5,
        block="@fence", cap_block="@lantern",
    )
    return ops
