// Fence + fence-gate handler — Minecraft Java 1.16.5.
//
// Vanilla fences render as a thin central post (plus connecting rails to
// solid neighbours). We don't know neighbours at build time, so we draw the
// orientation-independent central post: a 4/16 × 1 × 4/16 box in the middle
// of the cell. That reads as a fence instead of the solid cube the default
// handler produced. Fence gates draw a thin full-width panel rotated to the
// gate's `facing`, sitting on the fence line through the cell centre.
//
// Textures: fences/gates use their wood's plank texture (oak_fence →
// oak_planks); nether_brick_fence → nether_bricks.

import * as THREE from 'three';
import { register } from './index.js';

const HALF_PI = Math.PI / 2;

const POST = 4 / 16;   // 0.25 — fence post footprint
const GATE_W = 1;      // full width along X
const GATE_H = 12 / 16; // gate panel a touch shorter than a full block
const GATE_T = 4 / 16; // panel thickness along Z

const FACING_Y = { north: 0, east: -HALF_PI, south: Math.PI, west: HALF_PI };

function isGate(name) { return typeof name === 'string' && name.endsWith('_fence_gate'); }
function isFence(name) { return typeof name === 'string' && name.endsWith('_fence'); }

function matchFn(name, _props) {
  return isGate(name) || isFence(name);
}

// Plank/base texture for the fence material.
function texFor(name) {
  const base = name.replace(/_fence_gate$/, '').replace(/_fence$/, '');
  if (base === 'nether_brick') return 'nether_bricks';
  return `${base}_planks`;
}

let _post = null;
function postGeometry() {
  if (!_post) _post = new THREE.BoxGeometry(POST, 1, POST);
  return _post.clone();
}
let _gate = null;
function gateGeometry() {
  if (!_gate) {
    // Centred panel; lowered slightly so the top isn't flush with the ceiling.
    _gate = new THREE.BoxGeometry(GATE_W, GATE_H, GATE_T);
    _gate.translate(0, -(1 - GATE_H) / 2, 0);
  }
  return _gate.clone();
}

register(matchFn, {
  geometry: (name, _props) => (isGate(name) ? gateGeometry() : postGeometry()),
  faces: (name, _props) => {
    const tex = texFor(name);
    return { up: tex, down: tex, north: tex, south: tex, east: tex, west: tex };
  },
  rotation: (name, props) => {
    if (!isGate(name)) return null;            // posts are symmetric
    const y = FACING_Y[(props && props.facing) || 'north'] ?? 0;
    return { x: 0, y, z: 0 };
  },
  transparent: (_name, _props) => false,
  tint: (_name, _props) => null,
});
