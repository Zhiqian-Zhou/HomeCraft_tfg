// Main entry: load index.json, render sidebar, hook UI controls, drive renderer.

import { BuildingRenderer } from './renderer.js';

const INDEX_URL = './data/index.json';
const PROCESSED_BASE = '../rag/reference_buildings/processed/';
// Experiment builds carry a full relative path in .file; the corpus carries a bare filename.
const buildUrl = (m) => (m && m.file && m.file.includes('/')) ? m.file : PROCESSED_BASE + m.file;

const state = {
  entries: [],          // all building metadata
  filtered: [],         // after filters
  selectedId: null,
  filters: {
    search: '',
    style: new Set(),
    category: new Set(),
    license: new Set(),
    populatedOnly: false,
  },
  floorIsolation: {
    storeys: [],        // cached [{idx, id, y0, y1, n_spaces}] for keyboard nav
    activeIdx: null,    // null = opaque-all
  },
};

let renderer = null;
// Minimap configs (one per floor card) for the live fly-mode camera marker.
let floorMaps = [];
let _lastMarkedFloor = -1;

// ────────────────────────────────────────────────────────────────────────
//  Boot
// ────────────────────────────────────────────────────────────────────────

async function boot() {
  // Init renderer (always)
  const container = document.getElementById('canvas-container');
  renderer = new BuildingRenderer(container);
  window.renderer = renderer;   // debug/automation handle

  // Deep-link mode: ?file=<path> bypasses the index entirely and loads the
  // referenced JSON directly. Used by the pipeline driver to open a freshly
  // generated building (paths typically point at ../scratch/generations/…).
  const params = new URLSearchParams(window.location.search);
  const directFile = params.get('file');
  if (directFile) {
    await bootDirectFile(directFile);
    return;
  }

  // Fetch index
  const res = await fetch(INDEX_URL);
  const data = await res.json();
  state.entries = data.entries;
  document.getElementById('dataset-count').textContent = `${data.count} edificios`;

  // Build filter UIs
  buildFilterUI('style', extractAll(state.entries, (e) => e.style));
  buildFilterUI('category', extractAll(state.entries, (e) => [e.category]));
  buildFilterUI('license', extractAll(state.entries, (e) => [e.license]));

  wireEvents();
  applyFiltersAndRender();
}

/** Valida que un objeto parseado parece un ReferenceBuilding. Lanza Error con
 *  mensaje claro y accionable si no. */
function validateBuildingDoc(doc) {
  if (!doc || typeof doc !== 'object') throw new Error('El JSON no es un objeto.');
  // ¿es un sidecar de evaluación, no un edificio? (error común por el naming)
  if (!doc.voxels && (doc.composite || doc.metric_metadata)) {
    throw new Error('Esto parece un informe de evaluación (.evaluation.json), no un edificio. Sube el JSON del edificio.');
  }
  if (!Array.isArray(doc.voxels) || doc.voxels.length === 0)
    throw new Error('Falta el array `voxels` (o está vacío).');
  if (!doc.block_palette || typeof doc.block_palette !== 'object')
    throw new Error('Falta `block_palette`.');
  const size = doc.bounding_box && doc.bounding_box.size;
  if (!Array.isArray(size) || size.length !== 3)
    throw new Error('Falta `bounding_box.size` (debe ser [W,H,D]).');
}

/** Render compartido por carga-por-URL y carga-por-fichero. */
async function renderDoc(doc, { sourceLabel, jsonHref = null, report = null } = {}) {
  await renderer.loadBuilding(doc);
  const [W, H, D] = doc.bounding_box.size;
  const meta = {
    id: doc.id, title: doc.title || doc.id, file: jsonHref,
    category: doc.tags?.category ?? '—', style: doc.tags?.style ?? [],
    license: doc.license ?? '—', source: doc.source ?? '—',
    size: [W, H, D], volume: W * H * D,
    voxel_count: doc.voxels.length,
    palette_size: Object.keys(doc.block_palette).length,
    furniture_blocks: doc.metadata_quality?.furniture_blocks ?? 0,
    interior_populated: !!doc.metadata_quality?.interior_populated,
  };
  state.selectedId = meta.id;
  if (sourceLabel) document.getElementById('dataset-count').textContent = sourceLabel;
  updateInfoPanel(meta, doc);
  setupLayerSlider(doc);
  updateFloorNavigator(doc);
  // report: objeto ya parseado (upload) o null → updateEvaluationPanel lo busca por URL
  updateEvaluationPanel(jsonHref, report);
  const link = document.getElementById('info-json-link');
  if (link && jsonHref) link.href = jsonHref;
}

async function bootDirectFile(file) {
  document.getElementById('empty-state').classList.add('hidden');
  document.getElementById('loader').classList.remove('hidden');
  try {
    const res = await fetch(file);
    if (!res.ok) throw new Error(`HTTP ${res.status} fetching ${file}`);
    const doc = await res.json();
    validateBuildingDoc(doc);
    await renderDoc(doc, { sourceLabel: `direct: ${file.split('/').pop()}`, jsonHref: file });
  } catch (err) {
    console.error('[viewer] direct-file load failed', err);
    document.getElementById('info-title').textContent = `Error: ${err.message}`;
  } finally {
    document.getElementById('loader').classList.add('hidden');
  }
  wireEvents();
}

/** Carga un edificio desde un File local (botón o arrastrar-y-soltar). */
function loadFromFile(file) {
  const MAX = 30 * 1024 * 1024;     // 30 MB
  if (file.size > MAX) {
    showLoadError(`Archivo demasiado grande (${(file.size / 1048576).toFixed(1)} MB, máx 30).`);
    return;
  }
  const reader = new FileReader();
  document.getElementById('loader').classList.remove('hidden');
  reader.onerror = () => {
    document.getElementById('loader').classList.add('hidden');
    showLoadError('No se pudo leer el archivo.');
  };
  reader.onload = async () => {
    try {
      const text = reader.result;
      if (!text) throw new Error('Archivo vacío.');
      let doc;
      try { doc = JSON.parse(text); }
      catch (e) { throw new Error('JSON inválido: ' + e.message.slice(0, 120)); }
      validateBuildingDoc(doc);
      document.getElementById('empty-state').classList.add('hidden');
      await renderDoc(doc, { sourceLabel: `📂 ${file.name}` });
    } catch (err) {
      console.error('[viewer] upload failed', err);
      showLoadError(err.message);
    } finally {
      document.getElementById('loader').classList.add('hidden');
    }
  };
  reader.readAsText(file);
}

function showLoadError(msg) {
  const es = document.getElementById('empty-state');
  if (es) {
    es.classList.remove('hidden');
    es.innerHTML = `<p style="color:#E66A3C">⚠ ${msg}</p>`
      + '<p class="muted">Arrastra un JSON de edificio o usa «📂 Cargar JSON».</p>';
  }
  const t = document.getElementById('info-title');
  if (t) t.textContent = `Error: ${msg}`;
}

function extractAll(entries, getValues) {
  const map = new Map();
  for (const e of entries) {
    for (const v of getValues(e)) {
      map.set(v, (map.get(v) ?? 0) + 1);
    }
  }
  return [...map.entries()].sort((a, b) => b[1] - a[1]);
}

function buildFilterUI(facet, options) {
  const container = document.getElementById('filter-' + facet);
  container.innerHTML = '';
  for (const [val, count] of options) {
    const id = `f-${facet}-${val}`;
    const label = document.createElement('label');
    label.innerHTML = `<input type="checkbox" id="${id}" data-facet="${facet}" data-value="${val}" />
      ${val} <span class="count-pill">${count}</span>`;
    container.appendChild(label);
    label.querySelector('input').addEventListener('change', (e) => {
      const set = state.filters[facet];
      if (e.target.checked) set.add(val);
      else set.delete(val);
      applyFiltersAndRender();
    });
  }
  document.getElementById('count-' + facet).textContent = options.length;
}

function applyFiltersAndRender() {
  const f = state.filters;
  const q = f.search.trim().toLowerCase();
  state.filtered = state.entries.filter((e) => {
    if (q && !e.title.toLowerCase().includes(q) && !e.id.toLowerCase().includes(q)) return false;
    if (f.style.size > 0 && !e.style.some((s) => f.style.has(s))) return false;
    if (f.category.size > 0 && !f.category.has(e.category)) return false;
    if (f.license.size > 0 && !f.license.has(e.license)) return false;
    if (f.populatedOnly && !e.interior_populated) return false;
    return true;
  });
  document.getElementById('visible-count').textContent = `${state.filtered.length} visibles`;
  renderBuildingList();
}

function renderBuildingList() {
  const ul = document.getElementById('building-list');
  ul.innerHTML = '';
  // Sort by populated desc, then by voxel count desc
  const sorted = [...state.filtered].sort((a, b) => {
    if (a.interior_populated !== b.interior_populated) return b.interior_populated - a.interior_populated;
    return b.voxel_count - a.voxel_count;
  });
  const limit = 250; // virtualization-lite: only render the top 250 of the filter
  for (let i = 0; i < Math.min(sorted.length, limit); i++) {
    const e = sorted[i];
    const div = document.createElement('div');
    div.className = 'building-item' + (e.id === state.selectedId ? ' active' : '');
    div.dataset.id = e.id;
    div.dataset.file = e.file;
    div.innerHTML = `
      <div class="bi-title">${escapeHtml(e.title)}</div>
      <div class="bi-meta">
        <span class="bi-tag">${e.category}</span>
        <span class="bi-tag">${e.style[0] ?? '—'}</span>
        ${e.interior_populated ? '<span class="bi-tag pop">populated</span>' : ''}
        ${e.synthetic ? '<span class="bi-tag syn">synth</span>' : ''}
        <span style="margin-left:auto;color:var(--fg-2);font-size:9.5px">${formatVolume(e.volume)}</span>
      </div>`;
    div.addEventListener('click', () => selectBuilding(e));
    ul.appendChild(div);
  }
  if (sorted.length > limit) {
    const more = document.createElement('div');
    more.className = 'muted';
    more.style.padding = '8px 12px';
    more.textContent = `… y ${sorted.length - limit} más (afina filtros)`;
    ul.appendChild(more);
  }
}

async function selectBuilding(meta) {
  state.selectedId = meta.id;
  document.getElementById('empty-state').classList.add('hidden');
  document.getElementById('loader').classList.remove('hidden');

  // Highlight in list
  document.querySelectorAll('.building-item').forEach((el) => {
    el.classList.toggle('active', el.dataset.id === meta.id);
  });

  try {
    const res = await fetch(buildUrl(meta));
    const doc = await res.json();
    await renderer.loadBuilding(doc);
    updateInfoPanel(meta, doc);
    setupLayerSlider(doc);
    updateFloorNavigator(doc);
    updateEvaluationPanel(buildUrl(meta));
  } catch (err) {
    console.error('[viewer] failed to load building', err);
    document.getElementById('info-title').textContent = 'Error cargando';
  } finally {
    document.getElementById('loader').classList.add('hidden');
  }
}

function updateInfoPanel(meta, doc) {
  $('#info-title').textContent = doc.title || meta.id;
  $('#info-id').textContent = meta.id;
  $('#info-category').textContent = meta.category;
  $('#info-style').textContent = meta.style.join(', ');
  const [W, H, D] = meta.size;
  $('#info-size').textContent = `${W} × ${H} × ${D} (${meta.volume.toLocaleString()} cells)`;
  $('#info-voxels').textContent = meta.voxel_count.toLocaleString();
  $('#info-palette').textContent = meta.palette_size;
  $('#info-furniture').textContent = meta.furniture_blocks.toString();
  $('#info-populated').textContent = meta.interior_populated ? 'sí' : 'no';
  $('#info-license').textContent = meta.license;
  $('#info-source').textContent = meta.source;
  $('#info-json-link').href = buildUrl(meta);

  // Scores + human-language explanation (experiment builds carry these in the index)
  const scoresBox = document.getElementById('info-scores');
  const grid = document.getElementById('info-scores-grid');
  const expl = document.getElementById('info-explanation');
  const fams = meta.families || {};
  const order = ['Physical', 'Interior', 'Exterior', 'Alexander', 'Prompt'];
  if (Object.keys(fams).length || meta.overall != null) {
    const scoreColor = (v) => v == null ? '#888' : `hsl(${Math.round(120 * v)},70%,42%)`;
    const cells = [];
    if (meta.overall != null) {
      cells.push(`<div class="sc-cell sc-overall"><span class="sc-lab">Overall</span>
        <span class="sc-val" style="color:${scoreColor(meta.overall)}">${meta.overall.toFixed(3)}</span></div>`);
    }
    for (const k of order) {
      if (fams[k] == null) continue;
      cells.push(`<div class="sc-cell"><span class="sc-lab">${k}</span>
        <span class="sc-val" style="color:${scoreColor(fams[k])}">${fams[k].toFixed(2)}</span></div>`);
    }
    grid.innerHTML = cells.join('');
    expl.textContent = meta.explanation || '';
    expl.style.display = meta.explanation ? '' : 'none';
    const crit = document.getElementById('info-critique');
    if (crit) {
      crit.textContent = meta.critique || '';
      crit.style.display = meta.critique ? '' : 'none';
    }
    scoresBox.classList.remove('hidden');
  } else {
    scoresBox.classList.add('hidden');
  }

  // Bill of materials
  const counts = new Map();
  for (const [, , , p] of doc.voxels) {
    const block = doc.block_palette[String(p)];
    counts.set(block, (counts.get(block) ?? 0) + 1);
  }
  const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const bomDiv = document.getElementById('bom-list');
  bomDiv.innerHTML = '';
  for (const [block, n] of sorted.slice(0, 50)) {
    const row = document.createElement('div');
    row.className = 'bom-row';
    row.innerHTML = `<span class="bom-name">${escapeHtml(block)}</span><span class="bom-count">${n.toLocaleString()}</span>`;
    bomDiv.appendChild(row);
  }
  if (sorted.length > 50) {
    const more = document.createElement('div');
    more.className = 'muted';
    more.textContent = `… +${sorted.length - 50} blocks`;
    bomDiv.appendChild(more);
  }
}

function setupLayerSlider(doc) {
  const sliderMin = $('#layer-min');
  const sliderMax = $('#layer-max');
  const valueLabel = $('#layer-value');
  const H = doc.bounding_box.size[1];
  const lastY = H - 1;
  for (const s of [sliderMin, sliderMax]) {
    s.min = '0';
    s.max = String(lastY);
    s.disabled = false;
  }
  sliderMin.value = '0';
  sliderMax.value = String(lastY);

  const floors = renderer.detectFloors();
  const floorsTxt = floors.length ? ` · pisos@y=${floors.join(',')}` : '';
  const refresh = (fromUser = false) => {
    let lo = Number(sliderMin.value);
    let hi = Number(sliderMax.value);
    if (lo > hi) [lo, hi] = [hi, lo];
    valueLabel.textContent = `${lo}–${hi} / ${lastY}${floorsTxt}`;
    // Mode-switch: user dragging Y-band sliders deactivates any active
    // storey isolation. We don't call setActiveFloor(null) because that
    // would re-run setActiveStorey and override the slider's matrix path.
    if (fromUser && state.floorIsolation.activeIdx !== null) {
      state.floorIsolation.activeIdx = null;
      document.querySelectorAll('.floor-card').forEach((c) => c.classList.remove('active'));
      const status = document.getElementById('floor-status');
      if (status) status.textContent = 'Mostrando todo (slider Y)';
      renderer.clearActiveStoreyState();
      // Reset aVisibility to 1.0 instantly (no fade) so the matrix-zero
      // band filter is visually consistent with no semantic dimming.
      if (renderer.currentMeshes) {
        for (const mesh of renderer.currentMeshes) {
          const vis = mesh.userData.visibility;
          if (vis) {
            vis.current.fill(1.0);
            vis.target.fill(1.0);
            vis.start.fill(1.0);
            mesh.geometry.attributes.aVisibility.needsUpdate = true;
          }
        }
      }
      if (window.location.hash.startsWith('#floor=')) {
        history.replaceState(null, '', window.location.pathname + window.location.search);
      }
    }
    renderer.setLayerBand(lo, hi);
  };
  sliderMin.oninput = () => refresh(true);
  sliderMax.oninput = () => refresh(true);
  refresh(false);
}

// ────────────────────────────────────────────────────────────────────────
//  Event wiring
// ────────────────────────────────────────────────────────────────────────

function wireEvents() {
  // Search
  $('#search').addEventListener('input', (e) => {
    state.filters.search = e.target.value;
    applyFiltersAndRender();
  });
  // Populated checkbox
  $('#filter-populated').addEventListener('change', (e) => {
    state.filters.populatedOnly = e.target.checked;
    applyFiltersAndRender();
  });
  // Clear filters
  $('#btn-clear-filters').addEventListener('click', () => {
    state.filters.style.clear();
    state.filters.category.clear();
    state.filters.license.clear();
    state.filters.populatedOnly = false;
    state.filters.search = '';
    document.querySelectorAll('.filter-options input[type=checkbox]').forEach((cb) => (cb.checked = false));
    $('#search').value = '';
    applyFiltersAndRender();
  });
  // Toolbar
  $('#btn-mode-fps').addEventListener('click', () => toggleFps());
  $('#btn-reset-view').addEventListener('click', () => renderer && renderer.frameCamera());
  $('#btn-screenshot').addEventListener('click', () => {
    if (!renderer) return;
    const url = renderer.screenshot();
    const a = document.createElement('a');
    a.href = url;
    a.download = (state.selectedId || 'building') + '.png';
    a.click();
  });
  $('#btn-fullscreen').addEventListener('click', () => {
    document.documentElement.requestFullscreen?.();
  });

  // ── Cargar / soltar JSON ──────────────────────────────────────────────
  if (!wireEvents._uploadWired) {
    wireEvents._uploadWired = true;
    const fileInput = $('#file-input');
    $('#btn-upload')?.addEventListener('click', () => fileInput?.click());
    fileInput?.addEventListener('change', (e) => {
      const f = e.target.files && e.target.files[0];
      if (f) loadFromFile(f);
      e.target.value = '';   // permite recargar el mismo fichero
    });
    // arrastrar-y-soltar en toda la ventana
    const overlay = $('#drop-overlay');
    let dragDepth = 0;
    window.addEventListener('dragenter', (e) => {
      if (![...(e.dataTransfer?.types || [])].includes('Files')) return;
      e.preventDefault(); dragDepth++; overlay?.classList.remove('hidden');
    });
    window.addEventListener('dragover', (e) => {
      if ([...(e.dataTransfer?.types || [])].includes('Files')) e.preventDefault();
    });
    window.addEventListener('dragleave', (e) => {
      e.preventDefault(); if (--dragDepth <= 0) { dragDepth = 0; overlay?.classList.add('hidden'); }
    });
    window.addEventListener('drop', (e) => {
      e.preventDefault(); dragDepth = 0; overlay?.classList.add('hidden');
      const f = e.dataTransfer?.files && e.dataTransfer.files[0];
      if (f) loadFromFile(f);
    });
    // ── Ayuda / atajos ──────────────────────────────────────────────────
    const help = $('#help-modal');
    const toggleHelp = (show) => help?.classList.toggle('hidden', show === undefined ? undefined : !show);
    $('#btn-help')?.addEventListener('click', () => help?.classList.toggle('hidden'));
    $('#help-close')?.addEventListener('click', () => help?.classList.add('hidden'));
    help?.addEventListener('click', (e) => { if (e.target === help) help.classList.add('hidden'); });
  }

  // Toggles
  $('#toggle-grid').addEventListener('change', (e) => renderer.setGridVisible(e.target.checked));
  $('#toggle-axes').addEventListener('change', (e) => renderer.setAxesVisible(e.target.checked));
  $('#toggle-stairs').addEventListener('change', (e) => renderer.setStairHighlight(e.target.checked));
  startCameraMarkerLoop();   // live "you are here" marker on the minimap in fly mode
  $('#toggle-ao').addEventListener('change', (e) => {
    // AO toggle is a visual hint; for our simple renderer it doesn't change much.
    // Could be wired to a custom shader pass later.
  });

  // Block hover inspector
  const canvas = document.querySelector('#canvas-container canvas');
  // canvas may not exist until renderer init; query lazily
  document.getElementById('canvas-container').addEventListener('mousemove', (e) => {
    if (!renderer || !state.selectedId) return;
    const hit = renderer.pick(e.clientX, e.clientY);
    const badge = $('#hover-badge');
    const blockInfo = $('#block-info');
    if (hit) {
      badge.textContent = `${hit.blockIdRaw} @ (${hit.x}, ${hit.y}, ${hit.z})`;
      badge.style.left = (e.clientX + 14) + 'px';
      badge.style.top  = (e.clientY + 14) + 'px';
      badge.classList.remove('hidden');
      blockInfo.innerHTML = `
        <div class="field"><span class="field-key">ID</span><span class="field-val">${escapeHtml(hit.blockIdRaw)}</span></div>
        <div class="field"><span class="field-key">Bare</span><span class="field-val">${escapeHtml(hit.name)}</span></div>
        <div class="field"><span class="field-key">Coord</span><span class="field-val">(${hit.x}, ${hit.y}, ${hit.z})</span></div>
        ${Object.entries(hit.props).map(([k, v]) =>
          `<div class="field"><span class="field-key">${k}</span><span class="field-val">${v}</span></div>`
        ).join('')}
      `;
    } else {
      badge.classList.add('hidden');
    }
  });

  // Keyboard shortcuts
  window.addEventListener('keydown', (e) => {
    if (e.target.matches('input, textarea, [contenteditable]')) return;
    // '?' (Shift+/) abre/cierra la ayuda de atajos — disponible siempre.
    if (e.key === '?') { document.getElementById('help-modal')?.classList.toggle('hidden'); return; }
    if (e.key === 'Escape') { document.getElementById('help-modal')?.classList.add('hidden'); }
    if (renderer && renderer.mode === 'fps') return;  // let FPS controls own keys
    const k = e.key;
    // Digit 1-9 → activate that storey (1=ground, 9=8th floor)
    if (/^[1-9]$/.test(k)) {
      const idx = parseInt(k, 10) - 1;
      if (idx < state.floorIsolation.storeys.length) setActiveFloor(idx);
      return;
    }
    switch (k) {
      case '0':
        setActiveFloor(null);
        resetLayerBandSliders();
        break;
      case '[':
        cycleFloor(-1);
        break;
      case ']':
        cycleFloor(+1);
        break;
      default:
        switch (k.toLowerCase()) {
          case 'r': renderer && renderer.frameCamera(); break;
          case 'g': $('#toggle-grid').click(); break;
          case 's': $('#btn-screenshot').click(); break;
          case 'f': toggleFps(); break;
        }
    }
  });

  // Bind exit-fps callback so the UI updates when ESC is pressed
  if (renderer) {
    renderer.fpsControls.onExit(() => setFpsUi(false));
  }
}

function toggleFps() {
  if (!renderer || !state.selectedId) return;
  if (renderer.mode === 'fps') {
    renderer.setMode('orbit');
    setFpsUi(false);
  } else {
    renderer.setMode('fps');
    setFpsUi(true);
  }
}

function setFpsUi(on) {
  $('#btn-mode-fps').classList.toggle('active', on);
  $('#crosshair').classList.toggle('hidden', !on);
  $('#fps-overlay').classList.toggle('hidden', !on);
}

// ────────────────────────────────────────────────────────────────────────
//  Helpers
// ────────────────────────────────────────────────────────────────────────

const $ = (sel) => document.querySelector(sel);

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

function formatVolume(v) {
  if (v < 1000) return `${v}`;
  if (v < 1_000_000) return `${(v / 1000).toFixed(1)}k`;
  return `${(v / 1_000_000).toFixed(1)}M`;
}

// ────────────────────────────────────────────────────────────────────────
//  Floor navigator — only visible for generated buildings with bot_decomposition.
//  Lets the user filter by floor and inspect rooms via a top-down minimap.
// ────────────────────────────────────────────────────────────────────────

const ROOM_COLORS = {
  kitchen:        '#d97706',  // amber
  bedroom:        '#2563eb',  // blue
  bathroom:       '#0891b2',  // cyan
  'living-room':  '#16a34a',  // green
  living_room:    '#16a34a',
  'dining-room':  '#eab308',  // yellow
  dining_room:    '#eab308',
  library:        '#7c3aed',  // violet
  study:          '#9333ea',  // purple
  hallway:        '#6b7280',  // gray
  'entry-hall':   '#dc2626',  // red
  entry_hall:     '#dc2626',
  basement:       '#44403c',  // stone
  attic:          '#a16207',  // dark amber
  courtyard:      '#84cc16',  // lime
  courtyard_indoor: '#84cc16',
  chapel:         '#f59e0b',  // gold
  'throne-room':  '#b45309',
  throne_room:    '#b45309',
  'great-hall':   '#c2410c',
  great_hall:     '#c2410c',
  storage:        '#525252',
  pantry:         '#525252',
  music_room:     '#ec4899',
  nursery:        '#fb7185',
  other:          '#94a3b8',
  exterior:       '#65a30d',
};

function colorForRole(role) {
  if (!role) return '#94a3b8';
  return ROOM_COLORS[role] ?? ROOM_COLORS[role.replace(/_/g, '-')] ?? ROOM_COLORS[role.replace(/-/g, '_')] ?? '#94a3b8';
}

/** Single chokepoint for floor isolation. */
function setActiveFloor(idx) {
  // Clamp idx to valid range or null
  const n = state.floorIsolation.storeys.length;
  if (idx !== null && (idx < 0 || idx >= n)) return;
  state.floorIsolation.activeIdx = idx;
  // Update DOM highlight
  document.querySelectorAll('.floor-card').forEach((c, i) => {
    c.classList.toggle('active', i === idx);
  });
  // Update status text
  const status = document.getElementById('floor-status');
  if (status) {
    if (idx === null) {
      status.textContent = 'Mostrando todo';
    } else {
      const meta = state.floorIsolation.storeys[idx];
      status.textContent = `Planta ${idx + 1}/${n} (${meta.id}) aislada`;
    }
  }
  // Update URL hash
  if (idx === null) {
    if (window.location.hash.startsWith('#floor=')) {
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  } else {
    history.replaceState(null, '', `#floor=${idx}`);
  }
  // Drive the renderer
  if (renderer) {
    renderer.setActiveStorey(idx, { dimBelow: true, dimOpacity: 0.30, fadeMs: 300 });
    // Encuadre automático: en picado sobre la planta aislada (se ve qué hay);
    // al "mostrar todo" (idx null) reencuadra el edificio completo.
    if (idx === null) renderer.frameCamera();
    else renderer.frameStorey(idx);
  }
}

/** Keyboard cycle: ±1 storey, clamped at [0, N-1]. */
function cycleFloor(delta) {
  const n = state.floorIsolation.storeys.length;
  if (n === 0) return;
  const cur = state.floorIsolation.activeIdx;
  let next;
  if (cur === null) {
    next = delta > 0 ? 0 : n - 1;
  } else {
    next = Math.max(0, Math.min(n - 1, cur + delta));
  }
  setActiveFloor(next);
}

/** Reset layer-band sliders to full range (used by '0' key). */
function resetLayerBandSliders() {
  const sliderMin = $('#layer-min');
  const sliderMax = $('#layer-max');
  if (!sliderMin || !sliderMax) return;
  sliderMin.value = '0';
  sliderMax.value = sliderMax.max;
  sliderMin.dispatchEvent(new Event('input'));
}

function updateFloorNavigator(doc) {
  const wrap = document.getElementById('floor-navigator');
  const list = document.getElementById('floor-list');
  const bot  = doc.bot_decomposition;

  if (!bot || !bot.building || !Array.isArray(bot.building.storeys) || !bot.building.storeys.length) {
    wrap.classList.add('hidden');
    list.innerHTML = '';
    state.floorIsolation.storeys = [];
    state.floorIsolation.activeIdx = null;
    return;
  }
  wrap.classList.remove('hidden');
  wrap.open = true;
  list.innerHTML = '';
  floorMaps = [];           // reset live-marker registry for this building
  _lastMarkedFloor = -1;

  // Compute global building extents on X-Z to scale the minimaps
  const [, , D] = doc.bounding_box.size;
  const W = doc.bounding_box.size[0];

  // Connectors (doors + staircases) for the floor plan, if present.
  const conn = doc.connectors || {};
  const allDoors = Array.isArray(conn.doors) ? conn.doors : [];
  const allStairs = Array.isArray(conn.staircases) ? conn.staircases : [];

  // Cache storey metadata for keyboard nav + setActiveFloor
  state.floorIsolation.storeys = bot.building.storeys.map((st, i) => {
    const spaces = Array.isArray(st.spaces) ? st.spaces : [];
    let y0, y1;
    if (Array.isArray(st.aabb) && st.aabb.length === 6) {
      y0 = st.aabb[1]; y1 = st.aabb[4];
    } else if (spaces.length) {
      y0 = Math.min(...spaces.map((s) => s.aabb[1]));
      y1 = Math.max(...spaces.map((s) => s.aabb[4]));
    } else {
      y0 = 0; y1 = doc.bounding_box.size[1];
    }
    return { idx: i, id: st.id ?? `floor-${i}`, y0, y1, n_spaces: spaces.length };
  });
  state.floorIsolation.activeIdx = null;

  // "Show all" clears semantic isolation (sliders unchanged).
  document.getElementById('floor-show-all').onclick = () => setActiveFloor(null);

  for (let storeyIdx = 0; storeyIdx < bot.building.storeys.length; storeyIdx++) {
    const storey = bot.building.storeys[storeyIdx];
    const spaces = Array.isArray(storey.spaces) ? storey.spaces : [];

    // Storey AABB: from storey.aabb if present, else union of spaces
    let aabb = storey.aabb;
    if (!aabb && spaces.length) {
      aabb = [
        Math.min(...spaces.map((s) => s.aabb[0])),
        Math.min(...spaces.map((s) => s.aabb[1])),
        Math.min(...spaces.map((s) => s.aabb[2])),
        Math.max(...spaces.map((s) => s.aabb[3])),
        Math.max(...spaces.map((s) => s.aabb[4])),
        Math.max(...spaces.map((s) => s.aabb[5])),
      ];
    }
    const y0 = aabb ? aabb[1] : 0;
    const y1 = aabb ? aabb[4] : (doc.bounding_box.size[1] - 1);

    const card = document.createElement('div');
    card.className = 'floor-card';
    card.innerHTML = `
      <button class="floor-btn" data-y0="${y0}" data-y1="${y1 - 1}">
        <span class="floor-name">📐 ${escapeHtml(storey.id ?? 'floor')}</span>
        <span class="floor-y">y=${y0}..${y1 - 1}</span>
        <span class="floor-rooms">${spaces.length} habitaciones</span>
        <span class="floor-active-pill" aria-hidden="true">aislada</span>
      </button>
      <canvas class="floor-map" width="220" height="160" data-w="${W}" data-d="${D}"></canvas>
      <ul class="room-list"></ul>
    `;
    list.appendChild(card);

    // Wire floor button → semantic isolation (per-voxel storey filter).
    const btn = card.querySelector('.floor-btn');
    btn.onclick = () => setActiveFloor(storeyIdx);

    // Doors whose Y sits on this storey; stairs whose span overlaps it.
    const doorsHere = allDoors.filter((dn) => {
      const at = dn.at || (dn.validated || {}).at;
      return Array.isArray(at) && at[1] >= y0 && at[1] < y1;
    });
    const stairsHere = allStairs.filter((s) => {
      const a = s.aabb || (s.validated || {}).aabb;
      return Array.isArray(a) && a.length === 6 && a[1] < y1 && a[4] > y0;
    });

    // Draw the minimap (with doors + stairs)
    const canvas = card.querySelector('.floor-map');
    drawFloorMap(canvas, W, D, spaces, doorsHere, stairsHere);
    // Register for the live fly-mode camera marker (redrawn each frame).
    floorMaps.push({ canvas, W, D, spaces, doors: doorsHere, stairs: stairsHere,
                     y0, y1, name: storey.id ?? `Planta ${storeyIdx}`, idx: storeyIdx });

    // Render room list
    const ul = card.querySelector('.room-list');
    for (const sp of spaces) {
      const aw = sp.aabb[3] - sp.aabb[0];
      const ah = sp.aabb[4] - sp.aabb[1];
      const ad = sp.aabb[5] - sp.aabb[2];
      const li = document.createElement('li');
      li.className = 'room-item';
      li.innerHTML = `
        <span class="room-swatch" style="background:${colorForRole(sp.function)}"></span>
        <span class="room-id">${escapeHtml(sp.id)}</span>
        <span class="room-role">${escapeHtml(sp.function ?? '—')}</span>
        <span class="room-dims">${aw}×${ah}×${ad}</span>
      `;
      ul.appendChild(li);
    }
  }

  // Restore active floor from URL fragment after navigator is built.
  const m = window.location.hash.match(/^#floor=(\d+)$/);
  if (m) {
    const idx = parseInt(m[1], 10);
    if (idx >= 0 && idx < state.floorIsolation.storeys.length) {
      setActiveFloor(idx);
    }
  }
}

function drawFloorMap(canvas, W, D, spaces, doors = [], stairs = [], cam = null) {
  const ctx = canvas.getContext('2d');
  const cw = canvas.width, ch = canvas.height;
  ctx.clearRect(0, 0, cw, ch);
  // Background
  ctx.fillStyle = '#1a1a1d';
  ctx.fillRect(0, 0, cw, ch);

  // Fit the building footprint into the canvas with padding
  const PAD = 12;
  const sx = (cw - 2 * PAD) / Math.max(W, 1);
  const sz = (ch - 2 * PAD) / Math.max(D, 1);
  const s = Math.min(sx, sz);
  const offX = (cw - W * s) / 2;
  const offY = (ch - D * s) / 2;
  const px = (x) => offX + x * s;   // world X → canvas
  const pz = (z) => offY + z * s;   // world Z → canvas

  // Building outline
  ctx.strokeStyle = '#3a3a3d';
  ctx.lineWidth = 1;
  ctx.strokeRect(offX, offY, W * s, D * s);

  // Each room
  ctx.font = '10px system-ui';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const sp of spaces) {
    const x0 = sp.aabb[0], z0 = sp.aabb[2];
    const w  = sp.aabb[3] - sp.aabb[0];
    const d  = sp.aabb[5] - sp.aabb[2];
    const rx = offX + x0 * s;
    const ry = offY + z0 * s;
    const rw = w * s, rh = d * s;
    ctx.fillStyle = colorForRole(sp.function) + 'cc';
    ctx.fillRect(rx, ry, rw, rh);
    ctx.strokeStyle = '#fff8';
    ctx.strokeRect(rx, ry, rw, rh);
    // Label = first letter of role (or '?' if missing)
    const label = (sp.function || '?').replace(/[-_]/g, ' ').slice(0, 3);
    ctx.fillStyle = '#fff';
    ctx.fillText(label, rx + rw / 2, ry + rh / 2);
  }

  // ── Stairs: a hatched square + ⇅ at the shaft footprint (how you change floor)
  for (const st of stairs) {
    const a = st.aabb || (st.validated || {}).aabb;
    if (!Array.isArray(a) || a.length !== 6) continue;
    const rx = px(a[0]), ry = pz(a[2]);
    const rw = (a[3] - a[0]) * s, rh = (a[5] - a[2]) * s;
    ctx.fillStyle = '#f9731680';      // orange, semi
    ctx.fillRect(rx, ry, rw, rh);
    ctx.strokeStyle = '#fb923c';
    ctx.lineWidth = 1.5;
    ctx.strokeRect(rx, ry, rw, rh);
    ctx.fillStyle = '#fff';
    ctx.font = 'bold 11px system-ui';
    ctx.fillText('⇅', rx + rw / 2, ry + rh / 2);
  }

  // ── Doors: a bright dot where you pass between two rooms (or to outside) ──
  for (const dn of doors) {
    const at = dn.at || (dn.validated || {}).at;
    if (!Array.isArray(at) || at.length !== 3) continue;
    const cx = px(at[0] + 0.5), cy = pz(at[2] + 0.5);
    const ext = (dn.between || []).includes('outside');
    ctx.beginPath();
    ctx.arc(cx, cy, 3, 0, Math.PI * 2);
    ctx.fillStyle = ext ? '#22d3ee' : '#fde047';  // cyan = entrance, yellow = interior
    ctx.fill();
    ctx.strokeStyle = '#000a';
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // Legend
  ctx.textAlign = 'left';
  ctx.font = '8px system-ui';
  ctx.fillStyle = '#fde047'; ctx.fillText('● puerta', 4, 10);
  ctx.fillStyle = '#22d3ee'; ctx.fillText('● entrada', 48, 10);
  ctx.fillStyle = '#fb923c'; ctx.fillText('⇅ escalera', 100, 10);

  // Compass
  ctx.fillStyle = '#888';
  ctx.font = '9px system-ui';
  ctx.textAlign = 'left';
  ctx.fillText('+X →', 4, ch - 4);
  ctx.textAlign = 'right';
  ctx.save();
  ctx.translate(cw - 4, 4);
  ctx.rotate(Math.PI / 2);
  ctx.fillText('+Z →', 0, 0);
  ctx.restore();

  // ── "Estás aquí": marcador de cámara en fly mode (verde lima) ──
  if (cam) {
    const mx = px(cam.vx), my = pz(cam.vz);
    // línea de dirección de mirada (proyección X-Z)
    const len = Math.hypot(cam.dx, cam.dz) || 1;
    const ex = mx + (cam.dx / len) * 14, ey = my + (cam.dz / len) * 14;
    ctx.strokeStyle = '#a3e635'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(mx, my); ctx.lineTo(ex, ey); ctx.stroke();
    ctx.beginPath(); ctx.arc(mx, my, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = '#a3e635'; ctx.fill();
    ctx.strokeStyle = '#000'; ctx.lineWidth = 1.2; ctx.stroke();
    ctx.fillStyle = '#a3e635'; ctx.font = 'bold 8px system-ui'; ctx.textAlign = 'left';
    ctx.fillText('estás aquí', 4, 20);
  }
}

// Live loop: while in fly mode, draw a "you are here" marker on the minimap of
// the floor the camera is currently on (and clear it from the others).
function startCameraMarkerLoop() {
  const hud = () => document.getElementById('fly-hud');
  const hudCanvas = () => document.getElementById('fly-minimap');
  const hudLabel = () => document.getElementById('fly-floor-label');
  function tick() {
    requestAnimationFrame(tick);
    const inFly = renderer && renderer.mode === 'fps' && floorMaps.length;
    if (!inFly) {
      if (hud()) hud().classList.add('hidden');
      if (_lastMarkedFloor >= 0 && floorMaps[_lastMarkedFloor]) {
        const f = floorMaps[_lastMarkedFloor];
        drawFloorMap(f.canvas, f.W, f.D, f.spaces, f.doors, f.stairs, null);
        floorMaps.forEach((fm) => fm.canvas.classList.remove('cam-active'));
        _lastMarkedFloor = -1;
      }
      return;
    }
    const pose = renderer.getCameraPose();
    // ¿en qué planta está la cámara (por su Y)?
    let idx = floorMaps.findIndex((f) => pose.vy >= f.y0 && pose.vy < f.y1);
    if (idx < 0) idx = pose.vy < floorMaps[0].y0 ? 0 : floorMaps.length - 1;
    const f = floorMaps[idx];
    // sidebar minimap: marcador en la planta activa, limpiar la anterior
    if (_lastMarkedFloor >= 0 && _lastMarkedFloor !== idx && floorMaps[_lastMarkedFloor]) {
      const p = floorMaps[_lastMarkedFloor];
      drawFloorMap(p.canvas, p.W, p.D, p.spaces, p.doors, p.stairs, null);
    }
    drawFloorMap(f.canvas, f.W, f.D, f.spaces, f.doors, f.stairs, pose);
    floorMaps.forEach((fm, i) => fm.canvas.classList.toggle('cam-active', i === idx));
    _lastMarkedFloor = idx;
    // HUD prominente sobre el canvas 3D
    if (hudCanvas()) {
      drawFloorMap(hudCanvas(), f.W, f.D, f.spaces, f.doors, f.stairs, pose);
      // sala bajo la cámara (para la etiqueta)
      const room = (f.spaces || []).find((s) => {
        const a = s.aabb; return a && pose.vx >= a[0] && pose.vx < a[3]
          && pose.vz >= a[2] && pose.vz < a[5];
      });
      hudLabel().textContent = `📍 ${f.name}` + (room ? ` · ${room.function || ''}` : '');
      hud().classList.remove('hidden');
    }
  }
  tick();
}

// ────────────────────────────────────────────────────────────────────────
//  Evaluation panel — fetches the sidecar evaluation_report.json
//  (written by tools/evaluate_building.py --out or by the pipeline's
//  Stage 6 evaluator) and renders it as colored metric bars + critique.
// ────────────────────────────────────────────────────────────────────────

const METRIC_LABEL_ES = {
  structural_integrity:    'Integridad estructural',
  voxel_connectivity:      'Conectividad / accesibilidad',
  vertical_clearance:      'Altura libre',
  door_functionality:      'Funcionalidad de puertas',
  light_coverage:          'Cobertura de iluminación',
  block_legitimacy:        'Legitimidad de bloques 1.16.5',
  material_consistency:    'Coherencia de materiales',
  volume_density:          'Densidad volumétrica',
  light_on_two_sides:      'Luz por dos lados (APL 159)',
  intimacy_gradient:       'Gradiente de intimidad (APL 127)',
  common_areas_at_heart:   'Áreas comunes al centro (APL 129)',
  sheltering_roof:         'Tejado protector (APL 117)',
  building_edge:           'Borde habitable (APL 160)',
  window_place:            'Ventana con estar (APL 180)',
  entrance_transition:     'Transición de entrada (APL 112)',
  main_entrance:           'Entrada principal (APL 110)',
  farmhouse_kitchen:       'Cocina-corazón (APL 139)',
  roof_layout:             'Articulación del techo (APL 209)',
  envelope_integrity:      'Integridad de envolvente',
  room_furnishing:         'Amueblado por sala',
  space_utilization:       'Aprovechamiento del espacio',
  room_size:               'Tamaño de sala',
  room_count:              'Número de salas (prompt)',
  materials:               'Material/color (prompt)',
  floors:                  'Número de plantas (prompt)',
  furniture:               'Mobiliario pedido (prompt)',
  generation_success:      'Éxito de generación (coherencia)',
  prompt_adherence:        'Adherencia al prompt (salas)',
  prompt_material_adherence: 'Adherencia al prompt (material/color)',
  facade_articulation:     'Articulación de fachada',
  fine_detail:             'Detalle fino',
  decoration_density:      'Densidad de decoración',
  silhouette_complexity:   'Complejidad de silueta',
  material_richness:       'Riqueza de materiales',
};

function scoreColor(s) {
  // Escala COLORBLIND-SAFE (teal ↔ naranja, distinguible en deuteranopia/
  // protanopia, a diferencia del rojo/verde). El número siempre se muestra
  // junto al color (codificación redundante, WCAG 1.4.1).
  if (s == null) return '#8a9099';   // gris neutro = n/a
  if (s >= 0.8) return '#2BA88A';    // teal-verde = bien
  if (s >= 0.5) return '#E6B800';    // ámbar = medio
  return '#E0653C';                   // naranja-bermellón = mal (no rojo puro)
}

function reportPathFor(buildingPath) {
  // Experiment builds: .../<name>/cand/<name>.json → .../<name>/evaluation_report.json
  const m = buildingPath.match(/^(.*)\/cand\/[^/]+\.json$/i);
  if (m) return m[1] + '/evaluation_report.json';
  // Curation/corpus: .../foo.json → .../foo.evaluation.json
  return buildingPath.replace(/\.json$/i, '.evaluation.json');
}

async function updateEvaluationPanel(buildingPath, reportObj = null) {
  const panel  = document.getElementById('evaluation-panel');
  const content = document.getElementById('evaluation-content');
  content.innerHTML = '';
  panel.classList.add('hidden');

  // report ya parseado (carga por fichero) o buscar el sidecar por URL.
  let report = reportObj;
  if (!report) {
    if (!buildingPath) return;          // upload sin evaluación → ocultar panel
    try {
      const res = await fetch(reportPathFor(buildingPath));
      if (!res.ok) return;  // no sidecar — hide panel silently
      report = await res.json();
    } catch (err) {
      return;
    }
  }
  panel.classList.remove('hidden');

  const meta = report.metric_metadata || {};

  // Composite scores at top (físico / Alexander / apariencia / overall)
  const comp = report.composite || {};
  const compDiv = document.createElement('div');
  compDiv.className = 'eval-composite';
  compDiv.innerHTML = `
    <div class="eval-score-cell"><span class="eval-label">Físico</span>
      <span class="eval-score" style="color:${scoreColor(comp.physical_total)}">${fmtScore(comp.physical_total)}</span></div>
    <div class="eval-score-cell"><span class="eval-label">Alexander</span>
      <span class="eval-score" style="color:${scoreColor(comp.alexander_total)}">${fmtScore(comp.alexander_total)}</span></div>
    <div class="eval-score-cell"><span class="eval-label">Interior</span>
      <span class="eval-score" style="color:${scoreColor(comp.interior_total)}">${fmtScore(comp.interior_total)}</span></div>
    <div class="eval-score-cell"><span class="eval-label">Exterior</span>
      <span class="eval-score" style="color:${scoreColor(comp.exterior_total)}">${fmtScore(comp.exterior_total)}</span></div>
    <div class="eval-score-cell" title="Fidelidad al prompt (eje aparte de la calidad)"><span class="eval-label">Prompt</span>
      <span class="eval-score" style="color:${scoreColor(comp.prompt_adherence_total)}">${fmtScore(comp.prompt_adherence_total)}</span></div>
    <div class="eval-score-cell eval-overall"><span class="eval-label">Overall</span>
      <span class="eval-score" style="color:${scoreColor(comp.overall)}">${fmtScore(comp.overall)}</span></div>
  `;
  content.appendChild(compDiv);

  // Coste de generación (tokens + tiempo + modelo) → comparación de LLMs
  const gen = report.generation;
  if (gen) {
    const g = document.createElement('div');
    g.className = 'eval-gencost';
    g.innerHTML = `
      <h4 class="eval-cat-title">⚙️ Coste de generación (comparación de LLMs)</h4>
      <div class="eval-genrow">
        <span title="Modelo LLM usado">🤖 ${escapeHtml(gen.model || '—')}</span>
        <span title="Tokens totales (prompt + completion)">🔢 ${(gen.total_tokens ?? 0).toLocaleString()} tok
          <small>(${(gen.prompt_tokens ?? 0).toLocaleString()}p + ${(gen.completion_tokens ?? 0).toLocaleString()}c)</small></span>
        <span title="Nº de llamadas al LLM">📞 ${gen.llm_calls ?? 0}</span>
        <span title="Tiempo total de pared">⏱️ ${gen.wall_time_s ?? '—'}s</span>
        <span title="Tiempo esperando al LLM">⏳ ${gen.llm_wait_s ?? '—'}s LLM</span>
      </div>`;
    content.appendChild(g);
  }

  // Resumen por ámbito (interior / exterior / prompt / estructural)
  const ss = report.scope_summary;
  if (ss) {
    const labels = {structural: 'Estructural', interior: 'Interior',
                    exterior: 'Exterior', prompt: 'Prompt'};
    const cells = ['structural', 'interior', 'exterior', 'prompt']
      .filter((k) => ss[k] && ss[k].mean != null)
      .map((k) => `<div class="eval-score-cell" title="${ss[k].n_metrics} métricas">
        <span class="eval-label">${labels[k]}</span>
        <span class="eval-score" style="color:${scoreColor(ss[k].mean)}">${fmtScore(ss[k].mean)}</span></div>`)
      .join('');
    if (cells) {
      const d = document.createElement('div');
      d.innerHTML = `<h4 class="eval-cat-title">Estado por ámbito</h4>
        <div class="eval-composite">${cells}</div>`;
      content.appendChild(d);
    }
  }

  // Critique
  if (report.critique) {
    const c = document.createElement('div');
    c.className = 'eval-critique';
    c.textContent = report.critique;
    content.appendChild(c);
  }

  // Metric bars by category (físico / Alexander / apariencia)
  const CAT_TITLE = {
    physical: '🧱 Métricas físicas (Minecraft 1.16.5)',
    interior: '🏠 Métricas de interior',
    exterior: '🧭 Métricas de exterior',
    alexander: '📐 Métricas Alexander (A Pattern Language)',
    prompt_adherence: '📝 Adecuación al prompt (fidelidad al texto pedido)',
    appearance: 'Apariencia (elaboración visual)',
  };
  for (const cat of ['physical', 'interior', 'exterior', 'alexander', 'prompt_adherence', 'appearance']) {
    const metrics = report[cat] || {};
    if (!Object.keys(metrics).length) continue;
    const title = document.createElement('h4');
    title.className = 'eval-cat-title';
    title.textContent = CAT_TITLE[cat] || cat;
    content.appendChild(title);
    for (const [mid, m] of Object.entries(metrics)) {
      if (!m || typeof m !== 'object') continue;
      const row = document.createElement('div');
      row.className = 'eval-metric-row';
      const score = m.score;
      const pct = score == null ? 0 : Math.round(score * 100);
      const color = scoreColor(score);
      const info = meta[mid] || {};
      // tooltip = qué mide + soporte bibliográfico (defendible ante tribunal)
      const tip = [info.measures, info.source].filter(Boolean).join('\n— Fuente: ');
      const scopeTag = info.scope ? `<span class="eval-scope">${info.scope}</span>` : '';
      // desglose por rol del amueblado / por mueble pedido vs generado
      let extra = '';
      if (mid === 'room_furnishing' && m.by_role) {
        extra = '<div class="eval-byrole">' + Object.entries(m.by_role).map(
          ([r, v]) => `<span class="${v.furnished < v.total ? 'bad' : 'ok'}">${r}: ${v.furnished}/${v.total}</span>`
        ).join('') + '</div>';
      } else if (mid === 'furniture' && m.by_furniture) {
        // camas pedidas vs generadas, hornos pedidos vs generados, …
        extra = '<div class="eval-byrole">' + Object.entries(m.by_furniture).map(
          ([fur, v]) => `<span class="${v.present < v.requested ? 'bad' : 'ok'}">${fur}: ${v.present}/${v.requested}</span>`
        ).join('') + '</div>';
      }
      row.innerHTML = `
        <div class="eval-metric-header" title="${escapeHtml(tip)}">
          <span class="eval-metric-label">${METRIC_LABEL_ES[mid] || mid} ${scopeTag}</span>
          <span class="eval-metric-score" style="color:${color}">${fmtScore(score)}</span>
        </div>
        <div class="eval-metric-bar"><div class="eval-metric-fill"
          style="width:${pct}%; background:${color}"></div></div>
        ${(m.note || m.notes) ? `<div class="eval-metric-notes">${escapeHtml(m.note || m.notes)}</div>` : ''}
        ${extra}
      `;
      content.appendChild(row);
    }
  }

  // Skipped metrics
  if (comp.skipped_metrics && comp.skipped_metrics.length) {
    const s = document.createElement('div');
    s.className = 'eval-skipped';
    s.textContent = `Omitidas: ${comp.skipped_metrics.join(', ')}`;
    content.appendChild(s);
  }
}

function fmtScore(s) {
  if (s == null) return '—';
  return s.toFixed(2);
}

boot().catch((err) => {
  console.error('[viewer] boot failed', err);
  document.getElementById('dataset-count').textContent = 'ERROR cargando index.json';
});
