"""Skill: bridge_arched.

An arched stone bridge spanning a gap (typically over a moat, river, or
ravine) between two points. The AABB defines the straight span envelope;
the bridge length runs along the longer horizontal axis of the AABB and
the bridge width along the shorter. Composition (sketched in side view,
span along +u, width along +v, up = y):

         lantern        lantern        lantern        lantern
            ▲              ▲              ▲              ▲
       F R─────────────────────────────────────────────R F  ← walking
        P P P P P P P P P P P P P P P P P P P P P P P P     surface +
        P                                             P     railings
        P         arched soffit                       P
        S P                                       P S       ← stairs +
          S P                                   P S         primary form
            S P P P P P P P P P P P P P P P P P S           the curved
                                                            underside
       [pillar]                                [pillar]     ← support
       [pillar]                                [pillar]       posts of
                                                              @secondary

Where:
    * The walking surface is a flat `Rect` of @primary across the span at
      the top of the AABB. Width is clamped to 2-3.
    * The arched underside is 1-2 stone arches BELOW the walking surface.
      Each arch is built from @stairs blocks (upside-down on the
      ascending limbs so the slope reads as a soffit curving up to the
      deck) plus @primary infill near the apex/springers.
    * Two support pillars of @secondary at each end of the span, 2-3
      blocks tall, sitting under the walking surface where the arch
      meets the abutment.
    * Railings: a row of @fence on each side of the walking surface,
      one block above the deck.
    * 2-4 `minecraft:lantern` posts at intervals along the railings
      (replacing fence blocks with lanterns at evenly spaced points).
    * Optional @stairs ramps at the ends, going up to the bridge
      surface. Skipped on very short spans (< 6) since there is no room.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth. AABB is half-open.

Defensive sizing: clamped to 3×4×6 (small bridge) .. 5×6×16 (long
bridge). The clamp preserves the span axis — if w >= d the bridge runs
along x, otherwise along z. Inputs smaller than the minimum grow; inputs
larger than the maximum shrink.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive bounds on (short_horizontal, height, long_horizontal).
# Spec: 3×4×6 (small) to 5×6×16 (long).
_MIN_SHORT  = 3
_MAX_SHORT  = 5
_MIN_H      = 4
_MAX_H      = 6
_MIN_LONG   = 6
_MAX_LONG   = 16

# Walking deck width clamped to 2..3 regardless of AABB short axis (the
# rest of the short axis is given over to the arched flank stairs).
_DECK_W_MIN = 2
_DECK_W_MAX = 3


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB into the defensive envelope, preserving span axis."""
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
    """Build an arched bridge spanning the long horizontal axis of `aabb`.

    Kwargs are accepted but unused for now (future variants may toggle
    `with_ramps`, `arch_count`, etc.).
    """
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    # Determine span axis: along x if width >= depth, otherwise along z.
    span_along_x = a.w >= a.d

    # Resolve axis-agnostic limits. `u` runs along the span (length),
    # `v` runs across the bridge (width).
    if span_along_x:
        u0, u1 = a.x0, a.x1
        v0, v1 = a.z0, a.z1
    else:
        u0, u1 = a.z0, a.z1
        v0, v1 = a.x0, a.x1
    y0, y1 = a.y0, a.y1
    span_len = u1 - u0          # bridge length
    short_w  = v1 - v0          # full short-axis extent of the AABB
    height   = y1 - y0          # vertical envelope

    # Walking deck width centred on the short axis, clamped to 2..3.
    deck_w = max(_DECK_W_MIN, min(_DECK_W_MAX, short_w))
    deck_v0 = v0 + (short_w - deck_w) // 2
    deck_v1 = deck_v0 + deck_w  # half-open

    # Walking surface sits at the TOP of the AABB to leave room for the
    # arches below. y_deck is the topmost row.
    y_deck = y1 - 1

    # Stair facings for the arch flanks depend on the span axis. The
    # ascending-end stairs face TOWARD the apex (the centre of the
    # span); the descending-end stairs face the opposite way. For a
    # span along +x: left flank stairs face east, right flank face west.
    if span_along_x:
        ascend_left_face  = "east"   # +x toward apex from the u0 end
        ascend_right_face = "west"   # -x toward apex from the u1 end
    else:
        ascend_left_face  = "south"  # +z toward apex from the u0 end
        ascend_right_face = "north"  # -z toward apex from the u1 end

    def pb(u: int, y: int, v: int, block: str) -> PlaceBlock:
        """Place a block in span-coords, mapping back to (x, y, z)."""
        if span_along_x:
            return PlaceBlock(u, y, v, block)
        else:
            return PlaceBlock(v, y, u, block)

    def box(u_a: int, y_a: int, v_a: int,
            u_b: int, y_b: int, v_b: int) -> AABB:
        """Build an AABB from span-coords (half-open like the rest)."""
        if span_along_x:
            return AABB(u_a, y_a, v_a, u_b, y_b, v_b)
        else:
            return AABB(v_a, y_a, u_a, v_b, y_b, u_b)

    # ────────────────────────────────────────────────────────────────────
    # 1) Walking surface — flat @primary rectangle across the span at
    #    y_deck. Spans the full bridge length and the deck_w centre strip.
    # ────────────────────────────────────────────────────────────────────
    deck_box = box(u0, y_deck, deck_v0, u1, y_deck + 1, deck_v1)
    ops.append(Fill(deck_box, "@primary"))

    # ────────────────────────────────────────────────────────────────────
    # 2) Arched underside — @stairs forming a curve that rises from the
    #    end abutments toward the centre, and a flat @primary apex
    #    spanning the middle. The arch sits ONE row below the deck
    #    (y_arch_top = y_deck - 1), and dips by up to `arch_depth`
    #    blocks at the abutment ends. We build one arch per "arch_count"
    #    — 1 for short spans, 2 for longer spans (a double-arch bridge).
    # ────────────────────────────────────────────────────────────────────
    y_arch_top = y_deck - 1
    # Arch depth: how many blocks the arch dips below the deck top at the
    # abutments. We want 1..2 depending on the AABB height. Need at least
    # height >= 4 for arch_depth = 2.
    arch_depth = 2 if height >= 5 else 1

    # Determine arch count. 2 arches on long spans (>= 12), else 1.
    arch_count = 2 if span_len >= 12 else 1

    # For each arch segment, the stair "rise length" on each side is
    # arch_depth (since stairs go up 1 block per cell). The flat apex
    # between the two rising sides fills the rest of the arch span.
    # Compute each arch's (u_arch_lo, u_arch_hi) inclusive.
    if arch_count == 1:
        arches = [(u0, u1 - 1)]
    else:
        # Two arches splitting the span roughly in half. Leave 1 cell
        # at the join for a central pillar block on the underside.
        mid = (u0 + u1) // 2
        arches = [(u0, mid - 1), (mid + 1, u1 - 1)]

    # The "flank" v-positions are just outside the deck centre strip
    # (one cell on either side of the deck along the short axis). For a
    # deck centred on a 3-wide AABB the flanks coincide with the AABB
    # edges; for a 4- or 5-wide AABB the flanks sit one cell inside.
    flank_v_left  = deck_v0 - 1 if deck_v0 - 1 >= v0 else deck_v0
    flank_v_right = deck_v1     if deck_v1     <  v1 else deck_v1 - 1
    flank_vs = sorted({flank_v_left, deck_v0, deck_v1 - 1, flank_v_right})

    for (u_lo, u_hi) in arches:
        arch_span = u_hi - u_lo + 1
        if arch_span < 3:
            continue
        # Stair limb length on each side, capped so the two limbs don't
        # exceed the arch span (need at least 1 cell of flat apex).
        limb = min(arch_depth, (arch_span - 1) // 2)
        if limb < 1:
            limb = 1

        # Ascending limb on the u_lo side: cells [u_lo .. u_lo+limb-1]
        # rise from (y_arch_top - limb + 1) up to (y_arch_top). The
        # stair at cell i has its half = top (upside-down) and faces the
        # apex so its slope visually closes the underside.
        for i in range(limb):
            cur_y = y_arch_top - (limb - 1) + i
            for v_flank in flank_vs:
                ops.append(pb(u_lo + i, cur_y, v_flank,
                              f"@stairs[facing={ascend_left_face},half=top]"))
            # Also fill the deck-centre cells one row below the deck so
            # the underside reads as solid stone (not see-through).
            for v_mid in range(deck_v0, deck_v1):
                ops.append(pb(u_lo + i, cur_y, v_mid, "@primary"))

        # Descending limb on the u_hi side: mirror of the ascending side.
        for i in range(limb):
            cur_y = y_arch_top - (limb - 1) + i
            u_here = u_hi - i
            for v_flank in flank_vs:
                ops.append(pb(u_here, cur_y, v_flank,
                              f"@stairs[facing={ascend_right_face},half=top]"))
            for v_mid in range(deck_v0, deck_v1):
                ops.append(pb(u_here, cur_y, v_mid, "@primary"))

        # Flat apex in the middle (cells between the two limbs at
        # y_arch_top). This is a solid @primary band one row below the
        # deck — the structural keystone band of the arch.
        apex_lo = u_lo + limb
        apex_hi = u_hi - limb
        if apex_lo <= apex_hi:
            apex_box = box(apex_lo, y_arch_top, v0, apex_hi + 1, y_arch_top + 1, v1)
            ops.append(Fill(apex_box, "@primary"))

    # If we have two arches, drop a thin central pillar of @secondary
    # connecting the apex level down toward y0 at the gap cell between
    # the arches. This reads as the middle pier of a double-arch bridge.
    if arch_count == 2:
        mid_u = (u0 + u1) // 2
        # Pier height: from y0 up to y_arch_top - 1 inclusive (below
        # the deck so it doesn't merge with it). Use the deck columns.
        for y in range(y0, y_arch_top):
            for v_mid in range(deck_v0, deck_v1):
                ops.append(pb(mid_u, y, v_mid, "@secondary"))

    # ────────────────────────────────────────────────────────────────────
    # 3) Two support pillars of @secondary at the ends. Each pillar is
    #    2-3 tall under the bridge at the abutment cell. We place one
    #    pillar per side of the deck (so 2 columns at u0, 2 at u1-1)
    #    when the deck is 2-3 wide — the spec asks for "2" total but
    #    a real bridge has piers on both deck edges; we mirror them
    #    along the short axis to give the structure proper support
    #    while still being legible as "two pillars at each end".
    # ────────────────────────────────────────────────────────────────────
    pillar_height = 3 if height >= 5 else 2
    pillar_y_lo = y0
    pillar_y_hi = y0 + pillar_height  # half-open

    # End-cell u-coords (the abutments).
    end_us = [u0, u1 - 1]
    for u_end in end_us:
        for v_mid in range(deck_v0, deck_v1):
            for y in range(pillar_y_lo, pillar_y_hi):
                ops.append(pb(u_end, y, v_mid, "@secondary"))

    # ────────────────────────────────────────────────────────────────────
    # 4) Railings — @fence on both sides of the walking surface, one row
    #    above the deck (y = y_deck + 1). Railings run the full length
    #    of the span on each long edge of the deck.
    # ────────────────────────────────────────────────────────────────────
    y_rail = y_deck + 1
    rail_v_left  = deck_v0
    rail_v_right = deck_v1 - 1
    for u in range(u0, u1):
        ops.append(pb(u, y_rail, rail_v_left,  "@fence"))
        if rail_v_right != rail_v_left:
            ops.append(pb(u, y_rail, rail_v_right, "@fence"))

    # ────────────────────────────────────────────────────────────────────
    # 5) Lantern posts — 2-4 minecraft:lantern at intervals along the
    #    railings (replacing fence blocks). Always include the two ends
    #    of the bridge; add mid-points for longer spans.
    # ────────────────────────────────────────────────────────────────────
    # Pick lantern u positions: 2 for short spans, 3 for medium, 4 for long.
    if span_len >= 14:
        n_lanterns = 4
    elif span_len >= 10:
        n_lanterns = 3
    else:
        n_lanterns = 2
    # Evenly spaced positions including both ends.
    if n_lanterns == 2:
        lantern_us = [u0, u1 - 1]
    elif n_lanterns == 3:
        lantern_us = [u0, (u0 + u1 - 1) // 2, u1 - 1]
    else:
        step = (u1 - 1 - u0) / 3.0
        lantern_us = [int(round(u0 + i * step)) for i in range(4)]
    lantern_us = sorted(set(lantern_us))

    for u_lan in lantern_us:
        ops.append(pb(u_lan, y_rail, rail_v_left,  "minecraft:lantern"))
        if rail_v_right != rail_v_left:
            ops.append(pb(u_lan, y_rail, rail_v_right, "minecraft:lantern"))

    # ────────────────────────────────────────────────────────────────────
    # 6) Optional end ramps — @stairs ramps at the two ends going UP to
    #    the bridge surface from the ground level (y0). On short bridges
    #    we skip them since the deck sits low enough that pillars suffice.
    #    A single stair block per end, sitting at y_deck - 1 just outside
    #    the abutment, facing the bridge centre so the slope leads up.
    # ────────────────────────────────────────────────────────────────────
    if span_len >= 6 and y_deck - 1 >= y0 + pillar_height:
        # Ramp facing into the bridge.
        for v_mid in range(deck_v0, deck_v1):
            # Lower-end ramp (u = u0 - 0 visually, place at u0 just under
            # the deck so it reads as a stair leading up onto the deck).
            ops.append(pb(u0, y_deck - 1, v_mid,
                          f"@stairs[facing={ascend_left_face},half=bottom]"))
            ops.append(pb(u1 - 1, y_deck - 1, v_mid,
                          f"@stairs[facing={ascend_right_face},half=bottom]"))

    return ops
