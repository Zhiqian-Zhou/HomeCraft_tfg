#!/usr/bin/env python3
"""Análisis del experimento multi-LLM DE-CONTAMINADO vs CONTAMINADO.

Lee results_decon.jsonl (pipeline sin fallbacks) y, si existe, results.jsonl
(pipeline contaminado) para comparar:
  - tasa de completado por modelo (decon vs contaminado)
  - desglose de etapa de fallo (decon)
  - calidad limpia (overall) en los builds que completan
  - tokens / tiempo

Genera plots en plots_decon/ y un resumen por consola.
"""
from __future__ import annotations
import json, collections, statistics as st
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

EXP = Path("/Users/zhiqian/Desktop/Uni/TFGv2Z/scratch/experimento")
PLOTS = EXP / "plots_decon"; PLOTS.mkdir(exist_ok=True)

def load(p):
    f = EXP / p
    if not f.exists():
        return []
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]

decon = load("results_decon.jsonl")
contam = load("results.jsonl")

MODELS = []
for r in decon:
    if r["model"] not in MODELS:
        MODELS.append(r["model"])
SHORT = {m: m.split("/")[-1] for m in MODELS}

def ok_rate(rows):
    d = {}
    for m in MODELS:
        rs = [r for r in rows if r["model"] == m]
        n_ok = sum(1 for r in rs if r.get("status") == "ok"
                   and isinstance(r.get("overall"), (int, float)))
        d[m] = (n_ok, len(rs))
    return d

def mean_overall(rows):
    d = {}
    for m in MODELS:
        vs = [r["overall"] for r in rows if r["model"] == m
              and isinstance(r.get("overall"), (int, float))]
        d[m] = st.mean(vs) if vs else float("nan")
    return d

rd, rc = ok_rate(decon), ok_rate(contam)
od, oc = mean_overall(decon), mean_overall(contam)

# fail-stage breakdown (decon)
stages = collections.Counter()
for r in decon:
    if r.get("status") != "ok":
        stages[r.get("fail_stage") or r.get("status")] += 1

print("\n=== TASA DE COMPLETADO: contaminado → de-contaminado ===")
print(f"{'modelo':30}{'contam':>14}{'decon':>14}{'overall_decon':>14}")
for m in MODELS:
    cok = f"{rc.get(m,(0,0))[0]}/{rc.get(m,(0,0))[1]}" if m in rc else "—"
    dok = f"{rd[m][0]}/{rd[m][1]}"
    ov = od[m]
    print(f"{SHORT[m]:30}{cok:>14}{dok:>14}{(f'{ov:.3f}' if ov==ov else '—'):>14}")

print("\n=== ETAPA DE FALLO (de-contaminado) ===")
for s, n in stages.most_common():
    print(f"  {s or '?':28} {n}")

# Plot 1: completion rate decon vs contam
x = np.arange(len(MODELS)); w = 0.38
fig, ax = plt.subplots(figsize=(12, 6))
ax.bar(x - w/2, [rc.get(m,(0,1))[0]/max(rc.get(m,(0,1))[1],1)*100 for m in MODELS],
       w, label="contaminado (con fallbacks)", color="#bbbbbb")
ax.bar(x + w/2, [rd[m][0]/max(rd[m][1],1)*100 for m in MODELS],
       w, label="de-contaminado (sin fallbacks)", color="#C44E52")
ax.set_xticks(x); ax.set_xticklabels([SHORT[m] for m in MODELS], rotation=20, ha="right")
ax.set_ylabel("% builds completados"); ax.set_ylim(0, 100)
ax.set_title("Tasa de completado: contaminado vs de-contaminado")
ax.legend(); ax.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(PLOTS / "01_completion_decon_vs_contam.png", dpi=110); plt.close()

# Plot 2: fail-stage pie
if stages:
    fig, ax = plt.subplots(figsize=(8, 6))
    labels = [str(s) for s, _ in stages.most_common()]
    sizes = [n for _, n in stages.most_common()]
    ax.pie(sizes, labels=labels, autopct=lambda p: f"{p*sum(sizes)/100:.0f}", startangle=90)
    ax.set_title("Etapa de fallo (pipeline de-contaminado)")
    fig.tight_layout(); fig.savefig(PLOTS / "02_fail_stage.png", dpi=110); plt.close()

# Plot 3: clean overall on completed builds
fig, ax = plt.subplots(figsize=(12, 6))
ax.bar(x - w/2, [oc.get(m, 0) if oc.get(m, 0)==oc.get(m, 0) else 0 for m in MODELS],
       w, label="contaminado", color="#bbbbbb")
ax.bar(x + w/2, [od[m] if od[m]==od[m] else 0 for m in MODELS],
       w, label="de-contaminado", color="#4C72B0")
ax.set_xticks(x); ax.set_xticklabels([SHORT[m] for m in MODELS], rotation=20, ha="right")
ax.set_ylabel("overall medio (builds OK)"); ax.set_ylim(0, 1)
ax.set_title("Calidad media: contaminado vs de-contaminado (solo builds completados)")
ax.legend(); ax.grid(axis="y", alpha=0.3)
fig.tight_layout(); fig.savefig(PLOTS / "03_quality_decon_vs_contam.png", dpi=110); plt.close()

print("\nplots en", PLOTS)
