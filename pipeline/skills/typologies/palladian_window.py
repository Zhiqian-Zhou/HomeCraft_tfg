"""Palladian Window — 3-part Georgian composite with arched center.

Source: TFGv2 `windows_v2.py:154-207` (WindowPalladianSkill).

Tall arched 3-wide center panel flanked by 2 shorter rectangular flankers
(at offsets +/- 3). Accent springers form the arch via stair-step + keystone.
Georgian, Federal, Neoclassical, Mughal palace signature.
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="palladian_window",
    kind="window",
    title="Palladian Window",
    description=(
        "3-part composite: tall arched center (3 wide × 4 tall) flanked by "
        "2 shorter rectangular flankers (1 wide × 3 tall). Accent springers "
        "form the arch and a keystone caps it."
    ),
    style_affinities=["georgian", "federal", "palladian", "neoclassical",
                      "mughal", "indian"],
    scale_affinities=["medium", "large", "monumental"],
    typical_footprint=(7, 5, 1),
    cost_blocks=22,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a south-facing Palladian window at the AABB's z0 wall plane."""
    ops: list[Op] = []
    a = aabb
    cx = a.cx
    z = a.z0
    y = a.y0   # sill

    # Two flanker side windows at +/- 3.
    for sign in (-3, 3):
        for yo in range(3):
            ops.append(PlaceBlock(x=cx + sign, y=y + yo, z=z, block="@glass"))

    # Central arched window (3 wide, 3 tall body).
    for dx in (-1, 0, 1):
        for yo in range(3):
            ops.append(PlaceBlock(x=cx + dx, y=y + yo, z=z, block="@glass"))

    # Springers at y+3 (sides), glass at center, keystone at y+4 over center.
    ops.append(PlaceBlock(x=cx - 1, y=y + 3, z=z, block="@accent"))
    ops.append(PlaceBlock(x=cx + 1, y=y + 3, z=z, block="@accent"))
    ops.append(PlaceBlock(x=cx,     y=y + 3, z=z, block="@glass"))
    ops.append(PlaceBlock(x=cx,     y=y + 4, z=z, block="@accent"))
    return ops
