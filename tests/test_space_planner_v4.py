"""Tests for space_planner.plan_spaces_v4 — v4 floor-skeleton path.

LLM is patched out; tests focus on retrieval, schema validation, and the
floor_layout/connector cross-reference rules.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline.agents import space_planner


GLOBAL_INTENT = {
    "schema_version": "v4",
    "expanded_description": (
        "A modest two-floor medieval cottage with a kitchen-living ground "
        "floor entered through a formal porch and two bedrooms above "
        "reached by a dogleg stair. Cozy and lived-in, with timber framing."
    ),
    "silhouette_id": "gable-cottage-silhouette",
    "category": "residential",
    "style": "medieval",
    "site_aabb": [0, 0, 0, 14, 14, 12],
    "building_aabb": [1, 0, 1, 9, 9, 11],
    "floors": [
        {"index": 0, "y0": 0, "y1": 4, "name": "ground", "role_hint": "ground"},
        {"index": 1, "y0": 4, "y1": 8, "name": "upper", "role_hint": "upper"},
    ],
    "height_intent": {"per_floor_height": 4, "roof_style": "gable",
                       "roof_pitch": 2, "has_basement": False,
                       "tower_axis": "none"},
    "alexander_rationale": [
        {"pattern_id": "sheltering-roof", "rationale": "low gable"},
    ],
}

GOOD_OUTPUT = {
    "schema_version": "v4",
    "floor_layout_id_per_floor": [
        "linear-corridor-layout",
        "double-loaded-corridor-layout",
    ],
    "connector_templates_used": [
        {"template_id": "formal-front-entrance", "role": "entrance"},
        {"template_id": "dogleg-staircase", "role": "stair"},
    ],
    "vertical_connections": [
        {"from_floor": 0, "to_floor": 1, "template_id": "dogleg-staircase"},
    ],
    "entry_points": [
        {"floor": 0, "side": "+x", "template_id": "formal-front-entrance"},
    ],
    "room_role_hints_per_floor": [
        ["entry_hall", "kitchen", "living_room"],
        ["bedroom", "bedroom", "bathroom"],
    ],
}


@pytest.fixture(autouse=True)
def _reset_caches():
    space_planner._reset_v4_caches()
    yield
    space_planner._reset_v4_caches()


def test_floor_layouts_cache_loads_real_skills():
    cache = space_planner._floor_layouts()
    assert "linear-corridor-layout" in cache


def test_connector_templates_cache_loads_real_skills():
    cache = space_planner._connector_templates()
    assert "formal-front-entrance" in cache
    assert "dogleg-staircase" in cache


def test_layout_query_for_floor_includes_style_and_role():
    f = GLOBAL_INTENT["floors"][0]
    q = space_planner._layout_query_for_floor(f, GLOBAL_INTENT)
    assert "ground" in q
    assert "medieval" in q


def test_layout_query_seeds_attic_keywords():
    f = {"index": 2, "y0": 8, "y1": 12, "role_hint": "attic"}
    q = space_planner._layout_query_for_floor(f, GLOBAL_INTENT)
    assert "attic" in q and "loft" in q


def test_strict_floor_role_filter():
    # attic-truss-layout is bound to 'attic' role only
    assert "attic" in space_planner._STRICT_FLOOR_ROLE["attic-truss-layout"]


def _patches():
    """Common patch stack: LLM + retrieve + retrieve_skills."""
    fl_hit = {"id": "linear-corridor-layout"}
    fl_hit2 = {"id": "double-loaded-corridor-layout"}
    conn_hits = [{"id": "formal-front-entrance"},
                  {"id": "dogleg-staircase"}]

    def fake_retrieve_skills(category, **kwargs):
        if category == "floor_layout":
            return [fl_hit, fl_hit2]
        if category == "connector_template":
            return conn_hits
        return []

    return fake_retrieve_skills


def test_plan_spaces_v4_returns_validated_dict():
    with patch.object(space_planner, "call_llm_json",
                       return_value=dict(GOOD_OUTPUT)):
        with patch.object(space_planner, "retrieve", return_value=[]):
            with patch.object(space_planner, "retrieve_skills",
                                side_effect=_patches()):
                doc = space_planner.plan_spaces_v4(dict(GLOBAL_INTENT))
    assert doc["schema_version"] == "v4"
    assert len(doc["floor_layout_id_per_floor"]) == 2
    assert doc["floor_layout_id_per_floor"][0] == "linear-corridor-layout"


def test_plan_spaces_v4_strips_legacy_rooms_field():
    polluted = dict(GOOD_OUTPUT)
    polluted["rooms"] = [{"id": "kitchen-1", "role": "kitchen",
                          "floor": 0, "aabb": [1, 0, 1, 5, 4, 5]}]
    with patch.object(space_planner, "call_llm_json", return_value=polluted):
        with patch.object(space_planner, "retrieve", return_value=[]):
            with patch.object(space_planner, "retrieve_skills",
                                side_effect=_patches()):
                doc = space_planner.plan_spaces_v4(dict(GLOBAL_INTENT))
    assert "rooms" not in doc


def test_post_validate_v4_unknown_layout_id():
    doc = dict(GOOD_OUTPUT)
    doc["floor_layout_id_per_floor"] = ["totally-fake-layout",
                                          "double-loaded-corridor-layout"]
    errs = space_planner._post_validate_v4(doc, GLOBAL_INTENT)
    assert any("not a known floor_layout" in e for e in errs)


def test_post_validate_v4_layout_count_mismatch():
    doc = dict(GOOD_OUTPUT)
    doc["floor_layout_id_per_floor"] = ["linear-corridor-layout"]  # only 1
    errs = space_planner._post_validate_v4(doc, GLOBAL_INTENT)
    assert any("length" in e and "floors.length" in e for e in errs)


def test_post_validate_v4_vertical_connection_missing_for_multifloor():
    doc = dict(GOOD_OUTPUT)
    doc["vertical_connections"] = []
    errs = space_planner._post_validate_v4(doc, GLOBAL_INTENT)
    assert any("vertical_connections" in e for e in errs)


def test_post_validate_v4_vc_template_not_in_used():
    doc = dict(GOOD_OUTPUT)
    doc["vertical_connections"] = [
        {"from_floor": 0, "to_floor": 1, "template_id": "spiral-staircase"},
    ]
    # spiral-staircase NOT in connector_templates_used as stair
    errs = space_planner._post_validate_v4(doc, GLOBAL_INTENT)
    assert any("spiral-staircase" in e and "stair" in e for e in errs)


def test_post_validate_v4_no_entry_at_floor_zero():
    doc = dict(GOOD_OUTPUT)
    doc["entry_points"] = [{"floor": 1, "side": "+x",
                              "template_id": "formal-front-entrance"}]
    errs = space_planner._post_validate_v4(doc, GLOBAL_INTENT)
    assert any("floor=0" in e for e in errs)


def test_post_validate_v4_tower_forbids_grand_staircase():
    gi = dict(GLOBAL_INTENT)
    gi["silhouette_id"] = "tower-cylinder-silhouette"
    doc = dict(GOOD_OUTPUT)
    doc["connector_templates_used"] = [
        {"template_id": "formal-front-entrance", "role": "entrance"},
        {"template_id": "grand-staircase", "role": "stair"},
    ]
    doc["vertical_connections"] = [
        {"from_floor": 0, "to_floor": 1, "template_id": "grand-staircase"},
    ]
    errs = space_planner._post_validate_v4(doc, gi)
    assert any("grand-staircase" in e for e in errs)


def test_post_validate_v4_secondary_entrance_cap():
    doc = dict(GOOD_OUTPUT)
    doc["connector_templates_used"] = [
        {"template_id": "formal-front-entrance", "role": "entrance"},
        {"template_id": "dogleg-staircase", "role": "stair"},
        {"template_id": "garden-door", "role": "secondary_entrance"},
        {"template_id": "secondary-side-entrance", "role": "secondary_entrance"},
        {"template_id": "vestibule-with-coatroom", "role": "secondary_entrance"},
    ]
    errs = space_planner._post_validate_v4(doc, GLOBAL_INTENT)
    assert any("secondary_entrance" in e and ("max" in e or "too many" in e)
                for e in errs)


def test_post_validate_v4_single_floor_requires_no_vc():
    gi = dict(GLOBAL_INTENT)
    gi["floors"] = [{"index": 0, "y0": 0, "y1": 4, "name": "ground",
                      "role_hint": "ground"}]
    doc = dict(GOOD_OUTPUT)
    doc["floor_layout_id_per_floor"] = ["linear-corridor-layout"]
    doc["connector_templates_used"] = [
        {"template_id": "formal-front-entrance", "role": "entrance"},
    ]
    doc["vertical_connections"] = [
        {"from_floor": 0, "to_floor": 1, "template_id": "dogleg-staircase"},
    ]
    errs = space_planner._post_validate_v4(doc, gi)
    assert any("must be empty" in e for e in errs)


def test_v3_plan_spaces_still_works():
    """Sanity: the legacy v3 plan_spaces function is untouched."""
    # Just check the symbol still exists and is callable
    assert callable(space_planner.plan_spaces)
