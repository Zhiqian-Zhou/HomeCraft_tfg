# Diseño del experimento — Comparación de LLMs en el pipeline texto→edificio voxel

**Fecha:** 2026-06-01 · **Pipeline:** v4 (sin modificar) · **RAG/evaluador:** estado actual de la rama `v4-elaboracion`.

## 1. Pregunta de investigación

> Manteniendo **constante** el pipeline (las skills, la RAG, el evaluador) y variando **solo el LLM**, ¿qué modelo produce mejores edificios, y a qué coste (tokens) y tiempo? ¿Por qué?

Esta es exactamente la reframulación de la tesis (§3.2 del informe): *el pipeline es la constante, el LLM es la variable*, lo que evita el confound de compute de la comparación GoG-vs-E2E de v1.

## 2. Variable independiente: el LLM

Se fija `MODEL_MAIN = MODEL_WORKER = <modelo>` (mismo modelo para agentes principales y de trabajo) vía variables de entorno, en un **subproceso nuevo por build** (necesario porque `llm.py` congela el modelo en el import).

| # | Modelo (OpenRouter) | Familia | Tamaño aprox. | Tipo | Disponibilidad |
|---|---|---|---|---|---|
| 1 | `meta-llama/llama-4-scout` | Llama 4 | MoE ~17B activos | Instruct | ✅ OK |
| 2 | `meta-llama/llama-3.3-70b-instruct` | Llama 3.3 | 70B | Instruct | ✅ OK |
| 3 | `google/gemma-4-26b-a4b-it` | Gemma 4 | MoE ~4B activos / 26B | Instruct | ✅ OK |
| 4 | `google/gemma-4-31b-it` | Gemma 4 | 31B | Instruct | ✅ OK |
| 5 | `qwen/qwen3.5-9b` | Qwen 3.5 | 9B | **Razonamiento** | ⚠️ ver §6 |
| 6 | `qwen/qwen3.5-35b-a3b` | Qwen 3.5 | MoE ~3B activos / 35B | **Razonamiento** | ⚠️ ver §6 |

## 3. Variables dependientes (lo que se mide por build)

Se capturan de `evaluation_report.json` (campo `composite` y `generation`) que el pipeline v4 ya escribe:

**Calidad (evaluador):**
- `composite.overall` — score global [0,1] (métrica principal).
- `composite.physical_total`, `composite.alexander_total`, `composite.appearance_total`.
- `composite.prompt_adherence_total` — fidelidad al prompt (eje separado).
- Desglose por las 18 métricas (físicas + Alexander + appearance).

**Coste y rendimiento:**
- `generation.total_tokens`, `prompt_tokens`, `completion_tokens`.
- `generation.llm_calls` — nº de llamadas al LLM por build.
- `generation.wall_time_s` — tiempo de pared del build.
- `generation.llm_wait_s` — tiempo esperando al LLM (aísla latencia del modelo).

**Robustez:**
- `status` ∈ {ok, error}. Tasa de éxito por modelo.
- `error` y `fail_stage` si falla (de stderr).
- Recuento de fallbacks deterministas (floor BSP, etc.) parseado de stderr — proxy de "cuánto decidió realmente el LLM" (auditoría previa).

## 4. Control de variables (validez interna)

- **Pipeline idéntico** para todos: misma versión (v4), mismas skills, misma RAG, mismo evaluador, mismos `max_tokens`/`temperature` por etapa.
- **Mismos 10 prompts** para todos los modelos (diseño *within-subjects*: cada prompt se corre en los 6 modelos).
- **`gen_id` determinista** por (modelo, prompt) → la semilla del pipeline (`seed_from(gen_id)`) es **idéntica entre modelos para el mismo prompt** → las decisiones deterministas (semilla de variantes, hash de exteriores) **no** introducen ruido entre modelos. La única diferencia es el LLM.
- **`temperature` la fija cada agente** (no la toco) → reproducibilidad parcial; aun así hay estocasticidad del LLM (n=10 prompts mitiga, no elimina; ver §7).
- Subproceso aislado por build → sin contaminación de estado entre builds.

## 5. Los 10 prompts (diversos, nuevos, distintos de los del gym)

Cubren deliberadamente: tamaño (pequeño→grande), nº de plantas (1→5), estilo (nórdico, moderno, adobe, asiático, industrial, castillo, mediterráneo, gótico, utilitario, barroco) y tipología estructural (altillo, patio, aleros de pagoda, torreones, cúpula, escalera de caracol, alas simétricas).

1. **nordic-cabin** — *A small Nordic log cabin with a single room around a central stone hearth and a sleeping loft tucked under a steep gabled roof.*
2. **modern-townhouse** — *A three-story glass-and-concrete townhouse with an open-plan ground floor, a cantilevered upper bedroom, and a flat rooftop terrace.*
3. **adobe-courtyard** — *An adobe pueblo dwelling with flat clay roofs, small deep-set windows, an interior courtyard, and an exterior staircase up to the second level.*
4. **pagoda-five-tier** — *A five-story pagoda with upturned tiled eaves on every tier, a central staircase column, and a shrine room at the base.*
5. **brick-watermill** — *A red-brick watermill beside a channel, with a wheel housing on one side, a grain storage loft above, and a timber-framed gable roof.*
6. **stone-keep** — *A square stone keep with round corner turrets, crenellated battlements, a great hall on the first floor, and a vaulted undercroft below.*
7. **greek-island-house** — *A whitewashed Greek island house with a blue domed roof, stepped flat terraces, narrow stairs between levels, and a vine-shaded pergola.*
8. **octagonal-baptistery** — *An octagonal baptistery chapel with a ribbed dome, a tall arched window on each of its eight faces, and a central font.*
9. **cylindrical-lighthouse** — *A tall cylindrical lighthouse with a spiral interior staircase, a glass lantern room at the very top, and a keeper's room at the base.*
10. **baroque-manor** — *A symmetrical Baroque manor with two side wings, a central ballroom under a barrel vault, a grand double staircase, a library, and a columned entrance portico.*

## 6. Amenaza conocida: modelos de razonamiento (qwen3.5)

Verificado empíricamente: `qwen/qwen3.5-9b` y `-35b-a3b` son modelos de **razonamiento**; devuelven el texto en `message.reasoning` y dejan `message.content = null`. El pipeline (`llm.py:148`) lee solo `content`; si está vacío reintenta 4× y luego lanza `RuntimeError`. Como `space_planner_v4` **no tiene fallback**, es probable que muchos/ todos los builds de qwen **fallen**.

**Decisión:** NO modifico el pipeline (el usuario pidió no tocar problemas, y mantenerlo intacto preserva la equidad de la comparación). El comportamiento resultante de qwen es, en sí, un **resultado válido y reportable**: "el pipeline, tal como está, es incompatible con modelos de razonamiento que emiten `content` vacío, y además consumen más tokens (los de razonamiento cuentan como completion)". Se medirá tasa de éxito, tokens y tiempo igualmente.

## 7. Amenazas a la validez (honestidad metodológica)

- **n pequeño (10 prompts/modelo):** suficiente para tendencias, no para significancia estadística fuerte. Se reportarán medias ± desviación, no se afirmará significancia sin test.
- **Estocasticidad del LLM:** temperatura > 0 en varios agentes → un solo build por (modelo,prompt). No hay repeticiones por límite de coste. Se asume que 10 prompts diversos promedian el ruido.
- **Fallbacks deterministas (de la auditoría):** parte del edificio no la decide el LLM (floor_planner→BSP, furnish.py). Esto **comprime** las diferencias entre modelos. Se cuantifica el nº de fallbacks por build como covariable.
- **Métricas saturadas (de la auditoría):** 5 métricas dan ~1.0 siempre → el `overall` discrimina menos de lo ideal. Se analizará también el subconjunto de métricas de alta varianza.
- **Evaluador con `gemini-2.5-flash-lite` para el critique LLM:** el critique es cualitativo y no entra en el composite, así que no sesga los scores numéricos.

## 8. Protocolo de ejecución

1. 6 modelos × 10 prompts = **60 builds**, pipeline v4, subproceso por build.
2. Concurrencia limitada (varios subprocesos a la vez) con **timeout de 300 s/build**.
3. Cada resultado → fila en `scratch/experimento/results.jsonl` (modelo, prompt, status, scores, tokens, tiempos, fallbacks).
4. Análisis (`analizar.py`): agregación a `results.csv` + plots en `scratch/experimento/plots/`.
5. Informe `RESULTADOS.md` con conclusiones y el *porqué*.

## 9. Plots previstos

- Barras: `overall` medio por modelo (± dt) + tasa de éxito.
- Barras apiladas: physical/alexander/appearance por modelo.
- Scatter coste–calidad: tokens totales (x) vs overall (y), un punto por build, color por modelo.
- Scatter tiempo–calidad: `llm_wait_s` vs overall.
- Heatmap: modelo × prompt → overall (ver qué prompts son difíciles).
- Heatmap: modelo × métrica (18) → score medio (qué capacidades distinguen a los modelos).
- Barras: tokens medios y llamadas medias por modelo.
