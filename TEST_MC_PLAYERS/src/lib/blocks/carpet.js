// Carpet + thin (pressure plates, tripwire) handler — Phase B agent #6.
//
// Covers the flat 1/16-tall family: 16-color carpets, all pressure plates
// (wood, stone, polished_blackstone, heavy/light weighted) and tripwire.
// Geometry is a 1 × 1/16 × 1 box translated down so its top face sits on
// the voxel floor (renderer centers the block at y+0.5; floor is at -0.5,
// half-height of the slab is 0.03125, so center offset = -0.5 + 0.03125
// = -0.46875).

import * as THREE from 'three';
import { register } from './index.js';

let _sharedCarpet = null;
function carpetGeometry() {
  if (!_sharedCarpet) {
    _sharedCarpet = new THREE.BoxGeometry(1, 0.0625, 1);
    _sharedCarpet.translate(0, -0.46875, 0);
  }
  return _sharedCarpet.clone();
}

function textureFor(name) {
  if (name.endsWith('_carpet')) {
    return name.replace(/_carpet$/, '_wool');
  }
  if (name.endsWith('_pressure_plate')) {
    const base = name.replace(/_pressure_plate$/, '');
    if (base === 'stone') return 'stone';
    if (base === 'polished_blackstone') return 'polished_blackstone';
    if (base === 'heavy_weighted') return 'iron_block';
    if (base === 'light_weighted') return 'gold_block';
    return base + '_planks';
  }
  if (name === 'tripwire') return 'tripwire';
  return name;
}

function matchFn(name) {
  return (
    name.endsWith('_carpet') ||
    name.endsWith('_pressure_plate') ||
    name === 'tripwire'
  );
}

register(matchFn, {
  geometry: () => carpetGeometry(),
  faces: (name) => {
    const t = textureFor(name);
    return { up: t, down: t, north: t, south: t, east: t, west: t };
  },
  rotation: () => null,
  transparent: () => false,
  tint: () => null,
});
