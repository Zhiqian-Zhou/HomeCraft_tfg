#!/usr/bin/env python3
"""Experiment2 harness: 6 LLMs x 50 prompts x 5 reps x 2 fallback arms.

Adapted from scratch/experimento/run_experiment.py. Each build runs in a fresh
subprocess (`python -m pipeline.agents.run ... -V v4`) with MODEL_MAIN/WORKER and
HOMECRAFT_FALLBACK_MODE fixed by env (model+toggle freeze at llm.py import).

Arms:
  fallback_off  -> HOMECRAFT_FALLBACK_MODE=off (LLM-only, current HEAD)
  fallback_on   -> HOMECRAFT_FALLBACK_MODE=on  (deterministic fallbacks re-enabled)

Builds are stored retrievably at:
  scratch/experimento2/builds/<arm>/<safe_model>/<prompt_key>__rep<k>/
Results appended (1 line/build) to scratch/experimento2/results.jsonl. Reentrant.

Critique is disabled (HOMECRAFT_RUN_CRITIQUE=0) — it does not affect composite.overall.

Env:
  OPENROUTER_API_KEY   required (source scratch/.env)
  EXP2_PILOT=1         -> 1 model x 50 prompts x 1 rep x arm=off (cost probe)
  EXP2_ARMS=off,on     -> override arms
  EXP2_MODELS=a,b      -> override model list
  EXP2_REPS=5          -> override reps
  EXP2_CONCURRENCY=12  -> override concurrency
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time, threading, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXP = ROOT / "scratch" / "experimento2"
BUILDS = EXP / "builds"
RESULTS = EXP / "results.jsonl"
PROMPTS_FILE = EXP / "prompts_50.jsonl"

TIMEOUT = int(os.environ.get("EXP2_BUILD_TIMEOUT", "900"))     # s per build
CONCURRENCY = int(os.environ.get("EXP2_CONCURRENCY", "12"))
REPS = int(os.environ.get("EXP2_REPS", "5"))

MODELS = [
    "qwen/qwen3.5-35b-a3b",
    "google/gemma-4-31b-it",
    "meta-llama/llama-4-scout",
    "qwen/qwen3.5-9b",
    "meta-llama/llama-3.3-70b-instruct",
    # google/gemma-4-26b-a4b-it removed: token hog (~2M tok/build, ~$0.13) to cut cost.
]
ARMS = {"fallback_off": "off", "fallback_on": "on"}

_lock = threading.Lock()


def _safe(m: str) -> str:
    return m.replace("/", "__")


def load_prompts() -> list[dict]:
    return [json.loads(l) for l in PROMPTS_FILE.read_text().splitlines() if l.strip()]


def _extract_metrics(report: dict) -> dict:
    out = {}
    for fam in ("physical", "alexander", "interior", "exterior", "prompt_adherence"):
        sub = report.get(fam)
        if isinstance(sub, dict):
            for k, v in sub.items():
                if isinstance(v, dict):
                    v = v.get("score")
                if isinstance(v, (int, float)):
                    out[k] = v
    return out


def _done_keys() -> set:
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text().splitlines():
            try:
                r = json.loads(line)
                if r.get("status") in ("ok", "no_score"):
                    done.add((r["arm"], r["model"], r["prompt_key"], r.get("rep", 0)))
            except Exception:
                pass
    return done


def run_one(arm: str, mode: str, model: str, p: dict, rep: int) -> dict:
    pkey = p["key"]
    gen_id = f"{pkey}__rep{rep}"
    outdir = BUILDS / arm / _safe(model)
    outdir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MODEL_MAIN"] = model
    env["MODEL_WORKER"] = model
    env["HOMECRAFT_FALLBACK_MODE"] = mode
    env["HOMECRAFT_RUN_CRITIQUE"] = "0"
    env["LLM_TIMEOUT_SEC"] = os.environ.get("LLM_TIMEOUT_SEC", "180")
    cmd = ["python3", "-m", "pipeline.agents.run", p["prompt"],
           "--gen-id", gen_id, "-V", "v4", "--quiet", "--output-dir", str(outdir)]
    t0 = time.time()
    status, err, stderr_tail = "ok", None, ""
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, timeout=TIMEOUT,
                              capture_output=True, text=True)
        stderr_tail = "\n".join(proc.stderr.splitlines()[-40:])
        if proc.returncode != 0:
            status, err = "error", (proc.stderr.splitlines() or ["?"])[-1][:300]
    except subprocess.TimeoutExpired:
        status, err = "timeout", f"timeout {TIMEOUT}s"
    wall = round(time.time() - t0, 1)

    bsp = len(re.findall(r"deterministic BSP fallback", stderr_tail))
    fail_stage = None
    if status != "ok":
        m = re.search(
            r"(floor_planner|global_designer_v4|space_planner_v4|prompt_expander|"
            r"room_agent|exterior_agent|voxelizer|aggregator|architecture_planner)"
            r"[:\s].*?(?:LLM (?:call )?failed|failed to produce|error)", stderr_tail)
        if m:
            fail_stage = m.group(1)
        elif "timeout" in (err or ""):
            fail_stage = "timeout"

    build_dir = outdir / gen_id
    rec = {"arm": arm, "model": model, "prompt_key": pkey,
           "style": p["style"], "building_type": p["building_type"], "rep": rep,
           "status": status, "wall_s": wall, "error": err, "fail_stage": fail_stage,
           "bsp_fallbacks": bsp, "gen_id": gen_id,
           "build_dir": str(build_dir.relative_to(ROOT))}
    if status != "ok":
        rec["stderr_tail"] = stderr_tail

    rep_path = build_dir / "evaluation_report.json"
    if rep_path.exists():
        try:
            report = json.loads(rep_path.read_text())
            comp = report.get("composite") or {}
            gen = report.get("generation") or {}
            rec.update({
                "parse_ok": True,
                "overall": comp.get("overall"),
                "physical_total": comp.get("physical_total"),
                "alexander_total": comp.get("alexander_total"),
                "interior_total": comp.get("interior_total"),
                "exterior_total": comp.get("exterior_total"),
                "prompt_adherence_total": comp.get("prompt_adherence_total"),
                "total_tokens": gen.get("total_tokens"),
                "prompt_tokens": gen.get("prompt_tokens"),
                "completion_tokens": gen.get("completion_tokens"),
                "llm_calls": gen.get("llm_calls"),
                "llm_wait_s": gen.get("llm_wait_s"),
                "gen_wall_s": gen.get("wall_time_s"),
                "metrics": _extract_metrics(report),
            })
            if rec.get("overall") is None and status == "ok":
                rec["status"] = "no_score"
        except Exception as e:
            rec["error"] = (rec.get("error") or "") + f" | report parse: {e}"
    else:
        rec["parse_ok"] = False

    with _lock:
        with open(RESULTS, "a") as f:
            f.write(json.dumps(rec) + "\n")
    o = rec.get("overall")
    print(f"[{rec['status']:8}] {arm:12} {model:34} {pkey:24} "
          f"overall={o if o is None else round(o,3)} tok={rec.get('total_tokens')} "
          f"wall={wall}s bsp={bsp}" + (f" ERR:{(err or '')[:50]}" if err else ""),
          flush=True)
    return rec


# ── pricing / cost estimate (OpenRouter) ──
def _pricing() -> dict:
    cache = Path("/tmp/or_models.json")
    try:
        if cache.exists():
            data = json.loads(cache.read_text()).get("data", [])
        else:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {os.environ.get('OPENROUTER_API_KEY','')}"})
            data = json.loads(urllib.request.urlopen(req, timeout=20).read()).get("data", [])
        out = {}
        for m in data:
            p = m.get("pricing", {}) or {}
            try:
                out[m["id"]] = (float(p.get("prompt", 0)), float(p.get("completion", 0)))
            except Exception:
                pass
        return out
    except Exception:
        return {}


def cost_summary():
    if not RESULTS.exists():
        return
    price = _pricing()
    n = ok = 0
    tot_tok = tot_cost = 0.0
    wall = []
    for line in RESULTS.read_text().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        n += 1
        if r.get("status") in ("ok", "no_score"):
            ok += 1
        pt = r.get("prompt_tokens") or 0
        ct = r.get("completion_tokens") or 0
        tot_tok += (pt + ct)
        pp, cp = price.get(r.get("model", ""), (0, 0))
        tot_cost += pt * pp + ct * cp
        if r.get("gen_wall_s"):
            wall.append(r["gen_wall_s"])
    avg_wall = sum(wall) / len(wall) if wall else 0
    print("\n===== COST / THROUGHPUT =====")
    print(f"  builds recorded : {n}   ok/no_score: {ok}  ({100*ok/n:.0f}%)" if n else "  no builds")
    print(f"  total tokens    : {tot_tok/1e6:.2f} M")
    print(f"  est. cost so far: ${tot_cost:.2f}")
    if ok:
        print(f"  $/build (ok)    : ${tot_cost/ok:.4f}")
        print(f"  avg gen wall    : {avg_wall:.0f}s")
        full = len(MODELS) * 50 * REPS * 2
        print(f"  -> extrapolated FULL ({full} builds): "
              f"${tot_cost/ok*full:.0f}, ~{avg_wall*full/CONCURRENCY/3600:.1f}h wall "
              f"@concurrency={CONCURRENCY}")


def write_index():
    """Map every recorded build to its retrievable path."""
    rows = []
    if RESULTS.exists():
        for line in RESULTS.read_text().splitlines():
            try:
                r = json.loads(line)
            except Exception:
                continue
            rows.append(r)
    idx = EXP / "INDEX.md"
    lines = ["# Indice de construcciones (experiment2)\n",
             f"- builds registrados: {len(rows)}",
             "- ruta de cada build: `build_dir/<gen_id>.json` (ReferenceBuilding) "
             "+ `evaluation_report.json`, `master_plan.json`, `generation_cost.json`\n",
             "| arm | modelo | prompt | rep | status | overall | build_dir |",
             "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x.get("arm",""), x.get("model",""), x.get("prompt_key",""), x.get("rep",0))):
        o = r.get("overall")
        lines.append(f"| {r.get('arm')} | {r.get('model')} | {r.get('prompt_key')} | "
                     f"{r.get('rep')} | {r.get('status')} | {o if o is None else round(o,3)} | "
                     f"`{r.get('build_dir')}` |")
    idx.write_text("\n".join(lines), encoding="utf-8")
    print(f"[index] wrote {idx} ({len(rows)} builds)")


def main():
    if not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("falta OPENROUTER_API_KEY (source scratch/.env)")
    prompts = load_prompts()
    pilot = os.environ.get("EXP2_PILOT") == "1"

    if pilot:
        arms = {"fallback_off": "off"}
        models = [os.environ.get("EXP2_PILOT_MODEL", "qwen/qwen3.5-35b-a3b")]
        reps = 1
        print("=== PILOT: 1 model x 50 prompts x 1 rep x arm=off ===")
    else:
        arms = {a: ARMS[a] for a in (os.environ["EXP2_ARMS"].split(",") if os.environ.get("EXP2_ARMS") else ARMS)}
        models = os.environ["EXP2_MODELS"].split(",") if os.environ.get("EXP2_MODELS") else MODELS
        reps = REPS

    if os.environ.get("EXP2_LIMIT"):   # smoke: cap number of prompts
        prompts = prompts[:int(os.environ["EXP2_LIMIT"])]

    BUILDS.mkdir(parents=True, exist_ok=True)
    done = _done_keys()
    jobs = [(arm, mode, m, p, rep)
            for arm, mode in arms.items()
            for m in models
            for p in prompts
            for rep in range(reps)
            if (arm, m, p["key"], rep) not in done]
    total = len(arms) * len(models) * len(prompts) * reps
    print(f"{len(jobs)} builds pendientes ({total-len(jobs)} hechos), "
          f"{len(arms)} arms x {len(models)} modelos x {len(prompts)} prompts x {reps} reps "
          f"= {total}, concurrencia={CONCURRENCY}", flush=True)

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futs = [pool.submit(run_one, arm, mode, m, p, rep)
                for (arm, mode, m, p, rep) in jobs]
        for _ in as_completed(futs):
            pass
    print(f"\nDONE en {round(time.time()-t0)}s. Resultados: {RESULTS}", flush=True)
    write_index()
    cost_summary()


if __name__ == "__main__":
    main()
