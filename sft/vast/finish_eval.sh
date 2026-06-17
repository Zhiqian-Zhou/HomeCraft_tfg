#!/usr/bin/env bash
# Waits until all 3 eval models are collected (gemma via PID-tracked orchestrator,
# qwen via babysit_qwen.sh), then scores ALL of them into COMPARISON.md.
set -uo pipefail
ROOT=${HOMECRAFT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
OUT="$ROOT/scratch/eval_comparison"
LOG="$ROOT/scratch/_finish_eval.log"
say() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

KEYS="gemma-4-e2b gemma-4-e4b qwen3.5-9b"
DEADLINE=$(( $(date +%s) + 10800 ))   # 3h hard cap

say "finisher waiting for results: $KEYS"
while true; do
  ready=0
  for k in $KEYS; do
    [ -f "$OUT/$k/results/base.jsonl" ] && ready=$((ready+1))
  done
  gemma_orch=$(pgrep -f "eval_comparison.py" | head -1 || true)
  if [ "$ready" -ge 3 ] && [ -z "$gemma_orch" ]; then
    say "all 3 collected and orchestrator exited"; break
  fi
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    say "DEADLINE reached; scoring with whatever exists ($ready/3)"; break
  fi
  say "ready=$ready/3 orch_alive=${gemma_orch:-no}; sleeping 90s"
  sleep 90
done

say "running final all-3 scoring (--skip-vast)…"
cd "$ROOT"
python3 sft/vast/eval_comparison.py --skip-vast >>"$LOG" 2>&1 || say "scoring errored"
say "DONE — see $OUT/COMPARISON.md"
