"""Unit tests for stratified retrieval cutoff (Fase 5).

Verifies that `_stratified_cutoffs` preserves diversity by keeping top-X%
PER bucket instead of globally — so a style with fewer-but-strong examples
doesn't get crowded out by a dominant style.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from build_retrieval_index import _bucket_key, _stratified_cutoffs  # noqa: E402


def _rec(bid: str, style: str, category: str, composite: float) -> dict:
    return {
        "bid": bid,
        "doc": {"tags": {"style": [style], "category": category}},
        "text": f"{bid}",
        "composite": composite,
    }


def test_bucket_key_style():
    doc = {"tags": {"style": ["medieval"], "category": "castle"}}
    assert _bucket_key(doc, "style") == ("medieval",)
    assert _bucket_key(doc, "style_category") == ("medieval", "castle")
    assert _bucket_key(doc, "none") == ("__all__",)


def test_bucket_key_missing_fields():
    doc = {"tags": {}}
    assert _bucket_key(doc, "style") == ("unknown",)
    assert _bucket_key(doc, "style_category") == ("unknown", "unknown")


def test_stratified_preserves_minority_style():
    """Without stratification, a 9-medieval + 1-minimalist corpus filtered
    at top-30% would keep the 3 best medievals and drop the minimalist
    even though it's the best of its bucket. With stratification, both
    buckets contribute at least one kept entry."""
    records = [_rec(f"med{i}", "medieval", "cottage", 0.5 + i * 0.05) for i in range(9)]
    records.append(_rec("min1", "minimalist", "house", 0.3))

    kept_global = [r for r in records
                   if r["composite"] >= sorted(rr["composite"] for rr in records)[-3]]
    # Just the top 3 by composite globally — all medieval.
    assert all(r["bid"].startswith("med") for r in kept_global)

    kept_strat, stats = _stratified_cutoffs(records, top_percent=30.0,
                                              scheme="style")
    styles = {r["bid"].rstrip("0123456789")[:3] for r in kept_strat}
    # Both 'med' and 'min' buckets must contribute.
    assert "med" in styles
    assert "min" in styles


def test_stratified_guarantees_at_least_one_per_bucket():
    """Tiny buckets get >= 1 kept entry even if percentile math says zero."""
    records = [
        _rec("only_modern", "modern", "house", 0.4),
        _rec("a", "medieval", "house", 0.8),
        _rec("b", "medieval", "house", 0.9),
    ]
    kept, stats = _stratified_cutoffs(records, top_percent=30.0,
                                        scheme="style")
    bids = {r["bid"] for r in kept}
    assert "only_modern" in bids


def test_stratified_respects_top_percent_in_large_bucket():
    """A bucket with 100 entries should retain ~30 at top-30%."""
    records = [_rec(f"med{i:03d}", "medieval", "house", i / 100.0)
               for i in range(100)]
    kept, stats = _stratified_cutoffs(records, top_percent=30.0,
                                        scheme="style")
    # numpy.percentile interpolation may put the cut at exactly 70th value;
    # accept a small slack.
    assert 28 <= len(kept) <= 32


def test_stratified_style_category_creates_more_buckets():
    """style_category should create distinct buckets per (style, category)."""
    records = [
        _rec("a", "medieval", "castle", 0.8),
        _rec("b", "medieval", "castle", 0.9),
        _rec("c", "medieval", "cottage", 0.7),
        _rec("d", "modern", "tower", 0.85),
    ]
    _, stats_style = _stratified_cutoffs(records, top_percent=30.0,
                                           scheme="style")
    _, stats_sc = _stratified_cutoffs(records, top_percent=30.0,
                                         scheme="style_category")
    # 2 style buckets, 3 style+category buckets.
    assert len(stats_style) == 2
    assert len(stats_sc) == 3
