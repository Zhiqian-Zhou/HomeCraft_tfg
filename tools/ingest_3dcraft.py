"""Convert the Facebook Research 3D-Craft / VoxelCNN house_data dataset into
canonical ReferenceBuilding JSONs.

Dataset:
    URL:     https://craftassist.s3-us-west-2.amazonaws.com/pubr/house_data.tar.gz
    Paper:   "Order-Aware Generative Modeling Using the 3D-Craft Dataset"
             Chen et al., ICCV 2019
    License: CC-BY-NC 4.0 (declared on the craftassist / VoxelCNN repo). Research
             use OK; redistribution NOT permitted, so this tool reads the tarball
             *locally* and emits derivative JSONs (still CC-BY-NC).

Per-house file layout (each subdirectory of `houses/`):
    - placed.json: action log
        [ [timestamp, annotator_id, [x, y, z], [block_id, meta], "P"|"B"], ... ]
      The canonical reconstruction is the voxelcnn `_load_annotation` algorithm:
      walk the log in order; for "B" (break) drop coord from current state; for
      "P" (place) overwrite coord with new block. The final house = remaining
      blocks. block_id is a *signed* int in JSON but should be interpreted as
      uint8 (legacy 1.7-era MC block id, 0-255). meta is the 4-bit blockstate.
    - schematic.npy: numpy `(W, 1, H, 2)` ... actually `(X, Z, Y, 2)` uint8.
      Redundant with placed.json. We don't use it (axes are tricky; placed.json
      is the official ground truth used by the dataloader).
    - stats.json: {"size": [W, H, D], "placed": N, "broken": M, ...}
      Useful sanity check but axis order is W=x, H=y, D=z.
    - chunky.*.png: render screenshots, ignored.

Block ID mapping is *legacy numeric + meta*; we expand the
`tools/ingest_hf_tuplelist.LEGACY_TO_NAMESPACED` table with a meta-aware overlay
specific to 1.16.5 (planks/logs/wool/stained-glass species differentiation).

Usage:
    python tools/ingest_3dcraft.py \\
        --houses-dir scratch/3d_craft/extracted/houses \\
        --limit 20
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    PROCESSED_DIR,
    _is_air,
    append_processing_log,
    compress_palette,
    now_iso,
    populated_interior_metrics,
    slugify,
)
from ingest_hf_tuplelist import LEGACY_TO_NAMESPACED  # noqa: E402


# --- meta-aware legacy → 1.16.5 mapping ---------------------------------------
#
# Many legacy numeric IDs distinguish variants via the 4-bit `meta` field:
#   - 5  planks: 0 oak / 1 spruce / 2 birch / 3 jungle / 4 acacia / 5 dark_oak
#   - 17 log:    0 oak / 1 spruce / 2 birch / 3 jungle   (high bits = axis)
#   - 162 log2:  0 acacia / 1 dark_oak
#   - 35 wool:   16 colours by meta
#   - 95 stained_glass, 160 stained_glass_pane: 16 colours
#   - 159 stained_terracotta, 251 concrete, 252 concrete_powder: 16 colours
#   - 126 wood_slab, 44 stone_slab, 43 double_stone_slab: variant by meta
#   - 67 stairs, 53/108/109/etc. stairs: meta encodes facing; we drop facing
#   - 98 stonebrick: 0 normal / 1 mossy / 2 cracked / 3 chiseled
#   - 24 sandstone: 0 normal / 1 chiseled / 2 smooth
#   - 179 red_sandstone: 0/1/2 same pattern
#
# Where the variant matters for visual style we expand; where it's facing only,
# we drop the meta (the schema permits state suffix but we keep things simple).

COLOR_BY_META: dict[int, str] = {
    0: "white", 1: "orange", 2: "magenta", 3: "light_blue", 4: "yellow",
    5: "lime", 6: "pink", 7: "gray", 8: "light_gray", 9: "cyan",
    10: "purple", 11: "blue", 12: "brown", 13: "green", 14: "red", 15: "black",
}

PLANKS_BY_META = {
    0: "minecraft:oak_planks", 1: "minecraft:spruce_planks",
    2: "minecraft:birch_planks", 3: "minecraft:jungle_planks",
    4: "minecraft:acacia_planks", 5: "minecraft:dark_oak_planks",
}
LOG_BY_META = {
    # low 2 bits = species; high bits = axis (drop axis)
    0: "minecraft:oak_log", 1: "minecraft:spruce_log",
    2: "minecraft:birch_log", 3: "minecraft:jungle_log",
}
LOG2_BY_META = {0: "minecraft:acacia_log", 1: "minecraft:dark_oak_log"}
LEAVES_BY_META = {
    0: "minecraft:oak_leaves", 1: "minecraft:spruce_leaves",
    2: "minecraft:birch_leaves", 3: "minecraft:jungle_leaves",
}
LEAVES2_BY_META = {0: "minecraft:acacia_leaves", 1: "minecraft:dark_oak_leaves"}
SAPLING_BY_META = {
    0: "minecraft:oak_sapling", 1: "minecraft:spruce_sapling",
    2: "minecraft:birch_sapling", 3: "minecraft:jungle_sapling",
    4: "minecraft:acacia_sapling", 5: "minecraft:dark_oak_sapling",
}
STONE_BY_META = {
    0: "minecraft:stone", 1: "minecraft:granite", 2: "minecraft:polished_granite",
    3: "minecraft:diorite", 4: "minecraft:polished_diorite",
    5: "minecraft:andesite", 6: "minecraft:polished_andesite",
}
DIRT_BY_META = {
    0: "minecraft:dirt", 1: "minecraft:coarse_dirt", 2: "minecraft:podzol",
}
SAND_BY_META = {0: "minecraft:sand", 1: "minecraft:red_sand"}
SANDSTONE_BY_META = {
    0: "minecraft:sandstone", 1: "minecraft:chiseled_sandstone", 2: "minecraft:smooth_sandstone",
}
RED_SANDSTONE_BY_META = {
    0: "minecraft:red_sandstone", 1: "minecraft:chiseled_red_sandstone", 2: "minecraft:smooth_red_sandstone",
}
STONEBRICK_BY_META = {
    0: "minecraft:stone_bricks", 1: "minecraft:mossy_stone_bricks",
    2: "minecraft:cracked_stone_bricks", 3: "minecraft:chiseled_stone_bricks",
}
QUARTZ_BY_META = {
    0: "minecraft:quartz_block", 1: "minecraft:chiseled_quartz_block",
    2: "minecraft:quartz_pillar", 3: "minecraft:quartz_pillar", 4: "minecraft:quartz_pillar",
}
# Stone-slab meta in 1.7: 0 stone, 1 sandstone, 3 cobblestone, 4 brick,
# 5 stone-brick, 6 nether-brick, 7 quartz. Bit 0x8 = upper-half flag.
STONE_SLAB_BY_META = {
    0: "minecraft:smooth_stone_slab", 1: "minecraft:sandstone_slab",
    3: "minecraft:cobblestone_slab", 4: "minecraft:brick_slab",
    5: "minecraft:stone_brick_slab", 6: "minecraft:nether_brick_slab",
    7: "minecraft:quartz_slab",
}
WOOD_SLAB_BY_META = {
    0: "minecraft:oak_slab", 1: "minecraft:spruce_slab",
    2: "minecraft:birch_slab", 3: "minecraft:jungle_slab",
    4: "minecraft:acacia_slab", 5: "minecraft:dark_oak_slab",
}
# Pre-flattening "double slab" — treat as the full block of the variant.
DOUBLE_STONE_SLAB_BY_META = {
    0: "minecraft:smooth_stone", 1: "minecraft:sandstone",
    3: "minecraft:cobblestone", 4: "minecraft:bricks",
    5: "minecraft:stone_bricks", 6: "minecraft:nether_bricks",
    7: "minecraft:quartz_block",
}
PRISMARINE_BY_META = {
    0: "minecraft:prismarine", 1: "minecraft:prismarine_bricks", 2: "minecraft:dark_prismarine",
}
COBBLESTONE_WALL_BY_META = {
    0: "minecraft:cobblestone_wall", 1: "minecraft:mossy_cobblestone_wall",
}


def _wool(meta: int) -> str:
    return f"minecraft:{COLOR_BY_META.get(meta & 0xF, 'white')}_wool"


def _carpet(meta: int) -> str:
    return f"minecraft:{COLOR_BY_META.get(meta & 0xF, 'white')}_carpet"


def _stained_glass(meta: int) -> str:
    return f"minecraft:{COLOR_BY_META.get(meta & 0xF, 'white')}_stained_glass"


def _stained_glass_pane(meta: int) -> str:
    return f"minecraft:{COLOR_BY_META.get(meta & 0xF, 'white')}_stained_glass_pane"


def _stained_terracotta(meta: int) -> str:
    return f"minecraft:{COLOR_BY_META.get(meta & 0xF, 'white')}_terracotta"


def _concrete(meta: int) -> str:
    return f"minecraft:{COLOR_BY_META.get(meta & 0xF, 'white')}_concrete"


def _concrete_powder(meta: int) -> str:
    return f"minecraft:{COLOR_BY_META.get(meta & 0xF, 'white')}_concrete_powder"


# Single-value (meta ignored / facing-only) legacy → namespaced 1.16.5.
# Extends `LEGACY_TO_NAMESPACED` from `ingest_hf_tuplelist`.
EXTRA_FLAT: dict[int, str] = {
    27: "minecraft:powered_rail",
    28: "minecraft:detector_rail",
    29: "minecraft:sticky_piston",
    30: "minecraft:cobweb",
    31: "minecraft:grass",            # tall_grass with meta=1 = grass, =2 = fern (we simplify)
    32: "minecraft:dead_bush",
    33: "minecraft:piston",
    37: "minecraft:dandelion",
    38: "minecraft:poppy",            # legacy "red flower" with meta deciding variant; default poppy
    39: "minecraft:brown_mushroom",
    40: "minecraft:red_mushroom",
    46: "minecraft:tnt",
    51: "minecraft:fire",
    52: "minecraft:spawner",
    55: "minecraft:redstone_wire",
    56: "minecraft:diamond_ore",
    57: "minecraft:diamond_block",
    59: "minecraft:wheat",
    60: "minecraft:farmland",
    62: "minecraft:furnace",          # lit furnace -> regular furnace
    63: "minecraft:oak_sign",
    66: "minecraft:rail",
    68: "minecraft:oak_wall_sign",
    69: "minecraft:lever",
    70: "minecraft:stone_pressure_plate",
    71: "minecraft:iron_door",
    72: "minecraft:oak_pressure_plate",
    73: "minecraft:redstone_ore",
    74: "minecraft:redstone_ore",
    75: "minecraft:redstone_torch",
    76: "minecraft:redstone_torch",
    77: "minecraft:stone_button",
    78: "minecraft:snow",
    79: "minecraft:ice",
    80: "minecraft:snow_block",
    81: "minecraft:cactus",
    82: "minecraft:clay",
    83: "minecraft:sugar_cane",
    84: "minecraft:jukebox",
    86: "minecraft:carved_pumpkin",
    87: "minecraft:netherrack",
    88: "minecraft:soul_sand",
    90: "minecraft:nether_portal",
    91: "minecraft:jack_o_lantern",
    92: "minecraft:cake",
    93: "minecraft:repeater",
    94: "minecraft:repeater",
    96: "minecraft:oak_trapdoor",
    97: "minecraft:infested_stone",
    99: "minecraft:brown_mushroom_block",
    100: "minecraft:red_mushroom_block",
    103: "minecraft:melon",
    104: "minecraft:pumpkin_stem",
    105: "minecraft:melon_stem",
    106: "minecraft:vine",
    107: "minecraft:oak_fence_gate",
    108: "minecraft:brick_stairs",
    110: "minecraft:mycelium",
    111: "minecraft:lily_pad",
    112: "minecraft:nether_bricks",
    113: "minecraft:nether_brick_fence",
    114: "minecraft:nether_brick_stairs",
    115: "minecraft:nether_wart",
    116: "minecraft:enchanting_table",
    117: "minecraft:brewing_stand",
    118: "minecraft:cauldron",
    119: "minecraft:end_portal",
    120: "minecraft:end_portal_frame",
    122: "minecraft:dragon_egg",
    123: "minecraft:redstone_lamp",
    124: "minecraft:redstone_lamp",
    127: "minecraft:cocoa",
    129: "minecraft:emerald_ore",
    130: "minecraft:ender_chest",
    131: "minecraft:tripwire_hook",
    132: "minecraft:tripwire",
    133: "minecraft:emerald_block",
    137: "minecraft:command_block",
    138: "minecraft:beacon",
    139: "minecraft:cobblestone_wall",
    140: "minecraft:flower_pot",
    141: "minecraft:carrots",
    142: "minecraft:potatoes",
    143: "minecraft:oak_button",
    144: "minecraft:skeleton_skull",
    145: "minecraft:anvil",
    146: "minecraft:trapped_chest",
    147: "minecraft:light_weighted_pressure_plate",
    148: "minecraft:heavy_weighted_pressure_plate",
    149: "minecraft:comparator",
    150: "minecraft:comparator",
    151: "minecraft:daylight_detector",
    152: "minecraft:redstone_block",
    153: "minecraft:nether_quartz_ore",
    154: "minecraft:hopper",
    157: "minecraft:activator_rail",
    158: "minecraft:dropper",
    161: "minecraft:acacia_leaves",   # leaves2 base – overridden below with meta map
    165: "minecraft:slime_block",
    166: "minecraft:barrier",
    167: "minecraft:iron_trapdoor",
    168: "minecraft:prismarine",
    170: "minecraft:hay_block",
    171: "minecraft:white_carpet",    # base carpet – overridden by _carpet()
    172: "minecraft:terracotta",
    173: "minecraft:coal_block",
    174: "minecraft:packed_ice",
    175: "minecraft:sunflower",       # large flowers; meta decides variant — simplify
    176: "minecraft:white_banner",
    177: "minecraft:white_wall_banner",
    178: "minecraft:daylight_detector",
    182: "minecraft:red_sandstone_slab",
    183: "minecraft:spruce_fence_gate",
    184: "minecraft:birch_fence_gate",
    185: "minecraft:jungle_fence_gate",
    186: "minecraft:dark_oak_fence_gate",
    187: "minecraft:acacia_fence_gate",
    198: "minecraft:end_rod",
    199: "minecraft:chorus_plant",
    200: "minecraft:chorus_flower",
    201: "minecraft:purpur_block",
    202: "minecraft:purpur_pillar",
    203: "minecraft:purpur_stairs",
    204: "minecraft:purpur_block",
    205: "minecraft:purpur_slab",
    206: "minecraft:end_stone_bricks",
    207: "minecraft:beetroots",
    208: "minecraft:grass_path",
    210: "minecraft:repeating_command_block",
    211: "minecraft:chain_command_block",
    212: "minecraft:frosted_ice",
    213: "minecraft:magma_block",
    214: "minecraft:nether_wart_block",
    215: "minecraft:red_nether_bricks",
    216: "minecraft:bone_block",
    217: "minecraft:structure_void",
    218: "minecraft:observer",
    219: "minecraft:white_shulker_box",
    255: "minecraft:structure_block",
}


def _map_block(legacy_id: int, meta: int) -> str:
    """Map (legacy_id, meta) → namespaced 1.16.5 block ID."""
    m = meta & 0xF  # mask off high bits used for axis / facing
    if legacy_id == 1:   return STONE_BY_META.get(m, "minecraft:stone")
    if legacy_id == 3:   return DIRT_BY_META.get(m, "minecraft:dirt")
    if legacy_id == 5:   return PLANKS_BY_META.get(m, "minecraft:oak_planks")
    if legacy_id == 6:   return SAPLING_BY_META.get(m, "minecraft:oak_sapling")
    if legacy_id == 12:  return SAND_BY_META.get(m, "minecraft:sand")
    if legacy_id == 17:  return LOG_BY_META.get(meta & 0x3, "minecraft:oak_log")
    if legacy_id == 18:  return LEAVES_BY_META.get(meta & 0x3, "minecraft:oak_leaves")
    if legacy_id == 24:  return SANDSTONE_BY_META.get(m, "minecraft:sandstone")
    if legacy_id == 35:  return _wool(meta)
    if legacy_id == 43:  return DOUBLE_STONE_SLAB_BY_META.get(m, "minecraft:smooth_stone")
    if legacy_id == 44:  return STONE_SLAB_BY_META.get(m & 0x7, "minecraft:smooth_stone_slab")
    if legacy_id == 95:  return _stained_glass(meta)
    if legacy_id == 98:  return STONEBRICK_BY_META.get(m, "minecraft:stone_bricks")
    if legacy_id == 125: return WOOD_SLAB_BY_META.get(m, "minecraft:oak_slab")  # double wood slab
    if legacy_id == 126: return WOOD_SLAB_BY_META.get(m & 0x7, "minecraft:oak_slab")
    if legacy_id == 139: return COBBLESTONE_WALL_BY_META.get(m, "minecraft:cobblestone_wall")
    if legacy_id == 155: return QUARTZ_BY_META.get(m, "minecraft:quartz_block")
    if legacy_id == 159: return _stained_terracotta(meta)
    if legacy_id == 160: return _stained_glass_pane(meta)
    if legacy_id == 161: return LEAVES2_BY_META.get(meta & 0x1, "minecraft:acacia_leaves")
    if legacy_id == 162: return LOG2_BY_META.get(meta & 0x1, "minecraft:acacia_log")
    if legacy_id == 168: return PRISMARINE_BY_META.get(m, "minecraft:prismarine")
    if legacy_id == 171: return _carpet(meta)
    if legacy_id == 179: return RED_SANDSTONE_BY_META.get(m, "minecraft:red_sandstone")
    if legacy_id == 251: return _concrete(meta)
    if legacy_id == 252: return _concrete_powder(meta)

    if legacy_id in EXTRA_FLAT:
        return EXTRA_FLAT[legacy_id]
    if legacy_id in LEGACY_TO_NAMESPACED:
        return LEGACY_TO_NAMESPACED[legacy_id]
    return "minecraft:stone"  # last-resort fallback


def reconstruct_final_house(placed_records: list) -> dict[tuple[int, int, int], tuple[int, int]]:
    """Apply the voxelcnn _load_annotation algorithm: walk the action log in
    order, mutate `current`, return the surviving placements.
    """
    current: dict[tuple[int, int, int], tuple[int, int]] = {}
    last_ts = -1
    for item in placed_records:
        try:
            ts, _aid, coord, binfo, action = item
        except (ValueError, TypeError):
            continue
        if not (isinstance(ts, (int, float)) and ts >= last_ts):
            # The voxelcnn loader asserts monotone timestamps; we just skip.
            pass
        else:
            last_ts = ts
        if not (isinstance(coord, list) and len(coord) == 3):
            continue
        if not (isinstance(binfo, list) and len(binfo) >= 1):
            continue
        c = (int(coord[0]), int(coord[1]), int(coord[2]))
        # Convert signed-in-JSON to uint8 like voxelcnn does.
        bid = int(binfo[0]) & 0xFF
        meta = int(binfo[1]) & 0xFF if len(binfo) > 1 else 0
        if action == "B":
            current.pop(c, None)
        else:
            current[c] = (bid, meta)
    return current


def ingest_house(house_dir: Path) -> dict | None:
    placed_path = house_dir / "placed.json"
    stats_path = house_dir / "stats.json"
    if not placed_path.exists():
        return None

    try:
        placed = json.loads(placed_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"[ingest] {house_dir.name}: bad placed.json ({exc})", file=sys.stderr)
        return None

    final = reconstruct_final_house(placed)
    if not final:
        print(f"[ingest] {house_dir.name}: empty after reconstruction", file=sys.stderr)
        return None
    # Reject trivially-tiny remnants (< 10 surviving blocks); these are usually
    # demolition / sandbox sessions, not actual buildings.
    if len(final) < 10:
        print(f"[ingest] {house_dir.name}: only {len(final)} blocks, skipping", file=sys.stderr)
        return None

    xs = [c[0] for c in final]
    ys = [c[1] for c in final]
    zs = [c[2] for c in final]
    minx, miny, minz = min(xs), min(ys), min(zs)
    maxx, maxy, maxz = max(xs), max(ys), max(zs)
    W = maxx - minx + 1
    H = maxy - miny + 1
    D = maxz - minz + 1

    if max(W, H, D) > 512:
        print(f"[ingest] {house_dir.name}: too large ({W}x{H}x{D})", file=sys.stderr)
        return None

    # Track unmapped IDs for warnings
    unmapped: set[int] = set()
    block_ids_seen: list[str] = []
    for (bid, meta) in final.values():
        b = _map_block(bid, meta)
        block_ids_seen.append(b)
        if bid not in LEGACY_TO_NAMESPACED and bid not in EXTRA_FLAT and bid not in (
            1, 3, 5, 6, 12, 17, 18, 24, 35, 43, 44, 95, 98, 125, 126,
            139, 155, 159, 160, 161, 162, 168, 171, 179, 251, 252,
        ):
            unmapped.add(bid)

    palette = compress_palette(block_ids_seen)  # drops air
    rev = {v: k for k, v in palette.items()}

    voxels: list[list[int]] = []
    for (x, y, z), (bid, meta) in final.items():
        b = _map_block(bid, meta)
        if _is_air(b):
            continue
        voxels.append([x - minx, y - miny, z - minz, rev[b]])

    metrics = populated_interior_metrics(voxels, palette)

    house_name = house_dir.name
    title = f"3D-Craft house {slugify(house_name, max_len=40)}"
    building_id = f"3dcraft-{slugify(house_name, max_len=40)}"

    # Sanity-check size vs stats.json if available. stats.json `size` field
    # is in upstream's `[H, D, W]` ordering (not [W, H, D]); we only flag a
    # mismatch when the *multiset* of extents disagrees, which would indicate
    # a real reconstruction error.
    warnings: list[str] = []
    if stats_path.exists():
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
            decl = stats.get("size")
            if isinstance(decl, list) and len(decl) == 3 and sorted(decl) != sorted([W, H, D]):
                warnings.append(f"stats_size_mismatch:declared={decl} derived=[{W},{H},{D}]")
        except Exception:
            pass
    if unmapped:
        sample = sorted(unmapped)[:10]
        warnings.append(f"unmapped_legacy_ids:{sample}")

    return {
        "id": building_id,
        "source": "craftassist",
        "source_url": "https://craftassist.s3-us-west-2.amazonaws.com/pubr/house_data.tar.gz",
        "license": "CC-BY-NC",
        "license_notes": (
            "Facebook Research craftassist / VoxelCNN dataset (Chen et al., ICCV 2019). "
            "CC-BY-NC 4.0 per the upstream repo. Research/academic use only; not redistributed."
        ),
        "title": title[:200],
        "description": (
            f"Player-built Minecraft house from the 3D-Craft dataset (Facebook Research, "
            f"craftassist project). Reconstructed from placement log "
            f"({len(placed)} records, {len(final)} final blocks)."
        )[:2000],
        "tags": {
            "category": "residential",
            "style": ["other"],
        },
        "bounding_box": {"size": [W, H, D]},
        "block_palette": {str(k): v for k, v in palette.items()},
        "voxels": voxels,
        "bot_decomposition": None,
        "metadata_quality": {
            **metrics,
            "has_labels": False,
            "ingest_warnings": warnings,
        },
        "ingest": {
            "tool": "ingest_3dcraft.py",
            "tool_version": "0.1.0",
            "source_format": "json",
            "ingested_at": now_iso(),
            "ingester_path": __file__,
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--houses-dir", type=Path, required=True)
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args(argv)

    if not args.houses_dir.is_dir():
        print(f"[ingest] {args.houses_dir} is not a directory", file=sys.stderr)
        return 2

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    rejected = 0
    total_unmapped: set[int] = set()
    house_dirs = sorted(d for d in args.houses_dir.iterdir() if d.is_dir())
    for i, house_dir in enumerate(house_dirs):
        if args.limit is not None and i >= args.limit:
            break
        doc = ingest_house(house_dir)
        if doc is None:
            rejected += 1
            continue
        for w in doc["metadata_quality"]["ingest_warnings"]:
            if w.startswith("unmapped_legacy_ids:"):
                inner = w.split(":", 1)[1]
                try:
                    total_unmapped.update(int(s) for s in inner.strip("[]").split(",") if s.strip())
                except ValueError:
                    pass
        out = PROCESSED_DIR / f"{doc['id']}.json"
        out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        written += 1

    log = (
        f"\n## {now_iso()} — 3D-Craft / VoxelCNN house_data batch\n"
        f"- source: https://craftassist.s3-us-west-2.amazonaws.com/pubr/house_data.tar.gz\n"
        f"- format: per-house dir with placed.json (action log) + stats.json + schematic.npy\n"
        f"- agent: phase-b-agent-7\n"
        f"- action: kept {written}, rejected {rejected}\n"
        f"- license: CC-BY-NC 4.0 (research-use OK; not redistributed)\n"
        f"- notes: reconstruction via voxelcnn `_load_annotation` algorithm "
        f"(walk action log, drop on B, overwrite on P); block IDs are legacy "
        f"uint8 + 4-bit meta, flattened to 1.16.5 namespaced via meta-aware "
        f"overlay; unmapped legacy IDs encountered: "
        f"{sorted(total_unmapped) if total_unmapped else 'none'}\n"
    )
    append_processing_log(log)
    print(f"[ingest] wrote {written}, rejected {rejected}, unmapped legacy IDs: {sorted(total_unmapped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
