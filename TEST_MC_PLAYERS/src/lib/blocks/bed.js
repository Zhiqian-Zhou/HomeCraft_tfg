// Bed handler — 16 colored beds (white_bed, …, black_bed).
//
// Minecraft 1.16.5 beds occupy two adjacent voxels (part=head + part=foot),
// each 1 × 9/16 voxels tall. The real textures live under entity/bed/<color>.png
// as a complex atlas. Aquí renderizamos cada mitad como una cama RECONOCIBLE y
// VISIBLE en cualquier suelo:
//   • cara superior (up) = lana del color de la cama (el colchón/sábana)
//   • caras laterales y base = MADERA (marco de la cama)
// Así la cama se lee como cama (colchón de color sobre marco de madera) y NO se
// camufla con suelos del mismo color (p.ej. white_bed sobre suelo de quartz
// blanco): el marco de madera la delinea siempre.

import * as THREE from 'three';
import { register } from './index.js';

// Geometría: 1 ancho × 9/16 alto × 1 fondo, base plantada en el suelo.
let _sharedBed = null;
function bedGeometry() {
  if (!_sharedBed) {
    _sharedBed = new THREE.BoxGeometry(1, 0.5625, 1);
    _sharedBed.translate(0, -0.21875, 0);
  }
  return _sharedBed.clone();
}

function bedColor(name) {
  return name.replace(/^minecraft:/, '').replace(/_bed$/, '');  // p.ej. "red"
}
const FRAME_TEX = 'oak_planks';        // marco de madera (lados + base)
// Región del atlas REAL de la cama (entity/bed/<color>.png, 64×64) que muestra
// el COLCHÓN + la ALMOHADA visto desde arriba → la cama se ve como la de
// Minecraft de verdad. [x, y, w, h] en px del atlas de 64.
const MATTRESS_TOP_CROP = [6, 6, 16, 16];

register(
  (name) => /_bed$/.test(name),
  {
    geometry: () => bedGeometry(),
    faces(name) {
      const tex = 'entity/bed/' + bedColor(name);   // atlas real de la cama MC
      // up = colchón+almohada del atlas real; lados = marco de madera (se lee
      // como cama y contrasta con cualquier suelo).
      return {
        up: { tex, crop: MATTRESS_TOP_CROP, atlas: 64 },
        down: FRAME_TEX, north: FRAME_TEX, south: FRAME_TEX,
        east: FRAME_TEX, west: FRAME_TEX,
      };
    },
    rotation(_name, props) {
      const f = props && props.facing;
      if (f === 'east')  return { x: 0, y: -Math.PI / 2, z: 0 };
      if (f === 'south') return { x: 0, y:  Math.PI,     z: 0 };
      if (f === 'west')  return { x: 0, y:  Math.PI / 2, z: 0 };
      return null;
    },
    transparent: () => false,
    tint: () => null,
  },
);
