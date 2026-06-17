// Canvas 3D: cielo, luces, terreno, el edificio actual y el jugador.
//
// El pointer lock se pide desde el overlay del HUD (no desde el canvas):
// aquí solo se registra la función lock() en playerState.requestLock y se
// notifica al store cuando se gana/pierde el lock (ESC).

import { Canvas } from '@react-three/fiber';
import { PointerLockControls, Sky } from '@react-three/drei';
import { useEffect, useRef } from 'react';
import { useStore, playerState } from '../store.js';
import VoxelBuilding from './VoxelBuilding.jsx';
import Player from './Player.jsx';

function Scene() {
  const building = useStore((s) => s.building);
  const setLocked = useStore((s) => s.setLocked);
  const controls = useRef();

  useEffect(() => {
    // el overlay del HUD llama a esto al hacer clic
    playerState.requestLock = () => {
      try { controls.current?.lock(); } catch { /* cooldown del navegador */ }
    };
    return () => { playerState.requestLock = null; };
  }, []);

  const size = building?.bounding_box?.size ?? [30, 20, 30];
  const ground = Math.max(size[0], size[2]) * 6 + 200;

  return (
    <>
      <Sky distance={4500} sunPosition={[80, 120, 60]} turbidity={6} rayleigh={1.2} />
      <hemisphereLight args={[0xcfe8ff, 0x7a6a55, 0.85]} />
      <directionalLight position={[80, 120, 60]} intensity={1.15} color={0xfff4e0} />
      <ambientLight intensity={0.55} />
      <fog attach="fog" args={[0xdcefff, 80, 420]} />

      {/* terreno: césped infinito a y=0 (las físicas lo tratan como sólido) */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[size[0] / 2, 0, size[2] / 2]}>
        <planeGeometry args={[ground, ground]} />
        <meshLambertMaterial color={0x6aa84f} />
      </mesh>

      {building && <VoxelBuilding doc={building} key={building.num} />}
      {building && <Player doc={building} key={'p' + building.num} />}

      {/* selector="#scene": el clic que captura el cursor SOLO cuenta dentro del
          panel 3D. Sin esto, drei engancha el "click→lock" a `document` entero
          y pulsar un número de puntuación en el sidebar re-capturaba el ratón. */}
      <PointerLockControls
        ref={controls}
        makeDefault
        selector="#scene"
        onLock={() => setLocked(true)}
        onUnlock={() => setLocked(false)}
      />
    </>
  );
}

export default function World() {
  return (
    <Canvas
      camera={{ fov: 75, near: 0.1, far: 1200, position: [0, 10, 30] }}
      gl={{ antialias: true }}
      dpr={[1, 2]}
    >
      <Scene />
    </Canvas>
  );
}
