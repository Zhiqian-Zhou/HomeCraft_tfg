// Renderiza un edificio voxel como un grupo de THREE.InstancedMesh — UNO POR
// ENTRADA DE PALETA (≈30–60 draw calls), nunca un mesh por bloque.
//
// La forma/textura/rotación de cada familia de bloques la decide el registro
// de handlers (src/lib/blocks/*): puertas, camas, antorchas, escaleras, losas,
// vallas, cristales… se renderizan con su geometría propia, no como cubos.
// Los IDs inválidos en 1.16.5 pasan antes por remapName().

import * as THREE from 'three';
import { useMemo, useEffect } from 'react';

// Imports con efecto: cada módulo registra su handler al cargarse.
// cubes.js instala el handler por defecto — debe importarse SIEMPRE.
import '../lib/blocks/cubes.js';
import '../lib/blocks/doors.js';
import '../lib/blocks/bed.js';
import '../lib/blocks/plants.js';
import '../lib/blocks/carpet.js';
import '../lib/blocks/fences.js';
import '../lib/blocks/panes.js';
import '../lib/blocks/slabs.js';
import '../lib/blocks/stairs.js';
import '../lib/blocks/lights.js';
import '../lib/blocks/furniture.js';
import '../lib/blocks/trapdoors.js';

import { resolve as resolveHandler } from '../lib/blocks/index.js';
import { parseBlock } from '../lib/blockstate.js';
import { remapName } from '../lib/remap.js';
import { getTexture, getCroppedTexture } from '../lib/textures.js';

// Caché de materiales por (textura|tint|side|transparent) — se comparten
// entre edificios y NUNCA se desechan (las texturas están cacheadas igual).
const materialCache = new Map();

function materialFor(faceVal, info) {
  const texKey = typeof faceVal === 'object' && faceVal
    ? faceVal.tex + '#' + faceVal.crop.join(',')
    : faceVal;
  const key = [texKey, info.tint ?? '', info.transparent ? 1 : 0,
    info.handler.doubleSided ? 1 : 0].join('|');
  if (materialCache.has(key)) return materialCache.get(key);

  const onLoad = (loadedTex) => { mat.map = loadedTex; mat.needsUpdate = true; };
  const map0 = (faceVal && typeof faceVal === 'object' && faceVal.crop)
    ? getCroppedTexture(faceVal.tex, faceVal.crop, onLoad, faceVal.atlas || 64)
    : getTexture(faceVal, onLoad);
  const mat = new THREE.MeshLambertMaterial({
    map: map0,
    transparent: info.transparent,
    alphaTest: info.transparent ? 0.1 : 0,
    depthWrite: !info.transparent,
    color: info.tint ?? 0xffffff,
    side: info.handler.doubleSided ? THREE.DoubleSide : THREE.FrontSide,
  });
  materialCache.set(key, mat);
  return mat;
}

function buildGroup(doc) {
  const group = new THREE.Group();

  // 1) paleta → handler + texturas
  const paletteInfo = {};
  for (const [idxStr, raw] of Object.entries(doc.block_palette)) {
    const parsed = parseBlock(raw);
    const name = remapName(parsed.name);
    const props = parsed.props;
    const handler = resolveHandler(name, props);
    paletteInfo[Number(idxStr)] = {
      name,
      props,
      handler,
      faces: handler.faces(name, props),
      rotation: handler.rotation ? handler.rotation(name, props) : null,
      transparent: handler.transparent ? handler.transparent(name, props) : false,
      tint: handler.tint ? handler.tint(name, props) : null,
    };
  }

  // 2) agrupa vóxeles por entrada de paleta
  const byPalette = new Map();
  for (const [x, y, z, p] of doc.voxels) {
    if (!byPalette.has(p)) byPalette.set(p, []);
    byPalette.get(p).push([x, y, z]);
  }

  // 3) un InstancedMesh por entrada
  const faceOrder = ['east', 'west', 'up', 'down', 'south', 'north'];
  const tmpMatrix = new THREE.Matrix4();
  const tmpQuat = new THREE.Quaternion();
  const tmpEuler = new THREE.Euler();
  const tmpPos = new THREE.Vector3();
  const ONE = new THREE.Vector3(1, 1, 1);

  for (const [paletteIdx, positions] of byPalette.entries()) {
    const info = paletteInfo[paletteIdx];
    if (!info) continue;
    const geom = info.handler.geometry(info.name, info.props);
    const materials = faceOrder.map((f) => materialFor(info.faces[f], info));
    const mesh = new THREE.InstancedMesh(geom, materials, positions.length);
    mesh.instanceMatrix.setUsage(THREE.StaticDrawUsage);

    if (info.rotation) {
      tmpEuler.set(info.rotation.x, info.rotation.y, info.rotation.z);
      tmpQuat.setFromEuler(tmpEuler);
    } else {
      tmpQuat.identity();
    }
    for (let i = 0; i < positions.length; i++) {
      const [x, y, z] = positions[i];
      // el vóxel (x,y,z) ocupa la celda [x,x+1)×… → centro en +0.5
      tmpPos.set(x + 0.5, y + 0.5, z + 0.5);
      tmpMatrix.compose(tmpPos, tmpQuat, ONE);
      mesh.setMatrixAt(i, tmpMatrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
    mesh.computeBoundingSphere();
    mesh.matrixAutoUpdate = false;
    group.add(mesh);
  }
  return group;
}

export default function VoxelBuilding({ doc }) {
  const group = useMemo(() => buildGroup(doc), [doc]);
  // al cambiar de edificio se desechan las geometrías (los materiales y
  // texturas quedan cacheados para el siguiente)
  useEffect(() => () => {
    group.traverse((o) => o.geometry?.dispose());
  }, [group]);
  return <primitive object={group} />;
}
