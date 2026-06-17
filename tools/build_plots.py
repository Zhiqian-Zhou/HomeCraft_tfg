"""Generate the five PDF plots used in the thesis.

Reads:
  - scratch/experimento/results.csv      (per-build CSV: model, prompt, status, scores, cost)
  - scratch/experimento/stats_5fam.json  (per-model summary: families, completion, n_ok)
  - output/gym/history.json              (iterative trajectory)

Writes:
  - plots/composite_by_model.pdf
  - plots/per_family_by_model.pdf
  - plots/cost_vs_quality.pdf
  - plots/completion_rate.pdf
  - plots/gym_trajectory.pdf
"""

import csv
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "scratch" / "experimento"
GYM_HIST = ROOT / "output" / "gym" / "history.json"
PLOTS = ROOT / "plots"
PLOTS.mkdir(parents=True, exist_ok=True)

# Okabe-Ito colourblind-safe palette
PALETTE = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#F0E442"]

plt.rcParams.update({
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
    "font.family": "serif",
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.5,
})


def short_name(model: str) -> str:
    """Convert OpenRouter model ID into a short display name."""
    mapping = {
        "qwen/qwen3.5-35b-a3b": "Qwen3.5-35B",
        "meta-llama/llama-4-scout": "Llama-4-Scout",
        "google/gemma-4-31b-it": "Gemma-4-31B",
        "google/gemma-4-26b-a4b-it": "Gemma-4-26B",
        "qwen/qwen3.5-9b": "Qwen3.5-9B",
        "meta-llama/llama-3.3-70b-instruct": "Llama-3.3-70B",
    }
    return mapping.get(model, model.split("/")[-1])


def load_stats():
    with open(EXP / "stats_5fam.json") as f:
        return json.load(f)


def load_csv():
    rows = []
    with open(EXP / "results.csv") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def fig_composite_by_model(stats):
    """Bar chart of mean composite score by model, sorted descending."""
    items = []
    for model, info in stats["summary"].items():
        mean = info["families"]["overall"]["mean"]
        hi = info["families"]["overall"]["hi"]
        lo = info["families"]["overall"]["lo"]
        items.append((short_name(model), mean, hi - mean, mean - lo))
    items.sort(key=lambda x: x[1], reverse=True)
    names = [x[0] for x in items]
    means = [x[1] for x in items]
    err_lo = [x[3] for x in items]
    err_hi = [x[2] for x in items]

    fig, ax = plt.subplots(figsize=(6.5, 3.6), constrained_layout=True)
    bars = ax.bar(names, means, color=PALETTE[:len(names)], width=0.65,
                  edgecolor="black", linewidth=0.4)
    ax.errorbar(names, means, yerr=[err_lo, err_hi], fmt="none",
                ecolor="black", capsize=3, linewidth=0.7)
    for bar, m in zip(bars, means):
        ax.text(bar.get_x() + bar.get_width() / 2, m + 0.012,
                f"{m:.3f}", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("Mean composite score")
    ax.set_ylim(0, max(means) * 1.20)
    ax.tick_params(axis="x", rotation=15)
    fig.savefig(PLOTS / "composite_by_model.pdf", bbox_inches="tight")
    plt.close(fig)


def fig_per_family_by_model(stats):
    """Grouped bar chart of per-family scores per model."""
    families = ["physical_total", "alexander_total",
                "interior_total", "exterior_total", "prompt_adherence_total"]
    labels = ["Physical", "Alexander", "Interior", "Exterior", "Prompt"]
    # Order models by overall mean descending
    ordered = sorted(stats["summary"].items(),
                     key=lambda kv: kv[1]["families"]["overall"]["mean"],
                     reverse=True)
    model_names = [short_name(m) for m, _ in ordered]
    n_models = len(ordered)
    n_fams = len(families)
    x = np.arange(n_models)
    width = 0.16
    fig, ax = plt.subplots(figsize=(7.5, 3.8), constrained_layout=True)
    for j, (fam, label) in enumerate(zip(families, labels)):
        means = [info["families"][fam]["mean"] for _, info in ordered]
        ax.bar(x + (j - (n_fams - 1) / 2) * width, means, width,
               label=label, color=PALETTE[j], edgecolor="black", linewidth=0.3)
    ax.set_ylabel("Mean family score")
    ax.set_xticks(x)
    ax.set_xticklabels(model_names, rotation=15)
    ax.set_ylim(0, 1.0)
    ax.legend(ncol=5, fontsize=8, loc="upper center",
              bbox_to_anchor=(0.5, 1.13), frameon=False)
    fig.savefig(PLOTS / "per_family_by_model.pdf", bbox_inches="tight")
    plt.close(fig)


def fig_cost_vs_quality(stats, csv_rows):
    """Scatter of mean tokens per build vs composite score."""
    # Compute mean token count per model from CSV (only ok rows)
    tok = {}
    for row in csv_rows:
        if row["status"] != "ok":
            continue
        try:
            t = int(row["total_tokens"])
        except (ValueError, KeyError):
            continue
        tok.setdefault(row["model"], []).append(t)
    pts = []
    for model, info in stats["summary"].items():
        if model not in tok:
            continue
        mean_tokens = sum(tok[model]) / len(tok[model])
        score = info["families"]["overall"]["mean"]
        pts.append((short_name(model), mean_tokens, score))
    fig, ax = plt.subplots(figsize=(6.5, 4.2), constrained_layout=True)
    for i, (name, tk, sc) in enumerate(pts):
        ax.scatter(tk / 1000, sc, s=110, color=PALETTE[i],
                   edgecolor="black", linewidth=0.5, zorder=3)
        ax.annotate(name, (tk / 1000, sc),
                    xytext=(8, 4), textcoords="offset points", fontsize=9)
    ax.set_xlabel("Mean cost (thousand tokens per build)")
    ax.set_ylabel("Mean composite score")
    ax.set_xlim(left=0)
    fig.savefig(PLOTS / "cost_vs_quality.pdf", bbox_inches="tight")
    plt.close(fig)


def fig_completion_rate(stats):
    """Bar chart of completion rate per model."""
    ordered = sorted(stats["summary"].items(),
                     key=lambda kv: kv[1]["n_ok"] / kv[1]["n_total"],
                     reverse=True)
    names = [short_name(m) for m, _ in ordered]
    rates = [info["n_ok"] / info["n_total"] for _, info in ordered]
    fig, ax = plt.subplots(figsize=(6.5, 3.4), constrained_layout=True)
    bars = ax.bar(names, rates, color=PALETTE[:len(names)], width=0.65,
                  edgecolor="black", linewidth=0.4)
    for bar, r in zip(bars, rates):
        ax.text(bar.get_x() + bar.get_width() / 2, r + 0.018,
                f"{r * 100:.0f}\\%", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("Completion rate")
    ax.set_ylim(0, 1.10)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.tick_params(axis="x", rotation=15)
    fig.savefig(PLOTS / "completion_rate.pdf", bbox_inches="tight")
    plt.close(fig)


def fig_gym_trajectory():
    """Line plot of the iterative trajectory."""
    with open(GYM_HIST) as f:
        hist = json.load(f)
    iters = [h["iter"] for h in hist]
    mean = [h["mean_score"] for h in hist]
    mn = [h["min_score"] for h in hist]
    mx = [h["max_score"] for h in hist]
    # peak iteration (by mean)
    peak_idx = int(np.argmax(mean))
    peak_iter = iters[peak_idx]
    peak_mean = mean[peak_idx]
    fig, ax = plt.subplots(figsize=(7.0, 3.6), constrained_layout=True)
    ax.fill_between(iters, mn, mx, color=PALETTE[0], alpha=0.20,
                    linewidth=0, label="min to max")
    ax.plot(iters, mean, color=PALETTE[0], linewidth=1.4, label="mean")
    ax.axhline(0.80, color="gray", linestyle="--", linewidth=0.7,
               label="convergence target")
    ax.axvline(peak_iter, color="black", linestyle=":", linewidth=0.7,
               label=f"peak (iter {peak_iter}, mean {peak_mean:.3f})")
    ax.set_xlabel("Iteration")
    ax.set_ylabel("Composite score")
    ax.set_ylim(0, 1.0)
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    fig.savefig(PLOTS / "gym_trajectory.pdf", bbox_inches="tight")
    plt.close(fig)


def fig_style_category_coverage():
    """Heatmap showing which prompt covers which style x category pair."""
    styles = ["Medieval", "Mediterranean", "Modern", "Fantasy",
              "Japanese", "Chinese", "Gothic", "Renaissance",
              "Rustic", "Tropical"]
    categories = ["Residential", "Civic", "Religious", "Leisure"]
    # Coverage matrix (rows = styles, cols = categories)
    M = np.zeros((len(styles), len(categories)))
    coverage = [
        ("Medieval", "Residential"),
        ("Mediterranean", "Residential"),
        ("Modern", "Residential"),
        ("Fantasy", "Civic"),
        ("Japanese", "Religious"),
        ("Chinese", "Civic"),
        ("Gothic", "Religious"),
        ("Renaissance", "Civic"),
        ("Rustic", "Leisure"),
        ("Tropical", "Residential"),
    ]
    for s, c in coverage:
        M[styles.index(s), categories.index(c)] = 1
    fig, ax = plt.subplots(figsize=(5.5, 4.4), constrained_layout=True)
    ax.imshow(M, cmap="Blues", vmin=0, vmax=1.5, aspect="auto")
    ax.set_xticks(range(len(categories))); ax.set_xticklabels(categories)
    ax.set_yticks(range(len(styles)));     ax.set_yticklabels(styles)
    for i in range(len(styles)):
        for j in range(len(categories)):
            if M[i, j] > 0:
                ax.text(j, i, "X", ha="center", va="center",
                        fontsize=10, color="#0b3d6b")
    ax.set_xlabel("Functional category")
    ax.set_ylabel("Architectural style")
    fig.savefig(PLOTS / "style_category_coverage.pdf", bbox_inches="tight")
    plt.close(fig)


def main():
    stats = load_stats()
    csv_rows = load_csv()
    fig_composite_by_model(stats)
    fig_per_family_by_model(stats)
    fig_cost_vs_quality(stats, csv_rows)
    fig_completion_rate(stats)
    fig_gym_trajectory()
    fig_style_category_coverage()
    print(f"Generated 6 plots in {PLOTS}")


if __name__ == "__main__":
    main()
