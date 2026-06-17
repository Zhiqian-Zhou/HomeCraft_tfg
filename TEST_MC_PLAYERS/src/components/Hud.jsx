// HUD sobre el canvas: crosshair, overlay "clic para explorar", strip de
// ayuda, indicador de modo SUPER y modal de bienvenida con instrucciones.

import { useState } from 'react';
import { useStore, playerState } from '../store.js';

// Ejemplo trabajado para guiar al jugador novato: cómo se puntuaría un edificio
// concreto en cada una de las 6 dimensiones (muestra que pueden divergir y que
// hay que usar todo el rango 1–10).
const EXAMPLE = [
  { label: 'Valoración global', score: 5, why: 'bien por fuera, floja por dentro.' },
  { label: 'Solidez y construcción', score: 7, why: 'se aguanta, sin bloques flotando ni agujeros.' },
  { label: 'Interior habitable', score: 3, why: 'salas vacías, sin muebles y a oscuras.' },
  { label: 'Aspecto exterior', score: 8, why: 'fachada limpia y completa, se ve bien.' },
  { label: 'Sensación de buen lugar', score: 4, why: 'se entra, pero no apetece quedarse; sin luz natural.' },
  { label: 'Fidelidad a la descripción', score: 6, why: 'es hormigón blanco y cristal, pero falta el dormitorio de arriba.' },
];

export default function Hud() {
  const locked = useStore((s) => s.locked);
  const mode = useStore((s) => s.mode);
  const toggleMode = useStore((s) => s.toggleMode);
  const showWelcome = useStore((s) => s.showWelcome);
  const loading = useStore((s) => s.loading);

  return (
    <>
      {/* crosshair */}
      {locked && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          <div className="w-1.5 h-1.5 rounded-full bg-white/90 ring-1 ring-black/40" />
        </div>
      )}

      {/* indicador / botón de modo SUPER */}
      <button
        onClick={toggleMode}
        className={`absolute top-3 left-3 z-20 px-3 py-1.5 rounded-lg text-xs font-bold shadow transition-colors ${
          mode === 'fly'
            ? 'bg-fuchsia-600 text-white'
            : 'bg-white/85 text-stone-700 hover:bg-white'
        }`}
        title="Tecla F o doble-espacio"
      >
        {mode === 'fly' ? '🪽 SUPER: volando (F para andar)' : '🚶 Andando (F = modo SUPER)'}
      </button>

      {/* strip de ayuda inferior */}
      {locked && (
        <div className="pointer-events-none absolute bottom-2 inset-x-0 z-10 flex justify-center">
          <p className="bg-black/55 text-white/95 text-xs px-3 py-1.5 rounded-full">
            {mode === 'fly'
              ? 'WASD/flechas mover · ratón mirar · espacio SUBIR · shift BAJAR · F volver a andar · '
              : 'WASD/flechas mover · ratón mirar · espacio saltar · F volar/atravesar · '}
            <b>ESC para soltar el ratón y puntuar →</b>
          </p>
        </div>
      )}

      {/* overlay clic-para-explorar */}
      {!locked && !showWelcome && (
        <div
          onClick={() => playerState.requestLock?.()}
          className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-black/35 cursor-pointer"
        >
          <div className="bg-white/95 rounded-2xl shadow-xl px-8 py-6 text-center max-w-sm pointer-events-none">
            <p className="text-2xl font-black text-stone-800 mb-2">🖱️ Haz clic para explorar</p>
            <div className="text-sm text-stone-600 space-y-1 text-left">
              <p><b>WASD</b> o flechas — moverte</p>
              <p><b>Ratón</b> — mirar alrededor</p>
              <p><b>Espacio</b> — saltar</p>
              <p><b>F</b> — modo SUPER (volar y atravesar bloques)</p>
              <p className="text-stone-500 pl-4">↳ en modo SUPER: <b>Espacio</b> subir · <b>Shift</b> bajar</p>
              <p><b>ESC</b> — soltar el ratón para puntuar en el panel derecho</p>
            </div>
          </div>
          {loading && <p className="mt-4 text-white font-bold">Cargando edificio…</p>}
        </div>
      )}

      {showWelcome && <Welcome />}
    </>
  );
}

function Welcome() {
  const participant = useStore((s) => s.participant);
  const setParticipant = useStore((s) => s.setParticipant);
  const closeWelcome = useStore((s) => s.closeWelcome);
  const [name, setName] = useState(participant);
  const ok = name.trim().length >= 2;

  return (
    <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/60 overflow-y-auto">
      <div className="bg-white rounded-2xl shadow-2xl max-w-xl w-[92%] p-6 my-6">
        <h2 className="text-xl font-black text-stone-800 mb-2">¡Bienvenido/a! 👋</h2>
        <p className="text-sm text-stone-600 mb-3">
          Vas a visitar <b>20 edificios generados automáticamente por una IA</b> a partir
          de una descripción de texto. Tu misión, en cada edificio:
        </p>
        <ol className="text-sm text-stone-700 space-y-1.5 mb-4 list-none">
          <li><b className="text-sky-700">1.</b> Lee en el panel derecho <b>qué se le pidió a la IA</b> (puedes verlo en español, inglés o chino).</li>
          <li><b className="text-sky-700">2.</b> <b>Explora el edificio</b> en primera persona, por dentro y por fuera, como en Minecraft (haz clic en la pantalla para empezar a moverte). El plano de cada planta te dice qué sala es cada cosa.</li>
          <li><b className="text-sky-700">3.</b> Pulsa <b>ESC</b> para recuperar el ratón y <b>puntúa de 1 a 10</b> las preguntas del panel.</li>
          <li><b className="text-sky-700">4.</b> Pulsa <b>Guardar</b> y pasa al siguiente. Tu progreso se guarda solo: puedes cerrar y continuar más tarde.</li>
        </ol>
        <p className="text-xs text-stone-500 mb-3">
          💡 Trucos: con <b>F</b> (o doble-espacio) activas el modo <b>SUPER</b>: vuelas y
          atraviesas paredes, ideal para inspeccionar por dentro (en SUPER,
          <b> Espacio</b> sube y <b>Shift</b> baja). No hay respuestas correctas:
          nos interesa <b>tu opinión como jugador/a</b>.
        </p>

        {/* Guía rápida de puntuación + ejemplo trabajado (para quien entra por 1ª vez) */}
        <div className="rounded-xl border border-sky-200 bg-sky-50/70 p-3 mb-4">
          <p className="text-sm font-bold text-stone-800 mb-1">📊 Cómo puntuar (ejemplo)</p>
          <p className="text-xs text-stone-600 mb-2">
            Cada edificio se puntúa <b>1–10</b> (1 = muy pobre · 10 = excelente).
            Usa <b>todo el rango</b> y recuerda que las 6 preguntas son
            <b> independientes</b>: un edificio puede estar muy bien por fuera y
            muy mal por dentro.
          </p>
          <p className="text-xs text-stone-700 italic mb-2">
            Imagina que el texto pedía <i>«una casa de hormigón blanco y cristal,
            con salón diáfano y un dormitorio arriba»</i>. Al visitarla: por fuera
            está limpia y se reconoce, pero por dentro las salas están vacías y a
            oscuras, y no hay escalera al piso de arriba. La puntuarías así:
          </p>
          <div className="space-y-1">
            {EXAMPLE.map((e) => (
              <div key={e.label} className="flex items-start gap-2 text-xs">
                <span className="inline-flex items-center justify-center w-6 h-5 rounded bg-sky-600 text-white font-bold shrink-0">
                  {e.score}
                </span>
                <span className="text-stone-700"><b>{e.label}:</b> {e.why}</span>
              </div>
            ))}
          </div>
          <p className="text-[11px] text-stone-500 mt-2">
            Explora <b>dentro y fuera</b> antes de puntuar. Si algo del texto no
            está (una planta, un material…), tenlo en cuenta en «Fidelidad».
          </p>
        </div>

        <label className="block text-sm font-bold text-stone-700 mb-1">
          Tu nombre o apodo
        </label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="p. ej. Alex"
          className="w-full border border-stone-300 rounded-lg px-3 py-2 text-sm mb-4 focus:outline-none focus:ring-2 focus:ring-sky-400"
        />
        <button
          disabled={!ok}
          onClick={() => { setParticipant(name.trim()); closeWelcome(); }}
          className={`w-full py-2.5 rounded-lg font-bold ${ok
            ? 'bg-sky-600 text-white hover:bg-sky-700'
            : 'bg-stone-200 text-stone-400 cursor-not-allowed'}`}
        >
          Empezar la visita →
        </button>
      </div>
    </div>
  );
}
