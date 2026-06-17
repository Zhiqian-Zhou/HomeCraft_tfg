"""Stage 5a-ter — composición MULTI-MASA dirigida por el DISEÑO (palanca 2).

Un edificio grande y complejo no es una caja: tiene masas secundarias (torres,
alas, cúpula, campanario…). PERO esas masas deben seguir la COHERENCIA del
edificio pedido, no ser un molde fijo. Por eso aquí NO se decide qué masas
poner: las decide el `global_designer` (LLM) en `gi["secondary_masses"]`,
coherentemente con el prompt (una catedral → campanario + cúpula; una fortaleza
→ torres; un palacio → alas; una cabaña → nada). Este módulo solo MATERIALIZA
de forma determinista y coherente lo que el diseño pidió.

Coherencia (aligner.py): cada masa se ancla SOLAPANDO el cuerpo principal
(comparte celdas → componente que toca el suelo) y se recorta al site_aabb →
nunca flota. Si `secondary_masses` está vacío/ausente → no hace nada.
"""
from __future__ import annotations

from .architecture_planner import _palette
from .evaluator import _build_voxel_map, _bare, _STRUCT_NON_SOLID

_SIZE = {"small": 0.6, "medium": 1.0, "large": 1.5}


def _palette_blocks(gi: dict):
    pal = _palette(gi.get("style", "medieval"), gi.get("category"))
    return (pal.get("primary", "minecraft:stone_bricks"),
            pal.get("accent", "minecraft:chiseled_stone_bricks"),
            pal.get("roof", "minecraft:dark_oak_planks"),
            pal.get("glass", "minecraft:glass_pane"),
            pal.get("light", "minecraft:lantern"))


_PAIR = {"left": "right", "right": "left",
         "corner-nw": "corner-ne", "corner-ne": "corner-nw",
         "corner-sw": "corner-se", "corner-se": "corner-sw"}


def _symmetrize(masses: list) -> list:
    """FIX 4: normaliza las masas para coherencia/simetría antes de construir:
    dedup por (tipo,posición); iguala el `size` de masas emparejadas (alas
    left/right, torres en esquinas opuestas) al mayor de la pareja."""
    seen = set()
    clean = []
    for m in masses:
        if not isinstance(m, dict):
            continue
        key = (m.get("type"), m.get("position"))
        if key in seen:
            continue                      # dedup: misma masa repetida
        seen.add(key)
        clean.append(dict(m))
    _RANK = {"small": 0, "medium": 1, "large": 2}
    by_key = {(m.get("type"), m.get("position")): m for m in clean}
    for m in clean:
        pos = (m.get("position") or "").lower()
        partner = by_key.get((m.get("type"), _PAIR.get(pos)))
        if partner:                       # pareja → igualar al tamaño mayor
            big = max(m.get("size", "medium"), partner.get("size", "medium"),
                      key=lambda s: _RANK.get(s, 1))
            m["size"] = partner["size"] = big
    return clean


def add_masses(doc: dict, global_intent: dict, *, log=None) -> tuple[dict, dict]:
    """Materializa gi['secondary_masses']. Devuelve (doc, counts)."""
    counts = {"masses_built": 0, "voxels": 0, "by_type": {}}
    masses = global_intent.get("secondary_masses") or []
    if not isinstance(masses, list) or not masses:
        return doc, counts
    masses = _symmetrize(masses)          # FIX 4                      # diseño no pidió masas → nada

    vmap = _build_voxel_map(doc)
    if not vmap:
        return doc, counts
    solid = {c for c, b in vmap.items() if _bare(b) not in _STRUCT_NON_SOLID}
    if not solid:
        return doc, counts

    bb = global_intent.get("building_aabb") or [0, 0, 0, 1, 1, 1]
    bx0, by0, bz0, bx1, by1, bz1 = bb
    site = global_intent.get("site_aabb") or bb
    sx0, _sy0, sz0, sx1, _sy1, sz1 = site
    wall_top = max((y for (x, y, z) in solid
                    if bx0 <= x < bx1 and bz0 <= z < bz1), default=by1 - 1)
    fp_w, fp_d = bx1 - bx0, bz1 - bz0
    primary, accent, roof, glass, light = _palette_blocks(global_intent)
    final = dict(vmap)

    def _set(x, y, z, b):
        if sx0 <= x < sx1 and sz0 <= z < sz1 and y >= by0:
            final[(x, y, z)] = b
            counts["voxels"] += 1

    def _anchor_xz(position: str, t: int):
        """(x0,z0) de una masa de lado t según la posición pedida, solapando el
        cuerpo (anclaje)."""
        p = (position or "").lower()
        cx, cz = (bx0 + bx1) // 2 - t // 2, (bz0 + bz1) // 2 - t // 2
        west, east = bx0 - 1, bx1 - t + 1
        north, south = bz0 - 1, bz1 - t + 1
        return {
            "corner-nw": (west, north), "corner-ne": (east, north),
            "corner-sw": (west, south), "corner-se": (east, south),
            "center": (cx, cz), "centre": (cx, cz),
            "front": (cx, north), "back": (cx, south),
            "left": (west, cz), "right": (east, cz),
            "flanking-entrance": (cx, north),
        }.get(p, (cx, cz))

    def _vertical_mass(x0, z0, t, height, *, taper_roof=True, belfry=False):
        """Cascarón hueco (torre/campanario/torreón) con ventanas + cubierta."""
        x1, z1 = x0 + t, z0 + t
        for y in range(by0, height + 1):
            band = accent if (y - by0) % 4 == 3 else primary
            for x in range(x0, x1):
                for z in range(z0, z1):
                    if x in (x0, x1 - 1) or z in (z0, z1 - 1):
                        win = ((belfry and y > height - 3) or (y - by0) % 4 == 2) \
                            and (x + z) % 2 == 0 and by0 + 2 < y < height
                        _set(x, y, z, glass if win else band)
        # almenas
        for x in range(x0, x1):
            for z in range(z0, z1):
                if (x in (x0, x1 - 1) or z in (z0, z1 - 1)) and (x + z) % 2 == 0:
                    _set(x, height + 1, z, accent)
        if taper_roof:
            cx0, cz0, cx1, cz1, ry = x0, z0, x1, z1, height + 1
            while cx1 - cx0 >= 1 and cz1 - cz0 >= 1:
                for x in range(cx0, cx1):
                    for z in range(cz0, cz1):
                        if x in (cx0, cx1 - 1) or z in (cz0, cz1 - 1):
                            _set(x, ry, z, roof)
                cx0 += 1; cz0 += 1; cx1 -= 1; cz1 -= 1; ry += 1
            _set((x0 + x1) // 2, ry, (z0 + z1) // 2, light)

    def _dome(x0, z0, t, base_y):
        """Cúpula escalonada sobre el centro."""
        r = t // 2
        cx, cz = x0 + r, z0 + r
        for k in range(r + 1):
            rr = r - k
            for x in range(cx - rr, cx + rr + 1):
                for z in range(cz - rr, cz + rr + 1):
                    if abs(x - cx) == rr or abs(z - cz) == rr or k == r:
                        _set(x, base_y + k, z, roof if k < r else light)

    def _wing(x0, z0, w, d, height):
        """Ala/anexo: caja baja (muros+suelo+cubierta a un agua) anclada a un lado."""
        x1, z1 = x0 + w, z0 + d
        for y in range(by0, height):
            for x in range(x0, x1):
                for z in range(z0, z1):
                    if x in (x0, x1 - 1) or z in (z0, z1 - 1) or y == by0:
                        _set(x, y, z, primary)
                    if y > by0 + 1 and (x in (x0, x1 - 1) or z in (z0, z1 - 1)) \
                            and (x + z) % 3 == 0 and by0 < y < height - 1:
                        _set(x, y, z, glass)
        for x in range(x0, x1):                       # techo plano con cornisa
            for z in range(z0, z1):
                _set(x, height, z, roof)

    for m in masses:
        if not isinstance(m, dict):
            continue
        mtype = (m.get("type") or "tower").lower()
        pos = m.get("position") or "corner-ne"
        scale = _SIZE.get((m.get("size") or "medium").lower(), 1.0)
        bh = max(4, wall_top - by0)

        if mtype in ("tower", "keep", "turret"):
            t = max(3, int((9 if mtype == "keep" else 5) * scale))
            t = min(t, max(3, min(fp_w, fp_d) // 2))
            x0, z0 = _anchor_xz(pos, t)
            _vertical_mass(x0, z0, t, wall_top + int(bh * (0.7 if mtype == "keep" else 0.5)))
        elif mtype in ("campanile", "bell_tower", "belltower", "minaret"):
            t = max(3, int(4 * scale))
            x0, z0 = _anchor_xz(pos, t)
            _vertical_mass(x0, z0, t, wall_top + int(bh * 1.1), belfry=True)
        elif mtype in ("spire", "pinnacle"):
            t = max(3, int(3 * scale))
            x0, z0 = _anchor_xz(pos, t)
            _vertical_mass(x0, z0, t, wall_top + int(bh * 0.3))
        elif mtype in ("dome", "cupola", "rotunda"):
            t = max(5, int(min(fp_w, fp_d) * 0.4 * scale))
            x0, z0 = _anchor_xz("center", t)
            _dome(x0, z0, t, wall_top + 1)
        elif mtype in ("wing", "annex", "pavilion", "transept"):
            w = max(5, int(fp_w * 0.4 * scale)); d = max(5, int(6 * scale))
            x0, z0 = _anchor_xz(pos, max(w, d))
            _wing(x0, z0, w, d, by0 + max(5, bh // 2))
        else:
            continue
        counts["masses_built"] += 1
        counts["by_type"][mtype] = counts["by_type"].get(mtype, 0) + 1

    if counts["voxels"] == 0:
        return doc, counts
    blocks = sorted(set(final.values()))
    idx = {b: i for i, b in enumerate(blocks)}
    doc["block_palette"] = {str(i): b for b, i in idx.items()}
    doc["voxels"] = [[x, y, z, idx[b]] for (x, y, z), b in final.items()]
    xs = [c[0] for c in final]; ys = [c[1] for c in final]; zs = [c[2] for c in final]
    doc["bounding_box"]["size"] = [max(xs) + 1, max(ys) + 1, max(zs) + 1]
    if log:
        log(f"       massing: {counts['masses_built']} masas {counts['by_type']} "
            f"(+{counts['voxels']} voxels)")
    return doc, counts
