"""Skill: pagoda_tower — a standalone multi-tier pagoda structure.

A square shaft divided into `tier_count` storeys, each smaller than the one
below, every storey crowned with a curved upturned-eave course (via
`pipeline.skills.eaves`) and the whole topped with a finial mast. Each storey is
a hollow room with a glazed window on each face, so the tower reads as a temple
pagoda rather than a solid spike.

Coordinate convention (matches `base.py`): x=width, y=up, z=depth; AABB half-open.
"""
from __future__ import annotations

from typing import List

from . import eaves, params
from .base import AABB, FillHollow, Materials, Op, PlaceBlock


def _ops_from_tuples(tups, mats: Materials) -> List[Op]:
    return [PlaceBlock(x, y, z, params.resolve(role, mats)) for (x, y, z, role) in tups]


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    tiers = params.resolve_int(kwargs, "tier_count", 3, lo=2, hi=6)
    flare = params.resolve_flare(kwargs, 1.0)
    mats = params.with_overrides(materials, kwargs, style, rag_id="pagoda_tower")

    x0, z0 = aabb.x0, aabb.z0
    x1, z1 = aabb.x1 - 1, aabb.z1 - 1
    tier_h = max(3, aabb.h // (tiers + 1))
    inset = max(1, min(x1 - x0, z1 - z0) // (tiers * 2 + 2))

    wall = params.resolve("@primary", mats)
    floor = params.resolve("@floor", mats)
    glass = params.resolve("@glass", mats)

    ops: List[Op] = []
    cx0, cz0, cx1, cz1 = x0, z0, x1, z1
    cy = aabb.y0
    tups: list = []
    for t in range(tiers):
        if cx1 - cx0 < 2 or cz1 - cz0 < 2:
            break
        last = t == tiers - 1
        # hollow storey shell
        ops.append(FillHollow(
            AABB(cx0, cy, cz0, cx1 + 1, cy + tier_h, cz1 + 1),
            wall=wall, floor=floor))
        # one window per face at mid-height
        wy = cy + tier_h // 2
        mx = (cx0 + cx1) // 2
        mz = (cz0 + cz1) // 2
        for (px, pz) in ((mx, cz0), (mx, cz1), (cx0, mz), (cx1, mz)):
            ops.append(PlaceBlock(px, wy, pz, glass))
        # upturned eave course crowning the storey
        oh = max(1, min(2, min(cx1 - cx0, cz1 - cz0) // 4))
        eave_y = cy + tier_h
        tups += eaves.eave_shelf(cx0, cz0, cx1, cz1, eave_y, oh, "@roof")
        tups += eaves.eave_upturn(cx0, cz0, cx1, cz1, eave_y, oh, flare,
                                  "@roof", "@accent", "@stairs")
        cy = eave_y + 1
        if last:
            ccx, ccz = (cx0 + cx1) // 2, (cz0 + cz1) // 2
            tups += eaves.finial(ccx, ccz, cy, 4, "@accent")
            break
        cx0, cz0, cx1, cz1 = cx0 + inset, cz0 + inset, cx1 - inset, cz1 - inset

    ops += _ops_from_tuples(tups, mats)
    return ops
