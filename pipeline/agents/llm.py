"""Thin LLM wrapper for the pipeline (OpenRouter via OpenAI-compatible API).

Env vars:
    OPENROUTER_API_KEY  required — get one from https://openrouter.ai/keys
    MODEL_MAIN          optional — overrides the default for main agent
    MODEL_WORKER        optional — overrides the default for room/exterior
    MODEL_VISION        optional — overrides the default for image+text calls
    LLM_TIMEOUT_SEC     optional — default 60

Usage:
    from pipeline.agents.llm import call_llm, MODEL_MAIN, MODEL_WORKER
    out = call_llm(system="You are a JSON-only assistant.",
                   user="Return {\"hello\": \"world\"}",
                   response_format={"type": "json_object"})
    # out is the raw assistant content (string).

Backoff: 3 retries with delays 1s/2s/4s on 429 and 5xx.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

# Default model: gemini-2.5-flash-lite (fast, low-cost Gemini Flash Lite).
# Set MODEL_MAIN or MODEL_WORKER env vars to override per-stage if needed.
MODEL_DEFAULT = "google/gemini-2.5-flash-lite"
MODEL_MAIN    = os.environ.get("MODEL_MAIN",    MODEL_DEFAULT)
MODEL_WORKER  = os.environ.get("MODEL_WORKER",  MODEL_DEFAULT)
# Multimodal model for the image+text describer (tools/describe_corpus.py).
# `google/gemini-3.1-flash` does NOT exist on OpenRouter (verified 2026-05-30);
# `gemini-2.5-flash` is the current stable Gemini Flash multimodal endpoint.
# Override via env var MODEL_VISION if a new id is published.
MODEL_VISION  = os.environ.get("MODEL_VISION",  "google/gemini-2.5-flash")

# Base URL: OpenRouter by default, but overridable via LLM_BASE_URL so the
# pipeline can be pointed at a self-hosted OpenAI-compatible endpoint (e.g. the
# Modal SFT server in sft/modal/server.py) without touching any call site.
_BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
_TIMEOUT  = float(os.environ.get("LLM_TIMEOUT_SEC", "60"))

# Reasoning OFF: this pipeline reads `message.content`. Reasoning ("thinking")
# models (e.g. qwen3.5-*) otherwise put their answer in `message.reasoning` and
# leave `content` empty, which breaks every stage. We send OpenRouter's unified
# `reasoning.enabled=false` AND the Qwen chat-template flag `enable_thinking`,
# so the answer always lands in `content`. Non-reasoning models ignore both.
# Set DISABLE_REASONING=0 to allow reasoning again.
_REASONING_OFF = os.environ.get("DISABLE_REASONING", "1") != "0"


def _extra_body_for(model: str) -> dict:
    """OpenRouter extra_body to keep the answer in `message.content`.

    `reasoning.enabled=false` is OpenRouter's UNIFIED, provider-agnostic switch
    (ignored by non-reasoning models). The Qwen-specific chat-template flag
    `enable_thinking` is sent ONLY to qwen — sending it to other providers
    (e.g. Llama) can corrupt their chat template and produce malformed JSON.
    """
    if not _REASONING_OFF:
        return {}
    eb: dict = {"reasoning": {"enabled": False}}
    if "qwen" in (model or "").lower():
        eb["chat_template_kwargs"] = {"enable_thinking": False}
    return eb


_client = None

# ── Contador de uso (tokens/llamadas/tiempo) para comparar LLMs ─────────────
# Acumula el `usage` de cada llamada al LLM. run.py hace reset al empezar una
# generación y snapshot al terminar → coste de generar UN edificio (tokens +
# nº de llamadas + segundos de espera del LLM), clave para comparar modelos.
_USAGE = {
    "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
    "llm_wait_s": 0.0, "by_model": {},
}


def reset_usage() -> None:
    """Reinicia el contador de uso (llamar al inicio de una generación)."""
    _USAGE.update(calls=0, prompt_tokens=0, completion_tokens=0,
                  total_tokens=0, llm_wait_s=0.0)
    _USAGE["by_model"] = {}


def usage_snapshot() -> dict:
    """Copia del contador de uso acumulado desde el último reset."""
    import copy
    return copy.deepcopy(_USAGE)


def _record_usage(model: str, usage, wait_s: float) -> None:
    """Suma el usage de una respuesta al acumulador (tolerante a None)."""
    pt = int(getattr(usage, "prompt_tokens", 0) or 0)
    ct = int(getattr(usage, "completion_tokens", 0) or 0)
    tt = int(getattr(usage, "total_tokens", 0) or (pt + ct))
    _USAGE["calls"] += 1
    _USAGE["prompt_tokens"] += pt
    _USAGE["completion_tokens"] += ct
    _USAGE["total_tokens"] += tt
    _USAGE["llm_wait_s"] += float(wait_s or 0.0)
    bm = _USAGE["by_model"].setdefault(
        model, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    bm["calls"] += 1
    bm["prompt_tokens"] += pt
    bm["completion_tokens"] += ct
    bm["total_tokens"] += tt


def _get_client():
    """Lazy-initialize the OpenAI client pointing at OpenRouter."""
    global _client
    if _client is not None:
        return _client
    # A self-hosted endpoint (LLM_BASE_URL set) needs no real key; the OpenAI
    # client still requires a non-empty string, so fall back to a placeholder.
    key = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("LLM_API_KEY")
    if not key and os.environ.get("LLM_BASE_URL"):
        key = "sk-local"
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY env var not set. "
            "Get one from https://openrouter.ai/keys and export it. "
            "Example: export OPENROUTER_API_KEY=sk-or-v1-...")
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError(
            "openai>=1.0 required: pip install openai") from e
    _client = OpenAI(api_key=key, base_url=_BASE_URL, timeout=_TIMEOUT)
    return _client


def call_llm(*, system: str, user: str, model: str = MODEL_DEFAULT,
             response_format: Optional[dict] = None,
             max_tokens: int = 4096, temperature: float = 0.7,
             retries: int = 4) -> str:
    """Call the LLM and return raw assistant content.

    Args:
        system: system prompt
        user:   user prompt
        model:  model id (OpenRouter format like "deepseek/deepseek-v4-flash")
        response_format: optional {"type": "json_object"} to force JSON output
        max_tokens: cap on output tokens
        temperature: 0..1 sampling temperature
        retries: number of additional attempts on transient errors (3 by default)

    Raises:
        RuntimeError: on persistent API failure or missing API key
        ValueError:   on empty model output

    Returns: assistant message content as a string
    """
    client = _get_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": user},
    ]
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    _eb = _extra_body_for(model)
    if _eb:
        kwargs["extra_body"] = _eb

    last_err = None
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            _t0 = time.time()
            resp = client.chat.completions.create(**kwargs)
            _record_usage(model, getattr(resp, "usage", None), time.time() - _t0)
            if not getattr(resp, "choices", None):
                # Self-hosted server returned an error envelope (no choices) —
                # e.g. a container restart/eviction. Treat as transient + retry.
                _srv = getattr(resp, "error", None) or getattr(resp, "model_extra", None)
                raise ValueError(f"server returned no choices (transient): {str(_srv)[:160]}")
            choice = resp.choices[0]
            content = (choice.message.content or "").strip()
            if not content:
                raise ValueError("LLM returned empty content")
            return content
        except Exception as e:  # noqa: BLE001 — catch all to retry
            last_err = e
            msg = str(e)
            # Treat as transient: rate limit, 5xx, timeouts, empty content
            # (LLMs occasionally produce zero-token outputs under JSON mode).
            transient = (
                any(s in msg for s in ("429", "500", "502", "503", "504",
                                        "timeout", "Timeout"))
                or "empty content" in msg
                or "non-JSON" in msg
                or "no choices" in msg
                or "Connection" in msg)
            if attempt < retries and transient:
                print(f"[llm] transient error (attempt {attempt+1}/{retries+1}): {msg[:200]} — retrying in {delay:.1f}s",
                      file=sys.stderr)
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"LLM call failed after {attempt+1} attempts: {msg}") from e
    # unreachable
    raise RuntimeError(f"LLM call exhausted retries; last error: {last_err}")


def call_llm_json(*, system: str, user: str, **kwargs) -> dict:
    """Convenience: call the LLM with JSON mode and parse the response.

    Robust to common model glitches:
      - Output wrapped in ``` markdown fences
      - Reasoning prose before/after the JSON object
      - Trailing commas
    Raises ValueError if no parseable JSON object is found.
    """
    text = call_llm(
        system=system, user=user,
        response_format={"type": "json_object"},
        **kwargs)
    return _parse_json_robust(text)


def _parse_json_robust(text: str) -> dict:
    """Find and parse the first JSON object in `text`.

    Strategy: strip markdown fences, then scan for the first balanced
    `{...}` substring and json.loads it. Falls back to direct json.loads on
    the original text if scanning fails.
    """
    raw = text.strip()
    # Strip markdown fences ```json ... ```
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    # Try direct parse first
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # Scan for first balanced JSON object using a brace counter
    start = raw.find("{")
    if start == -1:
        raise ValueError(f"LLM returned non-JSON (no '{{' found): {text[:300]}")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(raw)):
        ch = raw[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = raw[start:i+1]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError as e:
                    raise ValueError(f"LLM returned non-JSON (parse error: {e}): {text[:300]}")
                break
    raise ValueError(f"LLM returned non-JSON (unbalanced braces): {text[:300]}")


def call_llm_vision(*, system: str, user_text: str, image_path,
                     model: str = None,
                     max_tokens: int = 2048, temperature: float = 0.6,
                     retries: int = 3) -> str:
    """Call a multimodal LLM with one image + a text prompt.

    Used by tools/describe_corpus.py to generate building descriptions from
    a rendered PNG + metadata. Reuses the same OpenRouter client + retry
    pattern as call_llm(); the only difference is the message content shape.

    Args:
        system: system prompt (plain text)
        user_text: user text part of the message (metadata, instructions)
        image_path: Path-like to a PNG/JPG. Read + base64-embedded as a
            data: URL so the OpenAI client can pass it through.
        model: OpenRouter model id; defaults to MODEL_VISION env var or
            "google/gemini-3.1-flash".
        max_tokens / temperature: same semantics as call_llm.
        retries: extra attempts on transient errors.

    Returns: assistant message content as a plain string (NOT parsed).
    Raises: RuntimeError on persistent failure or missing API key.
    """
    import base64
    from pathlib import Path as _Path

    p = _Path(image_path)
    if not p.is_file():
        raise FileNotFoundError(f"call_llm_vision: image not found at {p}")
    suffix = p.suffix.lower().lstrip(".")
    mime = "image/png" if suffix in ("", "png") else \
           "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    b64 = base64.b64encode(p.read_bytes()).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"

    model = model or MODEL_VISION
    client = _get_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": [
            {"type": "text",      "text": user_text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]},
    ]
    kwargs = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    _eb = _extra_body_for(model)
    if _eb:
        kwargs["extra_body"] = _eb

    last_err = None
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            _t0 = time.time()
            resp = client.chat.completions.create(**kwargs)
            _record_usage(model, getattr(resp, "usage", None), time.time() - _t0)
            if not getattr(resp, "choices", None):
                # Self-hosted server returned an error envelope (no choices) —
                # e.g. a container restart/eviction. Treat as transient + retry.
                _srv = getattr(resp, "error", None) or getattr(resp, "model_extra", None)
                raise ValueError(f"server returned no choices (transient): {str(_srv)[:160]}")
            choice = resp.choices[0]
            content = (choice.message.content or "").strip()
            if not content:
                raise ValueError("LLM returned empty content")
            return content
        except Exception as e:  # noqa: BLE001
            last_err = e
            msg = str(e)
            transient = (
                any(s in msg for s in ("429", "500", "502", "503", "504",
                                        "timeout", "Timeout"))
                or "empty content" in msg
                or "Connection" in msg)
            if attempt < retries and transient:
                print(f"[llm-vision] transient error (attempt {attempt+1}/{retries+1}): "
                      f"{msg[:200]} — retrying in {delay:.1f}s",
                      file=sys.stderr)
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(
                f"LLM vision call failed after {attempt+1} attempts: {msg}") from e
    raise RuntimeError(f"LLM vision call exhausted retries; last error: {last_err}")


if __name__ == "__main__":
    # Quick smoke test (requires OPENROUTER_API_KEY).
    out = call_llm_json(
        system="You are a JSON-only assistant. Return exactly the user payload.",
        user='Return {"ok": true, "message": "hello from pipeline"}')
    print(json.dumps(out, indent=2))
