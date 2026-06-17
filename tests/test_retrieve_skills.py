"""Tests for pipeline.agents.retriever.retrieve_skills().

Uses the real rag/skills/ catalog (50 migrated entries) so the test
doubles as a sanity check on the v4 migration.
"""
from __future__ import annotations

import pytest

from pipeline.agents.retriever import (
    retrieve_skills, _reset_skills_cache, _skills,
)


@pytest.fixture(autouse=True)
def _reset():
    _reset_skills_cache()
    yield
    _reset_skills_cache()


def test_retrieve_room_role_returns_kitchen():
    hits = retrieve_skills("room_role", k=10, query="kitchen with stove")
    ids = [h["id"] for h in hits]
    assert "kitchen" in ids


def test_retrieve_global_silhouette_returns_roof_skills():
    hits = retrieve_skills("global_silhouette", k=10)
    ids = [h["id"] for h in hits]
    # Migrated: dome_roof, gabled_roof, hip_roof, flat_roof
    assert any("roof" in i for i in ids)
    assert len(hits) >= 4


def test_retrieve_connector_template_includes_doors_and_stairs():
    # k=30 because B.3 added 20 connector_templates → staircase is now mid-pack
    hits = retrieve_skills("connector_template", k=30)
    ids = [h["id"] for h in hits]
    assert "staircase" in ids
    assert any("door" in i or "arch" in i for i in ids)


def test_retrieve_wall_fitting_includes_windows():
    hits = retrieve_skills("wall_fitting", k=10)
    ids = [h["id"] for h in hits]
    assert any("window" in i for i in ids)


def test_retrieve_exterior_feature_includes_garden():
    hits = retrieve_skills("exterior_feature", k=20)
    ids = [h["id"] for h in hits]
    assert "garden_bed" in ids or "fountain" in ids


def test_retrieve_unknown_category_returns_empty():
    assert retrieve_skills("nonexistent_bucket", k=5) == []


def test_query_changes_ranking():
    """An empty query yields id-sorted results; a specific query reorders."""
    no_q = retrieve_skills("room_role", k=5, query="")
    yes_q = retrieve_skills("room_role", k=5, query="kitchen heart of the home")
    assert no_q != yes_q or len(no_q) == 0  # at least one ordering differs


def test_applicable_to_filter_residential():
    """Filtering by applicable_to keeps universals (empty applicable_to)."""
    # Our 50 legacy skills don't have applicable_to populated, so they all
    # count as "universal" → filter should still return all room_role entries.
    hits = retrieve_skills("room_role", k=20, applicable_to="residential")
    assert len(hits) > 0


def test_brief_shape_contract():
    hits = retrieve_skills("room_role", k=1)
    assert hits
    h = hits[0]
    expected_keys = {"id", "name", "description", "skill_category", "kind",
                      "category", "style", "applicable_to", "parameters",
                      "typical_dimensions", "alexander_patterns", "examples"}
    assert expected_keys.issubset(h.keys())


def test_cache_picks_up_new_skill(tmp_path):
    """If we point _SKILLS at a tmp dir and add a new file, cache reflects it."""
    from pipeline.agents import retriever as r
    # Build a fresh skills cache pointing at tmp_path
    sk = r._LoadedSkills(tmp_path)
    sk._maybe_refresh()
    assert sk.entries == []
    # Write a v2.0 skill
    import json as _json
    (tmp_path / "foo.json").write_text(_json.dumps({
        "id": "test_skill",
        "name": "Test",
        "kind": "structural",
        "description": "A synthetic test skill",
        "typical_dimensions": {"preferred": [3, 3, 3]},
        "tags": {"category": "other"},
        "skill_category": "wall_fitting",
        "schema_version": "2.0",
    }), encoding="utf-8")
    sk._maybe_refresh()
    assert len(sk.entries) == 1
    assert sk.entries[0]["id"] == "test_skill"
