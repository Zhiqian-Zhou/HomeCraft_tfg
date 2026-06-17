# HomeCraft v2 — Visor RAG-E

Visor web local para inspeccionar los edificios voxel del corpus RAG-E y cualquier edificio generado. Este repo público incluye una muestra de 61 edificios (licencia MIT); el corpus completo de desarrollo tiene ~2.746.

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
│   └── textures.js    cache + lazy-load de mcasset.cloud
└── data/index.json    metadata ligera de los edificios (muestra de 61; corpus completo ~2.746)
```

## Fuentes externas (CDN)

- **Three.js**: `cdn.jsdelivr.net/npm/three@0.160.0/` (vía ESM import map)
- **Texturas MC 1.16.5**: `mcasset.cloud/1.16.5/assets/minecraft/textures/block/*.png`
  - Fallback: `raw.githubusercontent.com/misode/mcmeta/1.16.5-assets/`
  - Para uso offline, descarga la carpeta de bloques y sirve localmente.

## Limitaciones conocidas

- **Blockstates**: solo se aplican rotaciones para los ~40 bloques más comunes (logs, stairs, doors, slabs, furnaces). Bloques con orientación no listada se renderizan sin rotación (cubo estándar).
- **Geometría no-cúbica**: stairs, slabs, doors, fences, panes se renderizan como cubos completos. Para geometría correcta haría falta parsear los block models JSON de 1.16.5.
- **Tinting**: leaves/grass se tintan con un color por defecto razonable (no usa el biome colormap).
- **Performance**: edificios de >100k voxels pueden tardar 1-3 segundos en cargar. Usa el filtro de tamaño en la sidebar para evitarlos hasta que hagas LOD/chunking.
