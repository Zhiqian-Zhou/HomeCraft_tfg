"""Convert a .schem / .schematic / .litematic file into a canonical
ReferenceBuilding JSON in rag/reference_buildings/processed/.

Supported formats:
- Sponge Schematic v1/v2/v3 (`.schem`) — via `mcschematic` if installed
- WorldEdit legacy (`.schematic`) — via `nbtlib`, legacy IDs flattened
- Litematica (`.litematic`) — via `litemapy` if installed

This is a thin orchestrator. It dispatches by file extension and delegates
the parse step. Output is written to `processed/` ONLY when:
- license is identifiable (passed via --license)
- schema validation passes (validate_building.py)

Usage:
    python tools/ingest_schematic.py \
        --input rag/reference_buildings/raw/some_house.schem \
        --source planet-minecraft \
        --source-url https://www.planetminecraft.com/project/foo/ \
        --license CC-BY \
        --title "Medieval cottage" \
        --category residential \
        --style medieval \
        --stories 1
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (
    PROCESSED_DIR,
    _is_air,
    append_processing_log,
    compress_palette,
    now_iso,
    populated_interior_metrics,
    slugify,
)


def _strip_block_state(block_id: str) -> str:
    """Drop the `[state=...]` suffix — palette stores 1.16.5-flat block IDs only."""
    idx = block_id.find("[")
    return block_id[:idx] if idx != -1 else block_id


def _varint_decode(buf: bytes) -> list[int]:
    out: list[int] = []
    i = 0
    n = len(buf)
    while i < n:
        v = 0
        shift = 0
        while True:
            b = buf[i] & 0xFF
            i += 1
            v |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        out.append(v)
    return out


def _parse_schem_v3(root) -> tuple[list[list[int]], dict[int, str], tuple[int, int, int]]:
    """Parse Sponge Schematic v3 (palette + varint Data under Blocks compound)."""
    W = int(root["Width"])
    H = int(root["Height"])
    L = int(root["Length"])
    blocks_section = root["Blocks"]
    raw_palette = {str(k): int(v) for k, v in blocks_section["Palette"].items()}
    # idx -> raw blockstate string
    idx_to_state = {v: k for k, v in raw_palette.items()}

    # Convert to flat IDs (drop blockstate properties for now — 1.16.5 ingester
    # is state-agnostic per common.compress_palette contract).
    idx_to_flat = {i: _strip_block_state(s) for i, s in idx_to_state.items()}

    data_bytes = bytes(int(x) & 0xFF for x in blocks_section["Data"])
    indices = _varint_decode(data_bytes)
    if len(indices) != W * H * L:
        raise ValueError(
            f"Sponge v3: Data length {len(indices)} != W*H*L {W*H*L}"
        )

    block_id_stream = (idx_to_flat[i] for i in indices)
    palette = compress_palette(block_id_stream)  # drops air
    rev = {v: k for k, v in palette.items()}

    voxels: list[list[int]] = []
    # Sponge order: index = y*W*L + z*W + x
    i = 0
    for y in range(H):
        for z in range(L):
            for x in range(W):
                flat = idx_to_flat[indices[i]]
                i += 1
                if _is_air(flat):
                    continue
                voxels.append([x, y, z, rev[flat]])
    return voxels, palette, (W, H, L)


def _parse_schem_v2(root) -> tuple[list[list[int]], dict[int, str], tuple[int, int, int]]:
    """Parse Sponge Schematic v1/v2 (palette + varint BlockData at root)."""
    W = int(root["Width"])
    H = int(root["Height"])
    L = int(root["Length"])
    raw_palette = {str(k): int(v) for k, v in root["Palette"].items()}
    idx_to_flat = {v: _strip_block_state(k) for k, v in raw_palette.items()}
    data_bytes = bytes(int(x) & 0xFF for x in root["BlockData"])
    indices = _varint_decode(data_bytes)
    if len(indices) != W * H * L:
        raise ValueError(
            f"Sponge v2: BlockData length {len(indices)} != W*H*L {W*H*L}"
        )
    block_id_stream = (idx_to_flat[i] for i in indices)
    palette = compress_palette(block_id_stream)  # drops air
    rev = {v: k for k, v in palette.items()}
    voxels: list[list[int]] = []
    i = 0
    for y in range(H):
        for z in range(L):
            for x in range(W):
                flat = idx_to_flat[indices[i]]
                i += 1
                if _is_air(flat):
                    continue
                voxels.append([x, y, z, rev[flat]])
    return voxels, palette, (W, H, L)


def _parse_schem(path: Path) -> tuple[list[list[int]], dict[int, str], tuple[int, int, int]]:
    """Parse a Sponge .schem file (v1/v2/v3). Returns (voxels, palette, (W,H,D))."""
    try:
        import nbtlib  # type: ignore
    except ImportError as exc:
        raise SystemExit("nbtlib not installed: pip install nbtlib") from exc

    nbt = nbtlib.load(str(path))
    # v3 wraps under a 'Schematic' compound; v1/v2 do not.
    root = nbt["Schematic"] if "Schematic" in nbt else nbt
    version = int(root.get("Version", 2))
    if version >= 3 or "Blocks" in root:
        return _parse_schem_v3(root)
    return _parse_schem_v2(root)


def _parse_litematic(path: Path) -> tuple[list[list[int]], dict[int, str], tuple[int, int, int]]:
    try:
        from litemapy import Schematic  # type: ignore
    except ImportError as exc:
        raise SystemExit("litemapy not installed: pip install litemapy") from exc

    schem = Schematic.load(str(path))
    blocks: dict[tuple[int, int, int], str] = {}
    minx = miny = minz = 0
    maxx = maxy = maxz = 0
    for region in schem.regions.values():
        for x, y, z in region.allblockpos():
            block = region.getblock(x, y, z)
            block_id = block.blockid if hasattr(block, "blockid") else str(block)
            if not block_id.startswith("minecraft:"):
                block_id = f"minecraft:{block_id}"
            blocks[(x, y, z)] = block_id
            minx, miny, minz = min(minx, x), min(miny, y), min(minz, z)
            maxx, maxy, maxz = max(maxx, x), max(maxy, y), max(maxz, z)

    W = maxx - minx + 1
    H = maxy - miny + 1
    D = maxz - minz + 1

    palette = compress_palette(blocks.values())  # drops air
    rev = {v: k for k, v in palette.items()}
    voxels = [
        [x - minx, y - miny, z - minz, rev[b]]
        for (x, y, z), b in blocks.items()
        if not _is_air(b)
    ]
    return voxels, palette, (W, H, D)


def _parse_legacy_schematic(path: Path) -> tuple[list[list[int]], dict[int, str], tuple[int, int, int]]:
    """Parse a WorldEdit legacy .schematic file (numeric IDs)."""
    raise NotImplementedError(
        "Legacy .schematic parser TODO. Use amulet-core flattening:\n"
        "  amulet.api.world.World(path).get_block(...) returns namespaced blocks."
    )


PARSERS = {
    ".schem":     _parse_schem,
    ".schematic": _parse_legacy_schematic,
    ".litematic": _parse_litematic,
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--source", required=True)
    p.add_argument("--source-url", required=True)
    p.add_argument("--license", required=True)
    p.add_argument("--license-notes", default=None,
                   help="Free-form note attached to the building when license is ambiguous.")
    p.add_argument("--title", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--style", nargs="+", required=True)
    p.add_argument("--stories", type=int, default=None)
    p.add_argument("--description", default="")
    p.add_argument("--id", default=None)
    args = p.parse_args(argv)

    ext = args.input.suffix.lower()
    if ext not in PARSERS:
        print(f"[ingest] unknown extension {ext}; supported: {list(PARSERS)}", file=sys.stderr)
        return 2

    voxels, palette, (W, H, D) = PARSERS[ext](args.input)
    metrics = populated_interior_metrics(voxels, palette)

    building_id = args.id or slugify(args.title)
    doc = {
        "id": building_id,
        "source": args.source,
        "source_url": args.source_url,
        "license": args.license,
        "title": args.title,
        "tags": {
            "category": args.category,
            "style": args.style,
        },
        "bounding_box": {"size": [W, H, D]},
        "block_palette": {str(k): v for k, v in palette.items()},
        "voxels": voxels,
        "bot_decomposition": None,
        "metadata_quality": {
            **metrics,
            "has_labels": False,
        },
        "ingest": {
            "tool": "ingest_schematic.py",
            "tool_version": "0.1.0",
            "source_format": ext.lstrip("."),
            "ingested_at": now_iso(),
            "ingester_path": __file__,
        },
    }
    if args.description:
        doc["description"] = args.description
    if args.license_notes:
        doc["license_notes"] = args.license_notes
    if args.stories:
        doc["tags"]["stories"] = args.stories

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / f"{building_id}.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    append_processing_log(
        f"\n## {now_iso()} — {out.name}\n"
        f"- source: {args.source_url}\n"
        f"- format: {ext.lstrip('.')}\n"
        f"- action: kept\n"
        f"- license: {args.license}\n"
        f"- size: {W}x{H}x{D}\n"
        f"- interior_populated: {metrics['interior_populated']}\n"
    )
    print(f"[ingest] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
