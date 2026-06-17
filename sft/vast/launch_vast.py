#!/usr/bin/env python3
"""Orquestador Vast.ai: entrena cada modelo en su propia 5090 y la destruye al acabar.

Para cada modelo de models.json, en paralelo:
  1. busca una oferta de RTX 5090 (1 GPU) barata y fiable,
  2. crea la instancia,
  3. copia por SSH el código + el dataset (bundle.tar.gz),
  4. lanza el entrenamiento (run_on_instance.sh) en segundo plano,
  5. sondea STATUS hasta DONE/FAIL,
  6. descarga el adapter entrenado y el log,
  7. **destruye la instancia** (siempre, también si falla — para no gastar de más).

Requisitos locales:
  - `vastai` CLI instalado y autenticado:  pip install vastai; vastai set api-key <KEY>
  - Tu clave SSH pública registrada en Vast (cuenta → SSH Keys, o `vastai create ssh-key`).
  - El dataset generado:  python tools/build_sft_dataset.py
  - Para Gemma (gated): export HF_TOKEN=hf_...   (acepta la licencia en HF antes)

Uso:
  export HF_TOKEN=hf_xxx
  python sft/vast/launch_vast.py                       # los 3 modelos en paralelo
  python sft/vast/launch_vast.py --only qwen3.5-9b     # solo uno
  python sft/vast/launch_vast.py --dry-run             # enseña ofertas y plan, no crea nada
  python sft/vast/launch_vast.py --hf-repo-prefix usuario/homecraft-sft  # backup en HF
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent                 # raíz del repo
DATA = ROOT / "scratch" / "sft"
MODELS_JSON = HERE / "models.json"
OUT_LOCAL = ROOT / "sft" / "outputs_vast"

# Imagen base con CUDA 12.8 (necesaria para Blackwell/5090).
DEFAULT_IMAGE = "pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime"  # más pequeña → arranca antes
DEFAULT_QUERY = "gpu_name=RTX_5090 num_gpus=1 rentable=true cuda_vers>=12.8 disk_space>=100"
DISK_GB = 100
POLL_SEC = 30
BOOT_TIMEOUT = 300        # 5 min para que arranque/dé SSH; si no, se destruye y se prueba otra
TRAIN_TIMEOUT = 6 * 3600  # s máximos de entrenamiento por modelo

_print_lock = threading.Lock()
_offer_lock = threading.Lock()
_used_offers: set = set()


def log(key: str, msg: str):
    with _print_lock:
        print(f"[{key}] {msg}", flush=True)


def vastai(*args, raw=True, check=True) -> str:
    cmd = ["vastai", *map(str, args)]
    if raw and "--raw" not in cmd:
        cmd.append("--raw")
    p = subprocess.run(cmd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"vastai {' '.join(map(str,args))} -> {p.stderr.strip()}")
    return p.stdout.strip()


def _strip_to_json(s: str) -> str:
    """Quita líneas previas al primer carácter JSON (avisos DEPRECATED, etc.)."""
    for i, ch in enumerate(s):
        if ch in "[{":
            return s[i:]
    return s


def vastai_json(*args):
    return json.loads(_strip_to_json(vastai(*args)))


def make_bundle() -> Path:
    """tar.gz con sft/ (código) + el dataset jsonl, preservando rutas relativas."""
    train = DATA / "sft_train.jsonl"
    val = DATA / "sft_val.jsonl"
    if not train.exists():
        sys.exit(f"No existe {train}. Genera el dataset: python tools/build_sft_dataset.py")
    bundle = HERE / "sft_bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        # código (excluye outputs y caches)
        for p in sorted((ROOT / "sft").rglob("*")):
            if any(part in ("outputs", "outputs_vast", "__pycache__", "sft_bundle.tar.gz")
                   for part in p.relative_to(ROOT).parts):
                continue
            if p.is_file():
                tar.add(p, arcname=str(p.relative_to(ROOT)))
        # dataset (gitignored, va aparte)
        tar.add(train, arcname="scratch/sft/sft_train.jsonl")
        if val.exists():
            tar.add(val, arcname="scratch/sft/sft_val.jsonl")
    log("bundle", f"creado {bundle} ({bundle.stat().st_size/1e6:.1f} MB)")
    return bundle


# Tiers (reliability, inet_down Mbps, inet_up Mbps): de más exigente a menos.
# Dentro de cada tier elegimos la MÁS BARATA → barato + estable + ancho de banda.
_OFFER_TIERS = [(0.98, 500, 100), (0.97, 300, 50), (0.95, 150, 30), (0.90, 0, 0)]


def pick_offer(query: str) -> dict:
    offers = vastai_json("search", "offers", query, "-o", "dph_total")
    if not offers:
        raise RuntimeError(f"sin ofertas para: {query}")

    def passes(o, rel, down, up):
        return (o.get("reliability2", 0) >= rel
                and o.get("cuda_max_good", 0) >= 12.8
                and o.get("inet_down", 0) >= down
                and o.get("inet_up", 0) >= up)

    # En paralelo, cada modelo coge una oferta DISTINTA (no dos instancias en la
    # misma máquina). Reservamos ids de forma atómica.
    with _offer_lock:
        for rel, down, up in _OFFER_TIERS:
            cand = [o for o in offers
                    if passes(o, rel, down, up) and o["id"] not in _used_offers]
            if cand:
                cand.sort(key=lambda o: o.get("dph_total", 9e9))
                o = cand[0]
                _used_offers.add(o["id"])
                return o
        # último recurso: la más barata no usada, sin filtros
        for o in sorted(offers, key=lambda o: o.get("dph_total", 9e9)):
            if o["id"] not in _used_offers:
                _used_offers.add(o["id"])
                return o
    raise RuntimeError("no quedan ofertas libres distintas para todos los modelos")


def create_instance(offer_id: int, image: str, label: str) -> int:
    out = vastai("create", "instance", offer_id, "--image", image,
                 "--disk", DISK_GB, "--ssh",
                 "--label", label,
                 "--onstart-cmd", "touch /root/.provisioned; sleep infinity")
    info = json.loads(_strip_to_json(out))
    iid = info.get("new_contract") or info.get("id")
    if not iid:
        raise RuntimeError(f"create sin id: {out}")
    return int(iid)


def attach_ssh_key(iid: int, pubkey_path: str):
    """Adjunta la clave pública local a la instancia (necesario para SSH/scp)."""
    pub = Path(pubkey_path).expanduser().read_text().strip()
    vastai("attach", "ssh", iid, pub, raw=False, check=False)


def get_instance(iid: int) -> dict:
    # 'show instance' (singular) crashea si start_date es None; usamos la lista.
    for i in vastai_json("show", "instances"):
        if i.get("id") == iid:
            return i
    return {}


def destroy_instance(iid: int):
    vastai("destroy", "instance", iid, "-y", raw=False, check=False)


def wait_ssh(iid: int) -> tuple[str, int]:
    t0 = time.time()
    while time.time() - t0 < BOOT_TIMEOUT:
        inf = get_instance(iid)
        # cur_state es el campo fiable ("running"); actual_status puede venir None.
        running = inf.get("cur_state") == "running" or inf.get("actual_status") == "running"
        if running and inf.get("ssh_host") and inf.get("ssh_port"):
            return inf["ssh_host"], int(inf["ssh_port"])
        time.sleep(POLL_SEC)
    raise TimeoutError(f"instancia {iid} no dio SSH en {BOOT_TIMEOUT}s")


def _ssh_base(host: str, port: int) -> list[str]:
    return ["ssh", "-p", str(port), f"root@{host}",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=20"]


def ssh_run(host: str, port: int, command: str, check=True) -> str:
    p = subprocess.run(_ssh_base(host, port) + [command],
                       capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"ssh '{command[:60]}...' -> {p.stderr.strip()}")
    return p.stdout.strip()


def scp_to(host: str, port: int, local: Path, remote: str):
    subprocess.run(["scp", "-P", str(port), "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null", str(local),
                    f"root@{host}:{remote}"], check=True)


def scp_from(host: str, port: int, remote: str, local: Path, recursive=True):
    local.parent.mkdir(parents=True, exist_ok=True)
    flags = ["-r"] if recursive else []
    subprocess.run(["scp", "-P", str(port), "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null", *flags,
                    f"root@{host}:{remote}", str(local)], check=False)


def wait_ssh_ready(host: str, port: int):
    """Espera a que el sshd acepte conexiones (tras 'running' puede tardar)."""
    t0 = time.time()
    while time.time() - t0 < 300:
        p = subprocess.run(_ssh_base(host, port) + ["echo ok"],
                           capture_output=True, text=True)
        if p.returncode == 0 and "ok" in p.stdout:
            return
        time.sleep(10)
    raise TimeoutError("sshd no respondió")


def run_model(m: dict, bundle: Path, args) -> dict:
    key = m["key"]
    label = f"sft-{key}"
    iid = None
    result = {"key": key, "model": m["model"], "status": "?", "instance": None}
    try:
        offer = pick_offer(args.query)
        log(key, f"oferta {offer['id']} {offer.get('gpu_name')} "
                 f"${offer.get('dph_total'):.3f}/h reliab={offer.get('reliability2'):.3f} "
                 f"down={offer.get('inet_down',0):.0f}Mbps up={offer.get('inet_up',0):.0f}Mbps")
        if args.dry_run:
            result["status"] = "dry-run"
            return result

        # Aprovisionar con reintento ENTRE PROVEEDORES: si una instancia tarda
        # demasiado en arrancar o falla, se DESTRUYE y se prueba otra oferta.
        iid = host = port = None
        for prov in range(args.max_providers):
            try:
                iid = create_instance(offer["id"], args.image, label)
            except Exception as e:
                log(key, f"create falló en oferta {offer['id']} ({e}); otro proveedor…")
                offer = pick_offer(args.query)
                continue
            result["instance"] = iid
            attach_ssh_key(iid, args.ssh_key)
            log(key, f"instancia {iid} (oferta {offer['id']}); esperando SSH…")
            try:
                host, port = wait_ssh(iid)
                wait_ssh_ready(host, port)
                break
            except TimeoutError:
                log(key, f"instancia {iid} tardó demasiado en arrancar; "
                         f"la destruyo y pruebo otro proveedor")
                destroy_instance(iid)
                iid = host = None
                offer = pick_offer(args.query)
        if iid is None or host is None:
            raise RuntimeError(f"ningún proveedor arrancó a tiempo ({args.max_providers} intentos)")
        log(key, f"SSH {host}:{port} listo; copiando bundle…")

        scp_to(host, port, bundle, "/root/sft_bundle.tar.gz")
        scp_to(host, port, HERE / "run_on_instance.sh", "/root/run_on_instance.sh")

        seq = args.smoke_seq if args.smoke else m["max_seq_len"]
        env = (f"MODEL='{m['model']}' CHAT_TEMPLATE='{m['chat_template']}' "
               f"MAX_SEQ_LEN={seq} EPOCHS={m['epochs']} "
               f"MAX_STEPS={args.smoke if args.smoke else 0} "
               f"MERGE={1 if args.merge else 0} ")
        if os.environ.get("HF_TOKEN"):
            env += f"HF_TOKEN='{os.environ['HF_TOKEN']}' "
        # Subir el modelo entrenado a HF (no durante el smoke-test).
        if args.hf_repo_prefix and not args.smoke:
            env += f"HF_REPO='{args.hf_repo_prefix}-{key}' "
        ssh_run(host, port,
                f"chmod +x /root/run_on_instance.sh; "
                f"nohup env {env} bash /root/run_on_instance.sh "
                f">/root/boot.log 2>&1 & echo lanzado")
        log(key, "entrenamiento lanzado; sondeando STATUS…")

        t0 = time.time()
        last = ""
        while time.time() - t0 < TRAIN_TIMEOUT:
            time.sleep(POLL_SEC)
            st = ssh_run(host, port, "cat /root/work/STATUS 2>/dev/null || echo BOOT",
                         check=False)
            if st != last:
                log(key, f"STATUS={st}")
                last = st
            if st in ("DONE", "FAIL"):
                break
        else:
            log(key, "TIMEOUT de entrenamiento")
            last = "TIMEOUT"

        # Descargar resultados y logs SIEMPRE que se pueda.
        dst = OUT_LOCAL / key
        log(key, f"descargando resultados a {dst}…")
        scp_from(host, port, "/root/work/outputs", dst)
        scp_from(host, port, "/root/work/train.log", dst / "train.log", recursive=False)
        scp_from(host, port, "/root/boot.log", dst / "boot.log", recursive=False)
        result["status"] = last
        return result

    except Exception as e:
        log(key, f"ERROR: {e}")
        result["status"] = f"error: {e}"
        return result
    finally:
        if iid is not None and not args.dry_run:
            if result["status"] != "DONE" and args.keep_on_fail:
                log(key, f"NO destruyo {iid} (--keep-on-fail). Recuerda: vastai destroy instance {iid}")
            else:
                try:
                    destroy_instance(iid)
                    log(key, f"instancia {iid} DESTRUIDA")
                except Exception as e:
                    log(key, f"!! no pude destruir {iid}: {e} -> hazlo a mano: vastai destroy instance {iid} -y")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", action="append", default=None,
                    help="entrena solo este(os) key de models.json (repetible)")
    ap.add_argument("--image", default=DEFAULT_IMAGE)
    ap.add_argument("--ssh-key", default="~/.ssh/id_ed25519.pub",
                    help="clave pública local a adjuntar a cada instancia")
    ap.add_argument("--max-providers", type=int, default=4,
                    help="nº de proveedores a probar si una instancia no arranca")
    ap.add_argument("--query", default=DEFAULT_QUERY,
                    help="consulta de ofertas vastai (gpu_name=RTX_5090 …)")
    ap.add_argument("--merge", action="store_true",
                    help="exportar también pesos 16-bit fusionados en la instancia")
    ap.add_argument("--hf-repo-prefix", default="Chengheng/Homecraft",
                    help="prefijo de repo HF donde subir cada modelo (se añade -<key>)")
    ap.add_argument("--keep-on-fail", action="store_true",
                    help="no destruir la instancia si el entrenamiento falla (debug)")
    ap.add_argument("--dry-run", action="store_true",
                    help="solo buscar ofertas y mostrar el plan")
    ap.add_argument("--smoke", type=int, default=0, metavar="N",
                    help="smoke-test: entrena solo N pasos (p.ej. 8) para validar el ciclo")
    ap.add_argument("--smoke-seq", type=int, default=4096,
                    help="max_seq_len reducido durante el smoke-test (default 4096)")
    ap.add_argument("--sequential", action="store_true",
                    help="entrenar de uno en uno en vez de en paralelo")
    args = ap.parse_args()

    models = json.loads(MODELS_JSON.read_text())
    if args.only:
        models = [m for m in models if m["key"] in args.only]
        if not models:
            sys.exit(f"--only no coincide. Keys: {[m['key'] for m in json.loads(MODELS_JSON.read_text())]}")

    # comprobaciones rápidas
    if subprocess.run(["which", "vastai"], capture_output=True).returncode != 0:
        sys.exit("falta el CLI 'vastai' (pip install vastai && vastai set api-key <KEY>)")
    if any(m.get("gated") for m in models) and not os.environ.get("HF_TOKEN") and not args.dry_run:
        log("aviso", "modelos gated (Gemma) sin HF_TOKEN: fallará la descarga. export HF_TOKEN=hf_…")

    bundle = make_bundle() if not args.dry_run else (HERE / "sft_bundle.tar.gz")
    log("plan", f"{len(models)} modelo(s): {[m['key'] for m in models]} "
                f"({'secuencial' if args.sequential else 'paralelo'})")

    results = []
    if args.sequential:
        for m in models:
            results.append(run_model(m, bundle, args))
    else:
        threads, out = [], {}
        for m in models:
            t = threading.Thread(target=lambda mm: out.__setitem__(mm["key"], run_model(mm, bundle, args)),
                                 args=(m,))
            t.start(); threads.append(t)
        for t in threads:
            t.join()
        results = list(out.values())

    print("\n===== RESUMEN =====")
    for r in results:
        print(f"  {r['key']:14} {r['status']:10} instancia={r.get('instance')}")
    print(f"resultados en {OUT_LOCAL}/")


if __name__ == "__main__":
    main()
