"""Tests for the v4 room_agent skill filter.

The v4 path adds `_load_skills_for_room(role, skill_category=...)` that
filters by BOTH `tags.category == role` AND `skill_category ==
<category>`. With room_decoration extraction deferred (currently 0
skills in that category), the fallback to room_role keeps the agent
functional.
"""
from __future__ import annotations

from pipeline.agents import room_agent


def test_v3_load_skills_by_role_returns_kitchen():
    skills = room_agent._load_skills_by_role("kitchen")
    ids = [s["id"] for s in skills]
    assert "kitchen" in ids


def test_v4_load_skills_for_room_room_decoration_currently_empty():
    """room_decoration extraction is deferred — primary returns []."""
    primary = room_agent._load_skills_for_room(
        "kitchen", skill_category="room_decoration", fallback=None)
    assert primary == []


def test_v4_load_skills_for_room_falls_back_to_room_role():
    """With fallback=room_role, the v4 filter still returns kitchen skills."""
    skills = room_agent._load_skills_for_room(
        "kitchen", skill_category="room_decoration", fallback="room_role")
    ids = [s["id"] for s in skills]
    assert "kitchen" in ids


def test_v4_load_skills_for_room_primary_only_no_fallback():
    primary = room_agent._load_skills_for_room(
        "kitchen", skill_category="room_role", fallback=None)
    ids = [s["id"] for s in primary]
    assert "kitchen" in ids


def test_v4_load_skills_for_room_handles_role_aliasing():
    """living_room ↔ living-room should both resolve."""
    a = room_agent._load_skills_for_room(
        "living_room", skill_category="room_role", fallback=None)
    b = room_agent._load_skills_for_room(
        "living-room", skill_category="room_role", fallback=None)
    assert {s["id"] for s in a} == {s["id"] for s in b}


def test_v4_unknown_role_returns_empty_even_with_fallback():
    out = room_agent._load_skills_for_room(
        "nonexistent_role", skill_category="room_decoration",
        fallback="room_role")
    assert out == []


def test_v4_brief_shape_matches_v3():
    v3 = room_agent._load_skills_by_role("kitchen")
    v4 = room_agent._load_skills_for_room(
        "kitchen", skill_category="room_role", fallback=None)
    if v3 and v4:
        # Same kitchen entry should show identical brief shape
        assert set(v3[0].keys()) == set(v4[0].keys())
