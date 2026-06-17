"""Build and verify the four serving checkpoints on a Modal GPU.

Produces, in the `homecraft-checkpoints` volume:
    /checkpoints/e2b-base   google/gemma-4-E2B-it           (base weights)
    /checkpoints/e2b-sft    base + LoRA merged (merge_and_unload)
    /checkpoints/e4b-base   google/gemma-4-E4B-it           (base weights)
    /checkpoints/e4b-sft    base + LoRA merged

For each SFT checkpoint it asserts the LoRA actually injected (>0 lora modules)
before merging. After building, every checkpoint is reloaded from disk and run on
a fixed input; the SFT logits must differ from the base (the merge had an effect)
and both must load without error. Merging (vs a runtime PEFT adapter) gives plain
standalone weights, so serving needs no adapter step.

    modal run sft/modal/build_checkpoints.py            # build + verify all 4
    modal run sft/modal/build_checkpoints.py --only e2b # just one model
"""
from __future__ import annotations
import modal

MODELS = {
    "e2b": {"base": "google/gemma-4-E2B-it", "adapter": "/adapters/gemma-4-e2b"},
    "e4b": {"base": "google/gemma-4-E4B-it", "adapter": "/adapters/gemma-4-e4b"},
}

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install("torch==2.5.1")
    .pip_install("git+https://github.com/huggingface/transformers.git")
    .pip_install("peft>=0.13", "accelerate>=0.30", "sentencepiece",
                 "huggingface_hub", "pillow", "timm")
)

app = modal.App("homecraft-build-checkpoints")
adapters_vol = modal.Volume.from_name("homecraft-adapters")
ckpt_vol = modal.Volume.from_name("homecraft-checkpoints", create_if_missing=True)
hf_cache_vol = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface")
CKPT = "/checkpoints"


def _load_base(base_id, token):
    """Load the base via the multimodal class (so a language-layer LoRA matches)."""
    import torch, transformers
    last = None
    for loader in ("AutoModelForImageTextToText", "AutoModelForCausalLM"):
        try:
            L = getattr(transformers, loader)
            print(f"[build] loading {base_id} via {loader} (bf16)…", flush=True)
            m = L.from_pretrained(base_id, dtype=torch.bfloat16, device_map="cuda",
                                  token=token, trust_remote_code=True)
            return m, loader
        except Exception as e:  # noqa: BLE001
            last = e
            print(f"[build] {loader} failed: {type(e).__name__}: {str(e)[:120]}")
    raise RuntimeError(f"cannot load {base_id}: {last}")


@app.function(image=image, gpu="L40S", secrets=[hf_secret], timeout=3600,
              volumes={"/adapters": adapters_vol, CKPT: ckpt_vol,
                       "/root/.cache/huggingface": hf_cache_vol})
def build_one(key: str) -> dict:
    import os, shutil, torch
    from pathlib import Path
    from transformers import AutoTokenizer
    from peft import PeftModel

    cfg = MODELS[key]
    token = os.environ.get("HF_TOKEN")
    base_dir, sft_dir = f"{CKPT}/{key}-base", f"{CKPT}/{key}-sft"
    for d in (base_dir, sft_dir):
        shutil.rmtree(d, ignore_errors=True); Path(d).mkdir(parents=True, exist_ok=True)

    tok = AutoTokenizer.from_pretrained(cfg["base"], token=token, trust_remote_code=True)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    tok.save_pretrained(base_dir); tok.save_pretrained(sft_dir)

    # ---- base checkpoint ----
    base, loader = _load_base(cfg["base"], token)
    base.save_pretrained(base_dir, safe_serialization=True)
    print(f"[build] {key}-base saved ({loader})", flush=True)

    # ---- sft checkpoint: wrap with LoRA, assert injected, merge, save ----
    model = PeftModel.from_pretrained(base, cfg["adapter"], token=token)
    n_lora = sum(1 for n, _ in model.named_modules() if "lora_A" in n or "lora_B" in n)
    print(f"[build] {key}: LoRA modules injected = {n_lora}", flush=True)
    if n_lora == 0:
        raise RuntimeError(f"{key}: 0 LoRA modules injected — adapter/base mismatch")
    merged = model.merge_and_unload()
    merged.save_pretrained(sft_dir, safe_serialization=True)
    print(f"[build] {key}-sft merged + saved", flush=True)
    ckpt_vol.commit()
    return {"key": key, "n_lora": n_lora, "loader": loader,
            "base_dir": base_dir, "sft_dir": sft_dir}


@app.function(image=image, gpu="L40S", secrets=[hf_secret], timeout=1800,
              volumes={CKPT: ckpt_vol, "/root/.cache/huggingface": hf_cache_vol})
def verify_one(key: str) -> dict:
    """Reload both checkpoints from disk and confirm the SFT differs from base."""
    import torch, transformers
    from pathlib import Path
    from transformers import AutoTokenizer
    ckpt_vol.reload()

    def load(path):
        for loader in ("AutoModelForImageTextToText", "AutoModelForCausalLM"):
            try:
                L = getattr(transformers, loader)
                return L.from_pretrained(path, dtype=torch.bfloat16, device_map="cuda")
            except Exception:  # noqa: BLE001
                continue
        raise RuntimeError(f"cannot reload {path}")

    base_dir, sft_dir = f"{CKPT}/{key}-base", f"{CKPT}/{key}-sft"
    res = {"key": key}
    for tag, path in (("base", base_dir), ("sft", sft_dir)):
        ok = Path(path, "config.json").exists()
        res[f"{tag}_exists"] = ok
        if not ok:
            raise RuntimeError(f"{key}-{tag}: checkpoint dir incomplete at {path}")

    tok = AutoTokenizer.from_pretrained(base_dir)
    enc = tok("Build a small house.", return_tensors="pt").to("cuda")
    with torch.inference_mode():
        b = load(base_dir); lb = b(**enc).logits[0, -1].float().cpu()
        del b; torch.cuda.empty_cache()
        s = load(sft_dir); ls = s(**enc).logits[0, -1].float().cpu()
    diff = float((lb - ls).abs().mean())
    res["logit_mean_abs_diff"] = round(diff, 5)
    res["sft_differs_from_base"] = diff > 1e-4
    res["loaded_ok"] = True
    print(f"[verify] {key}: base+sft load OK, mean|Δlogit|={diff:.5f} "
          f"({'DIFFERS' if diff > 1e-4 else 'IDENTICAL — merge had NO effect!'})", flush=True)
    if diff <= 1e-4:
        raise RuntimeError(f"{key}: merged SFT is identical to base — LoRA not applied")
    return res


@app.local_entrypoint()
def main(only: str = ""):
    keys = [only] if only else list(MODELS)
    print(f"=== building checkpoints for {keys} ===")
    built = list(build_one.map(keys))
    for b in built:
        print(f"  built {b['key']}: lora_modules={b['n_lora']} via {b['loader']}")
    print("=== verifying all checkpoints reload + SFT != base ===")
    ver = list(verify_one.map(keys))
    print("\n=== SUMMARY (4 checkpoints) ===")
    for k in keys:
        v = next(x for x in ver if x["key"] == k)
        print(f"  {k}-base : loaded={v['base_exists']}")
        print(f"  {k}-sft  : loaded={v['sft_exists']}  differs_from_base={v['sft_differs_from_base']} "
              f"(mean|Δlogit|={v['logit_mean_abs_diff']})")
    print("All checkpoints built and verified." if all(v["loaded_ok"] and v["sft_differs_from_base"]
          for v in ver) else "VERIFICATION FAILED")
