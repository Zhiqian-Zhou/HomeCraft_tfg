// Stairs handler — Minecraft Java 1.16.5 stairs blocks.
//
// Covers every block_id matching /_stairs$/ (≈ 35 vanilla variants: wood,
// stone, brick, sandstone, quartz, prismarine, purpur, blackstone, …).
//
// Geometry: a "straight" stair = lower slab (full footprint, half height)
// + upper step (full width, half height, half depth). Default orientation
// faces north (step toward -Z); rotation handles the other three facings,
// and `half=top` flips vertically via X=π so the cutout sits on the bottom.
//
// Limitation: shape=inner_left/inner_right/outer_left/outer_right are
// rendered as the straight base shape (TODO: corner geometry follow-up).

import * as THREE from 'three';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';
import { register } from './index.js';

const HALF_PI = Math.PI / 2;

// Y rotation per facing (Minecraft: block "faces" -Z for north).
const FACING_Y = {
  north: 0,
  east:  -HALF_PI,
  south: Math.PI,
  west:  HALF_PI,
};

// Texture aliases: strip "_stairs" then map base → actual texture name.
// Most stairs reuse the texture of their "parent" block; only the
// irregular cases need explicit entries.
const TEXTURE_ALIASES = {
  // Woods → planks
  oak: 'oak_planks', spruce: 'spruce_planks', birch: 'birch_planks',
  jungle: 'jungle_planks', acacia: 'acacia_planks', dark_oak: 'dark_oak_planks',
  crimson: 'crimson_planks', warped: 'warped_planks',
  // Stone variants
  cobblestone: 'cobblestone',
  mossy_cobblestone: 'mossy_cobblestone',
  stone: 'stone',
  smooth_stone: 'smooth_stone',
  andesite: 'andesite', polished_andesite: 'polished_andesite',
  diorite: 'diorite', polished_diorite: 'polished_diorite',
  granite: 'granite', polished_granite: 'polished_granite',
  // Brick variants
  stone_brick: 'stone_bricks',
  mossy_stone_brick: 'mossy_stone_bricks',
  nether_brick: 'nether_bricks',
  red_nether_brick: 'red_nether_bricks',
  brick: 'bricks',
  end_stone_brick: 'end_stone_bricks',
  polished_blackstone_brick: 'polished_blackstone_bricks',
  // Sandstone
  sandstone: 'sandstone',
  smooth_sandstone: 'sandstone_top',
  red_sandstone: 'red_sandstone',
  smooth_red_sandstone: 'red_sandstone_top',
  // Quartz
  quartz: 'quartz_block_side',
  smooth_quartz: 'quartz_block_bottom',
  // Prismarine
  prismarine: 'prismarine',
  prismarine_brick: 'prismarine_bricks',
  dark_prismarine: 'dark_prismarine',
  // Misc
  purpur: 'purpur_block',
  blackstone: 'blackstone',
  polished_blackstone: 'polished_blackstone',
};

function baseTexture(stairsName) {
  const base = stairsName.replace(/_stairs$/, '');
  return TEXTURE_ALIASES[base] ?? base;
}

// Match any *_stairs block_id.
function matchFn(name, _props) {
  return typeof name === 'string' && name.endsWith('_stairs');
}

// Build the "straight" stair geometry once and clone per instance.
// Two BoxGeometries merged with useGroups=false so all 12 per-face groups
// collapse into a single group bound to materialIndex 0. The renderer
// builds a 6-material array per mesh (BoxGeometry face order); if we
// kept useGroups=true the merged geometry would emit groups with
// materialIndex 6..11 — out of range, so Three.js would silently drop
// those faces (visible as missing slab sides / a "mini" stair).
// Since faces() returns the same texture for all 6 slots, applying
// material[0] uniformly is visually identical to the per-face mapping.
let _baseStair = null;
function stairGeometry() {
  if (!_baseStair) {
    const slab = new THREE.BoxGeometry(1, 0.5, 1);
    slab.translate(0, -0.25, 0); // y ∈ [-0.5, 0]
    const step = new THREE.BoxGeometry(1, 0.5, 0.5);
    step.translate(0, 0.25, -0.25); // y ∈ [0, 0.5], z ∈ [-0.5, 0]
    _baseStair = BufferGeometryUtils.mergeGeometries([slab, step], false);
  }
  return _baseStair.clone();
}

register(matchFn, {
  geometry: (_name, _props) => stairGeometry(),
  faces: (name, _props) => {
    const tex = baseTexture(name);
    return { up: tex, down: tex, north: tex, south: tex, east: tex, west: tex };
  },
  rotation: (_name, props) => {
    const facing = (props && props.facing) || 'north';
    const y = FACING_Y[facing] ?? 0;
    const x = (props && props.half === 'top') ? Math.PI : 0;
    return { x, y, z: 0 };
  },
  transparent: (_name, _props) => false,
  tint: (_name, _props) => null,
});
