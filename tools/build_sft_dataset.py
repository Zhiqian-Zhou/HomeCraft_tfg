#!/usr/bin/env python3
"""Construye el dataset de SFT (texto -> JSON de edificio voxel) para el TFG.

Combina dos fuentes de pares prompt->edificio que ya existen:

  A) RAG reference_buildings: casas cuya descripcion fue generada por LLM
     (metadata_quality.description_llm_generated == true). El prompt es su
     campo `description`.

  B) Builds del ultimo experimento (builds_5fam): solo los de alto rendimiento
     (status ok y composite.overall >= UMBRAL). El prompt es el texto ORIGINAL
     del experimento (lista PROMPTS por prompt_key), no la descripcion
     autogenerada del build.

Salida (JSONL, formato prompt/completion):
  {"prompt": <texto>, "completion": <string JSON compacto del edificio final>}

La completion = "el output final": el documento ReferenceBuilding tal cual,
quitando solo `description` (que es el input, para evitar fuga de informacion).

No modifica el pipeline, el RAG ni el evaluador. Reproducible.

Uso:
  python3 tools/build_sft_dataset.py
  python3 tools/build_sft_dataset.py --voxel-cap 2000 --threshold 0.70 --out scratch/sft
"""
from __future__ import annotations
import argparse
import json
import random
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAG_PROCESSED = ROOT / "rag" / "reference_buildings" / "processed"
EXP = ROOT / "scratch" / "experimento"
RESULTS = EXP / "results_5fam.jsonl"
BUILDS = EXP / "builds_5fam"

# Prompts originales del experimento (copiados de run_experiment.py para no
# acoplar este tool a un script de scratch).
PROMPTS = {
    "nordic-cabin": "A small Nordic log cabin with a single room around a central stone hearth and a sleeping loft tucked under a steep gabled roof.",
    "modern-townhouse": "A three-story glass-and-concrete townhouse with an open-plan ground floor, a cantilevered upper bedroom, and a flat rooftop terrace.",
    "adobe-courtyard": "An adobe pueblo dwelling with flat clay roofs, small deep-set windows, an interior courtyard, and an exterior staircase up to the second level.",
    "pagoda-five-tier": "A five-story pagoda with upturned tiled eaves on every tier, a central staircase column, and a shrine room at the base.",
    "brick-watermill": "A red-brick watermill beside a channel, with a wheel housing on one side, a grain storage loft above, and a timber-framed gable roof.",
    "stone-keep": "A square stone keep with round corner turrets, crenellated battlements, a great hall on the first floor, and a vaulted undercroft below.",
    "greek-island-house": "A whitewashed Greek island house with a blue domed roof, stepped flat terraces, narrow stairs between levels, and a vine-shaded pergola.",
    "octagonal-baptistery": "An octagonal baptistery chapel with a ribbed dome, a tall arched window on each of its eight faces, and a central font.",
    "cylindrical-lighthouse": "A tall cylindrical lighthouse with a spiral interior staircase, a glass lantern room at the very top, and a keeper's room at the base.",
    "baroque-manor": "A symmetrical Baroque manor with two side wings, a central ballroom under a barrel vault, a grand double staircase, a library, and a columned entrance portico.",
}


def _safe_model(m: str) -> str:
    return m.replace("/", "__")


def _est_tokens(text: str) -> int:
    """Estimacion aproximada de tokens (~4 chars/token)."""
    return max(1, round(len(text) / 4))


def _final_doc(doc: dict) -> dict:
    """Documento ReferenceBuilding final como salida de SFT.

    Quita el texto de entrada (`description`/`description_legacy`) para evitar
    fuga, y los metadatos de ingest sobre la descripcion (no son parte de la
    geometria generada y rompen el schema estricto). El resto del documento
    final (id, title, tags, bounding_box, block_palette, voxels,
    bot_decomposition, connectors...) se mantiene tal cual.
    """
    out = dict(doc)
    out.pop("description", None)
    out.pop("description_legacy", None)
    mq = out.get("metadata_quality")
    if isinstance(mq, dict):
        mq = dict(mq)
        mq.pop("description_llm_generated", None)
        mq.pop("description_model", None)
        out["metadata_quality"] = mq
    return out


def _completion_str(doc: dict) -> str:
    return json.dumps(_final_doc(doc), separators=(",", ":"), ensure_ascii=False)


def load_rag(voxel_cap: int) -> tuple[list[dict], int]:
    """Fuente A: RAG con descripcion generada por LLM, bajo el cap de voxels."""
    records, dropped = [], 0
    for fp in sorted(RAG_PROCESSED.glob("*.json")):
        try:
            doc = json.loads(fp.read_text())
        except Exception:
            continue
        desc = (doc.get("description") or "").strip()
        mq = doc.get("metadata_quality") or {}
        if not desc or not mq.get("description_llm_generated"):
            continue
        n_vox = len(doc.get("voxels") or [])
        if n_vox > voxel_cap:
            dropped += 1
            continue
        comp = _completion_str(doc)
        tags = doc.get("tags") or {}
        records.append({
            "prompt": desc,
            "completion": comp,
            "_meta": {
                "source": "rag",
                "id": doc.get("id"),
                "category": tags.get("category"),
                "style": tags.get("style"),
                "overall": None,
                "voxel_count": n_vox,
                "n_prompt_tokens_est": _est_tokens(desc),
                "n_completion_tokens_est": _est_tokens(comp),
            },
        })
    return records, dropped


def load_experiment(threshold: float, voxel_cap: int) -> tuple[list[dict], int, int]:
    """Fuente B: builds_5fam con overall >= threshold, bajo el cap de voxels.

    voxel_cap <= 0 desactiva el cap (incluye todos los builds de alto
    rendimiento, para maximizar la variedad de estructuras)."""
    if not RESULTS.exists():
        return [], 0, 0
    records, dropped, missing = [], 0, 0
    seen = set()
    for line in RESULTS.read_text().splitlines():
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("status") != "ok":
            continue
        overall = r.get("overall")
        if not isinstance(overall, (int, float)) or overall < threshold:
            continue
        model, pkey, rep = r.get("model"), r.get("prompt_key"), r.get("rep", 0)
        prompt = PROMPTS.get(pkey)
        if not prompt:
            continue
        gen_id = f"{_safe_model(model)}__{pkey}__rep{rep}"
        if gen_id in seen:
            continue
        seen.add(gen_id)
        cand_dir = BUILDS / _safe_model(model) / gen_id / "cand"
        cand = next(iter(cand_dir.glob("*.json")), None) if cand_dir.exists() else None
        if cand is None:
            missing += 1
            continue
        try:
            doc = json.loads(cand.read_text())
        except Exception:
            missing += 1
            continue
        n_vox = len(doc.get("voxels") or [])
        if voxel_cap > 0 and n_vox > voxel_cap:
            dropped += 1
            continue
        comp = _completion_str(doc)
        records.append({
            "prompt": prompt,
            "completion": comp,
            "_meta": {
                "source": "exp",
                "id": gen_id,
                "model": model,
                "prompt_key": pkey,
                "overall": round(float(overall), 4),
                "voxel_count": n_vox,
                "n_prompt_tokens_est": _est_tokens(prompt),
                "n_completion_tokens_est": _est_tokens(comp),
            },
        })
    return records, dropped, missing


def split_train_val(records: list[dict], val_frac: float, seed: int):
    """Split estratificado por estrato (source + prompt_key/category)."""
    rng = random.Random(seed)
    strata: dict[str, list[dict]] = {}
    for r in records:
        m = r["_meta"]
        key = m["source"] + ":" + str(m.get("prompt_key") or m.get("category") or "")
        strata.setdefault(key, []).append(r)
    train, val = [], []
    for key, items in sorted(strata.items()):
        items = items[:]
        rng.shuffle(items)
        n_val = max(1, round(len(items) * val_frac)) if len(items) > 1 else 0
        val.extend(items[:n_val])
        train.extend(items[n_val:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def _write_jsonl(path: Path, records: list[dict], keys=("prompt", "completion")):
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps({k: r[k] for k in keys}, ensure_ascii=False) + "\n")


def _write_manifest(path: Path, records: list[dict], split: str):
    with open(path, "a") as f:
        for r in records:
            row = dict(r["_meta"])
            row["split"] = split
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _dist(values: list[float]) -> dict:
    if not values:
        return {}
    s = sorted(values)
    def pct(p):
        return s[min(int(len(s) * p), len(s) - 1)]
    return {
        "min": s[0], "p50": pct(.5), "p90": pct(.9), "p95": pct(.95),
        "max": s[-1], "mean": round(statistics.mean(s), 1),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--voxel-cap", type=int, default=2000,
                    help="cap de voxels para la fuente RAG (default 2000)")
    ap.add_argument("--exp-voxel-cap", type=int, default=0,
                    help="cap de voxels para los builds del experimento; "
                         "<=0 = sin cap, incluye todos (default 0, por variedad)")
    ap.add_argument("--threshold", type=float, default=0.70,
                    help="overall minimo para builds del experimento (default 0.70)")
    ap.add_argument("--val-frac", type=float, default=0.10,
                    help="fraccion de validacion (default 0.10)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=str, default=str(EXP.parent / "sft"),
                    help="directorio de salida (default scratch/sft)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    rag, rag_dropped = load_rag(args.voxel_cap)
    exp, exp_dropped, exp_missing = load_experiment(args.threshold, args.exp_voxel_cap)
    records = rag + exp
    if not records:
        raise SystemExit("No se obtuvieron ejemplos. Revisa rutas de RAG/experimento.")

    train, val = split_train_val(records, args.val_frac, args.seed)

    _write_jsonl(out / "sft_train.jsonl", train)
    _write_jsonl(out / "sft_val.jsonl", val)
    manifest = out / "manifest.jsonl"
    manifest.unlink(missing_ok=True)
    _write_manifest(manifest, train, "train")
    _write_manifest(manifest, val, "val")

    stats = {
        "config": {"voxel_cap": args.voxel_cap, "exp_voxel_cap": args.exp_voxel_cap,
                   "threshold": args.threshold, "val_frac": args.val_frac,
                   "seed": args.seed},
        "totals": {"total": len(records), "train": len(train), "val": len(val),
                   "rag": len(rag), "exp": len(exp)},
        "dropped": {"rag_over_cap": rag_dropped, "exp_over_cap": exp_dropped,
                    "exp_missing_build": exp_missing},
        "voxels": _dist([r["_meta"]["voxel_count"] for r in records]),
        "prompt_tokens_est": _dist([r["_meta"]["n_prompt_tokens_est"] for r in records]),
        "completion_tokens_est": _dist([r["_meta"]["n_completion_tokens_est"] for r in records]),
        "completion_tokens_est_rag": _dist([r["_meta"]["n_completion_tokens_est"] for r in rag]),
        "completion_tokens_est_exp": _dist([r["_meta"]["n_completion_tokens_est"] for r in exp]),
        "exp_by_model": {},
        "exp_by_type": {},
        "rag_by_style": {},
    }
    for r in exp:
        m = r["_meta"]["model"]
        stats["exp_by_model"][m] = stats["exp_by_model"].get(m, 0) + 1
        t = r["_meta"].get("prompt_key")
        stats["exp_by_type"][t] = stats["exp_by_type"].get(t, 0) + 1
    for r in rag:
        styles = r["_meta"].get("style") or ["?"]
        for s in styles:
            stats["rag_by_style"][s] = stats["rag_by_style"].get(s, 0) + 1
    (out / "stats.json").write_text(json.dumps(stats, indent=2, ensure_ascii=False))

    print(f"Dataset SFT escrito en {out}")
    print(f"  total={len(records)}  train={len(train)}  val={len(val)}")
    print(f"  RAG(LLM-desc)={len(rag)} (descartados >cap: {rag_dropped})")
    print(f"  EXP(overall>={args.threshold})={len(exp)} "
          f"(descartados >cap: {exp_dropped}, build no hallado: {exp_missing})")
    print(f"  voxels: {stats['voxels']}")
    print(f"  completion_tokens_est: {stats['completion_tokens_est']}")
    print(f"  -> {out/'sft_train.jsonl'}, {out/'sft_val.jsonl'}, "
          f"{out/'manifest.jsonl'}, {out/'stats.json'}")


if __name__ == "__main__":
    main()
