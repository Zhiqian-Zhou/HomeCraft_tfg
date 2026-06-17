"""Amueblado garantizado por rol (FIX C).

Problema observado: dormitorios SIN cama (el LLM a veces elige una skill de
decoración como base, o el mueble se pierde en la composición). Esta pasada,
DETERMINISTA y TARDÍA (tras trim/massing, antes del aligner), garantiza que
cada sala tenga el mueble CLAVE de su rol: dormitorio→cama, cocina→horno,
baño→caldero, biblioteca/estudio→estantería, despensa→barril.

Solo AÑADE el mueble si falta, en un punto interior seguro (sobre el suelo,
pegado a un muro, sin pisar puerta/ventana ni el centro de paso). Al correr
tarde, sobrevive a la composición; sobre el suelo → no es flotante.
"""
from __future__ import annotations

import re

from .evaluator import (_build_voxel_map, _bare, _STRUCT_NON_SOLID,
                        _ROLE_REQUIRED_FURNITURE as _REQUIRED)
from pipeline.skills.base import Materials

# Bloques "blandos" sobre los que SÍ se puede colocar un mueble (la alfombra/
# planta se reemplaza): aire + decoración de suelo. No incluye muros/muebles.
_SOFT_RX = re.compile(r"carpet|flower|sapling|grass$|fern|snow|moss|^air$|leaves")


def _is_soft(b: str) -> bool:
    bb = _bare(b)
    return bb in _STRUCT_NON_SOLID or bool(_SOFT_RX.search(bb))


def _role(s: str) -> str:
    return (s or "").strip().lower().replace("-", "_")


def _orientations_for(role: str, mats: Materials) -> list[list]:
    """Orientaciones candidatas del mueble clave del rol. Cada orientación es
    una lista de (dx, dz, block). Para la cama devolvemos DOS orientaciones (a
    lo largo de Z y de X) → cabe también en salas estrechas (la elige el bucle
    según qué eje tiene hueco). El resto son muebles de 1 celda (1 orientación)."""
    if role in ("bedroom", "nursery"):
        bed = mats.bed                                   # p.ej. red_bed/white_bed
        return [
            [(0, 0, f"{bed}[part=foot,facing=south]"),   # a lo largo de +Z
             (0, 1, f"{bed}[part=head,facing=south]")],
            [(0, 0, f"{bed}[part=foot,facing=east]"),    # a lo largo de +X
             (1, 0, f"{bed}[part=head,facing=east]")],
        ]
    if role == "kitchen":
        return [[(0, 0, "minecraft:furnace[facing=south]")]]
    if role == "bathroom":
        return [[(0, 0, "minecraft:cauldron")]]
    if role in ("library", "study"):
        return [[(0, 0, "minecraft:bookshelf")]]
    if role == "pantry":
        return [[(0, 0, "minecraft:barrel")]]
    return []


def furnish(doc: dict, *, style: str = "medieval",
            door_cells: frozenset = frozenset(), log=None) -> tuple[dict, dict]:
    """Garantiza el mueble clave por rol. Devuelve (doc, report)."""
    report = {"checked": 0, "placed": 0, "by_role": {}}
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    if not storeys:
        return doc, report
    vmap = _build_voxel_map(doc)
    solid = {c for c, b in vmap.items() if _bare(b) not in _STRUCT_NON_SOLID}
    mats = Materials.for_style(style)
    final = dict(vmap)
    additions = []

    def _has_required(aabb, fams):
        x0, y0, z0, x1, y1, z1 = aabb
        for (cx, cy, cz), b in vmap.items():
            if x0 <= cx < x1 and y0 <= cy < y1 and z0 <= cz < z1:
                if any(f in _bare(b) for f in fams):
                    return True
        return False

    def _placeable(c):
        """Se puede poner mueble: no es puerta, y la celda está vacía o es
        decoración blanda (alfombra/planta → la reemplaza)."""
        if c in door_cells:
            return False
        b = final.get(c)
        return b is None or _is_soft(b)

    for st in storeys:
        for sp in st.get("spaces") or []:
            role = _role(sp.get("function"))
            fams = _REQUIRED.get(role)
            a = sp.get("aabb")
            if not fams or not (isinstance(a, list) and len(a) == 6):
                continue
            report["checked"] += 1
            if _has_required(a, fams):
                continue                       # ya amueblado → nada
            x0, y0, z0, x1, y1, z1 = (int(v) for v in a)
            orientations = _orientations_for(role, mats)
            # Para que quepa un mueble de 1-2 celdas hace falta interior ≥1 en
            # ambos ejes y ≥2 en el eje largo del mueble. Salas tipo pasillo
            # (p.ej. 17×3) caben con la cama orientada a lo largo del lado largo.
            if not orientations or x1 - x0 < 3 or z1 - z0 < 3:
                continue
            fy = y0 + 1                          # sobre el suelo
            placed_here = False
            for piece in orientations:
                ext_x = max(dx for dx, _dz, _b in piece) + 1   # ancho del mueble en X
                ext_z = max(dz for _dx, dz, _b in piece) + 1   # fondo del mueble en Z
                # anclas INTERIORES (nunca el perímetro), pegadas a cada muro,
                # respetando la extensión del mueble en cada eje.
                xs = range(x0 + 1, x1 - ext_x)       # ax tal que ax..ax+ext_x-1 ≤ x1-2
                zs = range(z0 + 1, z1 - ext_z)
                anchors = ([(x0 + 1, az) for az in zs]
                           + [(x1 - 1 - ext_x, az) for az in zs]
                           + [(ax, z0 + 1) for ax in xs]
                           + [(ax, z1 - 1 - ext_z) for ax in xs])
                anchors = [(ax, az) for (ax, az) in anchors
                           if x0 + 1 <= ax and ax + ext_x - 1 <= x1 - 2
                           and z0 + 1 <= az and az + ext_z - 1 <= z1 - 2]
                cells_of = lambda ax, az: [(ax + dx, fy, az + dz) for dx, dz, _b in piece]
                # 1ª pasada: hueco libre (aire/decoración blanda).
                anchor = next((an for an in anchors
                               if all(_placeable(c) for c in cells_of(*an))), None)
                # 2ª pasada (asertiva): interior no-puerta — SOBREESCRIBE lo que
                # haya (la cama tiene prioridad sobre un cofre en sala diminuta).
                if anchor is None:
                    anchor = next((an for an in anchors
                                   if all(c not in door_cells for c in cells_of(*an))), None)
                if anchor is not None:
                    for (dx, dz, b) in piece:
                        final[(anchor[0] + dx, fy, anchor[1] + dz)] = b
                    report["placed"] += 1
                    report["by_role"][role] = report["by_role"].get(role, 0) + 1
                    placed_here = True
                    break       # mueble colocado en esta sala → siguiente sala

    if report["placed"] == 0:
        return doc, report
    blocks = sorted(set(final.values()))
    idx = {b: i for i, b in enumerate(blocks)}
    doc["block_palette"] = {str(i): b for b, i in idx.items()}
    doc["voxels"] = [[x, y, z, idx[b]] for (x, y, z), b in final.items()]
    if log:
        log(f"       furnish: colocados {report['placed']} muebles clave "
            f"faltantes {report['by_role']}")
    return doc, report
