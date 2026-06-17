# HomeCraft v2 — Visor RAG-E

Visor web local para inspeccionar cualquier edificio voxel en formato `ReferenceBuilding` JSON (los que genera el pipeline, o el corpus RAG-E). **El corpus de referencia no se incluye en este repo** (ver *Data availability* en el [README](../README.md#data-availability)); abre cualquier edificio con `?file=<ruta>` o coloca tus JSON en `rag/reference_buildings/processed/` y regenera el índice.

## Cómo arrancar

Desde la raíz del repo (`TFGv2Z/`):

```
python3 -m http.server 8000
```

Abre `http://localhost:8000/viewer/` en el navegador.

> Hace falta servirlo por HTTP — no funciona si abres `index.html` con `file://` porque `fetch()` no carga ficheros locales.

## Cómo regenerar el índice

Si añades / quitas edificios en `rag/reference_buildings/processed/`, regenera el índice:

```
python3 tools/build_viewer_index.py
```

## Atajos de teclado

- `R` — reset cámara
- `S` — screenshot (descarga PNG)
- `F` — fullscreen
- `G` — toggle grid
- L — layer slicer (rango Y) para ver interiores

## Arquitectura

```
viewer/
├── index.html
├── css/style.css
├── js/
│   ├── app.js         orquestador + UI + filters
│   ├── renderer.js    Three.js + InstancedMesh por palette idx
│   ├── blockstate.js  parser de "minecraft:oak_stairs[facing=east]" + rotaciones
│   └── textures.js    cache + lazy-load de texturas (jsDelivr / misode-mcmeta)
└── data/index.json    metadata ligera de los edificios (vacío en este repo; el corpus no se incluye)
```

## Fuentes externas (CDN)

- **Three.js**: `cdn.jsdelivr.net/npm/three@0.160.0/` (vía ESM import map)
- **Texturas MC 1.16.5** (vía jsDelivr):
  - Principal: `cdn.jsdelivr.net/gh/misode/mcmeta@1.16.5-assets/assets/minecraft/textures/block/`
  - Fallback: `cdn.jsdelivr.net/gh/InventivetalentDev/minecraft-assets@1.16.5/.../block/`
  - Para uso offline, descarga la carpeta de bloques y sirve localmente.

## Limitaciones conocidas

- **Blockstates**: solo se aplican rotaciones para los ~40 bloques más comunes (logs, stairs, doors, slabs, furnaces). Bloques con orientación no listada se renderizan sin rotación (cubo estándar).
- **Geometría no-cúbica**: stairs, slabs, doors, fences, panes, trapdoors, alfombras y otras familias se renderizan con geometría dedicada (ver `js/blocks/`). Los bloques sin handler específico caen a un cubo estándar; la geometría exacta de algún caso raro puede no coincidir con el block model JSON de 1.16.5.
- **Tinting**: leaves/grass se tintan con un color por defecto razonable (no usa el biome colormap).
- **Performance**: edificios de >100k voxels pueden tardar 1-3 segundos en cargar. Usa el filtro de tamaño en la sidebar para evitarlos hasta que hagas LOD/chunking.
