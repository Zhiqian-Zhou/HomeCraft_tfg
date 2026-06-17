// Panel de puntuación: una fila por dimensión × botones 1–10 (sin sliders: más
// rápido y sin sesgo de posición inicial). No se puede guardar hasta responder
// todas las dimensiones.

import { useState } from 'react';
import { useStore, isComplete } from '../store.js';
import { DIMENSIONS, BASE } from '../config.js';

export default function ScorePanel() {
  const building = useStore((s) => s.building);
  const scores = useStore((s) => s.scores);
  const setScore = useStore((s) => s.setScore);
  const submitCurrent = useStore((s) => s.submitCurrent);
  const selectBuilding = useStore((s) => s.selectBuilding);
  const index = useStore((s) => s.index);
  const [showMissing, setShowMissing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedMsg, setSavedMsg] = useState(false);

  if (!building) return null;
  const s = scores[building.num] ?? {};
  const answered = DIMENSIONS.filter((d) => s[d.id] != null).length;
  const complete = isComplete(s);

  const onSave = async () => {
    if (!complete) { setShowMissing(true); return; }
    setSaving(true);
    await submitCurrent();
    setSaving(false);
    setSavedMsg(true);
    setTimeout(() => setSavedMsg(false), 2500);
    // pasa al siguiente edificio sin puntuar
    const next = index.find((b) => b.num !== building.num && !isComplete(useStore.getState().scores[b.num]));
    if (next) selectBuilding(next.num, BASE);
  };

  return (
    <div>
      <h3 className="font-bold text-stone-700 text-sm mb-0.5">3 · Puntúa (1 = muy pobre · 10 = excelente)</h3>
      <p className="text-[11px] text-stone-500 mb-2">{answered}/{DIMENSIONS.length} respondidas</p>
      <div className="space-y-2">
        {DIMENSIONS.map((d) => {
          const missing = showMissing && s[d.id] == null;
          return (
            <div key={d.id} className={`rounded p-1.5 ${missing ? 'bg-red-50 ring-1 ring-red-300' : ''}`}>
              <p className={`text-xs font-semibold mb-0.5 ${missing ? 'text-red-700' : 'text-stone-800'}`}>
                {d.label}
              </p>
              <p className={`text-[11px] mb-1 leading-snug ${missing ? 'text-red-600' : 'text-stone-500'}`}>
                {d.question}
              </p>
              <div className="grid grid-cols-10 gap-0.5">
                {Array.from({ length: 10 }, (_, i) => i + 1).map((v) => (
                  <button
                    key={v}
                    onClick={() => setScore(building.num, d.id, v)}
                    className={`h-6 rounded text-[11px] font-semibold border transition-colors ${
                      s[d.id] === v
                        ? 'bg-sky-600 text-white border-sky-700'
                        : 'bg-white text-stone-600 border-stone-300 hover:bg-sky-100'
                    }`}
                  >{v}</button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <button
        onClick={onSave}
        disabled={saving}
        className={`mt-3 w-full py-2 rounded-lg font-bold text-sm transition-colors ${
          complete
            ? 'bg-emerald-600 text-white hover:bg-emerald-700'
            : 'bg-stone-200 text-stone-400 cursor-not-allowed'
        }`}
      >
        {saving ? 'Guardando…' : savedMsg ? '✓ ¡Guardado!' : complete
          ? 'Guardar y pasar al siguiente →'
          : `Responde las ${DIMENSIONS.length} preguntas (${answered}/${DIMENSIONS.length})`}
      </button>
    </div>
  );
}
