"""Skill: torii_gate — a Japanese/Chinese ceremonial gate (paifang/torii).

Two pillars carrying a curved upturned top lintel (kasagi) and a straight tie
beam (nuki). Spans the longer horizontal axis of the AABB; thin on the other.
Reads vermilion by default. Marks an entrance or a garden threshold.

Coordinate convention (matches `base.py`): x=width, y=up, z=depth; AABB half-open.
"""
from __future__ import annotations

from typing import List

from . import params
from .base import AABB, Fill, Materials, Op, PlaceBlock


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    flare = params.resolve_flare(kwargs, 1.0)
    # vermilion by default for a paifang/torii feel
    kw = dict(kwargs)
    kw.setdefault("color", "red")
    mats = params.with_overrides(materials, kw, style, rag_id="torii_gate")
    primary = params.resolve("@accent", mats)
    beam = params.resolve("@primary", mats)

    ops: List[Op] = []
    along_x = aabb.w >= aabb.d
    y0 = aabb.y0
    top = aabb.y1 - 1
    height = max(3, top - y0)

    if along_x:
        x_lo, x_hi = aabb.x0, aabb.x1 - 1
        zc = (aabb.z0 + aabb.z1 - 1) // 2
        # two pillars
        for px in (x_lo, x_hi):
            ops.append(Fill(AABB(px, y0, zc, px + 1, y0 + height, zc + 1), primary))
        # nuki tie beam
        nuki_y = y0 + height - 2
        ops.append(Fill(AABB(x_lo, nuki_y, zc, x_hi + 1, nuki_y + 1, zc + 1), beam))
        # kasagi top lintel, overhanging both ends, upturned tips
        kasagi_y = y0 + height
        ops.append(Fill(AABB(x_lo - 1, kasagi_y, zc, x_hi + 2, kasagi_y + 1, zc + 1), primary))
        horn = max(1, min(3, round(flare * 2)))
        for k in range(1, horn + 1):
            ops.append(PlaceBlock(x_lo - 1, kasagi_y + k, zc, primary))
            ops.append(PlaceBlock(x_hi + 1, kasagi_y + k, zc, primary))
    else:
        z_lo, z_hi = aabb.z0, aabb.z1 - 1
        xc = (aabb.x0 + aabb.x1 - 1) // 2
        for pz in (z_lo, z_hi):
            ops.append(Fill(AABB(xc, y0, pz, xc + 1, y0 + height, pz + 1), primary))
        nuki_y = y0 + height - 2
        ops.append(Fill(AABB(xc, nuki_y, z_lo, xc + 1, nuki_y + 1, z_hi + 1), beam))
        kasagi_y = y0 + height
        ops.append(Fill(AABB(xc, kasagi_y, z_lo - 1, xc + 1, kasagi_y + 1, z_hi + 2), primary))
        horn = max(1, min(3, round(flare * 2)))
        for k in range(1, horn + 1):
            ops.append(PlaceBlock(xc, kasagi_y + k, z_lo - 1, primary))
            ops.append(PlaceBlock(xc, kasagi_y + k, z_hi + 1, primary))
    return ops
