"""Pagoda Tower — multi-tier asian tower with upturned eaves.

Source: TFGv2 `tower_variety.py:147-215` (PagodaTowerSkill).

Each tier is a smaller hollow square body with a deep eave overhang, an
accent band at the body bottom, and raised corner blocks for the upturned
"flying-eave" tips. Crowned by a sorin-style finial built from trim blocks.

1.17+ remap: original used `end_rod` for the finial cap; here mapped to
`@lantern` which resolves to a 1.16.5-safe block per style.
"""
from __future__ import annotations

from ..base import AABB, FillHollow, Materials, Op, PlaceBlock, Rect
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="pagoda_tower",
    kind="tower",
    title="Pagoda Tower",
    description=(
        "Multi-tiered pagoda — each tier shrinks inward with a wider eave "
        "overhang. Corner blocks raise to suggest upturned tips. Crowned "
        "with a tall sorin-style spire."
    ),
    style_affinities=["japanese", "chinese", "asian", "fantasy_temple"],
    scale_affinities=["medium", "large", "monumental"],
    typical_footprint=(13, 30, 13),
    cost_blocks=700,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a pagoda inside `aabb`. Tier count is derived so the tower fits."""
    ops: list[Op] = []
    a = aabb
    base = min(a.w, a.d)
    tier_h = 4
    tiers = max(2, min(7, a.h // tier_h - 1))  # leave room for spire
    cx, cz = a.cx, a.cz

    for i in range(tiers):
        s = max(3, base - 2 * i)
        s2 = s // 2
        body_y = a.y0 + i * tier_h
        # Tier body.
        tier_aabb = AABB(cx - s2, body_y, cz - s2,
                         cx + s2 + 1, body_y + tier_h, cz + s2 + 1)
        ops.append(FillHollow(aabb=tier_aabb, wall="@primary"))
        # Eave overhang (single ring 1 block wider, 1 above body top).
        eave_y = body_y + tier_h
        eave_s = s2 + 1
        for x in range(cx - eave_s, cx + eave_s + 1):
            ops.append(PlaceBlock(x=x, y=eave_y, z=cz - eave_s,
                                  block="@stairs[facing=north]"))
            ops.append(PlaceBlock(x=x, y=eave_y, z=cz + eave_s,
                                  block="@stairs[facing=south]"))
        for z in range(cz - eave_s + 1, cz + eave_s):
            ops.append(PlaceBlock(x=cx - eave_s, y=eave_y, z=z,
                                  block="@stairs[facing=west]"))
            ops.append(PlaceBlock(x=cx + eave_s, y=eave_y, z=z,
                                  block="@stairs[facing=east]"))
        # Corner upturn tips — extra block at each corner one row above.
        for dx, dz in ((-eave_s, -eave_s), (-eave_s, eave_s),
                       (eave_s, -eave_s), (eave_s, eave_s)):
            ops.append(PlaceBlock(x=cx + dx, y=eave_y + 1, z=cz + dz,
                                  block="@stairs"))
        # Accent band at body bottom (south + north faces).
        for x in range(cx - s2 + 1, cx + s2):
            ops.append(PlaceBlock(x=x, y=body_y, z=cz - s2, block="@accent"))
            ops.append(PlaceBlock(x=x, y=body_y, z=cz + s2, block="@accent"))

    # Sorin spire: 6 trim blocks + lantern finial (1.17+ remap from end_rod).
    spire_base_y = a.y0 + tiers * tier_h + 1
    for k in range(6):
        ops.append(PlaceBlock(x=cx, y=spire_base_y + k, z=cz, block="@fence"))
    ops.append(PlaceBlock(x=cx, y=spire_base_y + 6, z=cz, block="@lantern"))
    return ops
