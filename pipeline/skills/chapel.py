"""Chapel skill — small religious room with altar.

Builds a furnished chapel inside the given AABB:

    * @floor plane on y0.
    * @primary perimeter walls rising up to the ceiling (tall room,
      ≥ 5 high when the AABB allows).
    * Ceiling: a small @slab flat lid in tight AABBs, or a stepped dome
      of @slab + @accent over the centre when there is enough headroom.
    * Altar at the far end (small-z): a Fill of @accent 2 wide × 1 tall
      × 1 deep, topped with a centred `minecraft:enchanting_table`.
    * 2-3 pew rows of @stairs facing the altar, evenly spaced along z.
    * Tall stained-glass windows: 2-3 cell vertical columns of @glass on
      both long (east + west) side walls.
    * Big chandelier — a cluster of 3-4 `minecraft:lantern[hanging=true]`
      below the ceiling centre, marking the conceptual nave.
    * 4-6 `minecraft:wall_torch` or `minecraft:torch` on the interior
      faces of the walls, between the windows.
    * 1 long @carpet aisle running entrance → altar foot, 1 cell wide.

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth. AABB is half-open.

The chapel is "long" along z (depth dominates by default). The altar
sits flush against the small-z (far) short wall; the entrance is the
opposite (+z) short wall. When the AABB happens to be wider than deep
we still treat -z as the altar side — the rule is consistent for the
chandelier, pews, aisle and windows.

Defensive on AABBs from 5×5×8 up to 10×7×16. Smaller inputs are
clamped up to the minimum, larger inputs clamped down to the maximum
so the chapel always reads as intimate.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Fill, Materials, Op, PlaceBlock, Rect


# Defensive envelope for the chapel.
_MIN_W, _MIN_H, _MIN_D = 5, 5, 8
_MAX_W, _MAX_H, _MAX_D = 10, 7, 16


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the AABB extent into the [5×5×8 .. 10×7×16] envelope.

    Origin is preserved; only the upper corner moves.
    """
    w = max(_MIN_W, min(_MAX_W, aabb.w))
    h = max(_MIN_H, min(_MAX_H, aabb.h))
    d = max(_MIN_D, min(_MAX_D, aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Return AST ops that materialize a furnished chapel inside `aabb`."""
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    ops.extend(_floor(a))
    ops.extend(_walls(a))
    ops.extend(_ceiling(a))
    ops.extend(_altar(a))
    ops.extend(_pews(a))
    ops.extend(_aisle(a))
    ops.extend(_windows(a))
    ops.extend(_chandelier(a))
    ops.extend(_wall_torches(a))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Layout helpers
# ────────────────────────────────────────────────────────────────────────

def _floor(a: AABB) -> List[Op]:
    """Solid @floor plane on y == y0."""
    return [Rect(a, "@floor", axis="y", level=a.y0)]


def _walls(a: AABB) -> List[Op]:
    """Perimeter walls of @primary rising from y0+1 to the top row.

    Walls span the full interior height; the ceiling is added separately
    so it can be either flat or a small dome.
    """
    ops: List[Op] = []
    y0w = a.y0 + 1
    y1w = a.y1 - 1   # leave the top row for the ceiling/dome
    if y1w <= y0w:
        return ops
    # North (z = z0): the altar (far) wall
    ops.append(Fill(AABB(a.x0, y0w, a.z0, a.x1, y1w, a.z0 + 1), "@primary"))
    # South (z = z1-1): the entrance wall
    ops.append(Fill(AABB(a.x0, y0w, a.z1 - 1, a.x1, y1w, a.z1), "@primary"))
    # West (x = x0)
    ops.append(Fill(AABB(a.x0, y0w, a.z0, a.x0 + 1, y1w, a.z1), "@primary"))
    # East (x = x1-1)
    ops.append(Fill(AABB(a.x1 - 1, y0w, a.z0, a.x1, y1w, a.z1), "@primary"))
    return ops


def _ceiling(a: AABB) -> List[Op]:
    """Vaulted ceiling: either a small stepped dome or a flat @slab lid.

    A dome is attempted when the room is wide and tall enough (w ≥ 7 and
    h ≥ 6). It is implemented as a stepped 2-ring shape: a flat @slab
    plane at y1-1, with a smaller @accent square stepped up to y1 over
    the centre to suggest a vault. Otherwise a flat @slab lid covers the
    whole footprint at y1-1.
    """
    ops: List[Op] = []
    y_lid = a.y1 - 1
    # Flat slab ceiling across the full footprint.
    ops.append(Rect(a, "@slab", axis="y", level=y_lid))

    # Optional stepped vault over the centre when there is room.
    if a.w >= 7 and a.h >= 6:
        cx = a.cx
        cz = a.cz
        # Inner ring of @accent — a 3x3 square one cell above the lid.
        x0i = max(a.x0 + 1, cx - 1)
        x1i = min(a.x1 - 1, cx + 2)
        z0i = max(a.z0 + 1, cz - 1)
        z1i = min(a.z1 - 1, cz + 2)
        if x1i > x0i and z1i > z0i:
            ops.append(Fill(
                AABB(x0i, y_lid + 0, z0i, x1i, y_lid + 1, z1i),
                "@accent",
            ))
    return ops


def _altar(a: AABB) -> List[Op]:
    """Altar at the far (z = z0) end.

    A 2-wide × 1-tall × 1-deep Fill of @accent sits at z = z0+1, centred
    on x. An `minecraft:enchanting_table` is placed on top, centred over
    the 2-block dais.
    """
    ops: List[Op] = []
    altar_y = a.y0 + 1
    z_altar = a.z0 + 1
    if z_altar >= a.z1 - 1:
        z_altar = a.z0 + 1

    # 2-wide dais centred on cx (round so it stays inside the wall).
    cx = a.cx
    x0_d = max(a.x0 + 1, cx - 1)
    x1_d = min(a.x1 - 1, x0_d + 2)
    if x1_d - x0_d < 1:
        return ops

    ops.append(Fill(
        AABB(x0_d, altar_y, z_altar, x1_d, altar_y + 1, z_altar + 1),
        "@accent",
    ))
    # Enchanting table centred on the dais.
    table_x = x0_d + (x1_d - x0_d) // 2
    table_x = max(x0_d, min(x1_d - 1, table_x))
    ops.append(PlaceBlock(table_x, altar_y + 1, z_altar,
                          "minecraft:enchanting_table"))
    return ops


def _pews(a: AABB) -> List[Op]:
    """2-3 rows of @stairs facing the altar (north, -z).

    Each row spans the interior width minus the aisle (the centre cell).
    Rows sit on the floor at y = y0+1, evenly spaced along z between the
    altar and the entrance.
    """
    ops: List[Op] = []
    pew_y = a.y0 + 1
    # Span z between just past the altar and just before the entrance.
    z_lo = a.z0 + 3                     # altar takes z0+1; leave a gap
    z_hi = a.z1 - 2                     # leave one cell at the entrance
    if z_hi <= z_lo:
        return ops

    # Choose 2-3 evenly-spaced rows.
    n_rows = 3 if (z_hi - z_lo) >= 4 else 2
    positions = _evenly_spaced(z_lo, z_hi, n_rows)

    cx = a.cx                           # aisle column (kept clear)
    x_lo = a.x0 + 1
    x_hi = a.x1 - 1                     # exclusive
    for pz in positions:
        for px in range(x_lo, x_hi):
            if px == cx:                # skip aisle cell
                continue
            # Stairs face the altar (north = -z), facing=north.
            ops.append(PlaceBlock(px, pew_y, pz,
                                  "@stairs[facing=north]"))
    return ops


def _aisle(a: AABB) -> List[Op]:
    """1-wide @carpet runner from the entrance to the altar foot.

    Sits one block above the floor (carpet plane), 1 cell wide centred on
    cx, running from z = z0+2 (just in front of the altar dais) to
    z = z1-2 (just inside the entrance wall).
    """
    ops: List[Op] = []
    cx = a.cx
    y_carpet = a.y0 + 1
    c_z0 = a.z0 + 2
    c_z1 = a.z1 - 1   # exclusive upper bound
    if c_z1 <= c_z0:
        return ops
    ops.append(Fill(
        AABB(cx, y_carpet, c_z0, cx + 1, y_carpet + 1, c_z1),
        "@carpet",
    ))
    return ops


def _windows(a: AABB) -> List[Op]:
    """Tall narrow @glass windows on the east + west (long) walls.

    Each window is a 2-3 block tall vertical column. We place 2-3 windows
    per wall, evenly spaced along z, skipping corners and the altar row.
    Window height = 2 when h == 5, 3 when h ≥ 6.
    """
    ops: List[Op] = []
    win_h = 3 if a.h >= 6 else 2
    win_y0 = a.y0 + 2                   # one row above the floor band
    win_y1 = min(a.y1 - 2, win_y0 + win_h)
    if win_y1 <= win_y0:
        return ops

    # Interior z span (skip altar wall and entrance wall).
    z_lo = a.z0 + 2
    z_hi = a.z1 - 2
    if z_hi <= z_lo:
        return ops

    n_windows = 3 if (z_hi - z_lo) >= 5 else 2
    positions = _evenly_spaced(z_lo, z_hi, n_windows)

    for pz in positions:
        # West wall (x = x0)
        ops.append(Fill(
            AABB(a.x0, win_y0, pz, a.x0 + 1, win_y1, pz + 1),
            "@glass",
        ))
        # East wall (x = x1-1)
        ops.append(Fill(
            AABB(a.x1 - 1, win_y0, pz, a.x1, win_y1, pz + 1),
            "@glass",
        ))
    return ops


def _chandelier(a: AABB) -> List[Op]:
    """Hanging cluster of 3-4 lanterns under the ceiling centre.

    Sits at y = y1-2 (one block below the slab ceiling). We use 4 lanterns
    in a small + pattern around the centre when there is room, else 3 in
    a row along the long axis.
    """
    ops: List[Op] = []
    y = a.y1 - 2
    if y <= a.y0 + 1:
        return ops
    cx = a.cx
    cz = a.cz

    # Prefer a 4-lantern + pattern: centre + 3 cardinal arms.
    # Always include the centre lantern.
    candidates = [
        (cx, cz),
        (cx, cz - 1),
        (cx, cz + 1),
        (cx - 1, cz) if a.w >= 6 else None,
    ]
    placed = 0
    for c in candidates:
        if c is None:
            continue
        x, z = c
        if not (a.x0 + 1 <= x <= a.x1 - 2):
            continue
        if not (a.z0 + 1 <= z <= a.z1 - 2):
            continue
        ops.append(PlaceBlock(x, y, z, "minecraft:lantern[hanging=true]"))
        placed += 1
        if placed >= 4:
            break

    # Fallback: ensure at least 3 lanterns by stretching along z.
    if placed < 3:
        for dz in (-2, 2):
            z = cz + dz
            if a.z0 + 1 <= z <= a.z1 - 2:
                ops.append(PlaceBlock(cx, y, z,
                                      "minecraft:lantern[hanging=true]"))
                placed += 1
            if placed >= 3:
                break
    return ops


def _wall_torches(a: AABB) -> List[Op]:
    """4-6 torches on the long (east + west) interior walls.

    Placed on the interior face (one cell in from each long wall) at a
    height between the window columns and the ceiling lid. We use
    `minecraft:wall_torch` with the appropriate facing so the renderer
    snaps them to the wall.
    """
    ops: List[Op] = []
    y_torch = min(a.y1 - 2, a.y0 + 3)
    if y_torch <= a.y0 + 1:
        return ops

    # Interior z range, offset from windows by half a step where possible.
    z_lo = a.z0 + 2
    z_hi = a.z1 - 2
    if z_hi <= z_lo:
        return ops

    n_per_side = 3 if (z_hi - z_lo) >= 5 else 2
    positions = _evenly_spaced(z_lo, z_hi, n_per_side, offset=True)

    for pz in positions:
        # Torch on west wall faces east (away from x0 wall).
        ops.append(PlaceBlock(a.x0 + 1, y_torch, pz,
                              "minecraft:wall_torch[facing=east]"))
        # Torch on east wall faces west.
        ops.append(PlaceBlock(a.x1 - 2, y_torch, pz,
                              "minecraft:wall_torch[facing=west]"))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Spacing helper
# ────────────────────────────────────────────────────────────────────────

def _evenly_spaced(lo: int, hi: int, n: int, *, offset: bool = False) -> list[int]:
    """Return `n` evenly-spaced integer positions inside [lo, hi).

    When `offset=True`, the positions are shifted by half a step so they
    interleave with a non-offset placement on the same range — useful for
    placing torches *between* windows.
    """
    span = hi - lo
    if span <= 0 or n <= 0:
        return []
    if n == 1:
        return [lo + span // 2]
    step = span / n
    shift = 0.5 if not offset else 1.0
    out = []
    for i in range(n):
        p = int(lo + step * (i + (0.5 if not offset else 0.0)))
        if shift == 1.0:
            # interleave: nudge each by half a step toward hi
            p = int(lo + step * i + step * 0.25)
        p = max(lo, min(hi - 1, p))
        out.append(p)
    # Deduplicate while preserving order.
    seen = set()
    uniq = []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq
