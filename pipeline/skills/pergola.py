"""`pergola` skill — wooden arbor for outdoor sitting with climbing plants.

Layout strategy (AABB coordinate system in `base.py`):
    * Ground (y0): a full footprint of @floor blocks (medieval/fantasy use a
      mixed grass/floor combination — see `_ground_block`). The bench inside
      sits on top of this floor.
    * Posts: 4-6 columns of @primary at the corners and along the longer
      sides, spaced every ~3 blocks. Posts rise from y0 + 1 up to the top
      row (y1 - 1). The exact number is min(6, max(4, long_side / 2)).
    * Crossbeams: Line ops of @primary connecting opposite posts along the
      LONG axis at the very top (y1 - 1). One beam per post pair.
    * Climbing plants: 4-6 `minecraft:vine` blocks hanging from the beams,
      placed one row below the beam (y1 - 2) on alternating post pairs.
    * Lanterns: 1-2 `minecraft:lantern[hanging=true]` hanging from a central
      beam at y1 - 2.
    * Bench: a row of @stairs (facing inward) along one side at y0 + 1,
      spanning the inner length minus 2 (so it doesn't collide with posts).
    * Flower pots: 2-3 `minecraft:flower_pot` placed at perimeter corners
      on top of the floor (y0 + 1), tucked just inside the post columns.

Defensive sizing: clamped to 4×3×4 .. 12×5×12. The roof of the AABB is
open (no @roof fill) — a pergola is an open frame, not a closed pavilion.

Style note: the bench/post material follows @primary so style packs can
choose oak, smooth_stone, or dark_oak. The fantasy preset's @light is
sea_lantern (provided by `Materials.for_style`), so the hanging "lantern"
beneath the beam becomes a sea_lantern automatically — we use the literal
`minecraft:lantern` here for medieval/modern and switch via
`_lantern_block(style)` for fantasy. See the RAG entry for the
style_variants table.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Line, Materials, Op, PlaceBlock, Rect


# Defensive bounds, per spec (footprint 4×4 .. 12×12, height 3..5).
_MIN = (4, 3, 4)
_MAX = (12, 5, 12)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the defensive envelope.

    Keeps the lower corner fixed; shifts the upper corner so the size
    constraints hold. Tiny inputs grow to 4×3×4; huge inputs shrink to
    12×5×12.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def _ground_block(style: str) -> str:
    """Style-aware ground block id.

    medieval / default → grass_block (rustic lawn under the pergola)
    modern             → @floor (smooth polished surface)
    fantasy            → grass_block (mossy garden floor)
    """
    s = (style or "").lower()
    if s == "modern":
        return "@floor"
    return "minecraft:grass_block"


def _lantern_block(style: str) -> str:
    """Style-aware hanging light block id.

    fantasy → sea_lantern (no `hanging` state — it's a full solid block)
    others  → minecraft:lantern[hanging=true]
    """
    s = (style or "").lower()
    if s == "fantasy":
        return "minecraft:sea_lantern"
    return "minecraft:lantern[hanging=true]"


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a pergola (open wooden arbor) inside the given AABB."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    x0, y0, z0 = a.x0, a.y0, a.z0
    x1, y1, z1 = a.x1, a.y1, a.z1
    w, d = a.w, a.d
    top_y = y1 - 1  # beams and roof of frame
    beam_under_y = y1 - 2  # vines/lantern hang one row below the beam

    # ──────────────────── 1) Ground floor at y0 ──────────────────
    # Full rectangle covering the AABB footprint.
    ground = _ground_block(style)
    ops.append(
        Rect(
            AABB(x0, y0, z0, x1, y0 + 1, z1),
            ground,
            axis="y",
            level=y0,
        )
    )

    # ──────────────────── 2) Posts at corners + along long sides ─
    # The long axis is whichever of w/d is bigger (ties prefer x).
    long_axis_x = w >= d
    # Post coordinates along the long axis: corners + intermediates every
    # ~3 blocks. We aim for 4..6 posts on each long edge — but a pergola
    # has 4-6 posts TOTAL, so we mirror them on both edges of the short
    # axis and pick 2..3 positions along the long axis.
    if long_axis_x:
        long_lo, long_hi = x0, x1 - 1
        short_lo, short_hi = z0, z1 - 1
    else:
        long_lo, long_hi = z0, z1 - 1
        short_lo, short_hi = x0, x1 - 1

    long_len = (long_hi - long_lo) + 1
    # Pick post positions along the long axis. Always include the two
    # endpoints; add 1 mid-post if length ≥ 7, 2 mid-posts if length ≥ 10.
    post_positions: list[int] = [long_lo, long_hi]
    if long_len >= 10:
        third = (long_hi - long_lo) // 3
        post_positions.insert(1, long_lo + third)
        post_positions.insert(2, long_lo + 2 * third)
    elif long_len >= 7:
        mid = (long_lo + long_hi) // 2
        post_positions.insert(1, mid)
    # Total post count = len(post_positions) * 2 (both short edges).
    # That gives 4 (2×2) for small, 6 (3×2) for medium, 8 capped to 6.
    if len(post_positions) > 3:
        # Cap to 3 along the long axis → 6 total posts.
        post_positions = [post_positions[0], post_positions[len(post_positions) // 2], post_positions[-1]]

    # Posts go from y0 + 1 up to top_y inclusive.
    post_pairs: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for lp in post_positions:
        if long_axis_x:
            p_a = (lp, short_lo)  # (x, z)
            p_b = (lp, short_hi)
        else:
            p_a = (short_lo, lp)
            p_b = (short_hi, lp)
        post_pairs.append((p_a, p_b))
        for (px, pz) in (p_a, p_b):
            for y in range(y0 + 1, top_y + 1):
                ops.append(PlaceBlock(px, y, pz, "@primary"))

    # ──────────────────── 3) Crossbeams at the top ───────────────
    # One beam per post pair, spanning the short axis at y = top_y.
    for (p_a, p_b) in post_pairs:
        ax, az = p_a
        bx, bz = p_b
        ops.append(Line(ax, top_y, az, bx, top_y, bz, "@primary"))

    # Also add two longitudinal beams along the long axis connecting the
    # tops of the corner posts on each short edge — this completes the
    # frame so vines have something to hang from along the full length.
    if long_axis_x:
        # Beam along x at z = short_lo and at z = short_hi, top row.
        ops.append(Line(x0, top_y, short_lo, x1 - 1, top_y, short_lo, "@primary"))
        ops.append(Line(x0, top_y, short_hi, x1 - 1, top_y, short_hi, "@primary"))
    else:
        ops.append(Line(short_lo, top_y, z0, short_lo, top_y, z1 - 1, "@primary"))
        ops.append(Line(short_hi, top_y, z0, short_hi, top_y, z1 - 1, "@primary"))

    # ──────────────────── 4) Climbing vines from the beams ───────
    # Place 4-6 vines descending from the longitudinal beams (y = top_y),
    # one row below (y = beam_under_y), at evenly spaced positions along
    # the long axis. Skip cells where a post already lives.
    vine_targets: list[tuple[int, int, int]] = []
    if long_len >= 6:
        vine_positions_long = [
            long_lo + 1,
            long_lo + (long_len // 3),
            long_lo + (2 * long_len // 3),
            long_hi - 1,
        ]
    else:
        vine_positions_long = [long_lo + 1, long_hi - 1]
    # Mirror on both short edges (so vines drape from both long beams).
    for lp in vine_positions_long:
        if long_axis_x:
            vine_targets.append((lp, beam_under_y, short_lo))
            vine_targets.append((lp, beam_under_y, short_hi))
        else:
            vine_targets.append((short_lo, beam_under_y, lp))
            vine_targets.append((short_hi, beam_under_y, lp))

    # Dedup + cap at 6 vines.
    seen: set[tuple[int, int, int]] = set()
    placed_vines = 0
    for (vx, vy, vz) in vine_targets:
        if placed_vines >= 6:
            break
        key = (vx, vy, vz)
        if key in seen:
            continue
        seen.add(key)
        # Avoid stamping a vine onto a post cell (posts occupy short_lo /
        # short_hi at every post_positions[i] along the long axis).
        is_post_cell = False
        for (p_a, p_b) in post_pairs:
            if (vx, vz) in (p_a, p_b):
                is_post_cell = True
                break
        if is_post_cell:
            continue
        ops.append(PlaceBlock(vx, vy, vz, "minecraft:vine"))
        placed_vines += 1

    # If we placed fewer than 4 (very small AABB), force a few extras at
    # interior cells just under the central beam crossings.
    if placed_vines < 4:
        cx = (x0 + x1 - 1) // 2
        cz = (z0 + z1 - 1) // 2
        for (vx, vz) in [(cx, z0 + 1), (cx, z1 - 2), (x0 + 1, cz), (x1 - 2, cz)]:
            if placed_vines >= 4:
                break
            key = (vx, beam_under_y, vz)
            if key in seen:
                continue
            seen.add(key)
            ops.append(PlaceBlock(vx, beam_under_y, vz, "minecraft:vine"))
            placed_vines += 1

    # ──────────────────── 5) Hanging lanterns ────────────────────
    # 1-2 lanterns suspended from a central crossbeam at y = beam_under_y.
    lantern_block = _lantern_block(style)
    cx = (x0 + x1 - 1) // 2
    cz = (z0 + z1 - 1) // 2
    # Primary central lantern.
    ops.append(PlaceBlock(cx, beam_under_y, cz, lantern_block))
    # Optional second lantern when there's room along the long axis.
    if long_len >= 7:
        if long_axis_x:
            second_x = (x0 + cx) // 2
            ops.append(PlaceBlock(second_x, beam_under_y, cz, lantern_block))
        else:
            second_z = (z0 + cz) // 2
            ops.append(PlaceBlock(cx, beam_under_y, second_z, lantern_block))

    # ──────────────────── 6) Wooden bench inside ─────────────────
    # A row of @stairs along one of the short edges (inside the posts).
    # The bench sits at y0 + 1, facing inward. We pick the +z edge by
    # default (or +x if pergola is short-axis-x oriented).
    # `@stairs[facing=...]` is not resolved by _resolve (the `[` breaks
    # the key lookup), so we pre-resolve the stairs block id here and
    # append the facing state ourselves — mirroring how the `Stairs` op
    # builds its block strings.
    bench_y = y0 + 1
    stairs_id = materials.stairs  # resolved namespaced id (e.g. minecraft:oak_stairs)
    if long_axis_x:
        # Bench runs along x at z = z0 + 1 (just inside the post row at z0),
        # spanning from x0 + 1 to x1 - 2 inclusive. Facing south (+z) so
        # the half-step looks inward toward the centre.
        bz = z0 + 1
        if bz < z1 - 1 and bz != z0:
            bench_block = f"{stairs_id}[facing=south]"
            for bx in range(x0 + 1, x1 - 1):
                ops.append(PlaceBlock(bx, bench_y, bz, bench_block))
    else:
        bx = x0 + 1
        if bx < x1 - 1 and bx != x0:
            bench_block = f"{stairs_id}[facing=east]"
            for bz in range(z0 + 1, z1 - 1):
                ops.append(PlaceBlock(bx, bench_y, bz, bench_block))

    # ──────────────────── 7) Flower pots at the perimeter ────────
    # 2-3 flower_pot blocks tucked at the corners (just inside posts) on
    # the OPPOSITE short edge from the bench, on top of the ground floor.
    pot_y = y0 + 1
    pots_placed = 0
    if long_axis_x:
        # Opposite edge: z = z1 - 2 (just inside the far post row).
        candidates = [
            (x0 + 1, pot_y, z1 - 2),
            (x1 - 2, pot_y, z1 - 2),
            ((x0 + x1 - 1) // 2, pot_y, z1 - 2),
        ]
    else:
        candidates = [
            (x1 - 2, pot_y, z0 + 1),
            (x1 - 2, pot_y, z1 - 2),
            (x1 - 2, pot_y, (z0 + z1 - 1) // 2),
        ]
    # Pick 2 pots for small pergolas, 3 for medium+.
    pot_cap = 3 if long_len >= 7 else 2
    for (px, py, pz) in candidates:
        if pots_placed >= pot_cap:
            break
        # Don't stamp on top of a post.
        is_post_cell = any((px, pz) in (p_a, p_b) for (p_a, p_b) in post_pairs)
        if is_post_cell:
            continue
        ops.append(PlaceBlock(px, py, pz, "minecraft:flower_pot"))
        pots_placed += 1

    return ops


# Linter friendliness: Fill is reserved for future variants (e.g. a
# fully-paved patio underfoot instead of grass).
_ = Fill
