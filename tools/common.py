"""Shared utilities for the RAG-E ingest pipeline.

Conventions:
- All block IDs are 1.16.5 namespaced (`minecraft:oak_planks`).
- Coordinates are local to the building's AABB lower corner (0, 0, 0).
- Y is up in Minecraft Java.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "rag" / "reference_buildings" / "processed"
RAW_DIR = REPO_ROOT / "rag" / "reference_buildings" / "raw"
MANIFEST_PATH = RAW_DIR / "manifest.jsonl"
PROCESSING_LOG = REPO_ROOT / "rag" / "reference_buildings" / "PROCESSING.md"


# Heuristic — blocks that mark a populated interior (a non-empty list of these
# inside the bounding-box interior implies the build is more than a cascarón).
FURNITURE_BLOCKS: frozenset[str] = frozenset({
    "minecraft:bed",
    "minecraft:white_bed", "minecraft:orange_bed", "minecraft:magenta_bed",
    "minecraft:light_blue_bed", "minecraft:yellow_bed", "minecraft:lime_bed",
    "minecraft:pink_bed", "minecraft:gray_bed", "minecraft:light_gray_bed",
    "minecraft:cyan_bed", "minecraft:purple_bed", "minecraft:blue_bed",
    "minecraft:brown_bed", "minecraft:green_bed", "minecraft:red_bed",
    "minecraft:black_bed",
    "minecraft:crafting_table",
    "minecraft:furnace",
    "minecraft:blast_furnace",
    "minecraft:smoker",
    "minecraft:chest",
    "minecraft:trapped_chest",
    "minecraft:barrel",
    "minecraft:bookshelf",
    "minecraft:lectern",
    "minecraft:enchanting_table",
    "minecraft:cauldron",
    "minecraft:anvil",
    "minecraft:chipped_anvil",
    "minecraft:damaged_anvil",
    "minecraft:grindstone",
    "minecraft:loom",
    "minecraft:stonecutter",
    "minecraft:smithing_table",
    "minecraft:cartography_table",
    "minecraft:fletching_table",
    "minecraft:brewing_stand",
    "minecraft:flower_pot",
    "minecraft:painting",
    "minecraft:item_frame",
    "minecraft:armor_stand",
    "minecraft:campfire",
    "minecraft:soul_campfire",
    "minecraft:lantern",
    "minecraft:soul_lantern",
    "minecraft:torch",
    "minecraft:wall_torch",
    "minecraft:soul_torch",
    "minecraft:candle",
    "minecraft:jukebox",
    "minecraft:note_block",
    "minecraft:carpet",
    "minecraft:white_carpet", "minecraft:red_carpet", "minecraft:blue_carpet",
})

# Blocks that count as "air-like" interior volume (not furniture, not wall).
AIR_LIKE: frozenset[str] = frozenset({
    "minecraft:air",
    "minecraft:cave_air",
    "minecraft:void_air",
})


# Slug pattern — must match `^[a-z0-9][a-z0-9_-]{2,63}$` in the schema.
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def slugify(text: str, max_len: int = 60) -> str:
    s = text.strip().lower()
    s = _SLUG_RE.sub("-", s)
    s = re.sub(r"-+", "-", s).strip("-_")
    if not s:
        s = "untitled"
    if not s[0].isalnum():
        s = "x" + s
    return s[:max_len]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class IngestResult:
    """Result of a single ingest attempt."""
    success: bool
    output_path: Path | None = None
    license: str = "unknown"
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_log_entry(self, source_url: str, source_format: str) -> str:
        action = "kept" if self.success else "rejected"
        bullets = [
            f"- source: {source_url}",
            f"- format: {source_format}",
            f"- action: {action}",
            f"- license: {self.license}",
        ]
        if self.warnings:
            bullets.append(f"- warnings: {'; '.join(self.warnings)}")
        if self.errors:
            bullets.append(f"- errors: {'; '.join(self.errors)}")
        return f"\n## {now_iso()} — {source_url.rsplit('/', 1)[-1]}\n" + "\n".join(bullets) + "\n"


def append_manifest(entry: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, separators=(",", ":")) + "\n")


def append_processing_log(text: str) -> None:
    PROCESSING_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PROCESSING_LOG.open("a", encoding="utf-8") as fh:
        fh.write(text)


def _is_air(block_id: str) -> bool:
    """Return True if block_id refers to any air variant (with or without state suffix)."""
    bare = block_id.split("[", 1)[0]
    return bare in AIR_LIKE


def filter_air(blocks: dict[tuple[int, int, int], str]) -> dict[tuple[int, int, int], str]:
    """Drop air-like entries from a coord→block dict."""
    return {coord: b for coord, b in blocks.items() if not _is_air(b)}


def compress_palette(blocks: Iterable[str]) -> dict[int, str]:
    """Build a deterministic palette {idx: block_id} from a stream of block IDs.

    Air variants (air, cave_air, void_air) are DROPPED — air is implicit in the
    voxel storage (any coord not present is air). Remaining blocks are sorted by
    frequency desc, then by name for determinism. The palette starts at idx 0.
    """
    counts: dict[str, int] = {}
    for b in blocks:
        if _is_air(b):
            continue
        counts[b] = counts.get(b, 0) + 1

    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return {i: block for i, (block, _) in enumerate(ordered)}


FURNITURE_THRESHOLD = 20


def populated_interior_metrics(voxels: list[list[int]], palette: dict[int, str]) -> dict:
    """Return {interior_populated, furniture_blocks}.

    Absolute-count heuristic: a build is populated if it contains at least
    FURNITURE_THRESHOLD furniture blocks (beds, chests, crafting tables, …).
    The previous ratio-based heuristic broke on builds with outdoor gardens
    (huge air count made the threshold unreachable). Since air is no longer
    stored in voxels, the ratio approach is moot anyway.
    """
    def _bare(b: str) -> str:
        return b.split("[", 1)[0]
    furn_idx = {i for i, b in palette.items() if _bare(b) in FURNITURE_BLOCKS}

    furniture = sum(1 for _, _, _, p in voxels if p in furn_idx)

    return {
        "interior_populated": furniture >= FURNITURE_THRESHOLD,
        "furniture_blocks": furniture,
    }
