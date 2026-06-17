"""Report coverage statistics over rag/reference_buildings/processed/*.json.

Prints a Markdown table to stdout: style × category × size bucket counts,
plus license distribution and the populated-interior fraction.

Used at the end of each ingest iteration to decide whether the stop
criterion is met (≥50 buildings, ≥30 populated, ≥3 styles, ≥3 categories).

Usage:
    python tools/audit_dataset.py
    python tools/audit_dataset.py --json   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "rag" / "reference_buildings" / "processed"


def size_bucket(size: list[int]) -> str:
    vol = size[0] * size[1] * size[2]
    if vol < 1_000:
        return "xs(<1k)"
    if vol < 10_000:
        return "s(<10k)"
    if vol < 100_000:
        return "m(<100k)"
    if vol < 1_000_000:
        return "l(<1M)"
    return "xl(>=1M)"


def scan(processed_dir: Path) -> dict:
    docs: list[dict] = []
    for path in sorted(processed_dir.glob("*.json")):
        try:
            docs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as e:
            print(f"[audit] skip {path.name}: {e}", file=sys.stderr)

    style_x_cat: dict[tuple[str, str], int] = defaultdict(int)
    size_dist: Counter[str] = Counter()
    license_dist: Counter[str] = Counter()
    populated = 0
    for d in docs:
        cat = d.get("tags", {}).get("category", "?")
        for st in d.get("tags", {}).get("style", ["?"]):
            style_x_cat[(st, cat)] += 1
        size_dist[size_bucket(d["bounding_box"]["size"])] += 1
        license_dist[d.get("license", "?")] += 1
        if d.get("metadata_quality", {}).get("interior_populated"):
            populated += 1

    styles = sorted({st for st, _ in style_x_cat})
    cats = sorted({c for _, c in style_x_cat})

    return {
        "total": len(docs),
        "populated": populated,
        "populated_frac": (populated / len(docs)) if docs else 0.0,
        "styles_distinct": len(styles),
        "categories_distinct": len(cats),
        "size_dist": dict(size_dist),
        "license_dist": dict(license_dist),
        "style_x_cat": {f"{st}|{cat}": n for (st, cat), n in style_x_cat.items()},
        "styles": styles,
        "categories": cats,
    }


def stop_criterion(report: dict) -> tuple[bool, str]:
    """Return (met, reason)."""
    if report["total"] < 50:
        return False, f"total={report['total']} < 50"
    if report["populated"] < 30:
        return False, f"populated={report['populated']} < 30"
    if report["styles_distinct"] < 3:
        return False, f"styles={report['styles_distinct']} < 3"
    if report["categories_distinct"] < 3:
        return False, f"categories={report['categories_distinct']} < 3"
    return True, "minimum viable reached"


def print_markdown(report: dict) -> None:
    print(f"# RAG-E audit\n")
    print(f"- total: **{report['total']}**")
    print(f"- populated interiors: **{report['populated']}** ({report['populated_frac']:.1%})")
    print(f"- distinct styles: {report['styles_distinct']}")
    print(f"- distinct categories: {report['categories_distinct']}")
    print()
    print("## Style × Category")
    cats = report["categories"]
    print("| style \\ category | " + " | ".join(cats) + " |")
    print("|" + "---|" * (len(cats) + 1))
    for st in report["styles"]:
        row = [st] + [str(report["style_x_cat"].get(f"{st}|{c}", 0)) for c in cats]
        print("| " + " | ".join(row) + " |")
    print()
    print("## Size distribution")
    for k, v in sorted(report["size_dist"].items()):
        print(f"- {k}: {v}")
    print()
    print("## License distribution")
    for k, v in sorted(report["license_dist"].items()):
        print(f"- {k}: {v}")
    print()
    met, reason = stop_criterion(report)
    print(f"\n**Stop criterion**: {'MET' if met else 'NOT MET'} — {reason}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true")
    p.add_argument("--dir", type=Path, default=PROCESSED_DIR)
    args = p.parse_args(argv)

    report = scan(args.dir)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_markdown(report)

    met, _ = stop_criterion(report)
    return 0 if met else 1


if __name__ == "__main__":
    sys.exit(main())
