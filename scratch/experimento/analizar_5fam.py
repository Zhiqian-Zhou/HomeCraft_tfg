#!/usr/bin/env python3
"""Análisis del experimento 5-familias con intervalos de confianza (k=3 reps).

Lee results_5fam.jsonl. Agrega las repeticiones por (modelo, prompt) y calcula
por modelo: tasa de completado ± IC Wilson 95%, overall y cada familia
media ± IC bootstrap 95%, tokens/tiempo. Tests entre modelos (Mann-Whitney).
Plots en plots_5fam/. Resumen a stats_5fam.json (consumido por el markdown).
"""
from __future__ import annotations
import json, math, statistics as st
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
try:
    from scipy import stats as sps
except Exception:
    sps = None

EXP = Path("/Users/zhiqian/Desktop/Uni/TFGv2Z/scratch/experimento")
PLOTS = EXP / "plots_5fam"; PLOTS.mkdir(exist_ok=True)
_RAW = [json.loads(l) for l in (EXP / "results_5fam.jsonl").read_text().splitlines() if l.strip()]
# El re-run APPENDEA filas (reintentos) → deduplicar por (model,prompt,rep)
# quedándose con el ÚLTIMO registro (el reintento más reciente).
_last = {}
for _r in _RAW:
    _last[(_r["model"], _r["prompt_key"], _r.get("rep", 0))] = _r
ROWS = list(_last.values())

ORDER = ["meta-llama/llama-4-scout", "qwen/qwen3.5-35b-a3b", "google/gemma-4-26b-a4b-it",
         "qwen/qwen3.5-9b", "meta-llama/llama-3.3-70b-instruct", "google/gemma-4-31b-it"]
MODELS = [m for m in ORDER if any(r["model"] == m for r in ROWS)]
SHORT = {m: m.split("/")[-1] for m in MODELS}
FAMILIES = ["overall", "physical_total", "alexander_total", "prompt_adherence_total",
            "interior_total", "exterior_total"]
PROMPTS = []
for r in ROWS:
    if r["prompt_key"] not in PROMPTS:
        PROMPTS.append(r["prompt_key"])


def boot_ci(vals, n=5000, alpha=0.05):
    """Bootstrap percentile 95% CI of the mean. Returns (mean, lo, hi)."""
    a = np.array([v for v in vals if isinstance(v, (int, float))], dtype=float)
    if len(a) == 0:
        return (None, None, None)
    if len(a) == 1:
        return (float(a[0]), float(a[0]), float(a[0]))
    rng = np.random.default_rng(12345)
    means = a[rng.integers(0, len(a), size=(n, len(a)))].mean(axis=1)
    return (float(a.mean()), float(np.percentile(means, 100 * alpha / 2)),
            float(np.percentile(means, 100 * (1 - alpha / 2))))


def wilson(k, n, z=1.96):
    """Wilson 95% CI for a proportion k/n. Returns (p, lo, hi)."""
    if n == 0:
        return (None, None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, max(0, c - h), min(1, c + h))


def ok_rows(m):
    return [r for r in ROWS if r["model"] == m and r.get("status") == "ok"
            and isinstance(r.get("overall"), (int, float))]


# ── aggregate per model ──────────────────────────────────────────────────
summary = {}
for m in MODELS:
    rs = [r for r in ROWS if r["model"] == m]
    ok = ok_rows(m)
    n_ok, n_tot = len(ok), len(rs)
    p, plo, phi = wilson(n_ok, n_tot)
    fam = {}
    for f in FAMILIES:
        mean, lo, hi = boot_ci([r.get(f) for r in ok])
        fam[f] = {"mean": mean, "lo": lo, "hi": hi}
    toks = [r.get("total_tokens") for r in ok if isinstance(r.get("total_tokens"), (int, float))]
    wall = [r.get("wall_s") for r in ok if isinstance(r.get("wall_s"), (int, float))]
    summary[m] = {
        "n_ok": n_ok, "n_total": n_tot,
        "completion": {"p": p, "lo": plo, "hi": phi},
        "families": fam,
        "tokens": boot_ci(toks), "wall_s": boot_ci(wall),
        "overall_samples": [r["overall"] for r in ok],
    }

# pairwise Mann-Whitney on overall vs the top model
best = max((m for m in MODELS if summary[m]["n_ok"] > 0),
           key=lambda m: summary[m]["families"]["overall"]["mean"] or 0, default=None)
tests = {}
if sps and best:
    for m in MODELS:
        if m == best or summary[m]["n_ok"] < 2:
            continue
        try:
            u, pv = sps.mannwhitneyu(summary[best]["overall_samples"],
                                      summary[m]["overall_samples"], alternative="two-sided")
            tests[m] = {"vs": best, "p_value": float(pv)}
        except Exception:
            pass

(EXP / "stats_5fam.json").write_text(json.dumps(
    {"summary": summary, "best": best, "tests": tests, "n_builds": len(ROWS),
     "models": MODELS, "prompts": PROMPTS}, indent=2), encoding="utf-8")

# ── plots ────────────────────────────────────────────────────────────────
labels = [SHORT[m] for m in MODELS]
x = np.arange(len(MODELS))

# 1. overall ± bootstrap CI
fig, ax = plt.subplots(figsize=(11, 6))
means = [summary[m]["families"]["overall"]["mean"] or 0 for m in MODELS]
los = [summary[m]["families"]["overall"]["lo"] or 0 for m in MODELS]
his = [summary[m]["families"]["overall"]["hi"] or 0 for m in MODELS]
yerr = [[m_ - l for m_, l in zip(means, los)], [h - m_ for m_, h in zip(means, his)]]
ax.bar(x, means, yerr=yerr, capsize=5, color="#4C72B0")
for i, m in enumerate(MODELS):
    ax.text(i, (his[i] or 0) + 0.01, f"{means[i]:.3f}\n{summary[m]['n_ok']}/{summary[m]['n_total']}",
            ha="center", va="bottom", fontsize=8)
ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20, ha="right")
ax.set_ylabel("overall (media ± IC bootstrap 95%)"); ax.set_ylim(0, 1)
ax.set_title("Calidad overall por modelo (k=3 reps × 10 prompts)")
ax.grid(axis="y", alpha=0.3); fig.tight_layout()
fig.savefig(PLOTS / "01_overall_ci.png", dpi=110); plt.close()

# 2. boxplot overall per model
fig, ax = plt.subplots(figsize=(11, 6))
data = [summary[m]["overall_samples"] or [0] for m in MODELS]
ax.boxplot(data, labels=labels, showmeans=True)
ax.set_xticklabels(labels, rotation=20, ha="right")
ax.set_ylabel("overall"); ax.set_title("Distribución de overall por modelo")
ax.grid(axis="y", alpha=0.3); fig.tight_layout()
fig.savefig(PLOTS / "02_overall_boxplot.png", dpi=110); plt.close()

# 3. stacked families (weighted contribution to overall)
W = {"physical_total": 0.20, "alexander_total": 0.15, "prompt_adherence_total": 0.30,
     "interior_total": 0.20, "exterior_total": 0.15}
COL = {"physical_total": "#55A868", "alexander_total": "#C44E52",
       "prompt_adherence_total": "#8172B3", "interior_total": "#CCB974",
       "exterior_total": "#64B5CD"}
fig, ax = plt.subplots(figsize=(11, 6))
bottom = np.zeros(len(MODELS))
for f, w in W.items():
    vals = [(summary[m]["families"][f]["mean"] or 0) * w for m in MODELS]
    ax.bar(x, vals, bottom=bottom, label=f.replace("_total", "") + f" (×{w})", color=COL[f])
    bottom += np.array(vals)
ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20, ha="right")
ax.set_ylabel("contribución ponderada al overall")
ax.set_title("Descomposición del overall por familia (5)")
ax.legend(fontsize=8); ax.grid(axis="y", alpha=0.3); fig.tight_layout()
fig.savefig(PLOTS / "03_families_stacked.png", dpi=110); plt.close()

# 4. completion ± Wilson CI
fig, ax = plt.subplots(figsize=(11, 6))
cp = [summary[m]["completion"]["p"] or 0 for m in MODELS]
clo = [summary[m]["completion"]["lo"] or 0 for m in MODELS]
chi = [summary[m]["completion"]["hi"] or 0 for m in MODELS]
yerr = [[p - l for p, l in zip(cp, clo)], [h - p for p, h in zip(cp, chi)]]
ax.bar(x, [v * 100 for v in cp], yerr=[[e * 100 for e in yerr[0]], [e * 100 for e in yerr[1]]],
       capsize=5, color="#C44E52")
ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20, ha="right")
ax.set_ylabel("% completado (± IC Wilson 95%)"); ax.set_ylim(0, 100)
ax.set_title("Tasa de completado por modelo"); ax.grid(axis="y", alpha=0.3); fig.tight_layout()
fig.savefig(PLOTS / "04_completion_ci.png", dpi=110); plt.close()

# 5. cost & time
fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5))
tk = [(summary[m]["tokens"][0] or 0) / 1000 for m in MODELS]
a1.bar(x, tk, color="#937860"); a1.set_xticks(x); a1.set_xticklabels(labels, rotation=20, ha="right")
a1.set_ylabel("tokens medios (k)"); a1.set_title("Coste en tokens/build"); a1.grid(axis="y", alpha=0.3)
wl = [summary[m]["wall_s"][0] or 0 for m in MODELS]
a2.bar(x, wl, color="#DA8BC3"); a2.set_xticks(x); a2.set_xticklabels(labels, rotation=20, ha="right")
a2.set_ylabel("wall_s medio"); a2.set_title("Tiempo/build"); a2.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(PLOTS / "05_cost_time.png", dpi=110); plt.close()

# 6. heatmap model × prompt (mean overall over reps)
M = np.full((len(MODELS), len(PROMPTS)), np.nan)
for i, m in enumerate(MODELS):
    for j, pk in enumerate(PROMPTS):
        vs = [r["overall"] for r in ROWS if r["model"] == m and r["prompt_key"] == pk
              and isinstance(r.get("overall"), (int, float))]
        if vs:
            M[i, j] = sum(vs) / len(vs)
fig, ax = plt.subplots(figsize=(13, 6))
im = ax.imshow(M, cmap="RdYlGn", vmin=0.4, vmax=0.9, aspect="auto")
ax.set_xticks(range(len(PROMPTS))); ax.set_xticklabels(PROMPTS, rotation=40, ha="right", fontsize=8)
ax.set_yticks(range(len(MODELS))); ax.set_yticklabels(labels, fontsize=9)
for i in range(len(MODELS)):
    for j in range(len(PROMPTS)):
        t = "✗" if np.isnan(M[i, j]) else f"{M[i,j]:.2f}"
        ax.text(j, i, t, ha="center", va="center", fontsize=7)
fig.colorbar(im, label="overall (media reps)")
ax.set_title("overall por modelo × prompt (✗ = ningún build OK)")
fig.tight_layout(); fig.savefig(PLOTS / "06_heatmap_model_prompt.png", dpi=110); plt.close()

# 7. heatmap model × metric (individual, incl. nuevas)
METS = []
for r in ROWS:
    for k in (r.get("metrics") or {}):
        if k not in METS:
            METS.append(k)
METS.sort()
H = np.full((len(MODELS), len(METS)), np.nan)
for i, m in enumerate(MODELS):
    rs = [r for r in ROWS if r["model"] == m and r.get("metrics")]
    for j, met in enumerate(METS):
        vs = [r["metrics"][met] for r in rs if met in r["metrics"]]
        if vs:
            H[i, j] = sum(vs) / len(vs)
fig, ax = plt.subplots(figsize=(17, 6))
im = ax.imshow(H, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
ax.set_xticks(range(len(METS))); ax.set_xticklabels(METS, rotation=55, ha="right", fontsize=7)
ax.set_yticks(range(len(MODELS))); ax.set_yticklabels(labels, fontsize=9)
fig.colorbar(im, label="score medio")
ax.set_title("Score medio por modelo × métrica individual")
fig.tight_layout(); fig.savefig(PLOTS / "07_heatmap_model_metric.png", dpi=110); plt.close()

# ── console summary ──
print(f"\n{'modelo':24}{'ok':>7}{'overall[95% CI]':>22}{'tokens':>9}{'wall':>7}")
for m in MODELS:
    s = summary[m]; f = s["families"]["overall"]
    ci = f"{f['mean']:.3f} [{f['lo']:.3f},{f['hi']:.3f}]" if f["mean"] is not None else "—"
    print(f"{SHORT[m]:24}{s['n_ok']:>3}/{s['n_total']:<3}{ci:>22}"
          f"{(s['tokens'][0] or 0):>9.0f}{(s['wall_s'][0] or 0):>7.0f}")
print(f"\nbest={SHORT.get(best,'?')}  tests vs best:",
      {SHORT[k]: round(v['p_value'], 4) for k, v in tests.items()})
print("plots →", PLOTS)
