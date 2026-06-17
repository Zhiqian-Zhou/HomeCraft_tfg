"""Modal serverless inference for the HomeCraft SFT evaluation.

Serves the two fine-tuned Gemma backbones (E2B, E4B) behind an OpenAI-compatible
/v1/chat/completions endpoint, so the generation pipeline (pipeline/agents/llm.py,
an OpenAI client) can drive them by just setting LLM_BASE_URL.

Why transformers+PEFT and not vLLM: gemma-4-E2B is a MatFormer checkpoint whose
q_norm/k_norm are stored irregularly, so vLLM's strict gemma-4 loader refuses both
the LoRA and the merged weights. The transformers + PEFT path loads it correctly
and lets us toggle the LoRA per request (base vs SFT vs hybrid) on one warm GPU.

One web endpoint per model, each serving THREE behaviours via the requested model id:
    <base>            -> LoRA DISABLED  (base arm, and the floor stage of the mixed arm)
    <base>:sft        -> LoRA ENABLED   (sft arm, and the non-floor stages of the mixed arm)
    anything else     -> LoRA ENABLED   (default)

Deploy:   modal deploy sft/modal/server.py
URLs:     https://<workspace>--homecraft-sft-e2b-serve.modal.run/v1
          https://<workspace>--homecraft-sft-e4b-serve.modal.run/v1

Prereqs (one-time):
    modal secret create huggingface HF_TOKEN=hf_xxx          # gated gemma base
    python sft/modal/upload_adapters.py                      # push local LoRA -> volume
"""
from __future__ import annotations
import os
import time
import modal

# ---------------------------------------------------------------- config ----
# Each endpoint serves TWO verified checkpoints from the homecraft-checkpoints
# volume (built by build_checkpoints.py): the plain base and the LoRA-merged SFT.
# Serving merged weights means no PEFT/adapter step at request time.
MODELS = {
    "e2b": {"base_id": "google/gemma-4-E2B-it",
            "base_ckpt": "/checkpoints/e2b-base", "adapter": "/adapters/gemma-4-e2b"},
    "e4b": {"base_id": "google/gemma-4-E4B-it",
            "base_ckpt": "/checkpoints/e4b-base", "adapter": "/adapters/gemma-4-e4b"},
}
GPU = os.environ.get("HOMECRAFT_MODAL_GPU", "L40S")
MAX_NEW_TOKENS = 6144   # bounded output; SDPA attention handles the long-input memory
IDLE_TIMEOUT = 60           # short idle window to minimise billed idle GPU
MAX_CONTAINERS = 4          # barn is simple (few rooms); 4 slots suffice + safe wall-cap
CONCURRENT_PER_GPU = 1      # the disable_adapter() base/sft toggle mutates one shared
                            # model object, so it is NOT thread-safe: serve one forward
                            # per container. Parallelism comes from autoscaling.

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")                       # needed for the transformers git install
    .pip_install("torch==2.5.1")
    # gemma-4 (E2B/E4B MatFormer) is newer than any stable PyPI transformers, so
    # the working inference path uses transformers from git main (same as the
    # runai pod). peft applies the LoRA; accelerate gives device_map.
    .pip_install("git+https://github.com/huggingface/transformers.git")
    .pip_install(
        "peft>=0.13", "accelerate>=0.30", "sentencepiece", "huggingface_hub",
        "fastapi==0.115.0", "pillow", "timm",
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "0",
          "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True"})
)

app = modal.App("homecraft-sft")
ckpt_vol = modal.Volume.from_name("homecraft-checkpoints")   # base weights (build_checkpoints.py)
adapters_vol = modal.Volume.from_name("homecraft-adapters")   # LoRA adapters (upload_adapters.py)
hf_cache_vol = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
hf_secret = modal.Secret.from_name("huggingface")


# ------------------------------------------------------------- the server ----
class _Base:
    """Shared loader + OpenAI-compatible FastAPI. Subclasses set MODEL_KEY."""
    MODEL_KEY: str = "e2b"

    @modal.enter()
    def _load(self):
        import torch, transformers
        from transformers import AutoTokenizer

        cfg = MODELS[self.MODEL_KEY]
        self.base_id = cfg["base_id"]

        def load_ckpt(path):
            last = None
            for loader in ("AutoModelForImageTextToText", "AutoModelForCausalLM"):
                try:
                    L = getattr(transformers, loader)
                    print(f"[load] {path} via {loader} (bf16)…", flush=True)
                    m = L.from_pretrained(path, dtype=torch.bfloat16, device_map="cuda",
                                          attn_implementation="sdpa")
                    m.eval()
                    return m
                except Exception as e:  # noqa: BLE001
                    last = e
                    print(f"[load] {loader} failed: {type(e).__name__}: {str(e)[:120]}")
            raise RuntimeError(f"could not load checkpoint {path}: {last}")

        self.tok = AutoTokenizer.from_pretrained(cfg["base_ckpt"])
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        self.tok.padding_side = "left"

        # One base model + LoRA adapter; toggle the adapter per request. This is
        # mathematically the merged SFT when enabled, but uses ~16GB (one model)
        # instead of ~32GB (two), so a big global_designer forward fits L40S.
        from peft import PeftModel
        base = load_ckpt(cfg["base_ckpt"])
        self.model = PeftModel.from_pretrained(base, cfg["adapter"])
        n = sum(1 for k, _ in self.model.named_modules() if "lora_A" in k or "lora_B" in k)
        if n == 0:
            raise RuntimeError("0 LoRA modules injected — adapter/base mismatch")
        self.model.eval()
        self.torch = torch
        self._pad = self.tok.pad_token_id or self.tok.eos_token_id
        print(f"[load] ready: {self.MODEL_KEY} (base + {n} LoRA modules, toggled per request)", flush=True)

    # ---- generation core (anti-loop stop on JSON close / repetition) ----
    def _stop_criteria(self, start_len):
        import torch
        from transformers import StoppingCriteria, StoppingCriteriaList
        tok = self.tok

        def json_complete(t):
            d = 0; seen = False
            for c in t:
                if c == "{":
                    d += 1; seen = True
                elif c == "}":
                    d -= 1
                    if seen and d <= 0:
                        return True
            return False

        def tail_repeats(t, n=60):
            t = t[-800:]
            return len(t) > 2 * n and t[-n:] in t[:-n]

        class _S(StoppingCriteria):
            def __init__(self):
                self.k = 0

            def __call__(self, ids, scores=None, **kw):
                self.k += 1
                done = torch.zeros(ids.shape[0], dtype=torch.bool, device=ids.device)
                if self.k % 24:
                    return done
                for i in range(ids.shape[0]):
                    txt = tok.decode(ids[i][start_len:], skip_special_tokens=True)
                    if json_complete(txt) or tail_repeats(txt):
                        done[i] = True
                return done
        return StoppingCriteriaList([_S()])

    def _render(self, messages):
        msgs = [{"role": m.get("role", "user"), "content": m.get("content", "")} for m in messages]
        try:
            return self.tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)
        except Exception:
            sys_txt = "\n\n".join(m["content"] for m in msgs if m["role"] == "system")
            merged, first = [], True
            for m in msgs:
                if m["role"] == "system":
                    continue
                if m["role"] == "user" and first and sys_txt:
                    merged.append({"role": "user", "content": f"{sys_txt}\n\n{m['content']}"}); first = False
                else:
                    merged.append(m)
            return self.tok.apply_chat_template(merged, tokenize=False, add_generation_prompt=True)

    def _generate(self, messages, max_tokens, temperature, model_id):
        torch = self.torch
        # base arm / mixed-arm floor stage: bare base id -> base checkpoint;
        # "<base>:sft" (or anything else) -> the LoRA-merged SFT checkpoint.
        use_base = bool(model_id) and (model_id == self.base_id or str(model_id).endswith(":base"))
        text = self._render(messages)
        enc = self.tok(text, return_tensors="pt", add_special_tokens=False).to(self.model.device)
        in_len = enc["input_ids"].shape[1]
        cap = min(int(max_tokens or MAX_NEW_TOKENS), MAX_NEW_TOKENS)
        gen = dict(max_new_tokens=cap, pad_token_id=self._pad,
                   do_sample=(temperature or 0) > 0,
                   temperature=temperature if (temperature or 0) > 0 else None,
                   stopping_criteria=self._stop_criteria(in_len))
        with torch.inference_mode():
            if use_base:
                with self.model.disable_adapter():
                    out = self.model.generate(**enc, **gen)
            else:
                out = self.model.generate(**enc, **gen)
        completion = self.tok.decode(out[0][in_len:], skip_special_tokens=True)
        return completion, in_len, int(out.shape[1] - in_len)

    @modal.asgi_app()
    def serve(self):
        from fastapi import FastAPI, Body
        web = FastAPI()
        base_id = self.base_id

        @web.get("/health")
        def health():
            return {"status": "ok", "model_key": self.MODEL_KEY, "base": base_id}

        @web.get("/v1/models")
        def models():
            return {"object": "list", "data": [
                {"id": base_id, "object": "model", "owned_by": "homecraft"},
                {"id": f"{base_id}:sft", "object": "model", "owned_by": "homecraft"},
            ]}

        @web.post("/v1/chat/completions")
        def chat(body: dict = Body(...)):
            t0 = time.time()
            try:
                content, pt, ct = self._generate(
                    body.get("messages", []), body.get("max_tokens"),
                    body.get("temperature", 0.7), body.get("model"))
            except Exception as e:  # noqa: BLE001
                import traceback; traceback.print_exc()
                print(f"[serve] generate failed: {type(e).__name__}: {e}", flush=True)
                return {"error": {"message": f"generate failed: {e}", "type": "internal_error"}}
            return {
                "id": f"chatcmpl-{int(t0)}", "object": "chat.completion", "created": int(t0),
                "model": body.get("model", base_id),
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct},
                "_latency_s": round(time.time() - t0, 2),
            }
        return web


_common = dict(image=image, gpu=GPU, secrets=[hf_secret],
               volumes={"/checkpoints": ckpt_vol, "/adapters": adapters_vol,
                        "/root/.cache/huggingface": hf_cache_vol},
               scaledown_window=IDLE_TIMEOUT, max_containers=MAX_CONTAINERS, timeout=900)


@app.cls(**_common)
@modal.concurrent(max_inputs=CONCURRENT_PER_GPU)
class E2B(_Base):
    MODEL_KEY = "e2b"


@app.cls(**_common)
@modal.concurrent(max_inputs=CONCURRENT_PER_GPU)
class E4B(_Base):
    MODEL_KEY = "e4b"
