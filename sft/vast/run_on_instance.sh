#!/usr/bin/env bash
# Se ejecuta DENTRO de la instancia Vast.ai. Instala deps, entrena un modelo y
# escribe /root/work/STATUS = RUNNING|DONE|FAIL para que el orquestador lo siga.
#
# Variables de entorno esperadas (las inyecta launch_vast.py por SSH):
#   MODEL, CHAT_TEMPLATE, MAX_SEQ_LEN, EPOCHS   (config del modelo)
#   HF_TOKEN     (para modelos gated como Gemma; opcional para Qwen)
#   HF_REPO      (opcional: repo HF donde subir el adapter como copia de seguridad)
#   MERGE        (opcional: "1" para exportar también pesos 16-bit fusionados)
set -uo pipefail

WORK=/root/work
mkdir -p "$WORK"
echo RUNNING > "$WORK/STATUS"
# Ante cualquier fallo, marcar FAIL (el orquestador lo detecta y destruye igual).
fail() { echo "FAIL" > "$WORK/STATUS"; echo "[run_on_instance] FALLO en línea $1"; exit 1; }
trap 'fail $LINENO' ERR

cd "$WORK"
tar xzf /root/sft_bundle.tar.gz -C "$WORK"
export PYTHONUNBUFFERED=1   # loss/logs en vivo (sin buffer de bloque)

# Compilador C: la imagen runtime no lo trae y torch.compile/inductor (Unsloth) lo necesita.
if ! command -v cc >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1; then
  echo "[run_on_instance] instalando build-essential (gcc)…"
  apt-get update -qq >/dev/null 2>&1 && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential >/dev/null 2>&1 \
    || conda install -y -q gcc_linux-64 gxx_linux-64 >/dev/null 2>&1 || true
fi
export CC=$(command -v cc || command -v gcc); export CXX=$(command -v c++ || command -v g++)

echo "[run_on_instance] modelo=$MODEL plantilla=$CHAT_TEMPLATE seq=$MAX_SEQ_LEN épocas=$EPOCHS"
nvidia-smi || true

pip install -q --upgrade pip

# PyTorch cu128 para Blackwell (5090) si la imagen no lo trae ya.
if ! python - <<'PY'
import sys
try:
    import torch
    maj, mn = map(int, torch.__version__.split('.')[:2])
    ok = (maj, mn) >= (2, 7) and bool(torch.version.cuda) and torch.version.cuda.startswith('12.8')
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
PY
then
  echo "[run_on_instance] instalando torch cu128…"
  pip install -q torch --index-url https://download.pytorch.org/whl/cu128
fi

pip install -q -r sft/requirements.txt
pip install -q "huggingface_hub[cli]"

# Autenticación HF (necesaria para Gemma gated; inofensiva si no hay token).
if [ -n "${HF_TOKEN:-}" ]; then
  huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential >/dev/null 2>&1 || true
fi

MERGE_FLAG=""
[ "${MERGE:-0}" = "1" ] && MERGE_FLAG="--merge"
STEPS_FLAG=""
[ "${MAX_STEPS:-0}" != "0" ] && STEPS_FLAG="--max-steps ${MAX_STEPS}"

# Entrenamiento (log en vivo a train.log; el orquestador lo descarga).
python sft/train_unsloth.py \
  --model "$MODEL" \
  --chat-template "$CHAT_TEMPLATE" \
  --max-seq-len "$MAX_SEQ_LEN" \
  --epochs "$EPOCHS" \
  --out "$WORK/outputs" \
  $STEPS_FLAG $MERGE_FLAG 2>&1 | tee "$WORK/train.log"

# Copia de seguridad opcional en Hugging Face Hub.
if [ -n "${HF_REPO:-}" ] && [ -n "${HF_TOKEN:-}" ]; then
  echo "[run_on_instance] subiendo adapter a $HF_REPO…"
  huggingface-cli upload "$HF_REPO" "$WORK/outputs/lora_adapter" . \
    --repo-type model --private 2>&1 | tail -5 || true
fi

echo DONE > "$WORK/STATUS"
echo "[run_on_instance] LISTO."
