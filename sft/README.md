# SFT con Unsloth — texto → JSON de edificio voxel (RTX 5090)

Entrenamiento *supervised fine-tuning* optimizado con **Unsloth (QLoRA 4-bit)**
para una sola **RTX 5090 (32 GB, Blackwell)**, con modelos **Gemma**.

El dataset lo genera `tools/build_sft_dataset.py` en `scratch/sft/`
(ver `scratch/sft/README.md`). Formato `{prompt, completion}`.

## Ficheros

| Fichero | Qué hace |
|---|---|
| `train_unsloth.py` | Entrena QLoRA con Unsloth, optimizado para 5090 |
| `infer.py` | Carga el adapter y genera/valida un edificio desde una descripción |
| `common.py` | Wrapper de prompt compartido train↔inferencia (no tocar por separado) |
| `requirements.txt` | Dependencias (con notas para Blackwell/cu128) |

## Instalación (Blackwell / 5090)

La 5090 (sm_120) **necesita CUDA 12.8 y PyTorch ≥ 2.7 (cu128)**. Instala torch primero:

```bash
python -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cu128
pip install -r sft/requirements.txt
```

Si `bitsandbytes` falla en Blackwell, usa ≥ 0.45.0. Si hay errores de kernels
Triton, `pip install --upgrade --no-cache-dir unsloth unsloth_zoo`.

## Entrenar

```bash
# Sweet spot recomendado en 5090: gemma-2-9b, secuencia 16k
python sft/train_unsloth.py --max-seq-len 16384

# Rápido / mínimo VRAM (solo casas pequeñas-medianas)
python sft/train_unsloth.py --max-seq-len 8192

# Más variedad de estructuras grandes → modelo más pequeño, contexto más largo
python sft/train_unsloth.py --model unsloth/gemma-3-4b-it-bnb-4bit \
    --chat-template gemma-3 --max-seq-len 32768

# Exportar pesos fusionados 16-bit (para desplegar) o GGUF (para llama.cpp/Ollama)
python sft/train_unsloth.py --max-seq-len 16384 --merge
python sft/train_unsloth.py --max-seq-len 16384 --save-gguf q4_k_m
```

Salidas en `sft/outputs/`: `lora_adapter/` (siempre), `merged_16bit/` y `gguf/`
(opcionales).

## Optimizaciones aplicadas (para caber en 32 GB)

- **QLoRA 4-bit** (`load_in_4bit`): el peso base ocupa ~6 GB (gemma-2-9b).
- **LoRA** r=16 sobre todas las proyecciones lineales (q,k,v,o,gate,up,down).
- **Gradient checkpointing `"unsloth"`**: clave para secuencias largas; reduce
  mucho la VRAM de activaciones.
- **Optimizador `adamw_8bit`**: estados del optimizador en 8-bit.
- **bf16** (Blackwell lo soporta nativo), `batch=1` × `grad_accum=16`
  (batch efectivo 16).
- **`train_on_responses_only`**: la pérdida se calcula SOLO sobre el JSON de
  salida (el prompt se enmascara) → mejor señal, menos cómputo desperdiciado.
- **Filtro por longitud (no truncado)**: truncar rompería el JSON; los ejemplos
  que no caben en `--max-seq-len` se descartan y se reporta la cobertura.

## Longitud de secuencia ↔ cobertura del dataset

Las casas del RAG son pequeñas; los edificios del experimento (variedad
arquitectónica fuerte: pagoda, torreón, barroco…) son grandes. Cuántos ejemplos
caben según `--max-seq-len` (estimado):

| `--max-seq-len` | RAG | Experimento | Tipos exp. | Nota |
|---|---|---|---|---|
| 4096  | 783/875 | 9/80  | 2/9 | demasiado corto |
| 8192  | 875/875 | 15/80 | 2/9 | mínimo, rápido |
| 16384 | 875/875 | 29/80 | 5/9 | **recomendado en 5090 (gemma-2-9b)** |
| 24576 | 875/875 | 45/80 | 6/9 | gemma-2-9b apurado; mejor gemma-3-4b |
| 32768 | 875/875 | 56/80 | 7/9 | usa gemma-3-4b |
| 65536 | 875/875 | 76/80 | 9/9 | requiere modelo pequeño / multi-GPU |

Para entrenar con TODAS las tipologías sin contexto enorme, otra vía es
**reducir el tamaño de los edificios del experimento** al generar el dataset:

```bash
python tools/build_sft_dataset.py --exp-voxel-cap 4000   # builds más pequeños
```

(pierde los edificios más grandes/distintivos, pero todos caben en 8k–16k).

## Probar el modelo entrenado

```bash
python sft/infer.py --prompt "A small round stone tower with a conical roof." \
    --out build.json --validate
```

Genera el JSON, lo parsea y lo valida con `tools/validate_building.py`. El JSON
resultante se puede abrir en el viewer (`tools/build_viewer_index.py` + servidor).

## Notas

- El wrapper de prompt está en `common.py` y se aplica **idéntico** en
  entrenamiento e inferencia (si lo cambias, reentrena).
- Hiperparámetros por defecto pensados para este dataset (~955 ejemplos):
  3 épocas, lr 2e-4, scheduler lineal, warmup 5%. Ajustables por CLI.
