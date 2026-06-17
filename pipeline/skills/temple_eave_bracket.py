"""Skill: temple_eave_bracket — a dougong-style corbel band under the eave.

A decorative add-on: a band of @accent brackets around the footprint perimeter
near the top of the AABB, each bracket an accent block sitting on an outward
stair, evoking the interlocking dougong brackets that carry an East-Asian eave.

Coordinate convention (matches `base.py`): x=width, y=up, z=depth; AABB half-open.
"""
from __future__ import annotations

from typing import List

from . import params
from .base import AABB, Materials, Op, PlaceBlock


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    mats = params.with_overrides(materials, kwargs, style, rag_id="temple_eave_bracket")
    accent = params.resolve("@accent", mats)
    stair = params.resolve("@stairs", mats)

    x0, z0 = aabb.x0, aabb.z0
    x1, z1 = aabb.x1 - 1, aabb.z1 - 1
    y = aabb.y1 - 1  # band just under where the eave starts
    ops: List[Op] = []
    for x in range(x0, x1 + 1):
        for z in range(z0, z1 + 1):
            if x not in (x0, x1) and z not in (z0, z1):
                continue
            ops.append(PlaceBlock(x, y, z, accent))
            # outward-facing stair corbel below the bracket
            if z == z0:
                f = "north"
            elif z == z1:
                f = "south"
            elif x == x0:
                f = "west"
            else:
                f = "east"
            sb = f"{stair}[facing={f}]" if "[" not in stair else stair
            if y - 1 >= aabb.y0:
                ops.append(PlaceBlock(x, y - 1, z, sb))
    return ops
