// Persistencia de resultados:
//  1) autosave inmediato en localStorage (sobrevive recargas),
//  2) envío por edificio completado a Google Sheets vía Apps Script
//     (POST text/plain para evitar el preflight CORS), con cola de reintento,
//  3) exportación final a CSV como respaldo.

import { APPS_SCRIPT_URL, DIMENSIONS, RESULT_EMAIL } from '../config.js';

const LS_KEY = 'test_mc_players_v1';

export function loadSaved() {
  try {
    return JSON.parse(localStorage.getItem(LS_KEY)) ?? {};
  } catch {
    return {};
  }
}

export function save(state) {
  const { participant, scores, sent, times } = state;
  localStorage.setItem(LS_KEY, JSON.stringify({ participant, scores, sent, times }));
}

/** Envía la fila de un edificio a Google Sheets. Devuelve true si llegó. */
export async function postRow(row) {
  if (!APPS_SCRIPT_URL) return false;
  try {
    const res = await fetch(APPS_SCRIPT_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify(row),
    });
    return res.ok;
  } catch {
    return false;
  }
}

export function buildRow(participant, building, scores, seconds) {
  return {
    timestamp: new Date().toISOString(),
    participantId: participant,
    buildingNum: building.num,
    buildingKey: building.key,
    ...Object.fromEntries(DIMENSIONS.map((d) => [d.id, scores[d.id]])),
    secondsExplored: Math.round(seconds),
  };
}

/** Construye el texto CSV con TODAS las respuestas guardadas en el navegador. */
export function csvString(participant, buildings, scores, times) {
  const header = ['participante', 'num', 'key',
    ...DIMENSIONS.map((d) => d.id), 'segundos_explorados'];
  const lines = [header.join(',')];
  for (const b of buildings) {
    const s = scores[b.num];
    if (!s) continue;
    lines.push([
      JSON.stringify(participant), b.num, b.key,
      ...DIMENSIONS.map((d) => s[d.id] ?? ''),
      Math.round(times[b.num] ?? 0),
    ].join(','));
  }
  return lines.join('\n');
}

/** Genera y descarga el CSV con todas las respuestas del participante. */
export function downloadCsv(participant, buildings, scores, times) {
  const blob = new Blob(['﻿' + csvString(participant, buildings, scores, times)],
    { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `respuestas_${participant.replace(/\W+/g, '_')}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/**
 * Envía los resultados por correo al investigador vía FormSubmit (sin backend).
 *
 * Para que lleguen ORDENADOS, se manda como `multipart/form-data` con:
 *   - el CSV adjunto como ARCHIVO real (campo `attachment`, abre directo en Excel),
 *   - campos estructurados (participante, fecha, nº de edificios) + plantilla
 *     `table` para un correo legible,
 *   - el CSV también inline (`csv`) como respaldo si el adjunto se ignorara.
 * Devuelve true si FormSubmit aceptó el envío.
 *
 * Nota: la PRIMERA vez, FormSubmit envía un correo de activación a
 * RESULT_EMAIL que hay que confirmar una sola vez (ver README).
 */
export async function emailResults(participant, csv, summary) {
  try {
    const safe = participant.replace(/\W+/g, '_');
    const fd = new FormData();
    fd.append('_subject', `Resultados HomeCraft — ${participant} (${summary})`);
    fd.append('_template', 'table');
    fd.append('_captcha', 'false');
    fd.append('participante', participant);
    fd.append('edificios_puntuados', summary);
    fd.append('enviado', new Date().toISOString());
    fd.append('csv', csv);
    // CSV adjunto como archivo .csv (con BOM para que Excel respete los acentos)
    const file = new File(['﻿' + csv], `respuestas_${safe}.csv`,
      { type: 'text/csv;charset=utf-8' });
    fd.append('attachment', file);
    // OJO: NO fijar Content-Type — el navegador pone el boundary multipart.
    const res = await fetch(
      'https://formsubmit.co/ajax/' + encodeURIComponent(RESULT_EMAIL),
      { method: 'POST', headers: { Accept: 'application/json' }, body: fd });
    const data = await res.json().catch(() => ({}));
    return res.ok && (data.success === undefined || `${data.success}` === 'true');
  } catch {
    return false;
  }
}
