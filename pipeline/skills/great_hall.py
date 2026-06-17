"""Great hall skill — large ceremonial / throne hall.

Builds a long, tall ceremonial chamber:

    * @floor plane across the AABB at y0.
    * @primary perimeter walls rising the full height (≥ 4 blocks).
    * A throne on a 2-3 block raised dais of @accent, centered against the
      far short wall — the dais is a Fill of @accent and the throne itself
      is a single @stairs block facing into the room (toward the entrance).
    * Two rows of @primary square pillars running along the long axis,
      framing the central path (4-6 pillars per row when the AABB allows).
    * A long @carpet runner along the floor from the entrance wall to the
      foot of the dais, two cells wide when the hall is wide enough.
    * 4+ braziers along the carpet — `minecraft:campfire` if there is
      headroom, otherwise `minecraft:fire` sitting on a `minecraft:netherrack`
      base when stacking is not feasible.
    * 2-3 hanging `minecraft:lantern` chandeliers suspended one block below
      the ceiling along the central axis.
    * 2-4 banner-style `minecraft:red_carpet` blocks affixed to the long
      walls as ceremonial banners (we choose `red_carpet` over `wall_torch`
      because it reads as fabric/heraldry in the viewer).

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth. AABB is half-open.

The hall is "long" along whichever horizontal axis is greater. The
entrance is conceptually the *near* short wall (the +z or +x end); the
throne sits centered on the opposite (far) short wall.

Defensive on AABBs from 8×5×10 up to 18×8×24. Anything smaller still
builds the shell + a single-pillar pair + throne if room allows; anything
larger is clamped to the upper envelope so the hall does not balloon out.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive envelope for the hall.
_MIN_W, _MIN_H, _MIN_D = 8, 5, 10
_MAX_W, _MAX_H, _MAX_D = 18, 8, 24


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [8×5×10 .. 18×8×24] envelope.

    Origin is preserved; only the upper corner moves.
    """
    w = max(_MIN_W, min(_MAX_W, aabb.w))
    h = max(_MIN_H, min(_MAX_H, aabb.h))
    d = max(_MIN_D, min(_MAX_D, aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    long_along_z = a.d >= a.w  # path runs along z when depth dominates

    # ── 1) Floor plane ─────────────────────────────────────────────────
    ops.append(Rect(a, "@floor", axis="y", level=a.y0))

    # ── 2) Walls (4 slabs, no ceiling — open lid for tall verticality) ─
    # Walls rise from y0+1 up to y1 (exclusive), so the hall stays tall.
    h_y0 = a.y0 + 1
    h_y1 = a.y1
    if h_y1 > h_y0:
        # North wall (z = z0)
        ops.append(Fill(AABB(a.x0, h_y0, a.z0, a.x1, h_y1, a.z0 + 1), "@primary"))
        # South wall (z = z1-1)
        ops.append(Fill(AABB(a.x0, h_y0, a.z1 - 1, a.x1, h_y1, a.z1), "@primary"))
        # West wall (x = x0)
        ops.append(Fill(AABB(a.x0, h_y0, a.z0, a.x0 + 1, h_y1, a.z1), "@primary"))
        # East wall (x = x1-1)
        ops.append(Fill(AABB(a.x1 - 1, h_y0, a.z0, a.x1, h_y1, a.z1), "@primary"))

    # ── 3) Throne + dais on the far short wall ─────────────────────────
    # "Far" short wall is the -z side when path is along z, else the -x.
    # The entrance is the opposite short wall (+z or +x).
    if long_along_z:
        # Long axis = z. Throne sits at small z (north end).
        throne_cx = a.cx
        throne_cz = a.z0 + 1  # one step in from the far wall
        # Dais: 3 blocks wide (centered on throne_cx), 2 deep (z0+1 .. z0+3),
        # 2 high if there is headroom, else 1.
        dais_h = 2 if a.h >= 6 else 1
        dais_x0 = max(a.x0 + 1, throne_cx - 1)
        dais_x1 = min(a.x1 - 1, throne_cx + 2)
        dais_z0 = a.z0 + 1
        dais_z1 = min(a.z1 - 1, dais_z0 + 2)
        if dais_x1 > dais_x0 and dais_z1 > dais_z0:
            ops.append(Fill(
                AABB(dais_x0, a.y0 + 1, dais_z0,
                     dais_x1, a.y0 + 1 + dais_h, dais_z1),
                "@accent",
            ))
        throne_y = a.y0 + 1 + dais_h
        # Throne faces +z (toward the entrance).
        ops.append(PlaceBlock(
            throne_cx, throne_y, throne_cz + 1
            if throne_cz + 1 < dais_z1 else throne_cz,
            "@stairs[facing=south]",
        ))
    else:
        # Long axis = x. Throne sits at small x (west end).
        throne_cz = a.cz
        throne_cx = a.x0 + 1
        dais_h = 2 if a.h >= 6 else 1
        dais_z0 = max(a.z0 + 1, throne_cz - 1)
        dais_z1 = min(a.z1 - 1, throne_cz + 2)
        dais_x0 = a.x0 + 1
        dais_x1 = min(a.x1 - 1, dais_x0 + 2)
        if dais_x1 > dais_x0 and dais_z1 > dais_z0:
            ops.append(Fill(
                AABB(dais_x0, a.y0 + 1, dais_z0,
                     dais_x1, a.y0 + 1 + dais_h, dais_z1),
                "@accent",
            ))
        throne_y = a.y0 + 1 + dais_h
        ops.append(PlaceBlock(
            throne_cx + 1 if throne_cx + 1 < dais_x1 else throne_cx,
            throne_y, throne_cz,
            "@stairs[facing=east]",
        ))

    # ── 4) Columns — two rows of @primary pillars flanking the path ────
    # Pillars are 1-block square, rise from y0+1 up to y1-1 (a clear cell
    # below the ceiling lid for chandeliers). We place 4-6 pairs along
    # the long axis, leaving a margin from the entrance and the dais.
    pillar_h_top = a.y1 - 1  # leave one cell at the very top
    pillar_y0 = a.y0 + 1
    if pillar_h_top > pillar_y0:
        if long_along_z:
            # Pillars at x = x0+2 and x = x1-3 (two cells in from each wall),
            # spaced along z. Skip the dais zone and the entrance row.
            path_start = a.z0 + 4  # past the dais
            path_end = a.z1 - 2    # leave one cell before the entrance wall
            px_left = a.x0 + 2
            px_right = a.x1 - 3
            if px_right > px_left and path_end > path_start:
                positions = _column_positions(path_start, path_end, target=5)
                for pz in positions:
                    ops.append(Fill(
                        AABB(px_left, pillar_y0, pz,
                             px_left + 1, pillar_h_top, pz + 1),
                        "@primary",
                    ))
                    if px_right > px_left:
                        ops.append(Fill(
                            AABB(px_right, pillar_y0, pz,
                                 px_right + 1, pillar_h_top, pz + 1),
                            "@primary",
                        ))
        else:
            path_start = a.x0 + 4
            path_end = a.x1 - 2
            pz_near = a.z0 + 2
            pz_far = a.z1 - 3
            if pz_far > pz_near and path_end > path_start:
                positions = _column_positions(path_start, path_end, target=5)
                for px in positions:
                    ops.append(Fill(
                        AABB(px, pillar_y0, pz_near,
                             px + 1, pillar_h_top, pz_near + 1),
                        "@primary",
                    ))
                    if pz_far > pz_near:
                        ops.append(Fill(
                            AABB(px, pillar_y0, pz_far,
                                 px + 1, pillar_h_top, pz_far + 1),
                            "@primary",
                        ))

    # ── 5) Carpet runner: entrance → throne ────────────────────────────
    # Runner is 2 wide when the hall is wide enough (>= 10), else 1.
    carpet_y = a.y0 + 1  # one block above the floor (sits on @floor)
    runner_wide = a.w >= 10 if long_along_z else a.d >= 10
    if long_along_z:
        cx = a.cx
        c_x0 = cx if not runner_wide else cx - 1
        c_x1 = cx + 1 if not runner_wide else cx + 1
        c_z0 = a.z0 + 4  # start past the dais base
        c_z1 = a.z1 - 1  # up to the entrance wall (exclusive)
        if c_z1 > c_z0 and c_x1 > c_x0:
            ops.append(Fill(
                AABB(c_x0, carpet_y, c_z0, c_x1, carpet_y + 1, c_z1),
                "@carpet",
            ))
    else:
        cz = a.cz
        c_z0 = cz if not runner_wide else cz - 1
        c_z1 = cz + 1 if not runner_wide else cz + 1
        c_x0 = a.x0 + 4
        c_x1 = a.x1 - 1
        if c_x1 > c_x0 and c_z1 > c_z0:
            ops.append(Fill(
                AABB(c_x0, carpet_y, c_z0, c_x1, carpet_y + 1, c_z1),
                "@carpet",
            ))

    # ── 6) Braziers along the carpet (≥ 4) ─────────────────────────────
    # We place braziers just outside the carpet runner so they flank the
    # path. Use `minecraft:campfire` directly on the floor (it occupies the
    # same cell as a normal block but reads as fire). For redundancy on
    # very tight rooms we fall back to a `minecraft:fire` on a
    # `minecraft:netherrack` base.
    brazier_y = a.y0 + 1  # one above the floor — flanking the carpet plane
    base_y = a.y0          # netherrack base sits at floor level
    if long_along_z:
        # Brazier columns at x = cx-2 / cx+2 (just outside a 2-wide runner)
        # or cx-1 / cx+1 for a 1-wide runner.
        bx_left = a.cx - (2 if runner_wide else 1)
        bx_right = a.cx + (2 if runner_wide else 1)
        bx_left = max(a.x0 + 1, bx_left)
        bx_right = min(a.x1 - 2, bx_right)
        b_positions_z = _column_positions(a.z0 + 5, a.z1 - 2, target=3)
        for bz in b_positions_z:
            for bx in (bx_left, bx_right):
                if not a.contains(bx, brazier_y, bz):
                    continue
                if a.h >= 5:
                    # Headroom — drop a campfire one cell above the floor.
                    ops.append(PlaceBlock(bx, brazier_y, bz, "minecraft:campfire"))
                else:
                    ops.append(PlaceBlock(bx, base_y, bz, "minecraft:netherrack"))
                    ops.append(PlaceBlock(bx, brazier_y, bz, "minecraft:fire"))
    else:
        bz_near = a.cz - (2 if runner_wide else 1)
        bz_far = a.cz + (2 if runner_wide else 1)
        bz_near = max(a.z0 + 1, bz_near)
        bz_far = min(a.z1 - 2, bz_far)
        b_positions_x = _column_positions(a.x0 + 5, a.x1 - 2, target=3)
        for bx in b_positions_x:
            for bz in (bz_near, bz_far):
                if not a.contains(bx, brazier_y, bz):
                    continue
                if a.h >= 5:
                    ops.append(PlaceBlock(bx, brazier_y, bz, "minecraft:campfire"))
                else:
                    ops.append(PlaceBlock(bx, base_y, bz, "minecraft:netherrack"))
                    ops.append(PlaceBlock(bx, brazier_y, bz, "minecraft:fire"))

    # ── 7) Chandeliers — 2-3 hanging lanterns along central axis ───────
    # They sit one cell below the conceptual ceiling row (y = y1 - 2),
    # marked as hanging so the renderer dangles them properly.
    lantern_y = a.y1 - 2
    if lantern_y > a.y0 + 1:
        if long_along_z:
            lpositions = _column_positions(a.z0 + 4, a.z1 - 2, target=3)
            for lz in lpositions:
                ops.append(PlaceBlock(
                    a.cx, lantern_y, lz, "minecraft:lantern[hanging=true]"
                ))
        else:
            lpositions = _column_positions(a.x0 + 4, a.x1 - 2, target=3)
            for lx in lpositions:
                ops.append(PlaceBlock(
                    lx, lantern_y, a.cz, "minecraft:lantern[hanging=true]"
                ))

    # ── 8) Banners — red_carpet blocks affixed to the long walls ───────
    # Hung high on the walls (mid-upper third of the hall), staggered along
    # the long axis. We over-paint the inner face of the wall (one cell in)
    # with red_carpet so it reads as fabric heraldry from the floor.
    banner_y = a.y0 + max(2, a.h - 3)
    if banner_y < a.y1 - 1:
        if long_along_z:
            bx_west = a.x0 + 1  # interior face of the west wall
            bx_east = a.x1 - 2  # interior face of the east wall
            bpositions = _column_positions(a.z0 + 5, a.z1 - 3, target=2)
            for bz in bpositions:
                if a.contains(bx_west, banner_y, bz):
                    ops.append(PlaceBlock(bx_west, banner_y, bz, "minecraft:red_carpet"))
                if a.contains(bx_east, banner_y, bz):
                    ops.append(PlaceBlock(bx_east, banner_y, bz, "minecraft:red_carpet"))
        else:
            bz_north = a.z0 + 1
            bz_south = a.z1 - 2
            bpositions = _column_positions(a.x0 + 5, a.x1 - 3, target=2)
            for bx in bpositions:
                if a.contains(bx, banner_y, bz_north):
                    ops.append(PlaceBlock(bx, banner_y, bz_north, "minecraft:red_carpet"))
                if a.contains(bx, banner_y, bz_south):
                    ops.append(PlaceBlock(bx, banner_y, bz_south, "minecraft:red_carpet"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────

def _column_positions(lo: int, hi: int, *, target: int) -> list[int]:
    """Return up to `target` evenly-spaced integer positions inside [lo, hi).

    Always returns at least one position when the span is non-empty. Used
    to space pillars, braziers, lanterns, and banners along the long axis.
    """
    span = hi - lo
    if span <= 0:
        return []
    n = max(1, min(target, span))
    if n == 1:
        return [lo + span // 2]
    step = span / n
    return [int(lo + step * (i + 0.5)) for i in range(n)]
