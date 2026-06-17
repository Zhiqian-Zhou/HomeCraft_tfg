# Entrenar los 3 modelos en Vast.ai (una RTX 5090 por modelo)

Automatiza: por cada modelo, **alquila una 5090**, copia código+dataset, entrena
con Unsloth (QLoRA), descarga el adapter y **destruye la instancia al terminar**
(también si falla, para no gastar de más). Los 3 corren en paralelo por defecto.

## Modelos (`models.json`)

| key | modelo | plantilla | max_seq_len |
|---|---|---|---|
| `gemma-4-e2b` | `google/gemma-4-E2B-it` | gemma-3 | 8192 |
| `gemma-4-e4b` | `google/gemma-4-E4B-it` | gemma-3 | 8192 |
| `qwen3.5-9b`  | `Qwen/Qwen3.5-9B`       | qwen3   | 8192 |

(`max_seq_len` por modelo según su tamaño; edítalo en `models.json` si quieres
más/menos cobertura del dataset — ver tabla en `../README.md`.)

## Requisitos (en tu máquina local)

```bash
pip install vastai
vastai set api-key <TU_API_KEY_VAST>

# Tu clave SSH pública registrada en Vast (cuenta → SSH Keys), p.ej.:
vastai create ssh-key "$(cat ~/.ssh/id_ed25519.pub)"

# Dataset generado (si no lo está):
python tools/build_sft_dataset.py

# Token de Hugging Face (Gemma es gated: acepta la licencia en su página HF antes)
export HF_TOKEN=hf_xxxxxxxx
```

## Lanzar

```bash
# 1) Ver ofertas y plan SIN crear nada (recomendado primero)
python sft/vast/launch_vast.py --dry-run

# 2) Entrenar los 3 en paralelo (una 5090 cada uno; se destruyen al acabar)
python sft/vast/launch_vast.py

# Variantes
python sft/vast/launch_vast.py --only qwen3.5-9b           # solo uno
python sft/vast/launch_vast.py --sequential                # de uno en uno
python sft/vast/launch_vast.py --merge                     # exporta 16-bit fusionado
python sft/vast/launch_vast.py --hf-repo-prefix usuario/homecraft-sft  # backup en HF
python sft/vast/launch_vast.py --keep-on-fail              # no destruir si falla (debug)
```

## Qué hace por cada modelo

1. `vastai search offers "gpu_name=RTX_5090 num_gpus=1 …"` → elige la más barata y fiable.
2. `vastai create instance` con imagen CUDA 12.8 (Blackwell) y SSH.
3. Espera a que dé SSH, copia `sft_bundle.tar.gz` (código `sft/` + `sft_train/val.jsonl`) y `run_on_instance.sh`.
4. Lanza `run_on_instance.sh` (instala torch cu128 + Unsloth, login HF, entrena, opcional push a HF).
5. Sondea `/root/work/STATUS` hasta `DONE`/`FAIL`.
6. Descarga `outputs/` (adapter LoRA) + `train.log` a `sft/outputs_vast/<key>/`.
7. **`vastai destroy instance`** (en `finally`: se destruye sí o sí, salvo `--keep-on-fail`).

## Resultados

```
sft/outputs_vast/
├── gemma-4-e2b/  (lora_adapter/, train.log, boot.log)
├── gemma-4-e4b/
└── qwen3.5-9b/
```

Probar uno: `python sft/infer.py --adapter sft/outputs_vast/qwen3.5-9b/lora_adapter \
--chat-template qwen3 --prompt "A small round stone tower." --validate`

## Seguridad de costes

- La instancia se **destruye en el bloque `finally`**: aunque el entrenamiento
  falle o haya excepción, se libera (a menos que pongas `--keep-on-fail`).
- Si el orquestador muere de golpe (Ctrl-C duro, caída de red), comprueba a mano:
  `vastai show instances` y `vastai destroy instance <id>`.
- `--hf-repo-prefix` sube el adapter a HF como copia de seguridad por si pierdes
  la conexión antes de descargarlo.

## Notas

- **Blackwell/5090** exige CUDA 12.8 + PyTorch ≥ 2.7 (cu128); la imagen por
  defecto ya lo trae y el script reinstala torch cu128 si hiciera falta.
- **Gemma gated:** sin `HF_TOKEN` (y sin aceptar la licencia en HF) la descarga
  del modelo falla → la instancia se marca FAIL y se destruye.
- El dataset viaja en el bundle por SSH (no hace falta repo git en la instancia).
- Si una clase de oferta no aparece, ajusta `--query` (p.ej. baja
  `disk_space>=100` o quita `cuda_vers>=12.8`).
