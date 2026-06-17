"""Unit tests for the typology geometry helpers in
`pipeline/skills/typologies/_geom.py`.

The helpers are pure-Python and small; the tests focus on invariants
(volume, perimeter count, monotonicity) rather than golden voxel lists,
so refactoring the helpers doesn't break the tests as long as the
geometry stays correct.
"""
from __future__ import annotations

import math

import pytest

from pipeline.skills.base import AABB, Materials, PlaceBlock, Rect
from pipeline.skills.composer import compose
from pipeline.skills.typologies._geom import (
    carve_slit,
    circle_xz,
    conical_spire,
    crenellated_circle,
    crenellated_ring,
    hollow_wall_ring,
    onion_dome,
    pyramid_square,
    vertical_strip,
)


MATERIALS = Materials.for_style("medieval")


def _cells_from_ops(ops) -> set[tuple[int, int, int]]:
    """Run ops through compose() and return the set of occupied cells.

    Coordinates are local to the composer's bounding box, so we translate
    back to absolute by tracking min coords ourselves.
    """
    cells = set()
    for op in ops:
        for (x, y, z, _block) in op.compile(MATERIALS):
            cells.add((x, y, z))
    return cells


# ────────────────────────────────────────────────────────────────────────
#  crenellated_ring
# ────────────────────────────────────────────────────────────────────────

def test_crenellated_ring_emits_roughly_half_perimeter():
    """A 10x10 ring has 4*9 = 36 perimeter cells. Alternating placement
    should yield ~half (18) merlons."""
    ops = crenellated_ring(AABB(0, 5, 0, 10, 6, 10), "@primary")
    # Each PlaceBlock = 1 cell.
    assert all(isinstance(o, PlaceBlock) for o in ops)
    assert 16 <= len(ops) <= 20  # alternation may include both endpoints

def test_crenellated_ring_y_constant():
    """All merlons sit at a single y plane."""
    ops = crenellated_ring(AABB(0, 7, 0, 8, 8, 8), "@primary")
    ys = {o.y for o in ops}
    assert ys == {7}


# ────────────────────────────────────────────────────────────────────────
#  hollow_wall_ring
# ────────────────────────────────────────────────────────────────────────

def test_hollow_wall_ring_emits_four_rects():
    """Exactly 4 Rect ops, one per cardinal wall, no Fill / PlaceBlock."""
    ops = hollow_wall_ring(AABB(0, 0, 0, 8, 5, 8), "@primary")
    assert len(ops) == 4
    assert all(isinstance(o, Rect) for o in ops)
    # Two south/north (axis=z), two west/east (axis=x).
    axis_count = {"x": 0, "z": 0}
    for o in ops:
        axis_count[o.axis] += 1
    assert axis_count == {"x": 2, "z": 2}

def test_hollow_wall_ring_voxel_count_matches_perimeter():
    """For an 8 x 5 x 8 hollow wall ring, voxel count = perimeter * height.

    Perimeter of a 8x8 face = 2*(8 + 8) - 4 = 28 cells per y-layer.
    Times 5 layers = 140 voxels.
    """
    ops = hollow_wall_ring(AABB(0, 0, 0, 8, 5, 8), "minecraft:stone")
    cells = _cells_from_ops(ops)
    assert len(cells) == 28 * 5


# ────────────────────────────────────────────────────────────────────────
#  circle_xz
# ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("r", [1, 3, 5, 7, 10])
def test_circle_xz_no_duplicates(r):
    cells = circle_xz(0, 0, r)
    assert len(cells) == len(set(cells))

@pytest.mark.parametrize("r", [3, 5, 8, 12])
def test_circle_xz_radius_bounds(r):
    """Every emitted cell sits within +/- 1 of the requested radius
    (Bresenham midpoint is not pixel-perfect but stays close)."""
    cells = circle_xz(0, 0, r)
    for x, z in cells:
        d = math.sqrt(x * x + z * z)
        assert r - 1.5 <= d <= r + 0.5, f"cell ({x},{z}) at distance {d:.2f} from radius {r}"


# ────────────────────────────────────────────────────────────────────────
#  crenellated_circle
# ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("r", [3, 5, 7])
def test_crenellated_circle_half_of_perimeter(r):
    """Should emit roughly half the circle's perimeter cells."""
    full = circle_xz(0, 0, r)
    ops = crenellated_circle(0, 0, 10, r, "@primary")
    assert len(ops) == math.ceil(len(full) / 2)


# ────────────────────────────────────────────────────────────────────────
#  conical_spire
# ────────────────────────────────────────────────────────────────────────

def test_conical_spire_tip_is_single_cap():
    """The top y layer must be a single block at (cx, cz)."""
    ops = conical_spire(5, 5, 0, 5, 8, "@primary", cap_block="@accent")
    # Group by y.
    layers: dict[int, list] = {}
    for o in ops:
        layers.setdefault(o.y, []).append(o)
    top_y = max(layers)
    assert len(layers[top_y]) == 1
    tip = layers[top_y][0]
    assert (tip.x, tip.z) == (5, 5)
    assert tip.block == "@accent"

def test_conical_spire_layers_monotone_decreasing():
    """Layer width should not grow as y increases."""
    ops = conical_spire(0, 0, 0, 6, 10, "@primary")
    layers: dict[int, set] = {}
    for o in ops:
        layers.setdefault(o.y, set()).add((o.x, o.z))
    sizes = [len(layers[y]) for y in sorted(layers)]
    for a, b in zip(sizes, sizes[1:]):
        assert b <= a, f"conical spire grew from {a} to {b}"


# ────────────────────────────────────────────────────────────────────────
#  pyramid_square
# ────────────────────────────────────────────────────────────────────────

def test_pyramid_square_base_is_widest():
    ops = pyramid_square(0, 0, 0, 5, 6, "@primary")
    layers: dict[int, set] = {}
    for o in ops:
        layers.setdefault(o.y, set()).add((o.x, o.z))
    base_y = min(layers)
    sizes = {y: len(cells) for y, cells in layers.items()}
    assert all(sizes[y] <= sizes[base_y] for y in sizes)

def test_pyramid_square_only_perimeter_per_layer():
    """At each layer the emitted cells form a ring (perimeter only),
    so for `half=H` we expect at most 8*H cells (for the bottom layer)."""
    half = 5
    ops = pyramid_square(0, 0, 0, half, 6, "@primary")
    layers: dict[int, set] = {}
    for o in ops:
        layers.setdefault(o.y, set()).add((o.x, o.z))
    base_y = min(layers)
    # Bottom layer: perimeter of (2*5+1)^2 = 11x11 square = 4*11 - 4 = 40.
    assert len(layers[base_y]) == 4 * (2 * half + 1) - 4


# ────────────────────────────────────────────────────────────────────────
#  onion_dome
# ────────────────────────────────────────────────────────────────────────

def test_onion_dome_spire_at_top():
    """Top 3 cells must be the centered spire."""
    ops = onion_dome(0, 0, 0, 4, 10, "@primary", finial_block="@accent")
    layers: dict[int, list] = {}
    for o in ops:
        layers.setdefault(o.y, []).append(o)
    top3 = sorted(layers)[-3:]
    for y in top3:
        assert len(layers[y]) == 1
        op = layers[y][0]
        assert (op.x, op.z) == (0, 0)
        assert op.block == "@accent"


# ────────────────────────────────────────────────────────────────────────
#  vertical_strip / carve_slit (Fase-0 helpers, smoke regression)
# ────────────────────────────────────────────────────────────────────────

def test_vertical_strip_length():
    ops = vertical_strip(3, 4, 0, 7, "@primary")
    assert len(ops) == 7
    assert {o.y for o in ops} == set(range(7))

def test_carve_slit_emits_air():
    ops = carve_slit(0, 0, 10, 3, axis="y")
    assert all(o.block == "minecraft:air" for o in ops)
    assert {o.y for o in ops} == {10, 11, 12}
