"""Render REPORT.md for a single gym iteration.

Synthesis of Pre-B.5 research. Section layout:
  1. Header  (yaml-style metadata: iter, mins/max/mean, convergence status)
  2. Per-build table  (slot, prompt, composite, top-3 weak metrics)
  3. Per-metric histogram across the 10 builds
  4. Top-3 globally weak metrics with notes + responsible skill_category
  5. Action checklist for Claude to tick

Claude reads this file (and only this) to decide skill changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .diagnose import (
    aggregate_across_builds, rank_weak_metrics, top_global_weak,
    DEFERRED_METRICS, METRIC_TO_CATEGORIES,
)


@dataclass
class BuildResult:
    slot: str
    prompt: str
    composite: Optional[float]
    physical: Optional[float]
    alexander: Optional[float]
    final_path: Optional[Path]
    report_path: Optional[Path]     # path to evaluation_report.json
    error: Optional[str] = None


def _ascii_bar(value: float, width: int = 10) -> str:
    filled = int(round(value * width))
    return "█" * filled + "░" * (width - filled)


def _fmt(v: Optional[float], n: int = 3) -> str:
    return f"{v:.{n}f}" if isinstance(v, float) else "----"


def render_report(
    iter_num: int,
    builds: list[BuildResult],
    reports: dict[str, dict],     # slot → evaluation_report.json
    prev_min: Optional[float] = None,
    audit_history: Optional[list[dict]] = None,
    variety: Optional[dict] = None,
    typology_variety: Optional[dict] = None,   # Fase 6
) -> str:
    """Build the REPORT.md content as a string."""
    scored = [b for b in builds if b.composite is not None]
    if scored:
        scores = [b.composite for b in scored]
        mn, mx = min(scores), max(scores)
        mean_raw = sum(scores) / len(scores)
    else:
        mn = mx = mean_raw = 0.0

    # Variety is reported INDEPENDENTLY — it is NOT subtracted from the
    # evaluator mean. The mean score remains the raw composite average.
    var_index = (variety or {}).get("diversity_index", 1.0)
    var_unique = (variety or {}).get("unique_fingerprints", len(scored))
    # Fase 6 — typology catalog diversity (chooser output across the iter).
    tv = typology_variety or {}
    tv_index = tv.get("diversity_index", 0.0)
    tv_with_choice = tv.get("n_with_choice", 0)
    tv_by_kind = tv.get("by_kind_unique") or {}
    mean = mean_raw

    if prev_min is not None:
        delta = mn - prev_min
        status = ("converged"  if mn >= 0.8
                  else "regressing" if delta < -0.02
                  else "stalled"    if abs(delta) < 0.01
                  else "improving")
    else:
        status = "converged" if mn >= 0.8 else "first_iter"
        delta = 0.0

    lines: list[str] = []
    lines.append(f"# Gym Iter {iter_num:02d}\n")
    lines.append("```yaml")
    lines.append(f"iter: {iter_num}")
    lines.append(f"min_score: {mn:.3f}")
    lines.append(f"max_score: {mx:.3f}")
    lines.append(f"mean_score: {mean:.3f}")
    lines.append(f"diversity_index: {var_index:.3f}  "
                  f"# INDEPENDENT — unique_fingerprints={var_unique}/{len(scored)}")
    if tv_with_choice or tv_index:
        bk = ", ".join(f"{k}={v}" for k, v in sorted(tv_by_kind.items())) or "—"
        lines.append(f"typology_diversity_index: {tv_index:.3f}  "
                      f"# Fase 6 — typology choices across {tv_with_choice} builds; by_kind=[{bk}]")
    lines.append(f"convergence_status: {status}")
    lines.append(f"delta_vs_prev_min: {delta:+.3f}")
    lines.append(f"target_min: 0.80")
    lines.append(f"target_all_above: 0.80")
    lines.append("```\n")

    # 2. Per-build table
    lines.append("## Per-Build Results (ascending by composite)\n")
    lines.append("| Slot | Prompt | Composite | Phys | Alex | Worst 3 metrics |")
    lines.append("|---|---|---|---|---|---|")
    builds_sorted = sorted(builds,
                            key=lambda b: (b.composite if b.composite is not None else -1.0))
    for b in builds_sorted:
        worst: list[str] = []
        if b.composite is not None and reports.get(b.slot):
            wp = rank_weak_metrics(reports[b.slot], k=3)
            worst = [f"{w.metric_id}({w.score:.2f})" for w in wp]
        prompt_short = b.prompt[:50] + ("…" if len(b.prompt) > 50 else "")
        if b.error:
            lines.append(f"| {b.slot} | {prompt_short} | ERR | --- | --- | "
                          f"{b.error[:50]} |")
        else:
            lines.append(f"| {b.slot} | {prompt_short} | "
                          f"{_fmt(b.composite)} | {_fmt(b.physical, 2)} | "
                          f"{_fmt(b.alexander, 2)} | {', '.join(worst)} |")
    lines.append("")

    # 3. Per-metric histogram (mean across 10 builds)
    lines.append("## Metric Health (mean across 10 builds)\n")
    valid_reports = {s: r for s, r in reports.items() if r}
    if valid_reports:
        agg = aggregate_across_builds(valid_reports)
        metrics_sorted = sorted(agg.values(), key=lambda g: g.mean_score)
        lines.append("```")
        for g in metrics_sorted:
            bar = _ascii_bar(g.mean_score)
            lines.append(
                f"{g.metric_id:<22s} [{bar}] {g.mean_score:.2f}  "
                f"(weak={g.affected_count}/{len(valid_reports)})")
        lines.append("```\n")

        # 4. Top-3 globally weak metrics with deep-dive
        tops = top_global_weak(agg, k=3, min_affected=2)
        if tops:
            lines.append("## Top Weak Metrics — what Claude should attack\n")
            for i, g in enumerate(tops, 1):
                cats = ", ".join(g.skill_categories) or "(no mapping)"
                lines.append(f"### {i}. {g.metric_id} "
                              f"(mean {g.mean_score:.2f}, "
                              f"{g.affected_count} weak builds)")
                lines.append(f"**Skill category responsible:** `{cats}`")
                lines.append(f"**Affected builds:**")
                for slot in g.affected_slots:
                    rep = reports.get(slot) or {}
                    block = rep.get("physical", {}) if g.metric_id in (
                        rep.get("physical") or {}) else rep.get("alexander", {})
                    m = block.get(g.metric_id) or {}
                    notes = str(m.get("notes", ""))[:120]
                    lines.append(
                        f"- {slot} (score {m.get('score', 'n/a')}) — {notes}")
                lines.append("")

    # 5. Audit history (skills changed in past iters)
    if audit_history:
        lines.append("## Skill Audit History\n")
        lines.append("| Iter | Action | Skill ID | Category | Rationale |")
        lines.append("|---|---|---|---|---|")
        for entry in audit_history[-20:]:    # last 20 to keep report short
            lines.append(
                f"| {entry.get('iter', '?')} | {entry.get('action', '?')} | "
                f"{entry.get('skill_id', '?')} | {entry.get('category', '?')} | "
                f"{entry.get('rationale', '')[:60]} |")
        lines.append("")

    # 6. Action checklist (pre-populated; Claude ticks as work)
    lines.append("## Action Checklist (Claude edits this)\n")
    if valid_reports:
        tops = top_global_weak(agg, k=3, min_affected=2)
        for g in tops:
            cats = g.skill_categories or ["(unmapped)"]
            cat_str = cats[0]
            lines.append(
                f"- [ ] Address `{g.metric_id}` "
                f"(skill_category=`{cat_str}`): "
                f"create OR modify a generic skill that improves this metric")
    lines.append("- [ ] Run `python3 tools/verify_rag_cross_refs.py` "
                  "(must stay 6/6 PASS)")
    lines.append("- [ ] Run `python3 -m tools.gym.genericness "
                  "<changed_skill.json>` for each new skill")
    lines.append("- [ ] When done, re-launch the gym for iter "
                  f"{iter_num + 1:02d}\n")

    return "\n".join(lines)


def render_summary(iter_history: list[dict]) -> str:
    """Render output/gym/SUMMARY.md showing iter→iter evolution."""
    lines = ["# Gym Loop Summary\n"]
    lines.append("| Iter | min | mean | max | Δ min | skills_changed |")
    lines.append("|---|---|---|---|---|---|")
    prev = None
    for h in iter_history:
        mn = h.get("min_score", 0.0)
        delta = f"{mn - prev:+.3f}" if prev is not None else "----"
        lines.append(
            f"| {h.get('iter', '?'):02d} | {mn:.3f} | "
            f"{h.get('mean_score', 0.0):.3f} | "
            f"{h.get('max_score', 0.0):.3f} | {delta} | "
            f"{h.get('skills_changed_count', 0)} |")
        prev = mn
    return "\n".join(lines) + "\n"
