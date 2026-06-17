// Físicas de vóxeles estilo Minecraft, sin librería externa.
//
// - Los bloques sólidos del edificio se indexan en un Set "x,y,z" → consulta
//   O(1) de "¿está ocupada esta celda?".
// - El jugador es un AABB de 0.6 × 1.8 (ojo a 1.62, como Minecraft) sometido
//   a gravedad; la resolución de colisiones es POR EJE (x, luego y, luego z),
//   el patrón estándar de los clones de Minecraft: evita atravesar esquinas y
//   da "deslizamiento" por las paredes gratis.
// - Step-up automático de 1 bloque cuando se anda contra un escalón con
//   espacio libre encima → subir escaleras sin saltar.
// - El suelo del mundo (plano y=0) siempre es sólido.

import { parseBlock } from './blockstate.js';
import { remapName } from './remap.js';

export const PLAYER = {
  width: 0.6,
  height: 1.8,
  eye: 1.62,
  walkSpeed: 4.3,
  flySpeed: 11,
  jumpSpeed: 8.5,
  gravity: 30,
  stepHeight: 1.05, // sube escalones de 1 bloque sin saltar
};

// Bloques por los que el jugador PASA (no colisionan). El resto de la paleta
// se trata como celda sólida completa (stairs/slabs/fences incluidos: mejor
// sólido de más que caerse por una ventana).
const NON_SOLID_EXACT = new Set([
  'air', 'water', 'torch', 'wall_torch', 'soul_torch', 'soul_wall_torch',
  'lantern', 'soul_lantern', 'end_rod', 'chain', 'ladder', 'vine', 'cobweb',
  'lily_pad', 'bamboo', 'sugar_cane', 'flower_pot', 'campfire',
  'dead_bush', 'fern', 'large_fern', 'grass', 'tall_grass', 'sweet_berry_bush',
  'poppy', 'dandelion', 'blue_orchid', 'allium', 'azure_bluet', 'cornflower',
  'lily_of_the_valley', 'oxeye_daisy', 'wither_rose', 'red_tulip',
  'orange_tulip', 'white_tulip', 'pink_tulip',
]);

function isSolidName(name) {
  if (NON_SOLID_EXACT.has(name)) return false;
  if (name.endsWith('_door')) return false;          // se entra sin abrir puertas
  if (name.endsWith('_carpet')) return false;
  if (name.endsWith('_button')) return false;
  if (name.endsWith('_pressure_plate')) return false;
  if (name.endsWith('_sapling')) return false;
  if (name.endsWith('_sign')) return false;
  if (name.endsWith('_torch')) return false;
  return true;
}

/** Construye el índice de colisión de un edificio. */
export function buildCollider(doc) {
  const solid = new Set();
  const solidByPalette = {};
  for (const [idx, raw] of Object.entries(doc.block_palette)) {
    const { name } = parseBlock(raw);
    solidByPalette[idx] = isSolidName(remapName(name));
  }
  for (const [x, y, z, p] of doc.voxels) {
    if (solidByPalette[p]) solid.add(x + ',' + y + ',' + z);
  }
  return {
    isSolid(x, y, z) {
      if (y < 0) return true; // suelo del mundo
      return solid.has(x + ',' + y + ',' + z);
    },
  };
}

/** ¿El AABB del jugador (centro-pies en pos) solapa algún bloque sólido? */
export function collides(collider, px, py, pz) {
  const hw = PLAYER.width / 2;
  const x0 = Math.floor(px - hw), x1 = Math.floor(px + hw - 1e-7);
  const y0 = Math.floor(py),      y1 = Math.floor(py + PLAYER.height - 1e-7);
  const z0 = Math.floor(pz - hw), z1 = Math.floor(pz + hw - 1e-7);
  for (let x = x0; x <= x1; x++)
    for (let y = y0; y <= y1; y++)
      for (let z = z0; z <= z1; z++)
        if (collider.isSolid(x, y, z)) return true;
  return false;
}

/**
 * Avanza al jugador un paso de simulación con colisiones por eje.
 * `state` = { pos: {x,y,z} (pies), vel: {x,y,z}, onGround: bool } — se MUTA.
 */
export function stepPlayer(collider, state, dt) {
  const p = state.pos, v = state.vel;

  // gravedad
  v.y -= PLAYER.gravity * dt;
  if (v.y < -50) v.y = -50; // velocidad terminal

  // eje X (con step-up si está en el suelo)
  moveAxisHorizontal(collider, state, 'x', v.x * dt);
  // eje Z
  moveAxisHorizontal(collider, state, 'z', v.z * dt);

  // eje Y
  const dy = v.y * dt;
  state.onGround = false;
  if (dy !== 0) {
    const ny = p.y + dy;
    if (!collides(collider, p.x, ny, p.z)) {
      p.y = ny;
    } else if (dy < 0) {
      // aterriza: ajusta los pies a la cara superior del bloque
      p.y = Math.floor(p.y - 1e-7 + dy) + 1;
      // por si el snap quedara dentro de algo (esquinas raras), sube de 1 en 1
      let guard = 0;
      while (collides(collider, p.x, p.y, p.z) && guard++ < 4) p.y += 1;
      v.y = 0;
      state.onGround = true;
    } else {
      // golpea el techo
      v.y = 0;
    }
  }
  // ¿hay suelo justo debajo? (para permitir saltar tras deslizar por bordes)
  if (!state.onGround && v.y <= 0 &&
      collides(collider, p.x, p.y - 0.05, p.z)) {
    state.onGround = true;
    v.y = 0;
  }
}

function moveAxisHorizontal(collider, state, axis, delta) {
  if (delta === 0) return;
  const p = state.pos;
  const next = { x: p.x, y: p.y, z: p.z };
  next[axis] += delta;
  if (!collides(collider, next.x, next.y, next.z)) {
    p[axis] = next[axis];
    return;
  }
  // step-up: si está apoyado, prueba a subir hasta stepHeight y avanzar
  if (state.onGround) {
    for (const lift of [1.0, PLAYER.stepHeight]) {
      if (!collides(collider, next.x, p.y + lift, next.z) &&
          !collides(collider, p.x, p.y + lift, p.z)) {
        p[axis] = next[axis];
        p.y += lift;
        // tras subir, deja que la gravedad lo asiente en el escalón
        return;
      }
    }
  }
  // bloqueado: anula la componente de velocidad (deslizamiento por pared)
  state.vel[axis] = 0;
}

/** Vuelo (modo SUPER): sin gravedad ni colisión, atraviesa bloques. */
export function stepFly(state, dt) {
  state.pos.x += state.vel.x * dt;
  state.pos.y += state.vel.y * dt;
  state.pos.z += state.vel.z * dt;
  state.onGround = false;
}

/** Punto de aparición: fuera del bbox, a pie de suelo, mirando al edificio. */
export function spawnPoint(doc) {
  const [W, , D] = doc.bounding_box.size;
  return {
    pos: { x: W / 2, y: 0, z: D + 6 },   // 6 bloques al sur de la fachada
    yaw: Math.PI,                          // mirando hacia -Z… (ver Player)
  };
}
