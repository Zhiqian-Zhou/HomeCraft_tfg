"""Weak-metric diagnosis: read evaluation_report.json + map weak metrics
to the skill_category most responsible for them.

Two outputs:
  - rank_weak_metrics(report, k) -> list[WeakPoint] for one building
  - aggregate_across_builds(reports) -> dict[metric_id, GlobalWeakness]
    for the whole iteration

Severity formula: family_weight * (1 - score), where family weights are
0.55 physical / 0.45 alexander (per evaluator.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field

_FAMILY_W = {"physical": 0.55, "alexander": 0.45}
_HIGH_THRESHOLD = 0.85  # metrics >= 0.85 already done; not "weak"

# From Pre-B.2 research. Map metric_id → primary skill_category(ies).
METRIC_TO_CATEGORIES: dict[str, list[str]] = {
    "structural_integrity":   ["global_silhouette"],
    "voxel_connectivity":     ["connector_template", "floor_layout"],
    "vertical_clearance":     ["room_role", "floor_layout"],
    "door_functionality":     ["connector_template"],
    "light_coverage":         ["room_decoration"],
    "block_legitimacy":       [],
    "material_consistency":   ["room_decoration", "wall_fitting"],
    "volume_density":         ["global_silhouette"],
    "light_on_two_sides":     ["wall_fitting", "floor_layout"],
    "intimacy_gradient":      ["room_role", "floor_layout"],
    "common_areas_at_heart":  ["floor_layout", "room_role"],
    "sheltering_roof":        ["global_silhouette"],
    "building_edge":          ["exterior_feature"],
    "window_place":           ["wall_fitting", "room_decoration"],
    "entrance_transition":    ["connector_template", "room_role"],
    "main_entrance":          ["connector_template", "global_silhouette"],
    "farmhouse_kitchen":      ["room_decoration", "connector_template"],
    "roof_layout":            ["global_silhouette"],
}

# Metrics that cannot be fixed by skill changes — composer / palette level.
DEFERRED_METRICS: set[str] = {"structural_integrity", "block_legitimacy"}


@dataclass
class WeakPoint:
    metric_id: str
    family: str           # "physical" or "alexander"
    score: float
    weight: float         # family_weight * nominal_weight
    deficit: float        # 1 - score
    severity: float       # weight * deficit
    notes: str = ""
    affected_skill_categories: list[str] = field(default_factory=list)


@dataclass
class GlobalWeakness:
    metric_id: str
    affected_count: int             # how many of the 10 builds are weak on this
    mean_score: float
    max_severity: float             # the worst single-build severity
    affected_slots: list[str] = field(default_factory=list)
    skill_categories: list[str] = field(default_factory=list)


def _metric_iter(report: dict):
    """Yield (metric_id, family, metric_dict) for all 18 scored metrics."""
    for family in ("physical", "alexander"):
        block = report.get(family) or {}
        for mid, m in block.items():
            if not isinstance(m, dict):
                continue
            yield mid, family, m


def _effective_weight(report: dict, family: str, metric_id: str) -> float:
    """Use weight_table from composite if present; otherwise fall back to
    1/N within family. Multiplied by family_weight (0.55/0.45)."""
    wt = (report.get("composite") or {}).get("weight_table") or {}
    fam_wt = wt.get(family) or {}
    nominal = fam_wt.get(metric_id)
    if nominal is None:
        block = report.get(family) or {}
        scored = [mid for mid, m in block.items()
                  if isinstance(m, dict) and m.get("score") is not None]
        nominal = 1.0 / len(scored) if scored else 0.0
    return _FAMILY_W[family] * float(nominal)


def rank_weak_metrics(report: dict, k: int = 3) -> list[WeakPoint]:
    """Return top-K weakest metrics for one building."""
    out: list[WeakPoint] = []
    for mid, family, m in _metric_iter(report):
        s = m.get("score")
        if s is None or s >= _HIGH_THRESHOLD:
            continue
        if mid in DEFERRED_METRICS:
            continue
        w = _effective_weight(report, family, mid)
        d = 1.0 - float(s)
        out.append(WeakPoint(
            metric_id=mid, family=family, score=float(s),
            weight=w, deficit=d, severity=w * d,
            notes=str(m.get("notes", ""))[:200],
            affected_skill_categories=METRIC_TO_CATEGORIES.get(mid, []),
        ))
    out.sort(key=lambda x: (-x.severity, -x.weight, x.metric_id))
    return out[:k]


def aggregate_across_builds(
    reports: dict[str, dict],
    *,
    weak_threshold: float = 0.40,
) -> dict[str, GlobalWeakness]:
    """Across an iteration's 10 reports, find which metrics are
    systematically weak."""
    metric_data: dict[str, dict] = {}
    for slot, report in reports.items():
        if not report:
            continue
        for mid, family, m in _metric_iter(report):
            s = m.get("score")
            if s is None or mid in DEFERRED_METRICS:
                continue
            d = metric_data.setdefault(mid, {
                "scores": [], "slots": [], "max_sev": 0.0, "family": family,
            })
            d["scores"].append(float(s))
            if float(s) < weak_threshold:
                d["slots"].append(slot)
            w = _effective_weight(report, family, mid)
            sev = w * (1.0 - float(s))
            d["max_sev"] = max(d["max_sev"], sev)

    out: dict[str, GlobalWeakness] = {}
    for mid, d in metric_data.items():
        scores = d["scores"]
        if not scores:
            continue
        out[mid] = GlobalWeakness(
            metric_id=mid,
            affected_count=len(d["slots"]),
            mean_score=sum(scores) / len(scores),
            max_severity=d["max_sev"],
            affected_slots=sorted(d["slots"]),
            skill_categories=METRIC_TO_CATEGORIES.get(mid, []),
        )
    return out


def top_global_weak(
    aggregated: dict[str, GlobalWeakness],
    k: int = 3,
    min_affected: int = 3,
) -> list[GlobalWeakness]:
    """Return top-K metrics where >= min_affected builds are weak,
    sorted by max_severity descending."""
    eligible = [g for g in aggregated.values()
                if g.affected_count >= min_affected]
    eligible.sort(key=lambda g: (-g.max_severity, -g.affected_count, g.metric_id))
    return eligible[:k]
