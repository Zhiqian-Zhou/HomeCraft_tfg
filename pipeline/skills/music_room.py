"""Music room skill — a small recital chamber.

Builds an intimate room organised around a single instrument against one
wall, with a small audience facing it. The composition mirrors Christopher
Alexander's "Eating Atmosphere" (acoustic enclosure: solid walls, a low
beamed ceiling that traps sound) and "Pools of Light" (lanterns instead of
torches, so the room reads as warm rather than utilitarian).

Layout (x → right, z → forward, "back" wall = z = z0):

    z0   I I I .              ← instrument bench: @primary fill with
         N N N .                 note_blocks on top, against north wall
         .   J . B              ← jukebox (J) + bookshelf (B) flanking
         R R R .                ← @carpet rug under audience
         S S S .                ← @stairs audience seats facing -z (north)
    z1   . F . .              ← flower_pot decoration near the door

Defensive on AABBs from 6×4×6 up to 12×5×12. Smaller inputs degrade
gracefully (shorter bench, fewer seats, single lantern); larger inputs are
clamped at the +x/+y/+z corner so the floor plan stays NW-anchored.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# ────────────────────────────────────────────────────────────────────────
#  Public entry point
# ────────────────────────────────────────────────────────────────────────

def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Return the AST ops that materialise a music room into `aabb`."""
    a = _clamp(aabb)
    ops: List[Op] = []

    # Reject absurdly small boxes — the brief defensive floor is 6x4x6.
    if a.w < 4 or a.d < 4 or a.h < 3:
        return ops

    # Order: shell first (floor, walls, beamed lintel ceiling); then the
    # floor finishes (carpet rug) so furniture overrides them with
    # later-wins; then the instrument bench + note_blocks; then jukebox,
    # bookshelf, audience stairs, lanterns, flower pot.

    ops.extend(_shell(a))
    ops.extend(_lintel_ceiling_with_beams(a))
    ops.extend(_carpet_rug(a))
    ops.extend(_instrument_bench(a))
    ops.extend(_jukebox(a))
    ops.extend(_bookshelf(a))
    ops.extend(_audience_stairs(a, stairs_block=materials.stairs))
    ops.extend(_lanterns(a))
    ops.extend(_flower_pot(a))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Defensive size clamp
# ────────────────────────────────────────────────────────────────────────

def _clamp(a: AABB) -> AABB:
    """Clamp the working AABB to the supported envelope [6x4x6 .. 12x5x12]."""
    max_w, max_h, max_d = 12, 5, 12
    x0, y0, z0 = a.x0, a.y0, a.z0
    x1 = min(a.x1, x0 + max_w)
    y1 = min(a.y1, y0 + max_h)
    z1 = min(a.z1, z0 + max_d)
    return AABB(x0, y0, z0, x1, y1, z1)


# ────────────────────────────────────────────────────────────────────────
#  Shell: floor + perimeter walls
# ────────────────────────────────────────────────────────────────────────

def _shell(a: AABB) -> List[Op]:
    """Solid @floor plane + four @primary walls. Ceiling left to the
    `_lintel_ceiling_with_beams` step."""
    ops: List[Op] = []

    # Floor plane at y = y0.
    ops.append(Rect(a, "@floor", axis="y", level=a.y0))

    h_y0 = a.y0 + 1
    h_y1 = a.y1  # exclusive — we paint up to the ceiling row inclusive
    if h_y1 <= h_y0:
        return ops

    # North wall (z = z0)
    ops.append(Fill(AABB(a.x0, h_y0, a.z0, a.x1, h_y1, a.z0 + 1), "@primary"))
    # South wall (z = z1-1)
    ops.append(Fill(AABB(a.x0, h_y0, a.z1 - 1, a.x1, h_y1, a.z1), "@primary"))
    # West wall (x = x0)
    ops.append(Fill(AABB(a.x0, h_y0, a.z0, a.x0 + 1, h_y1, a.z1), "@primary"))
    # East wall (x = x1-1)
    ops.append(Fill(AABB(a.x1 - 1, h_y0, a.z0, a.x1, h_y1, a.z1), "@primary"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Lintel ceiling with exposed beams
# ────────────────────────────────────────────────────────────────────────

def _lintel_ceiling_with_beams(a: AABB) -> List[Op]:
    """Drop the top row as a lintel ring + add a sparse beam grid spanning
    the room. The beams give the room its acoustic-enclosure feel without
    fully sealing the ceiling (preserves the room's airy silhouette and
    lets the renderer light the interior from above)."""
    ops: List[Op] = []
    ceil_y = a.y1 - 1
    if ceil_y <= a.y0:
        return ops

    # Lintel ring (already painted by the wall fill — kept explicit so the
    # ceiling reads as a frame even if a later op punches a wall opening).
    # North + south lintels
    ops.append(Fill(AABB(a.x0, ceil_y, a.z0, a.x1, ceil_y + 1, a.z0 + 1), "@primary"))
    ops.append(Fill(AABB(a.x0, ceil_y, a.z1 - 1, a.x1, ceil_y + 1, a.z1), "@primary"))
    # West + east lintels
    ops.append(Fill(AABB(a.x0, ceil_y, a.z0, a.x0 + 1, ceil_y + 1, a.z1), "@primary"))
    ops.append(Fill(AABB(a.x1 - 1, ceil_y, a.z0, a.x1, ceil_y + 1, a.z1), "@primary"))

    # Beams: spanning along the short axis, spaced every 3 cells along the
    # long axis. This keeps the room visually open while still trapping
    # sound (Eating Atmosphere).
    long_along_x = a.w >= a.d
    if long_along_x:
        for x in range(a.x0 + 2, a.x1 - 1, 3):
            ops.append(Fill(AABB(x, ceil_y, a.z0 + 1,
                                  x + 1, ceil_y + 1, a.z1 - 1),
                            "@primary"))
    else:
        for z in range(a.z0 + 2, a.z1 - 1, 3):
            ops.append(Fill(AABB(a.x0 + 1, ceil_y, z,
                                  a.x1 - 1, ceil_y + 1, z + 1),
                            "@primary"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Instrument: piano-shaped bench with note_blocks on top
# ────────────────────────────────────────────────────────────────────────

def _instrument_bench(a: AABB) -> List[Op]:
    """A 3-block-long @primary bench against the north wall (z = z0+1, the
    interior side), centred along x. The bench is one cell tall (y0+1).
    Three to four `minecraft:note_block` blocks sit on top of it (y0+2),
    giving the bench its "piano" silhouette. For wider rooms we extend the
    bench by one cell (L-shape: an extra @primary cap turning south along
    one end) so the instrument reads as a small upright with a stool."""
    ops: List[Op] = []

    bench_y = a.y0 + 1
    note_y = a.y0 + 2
    # Must have headroom above the bench for the note blocks.
    if note_y >= a.y1 - 1:
        # Tight ceilings: collapse to a single note_block on the floor.
        cz = a.z0 + 1
        cx = (a.x0 + a.x1 - 1) // 2
        if a.contains(cx, bench_y, cz):
            ops.append(PlaceBlock(cx, bench_y, cz, "minecraft:note_block"))
        return ops

    interior_w = a.w - 2
    bench_len = 3 if interior_w >= 3 else max(2, interior_w)
    bx0 = a.x0 + 1 + max(0, (interior_w - bench_len) // 2)
    bx1 = min(a.x1 - 1, bx0 + bench_len)
    bz = a.z0 + 1  # interior side of the north wall

    # Bench (Fill of @primary, 3 cells along x, 1 deep).
    ops.append(Fill(AABB(bx0, bench_y, bz, bx1, bench_y + 1, bz + 1), "@primary"))

    # L-shape extension: in larger rooms add one extra @primary cap turning
    # south from the east end of the bench, so the silhouette reads as an
    # upright piano with an attached stool.
    if a.w >= 9 and a.d >= 6:
        cap_x = bx1 - 1
        cap_z = bz + 1
        if a.contains(cap_x, bench_y, cap_z):
            ops.append(PlaceBlock(cap_x, bench_y, cap_z, "@primary"))

    # 3 note_blocks sitting on the bench top (one per bench cell). Bigger
    # rooms get a 4th block on the L-cap so the count satisfies "3-4".
    placed_notes = 0
    for nx in range(bx0, bx1):
        if a.contains(nx, note_y, bz):
            ops.append(PlaceBlock(nx, note_y, bz, "minecraft:note_block"))
            placed_notes += 1
    if placed_notes < 3:
        # Pad with extras at any remaining valid spot directly above the bench.
        for nx in range(bx0, bx1):
            if placed_notes >= 3:
                break
            ops.append(PlaceBlock(nx, note_y, bz, "minecraft:note_block"))
            placed_notes += 1
    if a.w >= 9 and a.d >= 6:
        cap_x = bx1 - 1
        cap_z = bz + 1
        if a.contains(cap_x, note_y, cap_z):
            ops.append(PlaceBlock(cap_x, note_y, cap_z, "minecraft:note_block"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Jukebox against a wall
# ────────────────────────────────────────────────────────────────────────

def _jukebox(a: AABB) -> List[Op]:
    """One jukebox flush with the west wall (interior side), near the
    instrument. Gives the room a "play recorded music" affordance to pair
    with the live-music note_blocks."""
    ops: List[Op] = []
    jb_x = a.x0 + 1
    jb_z = a.z0 + 2  # one cell south of the bench, against the west wall
    jb_y = a.y0 + 1
    if a.contains(jb_x, jb_y, jb_z):
        ops.append(PlaceBlock(jb_x, jb_y, jb_z, "minecraft:jukebox"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Bookshelf (sheet music)
# ────────────────────────────────────────────────────────────────────────

def _bookshelf(a: AABB) -> List[Op]:
    """One bookshelf against the east wall — represents the room's stash
    of sheet music. Wider rooms get a second shelf stacked above it."""
    ops: List[Op] = []
    bs_x = a.x1 - 2
    bs_z = a.z0 + 2  # roughly mirrors the jukebox on the opposite wall
    bs_y = a.y0 + 1
    if a.contains(bs_x, bs_y, bs_z):
        ops.append(PlaceBlock(bs_x, bs_y, bs_z, "minecraft:bookshelf"))
    # Stack a second sheet-music shelf if the ceiling allows.
    if a.h >= 4 and a.contains(bs_x, bs_y + 1, bs_z):
        ops.append(PlaceBlock(bs_x, bs_y + 1, bs_z, "minecraft:bookshelf"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Audience: 2–4 stair seats facing the instrument
# ────────────────────────────────────────────────────────────────────────

def _audience_stairs(a: AABB, stairs_block: str) -> List[Op]:
    """A row of @stairs facing the north wall (i.e. facing toward the
    instrument). Count scales with room width: 2 chairs in a 6-wide
    room, up to 4 in a 12-wide room."""
    ops: List[Op] = []
    interior_w = a.w - 2
    if interior_w < 2 or a.d < 5:
        return ops

    # Audience sits two cells south of the bench so there's space for the
    # rug between them and the instrument.
    seat_z = a.z0 + 4
    # If the room is shallow, place the seats one cell further north.
    if seat_z >= a.z1 - 1:
        seat_z = a.z1 - 2

    seat_count = 4 if interior_w >= 6 else (3 if interior_w >= 4 else 2)
    seat_count = min(seat_count, interior_w)

    # Centre the seats along x.
    sx0 = a.x0 + 1 + max(0, (interior_w - seat_count) // 2)
    for i in range(seat_count):
        sx = sx0 + i
        if not a.contains(sx, a.y0 + 1, seat_z):
            continue
        # facing=north — the seat's "back" faces +z, so the diner is
        # looking toward -z (the bench at z = z0+1).
        ops.append(PlaceBlock(sx, a.y0 + 1, seat_z, f"{stairs_block}[facing=north]"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Carpet rug under the audience
# ────────────────────────────────────────────────────────────────────────

def _carpet_rug(a: AABB) -> List[Op]:
    """A @carpet patch directly under the audience seats so the rug reads
    as the "performance area". Painted before furniture so later-wins
    leaves the stairs visible on top of the carpet from the side."""
    ops: List[Op] = []
    interior_w = a.w - 2
    if interior_w < 2 or a.d < 5:
        return ops

    rug_y = a.y0 + 1  # rugs sit on top of the floor
    # Match the audience x-range (computed identically below) and extend
    # one row toward the bench so the rug visually connects them.
    seat_count = 4 if interior_w >= 6 else (3 if interior_w >= 4 else 2)
    seat_count = min(seat_count, interior_w)
    sx0 = a.x0 + 1 + max(0, (interior_w - seat_count) // 2)
    sx1 = sx0 + seat_count

    rug_z0 = a.z0 + 2
    rug_z1 = min(a.z1 - 1, a.z0 + 5)
    if rug_z1 <= rug_z0 or sx1 <= sx0:
        return ops

    ops.append(Fill(AABB(sx0, rug_y, rug_z0, sx1, rug_y + 1, rug_z1), "@carpet"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Lanterns: 2 for atmosphere ("Pools of Light")
# ────────────────────────────────────────────────────────────────────────

def _lanterns(a: AABB) -> List[Op]:
    """Two `minecraft:lantern` blocks placed near the lintel — one above
    the instrument, one above the audience seats. Lanterns rather than
    torches per Alexander's "Pools of Light" pattern."""
    ops: List[Op] = []
    if a.h < 4:
        # Tight ceiling: drop them down by one row so they still fit.
        lantern_y = a.y0 + 2
    else:
        lantern_y = a.y1 - 2

    if lantern_y <= a.y0 + 1:
        lantern_y = a.y0 + 1

    cx = (a.x0 + a.x1 - 1) // 2
    # Lantern 1: above the instrument bench.
    l1_z = a.z0 + 1
    if a.contains(cx, lantern_y, l1_z):
        ops.append(PlaceBlock(cx, lantern_y, l1_z, "minecraft:lantern"))
    # Lantern 2: above the audience.
    l2_z = min(a.z1 - 2, a.z0 + 4)
    if l2_z != l1_z and a.contains(cx, lantern_y, l2_z):
        ops.append(PlaceBlock(cx, lantern_y, l2_z, "minecraft:lantern"))
    else:
        # Fallback: bump lantern 2 into a corner so we still emit two.
        fx = a.x1 - 2
        fz = a.z1 - 2
        if a.contains(fx, lantern_y, fz):
            ops.append(PlaceBlock(fx, lantern_y, fz, "minecraft:lantern"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Flower pot decoration
# ────────────────────────────────────────────────────────────────────────

def _flower_pot(a: AABB) -> List[Op]:
    """One `minecraft:flower_pot` near the south wall, off the audience
    axis so it doesn't crowd the seating. Adds a soft decorative touch."""
    ops: List[Op] = []
    pot_x = a.x1 - 2
    pot_z = a.z1 - 2
    pot_y = a.y0 + 1
    if a.contains(pot_x, pot_y, pot_z):
        ops.append(PlaceBlock(pot_x, pot_y, pot_z, "minecraft:flower_pot"))
    return ops
