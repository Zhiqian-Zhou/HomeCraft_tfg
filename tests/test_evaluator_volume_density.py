"""Tests for `_volume_density` (recalibrated to RAG-E corpus IQR).

Window:  default regime (total >= 100) — [0.12, 0.33] optimal, zeros at <=0.05 / >=0.50.
         small regime  (total <  100) — [0.08, 0.45] optimal, zeros at <=0.02 / >=0.70.
"""
from __future__ import annotations

import pytest

from pipeline.agents.evaluator import _volume_density, _build_voxel_map
from tests.conftest import build_doc, solid_box


def _doc_with_n_solids(W: int, H: int, D: int, n: int) -> tuple[dict, dict]:
    """Build a doc with explicit bbox size=(W,H,D) and exactly `n` solid voxels,
    then return (doc, vmap) where vmap is produced by the canonical builder.
    Solids are laid out as a contiguous strip starting at (0,0,0)."""
    voxels = []
    for i in range(n):
        # Lay them along x-axis first, then y, then z, all within bbox
        x = i % W
        y = (i // W) % H
        z = (i // (W * H)) % D
        voxels.append((x, y, z, "minecraft:stone"))
    doc = build_doc(voxels, size=(W, H, D))
    vmap = _build_voxel_map(doc)
    return doc, vmap


def test_volume_density_optimal_corpus_value():
    """ratio=0.22 (mediana del corpus) cae en IQR -> score=1.0."""
    doc, vmap = _doc_with_n_solids(10, 10, 10, 220)   # total=1000
    result = _volume_density(doc, vmap)
    assert result["score"] == pytest.approx(1.0, abs=0.001)
    assert result["solid_ratio"] == pytest.approx(0.22, abs=0.005)
    assert "[default regime]" in result["notes"]


def test_volume_density_lower_boundary_p5_returns_zero():
    """ratio=0.05 (=p05 del corpus) -> score=0 exacto."""
    doc, vmap = _doc_with_n_solids(10, 10, 10, 50)    # total=1000, ratio=0.05
    result = _volume_density(doc, vmap)
    assert result["score"] == 0.0
    assert "[default regime]" in result["notes"]


def test_volume_density_upper_boundary_p95_returns_zero():
    """ratio=0.50 (=p95 corpus) -> score=0 (mausoleo)."""
    doc, vmap = _doc_with_n_solids(10, 10, 10, 500)   # ratio=0.50
    result = _volume_density(doc, vmap)
    assert result["score"] == 0.0


def test_volume_density_low_ramp_midpoint():
    """ratio=0.085 a media rampa baja -> score ~ 0.5.

    (0.085 - 0.05) / (0.12 - 0.05) = 0.5
    """
    doc, vmap = _doc_with_n_solids(10, 10, 10, 85)
    result = _volume_density(doc, vmap)
    assert result["score"] == pytest.approx(0.5, abs=0.02)


def test_volume_density_high_ramp_midpoint():
    """ratio=0.415 a media rampa alta -> score ~ 0.5.

    (0.50 - 0.415) / (0.50 - 0.33) = 0.5
    """
    doc, vmap = _doc_with_n_solids(10, 10, 10, 415)
    result = _volume_density(doc, vmap)
    assert result["score"] == pytest.approx(0.5, abs=0.02)


def test_volume_density_empty_vmap_scores_zero():
    """vmap vacío -> ratio=0 -> score=0 (frame/cage)."""
    doc = build_doc([], size=(5, 5, 5))               # total=125 -> default regime
    result = _volume_density(doc, {})
    assert result["score"] == 0.0
    assert result["solid_blocks"] == 0


def test_volume_density_degenerate_bbox_zero_dim():
    """bbox con dim=0 -> early return con score=0 y notes específico."""
    doc = build_doc([], size=(0, 5, 5))
    result = _volume_density(doc, {})
    assert result["score"] == 0.0
    assert result["notes"] == "degenerate bbox"
    assert result["total_cells"] == 0


def test_volume_density_corrupt_solid_greater_than_total():
    """solid>total -> clamp a 1.0, notes con [corrupt]."""
    # bbox total=100 (default regime). Pass a vmap with 120 entries directly
    # (cannot place 120 voxels in a 4x5x5 bbox via _build_voxel_map without
    # collisions, so we synthesize an oversized vmap that simulates upstream
    # corruption — this is the very scenario the clamp guards against).
    doc = build_doc(solid_box(0, 0, 0, 4, 5, 5), size=(4, 5, 5))   # total=100
    vmap = {(i, 0, 0): "minecraft:stone" for i in range(120)}      # solid=120 > total
    result = _volume_density(doc, vmap)
    assert result["solid_ratio"] == 1.0
    assert "[corrupt: solid>total, clamped]" in result["notes"]
    assert result["score"] == 0.0     # 1.0 > hi_z (0.50) -> zero zone


def test_volume_density_small_building_regime_active():
    """total<100 -> rama permissive; ratio=0.148 -> 1.0 (lo_ok_small=0.08)."""
    doc, vmap = _doc_with_n_solids(3, 3, 3, 4)        # total=27 -> small regime
    result = _volume_density(doc, vmap)
    assert result["score"] == pytest.approx(1.0, abs=0.001)
    assert "[small regime]" in result["notes"]


def test_volume_density_malformed_bbox_returns_zero():
    """doc sin bounding_box válido -> score=0 sin crash."""
    # Build a valid doc, then strip bounding_box.size to simulate malformed input.
    doc = build_doc([], size=(5, 5, 5))
    doc["bounding_box"] = {}
    result = _volume_density(doc, {(0, 0, 0): "minecraft:stone"})
    assert result["score"] == 0.0
    assert "missing or malformed" in result["notes"]
