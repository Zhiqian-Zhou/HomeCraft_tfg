"""Analyze block frequencies across rag/reference_buildings/processed/*.json.

Writes `scratch/material_frequencies.json` with the top-100 most-used 1.16.5
namespaced block IDs (blockstate suffixes stripped). Each entry has:
    block_id (str), count (int), buildings_present_in (int),
    frac_of_corpus (float), example_building (str)

The output feeds Phase C — the 10 materials agents each take ~10 entries
from this list.

    python3 tools/build_material_corpus.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "rag" / "reference_buildings" / "processed"
OUT_PATH = REPO_ROOT / "scratch" / "material_frequencies.json"


def _bare(block_id: str) -> str:
    """Strip [state=...] suffix from a block id."""
    idx = block_id.find("[")
    return block_id[:idx] if idx != -1 else block_id


def main() -> int:
    block_voxel_count: Counter[str] = Counter()
    block_building_count: Counter[str] = Counter()
    example_for: dict[str, str] = {}

    files = sorted(PROCESSED_DIR.glob("*.json"))
    if not files:
        print(f"[material_corpus] no JSONs in {PROCESSED_DIR}", file=sys.stderr)
        return 1

    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        palette = doc.get("block_palette", {})
        voxels = doc.get("voxels", [])
        # palette idx → bare block id
        idx_to_bare: dict[int, str] = {}
        seen_in_this_building: set[str] = set()
        for k, v in palette.items():
            bare = _bare(v)
            idx_to_bare[int(k)] = bare
            seen_in_this_building.add(bare)
        for vox in voxels:
            if len(vox) != 4:
                continue
            bare = idx_to_bare.get(vox[3])
            if bare:
                block_voxel_count[bare] += 1
        for bare in seen_in_this_building:
            block_building_count[bare] += 1
            if bare not in example_for:
                example_for[bare] = doc.get("id", path.stem)

    total_voxels = sum(block_voxel_count.values())
    if total_voxels == 0:
        print("[material_corpus] no voxels found", file=sys.stderr)
        return 1

    top = block_voxel_count.most_common(150)
    entries = []
    for block_id, count in top:
        entries.append({
            "block_id": block_id,
            "count": count,
            "buildings_present_in": block_building_count[block_id],
            "frac_of_corpus": round(count / total_voxels, 6),
            "example_building": example_for.get(block_id, ""),
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "total_buildings_scanned": len(files),
        "total_voxels": total_voxels,
        "unique_blocks": len(block_voxel_count),
        "entries": entries,
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"[material_corpus] {len(files)} buildings, {total_voxels:,} voxels, "
          f"{len(block_voxel_count)} unique blocks")
    print(f"[material_corpus] wrote top {len(entries)} → {OUT_PATH.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
