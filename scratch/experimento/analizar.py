#!/usr/bin/env python3
"""Análisis del experimento multi-LLM: results.jsonl -> CSV + plots.

Genera en scratch/experimento/plots/:
  01_overall_por_modelo.png      barras overall medio (±dt) + tasa de exito
  02_familias_apiladas.png       physical/alexander/appearance por modelo
  03_coste_calidad.png           scatter tokens vs overall (por build)
  04_tiempo_calidad.png          scatter llm_wait_s vs overall
  05_heatmap_modelo_prompt.png   overall por (modelo,prompt)
  06_heatmap_modelo_metrica.png  score medio por (modelo, 18 metricas)
  07_tokens_llamadas.png         tokens medios y nº llamadas por modelo
  08_robustez.png                tasa de exito y fallbacks BSP por modelo
"""
from __future__ import annotations
import json, csv, statistics as st
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

EXP = Path("/Users/zhiqian/Desktop/Uni/TFGv2Z/scratch/experimento")
PLOTS = EXP / "plots"; PLOTS.mkdir(exist_ok=True)

rows = [json.loads(l) for l in (EXP / "results.jsonl").read_text().splitlines() if l.strip()]
MODELS = []
for r in rows:
    if r["model"] not in MODELS:
        MODELS.append(r["model"])
SHORT = {m: m.split("/")[-1] for m in MODELS}
PROMPTS = []
for r in rows:
    if r["prompt_key"] not in PROMPTS:
        PROMPTS.append(r["prompt_key"])

def by_model(key, only_ok=True):
    d = {}
    for m in MODELS:
        vals = [r.get(key) for r in rows if r["model"] == m
                and (r.get("status") == "ok" if only_ok else True)
                and isinstance(r.get(key), (int, float))]
        d[m] = vals
    return d

def ok_rate():
    d = {}
    for m in MODELS:
        rs = [r for r in rows if r["model"] == m]
        n_ok = sum(1 for r in rs if r.get("status") == "ok" and isinstance(r.get("overall"), (int, float)))
        d[m] = (n_ok, len(rs))
    return d

# ---- CSV resumen ----
with open(EXP / "results.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["model", "prompt", "status", "overall", "physical_total", "alexander_total",
                "appearance_total", "prompt_adherence_total", "total_tokens", "completion_tokens",
                "llm_calls", "wall_s", "llm_wait_s", "bsp_fallbacks", "fail_stage"])
    for r in rows:
        w.writerow([r["model"], r["prompt_key"], r["status"], r.get("overall"),
                    r.get("physical_total"), r.get("alexander_total"), r.get("appearance_total"),
                    r.get("prompt_adherence_total"), r.get("total_tokens"), r.get("completion_tokens"),
                    r.get("llm_calls"), r.get("wall_s"), r.get("llm_wait_s"),
                    r.get("bsp_fallbacks"), r.get("fail_stage")])

x = np.arange(len(MODELS))
labels = [SHORT[m] for m in MODELS]

# ---- 01 overall + tasa exito ----
ov = by_model("overall")
means = [st.mean(ov[m]) if ov[m] else 0 for m in MODELS]
sds = [st.pstdev(ov[m]) if len(ov[m]) > 1 else 0 for m in MODELS]
rate = ok_rate()
fig, ax = plt.subplots(figsize=(11, 6))
bars = ax.bar(x, means, yerr=sds, capsize=4, color="#4C72B0")
for i, m in enumerate(MODELS):
    n, tot = rate[m]
    ax.text(i, means[i] + (sds[i] or 0.01) + 0.01, f"{means[i]:.3f}\n{n}/{tot} ok",
            ha="center", va="bottom", fontsize=9)
ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20, ha="right")
ax.set_ylabel("composite overall (media ±dt, solo builds OK)")
ax.set_title("Calidad media por modelo y tasa de éxito")
ax.set_ylim(0, 1); ax.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(PLOTS / "01_overall_por_modelo.png", dpi=110); plt.close()

# ---- 02 familias apiladas ----
fam = ["physical_total", "alexander_total", "appearance_total"]
cols = ["#55A868", "#C44E52", "#8172B3"]
fig, ax = plt.subplots(figsize=(11, 6))
bottoms = np.zeros(len(MODELS))
for fk, c in zip(fam, cols):
    d = by_model(fk)
    # ponderar como en el evaluador (0.34/0.26/0.40) para ver contribucion al overall
    w = {"physical_total": 0.34, "alexander_total": 0.26, "appearance_total": 0.40}[fk]
    vals = [(st.mean(d[m]) if d[m] else 0) * w for m in MODELS]
    ax.bar(x, vals, bottom=bottoms, label=fk.replace("_total", "") + f" (×{w})", color=c)
    bottoms += np.array(vals)
ax.set_xticks(x); ax.set_xticklabels(labels, rotation=20, ha="right")
ax.set_ylabel("contribución ponderada al overall")
ax.set_title("Descomposición del overall por familia (physical/alexander/appearance)")
ax.legend(); ax.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(PLOTS / "02_familias_apiladas.png", dpi=110); plt.close()

# ---- 03 coste-calidad ----
fig, ax = plt.subplots(figsize=(10, 6))
cmap = plt.get_cmap("tab10")
for i, m in enumerate(MODELS):
    xs = [r["total_tokens"] for r in rows if r["model"] == m and isinstance(r.get("total_tokens"), (int, float)) and isinstance(r.get("overall"), (int, float))]
    ys = [r["overall"] for r in rows if r["model"] == m and isinstance(r.get("total_tokens"), (int, float)) and isinstance(r.get("overall"), (int, float))]
    ax.scatter(xs, ys, label=SHORT[m], color=cmap(i), s=60, alpha=0.8)
ax.set_xlabel("tokens totales por build"); ax.set_ylabel("composite overall")
ax.set_title("Coste (tokens) vs calidad"); ax.legend(fontsize=8); ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(PLOTS / "03_coste_calidad.png", dpi=110); plt.close()

# ---- 04 tiempo-calidad ----
fig, ax = plt.subplots(figsize=(10, 6))
for i, m in enumerate(MODELS):
    xs = [r["llm_wait_s"] for r in rows if r["model"] == m and isinstance(r.get("llm_wait_s"), (int, float)) and isinstance(r.get("overall"), (int, float))]
    ys = [r["overall"] for r in rows if r["model"] == m and isinstance(r.get("llm_wait_s"), (int, float)) and isinstance(r.get("overall"), (int, float))]
    ax.scatter(xs, ys, label=SHORT[m], color=cmap(i), s=60, alpha=0.8)
ax.set_xlabel("llm_wait_s por build (latencia acumulada)"); ax.set_ylabel("composite overall")
ax.set_title("Tiempo de LLM vs calidad"); ax.legend(fontsize=8); ax.grid(alpha=0.3)
fig.tight_layout(); fig.savefig(PLOTS / "04_tiempo_calidad.png", dpi=110); plt.close()

# ---- 05 heatmap modelo x prompt (overall) ----
M = np.full((len(MODELS), len(PROMPTS)), np.nan)
for r in rows:
    if isinstance(r.get("overall"), (int, float)):
        i = MODELS.index(r["model"]); j = PROMPTS.index(r["prompt_key"])
        M[i, j] = r["overall"]
fig, ax = plt.subplots(figsize=(13, 6))
im = ax.imshow(M, cmap="RdYlGn", vmin=0.4, vmax=0.95, aspect="auto")
ax.set_xticks(range(len(PROMPTS))); ax.set_xticklabels(PROMPTS, rotation=40, ha="right", fontsize=8)
ax.set_yticks(range(len(MODELS))); ax.set_yticklabels(labels, fontsize=9)
for i in range(len(MODELS)):
    for j in range(len(PROMPTS)):
        if not np.isnan(M[i, j]):
            ax.text(j, i, f"{M[i,j]:.2f}", ha="center", va="center", fontsize=7)
        else:
            ax.text(j, i, "✗", ha="center", va="center", fontsize=9, color="black")
fig.colorbar(im, label="overall"); ax.set_title("overall por modelo × prompt (✗ = fallo/sin score)")
fig.tight_layout(); fig.savefig(PLOTS / "05_heatmap_modelo_prompt.png", dpi=110); plt.close()

# ---- 06 heatmap modelo x metrica ----
METS = []
for r in rows:
    for k in (r.get("metrics") or {}):
        if k not in METS:
            METS.append(k)
METS.sort()
H = np.full((len(MODELS), len(METS)), np.nan)
for i, m in enumerate(MODELS):
    rs = [r for r in rows if r["model"] == m and r.get("metrics")]
    for j, met in enumerate(METS):
        vals = [r["metrics"][met] for r in rs if met in r["metrics"]]
        if vals:
            H[i, j] = st.mean(vals)
fig, ax = plt.subplots(figsize=(16, 6))
im = ax.imshow(H, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
ax.set_xticks(range(len(METS))); ax.set_xticklabels(METS, rotation=55, ha="right", fontsize=7)
ax.set_yticks(range(len(MODELS))); ax.set_yticklabels(labels, fontsize=9)
fig.colorbar(im, label="score medio"); ax.set_title("Score medio por modelo × métrica (18)")
fig.tight_layout(); fig.savefig(PLOTS / "06_heatmap_modelo_metrica.png", dpi=110); plt.close()

# ---- 07 tokens y llamadas ----
fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5))
tk = by_model("total_tokens"); cl = by_model("llm_calls", only_ok=False)
a1.bar(x, [st.mean(tk[m])/1000 if tk[m] else 0 for m in MODELS], color="#937860")
a1.set_xticks(x); a1.set_xticklabels(labels, rotation=20, ha="right"); a1.set_ylabel("tokens medios (k)")
a1.set_title("Tokens totales medios por build"); a1.grid(axis="y", alpha=0.3)
comp = by_model("completion_tokens")
a2.bar(x, [st.mean(comp[m]) if comp[m] else 0 for m in MODELS], color="#DA8BC3")
a2.set_xticks(x); a2.set_xticklabels(labels, rotation=20, ha="right"); a2.set_ylabel("completion tokens medios")
a2.set_title("Completion tokens (señal de razonamiento)"); a2.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(PLOTS / "07_tokens_llamadas.png", dpi=110); plt.close()

# ---- 08 robustez ----
fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 5))
rt = ok_rate()
a1.bar(x, [rt[m][0]/rt[m][1]*100 if rt[m][1] else 0 for m in MODELS], color="#4C72B0")
a1.set_xticks(x); a1.set_xticklabels(labels, rotation=20, ha="right"); a1.set_ylabel("% builds con score")
a1.set_title("Tasa de éxito"); a1.set_ylim(0, 100); a1.grid(axis="y", alpha=0.3)
bsp = by_model("bsp_fallbacks", only_ok=False)
a2.bar(x, [st.mean(bsp[m]) if bsp[m] else 0 for m in MODELS], color="#C44E52")
a2.set_xticks(x); a2.set_xticklabels(labels, rotation=20, ha="right"); a2.set_ylabel("fallbacks BSP medios/build")
a2.set_title("Fallbacks deterministas de floor_planner (↓ = más decide el LLM)"); a2.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(PLOTS / "08_robustez.png", dpi=110); plt.close()

# ---- resumen por consola ----
print(f"{'modelo':40} {'n_ok':>5} {'overall':>8} {'tokens':>9} {'wait_s':>8} {'bsp':>5}")
for m in MODELS:
    n, tot = rt[m]
    o = st.mean(ov[m]) if ov[m] else float('nan')
    t = st.mean(tk[m]) if tk[m] else float('nan')
    ws = by_model("llm_wait_s"); w = st.mean(ws[m]) if ws[m] else float('nan')
    b = st.mean(bsp[m]) if bsp[m] else float('nan')
    print(f"{SHORT[m]:40} {n}/{tot:>3} {o:8.3f} {t:9.0f} {w:8.1f} {b:5.1f}")
print("\nplots en", PLOTS)
