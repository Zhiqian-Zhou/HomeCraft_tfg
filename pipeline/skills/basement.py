"""Basement skill — underground storage / cellar.

Builds an enclosed stone cellar inside the given AABB:
    - Floor of @secondary (cobblestone-y feel).
    - Walls of @secondary (stone-y — NOT @primary, because @primary is
      wood and basements are cold, structural stone).
    - Ceiling: a solid plane of @primary at the top of the AABB. The
      basement is enclosed, and the floor above it is its ceiling — so
      we use @primary (the wooden floorboards of the house above).
    - LOW CEILING: the build is clamped to height 3 regardless of the
      AABB.y (unless the caller passes an even shorter AABB.y < 3, in
      which case we honour their shrinkage).
    - 3-6 minecraft:barrel along the walls (main storage).
    - 2-3 minecraft:chest (additional storage).
    - 1-2 minecraft:smoker / minecraft:furnace (cellar workshop).
    - 1+ minecraft:cobweb in a corner (basement vibe).
    - 1+ minecraft:torch on the wall (dim lighting).
    - 1 staircase up using a Line of @stairs (so the player can exit
      back to the ground floor).

Defensive on 4×3×4 to 10×3×10. Furniture counts scale with footprint
area; the tiny end of the range still gets the must-have blocks.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock, Rect, Fill, Line


# ────────────────────────────────────────────────────────────────────────
#  Public API
# ────────────────────────────────────────────────────────────────────────


def build(aabb: AABB, materials: Materials, style: str = "medieval",
          **kwargs) -> List[Op]:
    """Return AST ops that materialize a stone basement inside `aabb`."""
    s = (style or "medieval").lower()

    # Low-ceiling clamp: the basement is fixed at height 3 (1 floor row +
    # 1 interior row + 1 ceiling row). If the caller asked for less, we
    # respect that (still defensive); if they asked for more, we ignore
    # the upper rows of the AABB.
    h_target = min(3, aabb.h) if aabb.h >= 1 else 1
    if aabb.h < 3:
        h_target = aabb.h
    box = AABB(aabb.x0, aabb.y0, aabb.z0,
               aabb.x1, aabb.y0 + h_target, aabb.z1)

    ops: List[Op] = []
    ops.extend(_floor(box))
    ops.extend(_walls(box))
    ops.extend(_ceiling(box))
    ops.extend(_barrels(box))
    ops.extend(_chests(box))
    ops.extend(_workshop(box, s))
    ops.extend(_cobwebs(box))
    ops.extend(_torches(box))
    ops.extend(_staircase_up(box))
    return ops


# ────────────────────────────────────────────────────────────────────────
#  Layout helpers
# ────────────────────────────────────────────────────────────────────────


def _floor(box: AABB) -> List[Op]:
    """Solid stone floor plane at y == box.y0 using @secondary."""
    floor_plane = AABB(box.x0, box.y0, box.z0, box.x1, box.y0 + 1, box.z1)
    return [Rect(floor_plane, "@secondary", axis="y", level=box.y0)]


def _walls(box: AABB) -> List[Op]:
    """Stone perimeter walls (4 vertical faces) of @secondary.

    Walls span y from box.y0+1 (above the floor) up to box.y1-1
    (leaving the top row for the ceiling). For h=3 that's exactly 1
    interior row of walls.
    """
    y0w = box.y0 + 1
    y1w = max(box.y1 - 1, y0w + 1)
    ops: List[Op] = []
    # North (z = z0) + South (z = z1-1)
    ops.append(Fill(AABB(box.x0, y0w, box.z0,
                         box.x1, y1w, box.z0 + 1), "@secondary"))
    ops.append(Fill(AABB(box.x0, y0w, box.z1 - 1,
                         box.x1, y1w, box.z1), "@secondary"))
    # West (x = x0) + East (x = x1-1)
    ops.append(Fill(AABB(box.x0, y0w, box.z0,
                         box.x0 + 1, y1w, box.z1), "@secondary"))
    ops.append(Fill(AABB(box.x1 - 1, y0w, box.z0,
                         box.x1, y1w, box.z1), "@secondary"))
    return ops


def _ceiling(box: AABB) -> List[Op]:
    """Solid ceiling plane (the floor of the room above) using @primary."""
    if box.h < 2:
        return []
    y = box.y1 - 1
    ceiling_plane = AABB(box.x0, y, box.z0, box.x1, y + 1, box.z1)
    return [Rect(ceiling_plane, "@primary", axis="y", level=y)]


def _barrels(box: AABB) -> List[Op]:
    """3-6 barrels along the interior of the walls.

    We march along the north (z = z0+1) and south (z = z1-2) interior
    rows, placing barrels at every other x, spread evenly. Count
    scales with footprint area — at most 6 to leave room for chests
    and the workshop.
    """
    ops: List[Op] = []
    y = box.y0 + 1

    # Interior coordinate ranges.
    in_x0, in_x1 = box.x0 + 1, box.x1 - 1
    in_z0, in_z1 = box.z0 + 1, box.z1 - 1
    if in_x1 <= in_x0 or in_z1 <= in_z0:
        return ops

    # Target count: scale with area, clamp to [3, 6].
    area = max(1, (box.w - 2)) * max(1, (box.d - 2))
    target = min(6, max(3, area // 6))

    # North/south-wall x positions — we skip the corner cells so cobwebs
    # can claim them. For tiny rooms keep every cell; for bigger rooms
    # use stride 2 to leave gaps for the torch / staircase.
    inner_xs = list(range(in_x0 + 1, in_x1 - 1))
    if not inner_xs:
        inner_xs = list(range(in_x0, in_x1))
    stride = 2 if len(inner_xs) >= 4 else 1
    barrel_xs = inner_xs[::stride]

    candidates: list[tuple[int, int, int, str]] = []
    # Place along north wall — barrels face south (into the room).
    for x in barrel_xs:
        candidates.append((x, y, in_z0, "minecraft:barrel[facing=south]"))
    # Place along south wall — barrels face north.
    for x in barrel_xs:
        candidates.append((x, y, in_z1 - 1, "minecraft:barrel[facing=north]"))

    # Trim to target count.
    for (x, by, z, block) in candidates[:target]:
        ops.append(PlaceBlock(x, by, z, block))

    # If we somehow didn't hit 3 (very narrow room), pad along east wall.
    placed = min(len(candidates), target)
    if placed < 3:
        for z in range(in_z0, in_z1):
            if placed >= 3:
                break
            ops.append(PlaceBlock(box.x1 - 2, y, z,
                                  "minecraft:barrel[facing=west]"))
            placed += 1

    return ops


def _chests(box: AABB) -> List[Op]:
    """2-3 chests along the east interior wall, facing west.

    Avoid the corners (which usually host cobwebs / the staircase).
    """
    ops: List[Op] = []
    y = box.y0 + 1
    x_e = box.x1 - 2
    if x_e <= box.x0:
        x_e = box.x0 + 1

    in_z0, in_z1 = box.z0 + 1, box.z1 - 1
    if in_z1 <= in_z0:
        return ops

    # Target 2 or 3 chests depending on depth.
    target = 3 if box.d >= 7 else 2
    # Walk along east wall, skipping the corners.
    candidates = list(range(in_z0 + 1, in_z1 - 1))
    if not candidates:
        candidates = list(range(in_z0, in_z1))
    placed = 0
    for z in candidates:
        if placed >= target:
            break
        ops.append(PlaceBlock(x_e, y, z, "minecraft:chest[facing=west]"))
        placed += 1
    # Tiny-room fallback: ensure ≥ 2 chests.
    if placed < 2:
        # Drop a chest on the west wall too.
        x_w = box.x0 + 1
        for z in candidates:
            if placed >= 2:
                break
            ops.append(PlaceBlock(x_w, y, z, "minecraft:chest[facing=east]"))
            placed += 1
    return ops


def _workshop(box: AABB, style: str) -> List[Op]:
    """1-2 smoker / furnace blocks — the cellar workshop.

    Sits against the west wall, facing east into the room. Style nudges
    the smoker / furnace ratio (modern → 2x smoker; medieval → furnace +
    smoker; fantasy → smoker + furnace).
    """
    ops: List[Op] = []
    y = box.y0 + 1
    x_w = box.x0 + 1
    in_z0, in_z1 = box.z0 + 1, box.z1 - 1
    if in_z1 <= in_z0 or x_w >= box.x1 - 1:
        return ops

    if style == "modern":
        line = ["minecraft:smoker[facing=east]",
                "minecraft:smoker[facing=east]"]
    elif style == "fantasy":
        line = ["minecraft:smoker[facing=east]",
                "minecraft:furnace[facing=east]"]
    else:  # medieval default
        line = ["minecraft:furnace[facing=east]",
                "minecraft:smoker[facing=east]"]

    # How many fit? At least 1, at most 2.
    z_start = in_z0 + 1
    max_n = min(2, in_z1 - 1 - z_start)
    if max_n < 1:
        # Tight room — drop one against the wall regardless.
        ops.append(PlaceBlock(x_w, y, in_z0, line[0]))
        return ops
    for i in range(max_n):
        ops.append(PlaceBlock(x_w, y, z_start + i, line[i]))
    return ops


def _cobwebs(box: AABB) -> List[Op]:
    """At least one cobweb in a corner — basement atmosphere.

    Placed in the top-interior corners (just under the ceiling) so they
    visibly hang in the room. Bigger basements get two cobwebs. We pick
    corners that don't coincide with the barrel rows (every other x on
    the N/S walls), so cobwebs land at odd-x corners.
    """
    ops: List[Op] = []
    # Cobwebs sit hanging from the ceiling row (y = y1 - 1), overriding
    # the @primary ceiling block at that single corner voxel (later-wins
    # in the composer). This frees y0 + 1 at the same column for torches.
    y = box.y1 - 1
    if y <= box.y0:
        y = box.y0
    # Inner corners.
    in_x0, in_x1 = box.x0 + 1, box.x1 - 1
    in_z0, in_z1 = box.z0 + 1, box.z1 - 1
    if in_x1 <= in_x0 or in_z1 <= in_z0:
        return ops
    # Barrels skip the corner cells, so the four interior corners are
    # free for cobwebs. Use NE first; SW second on larger basements.
    ops.append(PlaceBlock(in_x1 - 1, y, in_z0, "minecraft:cobweb"))
    if box.w >= 6 and box.d >= 6:
        ops.append(PlaceBlock(in_x0, y, in_z1 - 1, "minecraft:cobweb"))
    return ops


def _torches(box: AABB) -> List[Op]:
    """1+ torches on the walls — dim lighting.

    Placed at interior cells at y = y0 + 1 (low) since the ceiling is so
    low. We sit them on the floor in front of the N/S walls (z = in_z0
    and z = in_z1-1) one cell INWARD so they don't collide with the
    perimeter wall blocks. Tiny rooms only get one torch.
    """
    ops: List[Op] = []
    y = box.y0 + 1
    in_x0, in_x1 = box.x0 + 1, box.x1 - 1
    in_z0, in_z1 = box.z0 + 1, box.z1 - 1
    if in_x1 <= in_x0 or in_z1 <= in_z0:
        return ops

    # Sit torches on the floor just in front of the N and S walls, at the
    # interior corners we know are free (the cobweb corners' opposite z).
    # NE corner row has the cobweb at (in_x1-1, y_high, in_z0); we use
    # (in_x1-1, y, in_z0) below it on the floor — but that's where the
    # wall itself sits when in_z0 == box.z0 + 1. Instead, anchor torches
    # one cell INWARD (toward room centre).
    # Free spots: (in_x1 - 1, y, in_z0) and (in_x0, y, in_z1 - 1)
    # — the same corner pillars the cobwebs hang at, but on the floor.
    # However barrels skip those corners (we coded inner_xs to start at
    # in_x0+1), so the corner cells are free for the torches as well.
    ops.append(PlaceBlock(in_x1 - 1, y, in_z0, "minecraft:torch"))
    # Larger rooms: a second torch on the SW corner.
    if box.w >= 5 and box.d >= 5:
        ops.append(PlaceBlock(in_x0, y, in_z1 - 1, "minecraft:torch"))
    return ops


def _staircase_up(box: AABB) -> List[Op]:
    """A staircase up to the floor above.

    Cuts a single-block hole through the ceiling at the SE interior corner
    (so the player can climb out) and places a Line of @stairs leading up
    through it. The basement ceiling itself is later-wins overridden by
    the stairs at that single voxel.
    """
    ops: List[Op] = []
    # SE-ish staircase column at (x1-2, ?, z1-2): one block in from each wall.
    sx = box.x1 - 2
    sz = box.z1 - 2
    if sx <= box.x0:
        sx = box.x0 + 1
    if sz <= box.z0:
        sz = box.z0 + 1

    # The interior floor is at y0; the player walks at y0+1; the ceiling
    # is at y1-1. Place a single @stairs facing west at (sx, y0+1, sz)
    # — that's the visible step heading up to the trapdoor hole.
    if box.h >= 2:
        ops.append(PlaceBlock(sx, box.y0 + 1, sz, "@stairs[facing=west]"))
    # Carve a hole through the ceiling above the stair so there's an
    # opening upward — replace the ceiling cell with air at the column.
    if box.h >= 3:
        ops.append(PlaceBlock(sx, box.y1 - 1, sz, "minecraft:air"))
    # Add a Line of @stairs continuing through the hole (just one block
    # past the ceiling) so the staircase visibly leads up. We only emit
    # this if the line lies inside the AABB; outside the box, the line
    # would still compose fine, but we keep it bounded for cleanliness.
    if box.h >= 3:
        ops.append(Line(sx, box.y0 + 1, sz,
                        sx - 1, box.y0 + 2, sz,
                        "@stairs"))
    return ops
