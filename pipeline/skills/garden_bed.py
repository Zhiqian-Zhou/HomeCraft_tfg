"""`garden_bed` skill — a small rectangular garden plot.

Layout strategy (AABB coordinate system in `base.py`):
    * y0 ground plane: a full rectangle of `minecraft:grass_block` covering
      the AABB footprint. This is the soil/lawn.
    * Bed border at y0 + 1: a 1-block tall rectangular wall of
      `cobblestone_wall` (resolved by style; default uses
      `minecraft:cobblestone_wall`, fantasy keeps it, modern swaps to a
      clean concrete edge via @secondary). The border defines the bed.
    * Central path: a 3-block wide strip of `@floor` running along the
      longest horizontal axis, at y0 (overrides the grass below). It
      enters the bed by cutting through the border on both ends.
    * Inside the bed (between border and path): rows of
      `minecraft:grass_block` topped with plants:
        - 3..5 `minecraft:flower_pot` scattered on a 2-step grid.
        - 3..5 `minecraft:oak_sapling` (alternate rows) and 3..5
          `minecraft:dandelion`/`minecraft:poppy` (alternate columns).
        - 1..2 `minecraft:hay_block` near a corner (compost-pile look).
    * Lantern posts at two corners (NW and SE by default): a 2-tall
      `@fence` column with `minecraft:lantern` on top.

Defensive sizing: clamped to 4×2×4 .. 16×3×16. The skill always returns
at least the grass ground + a border so previews are non-empty.

Style note: the border block uses `@secondary` to let style packs pick
their own edging material; fantasy adds a sea_lantern accent, modern
gets clean concrete edges (via the materials preset). See the RAG entry
for the style_variants table.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive bounds, per spec (footprint 4×4 .. 16×16, height 2..3).
_MIN = (4, 2, 4)
_MAX = (16, 3, 16)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the defensive envelope.

    Keeps the lower corner fixed; shifts the upper corner so the size
    constraints hold. Tiny inputs grow to 4×2×4; huge inputs shrink to
    16×3×16.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def _border_block(style: str) -> str:
    """Style-aware border block id.

    medieval / default → cobblestone_wall (rustic, mossy feel)
    modern             → @secondary (smooth concrete edge)
    fantasy            → mossy_cobblestone_wall
    """
    s = (style or "").lower()
    if s == "modern":
        return "@secondary"
    if s == "fantasy":
        return "minecraft:mossy_cobblestone_wall"
    return "minecraft:cobblestone_wall"


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a small garden bed inside the given AABB."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    x0, y0, z0 = a.x0, a.y0, a.z0
    x1, y1, z1 = a.x1, a.y1, a.z1
    w, d = a.w, a.d

    # ──────────────────── 1) Grass ground at y0 ────────────────────
    # Full rectangle of soil/lawn covering the AABB footprint.
    ops.append(
        Rect(
            AABB(x0, y0, z0, x1, y0 + 1, z1),
            "minecraft:grass_block",
            axis="y",
            level=y0,
        )
    )

    # ──────────────────── 2) Rectangular bed border ────────────────
    # 1-block tall border at y0 + 1 around the AABB edges. Walls along
    # the four perimeter edges (corners shared but later-wins handles).
    border = _border_block(style)
    y_border = y0 + 1

    # north edge (z = z0) and south edge (z = z1 - 1)
    for z_edge in (z0, z1 - 1):
        for x in range(x0, x1):
            ops.append(PlaceBlock(x, y_border, z_edge, border))
    # west edge (x = x0) and east edge (x = x1 - 1)
    for x_edge in (x0, x1 - 1):
        for z in range(z0 + 1, z1 - 1):
            ops.append(PlaceBlock(x_edge, y_border, z, border))

    # ──────────────────── 3) Central path (3 wide) ─────────────────
    # Runs along the longest horizontal axis. Overrides grass at y0 and
    # also cuts the border at both end edges so you can walk through.
    long_axis_x = w >= d
    if long_axis_x:
        # Path centred on z, full length along x. 3 blocks wide; on a
        # 4-deep bed we shrink to 1 wide to keep some greenery.
        path_half = 1 if d >= 5 else 0
        cz = (z0 + z1 - 1) // 2
        pz0 = max(z0 + 1, cz - path_half)
        pz1 = min(z1 - 1, cz + path_half + 1)
        # Path floor (y0) along the full x range so it punches through
        # the border at both ends as well (later-wins over grass).
        ops.append(
            Rect(
                AABB(x0, y0, pz0, x1, y0 + 1, pz1),
                "@floor",
                axis="y",
                level=y0,
            )
        )
        # Cut the border at the two end gates (so the path is open).
        for z in range(pz0, pz1):
            ops.append(PlaceBlock(x0, y_border, z, "minecraft:air"))
            ops.append(PlaceBlock(x1 - 1, y_border, z, "minecraft:air"))
    else:
        path_half = 1 if w >= 5 else 0
        cx = (x0 + x1 - 1) // 2
        px0 = max(x0 + 1, cx - path_half)
        px1 = min(x1 - 1, cx + path_half + 1)
        ops.append(
            Rect(
                AABB(px0, y0, z0, px1, y0 + 1, z1),
                "@floor",
                axis="y",
                level=y0,
            )
        )
        for x in range(px0, px1):
            ops.append(PlaceBlock(x, y_border, z0, "minecraft:air"))
            ops.append(PlaceBlock(x, y_border, z1 - 1, "minecraft:air"))

    # Recompute path band for "is this cell on the path?" checks below.
    if long_axis_x:
        path_x_range = range(x0, x1)
        path_z_range = range(pz0, pz1)
    else:
        path_x_range = range(px0, px1)
        path_z_range = range(z0, z1)

    def _on_path(x: int, z: int) -> bool:
        return x in path_x_range and z in path_z_range

    # ──────────────────── 4) Plants inside the bed ─────────────────
    # The plantable interior is the AABB shrunk by 1 on x/z (inside the
    # border). At y0 + 1 we place flower_pot / sapling / dandelion /
    # poppy on top of the grass block at y0. We skip the path band.
    plant_y = y0 + 1
    plants_added = {"flower_pot": 0, "sapling": 0, "dandelion": 0,
                    "poppy": 0, "hay_block": 0}
    # Caps (3..5 each, 1..2 hay).
    cap = {"flower_pot": 5, "sapling": 5, "dandelion": 5,
           "poppy": 5, "hay_block": 2}
    # Deterministic scatter: walk the interior in a fixed order and
    # assign by (x+z) parity / modulo so the layout is reproducible.
    for x in range(x0 + 1, x1 - 1):
        for z in range(z0 + 1, z1 - 1):
            if _on_path(x, z):
                continue
            # Skip the corner cells reserved for hay piles / lanterns.
            corner_nw = (x == x0 + 1 and z == z0 + 1)
            corner_ne = (x == x1 - 2 and z == z0 + 1)
            corner_sw = (x == x0 + 1 and z == z1 - 2)
            corner_se = (x == x1 - 2 and z == z1 - 2)
            if corner_nw or corner_se:
                # Lantern posts handled below — leave the grass bare.
                continue
            if corner_ne and plants_added["hay_block"] < cap["hay_block"]:
                ops.append(PlaceBlock(x, plant_y, z, "minecraft:hay_block"))
                plants_added["hay_block"] += 1
                continue
            if corner_sw and plants_added["hay_block"] < cap["hay_block"]:
                ops.append(PlaceBlock(x, plant_y, z, "minecraft:hay_block"))
                plants_added["hay_block"] += 1
                continue

            # Assignment rule:
            #   (x + z) % 4 == 0 → flower_pot
            #   (x + z) % 4 == 1 → oak_sapling
            #   (x + z) % 4 == 2 → dandelion
            #   (x + z) % 4 == 3 → poppy
            kind_idx = (x - x0 + z - z0) % 4
            if kind_idx == 0 and plants_added["flower_pot"] < cap["flower_pot"]:
                ops.append(PlaceBlock(x, plant_y, z, "minecraft:flower_pot"))
                plants_added["flower_pot"] += 1
            elif kind_idx == 1 and plants_added["sapling"] < cap["sapling"]:
                ops.append(PlaceBlock(x, plant_y, z, "minecraft:oak_sapling"))
                plants_added["sapling"] += 1
            elif kind_idx == 2 and plants_added["dandelion"] < cap["dandelion"]:
                ops.append(PlaceBlock(x, plant_y, z, "minecraft:dandelion"))
                plants_added["dandelion"] += 1
            elif kind_idx == 3 and plants_added["poppy"] < cap["poppy"]:
                ops.append(PlaceBlock(x, plant_y, z, "minecraft:poppy"))
                plants_added["poppy"] += 1

    # ──────────────────── 5) Lantern posts at corners ──────────────
    # 2-tall @fence pillar with a minecraft:lantern on top, at the NW
    # and SE corners (just inside the border so the lantern hangs over
    # the bed and not the path). On a 2-tall AABB the lantern still
    # mounts above the second fence (intentionally protrudes one block
    # above the bed envelope — a lantern post is conceptually taller
    # than the bed itself).
    lp_y0 = y0 + 1  # base sits on the grass ground
    lp_y1 = y0 + 2  # second fence
    lp_top = y0 + 3  # lantern on top (may protrude above AABB by 1)
    # NW corner
    nw_x, nw_z = x0 + 1, z0 + 1
    ops.append(PlaceBlock(nw_x, lp_y0, nw_z, "@fence"))
    ops.append(PlaceBlock(nw_x, lp_y1, nw_z, "@fence"))
    ops.append(PlaceBlock(nw_x, lp_top, nw_z, "minecraft:lantern"))
    # SE corner
    se_x, se_z = x1 - 2, z1 - 2
    ops.append(PlaceBlock(se_x, lp_y0, se_z, "@fence"))
    ops.append(PlaceBlock(se_x, lp_y1, se_z, "@fence"))
    ops.append(PlaceBlock(se_x, lp_top, se_z, "minecraft:lantern"))

    return ops


# Keep Fill import referenced (linter friendliness; future variants may
# use a solid soil fill at y0 instead of the grass rectangle).
_ = Fill
