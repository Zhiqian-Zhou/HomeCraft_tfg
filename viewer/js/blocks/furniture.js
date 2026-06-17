// Utility furniture handler — brewing_stand, cauldron, enchanting_table,
// anvil family, chest variants, hopper, end_portal_frame, composter, barrel.
//
// Each block uses a simplified box geometry (smaller than a full cube and/or
// shifted down to sit on the floor) plus a per-face texture map that
// distinguishes top/bottom from sides where the Minecraft 1.16.5 asset set
// provides distinct textures.

import * as THREE from 'three';
import { register } from './index.js';

const brewingGeom = new THREE.BoxGeometry(0.875, 0.875, 0.875);
brewingGeom.translate(0, -0.0625, 0);

const cauldronGeom = new THREE.BoxGeometry(1, 1, 1);

const enchantingGeom = new THREE.BoxGeometry(1, 0.75, 1);
enchantingGeom.translate(0, -0.125, 0);

const anvilGeom = new THREE.BoxGeometry(0.75, 1, 0.75);

const chestGeom = new THREE.BoxGeometry(0.875, 0.875, 0.875);
chestGeom.translate(0, -0.0625, 0);

const hopperGeom = new THREE.BoxGeometry(1, 0.625, 1);
hopperGeom.translate(0, -0.1875, 0);

const endPortalGeom = new THREE.BoxGeometry(1, 0.8125, 1);
endPortalGeom.translate(0, -0.09375, 0);

const fullCube = new THREE.BoxGeometry(1, 1, 1);

function facesFor(name) {
  switch (name) {
    case 'brewing_stand':
      return { up: 'brewing_stand_base', down: 'brewing_stand_base',
               north: 'brewing_stand', south: 'brewing_stand',
               east: 'brewing_stand', west: 'brewing_stand' };
    case 'cauldron':
      return { up: 'cauldron_top', down: 'cauldron_bottom',
               north: 'cauldron_side', south: 'cauldron_side',
               east: 'cauldron_side', west: 'cauldron_side' };
    case 'enchanting_table':
      return { up: 'enchanting_table_top', down: 'enchanting_table_bottom',
               north: 'enchanting_table_side', south: 'enchanting_table_side',
               east: 'enchanting_table_side', west: 'enchanting_table_side' };
    case 'anvil':
    case 'chipped_anvil':
    case 'damaged_anvil': {
      const top = name === 'anvil' ? 'anvil_top' :
                  name === 'chipped_anvil' ? 'chipped_anvil_top' : 'damaged_anvil_top';
      return { up: top, down: 'anvil', north: 'anvil', south: 'anvil',
               east: 'anvil', west: 'anvil' };
    }
    case 'chest':
    case 'trapped_chest':
      return { up: 'oak_planks', down: 'oak_planks',
               north: 'oak_planks', south: 'oak_planks',
               east: 'oak_planks', west: 'oak_planks' };
    case 'ender_chest':
      return { up: 'obsidian', down: 'obsidian',
               north: 'obsidian', south: 'obsidian',
               east: 'obsidian', west: 'obsidian' };
    case 'hopper':
      return { up: 'hopper_top', down: 'hopper_outside',
               north: 'hopper_outside', south: 'hopper_outside',
               east: 'hopper_outside', west: 'hopper_outside' };
    case 'end_portal_frame':
      return { up: 'end_portal_frame_top', down: 'end_stone',
               north: 'end_portal_frame_side', south: 'end_portal_frame_side',
               east: 'end_portal_frame_side', west: 'end_portal_frame_side' };
    case 'composter':
      return { up: 'composter_top', down: 'composter_bottom',
               north: 'composter_side', south: 'composter_side',
               east: 'composter_side', west: 'composter_side' };
    case 'barrel':
      return { up: 'barrel_top', down: 'barrel_bottom',
               north: 'barrel_side', south: 'barrel_side',
               east: 'barrel_side', west: 'barrel_side' };
    default:
      return { up: name, down: name, north: name, south: name, east: name, west: name };
  }
}

const matchFn = (name) =>
  /^(brewing_stand|cauldron|enchanting_table|anvil|chipped_anvil|damaged_anvil|chest|ender_chest|trapped_chest|hopper|end_portal_frame|composter|barrel)$/.test(name);

register(matchFn, {
  geometry(name) {
    if (name === 'brewing_stand') return brewingGeom.clone();
    if (name === 'cauldron') return cauldronGeom.clone();
    if (name === 'enchanting_table') return enchantingGeom.clone();
    if (name.endsWith('anvil')) return anvilGeom.clone();
    if (name === 'chest' || name === 'trapped_chest' || name === 'ender_chest') return chestGeom.clone();
    if (name === 'hopper') return hopperGeom.clone();
    if (name === 'end_portal_frame') return endPortalGeom.clone();
    return fullCube.clone();
  },
  faces: facesFor,
  rotation(name, props) {
    if (name.endsWith('anvil') || name === 'chest' || name === 'trapped_chest' ||
        name === 'ender_chest' || name === 'barrel') {
      const f = props && props.facing;
      if (f === 'east')  return { x: 0, y: -Math.PI / 2, z: 0 };
      if (f === 'south') return { x: 0, y: Math.PI,      z: 0 };
      if (f === 'west')  return { x: 0, y: Math.PI / 2,  z: 0 };
    }
    return null;
  },
  transparent: () => false,
  tint: () => null,
});
