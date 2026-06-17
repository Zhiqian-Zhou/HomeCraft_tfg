# Auditoría de procedencia del RAG global

**Fecha:** 2026-05-25
**Alcance:** colecciones A (skills), B (styles), C (patterns), D (materials), E (reference buildings)

> **Nota sobre este repo público.** El RAG (colecciones A–E) **no se incluye** en este repositorio por motivos de licencia — ver *Data availability* en el [README](../README.md#data-availability). Esta auditoría documenta la procedencia del corpus de desarrollo en su estado del **2026-05-25** (anterior a la expansión del catálogo de skills a 316 entradas que recoge la memoria); las cifras de abajo corresponden a esa instantánea histórica, no al estado final.
**Trigger:** petición del usuario — *"Lanza 10 agentes para comprobar que datos son reales y que datos son inventados por LLM. Si se puede, busca el dato real para reemplazarlo. Si no hay forma de encontrar, mirar de borrar ese dato."*

Este documento consolida el resultado de la verificación cruzada que realizaron 10 agentes en paralelo (V1–V10). El objetivo es separar, por colección, **qué datos están respaldados por una fuente externa verificable** y **qué datos siguen siendo síntesis del LLM** (defendibles para el TFG pero no auditables contra una fuente primaria). Al final se listan los borrados y se da una recomendación para la defensa.

---

## Resumen ejecutivo

| Colección | Antes | Después | Borrados | Estado |
|---|---:|---:|---:|---|
| A — skills (.json + .py) | 50 | 50 | 0 | ✓ refs normalizadas |
| B — styles | 10 | 10 | 0 | ✓ depurados |
| C — patterns | 30 | 29 | 1 | ✓ verificados contra patternlanguage.cc |
| D — materials | 186 | 182 | 4 | ✓ verificados contra minecraft.wiki |
| E — reference buildings | 2.746 | 2.746 | 0 | sin cambios |

**Cross-reference verifier:** 6/6 checks PASS tras la auditoría.
**Test harness de skills:** 300/300 invocaciones OK (50 skills × 3 estilos × 2 tamaños).

---

## Metodología

Cada agente recibió un subconjunto disjunto de entradas y un único mandato: para cada entrada, **(a)** identificar las afirmaciones que se podían verificar contra una fuente primaria, **(b)** corregirlas si estaban mal, **(c)** borrar la entrada si la fuente no la respaldaba en absoluto.

Las fuentes primarias utilizadas fueron:

- **patternlanguage.cc** — copia online y citable de *A Pattern Language* (Alexander et al., 1977, OUP, ISBN 0-19-501919-9), con números de página verificables. Usada por V1, V2, V3.
- **minecraft.wiki** — wiki canónica que documenta el comportamiento de cada bloque por versión (transparencia, emisión lumínica, solidez, blockstates disponibles en 1.16.5). Usada por V4, V5, V6.
- **scratch/style_palettes.json** — frecuencias empíricas de bloques por estilo en los 2.746 edificios de RAG-E. Usada por V7 para medir cuánto de cada style pack está respaldado por el corpus.
- **scratch/material_frequencies.json** — 621 bloques únicos en 4.704.009 vóxeles del corpus.

---

## V1 / V2 / V3 — Patterns (RAG-C, 30 → 29)

**Fuente:** patternlanguage.cc + *The Nature of Order* Book 1 (Alexander, 2002, ISBN 0-9726529-0-6).

### Lo verificado

- **28 entradas APL** con páginas y paráfrasis comparadas contra la fuente directa. Cinco correcciones de paginación (la más notable: `roof-layout` 956–961 → 970–977, *off by 14*). Todas las paráfrasis re-escritas con citas directas y marcadas `verified_against_corpus: true`.
- **3 propiedades de *Nature of Order*** (centros, escala, repetición alternante) confirmadas como conceptos del libro, con rango de páginas amplio (la paginación por propiedad concreta no es localizable online).

### Borrado

- `rag/patterns/reading-room.json` — **inventado**. No existe ningún pattern en APL llamado "Reading Room". El concepto más cercano (`workplace-enclosure`, APL 183) ya estaba catalogado. *Acción: archivo borrado, todas las referencias `reading-room` en skills reapuntadas a `workplace-enclosure`.*

### Corregido (no borrado)

- `workspace-privacy.json` — la paráfrasis describía `workplace-enclosure` por error; se reescribió con la cita correcta.
- Referencias bogus a skills inexistentes (`porch`, `window_seat`, `garden_bench`, `children-area`) eliminadas de `skills_embodying` de varios patterns.

### Duplicado pendiente

- `the-family-room` y `common-areas-at-the-heart` apuntan ambos a APL 129. Son el mismo pattern presentado dos veces. **Decisión diferida** — se mantienen ambos por ahora porque skills distintos los referencian; consolidar en una sola entry queda como tarea de limpieza posterior.

---

## V4 / V5 / V6 — Materials (RAG-D, 186 → 182)

**Fuente:** minecraft.wiki por versión 1.16.5.

### Lo verificado

- **182 bloques** confirmados como obtenibles en vanilla 1.16.5 con sus propiedades (`transparent`, `light_emission`, `is_solid`) ajustadas a la wiki.
- **Correcciones notables de emisión lumínica:**
  - `redstone-lamp`: 15 → 0 (la base no emite; sólo el blockstate `lit=true`)
  - `beacon`: 0 → 15
  - `red-mushroom`: 1 → 0 (sólo `brown_mushroom` emite)
  - `brewing-stand`: 0 → 1
  - `enchanting-table`: 0 → 7
- **Correcciones de transparencia/solidez:** ~14 ajustes en puertas, camas, cofres, yunques, calderos, glowstone, lava — bloques con hitbox no-cúbico que estaban marcados como sólidos opacos.

### Borrados

- `rag/materials/smooth-stone-stairs.json` — **el bloque no existe en 1.16.5** (se añadió en 1.16+ pero no como item obtenible legítimo en survival; la wiki lo lista como bloque "técnico"). *Acción: 23 skills que lo referenciaban migradas a `minecraft:smooth_quartz_stairs` (V8).*
- `rag/materials/bed.json` — `minecraft:bed` genérico **no existe**; sólo las 16 variantes coloreadas (`red_bed`, `white_bed`, …). *Acción: skills reapuntadas a placeholder `@bed` resuelto vía `style_variants.palette_overrides`.*
- `rag/materials/carpet.json` — mismo caso: sólo existen las 16 variantes coloreadas. *Acción: placeholder `@carpet`.*
- `rag/materials/armor-stand.json` — **es una entidad, no un bloque**. *Acción: skill `stable` reapuntada a placeholder `@armor_stand_entity`.*

### Lo que queda como síntesis del LLM (defendible)

- Campos como `used_by_styles`, `category` y `color`: son etiquetas semánticas sin fuente externa única — derivadas de inspección del corpus y de uso editorial. No verificables contra wiki, pero consistentes internamente.

---

## V7 — Styles (RAG-B, 10 → 10)

**Fuente:** `scratch/style_palettes.json` — paletas empíricas extraídas de los 2.746 edificios filtrados por `tags.style`.

### Lo verificado

- Cada style pack contrastado contra los **top-12 bloques signature** del corpus para su estilo. *Empirical grounding score* = fracción de la paleta del pack que aparece en los signature_blocks del corpus.

| Style | Grounding | Buildings en corpus |
|---|---:|---:|
| rustic | 0.50 | alto |
| medieval | 0.46 | alto |
| modern | 0.31 | alto |
| (otros) | 0.15–0.30 | bajo |
| japanese | 0.08 | 2 buildings |

### Corregido

- `medieval.json` y `fantasy.json`: se quitaron **7 bloques de 1.17+** (deepslate, calcite, cut_copper) que el agente generador había alucinado.

### Lo que queda como síntesis del LLM (defendible)

- `signature_elements` (p.ej. "almenas" para medieval, "shoji" para japonés) — son **convenciones culturales**, no se extraen del corpus. El TFG las defiende como decisión editorial basada en literatura de diseño arquitectónico, no como hecho empírico.
- `ratios` (story_height, wall_thickness, etc.) — números editoriales sin fuente externa, calibrados para que las skills produzcan output visualmente coherente.
- Para `japanese` (sólo 2 buildings en el corpus), el style pack es **mayoritariamente LLM** porque el corpus no da suficiente señal. Esto está documentado como riesgo en el plan original.

---

## V8 / V9 — Skills (RAG-A, 50 .json + 50 .py)

**Fuente:** test_harness ejecutable + cross-ref verifier.

### Lo verificado

- **300/300** invocaciones del harness OK (50 skills × 3 estilos × 2 tamaños), AABB respetado, output dentro del bounding box.
- **0 bloques de 1.17+** en el código Python tras V9.
- **112 referencias a patterns** normalizadas a kebab-ids (de "Light on Two Sides" → `light-on-two-sides`), con alias map en el verifier para los casos legacy.
- **25 fixes de block_id** en JSONs:
  - 23× `smooth_stone_stairs` → `smooth_quartz_stairs` (consecuencia del borrado en V4)
  - 2× `deepslate_bricks` → `blackstone` (1.16.5 equivalent del 1.17+ deepslate)

### Lo que queda como síntesis del LLM (defendible)

- Las **geometrías** (qué bloques colocar dónde para construir un "throne_room", un "gazebo", una "pergola") son **diseños del LLM**. No hay corpus que diga "así se construye una sala del trono"; son interpretaciones del lenguaje natural a vóxeles, exactamente el problema que el TFG quiere resolver.
- Las `required_furniture` con cantidades específicas son convenciones editoriales razonables, no medidas empíricas.
- Esta es la parte más "creativa" del RAG y se defiende como **prior del agente generador**, no como ground truth.

---

## E — Reference buildings (2.746)

Sin cambios en este pase. La trazabilidad de cada edificio está en su propio `license_notes` y `source_url`. El audit no abre esos ficheros porque ya tienen procedencia documentada en su ingesta.

---

## Lo que no se ha podido verificar y se queda como está

1. **`signature_elements` de los styles** — convención cultural, no empírica.
2. **`ratios` de los styles** — números editoriales.
3. **Geometrías de las skills** — el output de cada `build()` es síntesis del LLM por diseño.
4. **`used_by_styles` de los materials** — etiquetado editorial.
5. **El estilo `japanese`** — corpus insuficiente (2 buildings); el style pack es mayoritariamente síntesis.
6. **Duplicado `the-family-room` ↔ `common-areas-at-the-heart`** — ambos APL 129; consolidación diferida.

Estas decisiones quedan explícitas para que el tribunal pueda separar el "qué se extrajo" del "qué se sintetizó".

---

## Recomendación para la defensa del TFG

El RAG global tiene **dos capas de procedencia**:

1. **Capa verificable contra fuente primaria.** Patterns (APL + Nature of Order), materials (minecraft.wiki 1.16.5), bloques signature de los styles (corpus). Todo lo de esta capa tiene `verified_against_corpus: true` o equivalente.

2. **Capa de síntesis del LLM.** Geometrías de skills, signature_elements, ratios, etiquetado semántico. Defendible como **prior del sistema generador**, no como ground truth. Esto es precisamente la hipótesis del TFG: que un LLM con skills y RAG puede generar arquitectura coherente.

La separación es honesta y trazable. Para el tribunal, sugerir presentar la auditoría como **evidencia de rigor metodológico**: el sistema no esconde lo sintético; lo distingue del verificado y documenta el porqué de cada decisión.

---

## Referencias y herramientas

- `tools/verify_rag_cross_refs.py` — verificador cross-collection (6 checks).
- `tools/build_material_corpus.py` — frecuencias del corpus (4.704.009 vóxeles, 621 bloques únicos).
- `tools/build_style_palettes.py` — paletas signature por estilo.
- `pipeline/skills/test_harness.py` — ejecución de las 50 skills.
- `patternlanguage.cc` — fuente online de APL con páginas.
- `minecraft.wiki` — propiedades canónicas de bloques por versión.

---

*Auditoría producida tras la sesión de verificación V1–V10 (V10 escribió esta versión manual al fallar el agregador automático).*
