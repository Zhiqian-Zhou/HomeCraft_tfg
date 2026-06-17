#!/usr/bin/env python3
"""Chequeo de salud de los entrenamientos SFT en Vast (para el loop de 3 min).

Lee scratch/sft_jobs.json {key: {instance,host,port,model,hf_repo}}, y por cada
job: estado vía SSH (STATUS, últimas líneas de loss, errores, uso de GPU) y si la
instancia sigue viva en Vast. Imprime un informe compacto a stdout.

Salida pensada para redirigir a fichero y leerla (evita el tmpfs lleno del host).
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
JOBS = ROOT / "scratch" / "sft_jobs.json"


def ssh(host, port, cmd, timeout=25):
    p = subprocess.run(
        ["ssh", "-p", str(port), f"root@{host}",
         "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
         "-o", "ConnectTimeout=20", cmd],
        capture_output=True, text=True, timeout=timeout)
    return p.stdout.strip(), p.stderr.strip()


def alive_instances():
    try:
        out = subprocess.run(["vastai", "show", "instances", "--raw"],
                             capture_output=True, text=True).stdout
        i = out.find("[")
        data = json.loads(out[i:]) if i >= 0 else []
        return {x.get("id"): x.get("cur_state") for x in data}
    except Exception:
        return {}


def check(key, j, alive):
    iid = j["instance"]
    state = alive.get(iid, "NO-EXISTE")
    line = [f"== {key}  inst={iid}  vast_state={state}"]
    if state in ("NO-EXISTE", None):
        line.append("   (instancia no está en Vast)")
        return "\n".join(line), "GONE"
    try:
        remote = (
            "echo ST=$(cat /root/work/STATUS 2>/dev/null || echo NONE); "
            "echo GPU=$(nvidia-smi --query-gpu=utilization.gpu,memory.used "
            "--format=csv,noheader,nounits 2>/dev/null | head -1); "
            "echo PROG=$(tr '\\r' '\\n' < /root/work/train.log 2>/dev/null | grep -aoE '[0-9]+/[0-9]+ \\[' | tail -1); "
            "echo '--LOSS--'; tr '\\r' '\\n' < /root/work/train.log 2>/dev/null | grep -aoE \"loss[=: ]+[0-9.eE+-]+\" | tail -3; "
            "grep -aoE \"\\{'loss': [0-9.eE+-]+.*?\\}\" /root/work/train.log 2>/dev/null | tail -2; "
            "echo '--ERR--'; grep -aiE 'error|traceback|not support|out of memory|nan|assert|killed' "
            "/root/work/train.log /root/boot.log 2>/dev/null | tail -4"
        )
        out, err = ssh(j["host"], j["port"], remote)
    except Exception as e:
        line.append(f"   SSH falló: {e}")
        return "\n".join(line), "SSH-FAIL"

    st = "NONE"
    m = re.search(r"ST=(\w+)", out)
    if m:
        st = m.group(1)
    g = re.search(r"GPU=([\d, ]+)", out)
    losses = re.findall(r"'loss': ([0-9.eE+-]+)", out)
    errseg = out.split("--ERR--")[-1].strip() if "--ERR--" in out else ""
    line.append(f"   STATUS={st}  GPU={g.group(1).strip() if g else '?'}  "
                f"loss_recientes={losses if losses else '—'}")
    # señales de colapso
    collapsed = any(l.lower() in ("nan", "inf") for l in losses)
    if collapsed:
        line.append("   ⚠️ LOSS COLAPSADA (nan/inf)")
    if errseg:
        line.append("   errs: " + errseg.replace("\n", " | ")[:300])
    health = st
    if collapsed:
        health = "COLLAPSED"
    return "\n".join(line), health


def main():
    if not JOBS.exists():
        print("(no hay scratch/sft_jobs.json)")
        return
    jobs = json.loads(JOBS.read_text())
    alive = alive_instances()
    summary = []
    for key, j in jobs.items():
        rep, health = check(key, j, alive)
        print(rep)
        summary.append((key, health))
    print("\nRESUMEN:", ", ".join(f"{k}={h}" for k, h in summary))


if __name__ == "__main__":
    main()
