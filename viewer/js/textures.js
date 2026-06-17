// Texture cache. Lazy-loads 1.16.5 block textures from a CORS-friendly CDN.
//
// IMPORTANT: WebGL textures require the server to send Access-Control-Allow-Origin
// (the browser blocks cross-origin images from being used as WebGL textures
// even though they can be displayed in <img>). We use jsdelivr, which serves
// any GitHub repo with `access-control-allow-origin: *` headers.
//
// Primary source: misode/mcmeta @ 1.16.5-assets branch (curated assets).
// Fallback: InventivetalentDev/minecraft-assets @ 1.16.5 (alternative repo).
//
// Returns THREE.Texture objects with nearest-neighbour filtering (so the
// 16x16 textures stay crisp instead of blurring).

import * as THREE from 'three';

const CDN_BASE      = 'https://cdn.jsdelivr.net/gh/misode/mcmeta@1.16.5-assets/assets/minecraft/textures/block/';
const FALLBACK_BASE = 'https://cdn.jsdelivr.net/gh/InventivetalentDev/minecraft-assets@1.16.5/assets/minecraft/textures/block/';
// Raíz de texturas (sin /block/) para texturas de ENTIDAD como la cama real de
// Minecraft (entity/bed/<color>.png — atlas 64×64 con colchón, almohada, patas).
const ROOT_BASE      = CDN_BASE.replace(/block\/$/, '');
const ROOT_FALLBACK  = FALLBACK_BASE.replace(/block\/$/, '');

const loader = new THREE.TextureLoader();
// Explicit crossOrigin so the browser sends the Origin header and processes
// the CORS response correctly (THREE defaults to 'anonymous' since r60, but
// we set it explicitly for clarity).
loader.crossOrigin = 'anonymous';
const cache = new Map();       // name → THREE.Texture | Promise
const failed = new Set();      // textures known to 404

// Solid color texture used as fallback for missing block textures.
function fallbackTexture(colorHex = 0xa3a3a3) {
  const c = new THREE.DataTexture(
    new Uint8Array([
      (colorHex >> 16) & 0xff, (colorHex >> 8) & 0xff, colorHex & 0xff, 255
    ]),
    1, 1, THREE.RGBAFormat
  );
  c.needsUpdate = true;
  c.magFilter = THREE.NearestFilter;
  c.minFilter = THREE.NearestFilter;
  return c;
}

const FALLBACK_TEXTURE = fallbackTexture(0x808080);

function loadOne(url) {
  return new Promise((resolve, reject) => {
    loader.load(
      url,
      (tex) => {
        tex.magFilter = THREE.NearestFilter;
        tex.minFilter = THREE.NearestFilter;
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.generateMipmaps = false;
        resolve(tex);
      },
      undefined,
      (err) => reject(err)
    );
  });
}

/** Returns a THREE.Texture immediately. Loads from CDN async; while loading
 *  serves a gray fallback. When the real texture arrives, the material's
 *  `map` is replaced (caller passes a callback). */
export function getTexture(name, onLoaded) {
  if (cache.has(name)) {
    const v = cache.get(name);
    if (v instanceof Promise) {
      v.then(onLoaded);
      return FALLBACK_TEXTURE;
    }
    return v;
  }
  if (failed.has(name)) return FALLBACK_TEXTURE;

  // Texturas de entidad (p.ej. "entity/bed/red") se cargan desde la raíz de
  // assets, no desde /block/. El resto, desde /block/ como siempre.
  const isEntity = name.includes('/');
  const base1 = isEntity ? ROOT_BASE : CDN_BASE;
  const base2 = isEntity ? ROOT_FALLBACK : FALLBACK_BASE;
  const url = base1 + name + '.png';
  const p = loadOne(url)
    .catch(() => loadOne(base2 + name + '.png'))
    .then((tex) => {
      cache.set(name, tex);
      if (onLoaded) onLoaded(tex);
      return tex;
    })
    .catch(() => {
      failed.add(name);
      cache.delete(name);
      return FALLBACK_TEXTURE;
    });
  cache.set(name, p);
  return FALLBACK_TEXTURE;
}

/** Devuelve (sincrónicamente) una textura RECORTADA de un atlas, y cuando la
 *  textura base termina de cargar llama a `onLoaded(croppedReal)` (igual patrón
 *  que getTexture). `crop` = [x, y, w, h] en píxeles sobre un atlas `atlas`
 *  (por defecto 64, como la cama). Usa offset/repeat para mostrar la sub-región. */
const cropCache = new Map();
function applyCrop(tex, crop, atlas) {
  const [x, y, w, h] = crop;
  const t = tex.clone();
  t.needsUpdate = true;
  t.magFilter = THREE.NearestFilter;
  t.minFilter = THREE.NearestFilter;
  t.colorSpace = THREE.SRGBColorSpace;
  t.generateMipmaps = false;
  t.repeat.set(w / atlas, h / atlas);
  // origen UV abajo-izquierda → invertir Y respecto al atlas (origen arriba-izq)
  t.offset.set(x / atlas, 1 - (y + h) / atlas);
  return t;
}
export function getCroppedTexture(name, crop, onLoaded, atlas = 64) {
  const key = name + '#' + crop.join(',') + '@' + atlas;
  if (cropCache.has(key)) return cropCache.get(key);
  const placeholder = applyCrop(FALLBACK_TEXTURE, crop, atlas);
  cropCache.set(key, placeholder);
  getTexture(name, (loaded) => {
    const t = applyCrop(loaded, crop, atlas);
    cropCache.set(key, t);
    if (onLoaded) onLoaded(t);
  });
  return placeholder;
}

/** Synchronous lookup: returns the cached texture or FALLBACK. */
export function getCached(name) {
  const v = cache.get(name);
  if (v && !(v instanceof Promise)) return v;
  return FALLBACK_TEXTURE;
}

/** Pre-warm a list of texture names (e.g. the unique textures in a palette). */
export function preload(names) {
  return Promise.all(names.map((n) => new Promise((resolve) => {
    getTexture(n, () => resolve(n));
    // If already cached, resolve immediately
    if (cache.get(n) && !(cache.get(n) instanceof Promise)) resolve(n);
  })));
}

export { FALLBACK_TEXTURE };
