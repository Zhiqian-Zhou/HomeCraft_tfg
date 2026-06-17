"""Convert the HuggingFace dataset `assskelad/minecraftbuildings` (and any
dataset that follows the same `(x, y, z, block_id_int)` tuple-list-per-row
convention) into canonical ReferenceBuilding JSONs in
`rag/reference_buildings/processed/`.

The dataset reports `Description` (text) + `Block Info` (string-encoded list
of 4-int tuples). Block IDs are legacy numeric (`109` = stone bricks, `155`
= quartz block, etc.) and we remap them to namespaced 1.16.5 IDs through a
flattening table.

Phase B agent: run this on a downloaded `.csv` / `.parquet` sample before
deciding whether to ingest the full dataset. Verify the legacy-to-1.16.5
mapping table is correct (it's a starter — needs the agent's eyes).

Usage:
    python tools/ingest_hf_tuplelist.py \
        --input scratch/hf_assskelad.csv \
        --source huggingface \
        --source-url https://huggingface.co/datasets/assskelad/minecraftbuildings \
        --license unknown \
        --limit 50
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from pathlib import Path

# Block Info cells can exceed the default 128 KB CSV field limit (rows reach
# ~467 KB on the assskelad dataset). Raise to sys.maxsize so wide rows parse.
csv.field_size_limit(sys.maxsize)

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


# Legacy numeric → 1.16.5 namespaced. Starter table — Phase B agent extends.
# Reference: https://minecraft.wiki/w/Java_Edition_data_values/Pre-flattening
LEGACY_TO_NAMESPACED: dict[int, str] = {
    0:   "minecraft:air",
    1:   "minecraft:stone",
    2:   "minecraft:grass_block",
    3:   "minecraft:dirt",
    4:   "minecraft:cobblestone",
    5:   "minecraft:oak_planks",
    6:   "minecraft:oak_sapling",
    7:   "minecraft:bedrock",
    8:   "minecraft:water",
    9:   "minecraft:water",
    10:  "minecraft:lava",
    11:  "minecraft:lava",
    12:  "minecraft:sand",
    13:  "minecraft:gravel",
    14:  "minecraft:gold_ore",
    15:  "minecraft:iron_ore",
    16:  "minecraft:coal_ore",
    17:  "minecraft:oak_log",
    18:  "minecraft:oak_leaves",
    19:  "minecraft:sponge",
    20:  "minecraft:glass",
    21:  "minecraft:lapis_ore",
    22:  "minecraft:lapis_block",
    23:  "minecraft:dispenser",
    24:  "minecraft:sandstone",
    25:  "minecraft:note_block",
    26:  "minecraft:red_bed",
    27:  "minecraft:powered_rail",          # legacy "golden_rail"
    28:  "minecraft:detector_rail",
    29:  "minecraft:sticky_piston",
    30:  "minecraft:cobweb",                # legacy "web"
    31:  "minecraft:grass",                 # legacy "tallgrass" (default variant is grass; data 2 is fern)
    32:  "minecraft:dead_bush",
    33:  "minecraft:piston",
    34:  "minecraft:piston_head",
    35:  "minecraft:white_wool",            # default variant; color encoded in pre-flat metadata
    37:  "minecraft:dandelion",             # legacy "yellow_flower"
    38:  "minecraft:poppy",                 # legacy "red_flower" default
    39:  "minecraft:brown_mushroom",
    40:  "minecraft:red_mushroom",
    41:  "minecraft:gold_block",
    42:  "minecraft:iron_block",
    43:  "minecraft:smooth_stone_slab",     # legacy "double_stone_slab" — closest 1.16 equivalent
    44:  "minecraft:stone_slab",
    45:  "minecraft:bricks",
    46:  "minecraft:tnt",
    47:  "minecraft:bookshelf",
    48:  "minecraft:mossy_cobblestone",
    49:  "minecraft:obsidian",
    50:  "minecraft:torch",
    51:  "minecraft:fire",
    52:  "minecraft:spawner",               # legacy "mob_spawner"
    53:  "minecraft:oak_stairs",
    54:  "minecraft:chest",
    55:  "minecraft:redstone_wire",
    56:  "minecraft:diamond_ore",
    57:  "minecraft:diamond_block",
    58:  "minecraft:crafting_table",
    59:  "minecraft:wheat",
    60:  "minecraft:farmland",
    61:  "minecraft:furnace",
    62:  "minecraft:furnace",               # legacy "lit_furnace" (state-only differentiator)
    63:  "minecraft:oak_sign",              # legacy "standing_sign"
    64:  "minecraft:oak_door",
    65:  "minecraft:ladder",
    66:  "minecraft:rail",
    67:  "minecraft:cobblestone_stairs",    # legacy "stone_stairs" == cobblestone stairs
    68:  "minecraft:oak_wall_sign",         # legacy "wall_sign"
    69:  "minecraft:lever",
    70:  "minecraft:stone_pressure_plate",
    71:  "minecraft:iron_door",
    72:  "minecraft:oak_pressure_plate",    # legacy "wooden_pressure_plate" default
    73:  "minecraft:redstone_ore",
    75:  "minecraft:redstone_torch",        # legacy "unlit_redstone_torch" (state-only)
    76:  "minecraft:redstone_torch",
    77:  "minecraft:stone_button",
    78:  "minecraft:snow",                  # legacy "snow_layer"
    79:  "minecraft:ice",
    80:  "minecraft:snow_block",            # legacy "snow" is full block
    81:  "minecraft:cactus",
    82:  "minecraft:clay",
    83:  "minecraft:sugar_cane",            # legacy "reeds"
    84:  "minecraft:jukebox",
    85:  "minecraft:oak_fence",
    86:  "minecraft:pumpkin",
    87:  "minecraft:netherrack",
    88:  "minecraft:soul_sand",
    89:  "minecraft:glowstone",
    90:  "minecraft:nether_portal",         # legacy "portal"
    91:  "minecraft:jack_o_lantern",        # legacy "lit_pumpkin"
    92:  "minecraft:cake",
    93:  "minecraft:repeater",              # legacy "unpowered_repeater"
    94:  "minecraft:repeater",              # legacy "powered_repeater"
    95:  "minecraft:white_stained_glass",   # default; color in metadata
    96:  "minecraft:oak_trapdoor",          # legacy "trapdoor" default
    97:  "minecraft:infested_stone",        # legacy "monster_egg" default
    98:  "minecraft:stone_bricks",
    99:  "minecraft:brown_mushroom_block",
    100: "minecraft:red_mushroom_block",
    101: "minecraft:iron_bars",
    102: "minecraft:glass_pane",
    103: "minecraft:melon",                 # legacy "melon_block"
    104: "minecraft:pumpkin_stem",
    105: "minecraft:melon_stem",
    106: "minecraft:vine",
    107: "minecraft:oak_fence_gate",        # legacy "fence_gate" default
    108: "minecraft:brick_stairs",
    109: "minecraft:stone_brick_stairs",
    110: "minecraft:mycelium",
    111: "minecraft:lily_pad",              # legacy "waterlily"
    112: "minecraft:nether_bricks",         # legacy "nether_brick" (the block)
    113: "minecraft:nether_brick_fence",
    114: "minecraft:nether_brick_stairs",
    116: "minecraft:enchanting_table",
    117: "minecraft:brewing_stand",
    118: "minecraft:cauldron",
    119: "minecraft:end_portal",
    120: "minecraft:end_portal_frame",
    121: "minecraft:end_stone",
    123: "minecraft:redstone_lamp",
    124: "minecraft:redstone_lamp",         # legacy "lit_redstone_lamp"
    125: "minecraft:oak_planks",            # legacy "double_wooden_slab" default — best approx
    126: "minecraft:oak_slab",
    127: "minecraft:cocoa",
    128: "minecraft:sandstone_stairs",
    129: "minecraft:emerald_ore",
    130: "minecraft:ender_chest",
    131: "minecraft:tripwire_hook",
    132: "minecraft:tripwire",
    133: "minecraft:emerald_block",
    134: "minecraft:spruce_stairs",
    135: "minecraft:birch_stairs",
    136: "minecraft:jungle_stairs",
    137: "minecraft:command_block",
    138: "minecraft:beacon",
    139: "minecraft:cobblestone_wall",
    140: "minecraft:flower_pot",
    141: "minecraft:carrots",
    142: "minecraft:potatoes",
    143: "minecraft:oak_button",            # legacy "wooden_button" default
    144: "minecraft:skeleton_skull",        # legacy "skull" default; type encoded in metadata
    145: "minecraft:anvil",
    146: "minecraft:trapped_chest",
    147: "minecraft:light_weighted_pressure_plate",
    148: "minecraft:heavy_weighted_pressure_plate",
    149: "minecraft:comparator",            # legacy "unpowered_comparator"
    150: "minecraft:comparator",            # legacy "powered_comparator"
    151: "minecraft:daylight_detector",
    152: "minecraft:redstone_block",
    153: "minecraft:nether_quartz_ore",
    154: "minecraft:hopper",
    155: "minecraft:quartz_block",
    156: "minecraft:quartz_stairs",
    157: "minecraft:activator_rail",
    158: "minecraft:dropper",
    159: "minecraft:white_terracotta",      # legacy "stained_hardened_clay" default; color in meta
    160: "minecraft:white_stained_glass_pane",  # default; color in meta
    161: "minecraft:acacia_leaves",         # legacy "leaves2" default (acacia/dark_oak)
    162: "minecraft:acacia_log",            # legacy "log2" default
    163: "minecraft:acacia_stairs",
    164: "minecraft:dark_oak_stairs",
    165: "minecraft:slime_block",           # legacy "slime"
    166: "minecraft:barrier",
    167: "minecraft:iron_trapdoor",
    168: "minecraft:prismarine",
    169: "minecraft:sea_lantern",
    170: "minecraft:hay_block",
    171: "minecraft:white_carpet",          # legacy "carpet" default; color in meta
    172: "minecraft:terracotta",            # legacy "hardened_clay"
    173: "minecraft:coal_block",
    174: "minecraft:packed_ice",
    175: "minecraft:sunflower",             # legacy "double_plant" default (sunflower)
    176: "minecraft:white_banner",          # legacy "standing_banner" default
    177: "minecraft:white_wall_banner",     # legacy "wall_banner"
    179: "minecraft:red_sandstone",
    180: "minecraft:red_sandstone_stairs",
    181: "minecraft:red_sandstone_slab",
    182: "minecraft:red_sandstone_slab",    # legacy "stone_slab2"
    183: "minecraft:spruce_fence_gate",
    184: "minecraft:birch_fence_gate",
    185: "minecraft:jungle_fence_gate",
    186: "minecraft:dark_oak_fence_gate",
    187: "minecraft:acacia_fence_gate",
    188: "minecraft:spruce_fence",
    189: "minecraft:birch_fence",
    190: "minecraft:jungle_fence",
    191: "minecraft:dark_oak_fence",
    192: "minecraft:acacia_fence",
    193: "minecraft:spruce_door",
    194: "minecraft:birch_door",
    195: "minecraft:jungle_door",
    196: "minecraft:acacia_door",
    197: "minecraft:dark_oak_door",
    198: "minecraft:end_rod",
    199: "minecraft:chorus_plant",
    200: "minecraft:chorus_flower",
    201: "minecraft:purpur_block",
    202: "minecraft:purpur_pillar",
    203: "minecraft:purpur_stairs",
    205: "minecraft:purpur_slab",
    206: "minecraft:end_stone_bricks",      # legacy "end_bricks"
    207: "minecraft:beetroots",
    208: "minecraft:grass_path",
    212: "minecraft:frosted_ice",
    213: "minecraft:magma_block",           # legacy "magma"
    214: "minecraft:nether_wart_block",
    215: "minecraft:red_nether_bricks",     # legacy "red_nether_brick"
    216: "minecraft:bone_block",
    218: "minecraft:observer",
    251: "minecraft:white_concrete",        # default; color in meta
    252: "minecraft:white_concrete_powder", # default; color in meta
    255: "minecraft:structure_block",
}


def remap(block_int: int) -> str:
    return LEGACY_TO_NAMESPACED.get(block_int, "minecraft:stone")


def parse_block_info(raw: str) -> list[tuple[int, int, int, int]]:
    """Block Info comes as a stringified Python list of 4-tuples."""
    parsed = ast.literal_eval(raw)
    return [tuple(t) for t in parsed]


def ingest_row(
    *,
    description: str,
    block_info_str: str,
    row_idx: int,
    source: str,
    source_url: str,
    license_value: str,
    default_category: str,
    default_style: list[str],
) -> dict | None:
    try:
        tuples = parse_block_info(block_info_str)
    except (ValueError, SyntaxError) as exc:
        print(f"[ingest] row {row_idx}: bad Block Info ({exc})", file=sys.stderr)
        return None

    if not tuples:
        return None

    xs = [t[0] for t in tuples]
    ys = [t[1] for t in tuples]
    zs = [t[2] for t in tuples]
    minx, miny, minz = min(xs), min(ys), min(zs)
    maxx, maxy, maxz = max(xs), max(ys), max(zs)
    W = maxx - minx + 1
    H = maxy - miny + 1
    D = maxz - minz + 1

    if max(W, H, D) > 512:
        print(f"[ingest] row {row_idx}: too large ({W}x{H}x{D})", file=sys.stderr)
        return None

    blocks_seq = [remap(t[3]) for t in tuples]
    palette = compress_palette(blocks_seq)  # drops air
    rev = {v: k for k, v in palette.items()}

    voxels: list[list[int]] = []
    for (x, y, z, b_int), b_id in zip(tuples, blocks_seq):
        if _is_air(b_id):
            continue
        voxels.append([x - minx, y - miny, z - minz, rev[b_id]])

    if not voxels:
        return None

    metrics = populated_interior_metrics(voxels, palette)
    title = (description.strip().split("\n", 1)[0] or f"hf-build-{row_idx:05d}").strip()
    building_id = f"hf-asskd-{row_idx:05d}-{slugify(title, max_len=30)}"

    return {
        "id": building_id,
        "source": source,
        "source_url": source_url,
        "license": license_value,
        "title": title[:200],
        "description": description.strip()[:2000],
        "tags": {
            "category": default_category,
            "style": default_style,
        },
        "bounding_box": {"size": [W, H, D]},
        "block_palette": {str(k): v for k, v in palette.items()},
        "voxels": voxels,
        "bot_decomposition": None,
        "metadata_quality": {
            **metrics,
            "has_labels": False,
            "ingest_warnings": (
                ["legacy_block_id_fallback"]
                if any(t[3] not in LEGACY_TO_NAMESPACED for t in tuples)
                else []
            ),
        },
        "ingest": {
            "tool": "ingest_hf_tuplelist.py",
            "tool_version": "0.1.0",
            "source_format": "json",
            "ingested_at": now_iso(),
            "ingester_path": __file__,
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--source", default="huggingface")
    p.add_argument("--source-url", required=True)
    p.add_argument("--license", default="unknown")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--category", default="residential")
    p.add_argument("--style", nargs="+", default=["other"])
    args = p.parse_args(argv)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    rejected = 0
    with args.input.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            if args.limit and i >= args.limit:
                break
            doc = ingest_row(
                description=row.get("Description", ""),
                block_info_str=row.get("Block Info", ""),
                row_idx=i,
                source=args.source,
                source_url=args.source_url,
                license_value=args.license,
                default_category=args.category,
                default_style=args.style,
            )
            if doc is None:
                rejected += 1
                continue
            out = PROCESSED_DIR / f"{doc['id']}.json"
            out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
            written += 1

    append_processing_log(
        f"\n## {now_iso()} — HF assskelad/minecraftbuildings batch\n"
        f"- source: {args.source_url}\n"
        f"- format: csv (tuple-list)\n"
        f"- action: kept {written}, rejected {rejected}\n"
        f"- license: {args.license}\n"
    )
    print(f"[ingest] wrote {written}, rejected {rejected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
