"""Tests for global_designer — LLM patched out, focus on input/output contract."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline.agents import global_designer


VALID_FAKE = {
    "schema_version": "1.0",
    "prompt": "test prompt",
    "category": "residential",
    "style": "medieval",
    "exemplars_used": ["hf-asskd-00010"],
    "site_aabb": [0, 0, 0, 12, 10, 12],
    "building_aabb": [1, 0, 1, 11, 8, 11],
    "floors": [
        {"index": 0, "y0": 0, "y1": 4, "name": "ground", "role_hint": "ground"},
        {"index": 1, "y0": 4, "y1": 8, "name": "upper", "role_hint": "upper"},
    ],
    "height_intent": {
        "per_floor_height": 4, "roof_style": "gable",
        "roof_pitch": 2, "has_basement": False, "tower_axis": "none",
    },
    "alexander_rationale": [
        {"pattern_id": "sheltering-roof", "applied_to": ["roof"],
         "rationale": "pitched roof for shelter feel"},
    ],
}


def test_design_global_returns_validated_dict():
    with patch.object(global_designer, "call_llm_json", return_value=dict(VALID_FAKE)):
        with patch.object(global_designer, "retrieve",
                            return_value=[{"id": "hf-asskd-00010", "title": "x",
                                            "score": 0.5, "composite_score": 0.7,
                                            "style": ["medieval"], "category": "residential",
                                            "size_bucket": "small",
                                            "voxels_count": 100, "bbox_size": [10, 5, 10],
                                            "description_short": "x"}]):
            doc = global_designer.design_global("a cottage")
    assert doc["style"] == "medieval"
    assert doc["schema_version"] == "1.0"
    assert len(doc["floors"]) == 2


def test_design_global_retries_on_schema_failure():
    """First LLM response is missing required field; second is valid."""
    bad = {"prompt": "x"}  # missing many required
    good = dict(VALID_FAKE)
    with patch.object(global_designer, "call_llm_json",
                        side_effect=[bad, good]):
        with patch.object(global_designer, "retrieve", return_value=[]):
            doc = global_designer.design_global("a cottage")
    assert doc["style"] == "medieval"


def test_design_global_raises_after_two_failures():
    bad = {"prompt": "x"}
    with patch.object(global_designer, "call_llm_json",
                        side_effect=[bad, bad]):
        with patch.object(global_designer, "retrieve", return_value=[]):
            with pytest.raises(ValueError, match="failed validation"):
                global_designer.design_global("a cottage")


def test_normalize_fills_defaults():
    doc = {"prompt": "x", "category": "residential", "style": "medieval",
            "site_aabb": [0, 0, 0, 10, 6, 10],
            "building_aabb": [0, 0, 0, 10, 5, 10],
            "floors": [{"index": 0, "y0": 0, "y1": 4}]}
    global_designer._normalize(doc, "x")
    assert doc["schema_version"] == "1.0"
    assert doc["height_intent"] == {}
    assert doc["alexander_rationale"] == []
    assert doc["exemplars_used"] == []


def test_normalize_coerces_float_roof_pitch():
    doc = {"prompt": "x", "category": "residential", "style": "medieval",
            "site_aabb": [0, 0, 0, 10, 6, 10],
            "building_aabb": [0, 0, 0, 10, 5, 10],
            "floors": [{"index": 0, "y0": 0, "y1": 4}],
            "height_intent": {"roof_pitch": 2.5}}
    global_designer._normalize(doc, "x")
    assert doc["height_intent"]["roof_pitch"] == 2
