"""Smoke tests for the evaluator: load the 5 iter05 generations and
verify evaluate() returns a schema-valid report without raising.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GENS = REPO_ROOT / "scratch" / "generations"

from pipeline.agents.evaluator import evaluate  # noqa: E402


@pytest.fixture(scope="module")
def iter05_files():
    return sorted(GENS.glob("iter05-prompt*.json"))


def test_iter05_generations_exist(iter05_files):
    """All 5 iter05 buildings should be present."""
    # Filter sidecars
    buildings = [f for f in iter05_files if not f.name.endswith(".evaluation.json")]
    assert len(buildings) == 5, f"Expected 5 buildings, found {len(buildings)}"


@pytest.mark.parametrize("idx", [0, 1, 2, 3, 4])
def test_evaluate_does_not_raise(idx, iter05_files):
    """evaluate() on each iter05 building should produce a non-empty report."""
    buildings = [f for f in iter05_files if not f.name.endswith(".evaluation.json")]
    doc = json.loads(buildings[idx].read_text(encoding="utf-8"))
    report = evaluate(doc, run_critique=False)
    assert "composite" in report
    assert report["composite"]["overall"] is not None
    assert 0.0 <= report["composite"]["overall"] <= 1.0


def test_dispatcher_signatures_accept_master_plan():
    """Calling evaluate without master_plan should still work."""
    buildings = sorted((REPO_ROOT / "scratch" / "generations").glob("iter05-prompt*.json"))
    buildings = [f for f in buildings if not f.name.endswith(".evaluation.json")]
    if not buildings:
        pytest.skip("no iter05 buildings to test")
    doc = json.loads(buildings[0].read_text(encoding="utf-8"))
    # No master_plan, no design_intent
    report = evaluate(doc, run_critique=False)
    assert "physical" in report
    assert "alexander" in report
    # physical metrics (10: corrección estructural + habitabilidad; la adecuación
    # al prompt vive en su propio apartado report["prompt_adherence"]).
    expected_phys = {"structural_integrity", "voxel_connectivity", "vertical_clearance",
                     "door_functionality", "light_coverage", "block_legitimacy",
                     "material_consistency", "volume_density", "envelope_integrity",
                     "room_furnishing"}
    expected_alex = {"light_on_two_sides", "intimacy_gradient", "common_areas_at_heart",
                     "sheltering_roof", "building_edge", "window_place",
                     "entrance_transition", "main_entrance", "farmhouse_kitchen",
                     "roof_layout"}
    assert set(report["physical"].keys()) == expected_phys
    assert set(report["alexander"].keys()) == expected_alex
    # apartado de adecuación al prompt (fidelidad al texto pedido)
    assert "prompt_adherence" in report
    assert set(report["prompt_adherence"].keys()) == {
        "room_count", "furniture", "materials", "floors"}
    # cada sub-métrica de prompt tiene score (número o None)
    for m in report["prompt_adherence"].values():
        assert "score" in m


def test_conftest_build_doc():
    """The build_doc helper produces a usable synthetic doc."""
    from tests.conftest import build_doc, solid_box
    voxels = solid_box(0, 0, 0, 3, 3, 3, "minecraft:stone")
    doc = build_doc(voxels)
    assert doc["bounding_box"]["size"] == [3, 3, 3]
    assert len(doc["voxels"]) == 27
    assert "minecraft:stone" in doc["block_palette"].values()
