"""Tests for exterior_agent.select_exterior_features — deterministic picker."""
from __future__ import annotations

from pipeline.agents.exterior_agent import select_exterior_features

B = [4, 0, 4, 16, 12, 16]
S = [0, 0, 0, 20, 15, 20]


def _ids(cat, style, sil="x-silhouette"):
    return [f["skill_hint"] for f in select_exterior_features(cat, style, sil, B, S)]


def test_castle_gets_walls_towers_moat():
    ids = _ids("castle", "gothic")
    assert "perimeter_wall_fortified" in ids
    assert "gatehouse" in ids
    assert "moat" in ids
    assert ids.count("round_tower") >= 2          # corner towers


def test_villa_gets_garden_and_fountain():
    ids = _ids("residential", "mediterranean")
    assert "garden_bed" in ids and "fountain" in ids
    assert "perimeter_wall_fortified" not in ids   # not a castle


def test_temple_gets_statue():
    assert "statue_pedestal" in _ids("temple", "japanese")


def test_categories_differ():
    assert set(_ids("castle", "gothic")) != set(_ids("residential", "mediterranean"))


def test_features_lie_in_apron_not_inside_building():
    feats = select_exterior_features("castle", "gothic", "x", B, S)
    for f in feats:
        a = f["aabb"]
        assert len(a) == 6
        # within the site
        assert S[0] <= a[0] < a[3] <= S[3] and S[2] <= a[2] < a[5] <= S[5]


def test_bad_input_returns_empty():
    assert select_exterior_features("castle", "gothic", "x", None, S) == []
