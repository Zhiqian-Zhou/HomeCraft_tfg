# HomeCraft — Descripción técnica del pipeline

> Sistema texto-a-edificio en espacio voxel (Minecraft como backend de
> referencia) con evaluación arquitectónica basada en Christopher
> Alexander. **Este documento describe lo que el código hace REALMENTE**
> y marca con honestidad lo que está hardcoded, simulado o pendiente.
>
> El pipeline tiene cuatro ideas clave:
>
> 1. **Schema BOT-AABB unificado**: el LLM emite el edificio como un
>    árbol BOT (W3C) donde cada elemento es una caja envolvente AABB
>    con un *kind* (`slab`, `perimeter`, `gabled_roof`, `hipped_roof`,
>    `pyramid_roof`, `conical_roof`, `flat_roof_parapet`, ...). Un
>    expander Python convierte las cajas en voxels. Evita pedirle al
>    LLM cientos de bloques uno a uno.
>
> 2. **Dos ramas de generación**: E2E (1 llamada LLM, todo el edificio
>    de golpe) y GoG (N llamadas LLM, una por sub-goal arquitectónico).
>    Ambas emiten el MISMO schema BOT-AABB.
>
> 3. **Evaluación arquitectónica con split del scorer**: 7 propiedades
>    de Alexander divididas en 4 *sólidas* (métrica primaria
>    `overall_solid`) y 3 *proxies* (métrica exploratoria
>    `overall_full`); scorer no-compensatorio (media geométrica × 10)
>    para ambas; 6 misfits físicos (errores duros) + Critic con 9
>    reglas advisory (toda la capa soft vive ya en el Critic).
>
> 4. **Citas verificables en dos niveles**: cada `Critique` lleva una
>    paráfrasis verificada por substring contra `data/apl_corpus.json`
>    y una *referencia canónica* (obra + páginas + edición + ISBN) al
>    pasaje original publicado de Alexander.

---

## 1. Siglas

| Sigla | Significado |
|---|---|
| **BOT** | Building Topology Ontology (W3C). Jerarquía Building → Storey → Space → BuildingElement. |
| **AABB** | Axis-Aligned Bounding Box. Caja envolvente alineada con los ejes. |
| **APL** | *A Pattern Language* (Alexander 1977). 253 patrones arquitectónicos. |
| **GoG** | Goal-Oriented Graph. Rama de generación con descomposición. |
| **E2E** | End-to-End. Rama de generación de una sola llamada LLM. |
| **CBR** | Case-Based Reasoning. Aquí usado como **observatorio**, no caché. |

---

## 2. Vista global

```
Prompt
  ↓
1. Imagine            (LLM)    expande el prompt + cita patrones APL
  ↓
2. DesignSpec         (LLM)    paleta + dimensiones + estilo (una vez)
  ↓
3. Generación         (LLM)    E2E (1 call) o GoG (1 planner + N generators)
  ↓
4. Repair             (Python) limpia JSON malformado
  ↓
4b. Roof heuristic    (Python) sube `flat_roof` sobre torres a pyramid/conical
  ↓
5. Validación         (Python) 6 misfits físicos (solo errores duros)
  ↓
6. Placement          (mcpi)   coloca cada bloque en Minecraft
  ↓
7. Evaluación         (Python) 7 propiedades Alexander + scorer split (solid/full)
                      (LLM)    PromptClassifier (con cache) → tags del Critic
                      (Python) Critic: 9 reglas advisory + canonical references
                      (LLM)    Explainer adaptativo (con fallback determinista)
  ↓
8. Archivo            (SQLite) CaseMemory guarda el caso si `--db PATH` está activo
```

### Conteo real de llamadas LLM

| Modo | Llamadas LLM por `pipeline.run()` |
|---|---|
| **E2E live** | 1 Imagine + 1 DesignSpec + 1 BOT-AABB + 1 PromptClassifier (cacheable) + ~5-10 Explainer = **~9-14 llamadas** |
| **GoG live** | 1 Imagine + 1 DesignSpec + 1 SubGoalPlanner + N SubGoalGenerator + 1 PromptClassifier + ~5-10 Explainer = **~9-14 + N llamadas** |
| **Dry-run** | 0 reales (`FakeLLMClient` con respuestas canned) |

*Nota: cualquier llamada LLM fallida (timeout, JSON malformado,
schema reject) cae a su fallback determinista — el pipeline nunca
aborta por un error de red en el clasificador o el explainer.*

---

## 3. Lo que falta para producción

Antes de la descripción detallada, esta es la lista honesta de lo que
**NO está completo** o usa atajos. Si la defensa del TFG necesita
algo de aquí, hay que cerrarlo antes.

### 🔴 No implementado

| Item | Descripción | Esfuerzo aproximado |
|---|---|---|
| Estudio F (E2E++) | Control de cómputo justo: un E2E que recibe los mismos tokens totales que GoG. **Decisión de scope**: excluido del TFG (la conclusión del v1 ya es metodológica). | n/a |
| Validación humana de proxies | Estudio HCI con jueces arquitectos comparando *score automático* vs *score humano*. **Scaffold preparado** en `study/`; ejecución pendiente. | Externo al código |
| Benchmark multi-LLM | Correr la batería de 30 prompts con 3-4 LLMs distintos (Gemini, Claude, GPT-4o, DeepSeek) + agregador cross-modelo (Friedman). | ~100 LOC + 4×30 min de API |
| Fine-tuning de modelo pequeño | Exportar trazas, entrenar LoRA sobre 7B, cablear adapter local. | ~1-2 semanas externas |

### 🟢 Mitigaciones aplicadas (mayo 2026)

| Item original | Mitigación |
|---|---|
| `homecraft batch` | **Implementado**: subcomando `batch` + `app/batch.py` con Wilcoxon pareado + bootstrap CI sobre `overall_solid` y `overall_full`. |
| `SqliteCaseMemory` no enchufado | **Implementado**: flag `--db PATH` cablea `SqliteCaseMemory` via `adapters/casememory/make_case_memory`. |
| `LLMExplainer` stub | **Implementado**: JSON-mode con `_ExplanationResponse` schema-lock (`extra="forbid"`) + fallback automático al `TemplateExplainer` ante cualquier error. Activo en `make_live_pipeline`. |
| `FakePromptClassifier` débil | **Mitigado**: `LLMPromptClassifier` con vocabulario ES+EN, cache SHA1 en disco, fallback al fake. Activo en `make_live_pipeline`. |
| `ConstantJudge` engañoso | **Renombrado** a `judge_placeholder_DO_NOT_USE` en `summary.json` con campo `_warning`. El FINAL SCORE de pantalla ahora usa `scores.overall_solid` (real). Reemplazo por Judge real sigue pendiente como future work. |
| 3/7 propiedades Alexander | **Mitigado**: split del scorer en `overall_solid` (4 sólidas, primario) + `overall_full` (7 con proxies, exploratorio). El TFG defiende `overall_solid` como métrica principal. |
| `data/apl_corpus.json` paráfrasis | **Mitigado**: estructura two-tier `{paraphrase, canonical{work, pages, edition, isbn}}`. Cada Critique lleva la referencia bibliográfica auditable. |
| Roof simplificado | **Mitigado**: 4 kinds nuevos (`pyramid_roof`, `hipped_roof`, `conical_roof`, `flat_roof_parapet`) + heurística post-merge que sube tejados planos sobre torres. |

### 🟡 Persisten como limitaciones declaradas

| Item | Estado | Por qué importa |
|---|---|---|
| `ConstantJudge` | Sigue devolviendo 7/7/7 — solo se ha renombrado/etiquetado. El reemplazo por `GPT4oVisionJudge` es future work. | El score real ya viene de `scores.overall_solid`; el Judge nunca fue crítico. |
| `data/apl_fewshot.json` | 3 patrones (127, 159, 180) en paráfrasis para el few-shot prompt de Imagination. | Igual que el corpus: paráfrasis por decisión legal. |

### 🟢 Lo que SÍ está implementado correctamente

- Pipeline completo de 8 fases con **452 tests automáticos**.
- Repair chain (8 reglas) tolerante a JSON malformado / typos.
- BOT-AABB schema y voxelización (`Building.voxelized()`).
- 6 misfits físicos (solo errores duros que abortan el pipeline).
- 9 reglas Critic por defecto + 1 opt-in que cubren todo lo advisory (luz, intimidad, monotonía, common areas, color chaos, espacios exteriores).
- Anti-circularidad (invoked vs detected patterns).
- Scorer no-compensatorio con split `overall_solid` (primario, 4 sólidas) + `overall_full` (exploratorio, 7) y `liveliness_profile` por cada vista.
- Side-by-side ablation con orígenes mundo distintos.
- `homecraft-place` para re-place sin LLM, con `--clear` y `--compare`.
- mypy --strict + ruff limpios.

---

## 4. Etapa 1 — Imagination

`src/homecraft/services/imagination.py`. **Real.**

- Carga `data/apl_fewshot.json` (3 patrones APL paráfrasis) como system prompt.
- El LLM expande el prompt en una descripción rica que cita patrones (`Pat. 127`, `Pat. 159`, `Pat. 180`).
- Extrae `patterns_invoked` por regex `Pat\.\s*(\d+)`.
- Reintenta una vez con system reforzado si no cita ningún patrón.

---

## 5. Etapa 2 — DesignSpec

`src/homecraft/services/style/`. **Real.**

**Qué hace**: una llamada LLM extrae un JSON con:

- `palette`: bloque Minecraft por rol (wall, floor, roof, window, door, foundation, chimney, accent).
- `dimensions`: width × depth × height_per_storey × n_storeys.
- `style` + `mood`: tags libres.
- `facing` (N/S/E/W).
- `key_features` (lista corta).

**Por qué existe**: sin esto, cada sub-goal de GoG podía elegir un
material distinto y el edificio salía incoherente (la chimenea de
piedra, los muros de madera, el tejado de ladrillo).

**Tolerancia**: si el LLM falla, devuelve un DesignSpec con defaults
sensatos (cottage medieval 7×4×9 facing S). El pipeline nunca aborta.

---

## 6. Etapa 3 — Generación (BOT-AABB unificado)

El LLM emite directamente el `Building` BOT canónico, donde cada
`BuildingElement` es un **AABB**:

```json
{
  "kind": "perimeter",
  "type": "oak_planks",
  "role": "wall",
  "bbox": [[0,0,0], [6,3,8]],
  "openings": [
    {"kind": "door", "type": "oak_door", "role": "door",
     "bbox": [[3,0,0], [3,1,0]]},
    {"kind": "window", "type": "glass_pane", "role": "window",
     "bbox": [[0,2,4], [0,2,4]]}
  ]
}
```

Un solo elemento `perimeter` con 3 openings expande a ~96 voxels al
coste de ~70 tokens de JSON. Ahorro masivo de tokens.

### Tipos (`kind`) soportados por el expander

| Categoría | Kinds | Uso típico |
|---|---|---|
| **Volúmenes** | `slab`, `perimeter`, `wall_segment`, `column`, `filled_box` | Suelos, muros, columnas |
| **Tejados** | `gabled_roof`, `hipped_roof`, `pyramid_roof`, `conical_roof`, `flat_roof`, `flat_roof_parapet` | Cottages, casonas, torres cuadradas, torres redondas, modernos, almenas |
| **Aperturas** | `door`, `window` | Vanos (van dentro de `openings`) |
| **Singletons** | `single` | Un voxel suelto |

Los 4 tipos de tejado nuevos (`hipped_roof`, `pyramid_roof`,
`conical_roof`, `flat_roof_parapet`) los conoce tanto el expander
voxel como los system prompts de E2E y GoG.

**Heurística post-merge `services/roof_heuristic.py`**: tras generar
el `Building` y antes de voxelizar, una pasada determinista detecta
elementos `flat_roof` colocados sobre spaces/storeys con palabras
"tower / torre / tour / turm" en el id y bbox cuadradilla ≤6×6, y
los sube a `pyramid_roof` (cuadrado rectangular) o `conical_roof`
(bbox exactamente cuadrado, interpretado como redondo). Es una red
de seguridad por si el LLM olvida los kinds nuevos.

### 6a. E2E (`use_gog=false`)

- 1 consulta RAG global.
- 1 llamada LLM con un ejemplo trabajado (cottage 7×4×9).
- Output: `{"bot_Building": {...}}`.

### 6b. GoG (`use_gog=true`)

Tres pasos:

| Paso | Qué hace | LLM calls |
|---|---|---|
| `SubGoalPlanner` | Lista 4-8 sub-goals (foundation, walls, openings, roof, ...) con bbox por sub-goal. | 1 |
| `SubGoalGenerator` | Por **cada** sub-goal: emite los AABBs de esa parte usando el mismo schema que E2E, scoped a un storey + space. | N |
| `BuildingMerger` | Python puro: agrupa por `storey_id`, mezcla spaces, concatena elementos, ajusta Y. | 0 |

Cada sub-goal se archiva en `gog_workspace` con prefijo ordenable
(`01_foundation`, `02_exterior_walls`, ...) para reproducibilidad.

---

## 7. Etapa 4 — Repair + Etapa 5 — Validación

### Repair (`services/repair.py`)

Un limpiador de texto crudo (`DEFAULT_CLEANER_TYPES` = `StripLLMArtefactsRule`)
seguido de **8 reglas estructurales** (`DEFAULT_RULE_TYPES`) que limpian
el JSON malformado del LLM, en este orden:

0. *(cleaner)* Quita ` ```json ` y prosa — `StripLLMArtefactsRule`.
1. Desenvuelve `bot_Building` — `UnwrapBuildingRule`.
2. Rellena `name` si falta — `FillMissingNameRule`.
3. Rellena `bot_hasStorey` si falta — `FillMissingStoreyListRule`.
4. Descarta strings donde deberían ir dicts — `DropMalformedNestedRule`.
5. Convierte floats a ints en coordenadas + bbox — `CoerceIntCoordsRule`.
6. Normaliza roles libres (`window_west` → `window`) — `FillElementRoleRule`.
7. Aplica alias de materiales (`cobblestones` → `cobblestone`) — `NormaliseMaterialAliasesRule`.
8. Tira claves desconocidas en top-level — `DropUnknownTopLevelKeysRule`.

Walks recursivamente sobre `openings`, que es la pieza clave para el
schema AABB con cutouts.

### Validación (`services/misfits/`)

**Solo 6 misfits físicos.** Tras el refactor de mayo 2026 ("el Critic
absorbe la capa soft"), todo lo que era advisory soft (luz, intimidad,
monotonía, common areas, color chaos, espacios exteriores) se ha
movido al Critic. Validación se queda con solo errores duros que
abortan el pipeline.

Cada misfit lleva `cited_source` y `quote` (≤200 chars). El
`JustificationVerifier` comprueba match NFKC-substring contra el campo
`paraphrase` de la entrada correspondiente en `data/apl_corpus.json`
(estructura two-tier `{paraphrase, canonical}` desde mayo 2026; el
verifier también acepta la forma plana `{key: str}` por
back-compat). Si la cita no está en el corpus, el misfit se descarta
con un warning.

Las 6 reglas físicas (todas severity=ERROR, todas tag=physical_misfit):

| Regla | Cita | Detecta |
|---|---|---|
| `GravityViolation` | Alexander1964.Ch5 | bloques afectados por gravedad sin soporte |
| `OutOfBounds` | Alexander1964.Ch5 | coordenadas fuera del mundo |
| `FloatingArena` | Alexander1964.Ch5 | componentes desconectados del storey |
| `DuplicateCoords` | Alexander1964.Ch5 | dos elementos en el mismo (x,y,z) |
| `StoreyContinuityViolation` | Alexander1964.Ch5 | `base_y_level` no estrictamente creciente |
| `MaterialNotInPrompt` | Alexander1964.Ch6 | materiales del BOT que no se mencionaron en el prompt |

`MisfitChecker` implementa el Protocol `Validator`, por lo que es el
ÚNICO validador inyectado en el pipeline.

---

## 8. Etapa 6 — Placement

`src/homecraft/adapters/mc/mcpi_placer.py`. **Real.**

- Socket-probe a `localhost:4711` antes del handshake; si falla,
  devuelve `placed=0` sin abortar.
- Itera `building.all_voxels()` (no `all_elements()`) — el AABB ya
  está expandido a voxels individuales.
- 10+ materiales mapeados a IDs Minecraft 1.12 legacy.
- Circuit breaker: ≥5 errores de socket consecutivos → aborta.
- **Implementa `WorldCleaner`**: método `clear_building(building,
  padding=2)` que pone toda la región a aire con una sola llamada
  `mc.setBlocks(...)`. Usado por `homecraft-place --clear`.

---

## 9. Etapa 7 — Evaluación

### 9.1 FeatureExtractor — 7 propiedades de Alexander

El extractor calcula las 7 propiedades pero el código las clasifica
explícitamente en dos grupos disjuntos. Esa clasificación es la que el
scorer usa para producir los dos agregados (`overall_solid` y
`overall_full`; ver §9.2).

**Sólidas (4 — `services/features/properties.py:SOLID_KEYS`)**:
- `levels_of_scale`: buckets log2 de volúmenes de Space, ratio en [1.5, 4].
- `alternating_repetition`: autocorrelación 1D sobre proyecciones X/Z.
- `positive_space`: solidity (huella / convex_hull).
- `local_symmetries`: espejo X/Z por Space con tolerancia ±1.

**Proxies (3 — `services/features/proxies_advanced.py:PROXY_KEYS`)**:
Las docstrings los marcan literalmente como *"PROXIES APROXIMADOS — NO
medidas canónicas, hiperparámetros sujetos a validación empírica"*.
Solo entran en el agregado exploratorio `overall_full`.
- `strong_centers`: combinación lineal ad-hoc 0.4·simetría + 0.3·enclosure + 0.3·densidad.
- `deep_interlock`: proporción de pares con bbox XZ solapadas. Ignora Y.
- `simplicity_inner_calm`: `1 - entropy(palette)/log2(N)`. **Penaliza paletas variadas**.

**PatternMatcher**: 4 detectores heurísticos sobre la geometría
(Pat.127, 129, 159, 180). Confianza baja, signature sin
`patterns_invoked` (anti-circularidad por construcción).

### 9.2 Scorer no-compensatorio (con split sólido / exploratorio)

Tras el refactor de mayo 2026, el `NonCompensatoryScorer` calcula **dos
agregados en paralelo**, uno sobre las 4 propiedades sólidas y otro
sobre las 7. La aritmética es la misma — la media geométrica × 10
(esto es la *raíz n-ésima* del producto, no el producto directo) —
y se llama "no-compensatoria" porque cualquier propiedad a 0 colapsa
el agregado a 0 (sin compensación entre ellas):

```python
# Sobre las 4 sólidas (primario):
overall_solid            = geom_mean(solid_4_scores) × 10
liveliness_profile_solid = min(solid_4_scores) × 10

# Sobre las 7 (exploratorio):
overall_full             = geom_mean(full_7_scores) × 10
liveliness_profile_full  = min(full_7_scores) × 10

# Aliases retro-compat:
overall            = overall_solid
liveliness_profile = liveliness_profile_solid
```

**Por qué dos agregados**: las 3 propiedades proxy están explícitamente
disclaimadas en sus docstrings como "NO medidas canónicas, pendientes de
validación empírica". Mezclarlas con las 4 sólidas en un único score
contamina la métrica primaria. El TFG defiende `overall_solid` como
métrica defendible y reporta `overall_full` como exploratoria a la
espera del estudio HCI (`study/`).

**Consumidores del agregado**:

| Lugar | Métrica que consume | Por qué |
|---|---|---|
| `format.py` "FINAL SCORE" + barras de progreso | `overall_solid` | Métrica primaria visible al usuario |
| `summary.json` del run individual | emite los 6 campos (`overall`, `overall_solid`, `overall_full`, `liveliness_profile`, `liveliness_profile_full`, `by_property`) | Reproducibilidad |
| `homecraft batch` Wilcoxon "primary" / "exploratory" | `overall_solid` (primary) + `overall_full` (exploratory) | Cross-check |
| `CaseSimilarityRule._best_gap` (Critic) | `overall_full` | Las 7 propiedades dan rankings más estables entre runs |
| `CaseMemory.retrieve()` (sqlite + in-memory) | `overall_full` con `overall_solid` como tie-break | Coincide con el contrato de la regla |

### 9.3 CaseMemory

- `InMemoryCaseMemory` (default si no se pasa `--db`). Se pierde al cerrar.
- `SqliteCaseMemory` (**activado via `--db PATH`**). Persistencia entre
  invocaciones, índice en `score_overall_full` para retrieval rápido.
- `retrieve` desactivado por defecto (anti-contaminación cross-run).

### 9.4 Critic

`RuleBasedCritic` produce un `Critique` por cada problema detectado.
NO modifica el `Building` — solo emite recomendaciones con cita. Tras
el refactor de mayo 2026 absorbió toda la evaluación advisory que
antes vivía en `services/misfits/`.

**9 reglas por defecto + 1 opt-in**:

| # | Regla | Qué detecta | Cita |
|---|---|---|---|
| 1 | `WeakStrongCenterRule` | `strong_centers < 0.5` en edificios monumentales | NoO.Prop.2 |
| 2 | `PoorLevelsOfScaleRule` | menos de 2 escalas distintas de bbox en los centros | NoO.Prop.1 |
| 3 | `MissingLightOnTwoSidesRule` | espacios con ventanas en ≤1 muro | APL.Pat.159 |
| 4 | `NoIntimacyGradientRule` | layout residencial lineal sin gradiente público→íntimo | APL.Pat.127 |
| 5 | `MonotonousFacadeRule` | fachadas muy repetitivas con muchas ventanas | NoO.Prop.4 |
| 6 | `MissingCommonAreasRule` | ningún Space "central" con ≥2 hijos | APL.Pat.129 |
| 7 | `MissingEntryThresholdRule` *(NUEVA, migrada)* | prompt residencial sin puerta en la planta baja | APL.Pat.112 |
| 8 | `ColorChaosRule` *(NUEVA, migrada)* | paleta con >7 materiales y entropía alta | NoO.Prop.14 |
| 9 | `WeakOutdoorSpaceRule` *(NUEVA, migrada)* | prompt pide jardín y el +Z queda lleno | APL.Pat.105 |
| 10 *(opt-in)* | `CaseSimilarityRule` | hay un caso similar pasado con score mucho mejor | el case_id |

Cada `Critique` lleva `Justification(source_id, quote,
target_pointer_evidence, canonical_reference)` con:

1. **`quote`**: una paráfrasis del texto de Alexander, verificada por
   match NFKC-substring contra `data/apl_corpus.json` (en su nueva
   estructura two-tier `{paraphrase, canonical}`). Si la cita no está
   en el corpus, el Critique se descarta con un warning.
2. **`canonical_reference`**: un `CanonicalReference(work, pages,
   edition, isbn)` que apunta al pasaje **original publicado** de
   Alexander. Lo inyecta automáticamente el `RuleBasedCritic._enrich_canonical`
   tras la emisión de cada Critique (sin necesidad de tocar las reglas).

Esto permite al TFG afirmar: *"cada Critique carga una paráfrasis
verificada estructuralmente Y una referencia bibliográfica auditable
al original"* sin ambigüedad legal (paráfrasis bajo TRLPI art. 32 /
Berne art. 10; referencia bibliográfica es uso legítimo siempre).

**Texto natural — dos modos**:

- **Dry-run** (sin LLM): `TemplateExplainer` rellena una plantilla
  determinista en español (*"La regla X se dispara sobre Y: 'quote' [source_id]. Severity: ..."*).
- **Live** (con `OPENROUTER_API_KEY`): `LLMExplainer` con JSON-mode
  + Pydantic `extra="forbid"` schema-lock. El LLM solo puede rellenar
  `explanation_nl` (1-350 chars); cualquier intento de modificar
  `severity`, `quote`, `source_id` u otros campos es rechazado por el
  schema. Ante cualquier fallo (timeout / JSON malformado / oversized
  / empty / schema reject), cae automáticamente al `TemplateExplainer`.

`make_default_critic(llm=None)` decide qué explainer cablear:
sin `llm` usa el template; con `llm` usa el LLM. `wire.make_live_pipeline`
pasa el LLM por defecto.

### 9.5 PromptClassifier (decide qué tags activan qué reglas)

Muchas reglas del Critic se condicionan a tags del prompt: por ejemplo
`MissingLightOnTwoSidesRule` solo aplica si el prompt es residencial,
`WeakStrongCenterRule` si es monumental, etc. Esos tags los produce
el `PromptClassifier` (`PromptTags(monumental, residential,
public_building, has_outdoor_intent, scale_hint)`).

**Dos implementaciones, mismo Protocol**:

- **`FakePromptClassifier`** (default sin LLM): golden-set de prompts
  exactos + fallback por substring keywords (ES/EN). Determinista. Se
  queda corto con paráfrasis ("una vivienda con jardín trasero" no
  matchea `_OUTDOOR_KEYWORDS` por la palabra "trasero").
- **`LLMPromptClassifier`** (default en live): una llamada LLM con
  JSON-mode + Pydantic schema-lock + cache SHA1 en disco
  (`data/prompt_classifier_cache.json`). Entiende ES y EN, paráfrasis
  y vocabulario de Alexander. **Cualquier fallo** (timeout / JSON
  malformado / schema reject / empty) cae al `FakePromptClassifier`.
  El cache hace que reruns del mismo prompt sean bit-idénticos sin
  consultar al LLM.

`make_default_prompt_classifier(llm=None, cache_path=...)` elige
entre los dos. `wire.make_live_pipeline` lo cablea con el LLM y un
cache en `data/prompt_classifier_cache.json`.

### 9.6 Historia de la consolidación (mayo 2026)

El sistema empezó con DOS capas de evaluación que se solapaban:

- **Capa 1** (`services/validation.py`): 5 reglas físicas sin cita.
- **Capa 2** (`services/misfits/`): 12 misfits con cita, agrupados en
  `physical_misfit` (5), `logical_misfit` (4) y `aesthetic_advisory` (3).

4 de las 5 reglas de Capa 1 eran duplicados directos de los misfits
físicos, y 4 de los 7 misfits soft (logical + aesthetic) eran duplicados
de reglas del Critic. Además, `MisfitAmplifierRule` re-publicaba los
misfits estéticos como Critiques, generando **triple-reporte** del mismo
problema en algunos casos (p.ej. fachada monótona).

La consolidación se hizo en dos pasos:

1. **Borrar Capa 1**: las 4 reglas duplicadas se eliminaron; la única
   sin equivalente (`StoreyContinuityRule`) se convirtió en
   `StoreyContinuityViolation` (misfit con cita).
2. **El Critic absorbe la capa soft**: los 7 misfits no-físicos se
   movieron al Critic (3 como reglas nuevas; los otros 4 ya tenían
   equivalente). `MisfitAmplifierRule` desapareció.

Resultado: una **única fuente de verdad por dimensión**:

- ¿Es físicamente posible? → MisfitChecker (6 reglas ERROR).
- ¿Es arquitectónicamente bueno? → RuleBasedCritic (9 reglas advisory).

---

## 10. Anti-circularidad

`services/anti_circularity.py`. Trivial:

```python
patterns_emergent  = patterns_matched - patterns_invoked   # generalización
patterns_fulfilled = patterns_matched & patterns_invoked   # cumplimiento
```

El `pattern_matcher` (9.1) es heurístico simple. La confianza es baja.

---

## 11. Herramientas externas (post-pipeline)

| Herramienta | Qué hace |
|---|---|
| `homecraft-place` | Recoloca un `building.json` ya generado en Minecraft sin re-correr el LLM. |
| `--clear` + `WorldCleaner` | Wipea la región del edificio (bbox + padding) a aire antes de colocar. |
| `--e2e-origin / --gog-origin` | En modo ablation, coloca E2E y GoG en orígenes mundo distintos para verlos lado a lado. |
| `--compare A B` / `--latest-compare` | Coloca dos JSONs side-by-side, opcionalmente desde el último directorio de ablation. |

---

## 12. Resultados observados (smoke live)

### Cabaña medieval — ablation E2E vs GoG (DeepSeek-v4-flash)

Prompt: *"una cabaña medieval con chimenea, paredes oak_planks, dos
ventanas opuestas y puerta sur"*.

| | E2E | GoG |
|---|---|---|
| Llamadas LLM generación | 1 | 1 planner + 6 generators |
| AABB elements pre-voxel | ~10 | 14 |
| Voxels colocados | 143 | **274** |
| Storeys semánticos | 3 | 3 |
| `overall_solid` (media geométrica × 10 sobre 4 sólidas) | 6.86 | 0.00 (colapsa porque `levels_of_scale=0`) |
| `patterns_fulfilled` | 3/3 | 3/3 |

GoG produce ~2× más bloques pero el scorer no-compensatorio colapsa
si una propiedad es 0. Esta sensibilidad es **el motivo metodológico
del pivot v1→v2**: con un solo modelo no se puede separar "qué
estrategia es mejor" de "qué estrategia consume más cómputo" y el
ranking depende de qué propiedad colapsa más que del algoritmo. El
experimento se reformula como una comparación multi-LLM con el
pipeline fijo (ver `homecraft batch` y §3 del informe).

(Ver `apéndice A` para resultados del castillo de 5 plantas y
evolución histórica del pipeline.)

---

## 13. Cómo correr

### Generación end-to-end (un prompt)

La CLI ahora se organiza en dos subcomandos: `run` para un prompt
suelto y `batch` para una batería. La forma legacy
`homecraft "<prompt>" ...` se sigue aceptando (se inyecta `run`
automáticamente).

```bash
# Demo offline (1s, fakes deterministas)
homecraft run "una cabaña medieval con chimenea" --mode ablation

# Live con OpenRouter LLM + Minecraft + persistencia SQLite
homecraft run "una iglesia gótica" --mode ablation --live \
    --e2e-origin 0 4 0 --gog-origin 60 4 0 \
    --db outputs/cases.sqlite \
    --out outputs/iglesia/building.json
```

Outputs en `outputs/<timestamp>_<slug>/`:
- `building.json` o `building_e2e.json` + `building_gog.json`
- `summary.json` con `scores.overall_solid` (primario),
  `overall_full` (exploratorio), `judge_placeholder_DO_NOT_USE`
  (stub etiquetado), `patterns_*`, `n_critiques`, `case_id`
- `pipeline.log`

### Batch experimental (N prompts pareados E2E vs GoG)

```bash
# Dry-run con 3 prompts de ejemplo
homecraft batch \
    --prompts tests/fixtures/batch_prompts.txt \
    --out-dir outputs/batch_smoke

# Batería real
homecraft batch \
    --prompts study/prompts.txt \
    --out-dir outputs/batch_$(date -u +%Y%m%dT%H%MZ) \
    --live --no-minecraft \
    --db outputs/batch_cases.sqlite \
    --seed-base 0
```

Outputs en `<out-dir>/`:
- `config.json` — config + git SHA + versión homecraft
- `prompts.jsonl` — items resueltos (id, prompt, seed)
- `runs/{id}_{e2e,gog}.json` — un `summarise(result)` por run
- `cases.sqlite` (si no se pasó `--db`)
- `summary.json` — Wilcoxon pareado + bootstrap CIs en dos bloques:
  `primary` (sobre `overall_solid`) y `exploratory` (sobre `overall_full`)
- `report.md` — versión legible del summary.json

Exit codes: 0 (todo OK con N≥10 pares), 1 (algún run falló o
n_pairs < 10), 2 (error de config), 130 (SIGINT).

### Recolocar un JSON sin LLM

```bash
homecraft-place --latest --clear                          # último, clear región
homecraft-place outputs/.../building.json --origin 100 4 200
homecraft-place --latest-compare --clear                  # E2E vs GoG side-by-side
```

### Ver el edificio en Minecraft

Con el server (`HomeCraft_Server/start.command`) corriendo:

```
/tp @s 25 80 5   # centro entre E2E y GoG en defaults
```

---

## 14. Bibliografía mínima

Alexander 1964 (*Notes on the Synthesis of Form*), Alexander 1977
(*A Pattern Language*), Alexander 2002 (*Nature of Order* Vol. 1),
Aamodt & Plaza 1994 (CBR), Wei et al. 2022 (Chain-of-Thought),
Khot et al. 2022 (Decomposed Prompting), Voyager 2023, SceneCraft
2024, Holodeck 2024.

---

## Apéndice A — Resultados extendidos

### Castillo medieval de 5 plantas (GoG live)

Prompt: *"un castillo medieval de tres plantas con torre cuadrada en
cada esquina, almena, patio, gran portón, cocina, dormitorios,
biblioteca, atalaya, foso ..."*

| Métrica | Valor |
|---|---|
| Sub-goals planificados | **8** (moat_foundation, 3× walls, 3× openings, roof) |
| AABB elements pre-voxel | 39 |
| Voxels post-voxel | **7237** |
| Storeys semánticos | 5 (exterior, ground, first, second, roof) |
| Compresión AABB→voxel | ~186× |
| `patterns_fulfilled` | 3/3 |
| `overall` | 6.42/10 |

El SubGoalPlanner escala dinámicamente con la complejidad del prompt:
4 (fallback) → 5 (cabaña) → 8 (castillo).

### Evolución histórica del pipeline GoG

| Métrica | Pre-Rasterizer | Post-Rasterizer | Post-DesignSpec | Post-AABB-GoG |
|---|---|---|---|---|
| Esquema LLM | Voxel-a-voxel | RegionPlan aparte | + DesignSpec | **BOT-AABB unificado** |
| Bloques cabaña | ~11 | 205 | 333 | **1055** |
| Bloques castillo | n/a | n/a | n/a | **7237** |
| Coherencia paleta | mala | mala | bien | bien |
| Storeys semánticos | n/a | rebanadas Y | rebanadas Y | **plantas reales** |

---

## Apéndice B — Módulos legacy eliminados (mayo 2026)

En mayo de 2026 se eliminaron del árbol los 9 módulos del flujo GoG
antiguo, que `Pipeline.run` ya no invocaba:

- `services/decomposer/{bot_tree.py, decomposer.py, material_assigner.py, tree_rasterizer.py}`
  — flujo jerárquico con `BOTTree` y `Leaf`, reemplazado por la
  unificación AABB-faithful (`SubGoalPlanner` + `SubGoalGenerator` +
  `BuildingMerger`).
- `services/gog/{coverage_checker.py, orchestrator.py, workspace.py, assembler.py, coord_allocator.py}`
  — flujo flat con DAG y Assembler, también obsoleto bajo el nuevo
  esquema AABB.

Net: ~1 454 LOC en `src/` + ~610 LOC en `tests/` borradas. El árbol
actual de `services/decomposer/` solo expone `BuildingMerger`,
`SubGoalGenerator`, `SubGoalPlan`, `SubGoalPlanner`, `SubGoalSpec`.
