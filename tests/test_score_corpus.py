"""Tests for tools/score_corpus.py — batch evaluator over the corpus.

Builds a tiny synthetic corpus in a tmp_path, invokes the tool, verifies
that one sidecar per building is written with the expected shape, and
checks idempotence (running twice does not re-evaluate).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "score_corpus.py"

from tests.conftest import build_doc, hollow_box  # noqa: E402


def _make_corpus(tmp_path: Path, n: int = 3) -> Path:
    """Build n synthetic buildings under tmp_path/processed/."""
    processed = tmp_path / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        voxels = hollow_box(0, 0, 0, 4 + i, 3, 4 + i,
                              wall="minecraft:oak_planks")
        doc = build_doc(voxels, building_id=f"synthetic-{i}",
                        style="medieval", category="residential")
        # The score_corpus tool reads files by glob; the building id inside
        # the doc must match the filename stem.
        (processed / f"{doc['id']}.json").write_text(
            json.dumps(doc), encoding="utf-8")
    return processed


def _run_tool(processed: Path, out: Path, *extra: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(TOOL),
           "--processed-dir", str(processed),
           "--out-dir", str(out), *extra]
    return subprocess.run(cmd, capture_output=True, text=True,
                           cwd=REPO_ROOT, timeout=60)


def test_score_corpus_writes_one_sidecar_per_building(tmp_path):
    """Running the tool produces exactly N sidecars with composite + 18 metrics."""
    processed = _make_corpus(tmp_path, n=3)
    out_dir = tmp_path / "evaluations"
    res = _run_tool(processed, out_dir)
    assert res.returncode == 0, f"stderr: {res.stderr}\nstdout: {res.stdout}"

    sidecars = sorted(p for p in out_dir.glob("*.json")
                       if p.name != "_manifest.json")
    assert len(sidecars) == 3
    for s in sidecars:
        rep = json.loads(s.read_text(encoding="utf-8"))
        assert "composite" in rep
        assert "physical" in rep
        assert "alexander" in rep
        assert len(rep["physical"]) == 8
        assert len(rep["alexander"]) == 10
        # Synthetic buildings may have null composite (limited metric signal),
        # but the composite block itself must exist.
        assert "overall" in rep["composite"]


def test_score_corpus_writes_manifest(tmp_path):
    """A _manifest.json summary is written next to the sidecars."""
    processed = _make_corpus(tmp_path, n=2)
    out_dir = tmp_path / "evaluations"
    res = _run_tool(processed, out_dir)
    assert res.returncode == 0
    manifest = json.loads((out_dir / "_manifest.json").read_text())
    assert manifest["n_total"] == 2
    assert manifest["n_scored"] == 2
    assert manifest["n_errors"] == 0


def test_score_corpus_is_idempotent(tmp_path):
    """A second run with the same sources does no work (mtime check)."""
    processed = _make_corpus(tmp_path, n=2)
    out_dir = tmp_path / "evaluations"
    _run_tool(processed, out_dir)
    # Snapshot sidecar mtimes
    mtimes_before = {p.name: p.stat().st_mtime
                      for p in out_dir.glob("synthetic-*.json")}
    # Wait so a re-write would have a different mtime
    time.sleep(0.05)
    res2 = _run_tool(processed, out_dir)
    assert res2.returncode == 0
    assert "to_score=0" in res2.stdout
    mtimes_after = {p.name: p.stat().st_mtime
                     for p in out_dir.glob("synthetic-*.json")}
    assert mtimes_before == mtimes_after, "sidecars were re-written"


def test_score_corpus_force_re_evaluates(tmp_path):
    """--force re-runs even when sidecars are up-to-date."""
    processed = _make_corpus(tmp_path, n=2)
    out_dir = tmp_path / "evaluations"
    _run_tool(processed, out_dir)
    time.sleep(0.05)
    res = _run_tool(processed, out_dir, "--force")
    assert res.returncode == 0
    assert "to_score=2" in res.stdout


def test_score_corpus_limit(tmp_path):
    """--limit caps the work and writes only that many sidecars."""
    processed = _make_corpus(tmp_path, n=5)
    out_dir = tmp_path / "evaluations"
    res = _run_tool(processed, out_dir, "--limit", "2")
    assert res.returncode == 0
    sidecars = [p for p in out_dir.glob("synthetic-*.json")]
    assert len(sidecars) == 2


def test_score_corpus_recovers_from_unreadable_doc(tmp_path):
    """A malformed JSON in the corpus does not stop the rest."""
    processed = _make_corpus(tmp_path, n=2)
    (processed / "broken.json").write_text("not json {{{",
                                              encoding="utf-8")
    out_dir = tmp_path / "evaluations"
    res = _run_tool(processed, out_dir)
    # exit code 1 because there was an error, but the good sidecars exist
    assert res.returncode == 1
    good = [p for p in out_dir.glob("synthetic-*.json")]
    assert len(good) == 2
