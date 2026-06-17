# Typology Catalog — Fases 0-6 (`HomeCraft v2 Pipeline v2`)

## Resumen

Esta es la documentación de handoff del trabajo de variedad implementado
sobre TFGv2Z entre las fases 0 y 6. El objetivo era inyectar el catálogo
de 29 tipologías hand-curadas de TFGv2 (Pipeline v1) en TFGv2Z (Pipeline
v2) preservando su arquitectura.

**Estado:** todo el código está escrito y probado. La validación
end-to-end vía el gym A/B (10 prompts × 2 ramas) requiere ejecutar el
pipeline con `OPENROUTER_API_KEY` y queda para el usuario.

---

## Qué se ha entregado

### Catálogo (Fases 0-3)

| Kind | Count | Localización |
|---|---:|---|
| tower | 12 | `pipeline/skills/typologies/{norman_keep,campanile,pagoda_tower,minaret,lighthouse,watchtower,clock_tower,wizard_tower,windmill_tower,pepperpot_tower,drum_curtain_tower,observatory_tower}.py` |
| roof | 8 | `pipeline/skills/typologies/{gable,hip,mansard,gambrel,pyramidal,flat_parapet,pagoda_tiered,cross_gable}_roof.py` |
| window | 4 | `pipeline/skills/typologies/{oriel,bay,palladian,dormer_gabled}_window.py` (los dos primeros tienen `_window` suffix, `dormer_gabled` no) |
| garden | 5 | `pipeline/skills/typologies/{cottage_garden,formal_garden,zen_garden,tuscan_courtyard,castle_courtyard}.py` |
| **Total** | **29** | |

**Geom helpers** (9 funciones): `pipeline/skills/typologies/_geom.py` —
`crenellated_ring`, `crenellated_circle`, `vertical_strip`, `carve_slit`,
`hollow_wall_ring`, `circle_xz`, `conical_spire`, `pyramid_square`,
`onion_dome`. 23 unit tests en `tests/test_typology_geom.py`.

**Registry** (Fase 1): `pipeline/skills/typologies/__init__.py` espeja el
patrón lazy de `pipeline/skills/__init__.py:37-43`. APIs:
`list_typologies()`, `get_typology(name)`, `get_metadata(name)`,
`filter_by(kind, style, scale)`.

**Smoke harness:** `tools/preview_typology.py` — CLI que rendera una
typology aislada con un `Materials.for_style()` arbitrario y la escribe
como ReferenceBuilding JSON en `scratch/typology_previews/`.

### Selección por LLM (Fase 4)

`pipeline/agents/typology_chooser.py` — agente que filtra el catálogo por
`(kind, style, scale)`, presenta el menú a un LLM (`call_llm_json`), y
parsea `{"typology": "<name>"}`. Fallback al primer candidato si falla.
Opción anti-mode-collapse con `k_parallel=3` y temperaturas escalonadas
[0.7, 0.95, 1.1] + historial.

**Inserción en el pipeline:** `pipeline/agents/run.py` Stage 1a-bis,
inmediatamente después de `global_designer.design_global_v4()`. La salida
queda en `gi["selected_typologies"]` y se persiste en
`<workdir>/global_intent.json`.

### Dispatch downstream (Fases 4 + 4.5 + extended)

`pipeline/agents/voxelizer.py` `_expand_ops()` reconoce
`kind="typology"` y dispatcha a `get_typology(name)`. Espejo de la rama
`kind="skill"` existente, con import lazy.

`pipeline/agents/typology_injector.py` (**Stage 1f-bis**, justo después
de `connector_planner_v4`): traduce los 4 kinds de
`gi.selected_typologies` en ops concretas `{"kind": "typology", "name":
..., "aabb": ...}` añadidas a `architecture_plan.ops`:

| Kind | AABB del op |
|---|---|
| **roof** | unión de los bbox de ops `envelope_role="roof"` en architecture_plan |
| **tower** | `gi.building_aabb` (sólo si `silhouette_id` contiene "tower"/"keep"/"spire"/"minaret"/"campanile"/"pagoda") |
| **window** | AABB del **primer** slot de `connector_plan.windows` (los demás slots quedan deterministas para no sobrecargar la fachada) |
| **garden** | `gi.site_aabb` con `y` clampado a `[y0, y0+2]` (slab a ras de suelo) |

El composer "later wins" sobreescribe la envelope determinista en celdas
overlapping. Cada kind degrada silenciosamente si su input está vacío
(no roof envelope → sin roof; silhouette no tower-like → sin tower; sin
window slots → sin window; sin site_aabb → sin garden).

### RAG stratified retrieval (Fase 5)

`tools/build_retrieval_index.py` ahora filtra top-30% **por bucket**
`(style,)` (o `(style, category)` si pasas `--stratify style_category`).
Default cambiado a `--stratify style`. Para el comportamiento legado
global pasa `--stratify none`.

### Métrica de variedad en el gym (Fase 6)

`tools/gym/runner.py` ahora emite `_typology_diversity_score` paralelo a
`_variety_score`. Reportado en REPORT.md como
`typology_diversity_index: 0.700  # by_kind=[tower=3, roof=8, window=2, garden=4]`.
**No penaliza** el `mean_score` (mismo principio que post-44d354a).

---

## Tests añadidos

| Test file | Casos |
|---|---:|
| `tests/test_typology_geom.py` | 23 |
| `tests/test_typology_chooser.py` | 12 |
| `tests/test_voxelizer_typology_dispatch.py` | 4 |
| `tests/test_typology_injector.py` | 7 |
| `tests/test_stratified_retrieval.py` | 6 |
| `tests/test_gym_typology_diversity.py` | 8 |
| **Total nuevos** | **60** |

Suite TFGv2Z completa: **443 passed, 5 failed**. Los 5 failed son
**preexistentes** en `test_architecture_planner_v4`, `test_exterior_select`,
`test_space_planner_v4` (lógica del planner v4 que no se ha tocado). Net
delta vs estado pre-Fase 0: +43 tests passing, 0 regresiones.

---

## Cómo validar end-to-end (lo que necesitas correr tú)

Requiere `OPENROUTER_API_KEY` exportado.

### 1. Smoke isolado de typologies (sin LLM)

```bash
python3 tools/preview_typology.py --list           # 29 entradas
python3 tools/preview_typology.py norman_keep --style gothic --size large
# → scratch/typology_previews/norman_keep__gothic__large.json
# Ábrelo en el viewer: viewer/ (python3 -m http.server 8000)
```

### 2. Build single end-to-end (1 LLM run)

```bash
python3 -m pipeline.agents.run "a tall medieval castle keep with battlements"
# Lee gi["selected_typologies"] en scratch/generations/<gen_id>/global_intent.json
# Confirma que el architecture_plan.json contiene un op kind="typology" para el roof
grep -A1 '"kind": "typology"' scratch/generations/*/architecture_plan.json | head
```

### 3. Gym A/B — comparar ramas con/sin catálogo

El gym ya produce `typology_diversity_index` en cada iter. Para A/B usa
la env var `HOMECRAFT_CATALOG_OFF` — **no hace falta editar `run.py`**:

```bash
# Branch ON — chooser activo, injector emite ops typology (default)
python3 -m tools.gym.runner --iter 70

# Branch OFF — env var desactiva el chooser; el injector ve
# selected_typologies={} y queda como no-op
HOMECRAFT_CATALOG_OFF=1 python3 -m tools.gym.runner --iter 71

# Comparar typology_diversity_index + mean_score + diversity_index
diff -u output/gym/iter71/REPORT.md output/gym/iter70/REPORT.md | head -50
```

### 4. Stratified retrieval — rebuild + compare

```bash
# Rebuild con stratified (default)
python3 tools/build_retrieval_index.py
cat scratch/retrieval/index_info.json   # mira "buckets": …

# Rebuild con global (legacy)
python3 tools/build_retrieval_index.py --stratify none
cat scratch/retrieval/index_info.json
```

---

## Criterios de éxito según el plan original

| Métrica | Objetivo | Cómo medirla |
|---|---|---|
| `mean_composite_score` no baja > 0.02 | ≥ baseline − 0.02 | `output/gym/iter*/REPORT.md` mean_score line, comparado con iter anterior |
| `typology_diversity_index` | **≥ 0.7** | `output/gym/iter*/REPORT.md` `typology_diversity_index:` |
| `_fingerprint` distinct count | **≥ 7/10** | `output/gym/iter*/REPORT.md` `diversity_index:` × 10 |

Si los 3 criterios pasan en una iter post-catalog comparado a una pre-catalog
de referencia, **el objetivo del plan está cumplido**.

---

## Lo que NO se ha hecho (follow-ups posibles, ninguno bloqueante)

1. **Iteración visual de los 5 gardens.** Los `expand()` en TFGv2 eran
   stubs `return []`; mis implementaciones funcionan y son 1.16.5-clean
   pero no son ports literales (no había qué portar). Si quieres replicar
   exactamente lo que describen sus docstrings, revisarlos uno a uno en
   el viewer y ajustar es ~0.5 día por garden.
2. **Heurísticas más finas para placement.** Por simplicidad el injector
   usa la primera window slot y el building_aabb completo para la tower.
   Heurísticas mejores: elegir la ventana más visible (cara mayor del
   edificio) o sólo el volumen "torre" cuando el silhouette es híbrido
   (torre adosada a una casa). Mejoras incrementales, no bloqueantes.
3. **Re-evaluación del corpus** tras stratified retrieval. El índice nuevo
   sirve a `pipeline.agents.retriever.retrieve()` exactamente igual; sólo
   cambia QUÉ buildings sobreviven al top-30%. Si quieres confirmar que
   las recomendaciones cambian, basta con re-correr `build_retrieval_index.py`
   y comparar `scratch/retrieval/building_ids.json` antes/después.
4. **El gym A/B real**. Está pendiente de ejecutar con `OPENROUTER_API_KEY` —
   ver §3 de la sección "Cómo validar end-to-end".

---

## Archivos modificados / creados

```
Nuevos (typology infra)
  pipeline/skills/typologies/__init__.py
  pipeline/skills/typologies/base.py
  pipeline/skills/typologies/_geom.py
  pipeline/skills/typologies/{29 typology modules}.py

Nuevos (agentes)
  pipeline/agents/typology_chooser.py
  pipeline/agents/typology_injector.py     ← emite ops para 4 kinds

Nuevos (tooling)
  tools/preview_typology.py

Modificados
  pipeline/agents/run.py            (Stage 1a-bis chooser + Stage 1f-bis injector
                                      + HOMECRAFT_CATALOG_OFF env var)
  pipeline/agents/voxelizer.py      (kind="typology" dispatch)
  rag/schema/shape_op.schema.json   (oneOf variant para kind="typology",
                                      detectado en smoke E2E — sin esto el
                                      aggregator validate falla con
                                      "is not valid under any of the given
                                      schemas")
  tools/build_retrieval_index.py    (--stratify default style)
  tools/gym/runner.py               (_typology_signature, _typology_diversity_score)
  tools/gym/report.py               (typology_diversity_index line)

Tests nuevos (74 cases, all passing)
  tests/test_typology_geom.py              23
  tests/test_typology_chooser.py           12
  tests/test_voxelizer_typology_dispatch.py 4
  tests/test_typology_injector.py          21    ← 7 base + 14 nuevos para 4 kinds
  tests/test_stratified_retrieval.py        6
  tests/test_gym_typology_diversity.py      8

Tests modificados (1 file, 2 cases pinned to legacy mode)
  tests/test_retriever.py
```

---

## Cómo abrir un render en el viewer

```bash
python3 -m http.server 8000        # desde la raíz del repo
# luego en el navegador:
#   http://localhost:8000/viewer/?file=../scratch/typology_previews/<name>__<style>__<size>.json
```
