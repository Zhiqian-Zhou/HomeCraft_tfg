// Three.js renderer for a single building.
// Renders voxels as InstancedMesh groups keyed by texture-set + rotation.
// One InstancedMesh per (face-texture-set, rotation-hash) bucket → modest
// draw-call count even for buildings with hundreds of distinct block IDs.

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { parseBlock } from './blockstate.js';
import { resolve as resolveBlockHandler } from './blocks/index.js';
// Side-effect imports — each handler file registers itself with the
// blocks/index.js registry at module-load time. cubes.js installs the
// DEFAULT_CUBE_HANDLER; the rest register specific-family matchers.
// MUST be imported here (not from inside blocks/index.js) to avoid a
// circular-import / TDZ bug. Order doesn't affect correctness — match
// priority is registration order, and cubes.js uses setDefault() which
// is path-independent.
import './blocks/cubes.js';
import './blocks/doors.js';
import './blocks/plants.js';
import './blocks/stairs.js';
import './blocks/slabs.js';
import './blocks/connectors.js';
import './blocks/carpet.js';
import './blocks/lights.js';
import './blocks/bed.js';
import './blocks/trapdoors.js';
import './blocks/fences.js';
import './blocks/panes.js';
import './blocks/furniture.js';
import { getTexture, getCroppedTexture, FALLBACK_TEXTURE } from './textures.js';
import { FpsControls } from './fps-controls.js';

const BLOCK = 1; // 1 unit per voxel

export class BuildingRenderer {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a1a1d);
    this.scene.fog = new THREE.Fog(0x1a1a1d, 200, 800);

    const aspect = container.clientWidth / container.clientHeight;
    this.camera = new THREE.PerspectiveCamera(45, aspect, 0.1, 2000);
    this.camera.position.set(40, 40, 40);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(this.renderer.domElement);

    this.orbitControls = new OrbitControls(this.camera, this.renderer.domElement);
    this.orbitControls.enableDamping = true;
    this.orbitControls.dampingFactor = 0.08;
    this.fpsControls = new FpsControls(this.camera, this.renderer.domElement);
    this.mode = 'orbit';   // 'orbit' | 'fps'
    this._lastFrameTime = performance.now();

    // Lighting — ambient + directional (Minecraft-style flat-ish)
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const sun = new THREE.DirectionalLight(0xffffff, 0.85);
    sun.position.set(50, 80, 30);
    this.scene.add(sun);
    const fill = new THREE.DirectionalLight(0xa0a8c0, 0.25);
    fill.position.set(-50, 30, -30);
    this.scene.add(fill);

    // Grid + axes helpers (toggleable)
    this.gridHelper = new THREE.GridHelper(200, 200, 0x444444, 0x2a2a2d);
    this.scene.add(this.gridHelper);
    this.axesHelper = new THREE.AxesHelper(8);
    this.scene.add(this.axesHelper);

    // Raycaster for block-hover inspector
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.hovered = null;       // last hover info

    this.currentMeshes = [];
    this.currentVoxels = null;
    this.currentPalette = null;
    this.currentBuildingSize = [0, 0, 0];
    this.layerMin = 0;
    this.layerMax = Infinity;  // hides voxels outside [layerMin, layerMax]

    // Per-voxel storey/room tags (built once per loadBuilding from
    // doc.bot_decomposition). Indexed by global doc.voxels[i] order.
    //   voxelStorey[i] ∈ {-1, -2, 0..N-1}
    //     -1 = exterior (no storey AABB covers this voxel; always visible)
    //     -2 = inter-storey connector (stair/ladder); visible if either
    //          adjacent storey is active. connectorBase[i] gives base storey.
    //      k = belongs to storeys[k]
    //   voxelRoom[i] ∈ {-1, 0..M-1}, room flat index in this.roomMeta, or -1.
    this.voxelStorey = null;
    this.voxelRoom = null;
    this.storeyMeta = [];      // [{id, y0, y1, spaces:[...]}]
    this.roomMeta = [];        // [{id, function, storey, aabb}]
    this.connectorBase = null; // Map<globalVoxelIdx, baseStoreyIdx>

    // Resize handling
    this._onResize = this._onResize.bind(this);
    window.addEventListener('resize', this._onResize);

    // Animation loop
    this._tick = this._tick.bind(this);
    this._tick();
  }

  _onResize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    this.renderer.setSize(w, h);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  _tick() {
    requestAnimationFrame(this._tick);
    const now = performance.now();
    const dt = Math.min((now - this._lastFrameTime) / 1000, 0.1);
    this._lastFrameTime = now;
    if (this.mode === 'orbit') {
      this.orbitControls.update();
    } else {
      this.fpsControls.update(dt);
    }
    if (this._visAnimActive) this._stepVisibilityAnim(now);
    this.renderer.render(this.scene, this.camera);
  }

  setMode(mode) {
    if (mode === this.mode) return;
    if (mode === 'fps') {
      this.orbitControls.enabled = false;
      // Place the camera at the building's interior center, eye height
      const [W, H, D] = this.currentBuildingSize;
      this.fpsControls.placeAt(0, Math.min(H * 0.4, 8), 0);
      this.fpsControls.enable();
    } else {
      this.fpsControls.disable();
      this.orbitControls.enabled = true;
    }
    this.mode = mode;
  }

  setGridVisible(v) { this.gridHelper.visible = v; }
  setAxesVisible(v) { this.axesHelper.visible = v; }

  /** Clear current building. */
  clearBuilding() {
    for (const m of this.currentMeshes) {
      this.scene.remove(m);
      m.geometry?.dispose();
      // Don't dispose materials/textures — they're cached and reused.
    }
    this.currentMeshes = [];
    if (this.stairHighlightGroup) {
      this.scene.remove(this.stairHighlightGroup);
      this.stairHighlightGroup.traverse((o) => o.geometry?.dispose());
      this.stairHighlightGroup = null;
    }
    this.currentConnectors = null;
    this.currentVoxels = null;
    this.currentPalette = null;
    this.voxelStorey = null;
    this.voxelRoom = null;
    this.storeyMeta = [];
    this.roomMeta = [];
    this.connectorBase = null;
    this.activeStoreyIdx = null;
    this.currentBuildingSize = [0, 0, 0];
  }

  /** Load a building from its parsed JSON document. */
  async loadBuilding(doc) {
    console.info('[viewer] loadBuilding v-stairfix3', doc.id,
                 'voxels=', doc.voxels?.length);
    this.clearBuilding();
    const [W, H, D] = doc.bounding_box.size;
    this.currentBuildingSize = [W, H, D];

    // Resolve palette → parsed block info + textures via block handler registry
    const paletteInfo = {};
    const uniqueTextures = new Set();
    for (const [idxStr, blockIdRaw] of Object.entries(doc.block_palette)) {
      const idx = Number(idxStr);
      const { name, props } = parseBlock(blockIdRaw);
      const handler = resolveBlockHandler(name, props);
      const faces = handler.faces(name, props);
      paletteInfo[idx] = {
        name,
        props,
        blockIdRaw,
        handler,
        faces,
        rotation:    handler.rotation    ? handler.rotation(name, props)    : null,
        transparent: handler.transparent ? handler.transparent(name, props) : false,
        tint:        handler.tint        ? handler.tint(name, props)        : null,
      };
      // una cara puede ser string o descriptor {tex, crop}; preload el nombre.
      for (const tex of Object.values(faces)) {
        uniqueTextures.add(typeof tex === 'object' && tex ? tex.tex : tex);
      }
    }

    // Group voxels by palette idx (each palette index becomes one InstancedMesh)
    // The mesh's geometry is a unit BoxGeometry with per-face UV mapping
    // achieved via 6 sub-materials.
    const byPalette = new Map();
    for (const [x, y, z, p] of doc.voxels) {
      if (!byPalette.has(p)) byPalette.set(p, []);
      byPalette.get(p).push([x, y, z]);
    }

    this.currentVoxels = doc.voxels;
    this.currentPalette = paletteInfo;

    // Tag every voxel with its storey/room (semantic floor isolation).
    // No-op when bot_decomposition is absent (corpus buildings).
    this._buildStoreyIndex(doc);

    // Build one InstancedMesh per palette entry
    const tmpMatrix = new THREE.Matrix4();
    const tmpQuat = new THREE.Quaternion();
    const tmpScale = new THREE.Vector3(1, 1, 1);
    const tmpEuler = new THREE.Euler();

    // Center the building at origin for nicer camera framing
    const ox = -W / 2;
    const oz = -D / 2;
    const oy = 0; // keep ground at y=0

    // We need global-voxel-index → palette+local-index mapping to slice
    // voxelStorey into per-mesh storey-tag arrays. Build the inverse map
    // as we iterate doc.voxels (preserved order).
    const voxelToPaletteIdx = new Map();  // globalIdx → [palette, localIdx]
    {
      const counters = new Map();
      for (let gi = 0; gi < doc.voxels.length; gi++) {
        const p = doc.voxels[gi][3];
        const c = counters.get(p) ?? 0;
        voxelToPaletteIdx.set(gi, [p, c]);
        counters.set(p, c + 1);
      }
    }

    for (const [paletteIdx, positions] of byPalette.entries()) {
      const info = paletteInfo[paletteIdx];
      if (!info) continue;
      const mesh = this._makeInstancedMesh(info, positions.length);
      // Per-mesh storey-tag array, indexed by instance position in `positions`.
      const storeyTags = new Int8Array(positions.length).fill(-1);
      if (this.voxelStorey) {
        for (let gi = 0; gi < doc.voxels.length; gi++) {
          const [p, localIdx] = voxelToPaletteIdx.get(gi);
          if (p === paletteIdx) storeyTags[localIdx] = this.voxelStorey[gi];
        }
      }
      // Cache the unit-scale Matrix4 elements per instance once. setLayerBand
      // and setActiveStorey can then reuse these matrices instead of
      // recomputing quaternions every toggle. 16 floats per instance.
      const baseMatrices = new Float32Array(positions.length * 16);
      const tmpPos = new THREE.Vector3();
      // Per-instance visibility animation state (mirrors the GPU attribute).
      const visCurrent = mesh.geometry.attributes.aVisibility.array; // shared
      const visStart = new Float32Array(positions.length).fill(1);
      const visTarget = new Float32Array(positions.length).fill(1);
      mesh.userData = {
        paletteIdx, paletteInfo: info, positions, storeyTags, baseMatrices,
        visibility: {
          current: visCurrent, start: visStart, target: visTarget,
          animStartTime: 0, animDurationMs: 0,
        },
      };

      for (let i = 0; i < positions.length; i++) {
        const [x, y, z] = positions[i];
        const px = x + ox + 0.5;
        const py = y + oy + 0.5;
        const pz = z + oz + 0.5;

        if (info.rotation) {
          tmpEuler.set(info.rotation.x, info.rotation.y, info.rotation.z);
          tmpQuat.setFromEuler(tmpEuler);
        } else {
          tmpQuat.identity();
        }
        tmpPos.set(px, py, pz);
        tmpMatrix.compose(tmpPos, tmpQuat, tmpScale);
        mesh.setMatrixAt(i, tmpMatrix);
        // Snapshot the 16 floats into the per-instance cache.
        for (let j = 0; j < 16; j++) baseMatrices[i * 16 + j] = tmpMatrix.elements[j];
      }
      mesh.instanceMatrix.needsUpdate = true;
      this.scene.add(mesh);
      this.currentMeshes.push(mesh);
    }

    // Stair highlight overlay (locatable through walls; toggled from the UI).
    // Envuelto en try/catch: pase lo que pase, NUNCA debe impedir el render ni
    // el frameCamera() de abajo (si no, el lienzo queda en blanco).
    this.currentConnectors = doc.connectors || {};
    try {
      this._buildStairHighlights(W, H, D);
    } catch (e) {
      console.warn('[viewer] stair highlight skipped:', e);
    }

    this.frameCamera();
  }

  /** Bright translucent pillars at each staircase shaft so the user can SEE
   *  where the stairs are even through walls / when a floor is isolated. */
  _buildStairHighlights(W, H, D) {
    const grp = new THREE.Group();
    grp.visible = !!this._stairHighlightOn;
    const ox = -W / 2, oz = -D / 2;
    const mat = new THREE.MeshBasicMaterial({
      color: 0xff7a18, transparent: true, opacity: 0.35,
      depthTest: false, depthWrite: false,
    });
    const edgeMat = new THREE.LineBasicMaterial({
      color: 0xffa94d, transparent: true, opacity: 0.9, depthTest: false });

    const addBox = (x0, y0, z0, x1, y1, z1) => {
      const sw = Math.max(1, x1 - x0), sh = Math.max(1, y1 - y0), sd = Math.max(1, z1 - z0);
      const geo = new THREE.BoxGeometry(sw + 0.4, sh, sd + 0.4);
      const cx = (x0 + x1) / 2 + ox, cy = (y0 + y1) / 2, cz = (z0 + z1) / 2 + oz;
      const box = new THREE.Mesh(geo, mat);
      box.position.set(cx, cy, cz); box.renderOrder = 998; grp.add(box);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo), edgeMat);
      edges.position.set(cx, cy, cz); edges.renderOrder = 999; grp.add(edges);
    };

    // El hueco de la escalera viene del connector_plan (coords exactas: las
    // escaleras del connector NO se espejan — el mirror del voxelizer es por
    // skill, interno a cada sala). Varias escaleras pueden compartir el mismo
    // hueco XZ (una por transición de planta): las FUSIONAMOS por footprint XZ
    // en una sola caja de altura completa para no apilar cajas redundantes.
    const stairs = Array.isArray(this.currentConnectors.staircases)
      ? this.currentConnectors.staircases : [];
    const byXZ = new Map();
    for (const st of stairs) {
      const a = st.aabb || (st.validated || {}).aabb;
      if (!Array.isArray(a) || a.length !== 6) continue;
      const k = `${a[0]},${a[2]},${a[3]},${a[5]}`;
      const e = byXZ.get(k);
      if (e) { e[1] = Math.min(e[1], a[1]); e[4] = Math.max(e[4], a[4]); }
      else byXZ.set(k, [...a]);
    }
    const boxes = [...byXZ.values()];
    for (const a of boxes) addBox(a[0], a[1], a[2], a[3], a[4], a[5]);

    // Además de la caja del hueco, resaltar los PELDAÑOS reales que caen dentro
    // (a través de los muros) → se ve la FORMA ascendente de la escalera, no
    // solo dónde está. Marcadores sólidos brillantes sobre cada escalón.
    if (boxes.length) {
      const stepMat = new THREE.MeshBasicMaterial({
        color: 0xffd34d, transparent: true, opacity: 0.9,
        depthTest: false, depthWrite: false,
      });
      const stairRx = /(_stairs|_ladder|ladder)$/i;
      const inAnyBox = (x, y, z) => boxes.some(a =>
        x >= a[0] && x < a[3] && y >= a[1] && y < a[4] && z >= a[2] && z < a[5]);
      const stepGeo = new THREE.BoxGeometry(0.7, 0.5, 0.7);
      for (const mesh of this.currentMeshes) {
        const ud = mesh.userData || {};
        if (!stairRx.test(ud.paletteInfo?.name ?? '') || !Array.isArray(ud.positions)) continue;
        for (const [x, y, z] of ud.positions) {
          if (!inAnyBox(x, y, z)) continue;
          const m = new THREE.Mesh(stepGeo, stepMat);
          m.position.set(x + ox + 0.5, y + 0.5, z + oz + 0.5);
          m.renderOrder = 1000;
          grp.add(m);
        }
      }
    }
    this.stairHighlightGroup = grp;
    this.scene.add(grp);
  }

  /** Toggle the stair highlight overlay. */
  setStairHighlight(on) {
    this._stairHighlightOn = !!on;
    if (this.stairHighlightGroup) this.stairHighlightGroup.visible = !!on;
  }

  /** Camera pose in VOXEL coords (for the 2D minimap marker). Returns
   *  {vx, vy, vz, dx, dz} where (dx,dz) is the horizontal look direction. */
  getCameraPose() {
    const [W, , D] = this.currentBuildingSize || [0, 0, 0];
    const p = this.camera.position;
    const dir = new THREE.Vector3();
    this.camera.getWorldDirection(dir);
    return {
      vx: p.x + W / 2, vy: p.y, vz: p.z + D / 2,
      dx: dir.x, dz: dir.z,
    };
  }

  /** Tag every voxel with the storey and room it belongs to.
   *
   *  Rule: Y-band primary (storey.aabb covers y ∈ [y0, y1)), room-AABB
   *  secondary (room.aabb fully contains voxel → tagged with room).
   *
   *  Sentinels:
   *    storey = -1  exterior/roof — voxel falls outside every storey AABB.
   *                 Always visible (treated as "envelope" / "exterior").
   *    storey = -2  inter-storey connector (stairs/ladder/scaffolding).
   *                 connectorBase[i] gives the lower-storey index. Visible
   *                 when active storey is base or base+1.
   *    room   = -1  voxel inside the storey's Y band but not in any room
   *                 AABB (shared walls, perimeter, decorative ornaments).
   *
   *  No-op when doc.bot_decomposition is absent (corpus buildings).
   */
  _buildStoreyIndex(doc) {
    const bot = doc?.bot_decomposition;
    const storeys = bot?.building?.storeys;
    if (!Array.isArray(storeys) || storeys.length === 0) {
      this.voxelStorey = null;
      this.voxelRoom = null;
      this.storeyMeta = [];
      this.roomMeta = [];
      this.connectorBase = null;
      return;
    }

    // Cache storey + room metadata in flat order.
    this.storeyMeta = [];
    this.roomMeta = [];
    for (let s = 0; s < storeys.length; s++) {
      const st = storeys[s];
      const spaces = Array.isArray(st.spaces) ? st.spaces : [];
      // Storey y-range: explicit aabb if present, else union of spaces.
      let y0, y1;
      if (Array.isArray(st.aabb) && st.aabb.length === 6) {
        y0 = st.aabb[1]; y1 = st.aabb[4];
      } else if (spaces.length) {
        y0 = Math.min(...spaces.map((sp) => sp.aabb[1]));
        y1 = Math.max(...spaces.map((sp) => sp.aabb[4]));
      } else {
        continue;
      }
      const storeyEntry = { id: st.id, y0, y1, spaces: [] };
      for (const sp of spaces) {
        if (!Array.isArray(sp.aabb) || sp.aabb.length !== 6) continue;
        const roomIdx = this.roomMeta.length;
        this.roomMeta.push({
          id: sp.id, function: sp.function, storey: s, aabb: sp.aabb.slice(),
        });
        storeyEntry.spaces.push(roomIdx);
      }
      this.storeyMeta.push(storeyEntry);
    }

    const N = doc.voxels.length;
    this.voxelStorey = new Int8Array(N).fill(-1);
    this.voxelRoom = new Int16Array(N).fill(-1);
    this.connectorBase = new Map();

    // Huecos de escalera (footprint XZ del connector_plan, fusionados a altura
    // completa). Los peldaños DENTRO de un hueco son la escalera REAL (no la
    // decoración de tejado/fachada) → se etiquetan -3 = "escalera del núcleo",
    // SIEMPRE visible al aislar cualquier planta (para poder verla en todas).
    const shaftBoxes = [];
    {
      const byXZ = new Map();
      const scs = Array.isArray(doc.connectors?.staircases) ? doc.connectors.staircases : [];
      for (const st of scs) {
        const a = st.aabb || (st.validated || {}).aabb;
        if (!Array.isArray(a) || a.length !== 6) continue;
        const k = `${a[0]},${a[2]},${a[3]},${a[5]}`;
        const e = byXZ.get(k);
        if (e) { e[1] = Math.min(e[1], a[1]); e[4] = Math.max(e[4], a[4]); }
        else byXZ.set(k, [...a]);
      }
      shaftBoxes.push(...byXZ.values());
    }
    const inShaft = (x, y, z) => shaftBoxes.some(a =>
      x >= a[0] && x < a[3] && y >= a[1] && y < a[4] && z >= a[2] && z < a[5]);

    // Heuristic: detect connector voxels by palette block name.
    const connectorRx = /(_stairs|_ladder|_scaffolding|ladder|vine)$/i;

    for (let i = 0; i < N; i++) {
      const [x, y, z, p] = doc.voxels[i];
      const info = this.currentPalette?.[p];
      const isConnector = info && connectorRx.test(info.name ?? '');

      // Escalera del núcleo (peldaño/escalera dentro del hueco planeado) →
      // tag -3, visible en todas las plantas aisladas.
      if (isConnector && inShaft(x, y, z)) {
        this.voxelStorey[i] = -3;
        continue;
      }

      // Pass A — primary Y-band tag
      let storeyIdx = -1;
      for (let s = 0; s < this.storeyMeta.length; s++) {
        if (y >= this.storeyMeta[s].y0 && y < this.storeyMeta[s].y1) {
          storeyIdx = s;
          break;
        }
      }

      // Pass B — refine with room AABB (only the candidate storey's rooms)
      if (storeyIdx >= 0) {
        for (const roomIdx of this.storeyMeta[storeyIdx].spaces) {
          const a = this.roomMeta[roomIdx].aabb;
          if (x >= a[0] && x < a[3]
              && y >= a[1] && y < a[4]
              && z >= a[2] && z < a[5]) {
            this.voxelRoom[i] = roomIdx;
            break;
          }
        }
      }

      // Pass C — connector handling: if it's a stair/ladder AND the next
      // storey starts at y+1, mark as -2 (linking storeyIdx → storeyIdx+1).
      if (isConnector && storeyIdx >= 0
          && storeyIdx + 1 < this.storeyMeta.length
          && Math.abs(y + 1 - this.storeyMeta[storeyIdx + 1].y0) <= 1) {
        this.voxelStorey[i] = -2;
        this.connectorBase.set(i, storeyIdx);
      } else {
        this.voxelStorey[i] = storeyIdx;
      }
    }

    // Console sanity (helps verify against bot_decomposition during dev).
    if (typeof window !== 'undefined' && window.__DEBUG_FLOORS) {
      const counts = {};
      for (const t of this.voxelStorey) {
        counts[t] = (counts[t] ?? 0) + 1;
      }
      console.log('[storey-index] ' + JSON.stringify({
        storeys: this.storeyMeta.length,
        rooms: this.roomMeta.length,
        voxelTagCounts: counts,
        connectors: this.connectorBase.size,
      }));
    }
  }

  /** Create an InstancedMesh for one palette entry.
   *
   *  The block handler decides the geometry (cube, cross, slab, stair, …).
   *  Materials are always a 6-material array in BoxGeometry face order
   *  ([east, west, up, down, south, north]); custom geometries that need
   *  fewer materials (e.g. a single-material cross plant) can either
   *  request the same texture on all 6 faces (`faces.up = faces.down = …`)
   *  or use a custom geometry whose groups all reference index 0.
   */
  _makeInstancedMesh(info, count) {
    const geom = info.handler.geometry(info.name, info.props);
    const faceOrder = ['east', 'west', 'up', 'down', 'south', 'north'];
    const materials = faceOrder.map((face) => {
      const faceVal = info.faces[face];
      // Una cara puede ser un nombre de textura (string) o un descriptor con
      // recorte de atlas {tex, crop:[x,y,w,h], atlas} — p.ej. la cama de MC.
      const onLoad = (loadedTex) => { mat.map = loadedTex; mat.needsUpdate = true; };
      const map0 = (faceVal && typeof faceVal === 'object' && faceVal.crop)
        ? getCroppedTexture(faceVal.tex, faceVal.crop, onLoad, faceVal.atlas || 64)
        : getTexture(faceVal, onLoad);
      const mat = new THREE.MeshLambertMaterial({
        map: map0,
        // For floor isolation we need alpha-blended dim states. Forcing
        // transparent: true on opaque palettes carries a small depth-sort
        // cost — at ≤10 meshes per building this is negligible. depthWrite
        // remains true for opaque palettes so they don't z-fight when dim.
        transparent: true,
        alphaTest: info.transparent ? 0.1 : 0,
        depthWrite: info.transparent ? false : true,
        color: info.tint ?? 0xffffff,
        side: info.handler.doubleSided ? THREE.DoubleSide : THREE.FrontSide,
      });
      mat.onBeforeCompile = _patchShaderForVisibility;
      return mat;
    });
    const mesh = new THREE.InstancedMesh(geom, materials, count);
    mesh.frustumCulled = true;

    // Per-instance Float32 attribute: 1.0=opaque, 0.3=dim, 0.0=hidden.
    // Dynamic-draw because we'll update it on every floor change.
    const visArr = new Float32Array(count).fill(1.0);
    const visAttr = new THREE.InstancedBufferAttribute(visArr, 1);
    visAttr.setUsage(THREE.DynamicDrawUsage);
    geom.setAttribute('aVisibility', visAttr);

    return mesh;
  }

  /** Fit camera to current building. */
  frameCamera() {
    const [W, H, D] = this.currentBuildingSize;
    const maxDim = Math.max(W, H, D);
    const dist = maxDim * 1.6 + 8;
    this.camera.position.set(dist * 0.7, dist * 0.7, dist * 0.7);
    this.orbitControls.target.set(0, H / 2, 0);
    this.orbitControls.update();
  }

  /** Encuadra la cámara en PICADO (casi cenital, ligero ángulo para dar
   *  profundidad) sobre una planta aislada → se ve claramente QUÉ HAY en ella
   *  (el techo ya está cortado por setActiveStorey). idx = índice de storey. */
  frameStorey(idx) {
    if (idx == null || !this.storeyMeta || !this.storeyMeta[idx]) return;
    const [W, , D] = this.currentBuildingSize;
    const ox = -W / 2, oz = -D / 2;
    const s = this.storeyMeta[idx];
    // centro XZ de la planta (de su union de salas si la hay, si no el edificio)
    let cx = 0, cz = 0, span = Math.max(W, D);
    if (this.roomMeta && s.spaces && s.spaces.length) {
      let x0 = Infinity, x1 = -Infinity, z0 = Infinity, z1 = -Infinity;
      for (const ri of s.spaces) {
        const a = this.roomMeta[ri].aabb;
        x0 = Math.min(x0, a[0]); x1 = Math.max(x1, a[3]);
        z0 = Math.min(z0, a[2]); z1 = Math.max(z1, a[5]);
      }
      cx = (x0 + x1) / 2 + ox; cz = (z0 + z1) / 2 + oz;
      span = Math.max(x1 - x0, z1 - z0);
    }
    const cy = (s.y0 + s.y1) / 2;
    const dist = span * 1.4 + 10;
    // picado: muy por encima, ligeramente desplazado para ver relieve
    this.camera.position.set(cx + span * 0.25, cy + dist, cz + span * 0.25 + 0.01);
    this.orbitControls.target.set(cx, cy, cz);
    this.orbitControls.update();
  }

  /** Set Y layer band — voxels with y < minY OR y > maxY are hidden.
   *
   *  Uses the cached baseMatrices from loadBuilding(): per-toggle work is
   *  one typed-array read per instance plus one Matrix4 set, no quaternion
   *  recompute. Roughly 10× faster than the legacy implementation on
   *  multi-thousand-voxel buildings.
   */
  setLayerBand(minY, maxY) {
    this.layerMin = minY;
    this.layerMax = maxY;
    const tmpMatrix = new THREE.Matrix4();
    const ZERO = new Float32Array(16);  // all zeros = zero-scale, hidden

    for (const mesh of this.currentMeshes) {
      const positions = mesh.userData.positions;
      const baseMatrices = mesh.userData.baseMatrices;
      if (!baseMatrices) continue;  // mesh built before cache existed
      for (let i = 0; i < positions.length; i++) {
        const y = positions[i][1];
        const hidden = y < minY || y > maxY;
        if (hidden) {
          tmpMatrix.fromArray(ZERO);
        } else {
          tmpMatrix.fromArray(baseMatrices, i * 16);
        }
        mesh.setMatrixAt(i, tmpMatrix);
      }
      mesh.instanceMatrix.needsUpdate = true;
    }
  }

  /** Back-compat: setLayerCap(cap) === setLayerBand(0, cap) */
  setLayerCap(cap) { this.setLayerBand(0, cap); }


  // ── Semantic floor isolation (Step 4) ─────────────────────────────────

  /** Show only voxels belonging to storey `storeyIdx` (0-based index into
   *  this.storeyMeta). Other storeys are dimmed or hidden per `opts`.
   *
   *  storeyIdx = null → opaque-all (clear isolation).
   *
   *  opts.dimBelow   {bool}   show lower storeys at dimOpacity (default true)
   *  opts.dimOpacity {number} 0..1, default 0.30
   *  opts.fadeMs     {number} animation duration, default 300 (0=instant)
   *
   *  Exterior voxels (storeyStorey === -1) stay opaque always.
   *  Connector voxels (storeyStorey === -2) visible if active storey is
   *  the connector's base storey OR base+1.
   */
  setActiveStorey(storeyIdx, opts = {}) {
    const { dimBelow = true, dimOpacity = 0.30, fadeMs = 300 } = opts;
    if (!this.currentMeshes.length) return;
    if (!this.voxelStorey && storeyIdx !== null) {
      // No bot_decomposition — silently no-op.
      return;
    }
    this.activeStoreyIdx = storeyIdx;
    const now = performance.now();

    // Resolve the active storey Y-range for exterior voxel classification.
    // Exterior voxels (storey=-1) above the active floor get hidden (roof,
    // eaves cut away); those at or below stay visible/dim.
    const activeMeta = (storeyIdx !== null && storeyIdx >= 0)
      ? this.storeyMeta?.[storeyIdx] : null;
    const activeY0 = activeMeta?.y0;
    const activeY1 = activeMeta?.y1;

    // Robust ceiling/roof cut. Storey AABBs are half-open and contiguous
    // (y0..y1, next storey starts at y1), so the active storey's ceiling, the
    // floor slab above it and the roof all sit at y >= y1. Cutting there gives
    // a clean top-down view of the room. Using the AABB top (not the max
    // tagged voxel Y) is essential for tiered roofs/pagodas, where the eaves
    // are tagged to the storey and would otherwise defeat the cut. Degenerate
    // zero-height storey AABBs (a generator quirk) fall back to the next
    // storey's floor, then to the highest tagged voxel.
    let cutY = Infinity;
    if (storeyIdx !== null && storeyIdx >= 0) {
      const m = this.storeyMeta?.[storeyIdx];
      const sy0 = m?.y0 ?? 0;
      let c = (m && m.y1 != null) ? m.y1 : null;
      if (c == null || c <= sy0) {
        const next = this.storeyMeta?.[storeyIdx + 1];
        if (next && next.y0 != null && next.y0 > sy0) c = next.y0;
      }
      if (c == null || c <= sy0) {
        let maxTagY = -Infinity;
        for (const mesh of this.currentMeshes) {
          const tags = mesh.userData.storeyTags;
          const positions = mesh.userData.positions;
          if (!tags || !positions) continue;
          for (let i = 0; i < positions.length; i++) {
            if (tags[i] === storeyIdx && positions[i][1] > maxTagY) maxTagY = positions[i][1];
          }
        }
        if (maxTagY > -Infinity) c = maxTagY + 1;
      }
      cutY = (c != null) ? c : Infinity;
    }

    // Pre-compute "connector base storey" inverse lookup for the meshes —
    // expensive globally but cheap per voxel here (Map.get).
    for (const mesh of this.currentMeshes) {
      const vis = mesh.userData.visibility;
      if (!vis) continue;
      const tags = mesh.userData.storeyTags;
      const positions = mesh.userData.positions;

      // Snapshot current visibility as the animation start
      vis.start.set(vis.current);

      for (let i = 0; i < positions.length; i++) {
        const tag = tags[i];
        const y = positions[i][1];
        let target;
        if (tag === -3) {
          // Escalera del núcleo: SIEMPRE visible (en todas las plantas), para
          // que se vea cómo conecta los pisos. Exenta del corte de techo.
          target = 1.0;
        } else if (storeyIdx === null || storeyIdx < 0) {
          target = 1.0;                              // opaque-all
        } else if (y >= cutY) {
          // CEILING and everything above it (room ceiling, wall-top crown,
          // floor slab above, roof, eaves) → hidden. This is the dollhouse
          // top-down cut: the active floor's walls, floor and furniture all
          // sit below cutY and stay visible.
          target = 0.0;
        } else if (tag === -1) {
          // Exterior / no-storey voxel below the cut (envelope, foundation).
          //   activeY0 ≤ y < cutY → opaque (envelope at the active floor)
          //   y < activeY0        → dim    (foundation / lower-floor exterior)
          if (activeY0 != null && y >= activeY0) {
            target = 1.0;
          } else if (dimBelow) {
            target = dimOpacity;
          } else {
            target = 0.0;
          }
        } else if (tag === -2) {
          // Connector: visible if active == base OR base+1.
          // (We don't have per-mesh connectorBase index, recompute from
          // global. Acceptable: the operation is per-toggle.)
          const globalIdx = this._meshLocalToGlobal(mesh, i);
          const base = this.connectorBase?.get(globalIdx);
          target = (base !== undefined
                    && (storeyIdx === base || storeyIdx === base + 1))
            ? 1.0 : 0.0;
        } else if (tag === storeyIdx) {
          target = 1.0;                              // active floor
        } else if (dimBelow && tag < storeyIdx) {
          target = dimOpacity;                       // below = dim
        } else {
          target = 0.0;                              // above = hidden
        }
        vis.target[i] = target;
      }
      vis.animStartTime = now;
      vis.animDurationMs = fadeMs;
    }
    this._visAnimActive = true;
    // If fadeMs==0, advance immediately so callers can stack edits.
    if (fadeMs <= 0) this._stepVisibilityAnim(now + 1);
  }

  /** Reset active storey tracking without touching visibility. Used by
   *  the layer-slider mode-switch: when the user drags Y-band sliders,
   *  any active storey is conceptually deactivated (the slider applies
   *  its own Y filter via the matrix path). */
  clearActiveStoreyState() { this.activeStoreyIdx = null; }

  /** Build global voxel index from (mesh, local position index). Lazily
   *  computes a per-mesh reverse map the first time it's needed. */
  _meshLocalToGlobal(mesh, localIdx) {
    let map = mesh.userData._localToGlobal;
    if (!map) {
      // Reconstruct from doc.voxels order — only needed if connectors exist.
      const positions = mesh.userData.positions;
      const paletteIdx = mesh.userData.paletteIdx;
      map = new Int32Array(positions.length);
      let li = 0;
      for (let gi = 0; gi < this.currentVoxels.length; gi++) {
        if (this.currentVoxels[gi][3] === paletteIdx) {
          map[li++] = gi;
        }
      }
      mesh.userData._localToGlobal = map;
    }
    return map[localIdx];
  }

  /** Per-frame: lerp aVisibility from start→target over animDurationMs. */
  _stepVisibilityAnim(now) {
    let allDone = true;
    for (const mesh of this.currentMeshes) {
      const vis = mesh.userData.visibility;
      if (!vis) continue;
      const dur = vis.animDurationMs;
      let t = dur > 0 ? (now - vis.animStartTime) / dur : 1.0;
      if (t >= 1) { t = 1; } else { allDone = false; }
      // easeInOutCubic
      const e = t < 0.5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
      const cur = vis.current, st = vis.start, tg = vis.target;
      for (let i = 0; i < cur.length; i++) {
        cur[i] = st[i] + (tg[i] - st[i]) * e;
      }
      mesh.geometry.attributes.aVisibility.needsUpdate = true;
    }
    if (allDone) this._visAnimActive = false;
  }

  /** Detect floor Y levels by finding local minima in the per-Y voxel histogram.
   *  Returns an array of Y values where vertical density drops sharply
   *  (suggesting a floor gap / between-story air pocket).
   */
  detectFloors() {
    if (!this.currentVoxels) return [];
    const [, H] = this.currentBuildingSize;
    const histogram = new Array(H).fill(0);
    for (const [, y] of this.currentVoxels) {
      if (y >= 0 && y < H) histogram[y]++;
    }
    // Smooth the histogram a tiny bit
    const smooth = histogram.map((v, i) =>
      (v + (histogram[i - 1] ?? v) + (histogram[i + 1] ?? v)) / 3);
    const peak = Math.max(...smooth);
    if (peak < 5) return [];

    const floors = [];
    // A floor is a local minimum BELOW 25% of peak, with peaks on both sides.
    const threshold = peak * 0.25;
    for (let y = 1; y < H - 1; y++) {
      if (smooth[y] < threshold && smooth[y] < smooth[y - 1] && smooth[y] <= smooth[y + 1]) {
        floors.push(y);
      }
    }
    return floors;
  }

  /** Raycast at screen coords (px, py) — returns { blockIdRaw, x, y, z } or null.
   *  When floor isolation is active, hits on dim or hidden voxels are
   *  skipped (only the active floor is pickable). */
  pick(clientX, clientY) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(this.currentMeshes, false);
    for (const hit of hits) {
      const instanceId = hit.instanceId;
      if (instanceId == null) continue;
      // Reject dim/hidden voxels (only the fully opaque set is pickable).
      const vis = hit.object.userData.visibility?.current;
      if (vis && vis[instanceId] < 0.9) continue;
      const positions = hit.object.userData.positions;
      if (!positions || !positions[instanceId]) continue;
      const [x, y, z] = positions[instanceId];
      const info = hit.object.userData.paletteInfo;
      return { blockIdRaw: info.blockIdRaw, name: info.name, props: info.props, x, y, z };
    }
    return null;
  }

  /** Render to a PNG data URL for screenshots. */
  screenshot() {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL('image/png');
  }
}


/** Injects per-instance visibility into a MeshLambertMaterial shader.
 *
 *  Reads geometry attribute `aVisibility ∈ [0, 1]` per instance:
 *    1.0  fully opaque  — render normally
 *    0.x  dim          — multiply fragment alpha by this value
 *    0.0  hidden       — vertex collapse (cheap) + fragment discard
 *
 *  Assigned to material.onBeforeCompile in _makeInstancedMesh.
 */
function _patchShaderForVisibility(shader) {
  shader.vertexShader = shader.vertexShader
    .replace(
      '#include <common>',
      `#include <common>
attribute float aVisibility;
varying float vVisibility;`,
    )
    .replace(
      '#include <begin_vertex>',
      `#include <begin_vertex>
vVisibility = aVisibility;
if (aVisibility <= 0.001) { transformed = vec3(0.0); }`,
    );
  shader.fragmentShader = shader.fragmentShader
    .replace(
      '#include <common>',
      `#include <common>
varying float vVisibility;`,
    )
    .replace(
      '#include <dithering_fragment>',
      `if (vVisibility <= 0.001) discard;
gl_FragColor.a *= vVisibility;
#include <dithering_fragment>`,
    );
}
