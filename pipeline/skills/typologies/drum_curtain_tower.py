"""Curtain-Wall Drum Tower — round defensive tower with crenellated walk.

Source: TFGv2 `tower_variety.py:593-624` (DrumCurtainTowerSkill).
"""
from __future__ import annotations

from ..base import AABB, Cylinder, Materials, Op
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="drum_curtain_tower",
    kind="tower",
    title="Curtain-Wall Drum Tower",
    description=(
        "Round drum tower projecting from a curtain wall, with a "
        "crenellated walk on top. The defensive flanking tower of "
        "castle baileys."
    ),
    style_affinities=["castle", "medieval", "fortified"],
    scale_affinities=["medium", "large"],
    typical_footprint=(9, 16, 9),
    cost_blocks=320,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    ops: list[Op] = []
    a = aabb
    cx, cz = a.cx, a.cz
    r = max(3, min(a.w, a.d) // 2)
    h = max(8, a.h - 1)

    ops.append(Cylinder(cx=cx, cz=cz, y0=a.y0, radius=r, height=h,
                        block="@primary", hollow=True))
    ops += _geom.crenellated_circle(cx, cz, a.y0 + h, r, block="@primary")
    return ops
