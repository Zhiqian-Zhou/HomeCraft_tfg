#!/usr/bin/env bash
# Babysitter for the ORPHANED qwen3.5-9b eval instance (39503843).
# The active orchestrator (eval_comparison.py --only gemma) does NOT track it,
# so this loop polls gen_status, downloads results, and destroys the instance.
set -uo pipefail

IID=39503843
HOST=ssh3.vast.ai
PORT=23842
ROOT=${HOMECRAFT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
DST="$ROOT/scratch/eval_comparison/qwen3.5-9b"
LOG="$ROOT/scratch/_babysit_qwen.log"
SSH="ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20 -o BatchMode=yes -p $PORT root@$HOST"
SCP="scp -P $PORT -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=20 -o BatchMode=yes"

mkdir -p "$DST"
say() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }

say "babysitter start for qwen instance $IID"
DEADLINE=$(( $(date +%s) + 9000 ))   # 2.5h hard cap
last=""
while true; do
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then say "TIMEOUT"; st="TIMEOUT"; break; fi
  st=$($SSH 'cat /root/work/gen_status 2>/dev/null || echo BOOT' 2>/dev/null | tr -d '[:space:]')
  [ -z "$st" ] && st="UNREACHABLE"
  if [ "$st" != "$last" ]; then say "gen_status=$st"; last="$st"; fi
  case "$st" in DONE|FAIL) break;; esac
  sleep 60
done

say "collecting results (status=$st)…"
$SCP -r "root@$HOST:/root/work/results" "$DST/" 2>>"$LOG" || say "results scp failed"
$SCP "root@$HOST:/root/work/generation.log" "$DST/generation.log" 2>>"$LOG" || true
$SCP "root@$HOST:/root/boot.log" "$DST/boot.log" 2>>"$LOG" || true

say "destroying instance ${IID}..."
vastai destroy instance "${IID}" >>"$LOG" 2>&1 && say "instance ${IID} DESTROYED" || say "!! destroy failed for ${IID}"

say "babysitter done (final status=$st)"
