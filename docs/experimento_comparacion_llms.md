# Experimento: comparación de LLMs como motor generativo de HomeCraft (pipeline v4)

> Diseño experimental para el TFG (UPC/FIB) — generación **texto → edificio vóxel
> (Minecraft 1.16.5)**. Documento de referencia para ejecutar y defender la
> comparación de distintos modelos de lenguaje. Markdown en español (convención
> del proyecto).

## 1. Objetivo del proyecto y del experimento

El proyecto genera edificios habitables a partir de una descripción en lenguaje
natural, mediante una **tubería de agentes LLM** respaldada por un RAG de cinco
colecciones (skills, estilos, patrones, materiales, edificios de referencia).

**Objetivo del experimento:** cuantificar **en qué medida el LLM que actúa como
motor del razonamiento de diseño afecta** a (a) la **calidad** del edificio, (b)
la **fidelidad** al prompt, (c) el **coste** (tokens/tiempo) y (d) la
**robustez** (tasa de generación válida) — manteniendo TODO lo demás constante.
Es un experimento **controlado de una sola variable independiente: el LLM**.

### Preguntas de investigación
- **RQ1 (calidad).** ¿Producen mejores edificios los modelos más capaces, medido
  por las métricas físicas, de patrones de Alexander y de apariencia?
- **RQ2 (fidelidad).** ¿Cumplen mejor el prompt (salas/muebles/material/plantas
  pedidos)?
- **RQ3 (coste).** ¿Cuál es el compromiso **calidad ↔ coste** (tokens y tiempo)?
  ¿Compensa un modelo grande?
- **RQ4 (robustez).** ¿Con qué frecuencia el modelo genera una salida **válida**
  (esquema correcto, edificio no vacío) sin intervención de los *fallbacks*?

### Hipótesis (direccionales, falsables)
- H1: modelos más capaces ⇒ mayor `composite` (calidad) — pero con **rendimientos
  decrecientes** sobre el pipeline+RAG (gran parte de la corrección la garantizan
  pasadas deterministas: `physical_fixer`, `envelope_closer`, `furnish`).
- H2: la **fidelidad al prompt** discrimina más entre modelos que la calidad,
  porque la calidad está parcialmente "blindada" por las pasadas deterministas.
- H3: el coste en **tokens** crece con la capacidad/contexto, dominado por los
  *prompt tokens* (RAG); el modelo elegido debe optimizar **calidad por token**.

## 2. Variables

| Tipo | Variable | Valores |
|---|---|---|
| **Independiente** | LLM (motor) | p.ej. `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `gpt-4o-mini`, `claude-haiku`, … (vía OpenRouter) |
| **Dependientes** | calidad, fidelidad, coste, robustez | ver §4 (métricas) |
| **Controladas** | pipeline (v4), RAG, prompts de sistema, `temperature`, `best-of-K` (K=3), seed determinista (`seed_from(gen_id)`), versión MC (1.16.5) | constantes |
| **De ruido** | no determinismo del LLM | mitigado con **N repeticiones** por prompt |

El LLM se fija con la variable de entorno `MODEL_DEFAULT`/`MODEL_MAIN`
(`pipeline/agents/llm.py`); el resto del sistema no cambia entre condiciones.

## 3. Diseño

- **Conjunto de prompts (test set).** ≥ 20 prompts estratificados que cubran:
  - **tipologías:** casa, torre, castillo, palacio, templo, molino, biblioteca…
  - **atributos verificables explícitos:** nº de salas ("4 bedrooms, 2 kitchens"),
    nº de plantas ("three-story"), material/color ("stone", "white marble",
    "red brick"), muebles implícitos (dormitorio→cama).
  - **dificultad:** simple (cabaña 1 planta) → compleja (palacio multi-masa).
  - Los 11 *demos* de `scratch/generations/demo-*` sirven de semilla del test set.
- **Repeticiones.** N = 5 generaciones por (prompt × modelo) con `gen_id`
  distinto → permite medir **media y varianza** (estabilidad del modelo) y aplicar
  estadística.
- **Diseño:** *within-prompts* (cada prompt pasa por todos los modelos) →
  comparación pareada, mayor potencia estadística.
- **Tamaño:** 20 prompts × M modelos × 5 repeticiones.

## 4. Métricas (clasificadas por apartados)

Todas las produce `pipeline/agents/evaluator.py` (campo `metric_metadata` con la
**fuente bibliográfica** de cada métrica → defendible) y `run.py` (coste). Cada
métrica ∈ [0,1] salvo el coste; `None` = no aplica (no penaliza). El reporte
incluye `scope_summary` (media por ámbito interior/exterior/prompt/structural).

### 4.1 Calidad — Física / habitabilidad (`physical`, 10 métricas)
Corrección del edificio EN SÍ, independiente del prompt. Pesos en
`_PHYSICAL_WEIGHTS`; total `composite.physical_total`.
`structural_integrity` (estabilidad, *Model Synthesis*, Merrell 2010),
`voxel_connectivity` (navegabilidad, *Space Syntax*, Hillier & Hanson 1984),
`vertical_clearance`, `door_functionality`, `light_coverage` (APL 159),
`envelope_integrity` (cerramiento), `room_furnishing` (completitud funcional,
Gibson 1979 — con desglose **by_role**), `material_consistency`, `volume_density`,
`block_legitimacy` (validez 1.16.5; excluida del composite por no discriminar).

### 4.2 Calidad — Diseño arquitectónico (`alexander`, 10 métricas)
Patrones de *A Pattern Language* (Alexander 1977), cada uno con su nº de patrón:
`intimacy_gradient` (P.127), `common_areas_at_heart` (P.129),
`light_on_two_sides` (P.159), `sheltering_roof` (P.117), `building_edge` (P.160),
`window_place` (P.180), `entrance_transition` (P.112), `main_entrance` (P.110),
`farmhouse_kitchen` (P.139), `roof_layout` (P.209). Total `alexander_total`.

### 4.3 Calidad — Apariencia / elaboración (`appearance`, 5 métricas)
`facade_articulation`, `fine_detail`, `decoration_density`,
`silhouette_complexity`, `material_richness` (composición visual; cf. Ching).
Total `appearance_total`.

> **Composite de CALIDAD** = `0.34·physical + 0.26·alexander + 0.40·appearance`
> (`_OVERALL_WEIGHTS3`) → `composite.overall`. **No** mezcla fidelidad ni coste.

### 4.4 Fidelidad — Adecuación al prompt (`prompt_adherence`, apartado propio)
Eje SEPARADO de la calidad (controlabilidad texto→3D; cf. **CLIP-score**, Hessel
et al. 2021). Pesos `_PROMPT_WEIGHTS`; total `composite.prompt_adherence_total`.
- `room_count` — salas pedidas vs construidas por rol ("4 bedrooms"→4). Campos
  `requested`/`built`.
- `furniture` — **muebles pedidos vs generados** (p.ej. *camas pedidas vs
  generadas*); desglose `by_furniture {bed:{requested,present}, …}`.
- `materials` — material/color del prompt presente en la obra (match por palabra
  completa: "stone", "white", "marble"…).
- `floors` — nº de plantas pedido vs construido ("three-story"→3).

### 4.5 Coste — Tokens y tiempo (`generation`, apartado propio)
Lo registra `llm.py` (acumulador de `usage`) + `run.py`; en
`<gen_id>/generation_cost.json` y embebido en el reporte:
`model`, `total_tokens` (prompt+completion), `llm_calls`, `wall_time_s`,
`llm_wait_s`, `by_model`. **Métrica derivada clave: calidad por kilo-token**
= `composite.overall / (total_tokens/1000)`.

### 4.6 Robustez (nivel de LOTE, calculada al agregar)
No es una métrica por-edificio sino del experimento:
- **tasa de generación válida** = builds que producen reporte válido / intentos.
- **tasa de uso de *fallback*** = generaciones donde un agente LLM falló y entró
  el plan determinista (`fallback_on_failure`) — proxy de fragilidad del modelo.
- **reintentos por error transitorio** (429/5xx/JSON roto) registrados por
  `llm.py`. *(Sugerencia de mejora: exponer un contador de reintentos/fallbacks
  en `usage_snapshot()` para automatizar este apartado.)*

## 5. ¿Faltan métricas para este experimento?

Tras la auditoría de informatividad (varianza sobre los 11 demos):
- **Añadidas** en esta iteración: apartado **`prompt_adherence`** completo
  (`room_count`, `furniture`, `materials`, `floors`) y apartado **`generation`**
  (tokens/tiempo). Antes no existían como ejes explícitos.
- **Arregladas:** `intimacy_gradient` pasaba de informar en 1/11 a **10-11/11**
  (grafo de circulación = puertas ∪ adyacencia geométrica horizontal/vertical).
- **Pendiente recomendado:** métrica/contador de **robustez** automatizado
  (fallbacks + reintentos) a nivel de lote; opcional una métrica de **fidelidad
  de tamaño/footprint** si los prompts piden dimensiones explícitas.
- **No discriminantes entre buenos builds** (constantes ~1.0 por las pasadas
  deterministas): `door_functionality`, `material_consistency`, `block_legitimacy`.
  Se conservan como **puertas de validez** (un LLM peor SÍ las bajaría), pero no
  se espera que separen modelos competentes — declararlo en el análisis.

## 6. Procedimiento

1. Para cada modelo, exportar `MODEL_DEFAULT=<id>` (OpenRouter) y `OPENROUTER_API_KEY`.
2. Generar el test set:
   `python3 -m pipeline.agents.run "<prompt>" -V v4 --gen-id <modelo>__<promptid>__<rep>`.
3. Cada build escribe `scratch/generations/<gen_id>/generation_cost.json` y
   `<gen_id>.evaluation.json` (calidad + fidelidad + coste + metadatos con citas).
4. Agregar: recolectar todos los reportes → tabla por (modelo, prompt, rep).

## 7. Análisis

- **Por eje:** media ± IC95% de `physical_total`, `alexander_total`,
  `appearance_total`, `overall`, `prompt_adherence_total`, y de `scope_summary`
  (interior/exterior).
- **Comparación de modelos:** al ser *within-prompts*, **Friedman** + post-hoc
  **Wilcoxon** pareado con corrección (Holm). Tamaño del efecto.
- **Coste/calidad:** frontera de Pareto (overall vs total_tokens y vs wall_time);
  **calidad por kilo-token**.
- **Robustez:** tasa de éxito y de fallback por modelo (χ²).
- **Estabilidad:** desviación típica de `overall` entre las N repeticiones.

## 8. Defensibilidad ante el tribunal

- **Separación de ejes** calidad / fidelidad / coste / robustez → conclusiones no
  confundidas (un modelo puede ser barato pero infiel, etc.).
- **Cada métrica con fuente** (`metric_metadata.source`): Alexander (patrón nº),
  Space Syntax, Model Synthesis, affordances (Gibson), CLIP-score, Ching.
- **Reproducibilidad:** seed determinista, best-of-K fijo, RAG y prompts versionados.
- **Evaluador auditado:** sin fallos de estructura/rango; informatividad medida.

## 9. Amenazas a la validez (y mitigación)
- *No determinismo del LLM* → N repeticiones + reportar varianza.
- *Calidad "blindada" por pasadas deterministas* → por eso se separa la
  **fidelidad** (más sensible al LLM) y se reporta la **tasa de fallback**.
- *Juez LLM en el `critique`* (texto) → NO entra en las métricas numéricas; las
  métricas son deterministas/heurísticas.
- *Heurística de algunas métricas* (no ground truth humano) → **validado**: un
  estudio con 13 jugadores de Minecraft anonimizados, que puntuaron 20 escenas en
  6 preguntas, confirma el acuerdo del evaluador automático con el juicio humano
  (correlación agregada ≈ 0,84; ver `correlacion_humano/`).
- *RAG fijo* → la comparación mide el LLM **dentro de este sistema**, no en
  abstracto; es una decisión de diseño (mantener el RAG constante aísla el efecto
  del LLM), no una limitación de validez del evaluador.
