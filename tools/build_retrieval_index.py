"""Precompute the TF-IDF retrieval index over RAG-E, **pre-filtered** by the
Stage-6 evaluator's composite score.

For each ReferenceBuilding in rag/reference_buildings/processed/:
    1. Look up its evaluation sidecar from scratch/corpus_evaluations/<id>.json
       (produced by tools/score_corpus.py).
    2. Read composite.overall as the building's quality score.
    3. Keep only buildings in the top-K percent by composite (default 30%);
       buildings with composite=null are discarded.
    4. Build TF-IDF over the filtered subset using
       `title + description + style + category + size_bucket`.

Stratification (Fase 5)
-----------------------
By default the cutoff is computed PER (style, category) bucket instead of
globally. A style with a few but consistently strong examples (say,
'minimalist' modern flats) is no longer crowded out by a dominant style
('medieval cottages'). Empirically this preserves diversity of the
retrieved exemplars and is the recommended mode.

Disable with `--stratify none` to fall back to the original global cutoff.

Writes to scratch/retrieval/:
    building_ids.json    ordered list of building IDs in the filtered index
    metadata.json        per-id metadata (title, style, category, ...)
    tfidf_matrix.npz     scipy sparse CSR matrix (n_filtered × vocab_size)
    tfidf_vocab.json     {vocab_word: column_index}
    composite_scores.json  array of composite values aligned to building_ids
    index_info.json      stats (cutoff_percentile, cutoff_composite_value,
                         n_evaluated, n_filtered_in, n_discarded_null,
                         buckets[…])

Usage:
    python3 tools/build_retrieval_index.py                       # stratified
    python3 tools/build_retrieval_index.py --stratify none       # global cutoff
    python3 tools/build_retrieval_index.py --top-percent 20
    python3 tools/build_retrieval_index.py --min-composite 0.6   # threshold mode
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import scipy.sparse as sp
from sklearn.feature_extraction.text import TfidfVectorizer

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

PROCESSED = REPO_ROOT / "rag" / "reference_buildings" / "processed"
EVALUATIONS = REPO_ROOT / "scratch" / "corpus_evaluations"
OUT_DIR = REPO_ROOT / "scratch" / "retrieval"


def _doc_text(doc: dict) -> str:
    title = doc.get("title", "")
    desc = doc.get("description", "")
    tags = doc.get("tags", {})
    style = " ".join(tags.get("style", []))
    category = tags.get("category", "")
    size_bucket = tags.get("size_bucket", "")
    return f"{title}  {desc}  {style}  {category}  {size_bucket}".strip()


def _bucket_key(doc: dict, scheme: str) -> tuple[str, ...]:
    """Return the stratification bucket for `doc` under `scheme`.

    * scheme=='style'           → (first_style_or_unknown,)
    * scheme=='style_category'  → (first_style_or_unknown, category_or_unknown)
    * scheme=='none'            → ("__all__",)
    """
    if scheme == "none":
        return ("__all__",)
    tags = doc.get("tags", {})
    styles = tags.get("style") or []
    style = (styles[0] if styles else "unknown")
    if scheme == "style_category":
        category = tags.get("category") or "unknown"
        return (style, category)
    return (style,)


def _stratified_cutoffs(records: list[dict], top_percent: float,
                         scheme: str
                         ) -> tuple[list[dict], dict[tuple[str, ...], dict]]:
    """Apply a per-bucket top-X% cutoff. Returns (kept_records, per_bucket_stats).

    Each bucket gets at least 1 building (the highest-scoring) even if its
    size is too small for the percentile threshold to land sensibly. This
    prevents tiny buckets from being filtered out entirely.
    """
    from collections import defaultdict
    buckets: dict[tuple[str, ...], list[dict]] = defaultdict(list)
    for r in records:
        buckets[_bucket_key(r["doc"], scheme)].append(r)

    kept: list[dict] = []
    stats: dict[tuple[str, ...], dict] = {}
    for key, recs in buckets.items():
        composites = np.array([r["composite"] for r in recs], dtype=float)
        cutoff = float(np.percentile(composites, 100.0 - top_percent))
        bucket_kept = [r for r in recs if r["composite"] >= cutoff]
        # Guarantee at least one kept per bucket (handles single-record buckets).
        if not bucket_kept:
            bucket_kept = [max(recs, key=lambda r: r["composite"])]
        kept.extend(bucket_kept)
        stats["::".join(key)] = {
            "n_evaluated": len(recs),
            "n_kept":      len(bucket_kept),
            "cutoff":      cutoff,
        }
    return kept, stats


def _load_composite(evaluations_dir: Path, building_id: str) -> float | None:
    p = evaluations_dir / f"{building_id}.json"
    if not p.exists():
        return None
    try:
        report = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    composite = (report.get("composite") or {}).get("overall")
    if composite is None:
        return None
    try:
        return float(composite)
    except (TypeError, ValueError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-features", type=int, default=8000,
                     help="TF-IDF vocabulary cap (default 8000).")
    ap.add_argument("--top-percent", type=float, default=30.0,
                     help="Keep only the top X%% of corpus by composite "
                          "(default 30). Ignored if --min-composite is set.")
    ap.add_argument("--min-composite", type=float, default=None,
                     help="Absolute composite cutoff (e.g. 0.5). Overrides "
                          "--top-percent when set.")
    ap.add_argument("--stratify", choices=["style", "style_category", "none"],
                     default="style",
                     help="Bucketing scheme for the top-X%% filter (Fase 5). "
                          "Default 'style' preserves diversity by computing "
                          "the cutoff per style bucket. Use 'none' for the "
                          "legacy global cutoff.")
    ap.add_argument("--processed-dir", type=Path, default=PROCESSED)
    ap.add_argument("--evaluations-dir", type=Path, default=EVALUATIONS)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    processed_dir = Path(args.processed_dir).resolve()
    evaluations_dir = Path(args.evaluations_dir).resolve()
    out_dir = Path(args.out_dir).resolve()

    files = sorted(processed_dir.glob("*.json"))
    if not files:
        print(f"[index] no JSONs in {processed_dir}", file=sys.stderr)
        return 1
    if not evaluations_dir.exists():
        print(f"[index] no evaluations directory at {evaluations_dir} — "
              "run `python3 tools/score_corpus.py` first.", file=sys.stderr)
        return 1

    print(f"[index] scanning {len(files)} buildings...")

    # Pass 1: read every doc, collect composite from sidecar.
    records: list[dict] = []  # {bid, doc, text, composite}
    n_skipped_json = 0
    n_missing_sidecar = 0
    n_null_composite = 0
    for f in files:
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            n_skipped_json += 1
            continue
        bid = doc.get("id")
        if not bid:
            n_skipped_json += 1
            continue
        composite = _load_composite(evaluations_dir, bid)
        if composite is None:
            sidecar = evaluations_dir / f"{bid}.json"
            if not sidecar.exists():
                n_missing_sidecar += 1
            else:
                n_null_composite += 1
            continue
        records.append({
            "bid": bid,
            "doc": doc,
            "text": _doc_text(doc),
            "composite": composite,
        })

    if not records:
        print("[index] no buildings with a usable composite score", file=sys.stderr)
        return 1

    # Decide cutoff — global or stratified.
    bucket_stats: dict[tuple[str, ...], dict] = {}
    if args.min_composite is not None:
        cutoff = float(args.min_composite)
        cutoff_basis = f"min-composite={cutoff}"
        kept = [r for r in records if r["composite"] >= cutoff]
    elif args.stratify == "none":
        composites = np.array([r["composite"] for r in records], dtype=float)
        cutoff = float(np.percentile(composites, 100.0 - args.top_percent))
        cutoff_basis = (f"top-{args.top_percent:.0f}% global "
                        f"→ composite ≥ {cutoff:.3f}")
        kept = [r for r in records if r["composite"] >= cutoff]
    else:
        kept, bucket_stats = _stratified_cutoffs(
            records, top_percent=args.top_percent, scheme=args.stratify)
        cutoff = float("nan")  # not a single number under stratification
        cutoff_basis = (f"top-{args.top_percent:.0f}% per-bucket "
                        f"(scheme={args.stratify}, {len(bucket_stats)} buckets)")

    # Stable order: lexicographic by id (matches the scan above).
    kept.sort(key=lambda r: r["bid"])

    print(f"[index] evaluated={len(records)}  "
          f"discarded_null={n_null_composite}  "
          f"missing_sidecar={n_missing_sidecar}  "
          f"skipped_json={n_skipped_json}")
    print(f"[index] cutoff: {cutoff_basis}")
    print(f"[index] kept: {len(kept)} (= {100.0 * len(kept) / max(1, len(records)):.1f}% of evaluated)")

    if not kept:
        print("[index] cutoff produced an empty index", file=sys.stderr)
        return 1

    # Pass 2: TF-IDF on the filtered subset.
    print(f"[index] fitting TF-IDF (max_features={args.max_features})...")
    texts = [r["text"] for r in kept]
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=(1, 2),
        max_features=args.max_features,
        min_df=2,
    )
    matrix = vectorizer.fit_transform(texts)
    vocab = {w: int(i) for w, i in vectorizer.vocabulary_.items()}

    # Metadata for the kept subset.
    building_ids: list[str] = []
    metadata: dict[str, dict] = {}
    composite_scores: list[float] = []
    for r in kept:
        doc = r["doc"]
        bid = r["bid"]
        tags = doc.get("tags", {})
        building_ids.append(bid)
        composite_scores.append(r["composite"])
        metadata[bid] = {
            "title": doc.get("title", ""),
            "description_short": (doc.get("description") or "")[:300],
            "style": tags.get("style", []),
            "category": tags.get("category", ""),
            "size_bucket": tags.get("size_bucket", ""),
            "voxels_count": len(doc.get("voxels", [])),
            "bbox_size": doc.get("bounding_box", {}).get("size", [0, 0, 0]),
            "interior_populated": (doc.get("metadata_quality") or {}).get(
                "interior_populated", False),
            "composite_score": r["composite"],
        }

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        display_dir = str(out_dir.relative_to(REPO_ROOT)) + "/"
    except ValueError:
        display_dir = str(out_dir) + "/"
    print(f"[index] writing outputs to {display_dir}")
    sp.save_npz(out_dir / "tfidf_matrix.npz", matrix.tocsr())
    (out_dir / "building_ids.json").write_text(
        json.dumps(building_ids), encoding="utf-8")
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    (out_dir / "tfidf_vocab.json").write_text(
        json.dumps(vocab), encoding="utf-8")
    (out_dir / "composite_scores.json").write_text(
        json.dumps(composite_scores), encoding="utf-8")

    # Remove legacy features.json if it exists (alexander_scorer.py output).
    legacy = out_dir / "features.json"
    if legacy.exists():
        legacy.unlink()

    info = {
        "built_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds").replace("+00:00", "Z"),
        "n_corpus_total": len(files),
        "n_evaluated": len(records),
        "n_filtered_in": len(kept),
        "n_discarded_null": n_null_composite,
        "n_missing_sidecar": n_missing_sidecar,
        "n_skipped_json": n_skipped_json,
        "cutoff_mode":
            "min_composite" if args.min_composite is not None else "top_percent",
        "cutoff_top_percent": (None if args.min_composite is not None
                                else float(args.top_percent)),
        "cutoff_composite_value": float(cutoff),
        "stratify_scheme": args.stratify,
        "buckets": (bucket_stats if bucket_stats else None),
        "vocab_size": len(vocab),
        "matrix_shape": list(matrix.shape),
        "matrix_nnz": int(matrix.nnz),
    }
    (out_dir / "index_info.json").write_text(
        json.dumps(info, indent=2), encoding="utf-8")

    print(f"[index] OK — {len(building_ids)} buildings, vocab={len(vocab)}, "
          f"matrix={matrix.shape}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
