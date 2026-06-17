"""Tests for pipeline.agents.prompt_expander.expand_v4 — slim v4 path."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline.agents import prompt_expander


GOOD_V4 = {
    "schema_version": "v4",
    "original_prompt": "small cottage",
    "expanded_description": (
        "A modest cottage with low eaves and dark-oak timber framing over a "
        "stone-brick base; small leaded windows, a central hearth, and a "
        "thatched or shingled roof that pitches close to the ground. The "
        "vibe is cozy and lived-in, with weathered materials and a sense "
        "of warmth radiating from inside. Massing is low and grounded; the "
        "footprint stays compact and the building sits as if it grew from "
        "the meadow around it. Plain board doors, narrow paths, simple "
        "furnishings — nothing ostentatious, everything purposeful and worn."
    ),
}


def test_expand_v4_returns_validated_minimal_dict():
    with patch.object(prompt_expander, "call_llm_json",
                       return_value=dict(GOOD_V4)):
        doc = prompt_expander.expand_v4("small cottage")
    assert set(doc.keys()) == {"schema_version", "original_prompt",
                                 "expanded_description", "implied_rooms"}
    assert doc["schema_version"] == "v4"
    assert doc["original_prompt"] == "small cottage"
    assert len(doc["expanded_description"]) >= 50


def test_expand_v4_pins_original_prompt():
    """Even if the LLM rewrites original_prompt, the agent must restore it."""
    polluted = dict(GOOD_V4)
    polluted["original_prompt"] = "a totally different prompt"
    with patch.object(prompt_expander, "call_llm_json", return_value=polluted):
        doc = prompt_expander.expand_v4("small cottage")
    assert doc["original_prompt"] == "small cottage"


def test_expand_v4_strips_extra_fields():
    """LLM may emit v3-style fields; v4 schema forbids them — must strip.
    EXCEPCIÓN: implied_rooms se conserva pero se REEMPLAZA por el parse
    determinista del prompt (FIX A), no por lo que emita el LLM."""
    polluted = dict(GOOD_V4)
    polluted["implied_style"] = "medieval"
    polluted["implied_rooms"] = ["kitchen"]   # del LLM → se ignora
    polluted["constraints"] = ["under 2 floors"]
    with patch.object(prompt_expander, "call_llm_json", return_value=polluted):
        doc = prompt_expander.expand_v4("small cottage")
    assert "implied_style" not in doc
    assert "constraints" not in doc
    # implied_rooms presente, pero parseado de "small cottage" (=[]), NO ["kitchen"]
    assert doc.get("implied_rooms") == []


def test_expand_v4_retries_on_schema_failure_then_succeeds():
    bad = {"schema_version": "v4", "original_prompt": "x",
            "expanded_description": "too short"}  # < minLength
    with patch.object(prompt_expander, "call_llm_json",
                       side_effect=[bad, dict(GOOD_V4)]):
        doc = prompt_expander.expand_v4("small cottage")
    assert doc["schema_version"] == "v4"


def test_expand_v4_raises_after_persistent_schema_failure():
    """Gym constraint: no silent fallback. Persistent invalid output → raise."""
    bad = {"foo": "bar"}
    with patch.object(prompt_expander, "call_llm_json",
                       side_effect=[bad, bad, bad, bad]):
        with pytest.raises(ValueError, match="schema invalid"):
            prompt_expander.expand_v4("small cottage with a stone hearth")


def test_expand_v4_raises_on_persistent_llm_exception():
    """LLM raising for all max_attempts → bubble up as RuntimeError."""
    with patch.object(prompt_expander, "call_llm_json",
                       side_effect=RuntimeError("network down")):
        with pytest.raises(RuntimeError, match="failed after"):
            prompt_expander.expand_v4("tower of glass")


def test_v3_expand_still_works_unchanged():
    """Sanity: the legacy v3 expand() function is untouched and still valid."""
    legacy_good = {
        "original_prompt": "small cottage",
        "expanded_description": "A cozy cottage description. " * 10,
        "implied_style": "medieval",
        "implied_size_bucket": "small",
        "implied_category": "residential",
        "implied_rooms": ["kitchen", "bedroom"],
        "implied_exterior_features": [],
        "atmosphere": "cozy",
        "alexander_intent_keywords": ["intimacy-gradient"],
        "constraints": [],
    }
    with patch.object(prompt_expander, "call_llm_json",
                       return_value=dict(legacy_good)):
        doc = prompt_expander.expand("small cottage")
    assert doc["implied_style"] == "medieval"
    assert doc["original_prompt"] == "small cottage"
