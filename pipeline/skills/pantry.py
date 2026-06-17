"""Pantry skill — small storage room adjacent to a kitchen.

Composes a tightly packed despensa: a hollow shell with a @slab ceiling
(unlike the kitchen which leaves the top open for a roof skill — the
pantry sits inside a building so it has its own enclosed lid), a DENSE
wall of barrels stacked 2-3 high along 2-3 of the four interior walls,
bookshelves interleaved between barrel stacks (recipe books / ingredient
labels), one or two ground-level chests, a composter + cauldron pair on
the floor for food prep, a hanging lantern in the centre of the ceiling,
and a flower pot with a plant on top of a barrel for a touch of life.

Layout (looking down, w x d, "rear" wall = z = z1 - 1):

    z1-1   B b B b B b B          ← rear wall: alternating barrels (B) +
                                     bookshelves (b), each B is a stack
    ···                            of 2 (or 3) barrels high
    z2     B                       ← right wall: more barrel stacks
    z1     B                C      ← chest on floor; cauldron / composter
    z0     . . . . . . .             at the front (left wall stays open for
                                     a notional doorway / passage to kitchen)

Defensive on AABBs from 3x3x3 (degenerate-but-built) up to 6x4x6
(canonical pantry size). Bigger AABBs still produce a valid pantry by
extending the same dense storage pattern along the walls.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, Fill, FillHollow, PlaceBlock, Rect


# Furniture blocks we lean on.
_BARREL = "minecraft:barrel"
_BOOKSHELF = "minecraft:bookshelf"
_CHEST = "minecraft:chest"
_COMPOSTER = "minecraft:composter"
_CAULDRON = "minecraft:cauldron[level=3]"
_LANTERN_HANGING = "minecraft:lantern[hanging=true]"
_FLOWER_POT = "minecraft:potted_poppy"  # 1.16.5 pre-filled potted variants


def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Return AST ops that materialize a dense storage pantry inside `aabb`."""
    s = (style or "medieval").lower()

    ops: List[Op] = []

    # Defensive on tiny boxes: anything below 3×3×3 cannot host the
    # shell + a single barrel, so just bail out with nothing.
    if aabb.w < 3 or aabb.d < 3 or aabb.h < 3:
        return ops

    ops.extend(_shell(aabb))
    ops.extend(_barrel_stacks(aabb))
    ops.extend(_bookshelves_between(aabb))
    ops.extend(_floor_items(aabb, s))
    ops.extend(_lantern_ceiling(aabb))
    ops.extend(_flower_pot_on_shelf(aabb))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Shell
# ────────────────────────────────────────────────────────────────────────


def _shell(aabb: AABB) -> List[Op]:
    """Hollow shell: @floor on the floor, @primary on the four walls,
    @slab as the flat ceiling. Interior left as air.

    Unlike `kitchen.py`, we close the top — pantries are enclosed rooms
    sitting inside a larger building, not topped by a roof skill.
    """
    return [
        FillHollow(
            aabb=aabb,
            wall="@primary",
            floor="@floor",
            ceiling="@slab",
            fill=None,
        )
    ]


# ────────────────────────────────────────────────────────────────────────
#  Storage: dense barrel stacks
# ────────────────────────────────────────────────────────────────────────


def _barrel_stacks(aabb: AABB) -> List[Op]:
    """Stack barrels 2-3 high along the rear, right and back-half-of-left walls.

    Front wall (z = z0) is intentionally left bare for the implied doorway
    to the kitchen, so the room reads as accessible storage.

    Stack height is min(3, interior height) — for a 3-tall room (h==3)
    only the interior layer at y0+1 is reachable, so stacks become a
    single barrel; for h>=4 stacks are 2 high; for h>=5 stacks are 3 high.
    """
    ops: List[Op] = []

    # Interior cells available for storage furniture.
    y0 = aabb.y0 + 1
    # Cap the stack at 3 (a real-world pantry shelf is ~2-3 levels) AND
    # at the available interior height (h - 2 = floor and ceiling removed).
    interior_h = max(1, aabb.h - 2)
    stack_h = min(3, interior_h)

    # Rear wall (z = z1 - 2) — runs along x from x0+1 to x1-2.
    z_rear = aabb.z1 - 2
    for x in range(aabb.x0 + 1, aabb.x1 - 1):
        # Alternate barrel and bookshelf cells; barrel stacks on EVEN
        # offsets so bookshelves can slip into the ODD ones (handled in
        # _bookshelves_between).
        if (x - (aabb.x0 + 1)) % 2 != 0:
            continue
        for k in range(stack_h):
            ops.append(PlaceBlock(x, y0 + k, z_rear, f"{_BARREL}[facing=south]"))

    # Right wall (x = x1 - 2) — runs along z from z0+1 to z1-2.
    x_right = aabb.x1 - 2
    for z in range(aabb.z0 + 1, aabb.z1 - 2):  # exclude rear (already covered)
        if (z - (aabb.z0 + 1)) % 2 != 0:
            continue
        for k in range(stack_h):
            ops.append(PlaceBlock(x_right, y0 + k, z, f"{_BARREL}[facing=west]"))

    # Left wall (x = x0 + 1) — only the BACK half (z >= midpoint) so the
    # front half stays clear for the doorway and the floor furniture.
    x_left = aabb.x0 + 1
    z_mid = (aabb.z0 + aabb.z1) // 2
    for z in range(z_mid, aabb.z1 - 2):
        if (z - z_mid) % 2 != 0:
            continue
        for k in range(stack_h):
            ops.append(PlaceBlock(x_left, y0 + k, z, f"{_BARREL}[facing=east]"))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Variety: bookshelves between barrel stacks
# ────────────────────────────────────────────────────────────────────────


def _bookshelves_between(aabb: AABB) -> List[Op]:
    """Slip a bookshelf into ODD-offset cells between barrel stacks.

    Only on the rear wall — for the side walls we keep contiguous barrels
    to maximize storage density. The rear is the "feature" wall the user
    sees when entering, so the alternation reads as recipe-book shelving.

    We place at least 2 bookshelves overall; small rooms (w == 3) get
    only one rear column free for them, so we add a second shelf at the
    right wall in that case to meet the count.
    """
    ops: List[Op] = []
    y0 = aabb.y0 + 1
    z_rear = aabb.z1 - 2
    interior_h = max(1, aabb.h - 2)
    # Bookshelves stand 1-2 tall to read as a shelf with books and a
    # cookbook on top. Always at least the base row; second row only if
    # there's clearance for it (stack_h >= 2).
    shelf_h = 1 if interior_h < 2 else 2

    placed = 0
    for x in range(aabb.x0 + 1, aabb.x1 - 1):
        if (x - (aabb.x0 + 1)) % 2 == 0:
            continue  # skip barrel columns
        for k in range(shelf_h):
            ops.append(PlaceBlock(x, y0 + k, z_rear, _BOOKSHELF))
        placed += 1

    # Guarantee >= 2 bookshelves — if the rear wall only had one ODD cell
    # (rooms with w == 3 or w == 4), add a second shelf at the back-right
    # corner, displacing the corner barrel.
    if placed < 2:
        x_corner = aabb.x1 - 2
        z_corner = aabb.z1 - 3 if aabb.z1 - 3 > aabb.z0 else aabb.z0 + 1
        ops.append(PlaceBlock(x_corner, y0, z_corner, _BOOKSHELF))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Floor furniture: chests, composter, cauldron
# ────────────────────────────────────────────────────────────────────────


def _floor_items(aabb: AABB, style: str) -> List[Op]:
    """One chest (two on larger rooms) on the floor at the front, plus a
    composter and a cauldron near the prep corner.

    All sit at y = y0 + 1. We anchor against the FRONT wall (z = z0 + 1)
    since the back is already lined with barrels. The composter goes in
    the left-front corner (next to the implied kitchen doorway, so food
    scraps go straight there); the cauldron goes next to it.
    """
    ops: List[Op] = []
    y = aabb.y0 + 1
    z_front = aabb.z0 + 1
    # If the room is so shallow that front and rear barrel rows collide,
    # nudge front items one row in.
    if z_front >= aabb.z1 - 2:
        z_front = max(aabb.z0 + 1, aabb.z1 - 3)

    # Chest #1: front-centre.
    x_c = (aabb.x0 + aabb.x1 - 1) // 2
    ops.append(PlaceBlock(x_c, y, z_front, f"{_CHEST}[facing=north]"))

    # Chest #2: larger rooms (w >= 5) get a second chest offset one cell.
    if aabb.w >= 5:
        x_c2 = x_c + 1
        if aabb.x0 + 1 <= x_c2 <= aabb.x1 - 2 and x_c2 != aabb.x1 - 2:
            # Don't collide with the right wall's barrel stack (x1 - 2).
            ops.append(PlaceBlock(x_c2, y, z_front, f"{_CHEST}[facing=north]"))

    # Composter — left-front corner of the interior. Adjacent x to the
    # wall; if that conflicts with a left-wall barrel (the back half),
    # we still place it because the back-half barrels start at z_mid.
    x_l = aabb.x0 + 1
    z_compost = z_front
    # Avoid same cell as the chest.
    if x_l == x_c:
        x_l = aabb.x0 + 2 if aabb.x0 + 2 <= aabb.x1 - 2 else x_l
    ops.append(PlaceBlock(x_l, y, z_compost, _COMPOSTER))

    # Cauldron — next to the composter, one z forward if there's room, or
    # one x to the right otherwise.
    cauldron_x, cauldron_z = x_l, z_compost
    if z_compost + 1 <= aabb.z1 - 2 and (x_l, z_compost + 1) not in {(x_c, z_front)}:
        cauldron_z = z_compost + 1
    else:
        cauldron_x = x_l + 1 if x_l + 1 <= aabb.x1 - 2 else x_l
    # Defensive: don't drop the cauldron on the composter cell.
    if (cauldron_x, cauldron_z) == (x_l, z_compost):
        cauldron_x = x_l + 1 if x_l + 1 <= aabb.x1 - 2 else x_l
    ops.append(PlaceBlock(cauldron_x, y, cauldron_z, _CAULDRON))

    return ops


# ────────────────────────────────────────────────────────────────────────
#  Lighting
# ────────────────────────────────────────────────────────────────────────


def _lantern_ceiling(aabb: AABB) -> List[Op]:
    """A single hanging lantern in the centre of the ceiling.

    Sits one row BELOW the ceiling plane (y = y1 - 2) so the lantern
    hangs in the air without overwriting the @slab ceiling block. We use
    `[hanging=true]` so it dangles instead of standing.
    """
    if aabb.h < 3:
        return []
    y = aabb.y1 - 2
    x_c = (aabb.x0 + aabb.x1 - 1) // 2
    z_c = (aabb.z0 + aabb.z1 - 1) // 2
    return [PlaceBlock(x_c, y, z_c, _LANTERN_HANGING)]


# ────────────────────────────────────────────────────────────────────────
#  Decoration: flower pot with a plant
# ────────────────────────────────────────────────────────────────────────


def _flower_pot_on_shelf(aabb: AABB) -> List[Op]:
    """A potted poppy sitting ON TOP of a rear-wall barrel stack.

    1.16.5 has pre-filled potted_* variants — `potted_poppy` is one. We
    place it one row above the top of the first rear barrel stack so it
    reads as a decorative pot on the shelf.
    """
    # Pick the first rear barrel column (smallest x that is a barrel
    # column). That's (aabb.x0 + 1) — the (x - (x0+1)) % 2 == 0 anchor.
    x_pot = aabb.x0 + 1
    z_pot = aabb.z1 - 2

    # Y: one above the top barrel in the stack. We computed stack_h the
    # same way as _barrel_stacks; redo it here to stay independent.
    interior_h = max(1, aabb.h - 2)
    stack_h = min(3, interior_h)
    y_pot = aabb.y0 + 1 + stack_h

    # If that y collides with the ceiling, drop down one cell so the pot
    # sits between the topmost barrel and the @slab lid (this happens on
    # short rooms where the stack already fills the interior).
    if y_pot >= aabb.y1 - 1:
        y_pot = aabb.y1 - 2

    # If after clamping the pot would land on the topmost barrel, that's
    # fine — later-wins composer dedupe means the pot replaces it.
    return [PlaceBlock(x_pot, y_pot, z_pot, _FLOWER_POT)]
