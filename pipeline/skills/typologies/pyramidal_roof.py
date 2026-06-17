"""Pyramidal Roof — square base tapering to a single apex.

Source: TFGv2 `roof_variety.py:305-335` (PyramidalRoofSkill).

A direct wrapper around the `pyramid_square` geom helper. Used for
tower-top caps, pavilions, gazebos, and pagoda crowns.
"""
from __future__ import annotations

from ..base import AABB, Materials, Op
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="pyramidal_roof",
    kind="roof",
    title="Pyramidal Roof",
    description=(
        "Square base tapering to a single apex point. Used as tower-top "
        "caps, pavilion roofs, garden gazebos, and Japanese pagoda crowns."
    ),
    style_affinities=["castle_corner", "pavilion", "japanese", "garden"],
    scale_affinities=["small", "medium", "large"],
    typical_footprint=(7, 5, 7),
    cost_blocks=180,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    a = aabb
    half = max(a.w, a.d) // 2
    pitch = kwargs.get("pitch", min(a.h, max(3, half)))
    return _geom.pyramid_square(a.cx, a.cz, a.y0, half, pitch, block="@stairs")
