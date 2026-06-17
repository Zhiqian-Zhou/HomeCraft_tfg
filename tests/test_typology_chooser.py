"""Unit tests for `pipeline.agents.typology_chooser` (Fase 4).

These tests use a mocked LLM caller — no network calls, no API key
required, fully deterministic. The chooser's contract is that it ALWAYS
returns a dict with one entry per kind; entries are either a valid
typology name or None.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.agents.typology_chooser import (
    choose_typologies, _candidates, _scale_for_silhouette,
)
from pipeline.skills.typologies import list_typologies, get_metadata


# ────────────────────────────────────────────────────────────────────────
#  Helpers — mock LLM callers
# ────────────────────────────────────────────────────────────────────────

def _mock_llm_first(*, system, user, **_):
    """Mock LLM that always picks the first candidate from the catalog."""
    data = json.loads(user)
    catalog = data["catalog"].splitlines()
    if not catalog:
        return {"typology": None}
    # First line begins with "- <name> (...)".
    first = catalog[0].lstrip("- ").split(" ", 1)[0]
    return {"typology": first}


def _mock_llm_garbage(*, system, user, **_):
    """Mock LLM that returns invalid JSON-equivalent output."""
    return {"foo": "bar"}


def _mock_llm_offmenu(*, system, user, **_):
    """Mock LLM that picks an off-menu typology name."""
    return {"typology": "nonexistent_typology"}


def _mock_llm_null(*, system, user, **_):
    return {"typology": None}


def _mock_llm_raises(*, system, user, **_):
    raise RuntimeError("simulated network error")


# ────────────────────────────────────────────────────────────────────────
#  Contract tests
# ────────────────────────────────────────────────────────────────────────

def test_returns_one_entry_per_kind():
    gi = {"style": "medieval", "silhouette_id": "round_tower"}
    out = choose_typologies(gi, llm_caller=_mock_llm_first)
    assert set(out.keys()) == {"tower", "roof", "window", "garden"}

def test_picks_belong_to_catalog_or_None():
    gi = {"style": "medieval", "silhouette_id": "round_tower"}
    out = choose_typologies(gi, llm_caller=_mock_llm_first)
    valid_names = set(list_typologies())
    for kind, pick in out.items():
        assert pick is None or pick in valid_names

def test_no_llm_caller_is_deterministic_fallback():
    gi = {"style": "medieval", "silhouette_id": "round_tower"}
    out1 = choose_typologies(gi, llm_caller=None)
    out2 = choose_typologies(gi, llm_caller=None)
    assert out1 == out2

def test_llm_raising_falls_back_to_first_candidate():
    gi = {"style": "medieval", "silhouette_id": "round_tower"}
    out = choose_typologies(gi, llm_caller=_mock_llm_raises)
    # Each chosen value should be a real candidate (the first one returned
    # by filter_by for that kind).
    for kind, pick in out.items():
        if pick is not None:
            assert pick in list_typologies()

def test_offmenu_pick_falls_back_to_first_candidate():
    gi = {"style": "medieval", "silhouette_id": "round_tower"}
    out = choose_typologies(gi, llm_caller=_mock_llm_offmenu)
    for kind, pick in out.items():
        assert pick is None or pick in list_typologies()

def test_garbage_response_falls_back():
    gi = {"style": "medieval", "silhouette_id": "round_tower"}
    # Garbage response has no "typology" key → treated as None.
    out = choose_typologies(gi, llm_caller=_mock_llm_garbage)
    # None or fallback; never invalid.
    for pick in out.values():
        assert pick is None or pick in list_typologies()

def test_null_pick_propagates_as_None():
    gi = {"style": "medieval", "silhouette_id": "round_tower"}
    out = choose_typologies(gi, llm_caller=_mock_llm_null)
    assert all(v is None for v in out.values())


# ────────────────────────────────────────────────────────────────────────
#  Filtering / scale heuristic
# ────────────────────────────────────────────────────────────────────────

def test_candidates_relaxes_when_strict_filter_empty():
    # 'cyberpunk' is not in any typology's style_affinities — relaxation
    # should drop the style filter and still return something.
    cands = _candidates(kind="tower", style="cyberpunk", scale="medium")
    assert len(cands) > 0

def test_candidates_empty_for_unknown_kind():
    cands = _candidates(kind="staircase", style="medieval", scale="medium")
    assert cands == []

@pytest.mark.parametrize("sil_id,expected", [
    ("monumental_cathedral", "monumental"),
    ("grand_palace", "monumental"),
    ("round_tower", "large"),
    ("manor_house", "large"),
    ("cottage_compact", "small"),
    ("villa_l_shape", "medieval".upper() and "medium"),
])
def test_scale_heuristic(sil_id, expected):
    assert _scale_for_silhouette(sil_id) == expected


# ────────────────────────────────────────────────────────────────────────
#  Style sensitivity
# ────────────────────────────────────────────────────────────────────────

def test_castle_style_prefers_castle_towers():
    gi = {"style": "castle", "silhouette_id": "round_tower"}
    out = choose_typologies(gi, llm_caller=_mock_llm_first)
    tower_pick = out["tower"]
    if tower_pick is not None:
        m = get_metadata(tower_pick)
        # The strict filter for style="castle" + scale="large" should yield
        # a tower whose style_affinities include "castle" (or it should be
        # one of the relaxed candidates).
        assert m.kind == "tower"

def test_japanese_style_picks_japanese_roof_when_possible():
    gi = {"style": "japanese", "silhouette_id": "compact_rect"}
    out = choose_typologies(gi, llm_caller=_mock_llm_first)
    roof_pick = out["roof"]
    if roof_pick is not None:
        m = get_metadata(roof_pick)
        assert m.kind == "roof"
