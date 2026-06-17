"""Stage 5a-bis — molduras "always-on" deterministas (palanca A).

Añade la capa de ornamento arquitectónico que diferencia a un edificio
"elaborado" (estilo TFGv2) de una caja funcional: zócalo, cornisa/friso,
esquinales (quoins), recercado de ventanas y alero saliente. Es DETERMINISTA
— el brief ya fijó estilo y forma; aquí solo se añade detalle de superficie.

A diferencia de un emisor de ops, trabaja SOBRE EL DOC YA VOXELIZADO (como
`physical_fixer`), de modo que conoce los sólidos REALES y nunca decora el
vacío. Por eso garantiza las invariantes de coherencia (ver `aligner.py`):

  1. RECOLOR sobre muro real → 0 bloques flotantes, 0 voxels nuevos (bandas de
     color: zócalo/cornisa/quoins/recercado).
  2. ALERO: solo AÑADE un bloque en una celda de aire CARA-ADYACENTE a un muro
     exterior real → pertenece al componente 26-conectado que toca el suelo,
     así que el aligner no lo poda. Recortado al `site_aabb`.
  3. NO PISA CONECTORES — se saltan las celdas reservadas de puertas.
  4. NO INVADE EL INTERIOR — recolorea/añade solo en la superficie exterior del
     muro, nunca en el espacio transitable → no toca `vertical_clearance`.

Se ejecuta tras `physical_fixer` y antes del `aligner`, que actúa de red de
seguridad final.
"""
from __future__ import annotations

import re

from .architecture_planner import _palette
from .evaluator import _build_voxel_map, _bare, _STRUCT_NON_SOLID, _LIGHT_RX

# Bloques que NO se deben recolorear: parciales/funcionales (escaleras, losas,
# vallas, trampillas, puertas, escaleras de mano, alfombras…). Recolorearlos a
# un cubo sólido bloquearía el paso (escaleras de un staircase) o cambiaría su
# función → rompería voxel_connectivity / vertical_clearance.
_TRIM_NON_RECOLOR_RX = re.compile(
    r"(_stairs$|_slab$|_wall$|_fence$|_fence_gate$|_trapdoor$|_door$|_pane$|"
    r"iron_bars$|ladder$|_carpet$|_button$|scaffolding$|vine$|_sign$)")

_MIN_SIDE_FOR_TRIM = 6
_HORIZ = ((1, 0), (-1, 0), (0, 1), (0, -1))

# Bloques de "detalle arquitectónico" que SON CUBO COMPLETO (no dejan hueco ni
# sombrean ventanas) y que la métrica de elaboración cuenta como articulación
# de fachada: chiseled_* y *_log. (band=cornisa/friso/dintel, quoin=esquinal,
# plinth=zócalo). Por estilo para que combine.
_TRIM_DETAIL = {
    "medieval":      ("minecraft:chiseled_stone_bricks", "minecraft:stripped_oak_log", "minecraft:chiseled_stone_bricks"),
    "gothic":        ("minecraft:chiseled_stone_bricks", "minecraft:stripped_dark_oak_log", "minecraft:chiseled_stone_bricks"),
    "renaissance":   ("minecraft:chiseled_quartz_block", "minecraft:stripped_birch_log", "minecraft:chiseled_quartz_block"),
    "mediterranean": ("minecraft:chiseled_sandstone", "minecraft:stripped_jungle_log", "minecraft:cut_sandstone"),
    "modern":        ("minecraft:chiseled_quartz_block", "minecraft:smooth_stone", "minecraft:chiseled_quartz_block"),
    "minimalist":    ("minecraft:chiseled_quartz_block", "minecraft:smooth_stone", "minecraft:chiseled_quartz_block"),
    "japanese":      ("minecraft:stripped_dark_oak_log", "minecraft:stripped_dark_oak_log", "minecraft:stripped_spruce_log"),
    "chinese":       ("minecraft:chiseled_red_sandstone", "minecraft:stripped_dark_oak_log", "minecraft:chiseled_red_sandstone"),
    "fantasy":       ("minecraft:chiseled_stone_bricks", "minecraft:stripped_dark_oak_log", "minecraft:chiseled_stone_bricks"),
    "rustic":        ("minecraft:chiseled_stone_bricks", "minecraft:stripped_oak_log", "minecraft:chiseled_stone_bricks"),
}
_TRIM_DETAIL_DEFAULT = ("minecraft:chiseled_stone_bricks", "minecraft:stripped_oak_log",
                        "minecraft:chiseled_stone_bricks")


def _wall_y_range(global_intent: dict) -> tuple[int, int]:
    """(y_base, wall_top) a partir de las plantas; el tejado queda por encima
    de wall_top, así que recolorear en [y_base, wall_top) no toca el tejado."""
    floors = global_intent.get("floors") or []
    bb = global_intent.get("building_aabb") or [0, 0, 0, 1, 1, 1]
    y_base = min((int(f["y0"]) for f in floors), default=int(bb[1]))
    wall_top = max((int(f["y1"]) for f in floors), default=int(bb[4]))
    return y_base, wall_top


def decorate_doc(doc: dict, global_intent: dict, *,
                 door_cells: frozenset = frozenset(),
                 enable_eave: bool = False,
                 log=None) -> tuple[dict, dict]:
    """Decora el doc voxelizado in-place-ish y devuelve (doc, counts).

    enable_eave: el alero saliente AÑADE bloques pero proyecta sombra sobre las
    ventanas superiores → penaliza `light_coverage`/`light_on_two_sides` en el
    evaluador (medido: −0.05 composite). Desactivado por defecto: el trim queda
    como recolor de bandas (zócalo/cornisa/quoins/recercado), elaboración visual
    SIN coste de score. Actívalo solo si priorizas el aspecto sobre la métrica.
    """
    counts = {"plinth": 0, "cornice": 0, "quoin": 0, "window_trim": 0, "eave": 0}
    bb = global_intent.get("building_aabb") or [0, 0, 0, 1, 1, 1]
    if min(bb[3] - bb[0], bb[5] - bb[2]) < _MIN_SIDE_FOR_TRIM:
        return doc, counts

    vmap = _build_voxel_map(doc)
    if not vmap:
        return doc, counts

    solid = {c for c, b in vmap.items() if _bare(b) not in _STRUCT_NON_SOLID}
    glass = {c for c, b in vmap.items()
             if "glass" in _bare(b) or _bare(b) == "iron_bars"}
    # No tocar fuentes de luz (el physical_fixer añade una rejilla de linternas
    # ANTES del trim; repintarlas hundiría light_coverage).
    lights = {c for c, b in vmap.items() if _LIGHT_RX.match(_bare(b))}
    protected = glass | lights

    style = global_intent.get("style", "medieval")
    category = global_intent.get("category")
    pal = _palette(style, category)
    # Bandas con bloques de DETALLE (chiseled/log, cubo completo) → articulan la
    # fachada y la métrica los cuenta, sin huecos ni sombra.
    band_block, quoin_block, plinth_block = _TRIM_DETAIL.get(style, _TRIM_DETAIL_DEFAULT)
    sill_block = band_block
    eave_block = pal.get("roof") or band_block

    y_base, wall_top = _wall_y_range(global_intent)
    sx0, sy0, sz0, sx1, sy1, sz1 = global_intent.get("site_aabb") or bb

    def _air(c) -> bool:
        return c not in solid

    def _in_site(x, z) -> bool:
        return sx0 <= x < sx1 and sz0 <= z < sz1

    # Celdas de muro EXTERIOR en la franja [y_base, wall_top): sólidas y con al
    # menos un vecino horizontal de aire (dan a fuera).
    ext: dict[tuple, list] = {}     # cell -> lista de direcciones "afuera"
    for (x, y, z) in solid:
        if not (y_base <= y < wall_top):
            continue
        outward = [(dx, dz) for dx, dz in _HORIZ if _air((x + dx, y, z + dz))]
        if outward:
            ext[(x, y, z)] = outward

    final = dict(vmap)          # mapa de trabajo (recolor + add)

    def _recolor(cell, block, kind) -> None:
        if cell in door_cells or cell in protected:
            return                       # no tapar puertas, ventanas ni luces
        if _TRIM_NON_RECOLOR_RX.search(_bare(vmap.get(cell, ""))):
            return                       # no convertir bloques parciales/funcionales
        final[cell] = block
        counts[kind] += 1

    for (x, y, z), outward in ext.items():
        # Zócalo (hilada base) y cornisa/friso (hilada superior).
        if y == y_base:
            _recolor((x, y, z), plinth_block, "plinth")
        elif y == wall_top - 1:
            _recolor((x, y, z), band_block, "cornice")
        # Esquinales: celda con aire en dos lados perpendiculares (esquina
        # convexa), patrón vertical alterno.
        has_x = any(dx for dx, dz in outward if dx)
        has_z = any(dz for dx, dz in outward if dz)
        if has_x and has_z:
            _recolor((x, y, z), quoin_block, "quoin")

    # Recercado de ventanas: dintel (encima) y alféizar (debajo) sobre el muro.
    for (gx, gy, gz) in glass:
        above = (gx, gy + 1, gz)
        below = (gx, gy - 1, gz)
        if above in solid and y_base <= gy + 1 < wall_top:
            _recolor(above, band_block, "window_trim")
        if below in solid and y_base <= gy - 1 < wall_top:
            _recolor(below, sill_block, "window_trim")

    # Alero saliente: AÑADE un bloque en la celda de aire inmediatamente afuera
    # de cada celda de muro exterior a la altura de la cornisa. Cara-adyacente
    # al muro → anclado (el aligner lo conserva). Recortado al site.
    # OJO: sombrea ventanas → penaliza luz; off por defecto (ver docstring).
    eave_y = wall_top - 1
    for (x, y, z), outward in (ext.items() if enable_eave else []):
        if y != eave_y:
            continue
        for dx, dz in outward:
            tx, tz = x + dx, z + dz
            tgt = (tx, eave_y, tz)
            if tgt in final or tgt in door_cells or not _in_site(tx, tz):
                continue
            final[tgt] = eave_block
            counts["eave"] += 1

    # ── FIX 2: PROFUNDIDAD real de envolvente (no solo recolor plano) ──
    # Cornisa con SLAB saliente 1 bloque (cara-adyacente al muro → anclada) y
    # quoins de esquina salientes. Da relieve 3D. Se salta columnas con ventana
    # (no sombrear) y celdas de puerta. Slab fino → sombra mínima.
    counts["belt"] = 0
    counts["corner"] = 0
    win_cols = {(gx, gz) for (gx, _gy, gz) in glass}
    _SLAB = {"medieval": "minecraft:stone_brick_slab", "gothic": "minecraft:stone_brick_slab",
             "fantasy": "minecraft:stone_brick_slab", "rustic": "minecraft:oak_slab",
             "renaissance": "minecraft:smooth_quartz_slab", "modern": "minecraft:smooth_quartz_slab",
             "minimalist": "minecraft:smooth_quartz_slab", "mediterranean": "minecraft:sandstone_slab",
             "japanese": "minecraft:spruce_slab", "chinese": "minecraft:red_sandstone_slab"}
    slab = _SLAB.get(style, "minecraft:stone_brick_slab") + "[type=top]"
    cornice_y = wall_top - 1
    for (x, y, z), outward in ext.items():
        if y != cornice_y:
            continue
        n_air = len(outward)
        for dx, dz in outward:
            tx, tz = x + dx, z + dz
            tgt = (tx, cornice_y, tz)
            if tgt in final or tgt in door_cells or not _in_site(tx, tz):
                continue
            if (x, z) in win_cols:           # no sobre columnas de ventana
                continue
            if n_air >= 2:                   # esquina convexa → quoin saliente sólido
                final[tgt] = band_block
                counts["corner"] += 1
            else:                            # tramo recto → cornisa de slab
                final[tgt] = slab
                counts["belt"] += 1

    if sum(counts.values()) == 0:
        return doc, counts

    # Reconstruir voxels + paleta (aire ya excluido por construcción).
    blocks = sorted(set(final.values()))
    idx_of = {b: i for i, b in enumerate(blocks)}
    doc["block_palette"] = {str(i): b for b, i in idx_of.items()}
    doc["voxels"] = [[x, y, z, idx_of[b]] for (x, y, z), b in final.items()]
    sz = doc.get("bounding_box", {}).get("size")
    if sz and counts["eave"]:
        xs = [c[0] for c in final]; ys = [c[1] for c in final]; zs = [c[2] for c in final]
        doc["bounding_box"]["size"] = [max(xs) + 1, max(ys) + 1, max(zs) + 1]

    if log:
        log(f"       trim: {sum(counts.values())} celdas "
            f"(zócalo={counts['plinth']} cornisa={counts['cornice']} "
            f"quoins={counts['quoin']} ventanas={counts['window_trim']} "
            f"alero={counts['eave']})")
    return doc, counts
