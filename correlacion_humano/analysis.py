#!/usr/bin/env python3
"""Validacion del evaluador automatico frente al juicio humano.

Reproduce el analisis del estudio final (13 jugadores anonimizados P01..P13,
20 escenas, 6 preguntas 1-10) que valida las 5 familias del evaluador
automatico (+ compuesta) contra el consenso humano.

Entradas (mismo directorio):
  - human_ratings.csv : rater,scene_num,key,q1..q6,seconds  (datos crudos, anonimos)
  - auto_scores.csv   : scene_num,type_style,key,fisicas,interior,exterior,
                        alexander,prompt,compuesta           (exterior n/a -> 0)

Salida: imprime por consola la diagonal pregunta-familia (Pearson/Spearman),
las correlaciones agregadas, el acuerdo inter-evaluador, la fiabilidad de
Spearman-Brown, la curva de convergencia por numero de evaluadores, la robustez
ante exclusion de evaluadores y la deteccion de atipicos (z-score modificado).

Uso:  python3 analysis.py
Requiere: numpy, scipy.
"""
import csv
import os
from itertools import combinations

import numpy as np
from scipy.stats import pearsonr, spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))

# pregunta humana  ->  familia automatica que pretende medir lo mismo
DIAG = [
    ("q1", "compuesta", "Overall / Composite"),
    ("q2", "fisicas", "Solidity / Physical"),
    ("q3", "interior", "Interior"),
    ("q4", "exterior", "Exterior"),
    ("q5", "alexander", "Sense of place / Alexander"),
    ("q6", "prompt", "Fidelity / Prompt"),
]
QS = ["q1", "q2", "q3", "q4", "q5", "q6"]
FAMS = ["fisicas", "interior", "exterior", "alexander", "prompt"]


def load():
    auto = {}
    with open(os.path.join(HERE, "auto_scores.csv")) as f:
        for r in csv.DictReader(f):
            n = int(r["scene_num"])
            auto[n] = {k: float(r[k]) for k in
                       ["fisicas", "interior", "exterior", "alexander", "prompt", "compuesta"]}
    human = {}  # rater -> scene_num -> {q: value}
    with open(os.path.join(HERE, "human_ratings.csv")) as f:
        for r in csv.DictReader(f):
            human.setdefault(r["rater"], {})[int(r["scene_num"])] = {q: float(r[q]) for q in QS}
    return auto, human


def scenes_sorted(auto):
    return sorted(auto)


def human_mean_per_scene(human, raters, scenes):
    """media por escena y pregunta sobre el subconjunto `raters`."""
    out = {}
    for s in scenes:
        out[s] = {q: np.mean([human[r][s][q] for r in raters]) for q in QS}
    return out


def diag_correlations(auto, hmean, scenes):
    rows = []
    for q, fam, name in DIAG:
        h = [hmean[s][q] for s in scenes]
        a = [auto[s][fam] for s in scenes]
        pr, pp = pearsonr(h, a)
        sr, sp = spearmanr(h, a)
        rows.append((name, q, fam, pr, pp, sr, sp))
    return rows


def aggregates(auto, hmean, scenes):
    # media humana de las 6 preguntas por escena
    hbar = [np.mean([hmean[s][q] for q in QS]) for s in scenes]
    comp = [auto[s]["compuesta"] for s in scenes]
    mbar = [np.mean([auto[s][f] for f in FAMS]) for s in scenes]
    q1 = [hmean[s]["q1"] for s in scenes]
    res = {}
    res["q1_vs_composite"] = pearsonr(q1, comp)
    res["humanmean_vs_composite"] = pearsonr(hbar, comp)
    res["humanmean_vs_metricmean"] = pearsonr(hbar, mbar)
    return res


def interrater(human, raters, scenes):
    """acuerdo medio entre pares POR PREGUNTA: para cada pregunta se correlaciona
    el vector de 20 escenas de cada pareja de evaluadores, y se promedia sobre
    todas las parejas y las 6 preguntas. Da el r1 que alimenta Spearman-Brown."""
    rs = []
    for q in QS:
        vecs = {r: np.array([human[r][s][q] for s in scenes]) for r in raters}
        for a, b in combinations(raters, 2):
            va, vb = vecs[a], vecs[b]
            if np.std(va) > 0 and np.std(vb) > 0:
                rs.append(pearsonr(va, vb)[0])
    return float(np.mean(rs))


def spearman_brown(k, rbar):
    return k * rbar / (1 + (k - 1) * rbar)


def k_for(target, rbar):
    import math
    return math.ceil(target * (1 - rbar) / (rbar * (1 - target)))


def consensus_agreement(human, raters, scenes):
    """para cada evaluador: correlacion de su media-por-escena con la del resto."""
    permean = {r: np.array([np.mean([human[r][s][q] for q in QS]) for s in scenes]) for r in raters}
    out = {}
    for r in raters:
        rest = [permean[o] for o in raters if o != r]
        consensus = np.mean(rest, axis=0)
        out[r] = pearsonr(permean[r], consensus)[0]
    return out


def modified_zscore(values):
    """z-score modificado (mediana/MAD), robusto. |z|>3.5 = atipico."""
    v = np.array(values)
    med = np.median(v)
    mad = np.median(np.abs(v - med))
    if mad == 0:
        return np.zeros_like(v)
    return 0.6745 * (v - med) / mad


def main():
    auto, human = load()
    scenes = scenes_sorted(auto)
    raters = sorted(human)
    print(f"Raters: {len(raters)} ({', '.join(raters)})   Scenes: {len(scenes)}\n")

    hmean = human_mean_per_scene(human, raters, scenes)

    print("== Diagonal: human question vs matching automatic family (n=20) ==")
    print(f"{'pairing':32s} {'Pearson':>8} {'p':>8} {'Spearman':>9} {'p':>8}  sig")
    for name, q, fam, pr, pp, sr, sp in diag_correlations(auto, hmean, scenes):
        sig = "yes" if pp < 0.05 and sp < 0.05 else ("Pearson" if pp < 0.05 else "no")
        print(f"{q+' '+fam:32s} {pr:8.3f} {pp:8.3f} {sr:9.3f} {sp:8.3f}  {sig}")

    print("\n== Aggregate correlations ==")
    for k, (r, p) in aggregates(auto, hmean, scenes).items():
        print(f"  {k:28s} Pearson {r:.3f} (p={p:.4f})")

    rbar = interrater(human, raters, scenes)
    print(f"\n== Inter-rater agreement ==\n  mean pairwise Pearson  r1 = {rbar:.3f}")
    print(f"  Spearman-Brown reliability of the {len(raters)}-rater mean: "
          f"R = {spearman_brown(len(raters), rbar):.3f}")
    print("  raters needed for each reliability band (Spearman-Brown):")
    for t in (0.70, 0.80, 0.90):
        print(f"    R={t:.2f} -> k = {k_for(t, rbar)}")

    print("\n== Convergence (cumulative mean of first n raters, Pearson) ==")
    print(f"  {'metric':12s}" + "".join(f"{('n='+str(n)):>9}" for n in (1, 4, 6, 10, len(raters))))
    for q, fam, name in DIAG:
        line = f"  {fam:12s}"
        for n in (1, 4, 6, 10, len(raters)):
            hm = human_mean_per_scene(human, raters[:n], scenes)
            r = pearsonr([hm[s][q] for s in scenes], [auto[s][fam] for s in scenes])[0]
            line += f"{r:9.3f}"
        print(line)

    print("\n== Robustness (aggregate human-mean vs metric-mean) ==")
    for label, drop in [("all 13", []), ("drop P07", ["P07"]),
                        ("drop P07/P01/P08", ["P07", "P01", "P08"])]:
        rs = [r for r in raters if r not in drop]
        hm = human_mean_per_scene(human, rs, scenes)
        hbar = [np.mean([hm[s][q] for q in QS]) for s in scenes]
        mbar = [np.mean([auto[s][f] for f in FAMS]) for s in scenes]
        print(f"  {label:18s} (n_raters={len(rs)})  r = {pearsonr(hbar, mbar)[0]:.3f}")

    print("\n== Outlier detection (modified z-score on consensus agreement) ==")
    agr = consensus_agreement(human, raters, scenes)
    order = sorted(raters, key=lambda r: -agr[r])
    z = dict(zip(order, modified_zscore([agr[r] for r in order])))
    print(f"  {'rater':6s} {'agreement':>10} {'mod-z':>8}  outlier(|z|>3.5)")
    for r in order:
        print(f"  {r:6s} {agr[r]:10.3f} {z[r]:8.2f}  {'YES' if abs(z[r])>3.5 else 'no'}")
    n_out = sum(abs(z[r]) > 3.5 for r in raters)
    print(f"  -> {n_out} outliers; {len(raters)-n_out} raters retained")


if __name__ == "__main__":
    main()
