// Jugador en primera persona.
//
// - Modo "walk": gravedad + colisiones AABB contra el grid de vóxeles
//   (lib/physics.js), salto con espacio, step-up automático en escaleras.
// - Modo "fly" (SUPER): vuelo libre SIN colisiones (atraviesa bloques);
//   espacio sube, shift baja. Se alterna con F o doble-espacio.
// - La cámara la orienta PointerLockControls (en World.jsx); aquí solo
//   movemos su posición. Las teclas se leen por event.code → WASD funciona
//   también en teclados AZERTY, y las flechas sirven igual.
//
// Rendimiento: nada de estado React por frame — teclas y física viven en
// refs; el plano de planta lee playerState (objeto mutable) por su cuenta.

import * as THREE from 'three';
import { useEffect, useMemo, useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { useStore, playerState } from '../store.js';
import { buildCollider, stepPlayer, stepFly, collides, PLAYER } from '../lib/physics.js';

const SUBSTEP = 1 / 120;        // paso fijo de simulación
const MAX_DELTA = 0.05;          // clamp anti-teletransporte al cambiar de pestaña

export default function Player({ doc }) {
  const camera = useThree((s) => s.camera);
  const mode = useStore((s) => s.mode);
  const locked = useStore((s) => s.locked);
  const toggleMode = useStore((s) => s.toggleMode);

  const collider = useMemo(() => buildCollider(doc), [doc]);
  const keys = useRef(new Set());
  const state = useRef({ pos: { x: 0, y: 0, z: 0 }, vel: { x: 0, y: 0, z: 0 }, onGround: false });
  const acc = useRef(0);
  const lastSpace = useRef(0);

  // — aparición al cargar un edificio: fuera de la fachada sur, mirando al centro —
  useEffect(() => {
    const [W, H, D] = doc.bounding_box.size;
    const s = state.current;
    // distancia de aparición proporcional al tamaño: que el edificio se vea entero
    const back = Math.min(45, Math.max(10, Math.max(W, H) * 0.9));
    s.pos = { x: W / 2 + 0.5, y: 0, z: D + back };
    s.vel = { x: 0, y: 0, z: 0 };
    // por si hubiera bloques justo ahí, sube hasta quedar libre
    let guard = 0;
    while (collides(collider, s.pos.x, s.pos.y, s.pos.z) && guard++ < 60) s.pos.y += 1;
    camera.position.set(s.pos.x, s.pos.y + PLAYER.eye, s.pos.z);
    camera.lookAt(W / 2, H * 0.35, D / 2);
  }, [doc, collider, camera]);

  // — teclado —
  useEffect(() => {
    const down = (e) => {
      if (e.repeat) return;
      keys.current.add(e.code);
      if (e.code === 'KeyF') toggleMode();
      if (e.code === 'Space') {
        const now = performance.now();
        if (now - lastSpace.current < 280) toggleMode(); // doble-espacio = SUPER
        lastSpace.current = now;
        e.preventDefault();
      }
    };
    const up = (e) => keys.current.delete(e.code);
    const blur = () => keys.current.clear();
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    window.addEventListener('blur', blur);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
      window.removeEventListener('blur', blur);
    };
  }, [toggleMode]);

  const fwd = useMemo(() => new THREE.Vector3(), []);
  const right = useMemo(() => new THREE.Vector3(), []);

  useFrame((_, delta) => {
    const s = state.current;
    const k = keys.current;

    // dirección de la cámara proyectada al plano XZ
    camera.getWorldDirection(fwd);
    fwd.y = 0;
    if (fwd.lengthSq() < 1e-6) fwd.set(0, 0, -1);
    fwd.normalize();
    right.crossVectors(fwd, THREE.Object3D.DEFAULT_UP).normalize();

    let mx = 0, mz = 0;
    if (locked) {
      if (k.has('KeyW') || k.has('ArrowUp')) mz += 1;
      if (k.has('KeyS') || k.has('ArrowDown')) mz -= 1;
      if (k.has('KeyD') || k.has('ArrowRight')) mx += 1;
      if (k.has('KeyA') || k.has('ArrowLeft')) mx -= 1;
    }
    const moving = mx !== 0 || mz !== 0;
    const norm = moving ? 1 / Math.hypot(mx, mz) : 0;

    acc.current = Math.min(acc.current + Math.min(delta, MAX_DELTA), 0.25);
    while (acc.current >= SUBSTEP) {
      acc.current -= SUBSTEP;
      if (mode === 'fly') {
        const sp = k.has('ShiftLeft') || k.has('ShiftRight') ? PLAYER.flySpeed * 1 : PLAYER.flySpeed;
        s.vel.x = (fwd.x * mz + right.x * mx) * norm * sp;
        s.vel.z = (fwd.z * mz + right.z * mx) * norm * sp;
        s.vel.y = 0;
        if (locked && k.has('Space')) s.vel.y = sp;
        if (locked && (k.has('ShiftLeft') || k.has('ShiftRight'))) s.vel.y = -sp;
        stepFly(s, SUBSTEP);
      } else {
        s.vel.x = (fwd.x * mz + right.x * mx) * norm * PLAYER.walkSpeed;
        s.vel.z = (fwd.z * mz + right.z * mx) * norm * PLAYER.walkSpeed;
        if (locked && k.has('Space') && s.onGround) s.vel.y = PLAYER.jumpSpeed;
        stepPlayer(collider, s, SUBSTEP);
      }
    }

    // red de seguridad: si cae al vacío, reaparece
    if (s.pos.y < -30) {
      const [W, , D] = doc.bounding_box.size;
      s.pos = { x: W / 2 + 0.5, y: 0, z: D + 7 };
      s.vel = { x: 0, y: 0, z: 0 };
    }

    camera.position.set(s.pos.x, s.pos.y + PLAYER.eye, s.pos.z);

    // publica posición/yaw para el plano de planta (lectura fuera de React)
    playerState.x = s.pos.x;
    playerState.y = s.pos.y;
    playerState.z = s.pos.z;
    playerState.yaw = Math.atan2(fwd.x, fwd.z);
  });

  return null;
}
