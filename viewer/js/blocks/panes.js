// Thin-pane handler — glass panes, stained-glass panes and iron bars.
//
// The default cube handler rendered these as full blocks, so windows looked
// like solid glass cubes. We draw the orientation-independent "+" cross
// (two thin crossed panels through the cell centre), which reads as a pane
// or bars from every side without needing neighbour information.
//
// The geometry is merged into ONE group referencing material index 0, so the
// renderer's 6-material array collapses to a single texture (all faces share
// the same pane texture anyway).

import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { register } from './index.js';

const T = 2 / 16; // panel thickness

function matchFn(name, _props) {
  return name === 'glass_pane' || name === 'iron_bars'
      || (typeof name === 'string' && name.endsWith('_stained_glass_pane'));
}

// Texture name for the pane material.
function texFor(name) {
  if (name === 'glass_pane') return 'glass';                 // solid, visible square
  if (name === 'iron_bars') return 'iron_bars';
  if (name.endsWith('_stained_glass_pane')) {
    return name.replace(/_pane$/, '');                       // <color>_stained_glass
  }
  return name;
}

let _cross = null;
function crossGeometry() {
  if (_cross) return _cross.clone();
  try {
    const a = new THREE.BoxGeometry(1, 1, T);  // panel spanning X (faces N/S)
    const b = new THREE.BoxGeometry(T, 1, 1);  // panel spanning Z (faces E/W)
    const g = mergeGeometries([a, b], false);  // ignore per-box groups
    g.clearGroups();
    const count = g.index ? g.index.count : g.attributes.position.count;
    g.addGroup(0, count, 0);                    // whole mesh → material[0]
    _cross = g;
  } catch (_err) {
    // Defensive fallback: a single thin centred panel (still better than a cube).
    _cross = new THREE.BoxGeometry(1, 1, T);
  }
  return _cross.clone();
}

register(matchFn, {
  geometry: (_name, _props) => crossGeometry(),
  faces: (name, _props) => {
    const tex = texFor(name);
    return { up: tex, down: tex, north: tex, south: tex, east: tex, west: tex };
  },
  rotation: (_name, _props) => null,
  transparent: (_name, _props) => true,
  tint: (_name, _props) => null,
  doubleSided: true,
});
