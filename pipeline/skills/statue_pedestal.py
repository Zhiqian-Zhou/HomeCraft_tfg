"""Skill: statue_pedestal.

A monumental three-tiered pedestal crowned with an armor-stand statue. The
AABB defines the FOOTPRINT (and the surrounding pavement); the pedestal
itself is always centred inside that footprint:

  * Tier 1 (y0):       3×1×3 @accent pad — the broad base course.
  * Tier 2 (y0+1):     2×1×2 @accent block, centred on the base.
  * Tier 3 (y0+2):     1×1×1 @accent capstone.
  * Statue (y0+3):     one `minecraft:armor_stand` standing on the capstone.
  * Plaque (front):    a single `minecraft:lectern` on the courtyard ground
    in front of the base, acting as an inscription stone.
  * Corner torches:    four @fence posts at the corners of the base with a
    `minecraft:torch` (or `minecraft:sea_lantern` for the fantasy style)
    on top — decorative torch posts framing the monument.
  * Carpet pad:        when the AABB is wide enough to spare a cell beyond
    the 3×3 base, a @carpet ring is drawn around the base on the ground
    plane (an ornamental pad reading as a fabric border around the plinth).

The skill is defensive: the input AABB is clamped to [3..5, 4..6, 3..5] so
the pedestal, statue, torches and carpet always fit. Smaller AABBs are
padded; larger ones are trimmed (the optional carpet pad still fills the
3×3..5×5 envelope around the pedestal).

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive footprint clamps for this skill.
_MIN_W, _MIN_H, _MIN_D = 3, 4, 3
_MAX_W, _MAX_H, _MAX_D = 5, 6, 5


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [3..5, 4..6, 3..5] envelope.

    Origin is preserved; only the upper corner moves so the tiered base,
    the armor-stand and the four corner torches always fit vertically.
    """
    w = max(_MIN_W, min(_MAX_W, aabb.w))
    h = max(_MIN_H, min(_MAX_H, aabb.h))
    d = max(_MIN_D, min(_MAX_D, aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a tiered pedestal with an armor-stand statue on top."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    y0 = a.y0

    # Locate the 3×3 base footprint centred inside the AABB. Using integer
    # centres so the pedestal always has a true axis of symmetry.
    cx = (a.x0 + a.x1 - 1) // 2
    cz = (a.z0 + a.z1 - 1) // 2
    bx0, bx1 = cx - 1, cx + 2  # half-open 3-wide base span
    bz0, bz1 = cz - 1, cz + 2

    # Clamp the base so it never spills past the AABB (e.g. when the caller
    # passes a pathological corner location).
    bx0 = max(a.x0, bx0); bx1 = min(a.x1, bx1)
    bz0 = max(a.z0, bz0); bz1 = min(a.z1, bz1)

    # ───────────────────────────────────────────────────────────────
    # 0) Optional surrounding carpet pad on the ground plane.
    #    Drawn first so the tier-1 @accent base overwrites the centre
    #    cells (composer's "later wins" dedupe takes care of it).
    #    Only emit when the AABB is strictly larger than the 3×3 base
    #    so the pad actually reads as a ring around the plinth.
    # ───────────────────────────────────────────────────────────────
    if a.w > 3 or a.d > 3:
        ops.append(Rect(a, "@carpet", axis="y", level=y0))

    # ───────────────────────────────────────────────────────────────
    # 1) Tier 1 — 3×1×3 @accent base course at y0.
    # ───────────────────────────────────────────────────────────────
    ops.append(Fill(
        AABB(bx0, y0, bz0, bx1, y0 + 1, bz1),
        "@accent",
    ))

    # ───────────────────────────────────────────────────────────────
    # 2) Tier 2 — 2×1×2 @accent course at y0+1, centred on the base.
    #    A 2-wide block has no exact integer centre; we anchor it to
    #    (cx-1, cx+1) × (cz-1, cz+1) which sits flush against the
    #    NW corner of the base. To keep visual symmetry we then nudge
    #    it so it overlaps the centre cell on both axes (effectively
    #    a 2×2 quadrant that includes the centre column).
    # ───────────────────────────────────────────────────────────────
    t2x0, t2x1 = cx - 1, cx + 1  # 2 wide
    t2z0, t2z1 = cz - 1, cz + 1
    # Clamp to base extent.
    t2x0 = max(bx0, t2x0); t2x1 = min(bx1, t2x1)
    t2z0 = max(bz0, t2z0); t2z1 = min(bz1, t2z1)
    if t2x1 > t2x0 and t2z1 > t2z0:
        ops.append(Fill(
            AABB(t2x0, y0 + 1, t2z0, t2x1, y0 + 2, t2z1),
            "@accent",
        ))

    # ───────────────────────────────────────────────────────────────
    # 3) Tier 3 — 1×1×1 @accent capstone at y0+2 on the centre column.
    # ───────────────────────────────────────────────────────────────
    ops.append(PlaceBlock(cx, y0 + 2, cz, "@accent"))

    # ───────────────────────────────────────────────────────────────
    # 4) Armor-stand statue at y0+3 on top of the capstone.
    #    `minecraft:armor_stand` is treated as a placeable block id by
    #    the composer (it stores a one-block entity proxy in the voxel
    #    grid, which the viewer renders as the statue silhouette).
    # ───────────────────────────────────────────────────────────────
    statue_y = y0 + 3
    if statue_y < a.y1:
        ops.append(PlaceBlock(cx, statue_y, cz, "minecraft:armor_stand"))

    # ───────────────────────────────────────────────────────────────
    # 5) Four corner @fence posts with a torch on top.
    #    Posts rise from y0+1 (above the base course) up to y0+2 (one
    #    block tall) so they frame the pedestal without overshadowing
    #    the statue. The torch sits at y0+3, level with the statue's
    #    feet — a ring of light at the monument's pedestal corners.
    # ───────────────────────────────────────────────────────────────
    fence_y = y0 + 1
    torch_y = y0 + 2

    # Decorative light block. Fantasy palette uses the bright sea_lantern
    # described in the JSON style_variants; everything else gets a vanilla
    # torch which is universally available.
    s = style.lower()
    if s == "fantasy":
        torch_block = "minecraft:sea_lantern"
    else:
        torch_block = "minecraft:torch"

    corner_cells: list[tuple[int, int]] = []
    for px in (bx0, bx1 - 1):
        for pz in (bz0, bz1 - 1):
            corner_cells.append((px, pz))
    # Deduplicate (defensive: collapsed bases under heavy clamp).
    corner_cells = list({(px, pz) for (px, pz) in corner_cells})

    # Place the fence/torch *outside* the base footprint when there is
    # room in the AABB; otherwise we keep them at the base corners (in
    # which case the fence would conflict with the @accent base, but the
    # composer's later-wins dedupe leaves the fence visible since we
    # place it after the base fill).
    for (px, pz) in corner_cells:
        # Try to push outward (away from cx, cz) by one cell so the
        # post sits *next to* the pedestal rather than on it.
        dx = -1 if px < cx else 1
        dz = -1 if pz < cz else 1
        fx, fz = px + dx, pz + dz
        if not (a.x0 <= fx < a.x1 and a.z0 <= fz < a.z1):
            # No room outside the base — fall back to the base corner.
            fx, fz = px, pz
        ops.append(PlaceBlock(fx, fence_y, fz, "@fence"))
        if torch_y < a.y1:
            ops.append(PlaceBlock(fx, torch_y, fz, torch_block))

    # ───────────────────────────────────────────────────────────────
    # 6) Plaque lectern at the front of the base. We pick the +z face
    #    of the base (conventionally "south" in Minecraft) and place
    #    the lectern one cell in front of it on the ground plane,
    #    when there is room inside the AABB. The lectern reads as an
    #    inscription stone / text plaque next to the monument.
    # ───────────────────────────────────────────────────────────────
    plaque_x = cx
    plaque_z = bz1  # one cell past the base on the +z (south) face
    if plaque_z >= a.z1:
        # Not enough room on the +z side — try -z instead.
        plaque_z = bz0 - 1
    if a.x0 <= plaque_x < a.x1 and a.z0 <= plaque_z < a.z1:
        # Lectern facing the pedestal (i.e. toward -z when sitting on +z).
        facing = "north" if plaque_z >= bz1 else "south"
        ops.append(PlaceBlock(
            plaque_x, y0, plaque_z, f"minecraft:lectern[facing={facing}]"
        ))

    return ops
