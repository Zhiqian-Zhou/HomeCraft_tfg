"""Cottage Garden — wildflower jumble on a grass bed with low fence ring.

Source description: TFGv2 `garden.py:7-39` (CottageGardenSkill — stub in
original; implemented minimally here so the catalog entry produces real
voxels).

The AABB is treated as the SITE footprint. Grass blocks fill the y0
plane (cy === y0), flowers scatter on top with deterministic placement
(pseudo-random via cell parity), and an oak fence ring encloses the
perimeter.
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock, Rect
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="cottage_garden",
    kind="garden",
    title="Cottage Garden",
    description=(
        "Romantic wildflower jumble surrounding a building: mixed flowers "
        "on a grass bed, fence ring around the perimeter. English cottages "
        "and farmhouses."
    ),
    style_affinities=["cottage", "tudor", "scottish", "victorian",
                      "scandinavian", "farmhouse", "rustic"],
    scale_affinities=["tiny", "small", "medium", "large"],
    typical_footprint=(20, 1, 20),
    cost_blocks=160,
    mc_version_min="1.16.5",
)


_FLOWERS = (
    "minecraft:poppy", "minecraft:dandelion", "minecraft:oxeye_daisy",
    "minecraft:blue_orchid", "minecraft:cornflower", "minecraft:azure_bluet",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a cottage garden filling `aabb`. Only the y0 plane is used."""
    ops: list[Op] = []
    a = aabb
    y = a.y0

    # Grass bed.
    bed = AABB(a.x0, y, a.z0, a.x1, y + 1, a.z1)
    ops.append(Rect(aabb=bed, block="minecraft:grass_block", axis="y", level=y))

    # Flowers scattered above the grass at ~40% density. Deterministic via
    # (x*31 + z*17) % 10 < 4 — gives a pseudo-random but reproducible jumble.
    for x in range(a.x0, a.x1):
        for z in range(a.z0, a.z1):
            # Skip the perimeter ring (reserved for fence).
            if x in (a.x0, a.x1 - 1) or z in (a.z0, a.z1 - 1):
                continue
            h = (x * 31 + z * 17) % 10
            if h < 4:
                flower = _FLOWERS[(x * 7 + z * 3) % len(_FLOWERS)]
                ops.append(PlaceBlock(x=x, y=y + 1, z=z, block=flower))

    # Oak fence ring around the perimeter.
    for x in range(a.x0, a.x1):
        ops.append(PlaceBlock(x=x, y=y + 1, z=a.z0,     block="@fence"))
        ops.append(PlaceBlock(x=x, y=y + 1, z=a.z1 - 1, block="@fence"))
    for z in range(a.z0 + 1, a.z1 - 1):
        ops.append(PlaceBlock(x=a.x0,     y=y + 1, z=z, block="@fence"))
        ops.append(PlaceBlock(x=a.x1 - 1, y=y + 1, z=z, block="@fence"))
    return ops
