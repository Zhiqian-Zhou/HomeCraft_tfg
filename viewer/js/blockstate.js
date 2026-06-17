// Blockstate rotation + per-face texture mapping for Minecraft Java 1.16.5.
// Hand-coded for the top ~40 blocks that carry directional state in our corpus.
// Returns:
//   parseBlock(idString) -> { name, props }
//   rotationFor(name, props) -> THREE.Euler-like { x, y, z } in radians (or null if no rotation)
//   faceTextures(name, props) -> { up, down, north, south, east, west }
//     each is a texture key (without 'block/' prefix) for textures.js to resolve.

const HALF_PI = Math.PI / 2;

// parse "minecraft:oak_stairs[facing=east,half=top,shape=straight]"
// → { name: "oak_stairs", props: { facing: "east", half: "top", shape: "straight" } }
export function parseBlock(idStr) {
  const bracketIdx = idStr.indexOf('[');
  let bare = idStr;
  const props = {};
  if (bracketIdx !== -1) {
    bare = idStr.slice(0, bracketIdx);
    const inside = idStr.slice(bracketIdx + 1, -1);
    for (const part of inside.split(',')) {
      const [k, v] = part.split('=');
      if (k && v) props[k.trim()] = v.trim();
    }
  }
  const name = bare.replace(/^minecraft:/, '');
  return { name, props };
}

// Facing → Y rotation in radians (Minecraft convention: north = -Z, the block "faces" that way)
const FACING_Y_ROTATION = {
  north: 0,
  east:  -HALF_PI,
  south: Math.PI,
  west:  HALF_PI,
  up:    0,    // up/down: handled via X rotation
  down:  0,
};

// axis → rotation that orients a "log" texture so its rings face the given axis
const AXIS_ROTATION = {
  y: { x: 0, y: 0, z: 0 },
  x: { x: 0, y: 0, z: HALF_PI },
  z: { x: HALF_PI, y: 0, z: 0 },
};

// Returns {x,y,z} rotation in radians, or null if no rotation needed.
export function rotationFor(name, props) {
  // 1) axis-style blocks (logs, basalt, hay_bale, ...)
  if (props.axis && AXIS_ROTATION[props.axis]) {
    return AXIS_ROTATION[props.axis];
  }
  // 2) facing-style blocks (stairs, doors, furnaces, dispensers, ...)
  if (props.facing != null && FACING_Y_ROTATION[props.facing] != null) {
    const y = FACING_Y_ROTATION[props.facing];
    // For "up"/"down" facings, apply X rotation instead
    if (props.facing === 'up')   return { x: HALF_PI,  y: 0, z: 0 };
    if (props.facing === 'down') return { x: -HALF_PI, y: 0, z: 0 };
    // half=top flips vertically for stairs / trapdoors
    if (props.half === 'top' && /(stairs|trapdoor)/.test(name)) {
      return { x: Math.PI, y, z: 0 };
    }
    return { x: 0, y, z: 0 };
  }
  return null;
}

// ──────────────────────────────────────────────────────────────────────────
//  Per-face texture lookup
//  Returns { up, down, north, south, east, west } — texture names without
//  the "minecraft:" or "block/" prefix.
//  Falls back to {all: name} for unknown blocks.
// ──────────────────────────────────────────────────────────────────────────

// Blocks where the side texture differs from top/bottom
const FACE_MAP_OVERRIDES = {
  // We model windows as full glass_pane blocks; the real glass_pane texture is
  // ~90% transparent (a thin frame) so windows looked invisible. Render them
  // with the solid 'glass' texture (a visible translucent square) instead.
  glass_pane:         { up: 'glass', down: 'glass', side: 'glass' },
  grass_block:        { up: 'grass_block_top',     down: 'dirt',              side: 'grass_block_side' },
  podzol:             { up: 'podzol_top',          down: 'dirt',              side: 'podzol_side' },
  mycelium:           { up: 'mycelium_top',        down: 'dirt',              side: 'mycelium_side' },
  dirt_path:          { up: 'grass_path_top',      down: 'dirt',              side: 'grass_path_side' },
  grass_path:         { up: 'grass_path_top',      down: 'dirt',              side: 'grass_path_side' },
  oak_log:            { up: 'oak_log_top',         down: 'oak_log_top',       side: 'oak_log' },
  spruce_log:         { up: 'spruce_log_top',      down: 'spruce_log_top',    side: 'spruce_log' },
  birch_log:          { up: 'birch_log_top',       down: 'birch_log_top',     side: 'birch_log' },
  jungle_log:         { up: 'jungle_log_top',      down: 'jungle_log_top',    side: 'jungle_log' },
  acacia_log:         { up: 'acacia_log_top',      down: 'acacia_log_top',    side: 'acacia_log' },
  dark_oak_log:       { up: 'dark_oak_log_top',    down: 'dark_oak_log_top',  side: 'dark_oak_log' },
  stripped_oak_log:   { up: 'stripped_oak_log_top', down: 'stripped_oak_log_top', side: 'stripped_oak_log' },
  stripped_spruce_log:{ up: 'stripped_spruce_log_top', down: 'stripped_spruce_log_top', side: 'stripped_spruce_log' },
  stripped_birch_log: { up: 'stripped_birch_log_top', down: 'stripped_birch_log_top', side: 'stripped_birch_log' },
  basalt:             { up: 'basalt_top',          down: 'basalt_top',        side: 'basalt_side' },
  hay_block:          { up: 'hay_block_top',       down: 'hay_block_top',     side: 'hay_block_side' },
  bone_block:         { up: 'bone_block_top',      down: 'bone_block_top',    side: 'bone_block_side' },
  pumpkin:            { up: 'pumpkin_top',         down: 'pumpkin_top',       side: 'pumpkin_side' },
  carved_pumpkin:     { up: 'pumpkin_top',         down: 'pumpkin_top',       north: 'carved_pumpkin', side: 'pumpkin_side' },
  jack_o_lantern:     { up: 'pumpkin_top',         down: 'pumpkin_top',       north: 'jack_o_lantern', side: 'pumpkin_side' },
  melon:              { up: 'melon_top',           down: 'melon_top',         side: 'melon_side' },
  sandstone:          { up: 'sandstone_top',       down: 'sandstone_bottom',  side: 'sandstone' },
  smooth_sandstone:   { up: 'sandstone_top',       down: 'sandstone_top',     side: 'sandstone_top' },
  chiseled_sandstone: { up: 'sandstone_top',       down: 'sandstone_bottom',  side: 'chiseled_sandstone' },
  red_sandstone:      { up: 'red_sandstone_top',   down: 'red_sandstone_bottom', side: 'red_sandstone' },
  cut_sandstone:      { up: 'sandstone_top',       down: 'sandstone_bottom',  side: 'cut_sandstone' },
  quartz_block:       { up: 'quartz_block_top',    down: 'quartz_block_top',  side: 'quartz_block_side' },
  smooth_quartz:      { up: 'quartz_block_bottom', down: 'quartz_block_bottom', side: 'quartz_block_bottom' },
  furnace:            { up: 'furnace_top',         down: 'furnace_top',       north: 'furnace_front', side: 'furnace_side' },
  blast_furnace:      { up: 'blast_furnace_top',   down: 'blast_furnace_top', north: 'blast_furnace_front', side: 'blast_furnace_side' },
  smoker:             { up: 'smoker_top',          down: 'smoker_bottom',     north: 'smoker_front', side: 'smoker_side' },
  crafting_table:     { up: 'crafting_table_top',  down: 'oak_planks',        north: 'crafting_table_front', east: 'crafting_table_side', south: 'crafting_table_side', west: 'crafting_table_front' },
  bookshelf:          { up: 'oak_planks',          down: 'oak_planks',        side: 'bookshelf' },
  cartography_table:  { up: 'cartography_table_top', down: 'dark_oak_planks',  north: 'cartography_table_side3', east: 'cartography_table_side3', south: 'cartography_table_side1', west: 'cartography_table_side2' },
  loom:               { up: 'loom_top',            down: 'oak_planks',        north: 'loom_front', east: 'loom_side', south: 'loom_side', west: 'loom_front' },
  fletching_table:    { up: 'fletching_table_top', down: 'birch_planks',      side: 'fletching_table_side' },
  smithing_table:     { up: 'smithing_table_top',  down: 'smithing_table_bottom', north: 'smithing_table_front', east: 'smithing_table_side', south: 'smithing_table_front', west: 'smithing_table_side' },
  stonecutter:        { up: 'stonecutter_top',     down: 'stonecutter_bottom', side: 'stonecutter_side' },
  observer:           { up: 'observer_top',        down: 'observer_top',      north: 'observer_front', south: 'observer_back', side: 'observer_side' },
  dispenser:          { up: 'furnace_top',         down: 'furnace_top',       north: 'dispenser_front', side: 'furnace_side' },
  dropper:            { up: 'furnace_top',         down: 'furnace_top',       north: 'dropper_front', side: 'furnace_side' },
  command_block:      { up: 'command_block_back',  down: 'command_block_back', north: 'command_block_front', south: 'command_block_back', side: 'command_block_side' },
  jukebox:            { up: 'jukebox_top',         down: 'jukebox_side',      side: 'jukebox_side' },
  note_block:         { up: 'note_block',          down: 'note_block',        side: 'note_block' },
  tnt:                { up: 'tnt_top',             down: 'tnt_bottom',        side: 'tnt_side' },
  // Multi-texture blocks that fall through to the default cube handler.
  // Without these entries, the renderer tries '<name>.png' and gets a
  // 404 fallback gray, which looks like a broken/miniature block.
  campfire:           { up: 'campfire_log_lit',    down: 'campfire_log_lit',  side: 'campfire_log_lit' },
  soul_campfire:      { up: 'soul_campfire_log_lit', down: 'soul_campfire_log_lit', side: 'soul_campfire_log_lit' },
  lectern:            { up: 'lectern_top',         down: 'lectern_base',      north: 'lectern_front', side: 'lectern_sides' },
  // Water_cauldron in 1.16.5 = cauldron with water inside; use cauldron faces.
  water_cauldron:     { up: 'water_still',         down: 'cauldron_bottom',   side: 'cauldron_side' },
  lava_cauldron:      { up: 'lava_still',          down: 'cauldron_bottom',   side: 'cauldron_side' },
  // Water/lava textures are *_still.png in 1.16.5 (not water.png).
  water:              { up: 'water_still',         down: 'water_still',       side: 'water_still' },
  lava:               { up: 'lava_still',          down: 'lava_still',        side: 'lava_still' },
  // Bell: top/bottom/side textures.
  bell:               { up: 'bell_top',            down: 'bell_bottom',       side: 'bell_side' },
  // End portal frame (when not in furniture handler).
  end_portal_frame:   { up: 'end_portal_frame_top', down: 'end_stone',        side: 'end_portal_frame_side' },
  // Common functional blocks that need top/side differentiation.
  enchanting_table:   { up: 'enchanting_table_top', down: 'enchanting_table_bottom', side: 'enchanting_table_side' },
  brewing_stand:      { up: 'brewing_stand_base',  down: 'brewing_stand_base', side: 'brewing_stand' },
  cauldron:           { up: 'cauldron_top',        down: 'cauldron_bottom',   side: 'cauldron_side' },
  composter:          { up: 'composter_top',       down: 'composter_bottom',  side: 'composter_side' },
  barrel:             { up: 'barrel_top',          down: 'barrel_bottom',     side: 'barrel_side' },
  hopper:             { up: 'hopper_top',          down: 'hopper_outside',    side: 'hopper_outside' },
  // Redstone lamp (off state — the on variant is a different block).
  redstone_lamp:      { up: 'redstone_lamp',       down: 'redstone_lamp',     side: 'redstone_lamp' },
  // Sea lantern: same texture all faces.
  sea_lantern:        { up: 'sea_lantern',         down: 'sea_lantern',       side: 'sea_lantern' },
  // Purpur_pillar: top/side differentiation.
  purpur_pillar:      { up: 'purpur_pillar_top',   down: 'purpur_pillar_top', side: 'purpur_pillar' },
  // Snow block and ice variants.
  snow_block:         { up: 'snow',                down: 'snow',              side: 'snow' },
  ice:                { up: 'ice',                 down: 'ice',               side: 'ice' },
  packed_ice:         { up: 'packed_ice',          down: 'packed_ice',        side: 'packed_ice' },
  // Mushroom blocks: red/brown mushroom textures.
  red_mushroom_block:    { up: 'red_mushroom_block', down: 'mushroom_block_inside', side: 'red_mushroom_block' },
  brown_mushroom_block:  { up: 'brown_mushroom_block', down: 'mushroom_block_inside', side: 'brown_mushroom_block' },
};

const ALWAYS_TRANSPARENT = new Set([
  'glass', 'glass_pane', 'iron_bars', 'oak_leaves', 'spruce_leaves',
  'birch_leaves', 'jungle_leaves', 'acacia_leaves', 'dark_oak_leaves',
  'oak_trapdoor', 'spruce_trapdoor', 'birch_trapdoor', 'jungle_trapdoor',
  'acacia_trapdoor', 'dark_oak_trapdoor', 'iron_trapdoor',
  'ladder', 'water', 'ice', 'cobweb',
  // Stained glass
  'white_stained_glass', 'orange_stained_glass', 'magenta_stained_glass',
  'light_blue_stained_glass', 'yellow_stained_glass', 'lime_stained_glass',
  'pink_stained_glass', 'gray_stained_glass', 'light_gray_stained_glass',
  'cyan_stained_glass', 'purple_stained_glass', 'blue_stained_glass',
  'brown_stained_glass', 'green_stained_glass', 'red_stained_glass',
  'black_stained_glass',
]);

// Returns { up, down, north, south, east, west } texture names.
export function faceTextures(name) {
  const o = FACE_MAP_OVERRIDES[name];
  if (!o) {
    return { up: name, down: name, north: name, south: name, east: name, west: name };
  }
  const side = o.side ?? name;
  return {
    up:    o.up    ?? side,
    down:  o.down  ?? side,
    north: o.north ?? side,
    south: o.south ?? side,
    east:  o.east  ?? side,
    west:  o.west  ?? side,
  };
}

export function isTransparent(name) {
  return ALWAYS_TRANSPARENT.has(name);
}

// Tinted blocks (rendered with a slight color overlay)
// In 1.16.5 these would be biome-tinted; for our viewer we use a sane default.
const TINTS = {
  grass_block: 0x91bd59,
  oak_leaves: 0x4d8c40,
  spruce_leaves: 0x619961,
  birch_leaves: 0x80a755,
  jungle_leaves: 0x59c93c,
  acacia_leaves: 0x77ab2f,
  dark_oak_leaves: 0x59ad55,
  vine: 0x6bb061,
  water: 0x3f76e4,
};

export function tintColor(name) {
  return TINTS[name] ?? null;
}
