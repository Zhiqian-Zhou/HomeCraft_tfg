"""Unit tests for Fase 6 — `_typology_diversity_score` in the gym runner.

The gym is a heavy harness (parallel LLM builds, evaluator, etc.); these
tests exercise ONLY the pure-Python diversity metric over synthetic
on-disk fixtures (no LLM, no pipeline).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.gym.runner import _typology_diversity_score, _typology_signature
from tools.gym.report import BuildResult


def _mk_build(tmp_path: Path, slot: str, gi: dict) -> BuildResult:
    """Write a fake global_intent.json for a build slot and return its
    `BuildResult` stub."""
    gen_id = f"gym-i00-{slot}"
    workdir = tmp_path / gen_id
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "global_intent.json").write_text(
        json.dumps(gi), encoding="utf-8")
    # final_path: BuildResult only uses its .stem; fake a path under tmp.
    final_path = tmp_path / f"{gen_id}.json"
    final_path.write_text("{}", encoding="utf-8")
    return BuildResult(
        slot=slot, prompt="...", final_path=final_path,
        composite=0.5, physical=0.5, alexander=0.5,
        report_path=None, error=None,
    )


# ────────────────────────────────────────────────────────────────────────
#  signature extraction
# ────────────────────────────────────────────────────────────────────────

def test_signature_returns_tuple_in_canonical_order(tmp_path):
    workdir = tmp_path / "build1"
    workdir.mkdir()
    (workdir / "global_intent.json").write_text(json.dumps({
        "selected_typologies": {
            "tower": "norman_keep",
            "roof":  "gable_roof",
            "window": "oriel_window",
            "garden": "cottage_garden",
        }
    }), encoding="utf-8")
    sig = _typology_signature(workdir)
    assert sig == ("norman_keep", "gable_roof", "oriel_window", "cottage_garden")


def test_signature_handles_partial_choices(tmp_path):
    workdir = tmp_path / "build1"
    workdir.mkdir()
    (workdir / "global_intent.json").write_text(json.dumps({
        "selected_typologies": {"roof": "mansard_roof"}
    }), encoding="utf-8")
    sig = _typology_signature(workdir)
    assert sig == (None, "mansard_roof", None, None)


def test_signature_missing_file_returns_None(tmp_path):
    assert _typology_signature(tmp_path / "does_not_exist") is None


# ────────────────────────────────────────────────────────────────────────
#  diversity metric
# ────────────────────────────────────────────────────────────────────────

def test_diversity_all_same_signature(tmp_path):
    """5 identical choices → diversity_index = 1/5 = 0.2."""
    builds = []
    for i in range(5):
        gi = {"selected_typologies": {"roof": "gable_roof"}}
        builds.append(_mk_build(tmp_path, f"slot{i}", gi))
    out = _typology_diversity_score(builds, tmp_path)
    assert out["n_with_choice"] == 5
    assert out["unique_signatures"] == 1
    assert out["diversity_index"] == 0.2


def test_diversity_all_different_signatures(tmp_path):
    """5 distinct choices → diversity_index = 1.0."""
    roofs = ["gable_roof", "hip_roof", "mansard_roof", "gambrel_roof", "cross_gable_roof"]
    builds = []
    for i, r in enumerate(roofs):
        builds.append(_mk_build(tmp_path, f"slot{i}",
                                {"selected_typologies": {"roof": r}}))
    out = _typology_diversity_score(builds, tmp_path)
    assert out["unique_signatures"] == 5
    assert out["diversity_index"] == 1.0
    assert out["by_kind_unique"]["roof"] == 5


def test_diversity_mixed_signatures(tmp_path):
    """Mixed across 2 kinds: 4 builds, 3 distinct signatures."""
    fixtures = [
        {"tower": "norman_keep", "roof": "gable_roof"},
        {"tower": "norman_keep", "roof": "hip_roof"},
        {"tower": "wizard_tower", "roof": "gable_roof"},
        {"tower": "wizard_tower", "roof": "gable_roof"},   # duplicate of #3
    ]
    builds = []
    for i, sel in enumerate(fixtures):
        builds.append(_mk_build(tmp_path, f"slot{i}",
                                {"selected_typologies": sel}))
    out = _typology_diversity_score(builds, tmp_path)
    assert out["unique_signatures"] == 3
    assert out["diversity_index"] == 0.75
    assert out["by_kind_unique"] == {
        "tower": 2, "roof": 2, "window": 0, "garden": 0,
    }


def test_diversity_no_chooser_fired(tmp_path):
    """Builds without selected_typologies → n_with_choice=0,
    diversity_index=0 (metric undefined but never crashes)."""
    builds = []
    for i in range(3):
        builds.append(_mk_build(tmp_path, f"slot{i}", {}))
    out = _typology_diversity_score(builds, tmp_path)
    assert out["n_with_choice"] == 0
    assert out["diversity_index"] == 0.0
    # All-None signatures count as one "no-choice" bucket.
    assert out["unique_signatures"] == 1


def test_diversity_skips_errored_builds(tmp_path):
    """Builds with .error set are excluded from the metric."""
    gi = {"selected_typologies": {"roof": "gable_roof"}}
    ok = _mk_build(tmp_path, "ok", gi)
    bad = _mk_build(tmp_path, "bad", gi)
    bad.error = "simulated failure"
    out = _typology_diversity_score([ok, bad], tmp_path)
    assert out["n_builds"] == 1
