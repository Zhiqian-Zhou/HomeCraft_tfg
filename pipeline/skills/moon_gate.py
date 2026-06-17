"""Skill: moon_gate — a circular garden gateway set in a wall.

A vertical ring (the iconic Chinese yuèliàngmén) in the x-y plane: a masonry
circle around an open round doorway, optionally embedded in a short length of
garden wall. Marks a threshold between garden rooms.

Coordinate convention (matches `base.py`): x=width, y=up, z=depth; AABB half-open.
"""
from __future__ import annotations

from typing import List

from . import params
from .base import AABB, Materials, Op, PlaceBlock


def _ring(cx: int, cy: int, zc: int, r: int, block: str) -> List[Op]:
    out: List[Op] = []
    r_out2 = (r + 0.5) ** 2
    r_in2 = (r - 0.5) ** 2
    for dx in range(-r, r + 1):
        for dy in range(-r, r + 1):
            d2 = dx * dx + dy * dy
            if r_in2 <= d2 <= r_out2:
                out.append(PlaceBlock(cx + dx, cy + dy, zc, block))
    return out


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    mats = params.with_overrides(materials, kwargs, style, rag_id="moon_gate")
    ring_block = params.resolve("@secondary", mats)
    wall_block = params.resolve("@primary", mats)

    zc = (aabb.z0 + aabb.z1 - 1) // 2
    r = max(2, min((aabb.w - 1) // 2, (aabb.h - 1) // 2))
    cx = (aabb.x0 + aabb.x1 - 1) // 2
    cy = aabb.y0 + r  # sit the circle so its bottom is near ground

    ops: List[Op] = []
    # optional short wall the gate is set into (corners around the circle)
    for x in range(aabb.x0, aabb.x1):
        for y in range(aabb.y0, min(aabb.y1, cy + r + 1)):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            if d2 > (r + 0.5) ** 2:
                ops.append(PlaceBlock(x, y, zc, wall_block))
    # the moon ring itself
    ops += _ring(cx, cy, zc, r, ring_block)
    return ops
