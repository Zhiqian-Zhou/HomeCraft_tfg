"""Bathroom skill — small wet-room with stone-tile floor, plank walls,
slab ceiling and 1.16.5 furniture proxies.

Minecraft 1.16.5 has no toilet block, so we proxy bathroom function with:
  * `minecraft:cauldron`        — sink / bathtub (against a wall)
  * `minecraft:water`           — source block adjacent to the cauldron
  * `minecraft:brewing_stand`   — soap / potion proxy on a side counter
  * `minecraft:chest`           — towel storage
  * `minecraft:lantern` / torch — wall light (style-dependent)

Footprint: defensive on AABB ranging from 4×3×4 up to 10×5×10. Below the
minimum we clamp the interior placements so the skill still emits a
schema-valid shell instead of crashing.

Material roles used:
    @primary    — walls
    @secondary  — floor (tile-like stone surface)
    @slab       — flat ceiling slab roof
    @light      — wall fixture (lantern in fantasy, torch in medieval)
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Hard footprint clamps (defensive against tiny or oversized AABBs).
_MIN_W, _MIN_H, _MIN_D = 4, 3, 4
_MAX_W, _MAX_H, _MAX_D = 10, 5, 10


def _clamp_aabb(aabb: AABB) -> AABB:
    """Trim an oversized AABB and warn (via no-op) when it's too small.

    We always honour the AABB origin; we only shrink x1/y1/z1 when the
    requested size exceeds the documented maximum.
    """
    w = max(_MIN_W, min(aabb.w, _MAX_W))
    h = max(_MIN_H, min(aabb.h, _MAX_H))
    d = max(_MIN_D, min(aabb.d, _MAX_D))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a bathroom into the given AABB.

    Layout (interior coords are computed from the clamped AABB):
        - y0 plane               : @secondary (tile floor)
        - y in (y0, y_ceiling)   : @primary (walls only on perimeter)
        - y_ceiling plane        : @slab (flat ceiling roof)
        - cauldron + water       : middle of -X wall (water just outside cauldron)
        - brewing_stand          : next to cauldron along the same wall
        - chest                  : opposite (-Z or +X) wall corner
        - lantern/torch          : on the opposite wall at head height
    """
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    y_floor = a.y0
    y_ceiling = a.y1 - 1  # top layer of the AABB

    # 1. Floor — tile-like stone (secondary).
    ops.append(Rect(a, "@secondary", axis="y", level=y_floor))

    # 2. Walls — plank/primary perimeter, hollow inside.
    #    We fill the perimeter columns from (y_floor + 1) up to (y_ceiling - 1)
    #    so the floor and ceiling rectangles can override cleanly.
    wall_y0 = y_floor + 1
    wall_y1 = y_ceiling  # exclusive (Fill uses half-open)
    if wall_y1 > wall_y0:
        # -X wall slab
        ops.append(Fill(AABB(a.x0, wall_y0, a.z0,
                             a.x0 + 1, wall_y1, a.z1), "@primary"))
        # +X wall slab
        ops.append(Fill(AABB(a.x1 - 1, wall_y0, a.z0,
                             a.x1, wall_y1, a.z1), "@primary"))
        # -Z wall slab
        ops.append(Fill(AABB(a.x0, wall_y0, a.z0,
                             a.x1, wall_y1, a.z0 + 1), "@primary"))
        # +Z wall slab
        ops.append(Fill(AABB(a.x0, wall_y0, a.z1 - 1,
                             a.x1, wall_y1, a.z1), "@primary"))

    # 3. Ceiling — flat slab roof.
    ops.append(Rect(a, "@slab", axis="y", level=y_ceiling))

    # 4. Furniture placements (interior y just above the floor).
    fy = y_floor + 1

    # Cauldron against the -X interior wall, roughly centered along Z.
    cauldron_x = a.x0 + 1
    cauldron_z = (a.z0 + a.z1) // 2
    # Clamp cauldron Z inside the interior (avoid the -Z / +Z walls).
    cauldron_z = max(a.z0 + 1, min(cauldron_z, a.z1 - 2))
    ops.append(PlaceBlock(cauldron_x, fy, cauldron_z, "minecraft:cauldron"))

    # Water source adjacent to the cauldron (on the +X side, still interior).
    water_x = cauldron_x + 1
    if water_x < a.x1 - 1:
        ops.append(PlaceBlock(water_x, fy, cauldron_z, "minecraft:water"))

    # Brewing stand on the same wall, one block along +Z if it fits.
    brewing_z = cauldron_z + 1
    if brewing_z <= a.z1 - 2:
        ops.append(PlaceBlock(cauldron_x, fy, brewing_z, "minecraft:brewing_stand"))
    else:
        # Fallback: place it one block -Z instead.
        brewing_z = cauldron_z - 1
        if brewing_z >= a.z0 + 1:
            ops.append(PlaceBlock(cauldron_x, fy, brewing_z, "minecraft:brewing_stand"))

    # Chest against the +X wall, opposite the cauldron.
    chest_x = a.x1 - 2
    chest_z = max(a.z0 + 1, min(a.z1 - 2, cauldron_z))
    if chest_x > cauldron_x:  # only place if there's room separate from cauldron
        ops.append(PlaceBlock(chest_x, fy, chest_z, "minecraft:chest"))

    # Wall light — lantern on the +Z interior wall at head height.
    light_block = "minecraft:lantern" if style.lower() in {"fantasy", "modern"} else "minecraft:torch"
    light_y = min(y_ceiling - 1, fy + 1)
    light_x = (a.x0 + a.x1) // 2
    light_x = max(a.x0 + 1, min(light_x, a.x1 - 2))
    light_z = a.z1 - 2  # one block inside the +Z wall
    if light_z > a.z0:
        ops.append(PlaceBlock(light_x, light_y, light_z, light_block))

    return ops
