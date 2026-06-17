"""Generate viewer/data/index.json with lightweight metadata for every building.

The viewer needs to filter / sort 2,746 buildings client-side without loading
each ~50-100 KB JSON. This script reads every processed/*.json and emits one
compact index entry per building with just the fields the sidebar UI needs.

Usage:
    python tools/build_viewer_index.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "rag" / "reference_buildings" / "processed"
OUT_PATH = REPO_ROOT / "viewer" / "data" / "index.json"


def main() -> int:
    files = sorted(PROCESSED_DIR.glob("*.json"))
    entries: list[dict] = []
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        bb = doc["bounding_box"]["size"]
        entries.append({
            "id": doc["id"],
            "title": doc.get("title", doc["id"])[:120],
            "file": path.name,
            "category": doc.get("tags", {}).get("category", "other"),
            "style": doc.get("tags", {}).get("style", ["other"]),
            "license": doc.get("license", "unknown"),
            "source": doc.get("source", "other"),
            "size": bb,
            "volume": bb[0] * bb[1] * bb[2],
            "voxel_count": len(doc.get("voxels", [])),
            "palette_size": len(doc.get("block_palette", {})),
            "interior_populated": doc.get("metadata_quality", {}).get("interior_populated", False),
            "furniture_blocks": doc.get("metadata_quality", {}).get("furniture_blocks", 0),
            "synthetic": doc.get("source") == "synthetic",
        })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "count": len(entries),
        "entries": entries,
    }, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"[index] wrote {len(entries)} entries to {OUT_PATH.relative_to(REPO_ROOT)}")
    print(f"[index] file size: {OUT_PATH.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
