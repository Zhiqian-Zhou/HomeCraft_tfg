// Block-shape registry.
//
// Each block family (doors, plants, stairs, slabs, fences, …) lives in its
// own file under viewer/js/blocks/ and calls `register(matchFn, handler)`
// at module load time. The renderer asks `resolve(name, props)` for the
// handler that should produce geometry + per-face textures + rotation for
// a given block_id (already split into name and parsed blockstate props).
//
// Handler shape:
//   {
//     geometry(name, props): THREE.BufferGeometry,
//     faces(name, props):    { up, down, north, south, east, west } texture-name map,
//     rotation(name, props): { x, y, z } in radians, or null,
//     transparent(name, props): boolean,
//     tint(name, props):     hex color or null,
//   }
//
// Resolution: handlers are checked in registration order; the FIRST whose
// matchFn(name, props) returns true wins. If none match, the
// DEFAULT_HANDLER (set via setDefault by cubes.js) is returned, which
// reproduces the legacy behavior (BoxGeometry + faceTextures + rotationFor).

const handlers = [];
let defaultHandler = null;

/** Register a specific-family handler. Order matters: first match wins. */
export function register(matchFn, handler) {
  if (typeof matchFn !== 'function') {
    throw new Error('register(matchFn, handler): matchFn must be a function');
  }
  if (!handler || typeof handler.geometry !== 'function') {
    throw new Error('register(matchFn, handler): handler.geometry is required');
  }
  handlers.push({ matchFn, handler });
}

/** Install the fallback handler used when no specific handler matches. */
export function setDefault(handler) {
  defaultHandler = handler;
}

/** Return the first matching handler, or the default if none matched. */
export function resolve(name, props) {
  for (const { matchFn, handler } of handlers) {
    if (matchFn(name, props)) return handler;
  }
  if (!defaultHandler) {
    throw new Error(
      "block registry has no default handler — did you forget to import './blocks/cubes.js' before resolving?");
  }
  return defaultHandler;
}

/** Diagnostic: report how many handlers are registered (used in tests). */
export function _stats() {
  return { handlers: handlers.length, hasDefault: defaultHandler != null };
}

// NOTE: handler side-effect imports were moved to renderer.js to break a
// circular-import / TDZ bug. Each handler file imports `register` or
// `setDefault` from THIS module; if THIS module imported them back, the
// handlers would evaluate BEFORE `let defaultHandler` initialized (because
// JS hoists imports to the top of evaluation order). The handler's call to
// setDefault() / register() would then hit a Temporal Dead Zone error and
// silently break the chain, leaving the viewer with no rendered geometry.
// Solution: have the CONSUMER (renderer.js) import all handlers explicitly.
