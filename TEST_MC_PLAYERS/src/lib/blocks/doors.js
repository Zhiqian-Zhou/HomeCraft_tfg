// Door handler — Minecraft Java 1.16.5 doors.
//
// Covers the 9 vanilla door block_ids (oak/spruce/birch/jungle/acacia/
// dark_oak/crimson/warped/iron). Each door occupies two stacked blocks:
//   - half=lower → uses <wood>_door_bottom texture
//   - half=upper → uses <wood>_door_top texture
// The visible mesh is a thin panel (14/16 × 1 × 3/16) flush against one
// of the four walls of the unit cube, chosen by `facing`. Hinge=right
// is approximated by mirroring on X (acceptable simplification).

import * as THREE from 'three';
import { register } from './index.js';

const HALF_PI = Math.PI / 2;

// Panel dimensions in block units (1 block = 16 px / 16 = 1.0)
const PANEL_W = 14 / 16; // 0.875 — width along X
const PANEL_H = 1;       // 1     — full block height
const PANEL_T = 3 / 16;  // 0.1875 — thickness along Z (depth into wall)

// Z offset that places the panel flush against the NORTH wall (z = -0.5).
// Center of the panel = -0.5 + thickness/2 ≈ -0.40625.
const PANEL_Z = -0.5 + PANEL_T / 2;

// Y rotation per facing — door's panel sits on the wall opposite to facing.
const FACING_Y = {
  north: 0,
  east:  -HALF_PI,
  south: Math.PI,
  west:  HALF_PI,
};

// Match any *_door (with or without namespaced prefix already stripped by parser).
function matchFn(name, _props) {
  return typeof name === 'string' && name.endsWith('_door');
}

// Build the thin panel geometry, translated so it sits flush at z = -0.5.
// Sharing a single base geometry would be nice, but we need to translate
// per-instance and the renderer disposes the returned geometry, so clone.
let _basePanel = null;
function panelGeometry(props) {
  if (!_basePanel) {
    _basePanel = new THREE.BoxGeometry(PANEL_W, PANEL_H, PANEL_T);
    _basePanel.translate(0, 0, PANEL_Z);
  }
  const g = _basePanel.clone();
  // Hinge=right: mirror across X (simplification — real MC shifts the panel).
  if (props && props.hinge === 'right') {
    g.scale(-1, 1, 1);
  }
  return g;
}

// Resolve the texture name for this door + half.
function doorTexture(name, props) {
  const wood = name.replace(/_door$/, '');
  const half = props && props.half === 'upper' ? 'top' : 'bottom';
  return `${wood}_door_${half}`;
}

register(matchFn, {
  geometry: (_name, props) => panelGeometry(props),
  faces: (name, props) => {
    const tex = doorTexture(name, props);
    return { up: tex, down: tex, north: tex, south: tex, east: tex, west: tex };
  },
  rotation: (_name, props) => {
    const facing = (props && props.facing) || 'north';
    const y = FACING_Y[facing] ?? 0;
    return { x: 0, y, z: 0 };
  },
  transparent: (_name, _props) => true,
  tint: (_name, _props) => null,
});
