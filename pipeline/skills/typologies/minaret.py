"""Minaret — slim cylindrical tower with balcony + onion-dome cap.

Source: TFGv2 `tower_variety.py:222-268` (MinaretSkill).

1.17+ remap: `end_rod` finial → `@lantern` (per-style light).
"""
from __future__ import annotations

from ..base import AABB, Cylinder, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="minaret",
    kind="tower",
    title="Minaret",
    description=(
        "Slim cylindrical tower with banding every 6 blocks, a balcony ring "
        "near the top, and a small onion-dome cap with a glowing finial. "
        "Used for mosques and middle-eastern palaces."
    ),
    style_affinities=["middle_eastern", "mughal", "mosque", "persian"],
    scale_affinities=["medium", "large", "monumental"],
    typical_footprint=(5, 40, 5),
    cost_blocks=380,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    cx, cz = a.cx, a.cz
    r = max(2, min(a.w, a.d) // 2)
    h = max(8, a.h - 6)  # leave room for dome + finial

    # Cylindrical body.
    ops.append(Cylinder(cx=cx, cz=cz, y0=a.y0, radius=r, height=h,
                        block="@primary", hollow=True))

    # Accent banding every 6 blocks.
    for dy in range(5, h, 6):
        for (x, z) in _geom.circle_xz(cx, cz, r):
            ops.append(PlaceBlock(x=x, y=a.y0 + dy, z=z, block="@accent"))

    # Balcony ring at h-5 (one block wider).
    bal_y = a.y0 + h - 5
    if h >= 8:
        for (x, z) in _geom.circle_xz(cx, cz, r + 1):
            ops.append(PlaceBlock(x=x, y=bal_y, z=z, block="@accent"))
        # Fence railing above balcony.
        for (x, z) in _geom.circle_xz(cx, cz, r + 1):
            ops.append(PlaceBlock(x=x, y=bal_y + 1, z=z, block="@fence"))

    # Onion dome cap.
    ops += _geom.onion_dome(
        cx, cz, a.y0 + h, r, 6, block="@accent",
        finial_block="@lantern",
    )
    return ops
