#!/usr/bin/env python3
"""Compare base-model vs SFT HomeCraft buildings on Vast.ai.

For each of the 3 model families:
  1. Provision a RTX 5090 Vast instance.
  2. Upload code bundle + run generate_on_instance.py (base + SFT, 10 prompts each).
  3. Download 20 result files.
  4. Destroy the instance.
  5. Score ALL results locally with the 5-family evaluator (no GPU needed).
  6. Print and save a comparison table (base vs SFT, by model and by prompt).

Runs the 3 model families in parallel (3 instances simultaneously).

Usage:
  export HF_TOKEN=hf_...          # for private SFT repos + gated Gemma
  python sft/vast/eval_comparison.py
  python sft/vast/eval_comparison.py --only qwen3.5-9b
  python sft/vast/eval_comparison.py --dry-run
  python sft/vast/eval_comparison.py --skip-vast   # score already-downloaded results
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, tarfile, threading, time
from pathlib import Path

ROOT  = Path(__file__).resolve().parent.parent.parent
HERE  = Path(__file__).resolve().parent
OUT   = ROOT / "scratch" / "eval_comparison"
OUT.mkdir(parents=True, exist_ok=True)

# Re-use Vast helpers from launch_vast.py
sys.path.insert(0, str(HERE))
from launch_vast import (  # noqa: E402
    pick_offer, create_instance, attach_ssh_key, wait_ssh, wait_ssh_ready,
    destroy_instance, vastai_json, _used_offers, _offer_lock, log,
)

DEFAULT_IMAGE = "pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime"
DEFAULT_QUERY = "gpu_name=RTX_5090 num_gpus=1 rentable=true cuda_vers>=12.8 disk_space>=100"
BOOT_TIMEOUT  = 300
POLL_SEC      = 30
GEN_TIMEOUT   = 2 * 3600   # 2 h per model (9B models are slow)

MODELS = {
    "gemma-4-e2b": {
        "base_model":    "google/gemma-4-E2B-it",
        "lora_repo":     "Chengheng/Homecraft-gemma-4-e2b",
        "chat_template": "gemma-3",
        "max_seq_len":   8192,
    },
    "gemma-4-e4b": {
        "base_model":    "google/gemma-4-E4B-it",
        "lora_repo":     "Chengheng/Homecraft-gemma-4-e4b",
        "chat_template": "gemma-3",
        "max_seq_len":   8192,
    },
    "qwen3.5-9b": {
        "base_model":    "Qwen/Qwen3.5-9B",
        "lora_repo":     "Chengheng/Homecraft-qwen3.5-9b",
        "chat_template": "qwen3",
        "max_seq_len":   8192,
    },
}

_print_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Bundle builder
# ---------------------------------------------------------------------------

def make_bundle() -> Path:
    """Bundle only what the generation script needs: sft/ + pipeline/ Python."""
    bundle = HERE / "gen_bundle.tar.gz"
    with tarfile.open(bundle, "w:gz") as tar:
        # sft/ code (no outputs, no large safetensors)
        for p in sorted((ROOT / "sft").rglob("*")):
            if any(part in ("outputs", "outputs_vast", "__pycache__",
                            "sft_bundle.tar.gz", "gen_bundle.tar.gz")
                   for part in p.relative_to(ROOT).parts):
                continue
            if p.suffix in (".safetensors", ".bin", ".gguf"):
                continue
            if p.is_file():
                tar.add(p, arcname=str(p.relative_to(ROOT)))
        # pipeline Python (for evaluator on instance if ever needed)
        for p in sorted((ROOT / "pipeline").rglob("*.py")):
            if "__pycache__" not in str(p):
                tar.add(p, arcname=str(p.relative_to(ROOT)))
    log("bundle", f"created {bundle} ({bundle.stat().st_size/1e6:.1f} MB)")
    return bundle


# ---------------------------------------------------------------------------
# SSH helpers
# ---------------------------------------------------------------------------

def _ssh_base(host, port):
    return ["ssh", "-p", str(port), f"root@{host}",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=20"]

def ssh_run(host, port, cmd, check=True):
    p = subprocess.run(_ssh_base(host, port) + [cmd], capture_output=True, text=True)
    if check and p.returncode != 0:
        raise RuntimeError(f"ssh '{cmd[:60]}' -> {p.stderr.strip()}")
    return p.stdout.strip()

def scp_to(host, port, local, remote):
    subprocess.run(["scp", "-P", str(port), "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null", str(local),
                    f"root@{host}:{remote}"], check=True)

def scp_from(host, port, remote, local, recursive=True):
    Path(local).parent.mkdir(parents=True, exist_ok=True)
    flags = ["-r"] if recursive else []
    subprocess.run(["scp", "-P", str(port), "-o", "StrictHostKeyChecking=no",
                    "-o", "UserKnownHostsFile=/dev/null", *flags,
                    f"root@{host}:{remote}", str(local)], check=False)


# ---------------------------------------------------------------------------
# Run one model family on a Vast instance
# ---------------------------------------------------------------------------

def run_model(key: str, m: dict, bundle: Path, args) -> dict:
    result = {"key": key, "status": "?", "instance": None}
    iid = host = port = None
    try:
        offer = pick_offer(args.query)
        log(key, f"offer {offer['id']} {offer.get('gpu_name')} "
                 f"${offer.get('dph_total'):.3f}/h reliab={offer.get('reliability2'):.3f}")
        if args.dry_run:
            result["status"] = "dry-run"
            return result

        for attempt in range(3):
            try:
                iid = create_instance(offer["id"], args.image, f"eval-{key}")
                break
            except Exception as e:
                log(key, f"create failed ({e}), retrying…")
                offer = pick_offer(args.query)
        if iid is None:
            raise RuntimeError("could not create instance after 3 attempts")
        result["instance"] = iid
        attach_ssh_key(iid, args.ssh_key)
        log(key, f"instance {iid}; waiting for SSH…")
        host, port = wait_ssh(iid)
        wait_ssh_ready(host, port)

        log(key, f"SSH {host}:{port} ready; copying bundle…")
        scp_to(host, port, bundle, "/root/gen_bundle.tar.gz")
        scp_to(host, port, HERE / "run_generation.sh", "/root/run_generation.sh")

        env = (f"BASE_MODEL='{m['base_model']}' "
               f"LORA_REPO='{m['lora_repo']}' "
               f"CHAT_TEMPLATE='{m['chat_template']}' "
               f"MAX_SEQ_LEN={m['max_seq_len']} "
               f"MAX_NEW_TOKENS=4096 ")
        if os.environ.get("HF_TOKEN"):
            env += f"HF_TOKEN='{os.environ['HF_TOKEN']}' "

        ssh_run(host, port,
                f"chmod +x /root/run_generation.sh; "
                f"nohup env {env} bash /root/run_generation.sh "
                f">/root/boot.log 2>&1 & echo launched")
        log(key, "generation launched; polling gen_status…")

        t0 = time.time()
        last = ""
        while time.time() - t0 < GEN_TIMEOUT:
            time.sleep(POLL_SEC)
            st = ssh_run(host, port,
                         "cat /root/work/gen_status 2>/dev/null || echo BOOT",
                         check=False)
            if st != last:
                log(key, f"gen_status={st}")
                last = st
            if st in ("DONE", "FAIL"):
                break
        else:
            log(key, "TIMEOUT")
            last = "TIMEOUT"

        # Download results regardless
        dst = OUT / key
        dst.mkdir(exist_ok=True)
        log(key, f"downloading results to {dst}…")
        scp_from(host, port, "/root/work/results", dst, recursive=True)
        scp_from(host, port, "/root/work/generation.log", dst / "generation.log", recursive=False)
        scp_from(host, port, "/root/boot.log", dst / "boot.log", recursive=False)
        result["status"] = last
        return result

    except Exception as e:
        log(key, f"ERROR: {e}")
        result["status"] = f"error: {e}"
        return result
    finally:
        if iid is not None and not args.dry_run:
            try:
                destroy_instance(iid)
                log(key, f"instance {iid} DESTROYED")
            except Exception as e:
                log(key, f"!! could not destroy {iid}: {e}")


# ---------------------------------------------------------------------------
# Local scoring
# ---------------------------------------------------------------------------

def score_building(building: dict | None) -> dict | None:
    if building is None:
        return None
    try:
        sys.path.insert(0, str(ROOT))
        from pipeline.agents.evaluator import evaluate
        report = evaluate(building, run_critique=False)
        comp = report.get("composite") or {}
        return {
            "overall":          comp.get("overall"),
            "physical_total":   comp.get("physical_total"),
            "alexander_total":  comp.get("alexander_total"),
            "interior_total":   comp.get("interior_total"),
            "exterior_total":   comp.get("exterior_total"),
            "prompt_total":     comp.get("prompt_adherence_total"),
        }
    except Exception as e:
        return {"error": str(e)}


def load_and_score(key: str) -> list[dict]:
    scored = []
    for variant in ("base", "sft"):
        path = OUT / key / "results" / f"{variant}.jsonl"
        if not path.exists():
            log(key, f"missing {variant}.jsonl – skipping")
            continue
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            scores = score_building(r.get("building"))
            scored.append({
                "key": key, "variant": variant,
                "prompt_key": r.get("prompt_key"),
                "parse_ok": r.get("parse_ok", False),
                "backend": r.get("backend", "?"),
                **(scores or {"overall": None}),
            })
    return scored


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_comparison(all_scored: list[dict]):
    import statistics

    def avg(vals):
        v = [x for x in vals if x is not None]
        return round(statistics.mean(v), 3) if v else None

    keys    = sorted({r["key"] for r in all_scored})
    metrics = ["overall", "physical_total", "alexander_total",
               "interior_total", "exterior_total", "prompt_total"]

    print("\n" + "="*80)
    print("BASE vs SFT  —  HomeCraft 5-family evaluation")
    print("="*80)
    header = f"{'Model':18} {'Variant':6} {'Parse%':7} " + " ".join(f"{m[:9]:>10}" for m in metrics)
    print(header)
    print("-"*len(header))

    rows = []
    for key in keys:
        for variant in ("base", "sft"):
            subset = [r for r in all_scored if r["key"] == key and r["variant"] == variant]
            if not subset:
                continue
            parse_pct = round(100 * sum(1 for r in subset if r["parse_ok"]) / len(subset))
            row = {"key": key, "variant": variant, "n": len(subset),
                   "parse_pct": parse_pct}
            for m in metrics:
                row[m] = avg([r.get(m) for r in subset])
            rows.append(row)
            vals = " ".join(f"{row.get(m) or '-':>10}" for m in metrics)
            print(f"{key:18} {variant:6} {parse_pct:>5}%  {vals}")

    # Delta table (SFT - base)
    print("\n" + "="*80)
    print("DELTA: SFT − BASE (positive = SFT better)")
    print("-"*80)
    for key in keys:
        base = next((r for r in rows if r["key"] == key and r["variant"] == "base"), {})
        sft  = next((r for r in rows if r["key"] == key and r["variant"] == "sft"),  {})
        deltas = []
        for m in metrics:
            b, s = base.get(m), sft.get(m)
            deltas.append(f"{(s-b):>+.3f}" if b is not None and s is not None else f"{'N/A':>6}")
        parse_d = (sft.get("parse_pct", 0) - base.get("parse_pct", 0))
        print(f"{key:18}       {parse_d:>+4}%  " + " ".join(f"{d:>10}" for d in deltas))

    # Save
    report_path = OUT / "comparison_report.json"
    report_path.write_text(json.dumps(rows, indent=2))
    md_path = OUT / "COMPARISON.md"
    _write_markdown(rows, keys, metrics, md_path)
    print(f"\n[saved] {report_path}")
    print(f"[saved] {md_path}")


def _write_markdown(rows, keys, metrics, path):
    lines = ["# HomeCraft SFT Comparison — Base vs Fine-tuned\n",
             "## Scores por modelo y variante\n",
             "| Modelo | Variante | Parse% | Overall | Physical | Alexander | Interior | Exterior | Prompt |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        vals = " | ".join(str(r.get(m) or "—") for m in metrics)
        lines.append(f"| {r['key']} | {r['variant']} | {r['parse_pct']}% | {vals} |")
    lines += ["\n## Δ SFT − BASE\n",
              "| Modelo | ΔParse% | ΔOverall | ΔPhysical | ΔAlexander | ΔInterior | ΔExterior | ΔPrompt |",
              "|---|---|---|---|---|---|---|---|"]
    for key in keys:
        base = next((r for r in rows if r["key"] == key and r["variant"] == "base"), {})
        sft  = next((r for r in rows if r["key"] == key and r["variant"] == "sft"),  {})
        deltas = []
        for m in metrics:
            b, s = base.get(m), sft.get(m)
            deltas.append(f"{s-b:+.3f}" if b is not None and s is not None else "N/A")
        pd = sft.get("parse_pct", 0) - base.get("parse_pct", 0)
        lines.append(f"| {key} | {pd:+d}% | " + " | ".join(deltas) + " |")
    path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=None)
    ap.add_argument("--image", default=DEFAULT_IMAGE)
    ap.add_argument("--query", default=DEFAULT_QUERY)
    ap.add_argument("--ssh-key", default="~/.ssh/id_ed25519.pub")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-vast", action="store_true",
                    help="skip Vast provisioning; just score already-downloaded results")
    ap.add_argument("--sequential", action="store_true")
    return ap.parse_args()


def main():
    args = parse_args()

    if not os.environ.get("HF_TOKEN"):
        print("WARNING: HF_TOKEN not set – gated models (Gemma) and private LoRA repos will fail")

    models = {k: v for k, v in MODELS.items()
              if not args.only or k in args.only}

    if not args.skip_vast:
        if subprocess.run(["which", "vastai"], capture_output=True).returncode != 0:
            sys.exit("vastai CLI not found: pip install vastai && vastai set api-key <KEY>")

        bundle = make_bundle() if not args.dry_run else (HERE / "gen_bundle.tar.gz")
        log("plan", f"{len(models)} model(s): {list(models)} "
                    f"({'sequential' if args.sequential else 'parallel'})")

        results = {}
        if args.sequential:
            for k, m in models.items():
                results[k] = run_model(k, m, bundle, args)
        else:
            threads = {}
            for k, m in models.items():
                t = threading.Thread(
                    target=lambda kk, mm: results.__setitem__(kk, run_model(kk, mm, bundle, args)),
                    args=(k, m))
                t.start(); threads[k] = t
            for t in threads.values():
                t.join()

        print("\n===== GENERATION SUMMARY =====")
        for k, r in results.items():
            print(f"  {k:18} {r['status']:12} instance={r.get('instance')}")

    # Score
    print("\n===== SCORING =====")
    all_scored = []
    for key in models:
        scored = load_and_score(key)
        all_scored.extend(scored)
        print(f"  {key}: {len(scored)} results loaded")

    if all_scored:
        print_comparison(all_scored)
    else:
        print("No results to score yet.")


if __name__ == "__main__":
    main()
