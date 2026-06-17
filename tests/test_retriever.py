"""Tests for the quality-filtered retriever + build_retrieval_index.

The pipeline:
    score_corpus → composite per building (this test fakes the sidecars)
    build_retrieval_index → top-30% subset + TF-IDF over it
    retrieve → pure TF-IDF cosine over the filtered subset

We build a mini corpus of 10 synthetic buildings with manually-assigned
composite scores, run the indexer, monkey-patch the retriever's INDEX_DIR
to point at the tmp index, and verify behaviour end-to-end.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_TOOL = REPO_ROOT / "tools" / "build_retrieval_index.py"

from tests.conftest import build_doc, hollow_box  # noqa: E402


def _make_corpus(processed: Path, evaluations: Path, specs: list[dict]) -> None:
    """Create one (building_doc, evaluation_sidecar) pair per spec.

    Each spec: {id, title, description, style, category, composite}.
    composite=None means "missing or null sidecar".
    """
    processed.mkdir(parents=True, exist_ok=True)
    evaluations.mkdir(parents=True, exist_ok=True)
    for s in specs:
        voxels = hollow_box(0, 0, 0, 4, 3, 4, wall="minecraft:oak_planks")
        doc = build_doc(voxels, building_id=s["id"], style=s["style"],
                        category=s["category"])
        doc["title"] = s["title"]
        doc["description"] = s["description"]
        doc["tags"]["size_bucket"] = s.get("size_bucket", "small")
        (processed / f"{s['id']}.json").write_text(json.dumps(doc),
                                                      encoding="utf-8")
        if s["composite"] is None:
            # Skip writing a sidecar — indexer treats that as missing.
            continue
        # Minimal evaluation_report sidecar — only composite.overall is read
        # by the indexer.
        sidecar = {
            "building_id": s["id"],
            "schema_version": "1.0",
            "physical": {},
            "alexander": {},
            "composite": {"overall": s["composite"]},
            "critique": None,
            "generated_at": "2026-05-26T00:00:00Z",
        }
        (evaluations / f"{s['id']}.json").write_text(
            json.dumps(sidecar), encoding="utf-8")


def _run_indexer(processed: Path, evaluations: Path, out_dir: Path,
                  *extra: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(INDEX_TOOL),
           "--processed-dir", str(processed),
           "--evaluations-dir", str(evaluations),
           "--out-dir", str(out_dir), *extra]
    return subprocess.run(cmd, capture_output=True, text=True,
                           cwd=REPO_ROOT, timeout=60)


@pytest.fixture
def mini_corpus(tmp_path):
    """Build a 10-building corpus with controlled composites.

    Returns (processed, evaluations, sorted_composites_in).
    """
    specs = [
        # Eight medieval cottages with varied composite scores
        {"id": "b00-cottage", "title": "tiny medieval cottage hut",
         "description": "small wooden cottage with thatched roof",
         "style": "medieval", "category": "residential", "composite": 0.20},
        {"id": "b01-cottage", "title": "modest medieval cottage",
         "description": "stone-and-wood cottage",
         "style": "medieval", "category": "residential", "composite": 0.40},
        {"id": "b02-cottage", "title": "rustic medieval cottage",
         "description": "cottage with garden and chimney",
         "style": "rustic", "category": "residential", "composite": 0.55},
        {"id": "b03-cottage", "title": "fine medieval cottage",
         "description": "cottage with kitchen and bedroom",
         "style": "medieval", "category": "residential", "composite": 0.70},
        {"id": "b04-cottage", "title": "excellent medieval cottage",
         "description": "cottage with proper roof and entry",
         "style": "medieval", "category": "residential", "composite": 0.80},
        {"id": "b05-cottage", "title": "premium medieval cottage",
         "description": "cottage best example tutorial",
         "style": "medieval", "category": "residential", "composite": 0.90},
        # Two towers (different theme) so semantic match drops them
        {"id": "b06-tower", "title": "tall stone tower",
         "description": "tower with battlements",
         "style": "medieval", "category": "tower", "composite": 0.85,
         "size_bucket": "large"},
        {"id": "b07-tower", "title": "watchtower",
         "description": "tower with arrowslits and crenellations",
         "style": "medieval", "category": "tower", "composite": 0.75,
         "size_bucket": "large"},
        # One null-composite — must be discarded entirely
        {"id": "b08-null", "title": "medieval cottage scratched",
         "description": "cottage cottage cottage",
         "style": "medieval", "category": "residential", "composite": None},
        # One very low composite — must drop out at 30% cutoff
        {"id": "b09-bad", "title": "garbage medieval cottage",
         "description": "tiny cottage barely a hut",
         "style": "medieval", "category": "residential", "composite": 0.10},
    ]
    processed = tmp_path / "processed"
    evaluations = tmp_path / "evaluations"
    _make_corpus(processed, evaluations, specs)
    return processed, evaluations, specs


def _build_and_load(mini_corpus, tmp_path, *extra) -> dict:
    """Run the indexer + reload the retriever pointed at tmp index."""
    processed, evaluations, _ = mini_corpus
    index_dir = tmp_path / "index"
    res = _run_indexer(processed, evaluations, index_dir, *extra)
    assert res.returncode == 0, (
        f"build_retrieval_index failed\nstdout={res.stdout}\nstderr={res.stderr}")
    info = json.loads((index_dir / "index_info.json").read_text())
    return {"index_dir": index_dir, "info": info, "stdout": res.stdout}


def test_indexer_filters_to_top_30_percent_and_discards_null(mini_corpus, tmp_path):
    """top-30% of the 9 non-null scores → keeps ~3 buildings. null discarded.

    Pinned to --stratify none because this test asserts a single global
    cutoff value; under Fase 5 stratified default each bucket has its own.
    """
    out = _build_and_load(mini_corpus, tmp_path,
                            "--stratify", "none", "--top-percent", "30")
    info = out["info"]
    assert info["n_evaluated"] == 9, "10 corpus minus 1 null sidecar"
    assert info["n_discarded_null"] == 0, "no sidecars had composite=null"
    assert info["n_missing_sidecar"] == 1, "b08-null had no sidecar"
    # ~30% of 9 = 3 kept. p70 of [0.10,0.20,...,0.90] is around 0.78
    assert info["n_filtered_in"] in (2, 3, 4), info
    # Cutoff should land near the 70th-percentile of the spec composites.
    assert 0.7 <= info["cutoff_composite_value"] <= 0.9


def test_indexer_top_percent_50_keeps_more(mini_corpus, tmp_path):
    """A looser cutoff keeps more buildings."""
    out = _build_and_load(mini_corpus, tmp_path, "--top-percent", "50")
    assert out["info"]["n_filtered_in"] >= 4


def test_indexer_min_composite_threshold(mini_corpus, tmp_path):
    """--min-composite is an absolute cutoff, ignores --top-percent."""
    out = _build_and_load(mini_corpus, tmp_path, "--min-composite", "0.5")
    info = out["info"]
    assert info["cutoff_mode"] == "min_composite"
    assert info["cutoff_composite_value"] == 0.5
    # Buildings with composite ≥ 0.5: b02..b07 (six)
    assert info["n_filtered_in"] == 6


def _retrieve_with_index(monkeypatch, index_dir: Path, prompt: str, k: int = 5):
    """Reload the retriever module pointed at our temp index_dir."""
    import pipeline.agents.retriever as ret
    importlib.reload(ret)
    monkeypatch.setattr(ret, "INDEX_DIR", index_dir)
    ret._reset_index_cache()
    return ret.retrieve(prompt, k=k)


def test_retrieve_returns_only_filtered_buildings(mini_corpus, tmp_path, monkeypatch):
    """No hit ever has composite below the cutoff.

    Pinned to --stratify none for the same reason as the test above —
    under stratification (Fase 5 default) low-composite hits from minority
    buckets are preserved by design.
    """
    out = _build_and_load(mini_corpus, tmp_path,
                            "--stratify", "none", "--top-percent", "30")
    hits = _retrieve_with_index(monkeypatch, out["index_dir"],
                                  "medieval cottage", k=10)
    cutoff = out["info"]["cutoff_composite_value"]
    assert hits, "retriever returned no hits"
    for h in hits:
        assert h["composite_score"] >= cutoff, (
            f"hit {h['id']} composite={h['composite_score']} < cutoff {cutoff}")


def test_retrieve_ranks_by_pure_tfidf(mini_corpus, tmp_path, monkeypatch):
    """Two buildings with the same composite — the one whose text matches
    the prompt better must rank first. (Confirms ranking ignores composite.)
    """
    out = _build_and_load(mini_corpus, tmp_path, "--top-percent", "50")
    hits = _retrieve_with_index(monkeypatch, out["index_dir"],
                                  "tower battlements", k=10)
    # b06-tower (description: "tower with battlements") should rank first
    # over the cottages even though some cottages have higher composite.
    top = hits[0]
    assert "tower" in top["id"], (
        f"expected a tower at top, got {top['id']} "
        f"(composite={top['composite_score']})")


def test_retrieve_returns_composite_score_metadata(mini_corpus, tmp_path, monkeypatch):
    """The composite_score field is populated in every hit, never null."""
    out = _build_and_load(mini_corpus, tmp_path, "--top-percent", "50")
    hits = _retrieve_with_index(monkeypatch, out["index_dir"],
                                  "medieval cottage", k=5)
    for h in hits:
        assert "composite_score" in h
        assert isinstance(h["composite_score"], float)
        assert 0.0 <= h["composite_score"] <= 1.0


def test_retrieve_null_composite_building_never_in_results(mini_corpus, tmp_path, monkeypatch):
    """b08-null (missing sidecar) must never appear in retrieve() output."""
    out = _build_and_load(mini_corpus, tmp_path, "--top-percent", "90")
    hits = _retrieve_with_index(monkeypatch, out["index_dir"],
                                  "medieval cottage scratched cottage cottage cottage",
                                  k=10)
    for h in hits:
        assert h["id"] != "b08-null"


def test_indexer_clears_legacy_features_json(mini_corpus, tmp_path):
    """If a stale features.json exists in the out_dir, the indexer removes it."""
    processed, evaluations, _ = mini_corpus
    index_dir = tmp_path / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    legacy = index_dir / "features.json"
    legacy.write_text('[[0,0,0,0,0,0,0]]', encoding="utf-8")
    res = _run_indexer(processed, evaluations, index_dir, "--top-percent", "30")
    assert res.returncode == 0
    assert not legacy.exists(), "legacy features.json was not removed"
