// Slabs handler — half-block geometry for *_slab blocks (MC 1.16.5).
//
// Slab states:
//   - type=bottom (default): box at y in [0..0.5] of the voxel cell
//   - type=top:              box at y in [0.5..1]
//   - type=double:           full 1x1x1 cube
//
// The renderer centers each block at (x+0.5, y+0.5, z+0.5). To occupy the
// lower half of the cell, the geometry is translated to sit at y in
// [-0.5..0] in geometry-local space (i.e. centered at y=-0.25).

import * as THREE from 'three';
import { register } from './index.js';

// Cached geometries (cloned per call so the renderer can dispose freely).
const _slabBottom = new THREE.BoxGeometry(1, 0.5, 1);
_slabBottom.translate(0, -0.25, 0);
const _slabTop = new THREE.BoxGeometry(1, 0.5, 1);
_slabTop.translate(0, 0.25, 0);
const _slabDouble = new THREE.BoxGeometry(1, 1, 1);

// Map slab name → base texture name used on all six faces.
// All slabs in the v1.16.5 paleta use a uniform side texture; logs/basalt
// (which would need 3-texture handling) are not in the slab set.
function baseTexture(slabName) {
  const base = slabName.replace(/_slab$/, '');
  const aliases = {
    // Wood planks
    oak: 'oak_planks',
    spruce: 'spruce_planks',
    birch: 'birch_planks',
    jungle: 'jungle_planks',
    acacia: 'acacia_planks',
    dark_oak: 'dark_oak_planks',
    crimson: 'crimson_planks',
    warped: 'warped_planks',
    // Stone family
    cobblestone: 'cobblestone',
    mossy_cobblestone: 'mossy_cobblestone',
    stone: 'stone',
    smooth_stone: 'smooth_stone_slab_side',
    andesite: 'andesite',
    polished_andesite: 'polished_andesite',
    diorite: 'diorite',
    polished_diorite: 'polished_diorite',
    granite: 'granite',
    polished_granite: 'polished_granite',
    // Brick family
    stone_brick: 'stone_bricks',
    mossy_stone_brick: 'mossy_stone_bricks',
    nether_brick: 'nether_bricks',
    brick: 'bricks',
    // Sandstone (smooth_* uses the top texture as side)
    sandstone: 'sandstone',
    smooth_sandstone: 'sandstone_top',
    cut_sandstone: 'cut_sandstone',
    red_sandstone: 'red_sandstone',
    smooth_red_sandstone: 'red_sandstone_top',
    cut_red_sandstone: 'cut_red_sandstone',
    // Quartz
    quartz: 'quartz_block_side',
    smooth_quartz: 'quartz_block_bottom',
    // Misc
    purpur: 'purpur_block',
    prismarine: 'prismarine',
    prismarine_brick: 'prismarine_bricks',
    dark_prismarine: 'dark_prismarine',
    end_stone_brick: 'end_stone_bricks',
    blackstone: 'blackstone',
    polished_blackstone: 'polished_blackstone',
    polished_blackstone_brick: 'polished_blackstone_bricks',
  };
  return aliases[base] ?? base;
}

function slabFaces(name, _props) {
  const tex = baseTexture(name);
  return { up: tex, down: tex, north: tex, south: tex, east: tex, west: tex };
}

function slabGeometry(_name, props) {
  const type = (props && props.type) ?? 'bottom';
  if (type === 'top') return _slabTop.clone();
  if (type === 'double') return _slabDouble.clone();
  return _slabBottom.clone();
}

register((name, _props) => name.endsWith('_slab'), {
  geometry: slabGeometry,
  faces: slabFaces,
  rotation: (_name, _props) => null,
  transparent: (_name, _props) => false,
  tint: (_name, _props) => null,
});
