"""Observatory Tower — cylindrical body with glass ribbon + half-dome cap.

Source: TFGv2 `tower_variety.py:631-675` (ObservatoryTowerSkillV2).

1.17+ remap: `spyglass` telescope → `iron_bars` (vertical-looking proxy).
"""
from __future__ import annotations

from ..base import AABB, Cylinder, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="observatory_tower",
    kind="tower",
    title="Observatory Tower",
    description=(
        "Cylindrical stone tower with a glass-paned ribbon at the top and "
        "an open half-dome with a central telescope opening. Astronomy "
        "halls and wizard studies."
    ),
    style_affinities=["fantasy", "gothic", "victorian", "wizard"],
    scale_affinities=["medium", "large"],
    typical_footprint=(7, 18, 7),
    cost_blocks=300,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    cx, cz = a.cx, a.cz
    r = max(3, min(a.w, a.d) // 2)
    h = max(10, a.h - (r + 1))

    ops.append(Cylinder(cx=cx, cz=cz, y0=a.y0, radius=r, height=h,
                        block="@primary", hollow=True))

    # Glass ribbon at top (2 courses).
    if h >= 4:
        for dy in (h - 3, h - 2):
            for (x, z) in _geom.circle_xz(cx, cz, r):
                ops.append(PlaceBlock(x=x, y=a.y0 + dy, z=z, block="@glass"))

    # Half-dome cap with telescope opening at center.
    for i in range(r):
        for (x, z) in _geom.circle_xz(cx, cz, max(1, r - i)):
            if (x, z) == (cx, cz):
                continue
            ops.append(PlaceBlock(x=x, y=a.y0 + h + i, z=z, block="@primary"))

    # Telescope proxy — was spyglass (1.17+); now vertical iron_bars.
    ops.append(PlaceBlock(x=cx, y=a.y0 + h, z=cz, block="minecraft:iron_bars"))
    return ops
