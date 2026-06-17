"""Entry hall skill — formal entrance / foyer.

Builds a compact, defensive entry hall inside `aabb`. The room reads as the
transition zone between outside and inside: a welcome mat at the threshold,
a coat rack to hang things on arrival, and a sitting bench facing the door
so visitors can wait, take off boots, or be greeted.

Composition (later-wins paint order, like the other room skills):

    1. Floor plane at y = y0 using ``@floor``.
    2. Perimeter walls in ``@primary``, rising from y0+1 to y1-1.
    3. Lintel ring of ``@accent`` at the top row (no full ceiling — keeps
       this skill stackable under a roof skill, matching kitchen.py).
    4. A 1×2 door OPENING punched into the south wall (z = z1-1). The
       opening is *air* — the actual door blocks are placed by the
       door_with_frame skill elsewhere, never here.
    5. Welcome carpet at the door: a single @carpet block on the floor
       surface (y0+1) just inside the threshold.
    6. Coat rack against the west interior wall: a 3-tall column of
       ``@fence`` with a ``minecraft:wall_torch`` perched on top as a
       proxy for hanging hooks.
    7. Sitting bench: a 3-block row of ``@stairs`` against the north
       interior wall, facing south (into the room, toward the door).
    8. A ``minecraft:flower_pot`` on a 1-block ``@primary`` pedestal
       in the interior corner opposite the coat rack.
    9. ≥ 1 ``minecraft:lantern`` mounted near the lintel on the east wall.

Defensive envelope: clamps the input AABB into [4×3×4 .. 8×5×8]. The
preview test harness sends small (6×4×6) and medium (12×6×12) AABBs;
the 12×6×12 case is clamped down to 8×5×8 so the entry hall stays
intimate rather than cavernous.

Coordinate convention (matches `base.py`):
    x = width, y = height (up), z = depth. AABB is half-open.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect, Line


# Defensive envelope.
_MIN_W, _MIN_H, _MIN_D = 4, 3, 4
_MAX_W, _MAX_H, _MAX_D = 8, 5, 8


# ────────────────────────────────────────────────────────────────────────
#  Public entry point
# ────────────────────────────────────────────────────────────────────────

def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Return AST ops that materialize a formal entry hall inside `aabb`."""
    a = _clamp(aabb)
    s = (style or "medieval").lower()

    ops: List[Op] = []

    # Order matters: shell first, then later-wins details. The door
    # opening MUST come after the walls because it carves them; the
    # welcome carpet must come after the floor so it sits on top.
    ops.extend(_shell(a))
    ops.extend(_lintel(a))
    ops.extend(_door_opening(a))
    ops.extend(_welcome_carpet(a))
    ops.extend(_coat_rack(a))
    ops.extend(_bench(a, stairs_block=materials.stairs))
    ops.extend(_flower_pedestal(a))
    ops.extend(_lighting(a))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Defensive clamp
# ────────────────────────────────────────────────────────────────────────

def _clamp(aabb: AABB) -> AABB:
    """Clamp `aabb` into the [4×3×4 .. 8×5×8] envelope.

    Origin is preserved; only the upper corner moves. Inputs smaller than
    the minimum still build (guards below handle tiny cases) and larger
    inputs are truncated from +x/+y/+z.
    """
    w = max(_MIN_W, min(_MAX_W, aabb.w))
    h = max(_MIN_H, min(_MAX_H, aabb.h))
    d = max(_MIN_D, min(_MAX_D, aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


# ────────────────────────────────────────────────────────────────────────
#  Shell: floor + 4 wall slabs (no ceiling)
# ────────────────────────────────────────────────────────────────────────

def _shell(a: AABB) -> List[Op]:
    ops: List[Op] = []

    # Floor plane at y = y0 using @floor.
    ops.append(Rect(a, "@floor", axis="y", level=a.y0))

    # Walls rise from y0+1 up to y1-1; the y1-1 row hosts the lintel.
    y0w = a.y0 + 1
    y1w = max(a.y1 - 1, y0w + 1)

    # North wall (z = z0)
    ops.append(Fill(AABB(a.x0, y0w, a.z0,
                         a.x1, y1w, a.z0 + 1), "@primary"))
    # South wall (z = z1-1) — the door wall.
    ops.append(Fill(AABB(a.x0, y0w, a.z1 - 1,
                         a.x1, y1w, a.z1), "@primary"))
    # West wall (x = x0)
    ops.append(Fill(AABB(a.x0, y0w, a.z0,
                         a.x0 + 1, y1w, a.z1), "@primary"))
    # East wall (x = x1-1)
    ops.append(Fill(AABB(a.x1 - 1, y0w, a.z0,
                         a.x1, y1w, a.z1), "@primary"))
    return ops


def _lintel(a: AABB) -> List[Op]:
    """Top-of-wall accent ring (no full ceiling)."""
    if a.h < 3:
        return []
    y = a.y1 - 1
    return [
        Line(a.x0, y, a.z0,     a.x1 - 1, y, a.z0,     "@accent"),
        Line(a.x0, y, a.z1 - 1, a.x1 - 1, y, a.z1 - 1, "@accent"),
        Line(a.x0, y, a.z0,     a.x0,     y, a.z1 - 1, "@accent"),
        Line(a.x1 - 1, y, a.z0, a.x1 - 1, y, a.z1 - 1, "@accent"),
    ]


# ────────────────────────────────────────────────────────────────────────
#  Door opening (NO door block — just a 1×2 hole in the wall)
# ────────────────────────────────────────────────────────────────────────

def _door_opening(a: AABB) -> List[Op]:
    """Punch a 1-wide × 2-tall opening in the south wall (z = z1-1).

    Composer is later-wins, so writing `minecraft:air` over the wall
    here erases the two wall blocks, leaving a clean door-shaped gap.
    The door_with_frame skill is responsible for placing the actual door.
    """
    if a.w < 3 or a.h < 3:
        return []
    cx = (a.x0 + a.x1 - 1) // 2
    z = a.z1 - 1
    # Two-block tall opening on the bottom of the wall (y0+1 and y0+2).
    y_bot = a.y0 + 1
    y_top = min(a.y1 - 2, y_bot + 1)
    ops: List[Op] = [PlaceBlock(cx, y_bot, z, "minecraft:air")]
    if y_top > y_bot:
        ops.append(PlaceBlock(cx, y_top, z, "minecraft:air"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Welcome carpet (rug at the threshold)
# ────────────────────────────────────────────────────────────────────────

def _welcome_carpet(a: AABB) -> List[Op]:
    """Single @carpet block on the floor surface, just inside the door."""
    if a.w < 3 or a.d < 3:
        return []
    cx = (a.x0 + a.x1 - 1) // 2
    # One cell inside the south wall (where the door opening sits).
    z = a.z1 - 2
    y = a.y0 + 1
    return [PlaceBlock(cx, y, z, "@carpet")]


# ────────────────────────────────────────────────────────────────────────
#  Coat rack — 3-tall fence column + wall_torch crown
# ────────────────────────────────────────────────────────────────────────

def _coat_rack(a: AABB) -> List[Op]:
    """Stack of 3 @fence blocks against the west interior wall with a
    wall_torch on top as the 'hook' proxy.

    Placed near the door end of the west wall so visitors meet it on
    arrival.
    """
    if a.w < 3 or a.d < 3 or a.h < 3:
        return []
    ops: List[Op] = []
    x = a.x0 + 1                          # interior, against west wall
    z = a.z1 - 2                          # near the door end
    y_base = a.y0 + 1
    # Reserve the top row for the lintel: rack top must sit strictly
    # below y1-1 so the wall_torch crown has a wall block to mount on.
    #
    # Ideal rack height is 3, but we shrink it if the hall is short so
    # the crown torch never collides with the lintel ring.
    max_rack_h = max(1, (a.y1 - 1) - y_base - 1)  # leave a slot for the torch
    rack_h = min(3, max_rack_h)
    if rack_h < 1:
        rack_h = 1
    for i in range(rack_h):
        ops.append(PlaceBlock(x, y_base + i, z, "@fence"))
    crown_y = y_base + rack_h
    if crown_y < a.y1 - 1:
        # Standard case: wall_torch hooks on the west wall (so facing=east).
        ops.append(PlaceBlock(x, crown_y, z, "minecraft:wall_torch[facing=east]"))
    else:
        # Degenerate (very flat) hall — drop a torch on the topmost
        # fence so the "rack with hooks" image still reads.
        ops.append(PlaceBlock(x, y_base + rack_h - 1, z, "minecraft:torch"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Sitting bench — 3 stairs facing into the room
# ────────────────────────────────────────────────────────────────────────

def _bench(a: AABB, stairs_block: str) -> List[Op]:
    """A 3-block row of @stairs against the north wall, facing south
    (into the room, toward the door).

    Stairs need an explicit `[facing=…]` blockstate so we use the
    materials.stairs concrete id (the `@stairs` placeholder cannot
    carry a blockstate through `_resolve`).
    """
    if a.w < 3 or a.d < 3:
        return []
    ops: List[Op] = []
    y = a.y0 + 1
    z = a.z0 + 1                          # interior, against north wall
    interior_w = a.w - 2
    bench_len = min(3, max(1, interior_w))
    cx = (a.x0 + a.x1 - 1) // 2
    x0 = max(a.x0 + 1, cx - bench_len // 2)
    x1 = min(a.x1 - 1, x0 + bench_len)
    if x1 - x0 < bench_len:
        x0 = max(a.x0 + 1, x1 - bench_len)
    for x in range(x0, x1):
        ops.append(PlaceBlock(x, y, z, f"{stairs_block}[facing=south]"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Flower pot on a small @primary pedestal
# ────────────────────────────────────────────────────────────────────────

def _flower_pedestal(a: AABB) -> List[Op]:
    """1-block @primary pedestal in the east-near-door interior corner
    with a `minecraft:flower_pot` on top.

    Sits opposite the coat rack (which is on the west) so the room
    reads as symmetric on arrival.
    """
    if a.w < 4 or a.d < 4:
        return []
    ops: List[Op] = []
    x = a.x1 - 2                          # interior, against east wall
    z = a.z1 - 2                          # near the door
    y_base = a.y0 + 1                     # pedestal sits on the floor
    ops.append(PlaceBlock(x, y_base, z, "@primary"))
    # Flower pot on top of the pedestal.
    if y_base + 1 < a.y1 - 1:
        ops.append(PlaceBlock(x, y_base + 1, z, "minecraft:flower_pot"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Lighting
# ────────────────────────────────────────────────────────────────────────

def _lighting(a: AABB) -> List[Op]:
    """At least one `minecraft:lantern` mounted near the lintel on the
    east wall, opposite the coat rack's wall_torch. For taller halls we
    add a second lantern on the west wall above the rack for symmetry.
    """
    if a.h < 3 or a.w < 3 or a.d < 3:
        return []
    ops: List[Op] = []
    y_light = max(a.y0 + 2, a.y1 - 2)
    # East-wall lantern (interior, centred along z).
    x_east = a.x1 - 2
    z_c = (a.z0 + a.z1 - 1) // 2
    ops.append(PlaceBlock(x_east, y_light, z_c, "minecraft:lantern"))
    # Bigger hall? Add a second lantern on the west side near the
    # door for balance with the coat rack torch.
    if a.w >= 6 and a.d >= 6:
        ops.append(PlaceBlock(a.x0 + 1, y_light, z_c, "minecraft:lantern"))
    return ops
