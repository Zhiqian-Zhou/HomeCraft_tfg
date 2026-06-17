// Plano 2D por planta: rectángulos de salas coloreados por rol + escaleras +
// marcador del jugador (posición y orientación). La planta mostrada sigue
// automáticamente al jugador (según su altura), pero puede fijarse a mano.

import { useEffect, useRef, useState } from 'react';
import { playerState } from '../store.js';

// color estable por rol (paleta suave, contraste con el fondo claro)
const ROLE_COLORS = [
  '#8ecae6', '#ffb4a2', '#b7e4c7', '#ffd166', '#cdb4db', '#f4a8c0',
  '#a9def9', '#e9c46a', '#90be6d', '#f8961e', '#bdb2ff', '#70d6ff',
];
const roleColor = (() => {
  const assigned = new Map();
  return (role) => {
    if (!assigned.has(role)) {
      assigned.set(role, ROLE_COLORS[assigned.size % ROLE_COLORS.length]);
    }
    return assigned.get(role);
  };
})();

/** rango vertical [y0,y1) de una planta = unión de sus salas */
function floorYRange(floor) {
  let y0 = Infinity, y1 = -Infinity;
  for (const r of floor.rooms) {
    y0 = Math.min(y0, r.aabb[1]);
    y1 = Math.max(y1, r.aabb[4]);
  }
  return y0 <= y1 ? [y0, y1] : null;
}

export default function FloorPlan({ building }) {
  const canvasRef = useRef();
  const [manual, setManual] = useState(null); // índice fijado a mano, o null = seguir al jugador
  const [shown, setShown] = useState(0);

  const floors = (building?.floors ?? []).filter((f) => f.rooms.length > 0);

  // sigue al jugador + repinta el marcador (~6 veces/s)
  useEffect(() => {
    if (!building) return undefined;
    const timer = setInterval(() => {
      let idx = manual;
      if (idx == null) {
        // planta cuyo rango vertical contiene los pies del jugador
        const y = playerState.y;
        idx = 0;
        for (let i = 0; i < floors.length; i++) {
          const range = floorYRange(floors[i]);
          if (range && y >= range[0] - 0.5) idx = i;
        }
      }
      setShown(Math.min(idx, Math.max(floors.length - 1, 0)));
      draw(canvasRef.current, building, floors[Math.min(idx, floors.length - 1)]);
    }, 160);
    return () => clearInterval(timer);
  }, [building, manual, floors.length]);

  if (!building || floors.length === 0) {
    return <p className="text-xs text-stone-400">Este edificio no tiene planos de planta.</p>;
  }

  const floor = floors[shown];
  const roles = [...new Map(floor.rooms.map((r) => [r.role, r.label])).entries()];

  return (
    <div>
      {/* selector de plantas */}
      <div className="flex flex-wrap gap-1 mb-2">
        <button
          onClick={() => setManual(null)}
          className={`px-2 py-0.5 rounded text-xs border ${manual == null
            ? 'bg-emerald-600 text-white border-emerald-600'
            : 'bg-white text-stone-600 border-stone-300 hover:bg-stone-100'}`}
          title="La planta mostrada sigue al jugador"
        >📍 Auto</button>
        {floors.map((f, i) => (
          <button
            key={f.floor_index}
            onClick={() => setManual(i)}
            className={`px-2 py-0.5 rounded text-xs border ${manual === i || (manual == null && shown === i)
              ? 'bg-sky-600 text-white border-sky-600'
              : 'bg-white text-stone-600 border-stone-300 hover:bg-stone-100'}`}
          >{i === 0 ? 'PB' : 'P' + i}</button>
        ))}
      </div>
      <canvas ref={canvasRef} className="w-full rounded border border-stone-300 bg-stone-50" />
      {/* leyenda de roles */}
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5">
        {roles.map(([role, label]) => (
          <span key={role} className="inline-flex items-center gap-1 text-[11px] text-stone-600">
            <span className="inline-block w-2.5 h-2.5 rounded-sm border border-stone-400"
                  style={{ background: roleColor(role) }} />
            {label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1 text-[11px] text-stone-600">
          <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-600" /> Tú
        </span>
      </div>
    </div>
  );
}

function draw(canvas, building, floor) {
  if (!canvas || !floor) return;
  const [W, , D] = building.bounding_box.size;
  const cssW = canvas.clientWidth || 220;
  const scale = (cssW - 12) / Math.max(W, D);
  const cssH = Math.round(D * scale) + 12;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = cssW * dpr;
  canvas.height = cssH * dpr;
  canvas.style.height = cssH + 'px';
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, cssH);
  const ox = (cssW - W * scale) / 2;
  const oz = 6;

  // contorno del edificio
  ctx.strokeStyle = '#d6d3d1';
  ctx.strokeRect(ox, oz, W * scale, D * scale);

  // salas
  for (const r of floor.rooms) {
    const [x0, , z0, x1, , z1] = r.aabb;
    const rx = ox + x0 * scale, rz = oz + z0 * scale;
    const rw = (x1 - x0) * scale, rh = (z1 - z0) * scale;
    ctx.fillStyle = roleColor(r.role);
    ctx.globalAlpha = 0.85;
    ctx.fillRect(rx, rz, rw, rh);
    ctx.globalAlpha = 1;
    ctx.strokeStyle = '#78716c';
    ctx.strokeRect(rx, rz, rw, rh);
    if (rw > 46 && rh > 14) {
      ctx.fillStyle = '#44403c';
      ctx.font = '600 9px system-ui';
      ctx.textBaseline = 'top';
      ctx.fillText(r.label, rx + 3, rz + 3, rw - 6);
    }
  }

  // escaleras (huella reservada)
  for (const s of floor.stairs ?? []) {
    const rx = ox + s.x0 * scale, rz = oz + s.z0 * scale;
    const rw = (s.x1 - s.x0) * scale, rh = (s.z1 - s.z0) * scale;
    ctx.fillStyle = '#a8a29e';
    ctx.fillRect(rx, rz, rw, rh);
    ctx.fillStyle = '#fafaf9';
    ctx.font = '700 8px system-ui';
    ctx.fillText('≡', rx + rw / 2 - 3, rz + rh / 2 - 4);
  }

  // jugador: punto + flecha de orientación
  const px = ox + playerState.x * scale;
  const pz = oz + playerState.z * scale;
  ctx.fillStyle = '#dc2626';
  ctx.beginPath();
  ctx.arc(px, pz, 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#dc2626';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(px, pz);
  ctx.lineTo(px + Math.sin(playerState.yaw) * 8, pz + Math.cos(playerState.yaw) * 8);
  ctx.stroke();
  ctx.lineWidth = 1;
}
