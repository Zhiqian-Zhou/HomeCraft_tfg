"""Convert the HuggingFace dataset `lvnvceo/mc-schematics` example JSON
into a canonical ReferenceBuilding JSON in `rag/reference_buildings/processed/`.

Dataset URL:   https://huggingface.co/datasets/lvnvceo/mc-schematics
License:       CC-BY-NC-4.0  (research-use only; flagged in manifest)

Input shape (see scratch/lvnvceo_format.md for the full write-up):
```
{
  "dimensions": [W, H, D],
  "blocks": [
    { "position": [x, y, z], "block_type": "(minecraft:<id>)" },
    ...
  ]
}
```

Block IDs in the example use **pre-flattening 1.12-era names**
(`grass`, `planks`, `double_stone_slab`, `red_flower`, ...). We remap
to 1.16.5 namespaced IDs through `PRE_FLATTENING_REMAP`.

The example.json fits comfortably under the 64³/100k-voxel "building
region" target (dims 62x27x57, 12,109 non-air voxels), so we ingest it
as a single ReferenceBuilding.

Usage:
    python tools/ingest_lvnvceo.py \
        --input rag/reference_buildings/raw/hf_lvnvceo/example.json

Optional:
    --limit-blocks N    process only first N blocks (smoke test)
    --id-suffix STR     override the default building id stem
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    PROCESSED_DIR,
    RAW_DIR,
    _is_air,
    append_manifest,
    append_processing_log,
    compress_palette,
    now_iso,
    populated_interior_metrics,
    slugify,
)


SOURCE_URL = "https://huggingface.co/datasets/lvnvceo/mc-schematics"
LICENSE = "CC-BY-NC"  # CC-BY-NC-4.0 — schema enum stores the unversioned slug
LICENSE_NOTES = (
    "CC-BY-NC-4.0 (HF dataset card metadata). Research/non-commercial use "
    "only. Attribute lvnvceo/mc-schematics on any downstream artifact."
)


# Pre-flattening 1.12-era IDs → 1.16.5 namespaced.
# Only includes IDs we actually saw in the example; anything else falls
# back to `minecraft:stone` and the fallback is recorded as a warning.
PRE_FLATTENING_REMAP: dict[str, str] = {
    "minecraft:stone": "minecraft:stone",
    "minecraft:dirt": "minecraft:dirt",
    "minecraft:grass": "minecraft:grass_block",
    "minecraft:double_stone_slab": "minecraft:smooth_stone",
    "minecraft:sandstone": "minecraft:sandstone",
    "minecraft:stone_slab": "minecraft:smooth_stone_slab",
    "minecraft:cobblestone": "minecraft:cobblestone",
    "minecraft:gravel": "minecraft:gravel",
    "minecraft:torch": "minecraft:torch",
    "minecraft:netherrack": "minecraft:netherrack",
    "minecraft:ladder": "minecraft:ladder",
    "minecraft:stone_stairs": "minecraft:cobblestone_stairs",
    "minecraft:planks": "minecraft:oak_planks",
    "minecraft:fence": "minecraft:oak_fence",
    "minecraft:tallgrass": "minecraft:grass",
    "minecraft:log": "minecraft:oak_log",
    "minecraft:wall_sign": "minecraft:oak_wall_sign",
    "minecraft:red_flower": "minecraft:poppy",
    "minecraft:yellow_flower": "minecraft:dandelion",
    "minecraft:sand": "minecraft:sand",
    "minecraft:crafting_table": "minecraft:crafting_table",
    # Common pre-flat IDs we may see elsewhere in the corpus:
    "minecraft:wood": "minecraft:oak_log",
    "minecraft:leaves": "minecraft:oak_leaves",
    "minecraft:wooden_door": "minecraft:oak_door",
    "minecraft:wooden_slab": "minecraft:oak_slab",
    "minecraft:wooden_stairs": "minecraft:oak_stairs",
    "minecraft:standing_sign": "minecraft:oak_sign",
    "minecraft:bed": "minecraft:red_bed",
    "minecraft:water": "minecraft:water",
    "minecraft:flowing_water": "minecraft:water",
    "minecraft:lava": "minecraft:lava",
    "minecraft:flowing_lava": "minecraft:lava",
    "minecraft:air": "minecraft:air",
}


_BLOCK_TYPE_RE = re.compile(r"^\(?(minecraft:[a-z0-9_]+)\)?$")


def parse_block_type(raw: str) -> str | None:
    """Strip the literal parens and return the canonical pre-flat id."""
    if not isinstance(raw, str):
        return None
    m = _BLOCK_TYPE_RE.match(raw.strip())
    if not m:
        return None
    return m.group(1)


def remap(pre_flat_id: str) -> tuple[str, bool]:
    """Return (modern_id, fallback_used)."""
    if pre_flat_id in PRE_FLATTENING_REMAP:
        return PRE_FLATTENING_REMAP[pre_flat_id], False
    # Unknown ID — keep namespace, fall back to stone for safety so palette
    # never holds an unmappable string. Record the warning.
    return "minecraft:stone", True


def build_document(
    *,
    raw: dict,
    source_path: Path,
    building_id: str,
    title: str,
    description: str,
    category: str,
    style: list[str],
    limit_blocks: int | None,
) -> tuple[dict, dict]:
    """Return (reference_building_doc, ingest_stats)."""
    dims = raw.get("dimensions")
    if not (isinstance(dims, list) and len(dims) == 3):
        raise ValueError("dimensions missing or wrong shape")
    W, H, D = (int(v) for v in dims)
    if max(W, H, D) > 512:
        raise ValueError(f"dimensions exceed schema max 512: {W}x{H}x{D}")

    blocks_in = raw.get("blocks") or []
    if limit_blocks:
        blocks_in = blocks_in[:limit_blocks]

    voxel_records: list[tuple[int, int, int, str]] = []  # (x,y,z, modern_id)
    fallbacks: set[str] = set()
    bad_entries = 0
    seen_coords: set[tuple[int, int, int]] = set()

    for entry in blocks_in:
        pos = entry.get("position")
        bt_raw = entry.get("block_type")
        bt = parse_block_type(bt_raw) if isinstance(bt_raw, str) else None
        if not (isinstance(pos, list) and len(pos) == 3) or bt is None:
            bad_entries += 1
            continue
        try:
            x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
        except (TypeError, ValueError):
            bad_entries += 1
            continue
        if not (0 <= x < W and 0 <= y < H and 0 <= z < D):
            bad_entries += 1
            continue
        coord = (x, y, z)
        if coord in seen_coords:
            # First write wins; skip duplicates.
            continue
        seen_coords.add(coord)
        modern, was_fallback = remap(bt)
        if was_fallback:
            fallbacks.add(bt)
        voxel_records.append((x, y, z, modern))

    if not voxel_records:
        raise ValueError("no usable voxels after parsing")

    palette = compress_palette(r[3] for r in voxel_records)  # drops air
    rev = {v: k for k, v in palette.items()}
    voxels = [
        [x, y, z, rev[m]]
        for (x, y, z, m) in voxel_records
        if not _is_air(m)
    ]

    metrics = populated_interior_metrics(voxels, palette)

    ingest_warnings: list[str] = []
    if fallbacks:
        ingest_warnings.append(
            f"pre_flat_unknown_fallback: {sorted(fallbacks)[:10]}"
        )
    if bad_entries:
        ingest_warnings.append(f"skipped_bad_entries={bad_entries}")
    ingest_warnings.append("pre_flattening_remap_applied")
    ingest_warnings.append("block_states_lost")
    ingest_warnings.append("license_CC-BY-NC_research_only")

    doc = {
        "id": building_id,
        "source": "huggingface",
        "source_url": SOURCE_URL,
        "license": LICENSE,
        "license_notes": LICENSE_NOTES,
        "title": title[:200],
        "description": description[:2000],
        "tags": {
            "category": category,
            "style": style,
        },
        "bounding_box": {"size": [W, H, D]},
        "block_palette": {str(k): v for k, v in palette.items()},
        "voxels": voxels,
        "bot_decomposition": None,
        "metadata_quality": {
            **metrics,
            "has_labels": False,
            "ingest_warnings": ingest_warnings,
        },
        "ingest": {
            "tool": "ingest_lvnvceo.py",
            "tool_version": "0.1.0",
            "source_format": "json",
            "ingested_at": now_iso(),
            "ingester_path": str(source_path),
        },
    }

    stats = {
        "input_blocks": len(blocks_in),
        "written_voxels": len(voxels),
        "bad_entries": bad_entries,
        "unknown_pre_flat_ids": sorted(fallbacks),
        "palette_size": len(palette),
        "dims": [W, H, D],
    }
    return doc, stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--input",
        type=Path,
        default=RAW_DIR / "hf_lvnvceo" / "example.json",
    )
    p.add_argument("--id-suffix", default="example")
    p.add_argument("--title", default="lvnvceo mc-schematics example scene")
    p.add_argument(
        "--description",
        default=(
            "Single schematic from the HuggingFace dataset "
            "lvnvceo/mc-schematics (example.json). Pre-flattening 1.12 "
            "block IDs remapped to 1.16.5; block states discarded."
        ),
    )
    p.add_argument("--category", default="other")
    p.add_argument("--style", nargs="+", default=["other"])
    p.add_argument("--limit-blocks", type=int, default=None)
    args = p.parse_args(argv)

    if not args.input.exists():
        print(f"[ingest] input not found: {args.input}", file=sys.stderr)
        return 2

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    building_id = f"hf-lvnvceo-{slugify(args.id_suffix, max_len=40)}"

    doc, stats = build_document(
        raw=raw,
        source_path=args.input,
        building_id=building_id,
        title=args.title,
        description=args.description,
        category=args.category,
        style=args.style,
        limit_blocks=args.limit_blocks,
    )

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROCESSED_DIR / f"{doc['id']}.json"
    out_path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    append_manifest({
        "id": doc["id"],
        "source": doc["source"],
        "source_url": doc["source_url"],
        "license": doc["license"],
        "license_notes": "CC-BY-NC-4.0",
        "raw_path": str(args.input),
        "processed_path": str(out_path),
        "stats": stats,
        "ingested_at": doc["ingest"]["ingested_at"],
    })

    append_processing_log(
        f"\n## {now_iso()} - HF lvnvceo/mc-schematics example.json\n"
        f"- source: {SOURCE_URL}\n"
        f"- format: json (sparse non-air block list)\n"
        f"- agent: phase-b-agent-2\n"
        f"- action: kept 1\n"
        f"- reason: example.json fits as a single building region "
        f"({stats['dims'][0]}x{stats['dims'][1]}x{stats['dims'][2]}, "
        f"{stats['written_voxels']} non-air voxels, "
        f"palette={stats['palette_size']})\n"
        f"- license: CC-BY-NC-4.0 (research-use only; flagged)\n"
        f"- notes: pre-flattening 1.12 block IDs remapped to 1.16.5; "
        f"block-state info discarded. Full 1.36 GB archive NOT downloaded.\n"
    )

    print(f"[ingest] wrote {out_path}")
    print(f"[ingest] stats: {json.dumps(stats, indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
