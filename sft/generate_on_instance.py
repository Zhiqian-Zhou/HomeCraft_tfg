#!/usr/bin/env python3
"""Generate Minecraft buildings on a Vast.ai instance for base-vs-SFT comparison.

Runs ON the instance. Tries vLLM first (efficient: base + LoRA in one pass);
falls back to Unsloth/transformers if the architecture is not yet supported.

Env vars (set by run_generation.sh):
  BASE_MODEL       e.g. google/gemma-4-E2B-it
  LORA_REPO        HF repo with the SFT LoRA, e.g. Chengheng/Homecraft-gemma-4-e2b
  CHAT_TEMPLATE    gemma-3 | qwen3 | chatml
  HF_TOKEN         for gated/private models
  MAX_NEW_TOKENS   default 4096
  MAX_SEQ_LEN      default 8192

Output (both written to /root/work/results/):
  base.jsonl  — one JSON line per prompt: {prompt_key, prompt, building, raw, parse_ok}
  sft.jsonl   — same for the fine-tuned model
"""
from __future__ import annotations
import json, os, re, sys, traceback
from pathlib import Path

WORK = Path("/root/work")
sys.path.insert(0, str(WORK))      # so we can import sft.common from bundle
RESULTS = WORK / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

from sft.common import build_messages  # noqa: E402

BASE_MODEL    = os.environ["BASE_MODEL"]
LORA_REPO     = os.environ.get("LORA_REPO", "")
CHAT_TEMPLATE = os.environ.get("CHAT_TEMPLATE", "gemma-3")
HF_TOKEN      = os.environ.get("HF_TOKEN", "")
MAX_NEW_TOKENS = int(os.environ.get("MAX_NEW_TOKENS", "4096"))
MAX_SEQ_LEN    = int(os.environ.get("MAX_SEQ_LEN", "8192"))
TEMPERATURE    = float(os.environ.get("TEMPERATURE", "0.7"))

PROMPTS = [
    ("nordic-cabin",         "A small Nordic log cabin with a single room around a central stone hearth and a sleeping loft tucked under a steep gabled roof."),
    ("modern-townhouse",     "A three-story glass-and-concrete townhouse with an open-plan ground floor, a cantilevered upper bedroom, and a flat rooftop terrace."),
    ("adobe-courtyard",      "An adobe pueblo dwelling with flat clay roofs, small deep-set windows, an interior courtyard, and an exterior staircase up to the second level."),
    ("pagoda-five-tier",     "A five-story pagoda with upturned tiled eaves on every tier, a central staircase column, and a shrine room at the base."),
    ("brick-watermill",      "A red-brick watermill beside a channel, with a wheel housing on one side, a grain storage loft above, and a timber-framed gable roof."),
    ("stone-keep",           "A square stone keep with round corner turrets, crenellated battlements, a great hall on the first floor, and a vaulted undercroft below."),
    ("greek-island-house",   "A whitewashed Greek island house with a blue domed roof, stepped flat terraces, narrow stairs between levels, and a vine-shaded pergola."),
    ("octagonal-baptistery", "An octagonal baptistery chapel with a ribbed dome, a tall arched window on each of its eight faces, and a central font."),
    ("cylindrical-lighthouse","A tall cylindrical lighthouse with a spiral interior staircase, a glass lantern room at the very top, and a keeper's room at the base."),
    ("baroque-manor",        "A symmetrical Baroque manor with two side wings, a central ballroom under a barrel vault, a grand double staircase, a library, and a columned entrance portico."),
]


def extract_json(text: str) -> dict | None:
    """Extract first valid JSON object from model output (handles markdown fences)."""
    raw = text.strip()
    # Strip ```json ... ``` fences
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    if m:
        raw = m.group(1).strip()
    # Find the first { ... } spanning the whole output
    depth = 0
    start = None
    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    return json.loads(raw[start:i+1])
                except Exception:
                    pass
    # Last-resort: try the whole string
    try:
        return json.loads(raw)
    except Exception:
        return None


def format_prompt(description: str, tokenizer) -> str:
    msgs = build_messages(description)
    # Multimodal processors (Gemma4, Qwen3.5-VL) expect content as list of dicts,
    # not plain strings. Wrap if needed so apply_chat_template doesn't crash.
    wrapped = []
    for m in msgs:
        c = m["content"]
        if isinstance(c, str):
            wrapped.append({"role": m["role"], "content": [{"type": "text", "text": c}]})
        else:
            wrapped.append(m)
    try:
        return tokenizer.apply_chat_template(wrapped, tokenize=False, add_generation_prompt=True)
    except Exception:
        # Fallback: try plain string content (some tokenizers prefer it)
        return tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)


# ---------------------------------------------------------------------------
# vLLM path
# ---------------------------------------------------------------------------

def run_vllm(lora_path: str | None) -> list[dict]:
    """Generate with vLLM. lora_path=None → base model, else SFT."""
    print(f"[vllm] loading {BASE_MODEL}  lora={lora_path or 'none'}")
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest
    from transformers import AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE_MODEL,
                                        token=HF_TOKEN or None,
                                        trust_remote_code=True)
    llm = LLM(
        model=BASE_MODEL,
        tokenizer=BASE_MODEL,
        enable_lora=(lora_path is not None),
        max_lora_rank=16,
        dtype="bfloat16",
        max_model_len=MAX_SEQ_LEN,
        gpu_memory_utilization=0.85,
        token=HF_TOKEN or None,
        trust_remote_code=True,
    )
    params = SamplingParams(max_tokens=MAX_NEW_TOKENS, temperature=TEMPERATURE)
    lora_req = LoRARequest("sft", 1, lora_path) if lora_path else None

    texts = [format_prompt(p, tok) for _, p in PROMPTS]
    outputs = llm.generate(texts, params, lora_request=lora_req)

    results = []
    for (pkey, prompt), out in zip(PROMPTS, outputs):
        raw = out.outputs[0].text
        building = extract_json(raw)
        results.append({"prompt_key": pkey, "prompt": prompt,
                         "building": building, "raw": raw,
                         "parse_ok": building is not None})
    return results


# ---------------------------------------------------------------------------
# Unsloth fallback path
# ---------------------------------------------------------------------------

def _generate_unsloth(model, tokenizer, description: str) -> str:
    import torch
    # Use format_prompt which handles multimodal processor content wrapping,
    # then tokenize via the text tokenizer (processor.tokenizer if available).
    text = format_prompt(description, tokenizer)
    text_tok = getattr(tokenizer, "tokenizer", tokenizer)
    inputs = text_tok(text, return_tensors="pt", add_special_tokens=False)["input_ids"].to(model.device)
    with torch.no_grad():
        out = model.generate(
            input_ids=inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=TEMPERATURE,
            do_sample=(TEMPERATURE > 0),
        )
    return tokenizer.decode(out[0][inputs.shape[1]:], skip_special_tokens=True)


def run_unsloth(lora_path: str | None) -> list[dict]:
    print(f"[unsloth] loading {BASE_MODEL}  lora={lora_path or 'none'}")
    from unsloth import FastModel
    from unsloth.chat_templates import get_chat_template

    model, tokenizer = FastModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=MAX_SEQ_LEN,
        dtype=None,
        load_in_4bit=True,
        token=HF_TOKEN or None,
    )
    if lora_path:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, lora_path)
    FastModel.for_inference(model)

    # Apply chat template if the tokenizer doesn't already have one
    if not getattr(tokenizer, "chat_template", None):
        tokenizer = get_chat_template(tokenizer, chat_template=CHAT_TEMPLATE)

    results = []
    for pkey, prompt in PROMPTS:
        raw = _generate_unsloth(model, tokenizer, prompt)
        building = extract_json(raw)
        results.append({"prompt_key": pkey, "prompt": prompt,
                         "building": building, "raw": raw,
                         "parse_ok": building is not None})
    return results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_variant(label: str, lora_path: str | None):
    """Generate all 10 prompts for one variant; try vLLM, fall back to Unsloth."""
    out_path = RESULTS / f"{label}.jsonl"
    if out_path.exists():
        print(f"[skip] {label}.jsonl already exists")
        return

    # Try vLLM
    try:
        import vllm  # noqa: F401
        results = run_vllm(lora_path)
        backend = "vllm"
    except Exception as e:
        print(f"[vllm] failed ({type(e).__name__}: {e}), falling back to Unsloth")
        traceback.print_exc()
        results = run_unsloth(lora_path)
        backend = "unsloth"

    with open(out_path, "w") as f:
        for r in results:
            r["backend"] = backend
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    ok = sum(1 for r in results if r["parse_ok"])
    print(f"[{label}] {ok}/{len(results)} buildings parsed OK  backend={backend}")


def main():
    # 1) Base model (no LoRA)
    run_variant("base", lora_path=None)

    # 2) SFT model (LoRA from HF)
    if LORA_REPO:
        lora_local = WORK / "lora_adapter"
        if not lora_local.exists():
            print(f"[sft] downloading LoRA from {LORA_REPO}…")
            # Use the huggingface_hub Python API: the `huggingface-cli download`
            # command is deprecated/disabled in recent hub versions (requires `hf`).
            from huggingface_hub import snapshot_download
            snapshot_download(repo_id=LORA_REPO, local_dir=str(lora_local),
                              token=HF_TOKEN or None)
        run_variant("sft", lora_path=str(lora_local))
    else:
        print("[sft] no LORA_REPO set, skipping SFT generation")

    # Write done marker
    (WORK / "gen_status").write_text("DONE")
    print("=== generation complete ===")


if __name__ == "__main__":
    main()
