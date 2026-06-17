// Sidebar (20%): progreso, selector de los 20 edificios, prompt (ES/EN/中文),
// planos de planta con roles y panel de puntuación. Pasos numerados para
// guiar al jugador.

import { useState } from 'react';
import { useStore, isComplete } from '../store.js';
import { BASE, DIMENSIONS } from '../config.js';
import { downloadCsv, csvString, emailResults } from '../lib/results.js';
import FloorPlan from './FloorPlan.jsx';
import ScorePanel from './ScorePanel.jsx';

const TYPE_ES = {
  residential: 'Residencial', castle: 'Castillo', temple: 'Templo',
  shop: 'Tienda', tower: 'Torre', barn: 'Granero',
  monument: 'Monumento', lighthouse: 'Faro',
};
const STYLE_ES = {
  medieval: 'medieval', fantasy: 'fantasía', modern: 'moderno',
  minimalist: 'minimalista', rustic: 'rústico', japanese: 'japonés',
  chinese: 'chino', mediterranean: 'mediterráneo', gothic: 'gótico',
  renaissance: 'renacentista',
};

export default function Sidebar() {
  const index = useStore((s) => s.index);
  const building = useStore((s) => s.building);
  const scores = useStore((s) => s.scores);
  const selectBuilding = useStore((s) => s.selectBuilding);
  const participant = useStore((s) => s.participant);
  const times = useStore((s) => s.times);
  const pending = useStore((s) => s.pendingQueue);
  const retryPending = useStore((s) => s.retryPending);
  const openWelcome = useStore((s) => s.openWelcome);
  const [lang, setLang] = useState('es');
  const [emailState, setEmailState] = useState('idle'); // idle|sending|sent|error

  const done = index.filter((b) => isComplete(scores[b.num])).length;
  const allDone = index.length > 0 && done === index.length;

  const onEmail = async () => {
    setEmailState('sending');
    const csv = csvString(participant, index, scores, times);
    const ok = await emailResults(participant, csv, `${done}/${index.length} edificios puntuados`);
    setEmailState(ok ? 'sent' : 'error');
  };

  return (
    <aside className="h-full overflow-y-auto bg-stone-100 border-l border-stone-300 px-3 py-3 text-stone-800 select-none">
      {/* cabecera + progreso */}
      <div className="flex items-center justify-between mb-1">
        <h1 className="font-black text-base leading-tight">Evaluación de edificios</h1>
        <button onClick={openWelcome} title="Ver instrucciones"
                className="text-stone-400 hover:text-stone-600 text-lg leading-none">ⓘ</button>
      </div>
      <p className="text-[11px] text-stone-500 mb-1">Participante: <b>{participant || '—'}</b></p>
      <div className="w-full h-2 bg-stone-200 rounded-full overflow-hidden mb-1">
        <div className="h-full bg-emerald-500 transition-all"
             style={{ width: `${index.length ? (done / index.length) * 100 : 0}%` }} />
      </div>
      <p className="text-xs text-stone-600 mb-3"><b>{done}/{index.length}</b> edificios puntuados</p>

      {/* selector de edificios */}
      <h3 className="font-bold text-sm text-stone-700 mb-1">Edificios</h3>
      <div className="grid grid-cols-5 gap-1 mb-3">
        {index.map((b) => {
          const sel = building?.num === b.num;
          const ok = isComplete(scores[b.num]);
          return (
            <button
              key={b.num}
              onClick={() => selectBuilding(b.num, BASE)}
              title={`${TYPE_ES[b.type] ?? b.type} · ${STYLE_ES[b.style] ?? b.style}`}
              className={`h-8 rounded text-xs font-bold border transition-colors ${
                sel ? 'bg-sky-600 text-white border-sky-700'
                  : ok ? 'bg-emerald-100 text-emerald-700 border-emerald-300 hover:bg-emerald-200'
                  : 'bg-white text-stone-600 border-stone-300 hover:bg-sky-100'
              }`}
            >{ok && !sel ? '✓' : b.num}</button>
          );
        })}
      </div>

      {building && (
        <>
          <div className="rounded-lg bg-white border border-stone-300 p-2.5 mb-3">
            <p className="text-[11px] uppercase tracking-wide text-stone-400 font-bold mb-0.5">
              Edificio {building.num} / {index.length}
            </p>
            <p className="font-bold text-sm mb-1.5">
              {(TYPE_ES[building.type] ?? building.type)} · {(STYLE_ES[building.style] ?? building.style)}
            </p>
            {/* prompt con pestañas de idioma */}
            <h3 className="font-bold text-stone-700 text-sm mb-1">1 · Lee lo que se pidió generar</h3>
            <div className="flex gap-1 mb-1.5">
              {[['es', 'ES'], ['en', 'EN'], ['zh', '中文']].map(([code, label]) => (
                <button key={code} onClick={() => setLang(code)}
                  className={`px-2 py-0.5 rounded text-[11px] font-semibold border ${
                    lang === code ? 'bg-stone-700 text-white border-stone-700'
                      : 'bg-white text-stone-500 border-stone-300 hover:bg-stone-100'}`}
                >{label}</button>
              ))}
            </div>
            <p className="text-xs leading-relaxed text-stone-700 italic">
              “{building.prompts[lang] || building.prompts.en}”
            </p>
          </div>

          <div className="rounded-lg bg-white border border-stone-300 p-2.5 mb-3">
            <h3 className="font-bold text-stone-700 text-sm mb-1.5">2 · Explora con ayuda del plano</h3>
            <FloorPlan building={building} />
          </div>

          <div className="rounded-lg bg-white border border-stone-300 p-2.5 mb-3">
            <ScorePanel />
          </div>
        </>
      )}

      {/* final: descarga + estado de envío */}
      {allDone && (
        <div className="rounded-lg bg-emerald-50 border border-emerald-300 p-3 mb-3">
          <p className="font-bold text-emerald-800 text-sm mb-1">🎉 ¡Has puntuado los {index.length} edificios!</p>
          <p className="text-xs text-emerald-700">
            Muchísimas gracias. Pulsa <b>Enviar resultados</b> abajo para mandárselos
            al investigador (y/o descárgalos como respaldo).
          </p>
        </div>
      )}

      {/* Resultados: disponibles en cualquier momento (guardados en el navegador) */}
      {done >= 1 && (
        <div className="rounded-lg bg-white border border-stone-300 p-2.5 mb-3">
          <h3 className="font-bold text-stone-700 text-sm mb-0.5">Tus respuestas</h3>
          <p className="text-[11px] text-stone-500 mb-2">
            {done}/{index.length} edificios puntuados · guardados en este navegador
          </p>
          <button
            onClick={onEmail}
            disabled={emailState === 'sending'}
            className={`w-full py-2 rounded-lg font-bold text-sm mb-1.5 transition-colors ${
              emailState === 'sent'
                ? 'bg-emerald-600 text-white'
                : 'bg-sky-600 text-white hover:bg-sky-700'}`}
          >
            {emailState === 'sending' ? 'Enviando…'
              : emailState === 'sent' ? '✓ ¡Resultados enviados!'
              : '✉ Enviar resultados al investigador'}
          </button>
          {emailState === 'error' && (
            <p className="text-[11px] text-red-600 mb-1.5">
              No se pudo enviar. Comprueba tu conexión o descarga el CSV y envíalo a mano.
            </p>
          )}
          <button
            onClick={() => downloadCsv(participant, index, scores, times)}
            className="w-full py-2 rounded-lg bg-stone-200 text-stone-700 font-bold text-sm hover:bg-stone-300"
          >⬇ Descargar CSV (respaldo)</button>
        </div>
      )}
      {pending.length > 0 && (
        <div className="rounded-lg bg-amber-50 border border-amber-300 p-2 mb-3">
          <p className="text-xs text-amber-800 mb-1">
            ⚠ {pending.length} respuesta(s) sin enviar al servidor.
          </p>
          <button onClick={retryPending}
                  className="w-full py-1 rounded bg-amber-500 text-white text-xs font-bold hover:bg-amber-600">
            Reintentar envío
          </button>
        </div>
      )}

      <p className="text-[10px] text-stone-400 leading-snug mt-4">
        Estudio académico (TFG, UPC-FIB). No es un producto oficial de Minecraft;
        no está aprobado por ni asociado con Mojang. Texturas: recursos de
        Minecraft 1.16.5 vía CDN.
      </p>
    </aside>
  );
}
