// Cross-plant handler — Minecraft Java 1.16.5 flowers, saplings & grasses.
//
// Covers all single-tile "cross" plants: their model is two flat quads
// crossed at 45° inside the unit cube. The renderer still allocates 6
// materials (one per BoxGeometry face slot), so we make `faces()` return
// the same texture name for every slot — they all end up with the same
// MeshLambertMaterial pointing at the plant's PNG.
//
// Vertices use y ∈ [-0.5, 0.5] so the geometry's local origin matches the
// renderer's per-instance placement (block center at +0.5 of the voxel).

import * as THREE from 'three';
import { register } from './index.js';

// Block ids covered by this handler (exact match).
const FLOWERS = new Set([
  'poppy', 'dandelion', 'blue_orchid', 'allium', 'azure_bluet',
  'cornflower', 'lily_of_the_valley', 'oxeye_daisy', 'wither_rose',
  'red_tulip', 'orange_tulip', 'white_tulip', 'pink_tulip',
]);
const SAPLINGS = new Set([
  'oak_sapling', 'spruce_sapling', 'birch_sapling',
  'jungle_sapling', 'acacia_sapling', 'dark_oak_sapling',
]);
const PLANTS = new Set([
  'dead_bush', 'fern', 'large_fern', 'grass', 'tall_grass',
  'sweet_berry_bush', 'crimson_roots', 'warped_roots',
]);

function matchFn(name, _props) {
  return FLOWERS.has(name) || SAPLINGS.has(name) || PLANTS.has(name);
}

// Some block ids map to a slightly different texture file name.
const TEXTURE_OVERRIDES = {
  grass: 'grass',                  // grass.png (not grass_top.png — the tinted side)
  tall_grass: 'tall_grass_top',    // tall_grass_top.png
  large_fern: 'large_fern_top',    // large_fern_top.png
};

function textureFor(name) {
  return TEXTURE_OVERRIDES[name] ?? name;
}

// Plants that take a biome-grass-style green tint (approximated as 0x79c05a).
const TINTED = new Set(['grass', 'tall_grass', 'fern', 'large_fern']);

// Build the cross geometry: two perpendicular quads sharing the unit cube's
// vertical axis. y in [-0.5, 0.5] so renderer's (x+0.5, y+0.5, z+0.5)
// placement leaves the plant standing on the voxel floor.
let _baseCross = null;
function crossGeometry() {
  if (!_baseCross) {
    const s = 0.5;
    const g = new THREE.BufferGeometry();
    const pos = new Float32Array([
      // Quad 1: diagonal -x/-z to +x/+z
      -s, -s, -s,   s, -s,  s,   s,  s,  s,  -s,  s, -s,
      // Quad 2: diagonal -x/+z to +x/-z
      -s, -s,  s,   s, -s, -s,   s,  s, -s,  -s,  s,  s,
    ]);
    const uv = new Float32Array([
      0, 0, 1, 0, 1, 1, 0, 1,
      0, 0, 1, 0, 1, 1, 0, 1,
    ]);
    const idx = new Uint16Array([0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]);
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('uv',       new THREE.BufferAttribute(uv, 2));
    g.setIndex(new THREE.BufferAttribute(idx, 1));
    g.computeVertexNormals();
    // Renderer ships 6 materials (BoxGeometry face slots), but for the
    // cross geometry we only want to draw the two quads ONCE. Adding a
    // group for every slot (0..5) caused Three.js to render the same 12
    // indices six times with six translucent materials stacked on top of
    // each other — producing the "mini/multi-coloured flower" artifact.
    // A single group bound to slot 0 makes Three.js skip slots 1..5
    // (no geometry references them), so the plant is drawn exactly once.
    g.addGroup(0, 12, 0);
    _baseCross = g;
  }
  return _baseCross.clone();
}

register(matchFn, {
  geometry: (_name, _props) => crossGeometry(),
  faces: (name, _props) => {
    const tex = textureFor(name);
    return { up: tex, down: tex, north: tex, south: tex, east: tex, west: tex };
  },
  rotation:    (_name, _props) => null,
  transparent: (_name, _props) => true,
  tint:        (name,  _props) => (TINTED.has(name) ? 0x79c05a : null),
  doubleSided: true,
});
