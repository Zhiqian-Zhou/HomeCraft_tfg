// Trapdoors + thin panels handler.
//
// Covers: trapdoors (wood + iron), buttons (wood + stone + blackstone),
// daylight_detector, cake, flower_pot. All are sub-voxel "thin" shapes
// that need a custom BoxGeometry rather than the default unit cube.

import * as THREE from 'three';
import { register } from './index.js';

// --- Geometries (built once, cloned per instance) ----------------------------

const trapdoorBottom = new THREE.BoxGeometry(1, 0.1875, 1);
trapdoorBottom.translate(0, -0.40625, 0); // sit at floor

const trapdoorTop = new THREE.BoxGeometry(1, 0.1875, 1);
trapdoorTop.translate(0, 0.40625, 0); // sit at ceiling

const buttonGeom = new THREE.BoxGeometry(0.375, 0.125, 0.125);
buttonGeom.translate(0, 0, -0.4375); // pegado al muro norte por defecto (z=[-0.5,-0.375])

const daylightGeom = new THREE.BoxGeometry(1, 0.375, 1);
daylightGeom.translate(0, -0.3125, 0);

const cakeGeom = new THREE.BoxGeometry(0.875, 0.5, 0.875);
cakeGeom.translate(0, -0.25, 0);

const flowerPotGeom = new THREE.BoxGeometry(0.375, 0.375, 0.375);
flowerPotGeom.translate(0, -0.3125, 0);

// --- Texture resolution ------------------------------------------------------

function textureFor(name) {
  if (name.endsWith('_trapdoor')) {
    // Trapdoor textures are already named e.g. oak_trapdoor.png
    return name;
  }
  if (name.endsWith('_button')) {
    const base = name.replace(/_button$/, '');
    if (base === 'stone') return 'stone';
    if (base === 'polished_blackstone') return 'polished_blackstone';
    return base + '_planks'; // wood buttons use planks texture
  }
  if (name === 'daylight_detector') return 'daylight_detector_top';
  if (name === 'cake') return 'cake_top';
  if (name === 'flower_pot') return 'flower_pot';
  return name;
}

// --- Matcher -----------------------------------------------------------------

const matchFn = (name) =>
  name.endsWith('_trapdoor') ||
  name.endsWith('_button') ||
  name === 'daylight_detector' ||
  name === 'cake' ||
  name === 'flower_pot';

// --- Handler -----------------------------------------------------------------

register(matchFn, {
  geometry(name, props) {
    if (name.endsWith('_trapdoor')) {
      return (props && props.half === 'top')
        ? trapdoorTop.clone()
        : trapdoorBottom.clone();
    }
    if (name.endsWith('_button')) return buttonGeom.clone();
    if (name === 'daylight_detector') return daylightGeom.clone();
    if (name === 'cake') return cakeGeom.clone();
    if (name === 'flower_pot') return flowerPotGeom.clone();
    return trapdoorBottom.clone();
  },
  faces(name) {
    const t = textureFor(name);
    return { up: t, down: t, north: t, south: t, east: t, west: t };
  },
  rotation(name, props) {
    if (name.endsWith('_button') && props) {
      const f = props.facing;
      if (f === 'east')  return { x: 0, y: -Math.PI / 2, z: 0 };
      if (f === 'south') return { x: 0, y: Math.PI,      z: 0 };
      if (f === 'west')  return { x: 0, y: Math.PI / 2,  z: 0 };
    }
    return null;
  },
  transparent: (name) => name.endsWith('_trapdoor'),
  tint: () => null,
});
