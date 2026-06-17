"""Cierre de envolvente GUIADO POR EL DISEÑO (no a ciegas).

Algunas casas salen con tramos de muro exterior faltantes (el muro se planeó
pero no se materializó en la composición). Este pase los cierra — pero SOLO los
fallos reales, nunca aberturas intencionadas:

  - Usa el PLAN DE MUROS del master_plan (ops `fill_hollow` = "aquí va muro").
  - Rellena una celda solo si: (a) es muro de PERÍMETRO planeado, (b) es
    EXTERIOR (su vecino hacia afuera no pertenece a ninguna sala), (c) está en
    AIRE ahora (el muro planeado no salió), (d) NO es celda de puerta.
  - Las VENTANAS son cristal (no aire) → no se tocan. Las PUERTAS se saltan.
  - Estructuras ABIERTAS por diseño (pabellón/logia sin `fill_hollow` ahí, o
    patios) → no tienen muro planeado → no se cierran. El gate es inherente.

Anclado al cascarón → 0 flotantes. Mismo patrón que physical_fixer.
"""
from __future__ import annotations

from .architecture_planner import _palette
from .evaluator import (_build_voxel_map, _bare, _STRUCT_NON_SOLID,
                        planned_exterior_walls)


def close(doc: dict, *, master_plan: dict, global_intent: dict | None = None,
          door_cells: frozenset = frozenset(), log=None) -> tuple[dict, dict]:
    """Cierra huecos de fallo en muros exteriores planeados. (doc, report)."""
    report = {"planned": 0, "closed": 0}
    walls = planned_exterior_walls(master_plan)
    if not walls:
        return doc, report                # nada planeado (estructura abierta)
    vmap = _build_voxel_map(doc)
    solid = {c for c, b in vmap.items() if _bare(b) not in _STRUCT_NON_SOLID}
    style = (global_intent or {}).get("style") or master_plan.get("style", "medieval")
    wall_block = _palette(style, (global_intent or {}).get("category")).get(
        "primary", "minecraft:stone_bricks")
    report["planned"] = len(walls)
    new = []
    for c in walls:
        if c in solid:                    # ya hay muro/cristal → ok
            continue
        if c in door_cells:               # abertura de puerta → respetar
            continue
        new.append([c[0], c[1], c[2], wall_block])
        report["closed"] += 1
    if not new:
        return doc, report
    # Reconstruir paleta + voxels añadiendo los muros restaurados.
    final = dict(vmap)
    for c in walls:
        if c not in solid and c not in door_cells:
            final[(c[0], c[1], c[2])] = wall_block
    blocks = sorted(set(final.values()))
    idx = {b: i for i, b in enumerate(blocks)}
    doc["block_palette"] = {str(i): b for b, i in idx.items()}
    doc["voxels"] = [[x, y, z, idx[b]] for (x, y, z), b in final.items()]
    if log:
        log(f"       envelope_closer: cerrados {report['closed']} de "
            f"{report['planned']} muros exteriores planeados")
    return doc, report
