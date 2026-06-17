"""Batch-evaluate every ReferenceBuilding in rag/reference_buildings/processed/.

The Stage-6 evaluator works on raw corpus buildings (without design_intent
or master_plan sidecars): physical metrics produce real scores; Alexander
metrics that need bot_decomposition / master_plan return null and are
treated as skipped by the composite aggregator. The composite that emerges
ranks buildings by what evidence we DO have — a useful prior for retrieval.

Output: one sidecar per building in scratch/corpus_evaluations/<id>.json
matching the evaluation_report.schema.json shape, plus a small
manifest.json with summary statistics.

Usage:
    python3 tools/score_corpus.py                # incremental (skip up-to-date sidecars)
    python3 tools/score_corpus.py --force        # re-evaluate everything
    python3 tools/score_corpus.py --limit 50     # smoke test
    python3 tools/score_corpus.py --workers 4    # parallel (default 1 — evaluator is single-threaded)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.agents.evaluator import evaluate  # noqa: E402

PROCESSED = REPO_ROOT / "rag" / "reference_buildings" / "processed"
OUT_DIR = REPO_ROOT / "scratch" / "corpus_evaluations"


def _needs_eval(processed_path: Path, sidecar_path: Path, force: bool) -> bool:
    if force:
        return True
    if not sidecar_path.exists():
        return True
    return processed_path.stat().st_mtime > sidecar_path.stat().st_mtime


def _score_one(args_tuple: tuple[str, str]) -> tuple[str, float | None, str | None]:
    """Score a single building. Returns (building_id, composite, error_or_none).

    args_tuple is (processed_path, out_dir) — passed as a single arg so
    this works under ProcessPoolExecutor.submit / map equally.
    """
    processed_path_str, out_dir_str = args_tuple
    p = Path(processed_path_str)
    out_dir = Path(out_dir_str)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return (p.stem, None, f"read_failed: {e}")
    try:
        report = evaluate(doc, run_critique=False)
    except Exception as e:  # noqa: BLE001
        return (p.stem, None, f"evaluate_failed: {type(e).__name__}: {e}")

    out_path = out_dir / f"{p.stem}.json"
    try:
        out_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        return (p.stem, None, f"write_failed: {e}")

    composite = (report.get("composite") or {}).get("overall")
    return (p.stem, composite, None)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true",
                     help="Re-evaluate even when sidecar is newer than the source.")
    ap.add_argument("--limit", type=int, default=None,
                     help="Stop after evaluating N buildings (smoke test).")
    ap.add_argument("--workers", type=int, default=1,
                     help="Parallel workers (default 1).")
    ap.add_argument("--processed-dir", type=Path, default=PROCESSED,
                     help="Override the corpus directory (for testing).")
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR,
                     help="Override the sidecar output directory.")
    args = ap.parse_args()

    processed_dir = Path(args.processed_dir).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    all_paths = sorted(processed_dir.glob("*.json"))
    work: list[Path] = []
    skipped = 0
    for p in all_paths:
        sidecar = out_dir / f"{p.stem}.json"
        if _needs_eval(p, sidecar, args.force):
            work.append(p)
        else:
            skipped += 1
        if args.limit and len(work) >= args.limit:
            break

    print(f"[score_corpus] processed_dir={processed_dir}")
    print(f"[score_corpus] out_dir={out_dir}")
    print(f"[score_corpus] total={len(all_paths)} to_score={len(work)} "
          f"skipped(up_to_date)={skipped} workers={args.workers}")

    if not work:
        print("[score_corpus] nothing to do")
        return 0

    t0 = time.time()
    results: list[tuple[str, float | None, str | None]] = []
    if args.workers <= 1:
        for i, p in enumerate(work):
            results.append(_score_one((str(p), str(out_dir))))
            if (i + 1) % 100 == 0 or (i + 1) == len(work):
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                eta = (len(work) - (i + 1)) / rate if rate > 0 else 0
                print(f"  [{i+1}/{len(work)}] {rate:.1f}/s eta={eta:.0f}s")
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(_score_one, (str(p), str(out_dir))): p
                       for p in work}
            done = 0
            for fut in as_completed(futures):
                results.append(fut.result())
                done += 1
                if done % 100 == 0 or done == len(work):
                    elapsed = time.time() - t0
                    rate = done / elapsed if elapsed > 0 else 0
                    eta = (len(work) - done) / rate if rate > 0 else 0
                    print(f"  [{done}/{len(work)}] {rate:.1f}/s eta={eta:.0f}s")

    elapsed = time.time() - t0
    composites = [c for _, c, e in results if e is None and c is not None]
    errors = [(bid, e) for bid, _, e in results if e is not None]
    nulls = sum(1 for _, c, e in results if e is None and c is None)

    print(f"\n[score_corpus] done in {elapsed:.1f}s")
    print(f"  scored:           {len(results) - len(errors)}")
    print(f"  composite=null:   {nulls}")
    print(f"  errors:           {len(errors)}")
    if composites:
        composites.sort()
        n = len(composites)
        print(f"  composite stats:  min={composites[0]:.3f} "
              f"p25={composites[n//4]:.3f} "
              f"median={composites[n//2]:.3f} "
              f"p75={composites[3*n//4]:.3f} "
              f"max={composites[-1]:.3f}")
    for bid, e in errors[:10]:
        print(f"  ERROR  {bid}: {e}")
    if len(errors) > 10:
        print(f"  ... and {len(errors) - 10} more")

    # Write a small manifest for downstream tools.
    manifest = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_total":      len(all_paths),
        "n_scored":     len(results) - len(errors),
        "n_null":       nulls,
        "n_errors":     len(errors),
        "n_skipped":    skipped,
        "out_dir":      str(out_dir.relative_to(REPO_ROOT))
                        if out_dir.is_relative_to(REPO_ROOT) else str(out_dir),
    }
    (out_dir / "_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
