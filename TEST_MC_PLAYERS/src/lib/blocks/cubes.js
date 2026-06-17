// Default cube handler — reproduces the legacy renderer behavior.
//
// Used when no specific family handler matches. Emits a unit BoxGeometry
// and the per-face texture map from blockstate.js. This is the fallback
// for all "regular" cube blocks (oak_planks, stone, glass, …) and for
// any block we haven't written a specific handler for yet.

import * as THREE from 'three';
import { faceTextures, rotationFor, isTransparent, tintColor } from '../blockstate.js';
import { setDefault } from './index.js';

const BLOCK = 1;

// Box geometry is the same instance for every cube block — Three.js
// allows reusing geometry across InstancedMesh; we'd dispose it on clear.
let _sharedCube = null;
function sharedCubeGeometry() {
  if (!_sharedCube) _sharedCube = new THREE.BoxGeometry(BLOCK, BLOCK, BLOCK);
  return _sharedCube.clone();
  // Note: clone so renderer.clearBuilding() can dispose freely without
  // affecting future loads.
}

setDefault({
  geometry: (_name, _props) => sharedCubeGeometry(),
  faces:    (name, _props)  => faceTextures(name),
  rotation: (name, props)   => rotationFor(name, props),
  transparent: (name, _props) => isTransparent(name),
  tint:     (name, _props)  => tintColor(name),
});
