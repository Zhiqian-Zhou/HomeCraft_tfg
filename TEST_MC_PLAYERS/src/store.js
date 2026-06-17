// Estado global (zustand). Conecta el panel de puntuación con el edificio
// que se está renderizando en el canvas, y persiste el progreso.
//
// IMPORTANTE rendimiento: la posición del jugador NO vive aquí (cambia cada
// frame). Vive en `playerState` (objeto mutable) y la UI que la necesita
// (el plano de planta) la lee con un intervalo corto.

import { create } from 'zustand';
import { loadSaved, save, postRow, buildRow } from './lib/results.js';
import { DIMENSIONS } from './config.js';

// — estado mutable de alta frecuencia (fuera de React) —
export const playerState = {
  x: 0, y: 0, z: 0, yaw: 0,
  teleport: null,        // {x,y,z} → Player lo consume y recoloca
};

const saved = loadSaved();

export const useStore = create((set, get) => ({
  // — participante y progreso persistido —
  participant: saved.participant ?? '',
  scores: saved.scores ?? {},   // num → {q1..q8}
  sent: saved.sent ?? {},       // num → true (fila ya en Google Sheets)
  times: saved.times ?? {},     // num → segundos acumulados de exploración
  pendingQueue: [],             // filas que fallaron al enviarse (reintento)

  // — sesión —
  index: [],                    // index.json
  building: null,               // JSON completo del edificio actual
  currentNum: null,
  loading: false,
  mode: 'walk',                 // 'walk' | 'fly' (SUPER)
  locked: false,                // pointer lock activo
  showWelcome: !(saved.participant),
  enteredAt: null,              // timestamp de inicio de exploración

  setParticipant(name) {
    set({ participant: name });
    save(get());
  },
  closeWelcome() { set({ showWelcome: false }); },
  openWelcome() { set({ showWelcome: true }); },
  setLocked(locked) { set({ locked }); },
  toggleMode() {
    set((s) => ({ mode: s.mode === 'walk' ? 'fly' : 'walk' }));
  },

  async loadIndex(base) {
    let index;
    try {
      const res = await fetch(base + 'data/index.json');
      if (!res.ok) throw new Error('sin index.json');
      index = await res.json();
    } catch {
      // fallback de desarrollo: la casita mock (sin los 20 edificios reales)
      index = [{ num: 0, key: 'mock-house', type: 'residential',
                 style: 'rustic', file: 'mock.json' }];
    }
    set({ index });
    // reanuda en el primer edificio sin puntuar
    const { scores } = get();
    const next = index.find((b) => !isComplete(scores[b.num])) ?? index[0];
    await get().selectBuilding(next.num, base);
  },

  async selectBuilding(num, base) {
    const { index, currentNum, enteredAt } = get();
    if (num === currentNum) return;
    get()._accumulateTime(currentNum, enteredAt);
    const entry = index.find((b) => b.num === num);
    if (!entry) return;
    set({ loading: true });
    const res = await fetch(base + 'data/' + entry.file);
    const building = await res.json();
    set({ building, currentNum: num, loading: false, enteredAt: Date.now() });
  },

  _accumulateTime(num, enteredAt) {
    if (num == null || !enteredAt) return;
    const { times } = get();
    const secs = (Date.now() - enteredAt) / 1000;
    set({ times: { ...times, [num]: (times[num] ?? 0) + secs },
          enteredAt: Date.now() });
  },

  setScore(num, dim, value) {
    const { scores } = get();
    const cur = { ...(scores[num] ?? {}), [dim]: value };
    set({ scores: { ...scores, [num]: cur } });
    save(get());
  },

  /** Guarda el edificio actual: acumula tiempo, envía la fila a Sheets. */
  async submitCurrent() {
    const s = get();
    s._accumulateTime(s.currentNum, s.enteredAt);
    const { participant, building, scores, times, sent } = get();
    if (!building || !isComplete(scores[building.num])) return false;
    const row = buildRow(participant, building, scores[building.num],
                         times[building.num] ?? 0);
    const ok = await postRow(row);
    set({ sent: { ...sent, [building.num]: ok ? true : sent[building.num] } });
    if (!ok) set((st) => ({ pendingQueue: [...st.pendingQueue, row] }));
    save(get());
    return true;
  },

  /** Reintenta las filas que no llegaron a Sheets. */
  async retryPending() {
    const { pendingQueue, sent } = get();
    const still = [];
    const newSent = { ...sent };
    for (const row of pendingQueue) {
      if (await postRow(row)) newSent[row.buildingNum] = true;
      else still.push(row);
    }
    set({ pendingQueue: still, sent: newSent });
    save(get());
  },
}));

export function isComplete(s) {
  return !!s && DIMENSIONS.every((d) => s[d.id] >= 1 && s[d.id] <= 10);
}
