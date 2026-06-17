// Connectors: fences, fence gates, walls, panes, iron_bars.
//
// First-iteration geometry — does NOT inspect neighbors. Each block emits a
// central post plus four short arms (cardinal directions). Panes/bars emit a
// crossed pair of thin planes. Wall is a thicker fence variant. Fence gates
// reuse the fence geometry (ignoring open/closed state for now).
//
// Texture mapping follows the v1 paleta (Minecraft 1.16.5): _fence variants
// map to their wood _planks; _wall variants map to the base material texture;
// panes/bars use the matching block texture (glass, iron_bars, *_stained_glass).
import * as THREE from 'three';
import * as BufferGeometryUtils from 'three/addons/utils/BufferGeometryUtils.js';
import { register } from './index.js';

// --- geometry caches -------------------------------------------------------

let _fence = null;
let _wall = null;
let _pane = null;

function fenceGeometry() {
  if (_fence) return _fence;
  const post = new THREE.BoxGeometry(0.25, 1, 0.25);
  // Arms span 0.25 along the connecting axis, translated 0.375 outward so
  // they extend from the post edge (|0.125|) to the voxel boundary (|0.5|).
  const armN = new THREE.BoxGeometry(0.125, 0.375, 0.25); armN.translate(0, 0, -0.375);
  const armS = new THREE.BoxGeometry(0.125, 0.375, 0.25); armS.translate(0, 0,  0.375);
  const armE = new THREE.BoxGeometry(0.25, 0.375, 0.125); armE.translate( 0.375, 0, 0);
  const armW = new THREE.BoxGeometry(0.25, 0.375, 0.125); armW.translate(-0.375, 0, 0);
  const armN2 = armN.clone(); armN2.translate(0, 0.5, 0);
  const armS2 = armS.clone(); armS2.translate(0, 0.5, 0);
  const armE2 = armE.clone(); armE2.translate(0, 0.5, 0);
  const armW2 = armW.clone(); armW2.translate(0, 0.5, 0);
  // useGroups=false: renderer has 6 materials; preserving per-box groups would
  // leave most faces unmaterialized (holes). Merge into a single group.
  _fence = BufferGeometryUtils.mergeGeometries(
    [post, armN, armS, armE, armW, armN2, armS2, armE2, armW2], false);
  return _fence;
}

function wallGeometry() {
  if (_wall) return _wall;
  const post = new THREE.BoxGeometry(0.5, 1, 0.5);
  // Arms: 0.25 thick × 0.8 tall × 0.25 long along the connecting axis,
  // translated 0.375 so they reach from post edge (|0.25|) to voxel face (|0.5|).
  const armN = new THREE.BoxGeometry(0.25, 0.8, 0.25); armN.translate(0, -0.1, -0.375);
  const armS = new THREE.BoxGeometry(0.25, 0.8, 0.25); armS.translate(0, -0.1,  0.375);
  const armE = new THREE.BoxGeometry(0.25, 0.8, 0.25); armE.translate( 0.375, -0.1, 0);
  const armW = new THREE.BoxGeometry(0.25, 0.8, 0.25); armW.translate(-0.375, -0.1, 0);
  _wall = BufferGeometryUtils.mergeGeometries([post, armN, armS, armE, armW], false);
  return _wall;
}

function paneGeometry() {
  if (_pane) return _pane;
  const ns = new THREE.BoxGeometry(0.0625, 1, 1);
  const ew = new THREE.BoxGeometry(1, 1, 0.0625);
  _pane = BufferGeometryUtils.mergeGeometries([ns, ew], false);
  return _pane;
}

// --- texture mapping -------------------------------------------------------

const WALL_ALIASES = {
  cobblestone: 'cobblestone',
  mossy_cobblestone: 'mossy_cobblestone',
  stone_brick: 'stone_bricks',
  mossy_stone_brick: 'mossy_stone_bricks',
  granite: 'granite',
  andesite: 'andesite',
  diorite: 'diorite',
  sandstone: 'sandstone',
  red_sandstone: 'red_sandstone',
  brick: 'bricks',
  prismarine: 'prismarine',
  nether_brick: 'nether_bricks',
  red_nether_brick: 'red_nether_bricks',
  end_stone_brick: 'end_stone_bricks',
  blackstone: 'blackstone',
  polished_blackstone: 'polished_blackstone',
  polished_blackstone_brick: 'polished_blackstone_bricks',
};

function textureFor(name) {
  if (name.endsWith('_fence_gate') || name.endsWith('_fence')) {
    const base = name.replace(/_fence_gate$|_fence$/, '');
    if (base === 'nether_brick') return 'nether_bricks';
    return base + '_planks';
  }
  if (name.endsWith('_wall')) {
    const base = name.replace(/_wall$/, '');
    return WALL_ALIASES[base] ?? base;
  }
  if (name === 'glass_pane') return 'glass';
  if (name === 'iron_bars') return 'iron_bars';
  if (name.endsWith('_stained_glass_pane')) return name.replace(/_pane$/, '');
  return name;
}

// --- handler ---------------------------------------------------------------

// NOTE: glass_pane / *_stained_glass_pane are deliberately NOT matched here.
// The generator uses them as FULL-BLOCK windows, so they must render as a solid
// (translucent) glass CUBE via the default cube handler — not the thin MC pane
// cross geometry, which made windows nearly invisible.
const MATCH = /(_fence_gate|_fence|_wall|iron_bars)$/;

register(
  (name) => MATCH.test(name),
  {
    geometry(name) {
      if (name.endsWith('_wall')) return wallGeometry().clone();
      if (name === 'iron_bars' || name.includes('pane')) return paneGeometry().clone();
      return fenceGeometry().clone();
    },
    faces(name) {
      const t = textureFor(name);
      return { up: t, down: t, north: t, south: t, east: t, west: t };
    },
    rotation: () => null,
    transparent: (name) => name === 'iron_bars' || name.includes('pane'),
    tint: () => null,
  }
);
