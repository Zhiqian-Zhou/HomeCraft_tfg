# HomeCraft v2 — base de conocimiento del RAG

El RAG es el sustrato de retrieval que permite a cada agente LLM de Pipeline v2 trabajar sin meter el conocimiento de diseño dentro de los prompts. Tiene **cinco colecciones**, cada una en su carpeta y respaldada por un JSON Schema en `schema/`.

| Colección | Carpeta | Schema | Qué guarda |
|---|---|---|---|
| A · Skills | `skills/` | `skill_entry.schema.json` | Conocimiento *cómo hacer* de cada skill de room / structural / exterior (cocina, tejado a dos aguas, torre…). Empareja 1:1 con una función Python skill. |
| B · Style packs | `styles/` | `style_pack.schema.json` | Paleta por estilo, elementos firma y ratios típicos. |
| C · Patterns | `patterns/` | `architectural_pattern.schema.json` | Patrones de Alexander (Pattern Language + Nature of Order) con paráfrasis verificadas y referencias bibliográficas. |
| D · Materials | `materials/` | `material.schema.json` | Catálogo de bloques Minecraft 1.16.5 con metadatos semánticos. |
| E · Reference buildings | `reference_buildings/` | `reference_building.schema.json` | Edificios reales de Minecraft como listas de vóxeles `{x, y, z, palette_idx}`. |

## Contrato de retrieval

- **Los subgoal agents consultan A + E conjuntamente.** Una llamada del tipo "diseña una cocina medieval" debe devolver tanto la skill entry de cocina (el *cómo*) como ejemplos reales de cocinas medievales de E (cómo podría quedar).
- Las colecciones A y E comparten `tags.category` (kitchen, bathroom, tower…) y `tags.style` (medieval, fantasy…) para que un mismo filtro cubra ambas.
- C se consulta cuando el main agent necesita justificación basada en Alexander (p.ej. "intimacy gradient" → qué espacios situar más profundo).
- B se consulta en Phase 1 (Design intent) para fijar la paleta; D es el índice que permite resolver las paletas de B a bloques concretos.

### Retrieval sobre E (v2.6+)

El retriever (`pipeline.agents.retriever.retrieve`) funciona en dos fases:

1. **Pre-filtro por calidad** (offline, una vez): `tools/score_corpus.py` evalúa los 2,746 edificios con el evaluator de Stage 6 y produce un sidecar `scratch/corpus_evaluations/<id>.json` con el composite ∈ [0,1]. `tools/build_retrieval_index.py` se queda solo con el **top-30%** por composite (~833 edificios, cutoff ≈ 0.608) y construye TF-IDF únicamente sobre ese subset.
2. **Ranking online** (cada query): TF-IDF cosine puro sobre el subset filtrado. El composite ya hizo su trabajo durante el pre-filtro; no participa en el ranking.

Sustituye al blend antiguo `α·TF-IDF + (1-α)·alex_score`. Razón: el composite del evaluator (18 métricas físicas + Alexander) es señal mucho más rica que el diff geométrico de 7 dimensiones del `alexander_scorer.py` (ahora deprecado, kept para diagnóstico).

Regenerar el índice:
```bash
python3 tools/score_corpus.py             # ~1 min, incremental
python3 tools/build_retrieval_index.py    # rebuild filtrado top-30%
```

## Colección de reference buildings — pipeline

```
reference_buildings/
├── raw/                  ← toda descarga aterriza aquí tal cual
│   └── manifest.jsonl    ← registro append-only (URL, licencia, formato, agent_id, iter)
├── processed/            ← solo JSONs schema-valid (licencia identificable)
├── index/                ← índices cacheados (style/category → ids)
└── PROCESSING.md         ← log de decisiones (notas por ingest, rechazos)
```

La política de licencia es **híbrida**: todo lo accesible va a `raw/` con su licencia anotada; solo lo que tiene licencia identificable se mueve a `processed/`. Ver la nota de memoria del proyecto sobre política de licencia.

## Target de Minecraft

Todo lo ingestado se normaliza a IDs namespaced de **Minecraft Java 1.16.5** (`minecraft:oak_planks`). Los `.schematic` legacy se remapean vía las flattening tables de `mcschematic` / `amulet-core`; los bloques añadidos en 1.17+ se downsamplean o se rechazan, dejando registro en `PROCESSING.md`.

## Añadir al RAG

1. **Entries de A, B, C, D**: a mano o LLM-assisted; se deja un JSON en la carpeta. CI valida contra el schema.
2. **Entries de E**: nunca a mano. Usar `tools/ingest_schematic.py` / `tools/ingest_nbt.py` para convertir una descarga. El validador (`tools/validate_building.py`) hace cumplir el schema y la heurística `interior_populated`.

## Verificación

- `tools/validate_building.py rag/reference_buildings/processed/*.json` debe salir 0.
- `tools/audit_dataset.py` produce la matriz de cobertura (style × category × buckets de tamaño).
- Al menos una entry por iteración se renderiza (mcpi o renderer offline) para sanity visual.
