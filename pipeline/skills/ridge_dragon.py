"""Skill: ridge_dragon — an ornamental roof ridge with upturned ends.

A decorative add-on placed along the top ridge of a roof: an @accent ridge line
running the longer axis, with horns sweeping up at both ends and a finial — the
chiwen ridge ornaments of an East-Asian roof.

Coordinate convention (matches `base.py`): x=width, y=up, z=depth; AABB half-open.
"""
from __future__ import annotations

from typing import List

from . import params
from .base import AABB, Line, Materials, Op, PlaceBlock


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    flare = params.resolve_flare(kwargs, 1.0)
    mats = params.with_overrides(materials, kwargs, style, rag_id="ridge_dragon")
    accent = params.resolve("@accent", mats)

    y = aabb.y1 - 1
    ops: List[Op] = []
    horn = max(1, min(3, round(flare * 2)))
    if aabb.w >= aabb.d:
        zc = (aabb.z0 + aabb.z1 - 1) // 2
        x0, x1 = aabb.x0, aabb.x1 - 1
        ops.append(Line(x0, y, zc, x1, y, zc, accent))
        for (ex, _f) in ((x0, -1), (x1, 1)):
            for k in range(1, horn + 1):
                ops.append(PlaceBlock(ex, y + k, zc, accent))
    else:
        xc = (aabb.x0 + aabb.x1 - 1) // 2
        z0, z1 = aabb.z0, aabb.z1 - 1
        ops.append(Line(xc, y, z0, xc, y, z1, accent))
        for ez in (z0, z1):
            for k in range(1, horn + 1):
                ops.append(PlaceBlock(xc, y + k, ez, accent))
    return ops
