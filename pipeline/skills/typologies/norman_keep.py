"""Norman Square Keep — first port from TFGv2's tower_variety pack.

Source: TFGv2 `skills_v2/packs/tower_variety.py:21-93` (NormanKeepSkill).

Architecture (kept faithful to the original):
  - Thick hollow square shell of @primary stone.
  - 1-block pilaster buttresses of @accent at 1/3 and 2/3 of each face,
    protruding one block outside the wall plane and rising to within 2
    blocks of the parapet.
  - Single-course crenellated parapet of @primary one row above the
    keep top.
  - Arrow-slit ribbon punched through the south face at 2/3 height.

Coordinate convention follows TFGv2Z's half-open AABB: the keep occupies
[x0, x1) × [y0, y1) × [z0, z1). The crenelation sits at y == y1 (one
block above the keep). Defaults assume a square footprint; if w != d the
shell still fills correctly but buttresses use the smaller side.
"""
from __future__ import annotations

from ..base import AABB, FillHollow, Materials, Op, PlaceBlock
from . import _geom
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="norman_keep",
    kind="tower",
    title="Norman Square Keep",
    description=(
        "Massive thick-walled square keep, 3-4 storeys, with pilaster "
        "buttresses on each face and a crenellated parapet. Small slit "
        "windows. Defensive entry on the second storey."
    ),
    style_affinities=["castle", "medieval", "norman", "fortified", "gothic"],
    scale_affinities=["large", "monumental"],
    typical_footprint=(14, 28, 14),
    composability=["arrow_loop_cross", "garderobe_chute"],
    cost_blocks=900,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a Norman Keep inside `aabb`.

    Args:
        aabb: footprint + total height. `aabb.h` should be >= 6 to make
            sense of the parapet + slit-window placement; very small
            AABBs degrade gracefully (buttresses + slits are skipped if
            the height budget is too tight).
        materials: `@primary` is the wall stone; `@accent` is the
            buttress stone (e.g. mossy_cobblestone in medieval).
        style: passed through for future style-specific tweaks (currently
            unused — material thread does the work).
        **kwargs: reserved for future overrides (e.g. `slit_face`,
            `buttress_count`).
    """
    ops: list[Op] = []
    a = aabb

    # 1. Hollow shell: walls + floor + ceiling of @primary.
    ops.append(FillHollow(aabb=a, wall="@primary"))

    # 2. Pilaster buttresses on each of the 4 faces, at 1/3 and 2/3 along
    #    the face length. They protrude one block outside the wall plane.
    s = min(a.w, a.d)
    buttress_top = a.y1 - 2  # leave 2 blocks below parapet
    if s >= 6 and buttress_top > a.y0 + 1:
        for frac in (1.0 / 3.0, 2.0 / 3.0):
            # South face (z == a.z0 - 1, outside): protrudes south.
            bx_x = a.x0 + int(round(frac * (a.w - 1)))
            ops += _geom.vertical_strip(
                x=bx_x, z=a.z0 - 1, y0=a.y0, height=buttress_top - a.y0,
                block="@accent",
            )
            # North face (z == a.z1, outside).
            ops += _geom.vertical_strip(
                x=bx_x, z=a.z1, y0=a.y0, height=buttress_top - a.y0,
                block="@accent",
            )
            # West face (x == a.x0 - 1, outside).
            bz_z = a.z0 + int(round(frac * (a.d - 1)))
            ops += _geom.vertical_strip(
                x=a.x0 - 1, z=bz_z, y0=a.y0, height=buttress_top - a.y0,
                block="@accent",
            )
            # East face (x == a.x1, outside).
            ops += _geom.vertical_strip(
                x=a.x1, z=bz_z, y0=a.y0, height=buttress_top - a.y0,
                block="@accent",
            )

    # 3. Crenellated parapet — one course sitting on top of the keep.
    parapet_top = AABB(a.x0, a.y1, a.z0, a.x1, a.y1 + 1, a.z1)
    ops += _geom.crenellated_ring(parapet_top, block="@primary")

    # 4. Arrow-slit ribbon on the south face at ~2/3 height. The composer
    #    drops air voxels (later wins), so emitting air after the
    #    FillHollow effectively punches the slits through the wall.
    if a.h >= 6 and a.w >= 5:
        mid_y = a.y0 + (a.h * 2) // 3
        # Step every 3 blocks across the south wall, inset by 2 from corners.
        for x in range(a.x0 + 2, a.x1 - 1, 3):
            ops.append(PlaceBlock(x=x, y=mid_y,     z=a.z0, block="minecraft:air"))
            ops.append(PlaceBlock(x=x, y=mid_y + 1, z=a.z0, block="minecraft:air"))

    return ops
