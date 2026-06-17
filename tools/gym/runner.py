"""Gym Runner — one iteration of the skill-improvement loop.

CLI:
    python3 -m tools.gym.runner --iter 1          # run iter 1
    python3 -m tools.gym.runner --iter 2          # run iter 2 (after Claude edits)
    python3 -m tools.gym.runner --auto            # next-iter auto-detect

Per iter:
  1. Build 10 prompts in parallel (ThreadPoolExecutor, max_workers=10)
  2. Evaluator already ran inside _run_v4; sidecar evaluation.json exists
  3. Copy each build's voxel JSON + evaluation to output/gym/iterNN/ with
     score-prefixed filenames (0.612_fantasy-tower.json + sibling)
  4. Generate REPORT.md aggregating scores + diagnose + checklist
  5. Append iter row to SUMMARY.md
  6. Exit. (Claude reads REPORT.md and edits skills before next iter.)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from pipeline.agents.run import run as run_pipeline
from .prompts import GYM_PROMPTS, GymPrompt
from .report import BuildResult, render_report, render_summary

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_BASE = REPO_ROOT / "output" / "gym"


def _safe_slug(text: str, maxlen: int = 30) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen] or "x"


# ──────────────────────────────────────────────────────────────────────────
#  Variety penalty
# ──────────────────────────────────────────────────────────────────────────

def _fingerprint(workdir):
    """Extract a coarse 'look' fingerprint from a build's global_intent.json.

    The tuple captures the BIG decisions (silhouette, style, roof, floor count
    and rough footprint bucket). Two builds with the same fingerprint look
    similar regardless of room labels."""
    try:
        gi = json.loads((workdir / "global_intent.json").read_text(encoding="utf-8"))
    except Exception:    # noqa: BLE001
        return None
    bld = gi.get("building_aabb") or [0, 0, 0, 0, 0, 0]
    w_bucket = max(1, (bld[3] - bld[0]) // 4) * 4
    d_bucket = max(1, (bld[5] - bld[2]) // 4) * 4
    hi = gi.get("height_intent") or {}
    return (
        gi.get("silhouette_id"),
        gi.get("style"),
        hi.get("roof_style"),
        len(gi.get("floors") or []),
        w_bucket, d_bucket,
    )


def _variety_score(builds, iter_dir):
    """Compute the variety penalty for the iter (max -0.10).

    diversity_index = unique fingerprints / n built (∈ [0, 1])
    penalty = max(0, 0.6 - diversity_index) * 0.25  (max 0.10)
    """
    fingerprints = []
    for b in builds:
        if b.error or b.final_path is None:
            continue
        gen_id = b.final_path.stem
        fp = _fingerprint(iter_dir / gen_id)
        if fp:
            fingerprints.append(fp)
    n = len(fingerprints)
    unique = len(set(fingerprints))
    diversity = unique / n if n else 0.0
    penalty = max(0.0, 0.6 - diversity) * 0.25  # cap 0.10 when all 10 identical
    return {"n_builds": n, "unique_fingerprints": unique,
            "diversity_index": round(diversity, 3),
            "penalty": round(penalty, 3),
            "samples": fingerprints[:5]}


def _typology_signature(workdir: Path):
    """Read gi.selected_typologies from workdir/global_intent.json and
    return a hashable tuple in canonical (tower, roof, window, garden)
    order. Returns None if the file is missing/unreadable.
    """
    try:
        gi = json.loads((workdir / "global_intent.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    sel = (gi.get("selected_typologies") or {})
    return (sel.get("tower"), sel.get("roof"),
            sel.get("window"), sel.get("garden"))


def _typology_diversity_score(builds, iter_dir):
    """Compute typology choice diversity across the iter (Fase 6).

    Informational — NOT subtracted from `mean_score` (same principle as
    `_variety_score` post-44d354a). Reported in REPORT.md so the user
    can see whether the chooser is driving diversity or collapsing to
    the same picks every prompt.
    """
    sigs = []
    with_choice = 0
    for b in builds:
        if b.error or b.final_path is None:
            continue
        gen_id = b.final_path.stem
        sig = _typology_signature(iter_dir / gen_id)
        if sig is None:
            continue
        sigs.append(sig)
        if any(v is not None for v in sig):
            with_choice += 1

    n = len(sigs)
    unique = len(set(sigs))
    diversity = (unique / with_choice) if with_choice else 0.0

    KINDS = ("tower", "roof", "window", "garden")
    by_kind = {}
    for i, k in enumerate(KINDS):
        picks = {sig[i] for sig in sigs if sig[i] is not None}
        by_kind[k] = len(picks)

    return {
        "n_builds":          n,
        "n_with_choice":     with_choice,
        "unique_signatures": unique,
        "diversity_index":   round(diversity, 3),
        "by_kind_unique":    by_kind,
        "samples":           sigs[:5],
    }


def _build_one(gp: GymPrompt, iter_num: int, iter_dir: Path,
                 verbose: bool = False) -> BuildResult:
    """Run one pipeline build. Returns BuildResult with score loaded."""
    gen_id = f"gym-i{iter_num:02d}-{gp.slot}"
    try:
        final_path = run_pipeline(
            gp.prompt,
            gen_id=gen_id,
            pipeline_version="v4",
            parallel_rooms=True,
            verbose=verbose,
            out_base_dir=iter_dir,
        )
        # Load the evaluation_report.json from workdir
        report_path = iter_dir / gen_id / "evaluation_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) \
            if report_path.exists() else None
        comp = (report or {}).get("composite") or {}
        return BuildResult(
            slot=gp.slot,
            prompt=gp.prompt,
            composite=comp.get("overall"),
            physical=comp.get("physical_total"),
            alexander=comp.get("alexander_total"),
            final_path=final_path,
            report_path=report_path if report_path.exists() else None,
            error=None,
        )
    except Exception as e:    # noqa: BLE001
        return BuildResult(
            slot=gp.slot, prompt=gp.prompt,
            composite=None, physical=None, alexander=None,
            final_path=None, report_path=None,
            error=f"{type(e).__name__}: {e}",
        )


def _rename_with_score(b: BuildResult, iter_dir: Path) -> None:
    """Copy <gen_id>.json + <gen_id>.evaluation.json into iter_dir/ with
    score-prefixed names that the user requested."""
    if b.final_path is None or b.composite is None:
        return
    score_prefix = f"{b.composite:.3f}"
    safe_slot = _safe_slug(b.slot)
    new_name = f"{score_prefix}_{safe_slot}.json"
    new_path = iter_dir / new_name
    if b.final_path != new_path:
        shutil.copy(b.final_path, new_path)
    eval_src = b.final_path.with_suffix("") .with_name(
        b.final_path.stem + ".evaluation.json")
    eval_alt = b.final_path.parent / f"{b.final_path.stem}.evaluation.json"
    src = eval_src if eval_src.exists() else eval_alt
    if src.exists():
        shutil.copy(src, iter_dir / f"{score_prefix}_{safe_slot}.evaluation.json")


def run_iteration(iter_num: int, *, workers: int = 10,
                    verbose: bool = False) -> dict:
    """Run one iteration. Returns a dict with stats for SUMMARY.md."""
    iter_dir = OUT_BASE / f"iter{iter_num:02d}"
    iter_dir.mkdir(parents=True, exist_ok=True)

    # Pre-warm shared module caches so 10 parallel threads don't race on
    # cold-loading the TF-IDF index or scanning rag/skills/. The locks
    # serialize on miss but the matrix init is fragile to concurrent
    # access in scipy < 1.13.
    from pipeline.agents import retriever as _r
    from pipeline.agents import global_designer as _gd
    from pipeline.agents import space_planner as _sp
    from pipeline.agents import floor_planner as _fp
    _ = _r._index()
    _ = _r._skills()
    _ = _gd._silhouettes()
    _ = _sp._floor_layouts()
    _ = _sp._connector_templates()
    _ = _fp._floor_layouts_full()
    _ = _fp._room_role_briefs()

    t0 = time.time()
    print(f"[gym-iter{iter_num:02d}] launching {len(GYM_PROMPTS)} builds "
           f"(workers={workers}) …", flush=True)
    builds: list[BuildResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_build_one, gp, iter_num, iter_dir, verbose): gp
                   for gp in GYM_PROMPTS}
        for n, fut in enumerate(as_completed(futures), 1):
            gp = futures[fut]
            try:
                br = fut.result()
            except Exception as e:    # noqa: BLE001
                br = BuildResult(gp.slot, gp.prompt, None, None, None,
                                  None, None, f"executor: {e}")
            builds.append(br)
            mark = "✓" if br.error is None else "✗"
            tag = (f"score={br.composite:.3f}" if br.composite is not None
                   else (br.error or "no-score"))
            print(f"  [{n:2d}/{len(GYM_PROMPTS)}] {mark} {gp.slot:24s} "
                   f"{tag}", flush=True)

    # Copy score-renamed files into iter_dir
    for b in builds:
        _rename_with_score(b, iter_dir)

    # Build reports map for the diagnoser
    reports: dict[str, dict] = {}
    for b in builds:
        if b.report_path and b.report_path.exists():
            try:
                reports[b.slot] = json.loads(b.report_path.read_text(encoding="utf-8"))
            except Exception:    # noqa: BLE001
                reports[b.slot] = {}
        else:
            reports[b.slot] = {}

    # Load prev_min from SUMMARY history
    history_path = OUT_BASE / "history.json"
    history: list[dict] = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except Exception:    # noqa: BLE001
            history = []
    prev_min = history[-1]["min_score"] if history else None

    # Audit history (skill changes per iter)
    audit_path = OUT_BASE / "audit.json"
    audit_history: list[dict] = []
    if audit_path.exists():
        try:
            audit_history = json.loads(audit_path.read_text(encoding="utf-8"))
        except Exception:    # noqa: BLE001
            audit_history = []

    # Variety penalty — anti reward-hacking + anti monotony. Extracts a
    # fingerprint per build from its `global_intent.json` and penalises the
    # iter mean when the 10 builds cluster on the same silhouette/style/roof.
    # No reward stacking on the same look.
    variety = _variety_score(builds, iter_dir)

    # Fase 6 — typology catalog diversity (chooser picks across the iter).
    # Independent diagnostic, not folded into mean_score.
    typology_variety = _typology_diversity_score(builds, iter_dir)

    # Render REPORT.md
    report_md = render_report(iter_num, builds, reports,
                                prev_min=prev_min, audit_history=audit_history,
                                variety=variety,
                                typology_variety=typology_variety)
    (iter_dir / "REPORT.md").write_text(report_md, encoding="utf-8")

    # Stats — `mean_score` is the RAW evaluator mean (no variety adjustment).
    # `variety_index` is reported alongside as an INDEPENDENT diagnostic.
    scored = [b.composite for b in builds if b.composite is not None]
    raw_mean = sum(scored) / len(scored) if scored else 0.0
    stats = {
        "iter": iter_num,
        "min_score": min(scored) if scored else 0.0,
        "max_score": max(scored) if scored else 0.0,
        "mean_score": raw_mean,
        "variety_index": variety["diversity_index"],
        "variety_unique_fingerprints": variety["unique_fingerprints"],
        "typology_diversity_index": typology_variety["diversity_index"],
        "typology_n_with_choice":    typology_variety["n_with_choice"],
        "typology_by_kind_unique":   typology_variety["by_kind_unique"],
        "n_built": len(scored),
        "n_failed": len([b for b in builds if b.error]),
        "wall_clock_s": round(time.time() - t0, 1),
        "converged": (len(scored) == len(GYM_PROMPTS)
                       and min(scored) >= 0.80) if scored else False,
        "skills_changed_count": 0,    # filled in by post-edit hook
    }
    history.append(stats)
    history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
    (OUT_BASE / "SUMMARY.md").write_text(render_summary(history),
                                           encoding="utf-8")

    # Render a contact sheet of ALL buildings into the iter folder so each
    # iteration ships a visual snapshot alongside the score-prefixed JSONs.
    try:
        from tools import render_build as _rb
        sheet = _rb.contact_sheet(iter_dir, cols=4)
        sheet_path = iter_dir / f"iter{iter_num:02d}_render.png"
        sheet.save(sheet_path)
        print(f"[gym-iter{iter_num:02d}] render: {sheet_path}")
    except Exception as e:    # noqa: BLE001 — rendering must never fail the iter
        print(f"[gym-iter{iter_num:02d}] render skipped ({e})")

    print(f"\n[gym-iter{iter_num:02d}] done  min={stats['min_score']:.3f}  "
           f"mean={stats['mean_score']:.3f}  max={stats['max_score']:.3f}  "
           f"({stats['wall_clock_s']:.0f}s)")
    print(f"[gym-iter{iter_num:02d}] REPORT: {iter_dir / 'REPORT.md'}")
    if stats["converged"]:
        print(f"\n🎉 CONVERGED — all 10 builds >= 0.80\n")
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iter", "-i", type=int, default=None,
                     help="iteration number (auto-increments if --auto)")
    ap.add_argument("--auto", action="store_true",
                     help="auto-pick next iter from history.json")
    ap.add_argument("--workers", type=int, default=10,
                     help="parallel build workers (default 10)")
    ap.add_argument("--verbose", "-v", action="store_true",
                     help="verbose per-build logs (default: quiet)")
    args = ap.parse_args(argv)

    if args.iter is None and args.auto:
        history_path = OUT_BASE / "history.json"
        if history_path.exists():
            history = json.loads(history_path.read_text(encoding="utf-8"))
            args.iter = (history[-1]["iter"] + 1) if history else 1
        else:
            args.iter = 1
    if args.iter is None:
        ap.error("--iter or --auto required")

    OUT_BASE.mkdir(parents=True, exist_ok=True)
    stats = run_iteration(args.iter, workers=args.workers, verbose=args.verbose)
    return 0 if stats["converged"] or stats["n_built"] >= 8 else 2


if __name__ == "__main__":
    sys.exit(main())
