"""Study skill — a small office/despacho.

Composes a compact workspace: a hollow shell, a desk pushed against the
back wall, a chair facing the desk (so the seated writer looks toward the
desk and the window above it), a short run of bookshelves flanking the
window on the same wall, a lectern (or lantern as fallback) on top of the
desk, a chest for papers, a carpet underfoot, and a generous @glass window
on the desk wall for natural light.

The skill is defensive on AABBs from 4×3×4 up to 8×5×8. Anything below
4×3×4 just emits the shell; anything above 8×5×8 still works but the
furniture stays in the same low-density layout — a study is meant to be
intimate.

Layout (x to the right, z forward, "back" wall = z = z1 - 1):

    z1-1   B W W B            ← bookshelves flanking a central glass window
              D D              ← desk (2 long along x), with lectern on top
              C                ← @stairs chair, facing the desk (north / +z)
              ░                ← carpet under chair
    z0       . . .

When h >= 4 the window also extends up another row on the back wall.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, Fill, FillHollow, PlaceBlock, Rect


# Furniture choice tables. We prefer a lectern (looks like a real desk
# accessory) but fall back to a lantern when room is too cramped.
_DESK_BLOCK = "@primary"          # 2-block long counter @primary
_CHAIR_BLOCK = "@stairs"          # facing the desk
_BOOKSHELF = "minecraft:bookshelf"
_LECTERN = "minecraft:lectern"
_LANTERN = "minecraft:lantern"
_CHEST = "minecraft:chest"


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    ops: List[Op] = []

    # Reject absurdly small boxes — guard against degenerate ops below.
    if aabb.w < 3 or aabb.d < 3 or aabb.h < 2:
        return ops

    # ── Shell ──────────────────────────────────────────────────────────
    # Floor + walls + ceiling. Interior left as air.
    ops.append(
        FillHollow(
            aabb=aabb,
            wall="@primary",
            floor="@floor",
            ceiling="@roof",
            fill=None,
        )
    )

    # ── Carpet under desk + chair (a single strip) ─────────────────────
    # We anchor the desk against the BACK wall (z = z1 - 1, interior side)
    # so the writer faces a window in the FRONT wall (z = z0). The carpet
    # forms a 2×2 island in front of the desk.
    interior_y = aabb.y0 + 1
    # Desk row (interior side of back wall):
    desk_z = aabb.z1 - 2
    # Center the desk along x but clamp inside the interior strip.
    x_left_max = aabb.x1 - 2 - 1   # last x where a 2-long desk fits inside walls
    desk_x0 = max(aabb.x0 + 1, min(x_left_max, aabb.x0 + (aabb.w // 2) - 1))
    desk_x1 = desk_x0 + 2  # half-open

    # Carpet strip directly in front of the desk (one row toward z0).
    carpet_z = desk_z - 1
    if aabb.z0 + 1 <= carpet_z <= aabb.z1 - 2:
        cx0 = max(aabb.x0 + 1, desk_x0)
        cx1 = min(aabb.x1 - 1, desk_x1)
        if cx1 > cx0:
            ops.append(
                Rect(
                    aabb=AABB(cx0, interior_y, carpet_z, cx1, interior_y + 1, carpet_z + 1),
                    block="@carpet",
                    axis="y",
                    level=interior_y,
                )
            )

    # ── Desk (2 blocks of @primary in a row along x) ────────────────────
    desk_y = interior_y
    ops.append(
        Fill(
            AABB(desk_x0, desk_y, desk_z, desk_x1, desk_y + 1, desk_z + 1),
            _DESK_BLOCK,
        )
    )

    # ── Lectern (or lantern) on top of the desk ─────────────────────────
    # Sits at the LEFT desk cell so the chest can sit at the right.
    # If ceiling clearance is tight (h == 3) we still place the lantern
    # at the ceiling level — it reads as a hanging lamp over the desk.
    top_y = desk_y + 1
    desk_top_block = _LECTERN if aabb.h >= 4 else _LANTERN
    if top_y < aabb.y1:  # any cell still inside the AABB is fine
        ops.append(PlaceBlock(desk_x0, top_y, desk_z, desk_top_block))

    # ── Chair: @stairs facing the desk (i.e. facing +z toward back wall) ─
    chair_z = desk_z - 1
    chair_x = desk_x0  # aligned with the lectern half of the desk
    if (
        aabb.x0 + 1 <= chair_x <= aabb.x1 - 2
        and aabb.z0 + 1 <= chair_z <= aabb.z1 - 2
    ):
        # facing=south means the stair's seat side faces the desk (which is at z+1).
        ops.append(PlaceBlock(chair_x, interior_y, chair_z, f"{_CHAIR_BLOCK}[facing=south]"))

    # ── Window on the back wall, centred behind the desk ────────────────
    # We pierce the back wall (z = z1 - 1) with @glass directly above /
    # behind the desk so the seated writer looks at it through the desk.
    # At h >= 4 the window is a 2-row tall slit; at h == 3 it's a single
    # row at interior_y (eye level). Width is min(2, desk width).
    wall_z = aabb.z1 - 1
    win_w = 2 if aabb.w >= 4 else 1
    win_x0 = aabb.x0 + (aabb.w - win_w) // 2
    win_x1 = win_x0 + win_w
    win_y0 = interior_y
    win_y1 = min(aabb.y1 - 1, interior_y + (2 if aabb.h >= 4 else 1))
    if win_y1 > win_y0 and win_x1 > win_x0:
        ops.append(
            Fill(
                AABB(win_x0, win_y0, wall_z, win_x1, win_y1, wall_z + 1),
                "@glass",
            )
        )
    window_cells = {(x, y) for x in range(win_x0, win_x1) for y in range(win_y0, win_y1)}

    # ── Bookshelves: 2-3 on the back wall, FLANKING the window ──────────
    # Total shelves: 3 if room is wide enough, else 2. We place them at
    # interior_y on z = wall_z, skipping any (x, y) inside the window cells.
    n_shelves = 3 if aabb.w >= 6 else 2
    shelf_y = interior_y
    placed = 0
    # build candidate xs: start with cells immediately left/right of the
    # window and expand outward symmetrically.
    candidates: list[int] = []
    left = win_x0 - 1
    right = win_x1
    while (left >= aabb.x0 or right < aabb.x1) and len(candidates) < n_shelves:
        if right < aabb.x1:
            candidates.append(right)
            right += 1
        if len(candidates) < n_shelves and left >= aabb.x0:
            candidates.append(left)
            left -= 1
    for sx in candidates[:n_shelves]:
        if (sx, shelf_y) in window_cells:
            continue
        ops.append(PlaceBlock(sx, shelf_y, wall_z, _BOOKSHELF))
        placed += 1
    # If we still owe shelves, walk again wider on either side.
    if placed < n_shelves:
        extra_candidates = list(range(aabb.x0, aabb.x1))
        for sx in extra_candidates:
            if placed >= n_shelves:
                break
            if (sx, shelf_y) in window_cells:
                continue
            if sx in candidates:
                continue
            ops.append(PlaceBlock(sx, shelf_y, wall_z, _BOOKSHELF))
            placed += 1

    # ── Chest (papers): on the desk row next to the desk, if room; else
    # on the chair row to one side of the chair. We search candidate cells
    # in priority order and pick the first that's inside the interior and
    # not already taken by the chair or desk.
    chest_candidates = [
        (desk_x1, desk_z),          # right of desk, desk row
        (desk_x0 - 1, desk_z),      # left of desk, desk row
        (desk_x1, carpet_z),        # right of chair, chair row
        (desk_x0 - 1, carpet_z),    # left of chair, chair row
    ]
    chair_xz = (desk_x0, carpet_z)
    desk_cells = {(x, desk_z) for x in range(desk_x0, desk_x1)}
    placed_chest = False
    for (cx, cz) in chest_candidates:
        if not (aabb.x0 + 1 <= cx <= aabb.x1 - 2):
            continue
        if not (aabb.z0 + 1 <= cz <= aabb.z1 - 2):
            continue
        if (cx, cz) == chair_xz:
            continue
        if (cx, cz) in desk_cells:
            continue
        ops.append(PlaceBlock(cx, interior_y, cz, _CHEST))
        placed_chest = True
        break
    if not placed_chest:
        # Last-resort: replace the rightmost bookshelf cell with the chest.
        # The shelf op list is still in `ops`; we just emit the chest
        # after all shelves so later-wins gives us the chest.
        bx = max(aabb.x0, min(aabb.x1 - 1, desk_x1 - 1))
        ops.append(PlaceBlock(bx, interior_y, aabb.z1 - 1, _CHEST))

    # ── Window(s): pierce the FRONT wall (z = z0) with @glass ───────────
    # We want at least one BIG window — punch a 2-wide × (h-2)-tall slit
    # centered along the front wall. For wider rooms we add a second slit.
    win_z = aabb.z0
    win_y0 = aabb.y0 + 1
    win_y1 = aabb.y1 - 1  # leave the top course as @primary lintel
    if win_y1 > win_y0:
        # Centered big window
        win_w = 2 if aabb.w >= 4 else 1
        win_x0 = aabb.x0 + (aabb.w - win_w) // 2
        win_x1 = win_x0 + win_w
        ops.append(
            Fill(
                AABB(win_x0, win_y0, win_z, win_x1, win_y1, win_z + 1),
                "@glass",
            )
        )
        # Second smaller slit for wide rooms, offset to one side.
        if aabb.w >= 7:
            extra_x = aabb.x0 + 1
            if extra_x + 1 <= win_x0:  # don't overlap centered window
                ops.append(
                    Fill(
                        AABB(extra_x, win_y0, win_z, extra_x + 1, win_y1, win_z + 1),
                        "@glass",
                    )
                )

    return ops
