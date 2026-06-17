#!/usr/bin/env bash
# Runs ON the Vast.ai instance. Installs deps, runs generation, writes STATUS.
# Env vars injected by eval_comparison.py: BASE_MODEL, LORA_REPO, CHAT_TEMPLATE,
# HF_TOKEN, MAX_NEW_TOKENS, MAX_SEQ_LEN
set -uo pipefail
WORK=/root/work
mkdir -p "$WORK/results"
echo RUNNING > "$WORK/gen_status"

fail() { echo "FAIL" > "$WORK/gen_status"; echo "[run_generation] FAILED at line $1"; exit 1; }
trap 'fail $LINENO' ERR

cd "$WORK"
tar xzf /root/gen_bundle.tar.gz -C "$WORK"

export PYTHONUNBUFFERED=1

pip install -q --upgrade pip

# PyTorch cu128 (Blackwell 5090)
if ! python3 - <<'PY' 2>/dev/null
import torch,sys
ok=(tuple(map(int,torch.__version__.split('.')[:2]))>=(2,7) and
    bool(torch.version.cuda) and torch.version.cuda.startswith('12.8'))
sys.exit(0 if ok else 1)
PY
then
  echo "[run_generation] installing torch cu128…"
  pip install -q torch --index-url https://download.pytorch.org/whl/cu128
fi

# vLLM (fast path – OK if install fails, Unsloth is fallback)
pip install -q vllm 2>&1 | tail -3 || echo "[run_generation] vLLM install failed – will use Unsloth"

# Unsloth + training deps (fallback)
pip install -q -r sft/requirements.txt 2>&1 | tail -3

pip install -q "huggingface_hub[cli]"

# Auth HF (new hub: `hf auth login`; legacy `huggingface-cli login` is deprecated)
if [ -n "${HF_TOKEN:-}" ]; then
  hf auth login --token "$HF_TOKEN" >/dev/null 2>&1 \
    || huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential >/dev/null 2>&1 || true
fi

# Remove hf_transfer: its fast downloader has no stall-timeout and hangs forever on
# flaky CDN paths (observed mid-shard on RTX 5090 boxes). Force the standard downloader.
pip uninstall -y hf_transfer >/dev/null 2>&1 || true
export HF_HUB_ENABLE_HF_TRANSFER=0 HF_HUB_DOWNLOAD_TIMEOUT=30

# Robust base-model predownload: a hard per-attempt timeout kills half-open hangs,
# each retry resumes from cache. Generation then loads from the warm cache (no download).
echo "[run_generation] predownloading base model $BASE_MODEL (robust, resume-on-timeout)…"
for i in $(seq 1 60); do
  if timeout 300 hf download "$BASE_MODEL" >/dev/null 2>&1; then
    echo "[run_generation] base model cached after $i attempt(s)"; break
  fi
  echo "[run_generation] base predownload attempt $i timed out/failed; resuming…"; sleep 3
done

# gcc (needed by torch.compile / inductor)
if ! command -v gcc >/dev/null 2>&1; then
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential >/dev/null 2>&1 || true
fi
export CC=$(command -v cc || command -v gcc || true)
export CXX=$(command -v c++ || command -v g++ || true)

nvidia-smi -L

echo "[run_generation] starting generation  base=$BASE_MODEL  lora=${LORA_REPO:-none}"
python3 sft/generate_on_instance.py 2>&1 | tee "$WORK/generation.log"

echo DONE > "$WORK/gen_status"
echo "[run_generation] DONE"
