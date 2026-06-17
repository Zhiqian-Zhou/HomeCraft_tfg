"""Wizard's Tower — bulged cylinder with witch-hat conical roof.

Source: TFGv2 `tower_variety.py:432-489` (WizardTowerSkill).

Round stone tower with a bulged profile (wider at mid-height), stained-glass
ribbon, accent band at top, and a tall conical roof with a glowing finial.

1.17+ remaps:
  * `amethyst_block`        → `minecraft:quartz_block` (purple-ish, magical-feeling)
  * `deepslate_tile_stairs` → `@stairs` (per-style stair block)
  * `end_rod`               → `@lantern` (per-style light)
"""
from __future__ import annotations

import math

from ..base import AABB, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="wizard_tower",
    kind="tower",
    title="Wizard's Tower",
    description=(
        "Round stone tower that bulges out near the middle then tapers back, "
        "capped with a steep witch-hat conical roof and a glowing crystal "
        "finial. Often has a stained-glass ribbon."
    ),
    style_affinities=["fantasy", "fairytale", "wizard", "magical", "gothic"],
    scale_affinities=["medium", "large", "monumental"],
    typical_footprint=(11, 30, 11),
    cost_blocks=550,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build the bulged tower body and witch-hat cap from `aabb`."""
    ops: list[Op] = []
    a = aabb
    cx, cz = a.cx, a.cz
    base_r = max(2, min(a.w, a.d) // 2)
    h = max(6, a.h - (base_r + 4))    # reserve space for roof cap above

    # Bulged cylindrical body — per-Y radius follows 0.85 + 0.4·sin(pi·t).
    denom = max(1, h - 1)
    for y in range(h):
        t = y / denom
        yr = max(2, int(round(base_r * (0.85 + 0.4 * math.sin(math.pi * t)))))
        for (x, z) in _geom.circle_xz(cx, cz, yr):
            ops.append(PlaceBlock(x=x, y=a.y0 + y, z=z, block="@primary"))

    # Stained-glass ribbon at mid-height (8 anchor cells).
    if kwargs.get("stained_glass", True):
        mid = a.y0 + h // 2
        offsets = ((0, -base_r), (0, base_r), (-base_r, 0), (base_r, 0),
                   (base_r - 1, base_r - 1), (-(base_r - 1), -(base_r - 1)),
                   (-(base_r - 1), base_r - 1), (base_r - 1, -(base_r - 1)))
        for (dx, dz) in offsets:
            for ky in (mid, mid + 1):
                ops.append(PlaceBlock(x=cx + dx, y=ky, z=cz + dz,
                                      block="@glass"))

    # Accent band near top — replaces 1.17+ amethyst_block with quartz_block
    # which gives a similar magical-pale-stone read in 1.16.5.
    for (x, z) in _geom.circle_xz(cx, cz, base_r):
        ops.append(PlaceBlock(x=x, y=a.y0 + h, z=z,
                              block="minecraft:quartz_block"))

    # Witch-hat conical roof — uses @stairs (per-style) instead of the
    # original deepslate_tile_stairs; lantern (per-style) at the tip.
    ops += _geom.conical_spire(
        cx, cz, a.y0 + h + 1, base_r + 1, h // 2 + 2,
        block="@stairs", cap_block="@lantern",
    )
    return ops
