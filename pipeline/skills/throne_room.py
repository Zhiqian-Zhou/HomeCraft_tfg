"""Throne room skill — small ceremonial throne chamber.

Builds a compact, intimate audience chamber — distinct from great_hall by
being SMALLER (6×4×7 .. 10×6×14 envelope), fully enclosed (slab ceiling),
and reading as a private throne room rather than a long ceremonial hall.

Layout (assumes the long axis runs along z; the throne sits at the FAR
short wall, z = z0, and the entrance is at the NEAR short wall, z = z1-1):

    z0    .   B  T  B  .          ← banner | throne on dais | banner
          C [ ]    [ ] C          ← @accent columns flanking the throne
          .   ░    ░   .          ← chest tucked next to throne
          .   ▓▓▓▓▓▓   .          ← carpet runner (5-6 long)
          ░   ░    ░   ░          ← side benches against the long walls
    z1-1  .   .  .  .   .         ← entrance side

Ceiling is a flat @slab lid; 2-3 hanging lanterns dangle below it.

Defensive on AABBs from 6×4×7 up to 10×6×14. Anything smaller still emits
the shell + throne if room allows; anything larger is clamped to the
envelope so the throne room never bloats into a great-hall-sized space.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive envelope: the throne room is intentionally small.
_MIN_W, _MIN_H, _MIN_D = 6, 4, 7
_MAX_W, _MAX_H, _MAX_D = 10, 6, 14


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [6×4×7 .. 10×6×14] envelope.

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

    # The throne room is "long" along whichever horizontal axis dominates.
    # Throne sits on the FAR short wall (z = z0 when long-along-z; x = x0
    # otherwise). Entrance is on the OPPOSITE short wall.
    long_along_z = a.d >= a.w

    # ── 1) Floor plane ─────────────────────────────────────────────────
    ops.append(Rect(a, "@floor", axis="y", level=a.y0))

    # ── 2) Four walls (no ceiling yet) rising y0+1 .. y1-1 ─────────────
    # We leave the ceiling row free so the next step can lay a @slab lid.
    wall_y0 = a.y0 + 1
    wall_y1 = a.y1 - 1
    if wall_y1 > wall_y0:
        # North wall (z = z0)
        ops.append(Fill(AABB(a.x0, wall_y0, a.z0, a.x1, wall_y1, a.z0 + 1), "@primary"))
        # South wall (z = z1-1)
        ops.append(Fill(AABB(a.x0, wall_y0, a.z1 - 1, a.x1, wall_y1, a.z1), "@primary"))
        # West wall (x = x0)
        ops.append(Fill(AABB(a.x0, wall_y0, a.z0, a.x0 + 1, wall_y1, a.z1), "@primary"))
        # East wall (x = x1-1)
        ops.append(Fill(AABB(a.x1 - 1, wall_y0, a.z0, a.x1, wall_y1, a.z1), "@primary"))

    # ── 3) Flat @slab ceiling lid ──────────────────────────────────────
    # A single-plane lid of @slab. This is the main distinguishing
    # feature vs. great_hall's open-top — it makes the room feel
    # intimate and enclosed.
    ceiling_y = a.y1 - 1
    if ceiling_y > a.y0:
        ops.append(Rect(a, "@slab", axis="y", level=ceiling_y))

    # ── 4) Throne dais (1-block raised @accent) ────────────────────────
    # The dais is a 3-wide × 2-deep platform of @accent rising 1 block
    # above the floor. It sits flush against the far short wall.
    interior_y = a.y0 + 1
    if long_along_z:
        dais_cx = a.cx
        dais_x0 = max(a.x0 + 1, dais_cx - 1)
        dais_x1 = min(a.x1 - 1, dais_cx + 2)
        dais_z0 = a.z0 + 1
        dais_z1 = min(a.z1 - 1, dais_z0 + 2)
    else:
        dais_cz = a.cz
        dais_z0 = max(a.z0 + 1, dais_cz - 1)
        dais_z1 = min(a.z1 - 1, dais_cz + 2)
        dais_x0 = a.x0 + 1
        dais_x1 = min(a.x1 - 1, dais_x0 + 2)
    dais_top_y = interior_y  # the dais occupies just this one row
    if dais_x1 > dais_x0 and dais_z1 > dais_z0:
        ops.append(Fill(
            AABB(dais_x0, interior_y, dais_z0,
                 dais_x1, interior_y + 1, dais_z1),
            "@accent",
        ))

    # ── 5) Throne — single @stairs block centered on the dais ──────────
    # Facing INTO the room (toward the entrance wall).
    throne_y = dais_top_y + 1
    if long_along_z:
        throne_x = (dais_x0 + dais_x1 - 1) // 2
        # The dais center along z (we want the throne block to sit on
        # the dais top, ideally the cell furthest from the entrance).
        throne_z = dais_z0
        # Throne faces +z (south) — toward the entrance.
        ops.append(PlaceBlock(throne_x, throne_y, throne_z, "@stairs[facing=south]"))
    else:
        throne_z = (dais_z0 + dais_z1 - 1) // 2
        throne_x = dais_x0
        # Throne faces +x (east) — toward the entrance.
        ops.append(PlaceBlock(throne_x, throne_y, throne_z, "@stairs[facing=east]"))

    # ── 6) Two @accent columns flanking the throne (1×3 tall each) ─────
    # Columns rise from the floor up to interior_y + 2 (a stocky 3-block
    # column befitting a small chamber). They sit one cell to either
    # side of the dais.
    col_y0 = interior_y
    col_y1 = min(a.y1 - 1, interior_y + 3)
    if col_y1 > col_y0:
        if long_along_z:
            col_z = dais_z1  # one cell in front of the dais (toward entrance)
            col_xL = dais_x0 - 1
            col_xR = dais_x1
            if col_xL > a.x0 and a.contains(col_xL, col_y0, col_z):
                ops.append(Fill(
                    AABB(col_xL, col_y0, col_z, col_xL + 1, col_y1, col_z + 1),
                    "@accent",
                ))
            if col_xR < a.x1 - 1 and a.contains(col_xR, col_y0, col_z):
                ops.append(Fill(
                    AABB(col_xR, col_y0, col_z, col_xR + 1, col_y1, col_z + 1),
                    "@accent",
                ))
        else:
            col_x = dais_x1
            col_zN = dais_z0 - 1
            col_zS = dais_z1
            if col_zN > a.z0 and a.contains(col_x, col_y0, col_zN):
                ops.append(Fill(
                    AABB(col_x, col_y0, col_zN, col_x + 1, col_y1, col_zN + 1),
                    "@accent",
                ))
            if col_zS < a.z1 - 1 and a.contains(col_x, col_y0, col_zS):
                ops.append(Fill(
                    AABB(col_x, col_y0, col_zS, col_x + 1, col_y1, col_zS + 1),
                    "@accent",
                ))

    # ── 7) Banners — 2× @carpet on the far wall flanking the throne ────
    # We use @carpet on the interior face of the far short wall as a
    # banner proxy (the great_hall convention). They sit ABOVE the
    # throne, in the upper-mid wall.
    banner_y = min(a.y1 - 2, interior_y + 1)
    if banner_y > interior_y:
        if long_along_z:
            banner_z = a.z0 + 1  # interior face of the far short wall
            banner_xL = dais_x0 - 1
            banner_xR = dais_x1
            if a.contains(banner_xL, banner_y, banner_z):
                ops.append(PlaceBlock(banner_xL, banner_y, banner_z, "@carpet"))
            if a.contains(banner_xR, banner_y, banner_z):
                ops.append(PlaceBlock(banner_xR, banner_y, banner_z, "@carpet"))
        else:
            banner_x = a.x0 + 1
            banner_zN = dais_z0 - 1
            banner_zS = dais_z1
            if a.contains(banner_x, banner_y, banner_zN):
                ops.append(PlaceBlock(banner_x, banner_y, banner_zN, "@carpet"))
            if a.contains(banner_x, banner_y, banner_zS):
                ops.append(PlaceBlock(banner_x, banner_y, banner_zS, "@carpet"))

    # ── 8) Short @carpet runner — door → throne (5-6 blocks) ───────────
    # Single cell wide. Starts one cell in front of the dais and runs
    # 5-6 cells toward the entrance.
    runner_len_target = 6 if (a.d if long_along_z else a.w) >= 10 else 5
    if long_along_z:
        runner_x = a.cx
        runner_z0 = dais_z1  # start at the foot of the dais
        runner_z1 = min(a.z1 - 1, runner_z0 + runner_len_target)
        if runner_z1 > runner_z0:
            ops.append(Fill(
                AABB(runner_x, interior_y, runner_z0,
                     runner_x + 1, interior_y + 1, runner_z1),
                "@carpet",
            ))
    else:
        runner_z = a.cz
        runner_x0 = dais_x1
        runner_x1 = min(a.x1 - 1, runner_x0 + runner_len_target)
        if runner_x1 > runner_x0:
            ops.append(Fill(
                AABB(runner_x0, interior_y, runner_z,
                     runner_x1, interior_y + 1, runner_z + 1),
                "@carpet",
            ))

    # ── 9) Side benches — @stairs against the long walls ───────────────
    # 2-4 benches total (one or two per wall), facing inward.
    # We place them just inside the long walls, halfway along the runner.
    bench_y = interior_y
    if long_along_z:
        # Long walls are at x = x0 (west) and x = x1 - 1 (east).
        bench_xL = a.x0 + 1  # interior cell against west wall
        bench_xR = a.x1 - 2  # interior cell against east wall
        bench_positions = _bench_positions_z(a, dais_z1, a.z1 - 1)
        for bz in bench_positions:
            if a.contains(bench_xL, bench_y, bz):
                # West bench faces east (+x toward room center)
                ops.append(PlaceBlock(
                    bench_xL, bench_y, bz, "@stairs[facing=east]"
                ))
            if a.contains(bench_xR, bench_y, bz):
                # East bench faces west (-x toward room center)
                ops.append(PlaceBlock(
                    bench_xR, bench_y, bz, "@stairs[facing=west]"
                ))
    else:
        bench_zN = a.z0 + 1
        bench_zS = a.z1 - 2
        bench_positions = _bench_positions_z(a, dais_x1, a.x1 - 1)
        # Re-shape: in this branch we walk along x not z.
        bench_positions_x = _column_positions(dais_x1 + 1, a.x1 - 2, target=2)
        for bx in bench_positions_x:
            if a.contains(bx, bench_y, bench_zN):
                ops.append(PlaceBlock(
                    bx, bench_y, bench_zN, "@stairs[facing=south]"
                ))
            if a.contains(bx, bench_y, bench_zS):
                ops.append(PlaceBlock(
                    bx, bench_y, bench_zS, "@stairs[facing=north]"
                ))

    # ── 10) Hanging lanterns — 2-3 along central axis, below ceiling ───
    # Lanterns hang one cell BELOW the slab ceiling, aligned over the
    # carpet runner so they read as a row of pendant lights.
    lantern_y = ceiling_y - 1
    if lantern_y > interior_y:
        if long_along_z:
            l_positions = _column_positions(dais_z1, a.z1 - 2, target=3)
            for lz in l_positions:
                if a.contains(a.cx, lantern_y, lz):
                    ops.append(PlaceBlock(
                        a.cx, lantern_y, lz, "minecraft:lantern[hanging=true]"
                    ))
        else:
            l_positions = _column_positions(dais_x1, a.x1 - 2, target=3)
            for lx in l_positions:
                if a.contains(lx, lantern_y, a.cz):
                    ops.append(PlaceBlock(
                        lx, lantern_y, a.cz, "minecraft:lantern[hanging=true]"
                    ))

    # ── 11) Treasure chest next to the throne ──────────────────────────
    # Tucked just to the side of the dais — on the floor, at column
    # height, on the throne side of the foot of the dais.
    chest_y = interior_y
    chest_placed = False
    if long_along_z:
        # Prefer cell just outside the dais on the east side, at the
        # back of the dais (closest to the throne wall).
        chest_candidates = [
            (dais_x1, chest_y, dais_z0),   # east of the dais, throne row
            (dais_x0 - 1, chest_y, dais_z0),  # west of the dais, throne row
        ]
    else:
        chest_candidates = [
            (dais_x0, chest_y, dais_z1),
            (dais_x0, chest_y, dais_z0 - 1),
        ]
    for (cx, cy, cz) in chest_candidates:
        if a.contains(cx, cy, cz):
            ops.append(PlaceBlock(cx, cy, cz, "minecraft:chest"))
            chest_placed = True
            break
    if not chest_placed:
        # Last resort: drop the chest at the front-left interior corner.
        cx = a.x0 + 1
        cz = a.z0 + 1
        if a.contains(cx, chest_y, cz):
            ops.append(PlaceBlock(cx, chest_y, cz, "minecraft:chest"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────

def _column_positions(lo: int, hi: int, *, target: int) -> list[int]:
    """Return up to `target` evenly-spaced integer positions inside [lo, hi).

    Always returns at least one position when the span is non-empty. Used
    to space lanterns and benches along the long axis.
    """
    span = hi - lo
    if span <= 0:
        return []
    n = max(1, min(target, span))
    if n == 1:
        return [lo + span // 2]
    step = span / n
    return [int(lo + step * (i + 0.5)) for i in range(n)]


def _bench_positions_z(a: AABB, lo: int, hi: int) -> list[int]:
    """Pick 1-2 bench positions inside (lo, hi), biased toward the runner.

    Returns up to 2 cells along z (or x in the orthogonal branch). The
    caller is responsible for mapping these into the correct axis.
    """
    return _column_positions(lo + 1, hi - 1, target=2)
