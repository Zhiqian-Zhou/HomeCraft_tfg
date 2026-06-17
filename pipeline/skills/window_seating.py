"""Skill: window_seating — a continuous bench along the inside of EVERY wall.

Universal: applies to ANY room of ANY building. Places `@stairs` facing
inward along the perimeter, at y0+1. The `window_place` metric rewards
glass blocks with seating within Chebyshev 3; this skill guarantees seating
at every wall regardless of where the LLM placed glass.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Place a 1-block-tall bench along the four interior walls at y0+1."""
    stairs = materials.stairs  # e.g. "minecraft:oak_stairs"
    if aabb.w < 4 or aabb.d < 4 or aabb.h < 3:
        return []
    y = aabb.y0 + 1
    ops: List[Op] = []
    # North wall (z = z0): stairs facing south
    for x in range(aabb.x0 + 1, aabb.x1 - 1):
        ops.append(PlaceBlock(x, y, aabb.z0 + 1, f"{stairs}[facing=south]"))
    # South wall (z = z1-1): stairs facing north
    for x in range(aabb.x0 + 1, aabb.x1 - 1):
        ops.append(PlaceBlock(x, y, aabb.z1 - 2, f"{stairs}[facing=north]"))
    # West wall (x = x0): stairs facing east
    for z in range(aabb.z0 + 2, aabb.z1 - 2):
        ops.append(PlaceBlock(aabb.x0 + 1, y, z, f"{stairs}[facing=east]"))
    # East wall (x = x1-1): stairs facing west
    for z in range(aabb.z0 + 2, aabb.z1 - 2):
        ops.append(PlaceBlock(aabb.x1 - 2, y, z, f"{stairs}[facing=west]"))
    return ops
