// Lights handler — torches, lanterns, end rod, sea pickle.
//
// Covers small "light source" blocks that are not full cubes:
//   torch, wall_torch, soul_torch, soul_wall_torch,
//   redstone_torch, redstone_wall_torch,
//   lantern, soul_lantern,
//   end_rod, sea_pickle.
//
// Geometries are simplified prismatic stand-ins of the canonical 1.16.5
// models (no inclined wall_torch; we just pull the column toward the
// north face and rotate by `facing`).

import * as THREE from 'three';
import { register } from './index.js';

// --- shared geometries (cloned per call so renderer can dispose freely) ---

const torchGeom = new THREE.BoxGeometry(0.125, 0.625, 0.125);
torchGeom.translate(0, -0.1875, 0); // base sits at y=-0.5 (floor of voxel)

const wallTorchGeom = new THREE.BoxGeometry(0.125, 0.625, 0.125);
wallTorchGeom.translate(0, 0, -0.4); // hugs the north wall by default

const lanternGeomFloor = new THREE.BoxGeometry(0.375, 0.4375, 0.375);
lanternGeomFloor.translate(0, -0.28, 0); // sitting on the floor

const lanternGeomHanging = new THREE.BoxGeometry(0.375, 0.4375, 0.375);
lanternGeomHanging.translate(0, 0.28, 0); // hanging from the ceiling

const endRodGeom = new THREE.BoxGeometry(0.125, 1, 0.125);

const seaPickleGeom = new THREE.BoxGeometry(0.375, 0.375, 0.375);
seaPickleGeom.translate(0, -0.3125, 0); // glued to the floor

// --- helpers ---

function isLantern(name) {
  return name === 'lantern' || name === 'soul_lantern';
}

function isWallTorch(name) {
  return name === 'wall_torch'
      || name === 'soul_wall_torch'
      || name === 'redstone_wall_torch';
}

function isFloorTorch(name) {
  return name === 'torch' || name === 'soul_torch' || name === 'redstone_torch';
}

function textureFor(name) {
  if (name === 'wall_torch') return 'torch';
  if (name === 'soul_wall_torch') return 'soul_torch';
  if (name === 'redstone_wall_torch') return 'redstone_torch';
  return name;
}

// --- matcher ---

function matchFn(name) {
  return isLantern(name)
      || isWallTorch(name)
      || isFloorTorch(name)
      || name === 'end_rod'
      || name === 'sea_pickle';
}

// --- handler ---

register(matchFn, {
  geometry(name, props) {
    if (isLantern(name)) {
      const hanging = props && props.hanging === 'true';
      return (hanging ? lanternGeomHanging : lanternGeomFloor).clone();
    }
    if (name === 'end_rod') return endRodGeom.clone();
    if (name === 'sea_pickle') return seaPickleGeom.clone();
    if (isWallTorch(name)) return wallTorchGeom.clone();
    return torchGeom.clone(); // torch, soul_torch, redstone_torch
  },

  faces(name, _props) {
    const t = textureFor(name);
    return { up: t, down: t, north: t, south: t, east: t, west: t };
  },

  rotation(name, props) {
    if (!isWallTorch(name)) return null;
    const f = props && props.facing;
    if (f === 'east')  return { x: 0, y: -Math.PI / 2, z: 0 };
    if (f === 'south') return { x: 0, y:  Math.PI,     z: 0 };
    if (f === 'west')  return { x: 0, y:  Math.PI / 2, z: 0 };
    return { x: 0, y: 0, z: 0 }; // facing=north (default)
  },

  transparent: () => true,
  tint: () => null,
});
