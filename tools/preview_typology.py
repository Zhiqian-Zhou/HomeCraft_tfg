"""CLI smoke harness for typology builders.

Usage:
    python3 tools/preview_typology.py <name> [--style medieval] [--size large]
    python3 tools/preview_typology.py norman_keep
    python3 tools/preview_typology.py norman_keep --style gothic --size monumental

Builds a synthetic AABB matching the typology's `typical_footprint`, calls
`build()`, runs the composer, writes a schema-valid ReferenceBuilding JSON
to `scratch/typology_previews/<name>__<style>__<size>.json`, and prints a
short sanity report (op count, voxel count, palette size, distinct blocks).

Reuses helpers from `pipeline.skills.preview` so the output JSON drops
straight into the same viewer pipeline used for atomic-skill previews.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.skills.base import AABB, Materials                       # noqa: E402
from pipeline.skills.composer import compose                           # noqa: E402
from pipeline.skills.preview import (                                   # noqa: E402
    _bare, _has_furniture, _count_furniture_voxels, _now_iso,
    _STYLE_ENUM,
)
from pipeline.skills.typologies import (                                # noqa: E402
    get_metadata, get_typology, list_typologies,
)


# Larger size buckets than the atomic-skill SIZES — typologies (towers,
# roofs) need vertical room. `monumental` matches typical_footprint for
# the biggest typologies (Norman keep, campanile, minaret).
TYPOLOGY_SIZES = {
    "small":      AABB(0, 0, 0,  8, 12,  8),
    "medium":     AABB(0, 0, 0, 11, 18, 11),
    "large":      AABB(0, 0, 0, 14, 28, 14),
    "monumental": AABB(0, 0, 0, 18, 40, 18),
}

PREVIEWS_DIR = REPO_ROOT / "scratch" / "typology_previews"


def export_typology(name: str, *, style: str = "medieval",
                    size: str = "large",
                    out_dir: Path = PREVIEWS_DIR) -> tuple[Path, dict]:
    """Run the typology, compose, write JSON. Returns (path, sanity_report)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    aabb = TYPOLOGY_SIZES.get(size, TYPOLOGY_SIZES["large"])
    meta = get_metadata(name)
    materials = Materials.for_style(style)
    build = get_typology(name)

    ops = build(aabb=aabb, materials=materials, style=style)
    if not ops:
        raise ValueError(f"typology '{name}' returned no ops")

    voxels, palette, (W, H, D), _origin = compose(ops, materials)
    if not voxels:
        raise ValueError(f"typology '{name}' produced zero voxels after compose")

    doc = {
        "id": f"typo-{name}-{style}-{size}",
        "source": "synthetic",
        "source_url": f"https://homecraft.tfg/typology/{name}",
        "license": "MIT",
        "license_notes": f"typology preview: pipeline/skills/typologies/{name}.py",
        "title": f"{meta.title} ({style}, {size})",
        "tags": {
            "category": "tower" if meta.kind == "tower" else "other",
            "style": [style if style in _STYLE_ENUM else "other"],
        },
        "bounding_box": {"size": [W, H, D]},
        "block_palette": palette,
        "voxels": voxels,
        "bot_decomposition": None,
        "metadata_quality": {
            "interior_populated": _has_furniture(palette),
            "has_labels": False,
            "furniture_blocks": _count_furniture_voxels(voxels, palette),
            "ingest_warnings": ["typology_preview"],
        },
        "ingest": {
            "tool": "tools.preview_typology",
            "tool_version": "0.1.0",
            "source_format": "other",
            "ingested_at": _now_iso(),
            "ingester_path": __file__,
        },
    }
    out_path = out_dir / f"{name}__{style}__{size}.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                        encoding="utf-8")

    distinct_bare = {_bare(b) for b in palette.values()}
    report = {
        "ops": len(ops),
        "voxels": len(voxels),
        "palette_size": len(palette),
        "distinct_bare_blocks": len(distinct_bare),
        "size_WHD": [W, H, D],
        "bare_blocks": sorted(distinct_bare),
    }
    return out_path, report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("name", nargs="?", help="typology module name, e.g. 'norman_keep'")
    p.add_argument("--style", default="medieval", help="material style preset")
    p.add_argument("--size",  default="large",
                   choices=list(TYPOLOGY_SIZES.keys()))
    p.add_argument("--list", action="store_true", help="list available typologies and exit")
    args = p.parse_args(argv)

    if args.list:
        names = list_typologies()
        if not names:
            print("(no typologies registered yet)")
        for n in names:
            try:
                m = get_metadata(n)
                print(f"  {n:25s}  {m.kind:8s}  {m.title}")
            except Exception as e:
                print(f"  {n:25s}  ERROR: {e}")
        return 0

    if not args.name:
        p.error("typology name is required (or use --list)")

    path, report = export_typology(args.name, style=args.style, size=args.size)
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    print(f"  ops={report['ops']}  voxels={report['voxels']}  "
          f"palette={report['palette_size']}  bare_blocks={report['distinct_bare_blocks']}  "
          f"size(WHD)={report['size_WHD']}")
    print("  blocks: " + ", ".join(report["bare_blocks"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
