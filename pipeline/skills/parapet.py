"""Skill: parapet.

A low decorative wall running around the TOP edge of a building — the
classic battlement / roof-edge crown. Unlike `perimeter_wall_fortified`
(which is a full curtain wall around a courtyard), `parapet` is a thin
rim that sits 1-2 blocks ABOVE the building's footprint and dresses the
edge between the roof and the sky.

The input AABB describes the FOOTPRINT of the building underneath; the
parapet itself rises one course above ``y1`` (the top of the building).
Nothing is emitted inside the footprint — only along the perimeter ring.

Composition, from bottom to top of the parapet rim:

  * **Cornice** (optional, default on): a 1-block-tall ring of ``@slab``
    or ``@accent`` placed at ``y_top - 1`` — one course BELOW the parapet
    ring. This reads as the moulding / cornice that the parapet sits on.

  * **Parapet ring**: a 1-block-tall ring of ``@primary`` along the
    perimeter at ``y_top``. This is the actual low wall.

  * **Crenellations** (optional, on by default for medieval): the parapet
    ring is patterned every 2 blocks — odd-indexed positions are cleared
    to air, leaving alternating merlons (block) + crenels (gap) battlements.

  * **Corner posts** (optional, default on): a single block of ``@accent``
    at each of the four corners, sticking 1 block ABOVE the parapet ring
    (i.e. at ``y_top + 1``). They emphasise the building corners.

Material conventions (resolved via `Materials._resolve`):

  * ``@primary`` for the parapet ring
  * ``@accent``  for the corner posts
  * ``@slab``    for the cornice course (medieval / fantasy)
  * ``@accent``  for the cornice course on modern (a flat moulding band)

Coordinate convention (matches `base.py`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc.

Defensive sizing: clamped to 3×1×3 .. 30×3×30. The AABB ``h`` is the
building's height — the parapet is emitted at ``y1`` regardless of ``h``,
but ``h`` is still clamped so callers can't push the parapet absurdly far
up off-screen.
"""
from __future__ import annotations

from typing import List

from .base import AABB, Materials, Op, PlaceBlock


# Defensive bounds, per spec.
_MIN = (3, 1, 3)
_MAX = (30, 3, 30)


def _clamp_aabb(aabb: AABB) -> AABB:
    """Clamp the footprint AABB into the [3..30, 1..3, 3..30] envelope.

    The lower corner is preserved; the upper corner shifts to satisfy the
    size constraints. Mirrors the clamp pattern used by the sibling
    ``perimeter_wall_fortified`` skill.
    """
    w = max(_MIN[0], min(_MAX[0], aabb.w))
    h = max(_MIN[1], min(_MAX[1], aabb.h))
    d = max(_MIN[2], min(_MAX[2], aabb.d))
    return AABB(aabb.x0, aabb.y0, aabb.z0,
                aabb.x0 + w, aabb.y0 + h, aabb.z0 + d)


def _perimeter_cells(a: AABB, y: int) -> list[tuple[int, int, int]]:
    """Return every (x, y, z) cell on the perimeter ring of `a` at level `y`.

    Walks the 4 edges in a fixed order (front, back, left, right) so the
    index of each cell along the ring is deterministic — which lets the
    crenellation pattern start at the first corner and remain stable
    across calls.
    """
    cells: list[tuple[int, int, int]] = []
    # Front edge (z = z0): full x range.
    for x in range(a.x0, a.x1):
        cells.append((x, y, a.z0))
    # Right edge (x = x1-1): z from z0+1 to z1-1 (exclude top-right corner — already added).
    for z in range(a.z0 + 1, a.z1):
        cells.append((a.x1 - 1, y, z))
    # Back edge (z = z1-1): x from x1-2 down to x0 (exclude bottom-right corner — already added).
    for x in range(a.x1 - 2, a.x0 - 1, -1):
        cells.append((x, y, a.z1 - 1))
    # Left edge (x = x0): z from z1-2 down to z0+1 (exclude both corners).
    for z in range(a.z1 - 2, a.z0, -1):
        cells.append((a.x0, y, z))
    return cells


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    """Build a decorative parapet rim above the AABB footprint.

    Kwargs:
        crenellated (bool | None): force the crenel/merlon pattern on or
            off. Default ``None`` = auto: on for medieval / fantasy,
            off for modern.
        cornice (bool): emit a 1-block-tall ring of @slab / @accent one
            course below the parapet ring. Default ``True``.
        corner_posts (bool): emit four single @accent blocks sticking 1
            block above the parapet ring at each corner. Default ``True``.
    """
    a = _clamp_aabb(aabb)
    ops: List[Op] = []

    style_l = style.lower()
    crenellated_kw = kwargs.get("crenellated")
    if crenellated_kw is None:
        # Medieval/fantasy default to crenellated battlements; modern is
        # a smooth continuous parapet.
        crenellated = style_l in ("medieval", "fantasy", "gothic", "viking")
    else:
        crenellated = bool(crenellated_kw)

    cornice = bool(kwargs.get("cornice", True))
    corner_posts = bool(kwargs.get("corner_posts", True))

    # The parapet ring sits one course ABOVE the building's footprint
    # (AABB is half-open, so y1 is the first cell above the building).
    y_top = a.y1
    y_cornice = y_top - 1
    y_post = y_top + 1

    # ── 1) Cornice (optional, one course below the parapet ring) ─────
    # The cornice block depends on style: medieval/fantasy take @slab
    # (decorative moulding feel); modern takes @accent (a flat band).
    if cornice:
        cornice_block = "@accent" if style_l == "modern" else "@slab"
        for (x, y, z) in _perimeter_cells(a, y_cornice):
            ops.append(PlaceBlock(x, y, z, cornice_block))

    # ── 2) Parapet ring at y_top ──────────────────────────────────────
    ring = _perimeter_cells(a, y_top)
    for (x, y, z) in ring:
        ops.append(PlaceBlock(x, y, z, "@primary"))

    # ── 3) Crenellations: pattern every 2 blocks around the ring ─────
    # We walk the ring in the deterministic order from _perimeter_cells
    # and clear odd-indexed positions to air (so the merlon/crenel
    # pattern is `M . M . M . …` around the perimeter). Composer drops
    # air after later-wins, so the gap appears in the parapet ring.
    if crenellated:
        for i, (x, y, z) in enumerate(ring):
            if i % 2 == 1:
                ops.append(PlaceBlock(x, y, z, "minecraft:cave_air"))

    # ── 4) Corner posts (single @accent block at each corner, +1 above
    #       the parapet ring so they "stick up" past the merlons). ────
    if corner_posts:
        corners = [
            (a.x0,     y_post, a.z0),
            (a.x1 - 1, y_post, a.z0),
            (a.x0,     y_post, a.z1 - 1),
            (a.x1 - 1, y_post, a.z1 - 1),
        ]
        for (x, y, z) in corners:
            # Make sure the parapet cell directly below the post still
            # exists (a crenellation may have cleared the corner). We
            # re-stamp the corner of the parapet ring as @primary so the
            # post sits on a solid base — later-wins overrides any prior
            # air emit at that cell.
            ops.append(PlaceBlock(x, y_top, z, "@primary"))
            ops.append(PlaceBlock(x, y,     z, "@accent"))

    return ops
