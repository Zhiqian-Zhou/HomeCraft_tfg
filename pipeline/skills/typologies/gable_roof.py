"""Gable Roof — classic 2-slope pitched roof along the longest axis.

Source: TFGv2 `roof_variety.py:28-109` (GableRoofSkillV2).

The AABB describes the FOOTPRINT of the building below; the roof sits
starting at `aabb.y0` and rises `min(aabb.h, half)` levels where `half =
max(1, short_side // 2)`. The ridge runs along whichever horizontal axis
of the AABB is longer. The two short ends are filled in with the @primary
block as gable triangles.

Roof contract: `aabb` is the footprint+roof envelope (y0 = roof base, y1
= maximum ridge height). Stair facing strings (`@stairs[facing=north]`,
etc.) are resolved by the composer to the active style's stair block.
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="gable_roof",
    kind="roof",
    title="Gable Roof",
    description=(
        "Classic 2-slope gable along the longest footprint axis with "
        "triangular infill on the short ends. The defining pitched roof of "
        "tudor cottages, suburban houses, fantasy villages, and most "
        "low-rise residential buildings."
    ),
    style_affinities=["tudor", "cottage", "suburban", "fantasy_village",
                      "rustic", "medieval"],
    scale_affinities=["small", "medium", "large"],
    typical_footprint=(12, 6, 8),
    composability=["dormer_gabled", "oriel"],
    cost_blocks=200,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a gable roof over the footprint described by `aabb`.

    kwargs:
        ridge_axis: 'long' (default) or 'short' — which AABB axis the
            ridge runs along.
        pitch: int — explicit pitch budget. Defaults to min(aabb.h - 1, half).
    """
    ops: list[Op] = []
    a = aabb
    base_y = a.y0
    w, d = a.w, a.d
    ridge_axis = kwargs.get("ridge_axis", "long")
    along_x = (w >= d) if ridge_axis == "long" else (w < d)
    half = max(1, (d if along_x else w) // 2)
    pitch = kwargs.get("pitch", min(a.h - 1, half))
    pitch = max(1, min(pitch, half))

    if along_x:
        center_z = (a.z0 + a.z1 - 1) // 2
        for level in range(pitch + 1):
            lz = center_z - half + level
            rz = center_z + half - level
            for x in range(a.x0, a.x1):
                if lz < center_z:
                    ops.append(PlaceBlock(x=x, y=base_y + level, z=lz,
                                          block="@stairs[facing=north]"))
                if rz > center_z:
                    ops.append(PlaceBlock(x=x, y=base_y + level, z=rz,
                                          block="@stairs[facing=south]"))
                if lz == rz:
                    # Ridge cell — full block to close the apex.
                    ops.append(PlaceBlock(x=x, y=base_y + level, z=lz,
                                          block="@primary"))
        # Gable-end triangle fill on both short faces.
        for end_x in (a.x0, a.x1 - 1):
            for level in range(pitch + 1):
                span = half - level
                for zz in range(center_z - span, center_z + span + 1):
                    ops.append(PlaceBlock(x=end_x, y=base_y + level, z=zz,
                                          block="@primary"))
    else:
        center_x = (a.x0 + a.x1 - 1) // 2
        for level in range(pitch + 1):
            lx = center_x - half + level
            rx = center_x + half - level
            for z in range(a.z0, a.z1):
                if lx < center_x:
                    ops.append(PlaceBlock(x=lx, y=base_y + level, z=z,
                                          block="@stairs[facing=west]"))
                if rx > center_x:
                    ops.append(PlaceBlock(x=rx, y=base_y + level, z=z,
                                          block="@stairs[facing=east]"))
                if lx == rx:
                    ops.append(PlaceBlock(x=lx, y=base_y + level, z=z,
                                          block="@primary"))
        for end_z in (a.z0, a.z1 - 1):
            for level in range(pitch + 1):
                span = half - level
                for xx in range(center_x - span, center_x + span + 1):
                    ops.append(PlaceBlock(x=xx, y=base_y + level, z=end_z,
                                          block="@primary"))
    return ops
