"""Extract per-style block palette frequencies from reference buildings.

For each style tag (medieval, fantasy, etc.), counts how often each block
appears in buildings carrying that style, then emits the top-12 blocks per
style as a "seed palette" for the Phase E style-pack agents.

    python3 tools/build_style_palettes.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "rag" / "reference_buildings" / "processed"
OUT_PATH = REPO_ROOT / "scratch" / "style_palettes.json"

STYLES_OF_INTEREST = [
    "medieval", "fantasy", "gothic", "renaissance",
    "modern", "minimalist", "japanese", "chinese",
    "mediterranean", "rustic",
]

# Common structural blocks to deprioritize (they appear in everything) so
# the agent sees the SIGNATURE blocks per style.
STRUCTURAL_COMMON = {
    "minecraft:stone", "minecraft:cobblestone", "minecraft:dirt",
    "minecraft:grass_block", "minecraft:gravel", "minecraft:sand",
    "minecraft:air", "minecraft:cave_air",
}


def _bare(block_id: str) -> str:
    idx = block_id.find("[")
    return block_id[:idx] if idx != -1 else block_id


def main() -> int:
    files = sorted(PROCESSED_DIR.glob("*.json"))
    if not files:
        print("[style_palettes] no JSONs", file=sys.stderr)
        return 1

    # style → Counter[block_id]
    style_counters: dict[str, Counter] = defaultdict(Counter)
    style_building_count: Counter[str] = Counter()
    style_examples: dict[str, list[str]] = defaultdict(list)

    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        styles = doc.get("tags", {}).get("style", [])
        palette = doc.get("block_palette", {})
        voxels = doc.get("voxels", [])
        idx_to_bare = {int(k): _bare(v) for k, v in palette.items()}

        for style in styles:
            if style not in STYLES_OF_INTEREST:
                continue
            style_building_count[style] += 1
            if len(style_examples[style]) < 5:
                style_examples[style].append(doc.get("id", path.stem))
            for vox in voxels:
                bare = idx_to_bare.get(vox[3])
                if bare:
                    style_counters[style][bare] += 1

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out: dict = {"styles": {}}
    for style in STYLES_OF_INTEREST:
        cnt = style_counters[style]
        # Filter out structural common AND keep top-12
        signature = [(b, n) for b, n in cnt.most_common() if b not in STRUCTURAL_COMMON][:12]
        all_top = cnt.most_common(15)
        out["styles"][style] = {
            "buildings": style_building_count[style],
            "examples": style_examples[style],
            "top_all_blocks": [{"block_id": b, "count": n} for b, n in all_top],
            "signature_blocks": [{"block_id": b, "count": n} for b, n in signature],
        }
    OUT_PATH.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[style_palettes] wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    for style in STYLES_OF_INTEREST:
        n = style_building_count[style]
        print(f"  {style:15s} {n:>4d} buildings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
