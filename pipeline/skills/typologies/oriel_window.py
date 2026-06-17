"""Oriel Window — projecting upper-floor bay window on stair brackets.

Source: TFGv2 `windows_v2.py:29-85` (WindowOrielSkill).

Tudor / gothic / victorian signature: a 3-wide cantilevered glass box on
diagonal stair-bracket corbels below, with a slab cornice on top.

In TFGv2Z the AABB defines the sandbox; the oriel projects OUTWARD from
the centered-on-south wall plane at AABB's south face (z = z0).
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="oriel_window",
    kind="window",
    title="Oriel Window",
    description=(
        "Upper-floor bay window cantilevered on stair-bracket corbels "
        "pointing down-and-out. 3 wide, 2 tall glass, with a slab cornice. "
        "Tudor / gothic / victorian signature."
    ),
    style_affinities=["tudor", "gothic", "victorian", "jacobean", "manor"],
    scale_affinities=["small", "medium", "large"],
    typical_footprint=(3, 4, 2),
    cost_blocks=24,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a south-facing oriel projecting outward from the AABB's z0 face."""
    ops: list[Op] = []
    a = aabb
    width = kwargs.get("width", 3)
    # Sill row sits at mid-height of the AABB, centered on the south wall.
    sill_y = a.y0 + max(1, a.h // 2)
    cx = a.cx
    sill_z = a.z0   # face plane

    # Stair-bracket corbels: 2 stepped accent blocks below each sill cell,
    # extending one block out (south, decreasing z).
    for i in range(width):
        ox = cx + i - width // 2
        for k in range(2):
            ops.append(PlaceBlock(x=ox + 0, y=sill_y - 1 - k, z=sill_z - k,
                                  block="@accent"))
    # Glass bay one block out, 2 courses tall.
    bay_z = sill_z - 1
    for i in range(width):
        ox = cx + i - width // 2
        for yo in (0, 1):
            ops.append(PlaceBlock(x=ox, y=sill_y + yo, z=bay_z, block="@glass"))
    # Slab cornice on top of bay.
    for i in range(width):
        ox = cx + i - width // 2
        ops.append(PlaceBlock(x=ox, y=sill_y + 2, z=bay_z, block="@accent"))
    return ops
