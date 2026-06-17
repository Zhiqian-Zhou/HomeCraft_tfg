"""Pepperpot Corner Tower — slim round turret with steep conical cap.

Source: TFGv2 `tower_variety.py:551-586` (PepperpotTowerSkill).

1.17+ remaps:
  * Roof was `deepslate_tile_stairs` → `@stairs` (per-style stair block).
  * Cap finial was `end_rod` → `@lantern` (per-style light).
"""
from __future__ import annotations

from ..base import AABB, Cylinder, Materials, Op
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="pepperpot_tower",
    kind="tower",
    title="Pepperpot Corner Tower",
    description=(
        "Slim round corner tower projecting from a manor or chateau, with "
        "a steep conical roof and a glowing finial. The classic chateau / "
        "victorian turret."
    ),
    style_affinities=["french", "chateau", "victorian", "manor"],
    scale_affinities=["small", "medium"],
    typical_footprint=(5, 18, 5),
    cost_blocks=180,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    cx, cz = a.cx, a.cz
    r = max(2, min(a.w, a.d) // 2)
    h = max(8, a.h - (r + 4))   # leave room for the tall cone

    ops.append(Cylinder(cx=cx, cz=cz, y0=a.y0, radius=r, height=h,
                        block="@primary", hollow=True))
    ops += _geom.conical_spire(
        cx, cz, a.y0 + h, r, h // 2 + 2,
        block="@stairs", cap_block="@lantern",
    )
    return ops
