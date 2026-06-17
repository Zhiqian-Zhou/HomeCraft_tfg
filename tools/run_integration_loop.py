"""End-to-end integration loop for the pipeline.

Runs a battery of 5 prompts through `pipeline.agents.run.run()` and validates
the outputs. Designed to be invoked iteratively during pipeline development
— each iteration reports failures so you can fix the code and re-run.

    python3 tools/run_integration_loop.py
    python3 tools/run_integration_loop.py --max-iters 10
    python3 tools/run_integration_loop.py --iter 3 --prompt 1   # single prompt

Pre-requisite:
    export OPENROUTER_API_KEY=sk-or-v1-...

Stop criterion: 5/5 prompts pass schema + invariant checks, OR max-iters reached.
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.agents.run import run as pipeline_run
from jsonschema import Draft202012Validator

PROMPTS = [
    "a small medieval cottage with one bedroom and a kitchen",
    "a tall fantasy wizard tower with a study and a roof terrace",
    "a modern minimalist single-floor home with a living room kitchen and bathroom",
    "a Japanese-style house with a tatami room and a garden",
    "a Mediterranean villa with a courtyard and a chapel",
]

REPORT_DIR = REPO_ROOT / "scratch" / "integration_reports"


def _ref_building_schema() -> dict:
    return json.loads((REPO_ROOT / "rag" / "schema" / "reference_building.schema.json").read_text())


def _invariant_checks(doc: dict, *, master_plan: dict | None = None) -> list[str]:
    """Return a list of human-readable violations. Empty = clean."""
    violations = []
    palette = doc.get("block_palette", {})
    voxels = doc.get("voxels", [])
    bbox = doc.get("bounding_box", {}).get("size", [0, 0, 0])

    if not voxels:
        violations.append("voxels list is empty")
    if not palette:
        violations.append("palette is empty")
    for k, v in palette.items():
        bare = v.split("[")[0] if "[" in v else v
        if bare in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air"):
            violations.append(f"palette contains air variant {v!r} at idx {k}")
    # AABB respect: every voxel within bbox
    for vx in voxels[:1000]:  # spot check
        if len(vx) != 4:
            violations.append("voxel entry not [x,y,z,p]")
            continue
        x, y, z, p = vx
        if not (0 <= x < bbox[0] and 0 <= y < bbox[1] and 0 <= z < bbox[2]):
            violations.append(f"voxel ({x},{y},{z}) outside bbox {bbox}")
            break
        if str(p) not in palette:
            violations.append(f"voxel palette idx {p} not in palette")
            break
    # BOT decomposition coherence
    bot = doc.get("bot_decomposition")
    if bot is not None:
        storeys = bot.get("building", {}).get("storeys", [])
        if not storeys:
            violations.append("bot_decomposition has no storeys")
    return violations


def _run_one(prompt: str, *, gen_id: str) -> dict:
    """Run a single prompt and return a result record."""
    rec = {
        "prompt":  prompt,
        "gen_id":  gen_id,
        "passed":  False,
        "stage":   None,
        "error":   None,
        "voxel_count": 0,
        "palette_size": 0,
        "bbox": None,
        "warnings": [],
        "violations": [],
    }
    try:
        rec["stage"] = "pipeline"
        path = pipeline_run(prompt, gen_id=gen_id, verbose=True)
        doc = json.loads(path.read_text())
        rec["voxel_count"] = len(doc.get("voxels", []))
        rec["palette_size"] = len(doc.get("block_palette", {}))
        rec["bbox"] = doc.get("bounding_box", {}).get("size")

        rec["stage"] = "schema"
        Draft202012Validator(_ref_building_schema()).validate(doc)

        rec["stage"] = "invariants"
        violations = _invariant_checks(doc)
        rec["violations"] = violations
        # Pick up warnings produced by aggregator
        mp_path = path.parent / gen_id / "master_plan.json"
        if mp_path.exists():
            master = json.loads(mp_path.read_text())
            rec["warnings"] = master.get("warnings", [])
        rec["passed"] = len(violations) == 0
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        rec["traceback"] = traceback.format_exc(limit=8)
    return rec


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iter", type=int, default=1, help="iteration number (for output naming)")
    ap.add_argument("--max-iters", type=int, default=10)
    ap.add_argument("--prompts", type=int, nargs="*", default=None,
                     help="subset of prompts by index (0-based); default=all 5")
    args = ap.parse_args(argv)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    sel = args.prompts if args.prompts else list(range(len(PROMPTS)))
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    print(f"\n=== Integration iter {args.iter}/{args.max_iters} @ {ts} ===\n")
    print(f"running {len(sel)} prompts")

    results = []
    for ix in sel:
        prompt = PROMPTS[ix]
        gen_id = f"iter{args.iter:02d}-prompt{ix}-{ts}"
        print(f"\n--- prompt[{ix}]: {prompt}")
        rec = _run_one(prompt, gen_id=gen_id)
        results.append(rec)

    # Summary
    n_pass = sum(1 for r in results if r["passed"])
    print(f"\n=== iter {args.iter} summary: {n_pass}/{len(results)} pass ===")
    for r in results:
        if r["passed"]:
            v = r["voxel_count"]; p = r["palette_size"]; b = r["bbox"]
            print(f"  ✓ {r['gen_id']:50s} voxels={v:>6d} palette={p:>3d} bbox={b}")
        else:
            print(f"  ✗ {r['gen_id']:50s} stage={r['stage']}")
            if r["error"]:
                print(f"      error: {r['error'][:200]}")
            for v in r.get("violations", [])[:5]:
                print(f"      violation: {v}")

    report_path = REPORT_DIR / f"iter_{args.iter:02d}_{ts}.json"
    report_path.write_text(json.dumps({
        "iter":    args.iter,
        "timestamp": ts,
        "results": results,
        "all_pass": n_pass == len(results),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport written → {report_path.relative_to(REPO_ROOT)}")

    if n_pass == len(results):
        print(f"\n🎉  ALL {n_pass}/{len(results)} PROMPTS PASS")
        return 0
    print(f"\n⚠   {len(results) - n_pass} prompt(s) failed; fix and re-run with --iter {args.iter + 1}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
