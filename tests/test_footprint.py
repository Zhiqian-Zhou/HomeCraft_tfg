"""Tests for pipeline.agents.footprint — deterministic footprint masks."""
from __future__ import annotations

from pipeline.agents.footprint import (
    footprint_for, Footprint, _normalize_shape, _largest_component,
    _SHAPE_BUILDERS,
)

BIG = [0, 0, 0, 20, 10, 20]   # 20×20 footprint, plenty of room for any shape


def _fp(shape, aabb=BIG, **kw):
    return footprint_for("x-silhouette", aabb, footprint_shape=shape, **kw)


def _connected(fp: Footprint) -> bool:
    return _largest_component(set(fp.cells)) == set(fp.cells)


def test_unknown_shape_is_full_rectangle():
    fp = _fp("irregular_composition")
    assert fp.shape == "rectangle"
    assert len(fp.cells) == 20 * 20
    assert fp.contains(0, 0) and fp.contains(19, 19)


def test_normalize_aliases():
    assert _normalize_shape("near_square_with_central_void") == "O"
    assert _normalize_shape("square_or_octagon") == "octagon"
    assert _normalize_shape("long_rectangle") == "rectangle"
    assert _normalize_shape("rectangle_with_dome") == "rectangle"
    assert _normalize_shape("circle") == "circle"
    assert _normalize_shape(None) == "rectangle"


def test_circle_drops_corners_keeps_center():
    fp = _fp("circle")
    assert not fp.contains(0, 0)            # corner carved away
    assert not fp.contains(19, 19)
    assert fp.contains(10, 10)              # center present
    assert len(fp.cells) < 20 * 20         # smaller than the full rect
    assert _connected(fp)


def test_u_has_open_courtyard():
    fp = _fp("U", params={"open_side": "south"})
    # the courtyard interior (center, toward the open +z side) must be void
    assert not fp.contains(10, 18)
    # the three wings exist
    assert fp.contains(1, 1) and fp.contains(18, 1) and fp.contains(10, 1)
    assert _connected(fp)


def test_O_ring_has_hollow_center():
    fp = _fp("O")
    assert not fp.contains(10, 10)         # hollow middle
    assert fp.contains(0, 10) and fp.contains(19, 10)   # ring present
    assert _connected(fp)


def test_cross_is_plus_shaped():
    fp = _fp("cross")
    assert fp.contains(10, 10)             # crossing
    assert not fp.contains(0, 0)           # corners empty
    assert fp.contains(10, 0) and fp.contains(0, 10)    # arms reach edges
    assert _connected(fp)


def test_L_has_one_empty_corner():
    fp = _fp("L")
    assert fp.contains(0, 0)               # corner of the L
    assert not fp.contains(19, 19)         # opposite corner carved
    assert _connected(fp)


def test_all_catalog_shapes_nonempty_and_connected():
    for shape in sorted(set(_SHAPE_BUILDERS)):
        fp = _fp(shape)
        assert fp.cells, f"{shape} produced empty footprint"
        assert _connected(fp), f"{shape} is not connected"
        # every cell inside the bbox
        for (x, z) in fp.cells:
            assert 0 <= x < 20 and 0 <= z < 20


def test_rects_roundtrip_to_cells():
    for shape in ("rectangle", "circle", "U", "cross", "L", "O", "T", "H"):
        fp = _fp(shape)
        covered = set()
        for (x0, z0, x1, z1) in fp.rects():
            for x in range(x0, x1):
                for z in range(z0, z1):
                    covered.add((x, z))
        assert covered == set(fp.cells), f"{shape}: rects != cells"


def test_small_footprint_falls_back_to_rectangle():
    fp = _fp("cross", aabb=[0, 0, 0, 5, 6, 5])   # min side 5 < 7
    assert fp.shape == "rectangle"
    assert len(fp.cells) == 5 * 5


def test_clip_aabb():
    fp = _fp("U", params={"open_side": "south"})
    # a room in the left wing is inside; a room in the courtyard is not
    assert fp.clip_aabb([1, 0, 1, 4, 5, 5])
    assert not fp.clip_aabb([8, 0, 14, 13, 5, 19])


def test_setback_progression_is_monotone_subset():
    """Each upper floor must be ⊆ the floor below (no floating walls), and the
    footprint must taper overall. Setback insets one ring every TWO floors so
    towers read as slender shafts, so it is non-increasing per floor (not
    strictly shrinking every floor) but the top is strictly smaller than the
    base."""
    floors = []
    prev = None
    for fi in range(6):
        fp = footprint_for("x", [0, 0, 0, 16, 30, 16], floor_index=fi, n_floors=6,
                           footprint_shape="rectangle",
                           params={"floor_progression": "setback"})
        cells = set(fp.cells)
        assert cells, "progression emptied the footprint"
        if prev is not None:
            assert cells <= prev, f"floor {fi} not a subset of the floor below"
        assert _largest_component(cells) == cells   # still one component
        floors.append(cells)
        prev = cells
    # genuinely tapering: the top floor is strictly smaller than the base
    assert len(floors[-1]) < len(floors[0])


def test_uniform_progression_is_noop():
    a = footprint_for("x", [0, 0, 0, 16, 8, 16], floor_index=0, n_floors=3,
                      footprint_shape="U")
    b = footprint_for("x", [0, 0, 0, 16, 8, 16], floor_index=2, n_floors=3,
                      footprint_shape="U", params={"floor_progression": "uniform"})
    assert set(a.cells) == set(b.cells)


def test_exit_cell_pushes_to_perimeter():
    fp = _fp("circle")
    # from the center walking +x must land on the last building cell (perimeter)
    ex = fp.exit_cell((10, 10), (1, 0))
    assert fp.contains(*ex)
    assert not fp.contains(ex[0] + 1, ex[1])
