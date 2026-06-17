"""Tests for tools.gym.genericness — validates skill generic-ness."""
from __future__ import annotations

from tools.gym.genericness import is_generic


def _base_skill(**overrides) -> dict:
    s = {
        "id": "test-skill",
        "skill_category": "wall_fitting",
        "schema_version": "2.0",
        "applicable_to": ["residential", "tavern", "barn"],
        "parameters": {"width": "2-4", "color": "oak_or_spruce"},
        "tags": {"category": "wall", "style": ["medieval", "rustic"]},
        "alexander_patterns_relevant": ["building-edge"],
        "description": ("A medieval and rustic wall treatment that "
                         "applies to residential and tavern buildings."),
    }
    s.update(overrides)
    return s


def test_generic_skill_passes():
    passes, fails = is_generic(_base_skill())
    assert passes is True
    assert fails == []


def test_narrow_applicable_to_fails_mandatory():
    s = _base_skill(applicable_to=["residential"])
    passes, fails = is_generic(s)
    assert passes is False
    assert any("MANDATORY: applicable_to" in f for f in fails)


def test_fixed_parameters_fail_mandatory():
    s = _base_skill(parameters={"width": 3, "color": "oak"})
    passes, fails = is_generic(s)
    assert passes is False
    assert any("MANDATORY: parameters" in f for f in fails)


def test_enum_parameter_passes_with_pipe():
    s = _base_skill(parameters={"door_type": "single|double|sliding"})
    passes, _ = is_generic(s)
    assert passes is True


def test_single_style_is_soft_fail_but_still_passes():
    s = _base_skill(
        tags={"category": "wall", "style": ["medieval"]},
        # description must still name >=2 declared, so add the categories
        description=("A medieval treatment applying to residential, "
                      "tavern, and barn buildings."),
    )
    passes, fails = is_generic(s)
    # 1 soft fail (style count) is acceptable
    assert passes is True
    assert any("tags.style has 1" in f for f in fails)


def test_two_soft_fails_reject():
    s = _base_skill(
        tags={"category": "wall", "style": ["medieval"]},   # soft fail 1
        alexander_patterns_relevant=[],                       # soft fail 2
    )
    passes, fails = is_generic(s)
    assert passes is False
    assert len(fails) >= 2


def test_description_without_style_mention_fails():
    s = _base_skill(
        description="A wall treatment. " * 5,
    )
    passes, fails = is_generic(s)
    # description names 0 of declared → 1 soft fail; mandatory rules OK → passes
    assert any("description names only" in f for f in fails)


def test_empty_alexander_patterns_is_soft_fail():
    s = _base_skill(alexander_patterns_relevant=[])
    passes, fails = is_generic(s)
    assert passes is True   # only 1 soft fail
    assert any("alexander_patterns_relevant is empty" in f for f in fails)
