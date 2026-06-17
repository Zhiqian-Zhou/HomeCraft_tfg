"""Integration test for the Fase 4 voxelizer dispatch path.

Verifies that a master_plan op of `kind="typology"` is correctly
dispatched through `pipeline.skills.typologies.get_typology()` and
materialized into voxels by the composer.
"""
from __future__ import annotations

from pipeline.skills.base import Materials
from pipeline.agents.voxelizer import _expand_ops


def test_typology_op_dispatched_to_get_typology():
    """A typology op should produce real ops via the registry."""
    master_ops = [
        {"kind": "typology", "name": "norman_keep",
         "aabb": [0, 0, 0, 12, 22, 12], "style": "gothic"},
    ]
    materials = Materials.for_style("gothic")
    ops = list(_expand_ops(master_ops, style="gothic", materials=materials))
    # NormanKeep emits a FillHollow + buttress strips + crenellated ring
    # + slits — definitely > 0 ops.
    assert len(ops) > 0


def test_unknown_typology_raises():
    """An invalid typology name should propagate the ImportError so the
    pipeline fails loudly rather than silently producing empty voxels."""
    master_ops = [
        {"kind": "typology", "name": "definitely_not_a_typology",
         "aabb": [0, 0, 0, 8, 8, 8]},
    ]
    materials = Materials.for_style("medieval")
    import pytest
    with pytest.raises((ImportError, ModuleNotFoundError)):
        list(_expand_ops(master_ops, style="medieval", materials=materials))


def test_skill_op_still_works_after_dispatch_extension():
    """Regression: the existing kind='skill' path is unaffected by Fase 4."""
    # Use a small atomic skill that's known to produce ops.
    master_ops = [
        {"kind": "skill", "skill_id": "chimney",
         "aabb": [0, 0, 0, 3, 8, 3], "style": "medieval"},
    ]
    materials = Materials.for_style("medieval")
    ops = list(_expand_ops(master_ops, style="medieval", materials=materials))
    assert len(ops) > 0


def test_atomic_op_passes_through():
    """A non-skill, non-typology op should be returned by op_from_dict
    unchanged."""
    master_ops = [
        {"kind": "place", "at": [3, 4, 5], "block": "minecraft:stone"},
    ]
    materials = Materials.for_style("medieval")
    ops = list(_expand_ops(master_ops, style="medieval", materials=materials))
    assert len(ops) == 1
