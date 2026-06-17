"""Skill: drawbridge.

A straight wooden span across a moat (the moat being the sibling skill).
The drawbridge here is drawn in a *partially-lifted* pose: the deck is flat
at y0, two chains rise from the outer (far) end up to anchor points at the
inner (building-side) end, and two anchor posts (each 2 blocks tall, capped
with a lantern) define the bridge mouth.

Layout (looking from above, '+x' = span direction by default):

        outer end (water side)            inner end (building side)
        ┌──────────────────────────────────────────────┐
        │ chain                                  ANCHOR │  ← 2-tall @accent post
        │  \\                                          │     + lantern on top
        │   \\                                         │
        │    \\          planks floor                  │
        │     \\                                       │
        │      \\                                ANCHOR │  ← 2-tall @accent post
        │ chain                                         │     + lantern on top
        └──────────────────────────────────────────────┘

Key choices (matches the spec):
    * Length = max(W, D), running along whichever horizontal axis is longer
      (ties → x). Width = clamp(min(W, D), 2, 3).
    * Floor planks: a `Fill` of @primary across the full deck at y0.
    * Two slanted chains (iron_bars) on each long side: each chain starts
      from the outer-end railing post at y0 + 1 and rises one block per
      step inward, terminating at the top of the inner anchor post.
    * Two anchor posts at the inner end, one on each side of the width
      axis. Each is 2 @accent blocks tall starting at y0 + 1, with a
      `minecraft:lantern` on top.
    * Optional decorative "bumps" — every 2 blocks along the outer side
      of the deck we lift a plank as a stairs block facing OUTWARD (away
      from the bridge centreline). Pure visual texturing; disabled when
      the span is shorter than 6 blocks since there isn't room for a
      proper rhythm.

Coordinate convention matches `base.py`:
    x: width, y: height (up), z: depth. AABB is half-open.

Defensive sizing: clamped to 2×3×4 .. 3×6×12 on the (short × h × long)
axes. The clamp preserves the orientation: if the caller's AABB is wider
than deep we keep the span along x; if it's deeper than wide we put the
span along z.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock


# Defensive bounds on (short_horizontal, height, long_horizontal).
# Spec: 2×3×4 to 3×6×12. The first dim is bridge width (2..3), the
# second is the AABB height (3..6, providing headroom for the chains
# and lanterns), the third is the bridge length (4..12).
_MIN_SHORT  = 2
_MAX_SHORT  = 3
_MIN_H      = 3
_MAX_H      = 6
_MIN_LONG   = 4
_MAX_LONG   = 12


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB to defensive bounds while preserving the span axis.

    The long horizontal axis (`max(w, d)`) becomes the bridge length; the
    short one becomes the bridge width. If the caller passes w == d, we
    keep the original axes (span ends up along x).
    """
    w, h, d = aabb.w, aabb.h, aabb.d
    if w >= d:
        # Span runs along x.
        long_clamped  = max(_MIN_LONG,  min(_MAX_LONG,  w))
        short_clamped = max(_MIN_SHORT, min(_MAX_SHORT, d))
        h_clamped     = max(_MIN_H,     min(_MAX_H,     h))
        return AABB(aabb.x0, aabb.y0, aabb.z0,
                    aabb.x0 + long_clamped,
                    aabb.y0 + h_clamped,
                    aabb.z0 + short_clamped)
    else:
        # Span runs along z.
        long_clamped  = max(_MIN_LONG,  min(_MAX_LONG,  d))
        short_clamped = max(_MIN_SHORT, min(_MAX_SHORT, w))
        h_clamped     = max(_MIN_H,     min(_MAX_H,     h))
        return AABB(aabb.x0, aabb.y0, aabb.z0,
                    aabb.x0 + short_clamped,
                    aabb.y0 + h_clamped,
                    aabb.z0 + long_clamped)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a wooden drawbridge spanning the long horizontal axis of `aabb`."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # Determine span axis: along x if width >= depth, otherwise along z.
    span_along_x = a.w >= a.d

    # Resolve axis-agnostic limits. `u` is the *span* coordinate (length of
    # the bridge), `v` is the *width* coordinate (across the bridge).
    if span_along_x:
        u0, u1 = a.x0, a.x1   # span runs from u0 (outer) → u1 (inner)
        v0, v1 = a.z0, a.z1
    else:
        u0, u1 = a.z0, a.z1
        v0, v1 = a.x0, a.x1
    y0, y1 = a.y0, a.y1
    span_len = u1 - u0
    width    = v1 - v0

    def pb(u: int, y: int, v: int, block: str) -> PlaceBlock:
        """Place a block in span-coords, mapping back to (x, y, z)."""
        if span_along_x:
            return PlaceBlock(u, y, v, block)
        else:
            return PlaceBlock(v, y, u, block)

    # ────────────────────────────────────────────────────────────────────
    # 1) Floor planks: a flat rectangle of @primary at y0 covering the full
    #    deck. We use `Fill` of a 1-tall AABB so the composer sees this as
    #    a single op (helpful for material attribution in the RAG).
    # ────────────────────────────────────────────────────────────────────
    if span_along_x:
        deck_box = AABB(u0, y0, v0, u1, y0 + 1, v1)
    else:
        deck_box = AABB(v0, y0, u0, v1, y0 + 1, u1)
    ops.append(Fill(deck_box, "@primary"))

    # ────────────────────────────────────────────────────────────────────
    # 2) Anchor posts at the inner end (u = u1 - 1). One on each side of
    #    the width axis. Each post is 2 @accent blocks tall starting at
    #    y0 + 1, with a `minecraft:lantern` on top.
    # ────────────────────────────────────────────────────────────────────
    inner_u = u1 - 1
    # Anchor side v-coords: outermost cells in width.
    v_left, v_right = v0, v1 - 1
    post_y0 = y0 + 1
    post_y1 = y0 + 2
    lantern_y = y0 + 3
    # Don't exceed AABB height for the post body; lantern is allowed to sit
    # at y0+3 since lanterns above the AABB envelope are a documented
    # convention (see garden_bed for prior art).
    for v_side in (v_left, v_right):
        ops.append(pb(inner_u, post_y0, v_side, "@accent"))
        ops.append(pb(inner_u, post_y1, v_side, "@accent"))
        ops.append(pb(inner_u, lantern_y, v_side, "minecraft:lantern"))

    # ────────────────────────────────────────────────────────────────────
    # 3) Slanted chains. Two chains, one per side. Each starts at the
    #    OUTER end (u = u0) at y0 + 1 (just above the deck) and rises
    #    one block per step toward the inner anchor, capping at the top
    #    of the anchor post (y = post_y1 = y0 + 2). When the span is
    #    longer than the available rise (2), we keep the chain at the
    #    anchor height for the remaining inner stretch — visually this
    #    reads as "chain slack already pulled taut and looping to the
    #    winch up top".
    #
    #    Block: minecraft:iron_bars (literal). The chain is 1 cell inset
    #    from the anchor post (v = v_left + 1 / v_right - 1) on the
    #    interior side so it doesn't merge with the post.
    # ────────────────────────────────────────────────────────────────────
    chain_v_left  = v_left  + 1 if width >= 3 else v_left
    chain_v_right = v_right - 1 if width >= 3 else v_right
    chain_block = "minecraft:iron_bars"

    rise_target_y = post_y1  # y0 + 2 — top of anchor post
    start_y = y0 + 1         # one block above the deck

    for v_chain in (chain_v_left, chain_v_right):
        # Walk the chain from outer (u0) to inner (inner_u - 1), one block
        # per cell, ramping the y by 1 per step until we hit `rise_target_y`.
        cur_y = start_y
        for step in range(span_len - 1):  # last cell is the anchor itself
            u_here = u0 + step
            ops.append(pb(u_here, cur_y, v_chain, chain_block))
            if cur_y < rise_target_y:
                cur_y += 1
        # Snap the final chain link onto the anchor post-top (we don't
        # overwrite the post itself — the chain ends adjacent to it).

    # ────────────────────────────────────────────────────────────────────
    # 4) Optional decorative bumps: every 2 blocks along the outer edge
    #    of the deck we lift a plank as a stairs block facing OUTWARD,
    #    away from the bridge centreline. Skipped on short spans (< 6).
    #
    #    Stairs face along the width axis: the left side (v = v_left)
    #    faces "outward" toward -v (i.e. west when span_along_x, else
    #    north). The right side faces the opposite cardinal.
    # ────────────────────────────────────────────────────────────────────
    if span_len >= 6 and width >= 3:
        # Pick stair facings per side, axis-aware.
        if span_along_x:
            left_facing  = "north"   # -z side faces north (away from deck)
            right_facing = "south"   # +z side faces south
        else:
            left_facing  = "west"    # -x side faces west
            right_facing = "east"    # +x side faces east

        # Bump positions: u = u0 + 2, u0 + 4, ... up to two cells short of
        # the inner anchor so we don't clip into the post column.
        bump_y = y0 + 1
        u_step = 2
        u_cur = u0 + u_step
        while u_cur <= u1 - 3:
            # Left-side bump (outermost row on the −v face of the deck).
            ops.append(pb(u_cur, bump_y, v_left,
                          f"@stairs[facing={left_facing},half=bottom]"))
            # Right-side bump (outermost row on the +v face).
            ops.append(pb(u_cur, bump_y, v_right,
                          f"@stairs[facing={right_facing},half=bottom]"))
            u_cur += u_step

    return ops
