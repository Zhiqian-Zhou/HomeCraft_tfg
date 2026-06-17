"""Standalone CLI to evaluate a ReferenceBuilding JSON.

Useful for re-scoring already-generated buildings without re-running the pipeline,
or for evaluating corpus buildings from rag/reference_buildings/processed/.

    python3 tools/evaluate_building.py scratch/generations/iter05-prompt0-20260525-213448.json
    python3 tools/evaluate_building.py --no-critique <file.json>
    python3 tools/evaluate_building.py --batch 'scratch/generations/iter05-*.json'
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.agents.evaluator import evaluate


def _try_load_sidecar(building_path: Path) -> tuple[dict | None, dict | None]:
    """Best-effort load of design_intent.json + master_plan.json from a
    sibling gen workdir (scratch/generations/<gen_id>/...).
    Returns (design_intent, master_plan) or (None, None) if not found.
    """
    workdir = building_path.parent / building_path.stem
    di = workdir / "design_intent.json"
    mp = workdir / "master_plan.json"
    return (json.loads(di.read_text()) if di.exists() else None,
            json.loads(mp.read_text()) if mp.exists() else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", help="ReferenceBuilding JSON paths or globs")
    ap.add_argument("--no-critique", action="store_true",
                     help="skip the LLM critique (saves API calls)")
    ap.add_argument("--out", action="store_true",
                     help="write report alongside source as <stem>.evaluation.json")
    ap.add_argument("--summary", action="store_true", help="only print summary table")
    args = ap.parse_args()

    # Expand globs, then filter out .evaluation.json sidecars (they look
    # like building JSONs but are evaluation reports — no bounding_box).
    files = []
    for p in args.paths:
        if any(c in p for c in "*?["):
            files.extend(sorted(glob.glob(p)))
        else:
            files.append(p)
    files = [f for f in files if not f.endswith(".evaluation.json")]
    if not files:
        print("[evaluate] no files found", file=sys.stderr)
        return 1

    rows = []
    for f in files:
        path = Path(f)
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[evaluate] {f}: bad JSON ({e})", file=sys.stderr)
            continue
        di, mp = _try_load_sidecar(path)
        report = evaluate(doc, design_intent=di, master_plan=mp,
                          run_critique=not args.no_critique)
        if args.out:
            out_path = path.parent / f"{path.stem}.evaluation.json"
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
        c = report["composite"]
        rows.append({
            "file": path.name,
            "physical":  c.get("physical_total"),
            "alexander": c.get("alexander_total"),
            "overall":   c.get("overall"),
            "report":    report,
        })

    # Output
    if args.summary or len(rows) > 1:
        print(f"\n=== Evaluation summary ({len(rows)} buildings) ===\n")
        print(f"  {'file':60s} {'physical':>10s} {'alexander':>10s} {'overall':>10s}")
        for r in rows:
            p = f"{r['physical']:.3f}" if r['physical'] is not None else "  null"
            a = f"{r['alexander']:.3f}" if r['alexander'] is not None else "  null"
            o = f"{r['overall']:.3f}"  if r['overall']  is not None else "  null"
            print(f"  {r['file']:60s} {p:>10s} {a:>10s} {o:>10s}")
    else:
        # Single file: print full report
        print(json.dumps(rows[0]["report"], indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
