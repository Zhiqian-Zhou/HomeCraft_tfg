"""Convert a Mojang Minecraft structure-block `.nbt` file into a canonical
ReferenceBuilding JSON in rag/reference_buildings/processed/.

Format reference: https://minecraft.wiki/w/Structure_Block_file_format

The Mojang structure-block NBT format has the following top-level tags:
- size: List[Int] [X, Y, Z]
- palette: List[Compound]
    - Name: String (namespaced block id, e.g. "minecraft:oak_planks")
    - Properties: Compound (optional, blockstate as string→string map)
- blocks: List[Compound]
    - state: Int (index into palette)
    - pos: List[Int] [x, y, z]   (already 0-based local coords)
    - nbt: Compound (optional tile-entity data; we ignore for now)
- entities: List[Compound] (ignored)
- DataVersion: Int

This script:
  1. Loads the .nbt with nbtlib (gzip handling is built-in).
  2. Builds a canonical block_id string for each palette entry. If the entry
     has Properties, we append `[k1=v1,k2=v2,...]` (sorted, lowercased).
  3. Re-compresses the palette via common.compress_palette so air sits at
     index 0 and the canonical ordering matches other ingesters.
  4. Emits one voxel per block in the input blocks list.

Usage:
    python tools/ingest_nbt.py \
        --input rag/reference_buildings/raw/nbt_datapacks/<repo>/<file>.nbt \
        --source github \
        --source-url https://github.com/<repo>/blob/<branch>/<path> \
        --license MIT \
        --title "Hobbit hole" \
        --category residential \
        --style fantasy rustic
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
    _is_air,
    append_processing_log,
    compress_palette,
    now_iso,
    populated_interior_metrics,
    slugify,
)

# Schema constraint: palette values must match this regex
_PALETTE_RE = re.compile(r"^minecraft:[a-z0-9_]+(\[[a-z0-9_=,]+\])?$")
# A 1.16.5-style namespaced fallback.
_NAME_FALLBACK = "minecraft:stone"


# Downsample table: blocks added in MC 1.17+ → nearest 1.16.5 equivalent.
# The targets are intentionally drab/permissive so the schema regex accepts
# them and the resulting buildings stay visually coherent. When a precise
# match is impossible we fall back to a generic stand-in (e.g. cobblestone).
# Bare block names only — blockstate suffixes are stripped before lookup.
BLOCK_REMAP_1_17_PLUS: dict[str, str] = {
    # --- 1.17 Caves & Cliffs Part 1 ---
    "minecraft:candle": "minecraft:torch",
    "minecraft:white_candle": "minecraft:torch",
    "minecraft:orange_candle": "minecraft:torch",
    "minecraft:magenta_candle": "minecraft:torch",
    "minecraft:light_blue_candle": "minecraft:torch",
    "minecraft:yellow_candle": "minecraft:torch",
    "minecraft:lime_candle": "minecraft:torch",
    "minecraft:pink_candle": "minecraft:torch",
    "minecraft:gray_candle": "minecraft:torch",
    "minecraft:light_gray_candle": "minecraft:torch",
    "minecraft:cyan_candle": "minecraft:torch",
    "minecraft:purple_candle": "minecraft:torch",
    "minecraft:blue_candle": "minecraft:torch",
    "minecraft:brown_candle": "minecraft:torch",
    "minecraft:green_candle": "minecraft:torch",
    "minecraft:red_candle": "minecraft:torch",
    "minecraft:black_candle": "minecraft:torch",
    "minecraft:azalea": "minecraft:oak_leaves",
    "minecraft:flowering_azalea": "minecraft:oak_leaves",
    "minecraft:azalea_leaves": "minecraft:oak_leaves",
    "minecraft:flowering_azalea_leaves": "minecraft:oak_leaves",
    "minecraft:potted_azalea_bush": "minecraft:flower_pot",
    "minecraft:potted_flowering_azalea_bush": "minecraft:flower_pot",
    "minecraft:moss_block": "minecraft:green_concrete_powder",
    "minecraft:moss_carpet": "minecraft:green_carpet",
    "minecraft:big_dripleaf": "minecraft:lily_pad",
    "minecraft:big_dripleaf_stem": "minecraft:vine",
    "minecraft:small_dripleaf": "minecraft:fern",
    "minecraft:hanging_roots": "minecraft:vine",
    "minecraft:rooted_dirt": "minecraft:dirt",
    "minecraft:tinted_glass": "minecraft:gray_stained_glass",
    "minecraft:glow_lichen": "minecraft:vine",
    "minecraft:dirt_path": "minecraft:grass_path",  # renamed in 1.17
    "minecraft:short_grass": "minecraft:grass",     # renamed in 1.20
    "minecraft:cave_vines": "minecraft:vine",
    "minecraft:cave_vines_plant": "minecraft:vine",
    "minecraft:spore_blossom": "minecraft:vine",
    "minecraft:water_cauldron": "minecraft:cauldron",
    "minecraft:lava_cauldron": "minecraft:cauldron",
    "minecraft:powder_snow_cauldron": "minecraft:cauldron",
    "minecraft:powder_snow": "minecraft:snow_block",
    "minecraft:potted_torchflower": "minecraft:flower_pot",
    "minecraft:torchflower": "minecraft:dandelion",
    "minecraft:potted_mangrove_propagule": "minecraft:flower_pot",
    "minecraft:pointed_dripstone": "minecraft:stone",
    "minecraft:dripstone_block": "minecraft:stone",
    "minecraft:amethyst_block": "minecraft:purpur_block",
    "minecraft:budding_amethyst": "minecraft:purpur_block",
    "minecraft:amethyst_cluster": "minecraft:purpur_block",
    "minecraft:small_amethyst_bud": "minecraft:purpur_block",
    "minecraft:medium_amethyst_bud": "minecraft:purpur_block",
    "minecraft:large_amethyst_bud": "minecraft:purpur_block",
    "minecraft:calcite": "minecraft:diorite",
    "minecraft:tuff": "minecraft:andesite",
    "minecraft:raw_iron_block": "minecraft:iron_block",
    "minecraft:raw_copper_block": "minecraft:orange_terracotta",
    "minecraft:raw_gold_block": "minecraft:gold_block",
    # --- 1.18 Caves & Cliffs Part 2 (deepslate variants) ---
    "minecraft:deepslate": "minecraft:cobblestone",
    "minecraft:cobbled_deepslate": "minecraft:cobblestone",
    "minecraft:cobbled_deepslate_slab": "minecraft:cobblestone_slab",
    "minecraft:cobbled_deepslate_stairs": "minecraft:cobblestone_stairs",
    "minecraft:cobbled_deepslate_wall": "minecraft:cobblestone_wall",
    "minecraft:polished_deepslate": "minecraft:stone",
    "minecraft:polished_deepslate_slab": "minecraft:stone_slab",
    "minecraft:polished_deepslate_stairs": "minecraft:stone_brick_stairs",
    "minecraft:polished_deepslate_wall": "minecraft:stone_brick_wall",
    "minecraft:deepslate_bricks": "minecraft:stone_bricks",
    "minecraft:deepslate_brick_slab": "minecraft:stone_brick_slab",
    "minecraft:deepslate_brick_stairs": "minecraft:stone_brick_stairs",
    "minecraft:deepslate_brick_wall": "minecraft:stone_brick_wall",
    "minecraft:cracked_deepslate_bricks": "minecraft:cracked_stone_bricks",
    "minecraft:deepslate_tiles": "minecraft:stone_bricks",
    "minecraft:deepslate_tile_slab": "minecraft:stone_brick_slab",
    "minecraft:deepslate_tile_stairs": "minecraft:stone_brick_stairs",
    "minecraft:deepslate_tile_wall": "minecraft:stone_brick_wall",
    "minecraft:cracked_deepslate_tiles": "minecraft:cracked_stone_bricks",
    "minecraft:chiseled_deepslate": "minecraft:chiseled_stone_bricks",
    "minecraft:deepslate_coal_ore": "minecraft:coal_ore",
    "minecraft:deepslate_iron_ore": "minecraft:iron_ore",
    "minecraft:deepslate_gold_ore": "minecraft:gold_ore",
    "minecraft:deepslate_diamond_ore": "minecraft:diamond_ore",
    "minecraft:deepslate_emerald_ore": "minecraft:emerald_ore",
    "minecraft:deepslate_lapis_ore": "minecraft:lapis_ore",
    "minecraft:deepslate_redstone_ore": "minecraft:redstone_ore",
    "minecraft:copper_ore": "minecraft:iron_ore",
    "minecraft:deepslate_copper_ore": "minecraft:iron_ore",
    "minecraft:smooth_basalt": "minecraft:basalt",
    # --- 1.19 Wild Update (mangrove, mud) ---
    "minecraft:mangrove_log": "minecraft:dark_oak_log",
    "minecraft:mangrove_wood": "minecraft:dark_oak_wood",
    "minecraft:stripped_mangrove_log": "minecraft:stripped_dark_oak_log",
    "minecraft:stripped_mangrove_wood": "minecraft:stripped_dark_oak_wood",
    "minecraft:mangrove_planks": "minecraft:dark_oak_planks",
    "minecraft:mangrove_slab": "minecraft:dark_oak_slab",
    "minecraft:mangrove_stairs": "minecraft:dark_oak_stairs",
    "minecraft:mangrove_fence": "minecraft:dark_oak_fence",
    "minecraft:mangrove_fence_gate": "minecraft:dark_oak_fence_gate",
    "minecraft:mangrove_door": "minecraft:dark_oak_door",
    "minecraft:mangrove_trapdoor": "minecraft:dark_oak_trapdoor",
    "minecraft:mangrove_button": "minecraft:dark_oak_button",
    "minecraft:mangrove_pressure_plate": "minecraft:dark_oak_pressure_plate",
    "minecraft:mangrove_sign": "minecraft:dark_oak_sign",
    "minecraft:mangrove_wall_sign": "minecraft:dark_oak_wall_sign",
    "minecraft:mangrove_leaves": "minecraft:dark_oak_leaves",
    "minecraft:mangrove_roots": "minecraft:dark_oak_log",
    "minecraft:muddy_mangrove_roots": "minecraft:dark_oak_log",
    "minecraft:mangrove_propagule": "minecraft:dark_oak_sapling",
    "minecraft:mud": "minecraft:dirt",
    "minecraft:packed_mud": "minecraft:coarse_dirt",
    "minecraft:mud_bricks": "minecraft:bricks",
    "minecraft:mud_brick_slab": "minecraft:brick_slab",
    "minecraft:mud_brick_stairs": "minecraft:brick_stairs",
    "minecraft:mud_brick_wall": "minecraft:brick_wall",
    "minecraft:sculk": "minecraft:black_concrete",
    "minecraft:sculk_vein": "minecraft:vine",
    "minecraft:sculk_catalyst": "minecraft:black_concrete",
    "minecraft:sculk_sensor": "minecraft:gray_concrete",
    "minecraft:sculk_shrieker": "minecraft:gray_concrete",
    "minecraft:reinforced_deepslate": "minecraft:obsidian",
    "minecraft:frogspawn": "minecraft:lily_pad",
    "minecraft:ochre_froglight": "minecraft:glowstone",
    "minecraft:verdant_froglight": "minecraft:glowstone",
    "minecraft:pearlescent_froglight": "minecraft:glowstone",
    # --- 1.19.3+ wall hanging / hanging signs (trails & tales prep) ---
    "minecraft:oak_hanging_sign": "minecraft:oak_wall_sign",
    "minecraft:spruce_hanging_sign": "minecraft:spruce_wall_sign",
    "minecraft:birch_hanging_sign": "minecraft:oak_wall_sign",
    "minecraft:jungle_hanging_sign": "minecraft:jungle_wall_sign",
    "minecraft:acacia_hanging_sign": "minecraft:acacia_wall_sign",
    "minecraft:dark_oak_hanging_sign": "minecraft:dark_oak_wall_sign",
    "minecraft:mangrove_hanging_sign": "minecraft:dark_oak_wall_sign",
    "minecraft:oak_wall_hanging_sign": "minecraft:oak_wall_sign",
    "minecraft:spruce_wall_hanging_sign": "minecraft:spruce_wall_sign",
    "minecraft:birch_wall_hanging_sign": "minecraft:oak_wall_sign",
    "minecraft:jungle_wall_hanging_sign": "minecraft:jungle_wall_sign",
    "minecraft:acacia_wall_hanging_sign": "minecraft:acacia_wall_sign",
    "minecraft:dark_oak_wall_hanging_sign": "minecraft:dark_oak_wall_sign",
    "minecraft:mangrove_wall_hanging_sign": "minecraft:dark_oak_wall_sign",
    # --- 1.20 Trails & Tales (cherry, bamboo, archaeology) ---
    "minecraft:cherry_log": "minecraft:birch_log",
    "minecraft:cherry_wood": "minecraft:birch_wood",
    "minecraft:stripped_cherry_log": "minecraft:stripped_birch_log",
    "minecraft:stripped_cherry_wood": "minecraft:stripped_birch_wood",
    "minecraft:cherry_planks": "minecraft:birch_planks",
    "minecraft:cherry_slab": "minecraft:birch_slab",
    "minecraft:cherry_stairs": "minecraft:birch_stairs",
    "minecraft:cherry_fence": "minecraft:birch_fence",
    "minecraft:cherry_fence_gate": "minecraft:birch_fence_gate",
    "minecraft:cherry_door": "minecraft:birch_door",
    "minecraft:cherry_trapdoor": "minecraft:birch_trapdoor",
    "minecraft:cherry_button": "minecraft:birch_button",
    "minecraft:cherry_pressure_plate": "minecraft:birch_pressure_plate",
    "minecraft:cherry_sign": "minecraft:birch_sign",
    "minecraft:cherry_wall_sign": "minecraft:birch_wall_sign",
    "minecraft:cherry_hanging_sign": "minecraft:birch_wall_sign",
    "minecraft:cherry_wall_hanging_sign": "minecraft:birch_wall_sign",
    "minecraft:cherry_leaves": "minecraft:birch_leaves",
    "minecraft:cherry_sapling": "minecraft:birch_sapling",
    "minecraft:pink_petals": "minecraft:pink_carpet",
    "minecraft:potted_cherry_sapling": "minecraft:flower_pot",
    "minecraft:bamboo_planks": "minecraft:jungle_planks",
    "minecraft:bamboo_mosaic": "minecraft:jungle_planks",
    "minecraft:bamboo_slab": "minecraft:jungle_slab",
    "minecraft:bamboo_mosaic_slab": "minecraft:jungle_slab",
    "minecraft:bamboo_stairs": "minecraft:jungle_stairs",
    "minecraft:bamboo_mosaic_stairs": "minecraft:jungle_stairs",
    "minecraft:bamboo_fence": "minecraft:jungle_fence",
    "minecraft:bamboo_fence_gate": "minecraft:jungle_fence_gate",
    "minecraft:bamboo_door": "minecraft:jungle_door",
    "minecraft:bamboo_trapdoor": "minecraft:jungle_trapdoor",
    "minecraft:bamboo_button": "minecraft:jungle_button",
    "minecraft:bamboo_pressure_plate": "minecraft:jungle_pressure_plate",
    "minecraft:bamboo_sign": "minecraft:jungle_sign",
    "minecraft:bamboo_wall_sign": "minecraft:jungle_wall_sign",
    "minecraft:bamboo_hanging_sign": "minecraft:jungle_wall_sign",
    "minecraft:bamboo_wall_hanging_sign": "minecraft:jungle_wall_sign",
    "minecraft:bamboo_block": "minecraft:jungle_log",
    "minecraft:stripped_bamboo_block": "minecraft:stripped_jungle_log",
    "minecraft:chiseled_bookshelf": "minecraft:bookshelf",
    "minecraft:decorated_pot": "minecraft:flower_pot",
    "minecraft:suspicious_sand": "minecraft:sand",
    "minecraft:suspicious_gravel": "minecraft:gravel",
    "minecraft:torchflower_crop": "minecraft:dandelion",
    "minecraft:pitcher_plant": "minecraft:rose_bush",
    "minecraft:pitcher_crop": "minecraft:rose_bush",
    "minecraft:potted_pitcher_plant": "minecraft:flower_pot",
    "minecraft:calibrated_sculk_sensor": "minecraft:gray_concrete",
    # --- 1.21 Tricky Trials (copper, tuff, trial spawner) ---
    "minecraft:copper_block": "minecraft:orange_terracotta",
    "minecraft:exposed_copper": "minecraft:orange_terracotta",
    "minecraft:weathered_copper": "minecraft:lime_terracotta",
    "minecraft:oxidized_copper": "minecraft:cyan_terracotta",
    "minecraft:waxed_copper_block": "minecraft:orange_terracotta",
    "minecraft:waxed_exposed_copper": "minecraft:orange_terracotta",
    "minecraft:waxed_weathered_copper": "minecraft:lime_terracotta",
    "minecraft:waxed_oxidized_copper": "minecraft:cyan_terracotta",
    "minecraft:cut_copper": "minecraft:orange_terracotta",
    "minecraft:exposed_cut_copper": "minecraft:orange_terracotta",
    "minecraft:weathered_cut_copper": "minecraft:lime_terracotta",
    "minecraft:oxidized_cut_copper": "minecraft:cyan_terracotta",
    "minecraft:waxed_cut_copper": "minecraft:orange_terracotta",
    "minecraft:waxed_exposed_cut_copper": "minecraft:orange_terracotta",
    "minecraft:waxed_weathered_cut_copper": "minecraft:lime_terracotta",
    "minecraft:waxed_oxidized_cut_copper": "minecraft:cyan_terracotta",
    "minecraft:cut_copper_slab": "minecraft:smooth_red_sandstone_slab",
    "minecraft:exposed_cut_copper_slab": "minecraft:smooth_red_sandstone_slab",
    "minecraft:weathered_cut_copper_slab": "minecraft:prismarine_slab",
    "minecraft:oxidized_cut_copper_slab": "minecraft:prismarine_slab",
    "minecraft:waxed_cut_copper_slab": "minecraft:smooth_red_sandstone_slab",
    "minecraft:waxed_exposed_cut_copper_slab": "minecraft:smooth_red_sandstone_slab",
    "minecraft:waxed_weathered_cut_copper_slab": "minecraft:prismarine_slab",
    "minecraft:waxed_oxidized_cut_copper_slab": "minecraft:prismarine_slab",
    "minecraft:cut_copper_stairs": "minecraft:smooth_red_sandstone_stairs",
    "minecraft:exposed_cut_copper_stairs": "minecraft:smooth_red_sandstone_stairs",
    "minecraft:weathered_cut_copper_stairs": "minecraft:prismarine_stairs",
    "minecraft:oxidized_cut_copper_stairs": "minecraft:prismarine_stairs",
    "minecraft:waxed_cut_copper_stairs": "minecraft:smooth_red_sandstone_stairs",
    "minecraft:waxed_exposed_cut_copper_stairs": "minecraft:smooth_red_sandstone_stairs",
    "minecraft:waxed_weathered_cut_copper_stairs": "minecraft:prismarine_stairs",
    "minecraft:waxed_oxidized_cut_copper_stairs": "minecraft:prismarine_stairs",
    "minecraft:chiseled_copper": "minecraft:orange_terracotta",
    "minecraft:exposed_chiseled_copper": "minecraft:orange_terracotta",
    "minecraft:weathered_chiseled_copper": "minecraft:lime_terracotta",
    "minecraft:oxidized_chiseled_copper": "minecraft:cyan_terracotta",
    "minecraft:waxed_chiseled_copper": "minecraft:orange_terracotta",
    "minecraft:waxed_exposed_chiseled_copper": "minecraft:orange_terracotta",
    "minecraft:waxed_weathered_chiseled_copper": "minecraft:lime_terracotta",
    "minecraft:waxed_oxidized_chiseled_copper": "minecraft:cyan_terracotta",
    "minecraft:copper_door": "minecraft:iron_door",
    "minecraft:exposed_copper_door": "minecraft:iron_door",
    "minecraft:weathered_copper_door": "minecraft:iron_door",
    "minecraft:oxidized_copper_door": "minecraft:iron_door",
    "minecraft:waxed_copper_door": "minecraft:iron_door",
    "minecraft:waxed_exposed_copper_door": "minecraft:iron_door",
    "minecraft:waxed_weathered_copper_door": "minecraft:iron_door",
    "minecraft:waxed_oxidized_copper_door": "minecraft:iron_door",
    "minecraft:copper_trapdoor": "minecraft:iron_trapdoor",
    "minecraft:exposed_copper_trapdoor": "minecraft:iron_trapdoor",
    "minecraft:weathered_copper_trapdoor": "minecraft:iron_trapdoor",
    "minecraft:oxidized_copper_trapdoor": "minecraft:iron_trapdoor",
    "minecraft:waxed_copper_trapdoor": "minecraft:iron_trapdoor",
    "minecraft:waxed_exposed_copper_trapdoor": "minecraft:iron_trapdoor",
    "minecraft:waxed_weathered_copper_trapdoor": "minecraft:iron_trapdoor",
    "minecraft:waxed_oxidized_copper_trapdoor": "minecraft:iron_trapdoor",
    "minecraft:copper_grate": "minecraft:iron_bars",
    "minecraft:exposed_copper_grate": "minecraft:iron_bars",
    "minecraft:weathered_copper_grate": "minecraft:iron_bars",
    "minecraft:oxidized_copper_grate": "minecraft:iron_bars",
    "minecraft:waxed_copper_grate": "minecraft:iron_bars",
    "minecraft:waxed_exposed_copper_grate": "minecraft:iron_bars",
    "minecraft:waxed_weathered_copper_grate": "minecraft:iron_bars",
    "minecraft:waxed_oxidized_copper_grate": "minecraft:iron_bars",
    "minecraft:copper_bulb": "minecraft:redstone_lamp",
    "minecraft:exposed_copper_bulb": "minecraft:redstone_lamp",
    "minecraft:weathered_copper_bulb": "minecraft:redstone_lamp",
    "minecraft:oxidized_copper_bulb": "minecraft:redstone_lamp",
    "minecraft:waxed_copper_bulb": "minecraft:redstone_lamp",
    "minecraft:waxed_exposed_copper_bulb": "minecraft:redstone_lamp",
    "minecraft:waxed_weathered_copper_bulb": "minecraft:redstone_lamp",
    "minecraft:waxed_oxidized_copper_bulb": "minecraft:redstone_lamp",
    "minecraft:lightning_rod": "minecraft:iron_bars",
    "minecraft:polished_tuff": "minecraft:polished_andesite",
    "minecraft:polished_tuff_slab": "minecraft:polished_andesite_slab",
    "minecraft:polished_tuff_stairs": "minecraft:polished_andesite_stairs",
    "minecraft:polished_tuff_wall": "minecraft:stone_brick_wall",
    "minecraft:tuff_bricks": "minecraft:stone_bricks",
    "minecraft:tuff_brick_slab": "minecraft:stone_brick_slab",
    "minecraft:tuff_brick_stairs": "minecraft:stone_brick_stairs",
    "minecraft:tuff_brick_wall": "minecraft:stone_brick_wall",
    "minecraft:chiseled_tuff": "minecraft:chiseled_stone_bricks",
    "minecraft:chiseled_tuff_bricks": "minecraft:chiseled_stone_bricks",
    "minecraft:tuff_slab": "minecraft:cobblestone_slab",
    "minecraft:tuff_stairs": "minecraft:cobblestone_stairs",
    "minecraft:tuff_wall": "minecraft:cobblestone_wall",
    "minecraft:crafter": "minecraft:crafting_table",
    "minecraft:trial_spawner": "minecraft:spawner",
    "minecraft:vault": "minecraft:chest",
    "minecraft:heavy_core": "minecraft:obsidian",
    # --- structure markers (1.17+ jigsaw) — drop to stone so they don't pollute ---
    "minecraft:jigsaw": "minecraft:stone",
    "minecraft:structure_block": "minecraft:stone",
    "minecraft:structure_void": "minecraft:air",  # will be dropped by _is_air
}


def _remap_block_name(name: str, remap_log: set[tuple[str, str]] | None = None) -> str:
    """Apply the 1.17+ → 1.16.5 downsample table to a bare block name."""
    target = BLOCK_REMAP_1_17_PLUS.get(name)
    if target is None:
        return name
    if remap_log is not None:
        remap_log.add((name, target))
    return target


def _serialize_palette_entry(entry, remap_log: set[tuple[str, str]] | None = None) -> str:
    """Convert a palette Compound to a `minecraft:block[k=v,...]` string.

    Returns the block ID matching the ReferenceBuilding palette regex.
    Properties whose values are not lowercase identifiers (e.g. contain digits
    only or `=`) are dropped to keep the regex happy; the wall/door shape is
    not needed for building-level RAG.

    Any block introduced after MC 1.16.5 is downsampled via
    BLOCK_REMAP_1_17_PLUS so the resulting palette stays placeable on a 1.16.5
    world. Remapping happens BEFORE properties are merged: when the target
    block uses a different state set (e.g. waxed_*_door → iron_door) we drop
    properties that the target wouldn't accept to keep the canonical form
    deterministic and the schema regex happy.
    """
    name = str(entry.get("Name", _NAME_FALLBACK))
    if not name.startswith("minecraft:"):
        name = f"minecraft:{name}"

    # Apply 1.17+ → 1.16.5 downsample BEFORE property handling
    remapped = _remap_block_name(name, remap_log=remap_log)
    if remapped != name:
        # The target block may not share the same property keys as the source
        # (e.g. iron_door has its own state set). Drop all properties to be
        # safe — losing facing/half on a remap is acceptable since the build
        # is already a structural approximation.
        return remapped

    props = entry.get("Properties")
    if not props:
        return name

    pairs: list[tuple[str, str]] = []
    for k, v in props.items():
        ks = str(k).lower()
        vs = str(v).lower()
        # The schema allows only [a-z0-9_=,] inside the bracket — be strict.
        if not re.fullmatch(r"[a-z0-9_]+", ks):
            continue
        if not re.fullmatch(r"[a-z0-9_]+", vs):
            continue
        pairs.append((ks, vs))
    if not pairs:
        return name
    pairs.sort()
    inside = ",".join(f"{k}={v}" for k, v in pairs)
    candidate = f"{name}[{inside}]"
    if not _PALETTE_RE.match(candidate):
        # Properties have weird chars (rare); fall back to bare name.
        return name
    return candidate


def _parse_nbt(path: Path) -> tuple[list[list[int]], dict[int, str], tuple[int, int, int], list[str]]:
    """Parse a Mojang structure-block .nbt. Returns (voxels, palette, (W,H,D), warnings)."""
    try:
        import nbtlib  # type: ignore
    except ImportError as exc:
        raise SystemExit("nbtlib not installed: pip install nbtlib") from exc

    nbt = nbtlib.load(str(path))
    root = nbt.root if hasattr(nbt, "root") else nbt

    warnings: list[str] = []

    size = root.get("size")
    if size is None or len(size) != 3:
        raise ValueError(f"{path}: missing/invalid `size` tag")
    W, H, D = int(size[0]), int(size[1]), int(size[2])

    palette_list = root.get("palette")
    if palette_list is None:
        # Multi-palette variant (rare). Use first.
        palettes = root.get("palettes")
        if not palettes:
            raise ValueError(f"{path}: no palette/palettes tag")
        palette_list = palettes[0]
        warnings.append("multi-palette nbt; used palettes[0]")

    remap_log: set[tuple[str, str]] = set()
    raw_palette: list[str] = [_serialize_palette_entry(e, remap_log=remap_log) for e in palette_list]
    if remap_log:
        sample = ", ".join(f"{a}->{b}" for a, b in sorted(remap_log)[:8])
        suffix = "" if len(remap_log) <= 8 else f" (+{len(remap_log) - 8} more)"
        warnings.append(f"1.17+ downsample applied to {len(remap_log)} block ids: {sample}{suffix}")

    blocks_tag = root.get("blocks")
    if blocks_tag is None:
        raise ValueError(f"{path}: missing `blocks` tag")

    # Map from input palette idx -> block string
    block_strings_stream: list[str] = []
    raw_voxels: list[tuple[int, int, int, str]] = []
    for b in blocks_tag:
        state = int(b.get("state"))
        pos = b.get("pos")
        x, y, z = int(pos[0]), int(pos[1]), int(pos[2])
        if state >= len(raw_palette):
            warnings.append(f"voxel state {state} out of palette range; skipped")
            continue
        block_id = raw_palette[state]
        if not (0 <= x < W and 0 <= y < H and 0 <= z < D):
            warnings.append(f"voxel ({x},{y},{z}) outside size {W}x{H}x{D}; skipped")
            continue
        block_strings_stream.append(block_id)
        raw_voxels.append((x, y, z, block_id))

    # Re-compress using common.compress_palette for canonical ordering. Air is
    # dropped from the palette; air voxels are skipped (air is implicit).
    palette = compress_palette(block_strings_stream)
    rev = {v: k for k, v in palette.items()}
    voxels = [
        [x, y, z, rev[bid]]
        for (x, y, z, bid) in raw_voxels
        if not _is_air(bid)
    ]

    # Deduplicate any (x,y,z) repeats — keep last seen.
    if len({(x, y, z) for (x, y, z, _) in raw_voxels}) != len(raw_voxels):
        warnings.append("duplicate voxel positions; later writes win")
        seen: dict[tuple[int, int, int], list[int]] = {}
        for vox in voxels:
            seen[(vox[0], vox[1], vox[2])] = vox
        voxels = list(seen.values())

    return voxels, palette, (W, H, D), warnings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--source", default="github")
    p.add_argument("--source-url", required=True)
    p.add_argument("--license", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--style", nargs="+", required=True)
    p.add_argument("--stories", type=int, default=None)
    p.add_argument("--description", default="")
    p.add_argument("--id", default=None)
    p.add_argument("--agent", default="phase-b-agent-8",
                   help="Agent ID used in the PROCESSING.md log entry.")
    args = p.parse_args(argv)

    if args.input.suffix.lower() != ".nbt":
        print(f"[ingest-nbt] expected .nbt extension, got {args.input.suffix}", file=sys.stderr)
        return 2

    voxels, palette, (W, H, D), warnings = _parse_nbt(args.input)
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
            "ingest_warnings": warnings,
        },
        "ingest": {
            "tool": "ingest_nbt.py",
            "tool_version": "0.1.0",
            "source_format": "nbt",
            "ingested_at": now_iso(),
            "ingester_path": __file__,
        },
    }
    if args.description:
        doc["description"] = args.description
    if args.stories:
        doc["tags"]["stories"] = args.stories

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / f"{building_id}.json"
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")

    append_processing_log(
        f"\n## {now_iso()} — {out.name}\n"
        f"- source: {args.source_url}\n"
        f"- format: nbt\n"
        f"- agent: {args.agent}\n"
        f"- action: kept\n"
        f"- license: {args.license}\n"
        f"- size: {W}x{H}x{D}\n"
        f"- voxels: {len(voxels)}\n"
        f"- interior_populated: {metrics['interior_populated']}\n"
        + (f"- warnings: {'; '.join(warnings)}\n" if warnings else "")
    )
    print(f"[ingest-nbt] wrote {out}  ({W}x{H}x{D}, {len(voxels)} voxels, populated={metrics['interior_populated']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
