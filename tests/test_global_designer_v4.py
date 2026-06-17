"""Tests for global_designer.design_global_v4 — v4 silhouette-anchored path.

LLM is patched out; tests focus on retrieval, schema validation, and the
silhouette-coherence post-validation rules.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline.agents import global_designer


# Borrowed shape from the C.2.3 schema draft.
GOOD_V4 = {
    "schema_version": "v4",
    "original_prompt": "small medieval cottage",
    "expanded_description": (
        "A modest single-storey cottage of timber and stone, with a gable "
        "roof of dark shingles and small leaded windows set deep in the "
        "thick walls. The footprint is compact and rectangular; the door "
        "sits in the long facade under a simple porch. The vibe is cozy, "
        "lived-in, and grounded — modest scale, warm interior."
    ),
    "silhouette_id": "gable-cottage-silhouette",
    "silhouette_parameters": {"aspect_ratio": "1.5"},
    "silhouette_rationale": (
        "Gable cottage matches the modest single-storey timber-stone "
        "footprint the prompt describes."
    ),
    "category": "residential",
    "style": "medieval",
    "exemplars_used": [],
    "site_aabb": [0, 0, 0, 14, 12, 12],
    "building_aabb": [1, 0, 1, 9, 7, 11],
    "floors": [
        {"index": 0, "y0": 0, "y1": 4, "name": "ground", "role_hint": "ground"},
    ],
    "height_intent": {
        "per_floor_height": 4,
        "roof_style": "gable",
        "roof_pitch": 2,
        "has_basement": False,
        "tower_axis": "none",
    },
    "alexander_rationale": [
        {"pattern_id": "sheltering-roof", "applied_to": ["roof"],
         "rationale": "low gable shelters the modest cottage footprint"},
    ],
}


@pytest.fixture(autouse=True)
def _reset_silhouette_cache():
    global_designer._reset_silhouette_cache()
    yield
    global_designer._reset_silhouette_cache()


def test_silhouettes_cache_loads_real_skills():
    cache = global_designer._silhouettes()
    assert "gable-cottage-silhouette" in cache
    assert cache["gable-cottage-silhouette"].get("skill_category") == "global_silhouette"


def test_distill_query_extracts_style_and_shape_words():
    q = global_designer._distill_silhouette_query(
        "A modest cottage in the medieval style with a low gable roof.")
    assert "cottage" in q
    assert "medieval" in q


def test_distill_query_keeps_first_sentence():
    text = "A tall narrow stone tower. It has crenellations and arrow slits."
    q = global_designer._distill_silhouette_query(text)
    assert q.startswith("A tall narrow stone tower")


def test_parse_floor_range_single():
    assert global_designer._parse_floor_range("1") == (1, 1)


def test_parse_floor_range_pair():
    assert global_designer._parse_floor_range("2-4") == (2, 4)


def test_parse_floor_range_malformed():
    assert global_designer._parse_floor_range("many") is None
    assert global_designer._parse_floor_range("") is None
    assert global_designer._parse_floor_range(None) is None


def test_design_global_v4_returns_validated_dict():
    with patch.object(global_designer, "call_llm_json",
                       return_value=dict(GOOD_V4)):
        with patch.object(global_designer, "retrieve", return_value=[]):
            with patch.object(global_designer, "retrieve_skills",
                                return_value=[{"id": "gable-cottage-silhouette"}]):
                doc = global_designer.design_global_v4(
                    GOOD_V4["expanded_description"],
                    original_prompt="small medieval cottage")
    assert doc["schema_version"] == "v4"
    assert doc["silhouette_id"] == "gable-cottage-silhouette"
    assert doc["expanded_description"] == GOOD_V4["expanded_description"]


def test_design_global_v4_pins_expanded_description():
    """Even if the LLM mutates expanded_description, agent must restore."""
    polluted = dict(GOOD_V4)
    polluted["expanded_description"] = "totally different paragraph " * 5
    with patch.object(global_designer, "call_llm_json", return_value=polluted):
        with patch.object(global_designer, "retrieve", return_value=[]):
            with patch.object(global_designer, "retrieve_skills",
                                return_value=[{"id": "gable-cottage-silhouette"}]):
                doc = global_designer.design_global_v4(
                    GOOD_V4["expanded_description"])
    assert doc["expanded_description"] == GOOD_V4["expanded_description"]


def test_design_global_v4_drops_legacy_prompt_field():
    """LLM might emit v3-style 'prompt' field; v4 schema forbids it."""
    polluted = dict(GOOD_V4)
    polluted["prompt"] = "echo of the v3 contract"
    with patch.object(global_designer, "call_llm_json", return_value=polluted):
        with patch.object(global_designer, "retrieve", return_value=[]):
            with patch.object(global_designer, "retrieve_skills",
                                return_value=[{"id": "gable-cottage-silhouette"}]):
                doc = global_designer.design_global_v4(
                    GOOD_V4["expanded_description"])
    assert "prompt" not in doc


def test_design_global_v4_retries_on_unknown_silhouette_id():
    """LLM picks a bogus silhouette_id → post-validation triggers retry."""
    bad = dict(GOOD_V4)
    bad["silhouette_id"] = "made-up-id-not-real"
    good = dict(GOOD_V4)
    with patch.object(global_designer, "call_llm_json",
                       side_effect=[bad, good]):
        with patch.object(global_designer, "retrieve", return_value=[]):
            with patch.object(global_designer, "retrieve_skills",
                                return_value=[{"id": "gable-cottage-silhouette"}]):
                doc = global_designer.design_global_v4(
                    GOOD_V4["expanded_description"])
    assert doc["silhouette_id"] == "gable-cottage-silhouette"


def test_design_global_v4_accepts_atypical_style_with_warning(capsys):
    """2026-05-30 RELAJADO: LLM picks style outside silhouette.tags.style →
    soft stderr warn but does NOT raise. Variety > silhouette-style coercion."""
    bad = dict(GOOD_V4)
    bad["style"] = "modern"  # gable-cottage accepts medieval/rustic/fantasy
    with patch.object(global_designer, "call_llm_json", side_effect=[bad]):
        with patch.object(global_designer, "retrieve", return_value=[]):
            with patch.object(global_designer, "retrieve_skills",
                                return_value=[{"id": "gable-cottage-silhouette"}]):
                doc = global_designer.design_global_v4(
                    GOOD_V4["expanded_description"])
    assert doc["style"] == "modern"
    captured = capsys.readouterr()
    assert "atypical" in captured.err or "WARN" in captured.err


def test_post_validate_v4_below_min_dimensions_is_soft_warning(capsys):
    """2026-05-30 RELAJADO: building_aabb < silhouette.min → soft stderr warn
    (not a hard error). The LLM's geometry choice is respected as-is."""
    doc = dict(GOOD_V4)
    doc["building_aabb"] = [0, 0, 0, 2, 3, 2]  # 2×3×2, way below gable min
    errs = global_designer._post_validate_v4(
        doc, allowed_sil_ids={"gable-cottage-silhouette"})
    assert not any("below silhouette" in e for e in errs)
    captured = capsys.readouterr()
    assert "below silhouette" in captured.err


def test_post_validate_v4_above_max_is_soft_warning(capsys):
    """building_aabb above max should warn but not fail."""
    doc = dict(GOOD_V4)
    # gable-cottage max=[10,12,18]; make it huge
    doc["building_aabb"] = [0, 0, 0, 30, 12, 30]
    doc["site_aabb"] = [0, 0, 0, 32, 14, 32]
    errs = global_designer._post_validate_v4(doc, allowed_sil_ids={"gable-cottage-silhouette"})
    # No hard error about "above max" — soft warnings go to stderr
    assert not any("above silhouette" in e for e in errs)
    captured = capsys.readouterr()
    assert "above silhouette" in captured.err or "above" in captured.err
