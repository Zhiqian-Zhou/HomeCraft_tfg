"""Stage 0 of the pipeline — pre-process a raw user prompt.

Takes a possibly-vague prompt like "small cottage" and produces an
ExpandedPrompt JSON with:
  - expanded_description: 80-200 word rich description (fed to retriever +
    main_agent in place of the raw prompt)
  - implied_style / implied_size_bucket / implied_category
  - implied_rooms + implied_exterior_features (hints to the main_agent)
  - atmosphere (one-line vibe)
  - alexander_intent_keywords (2-4 pattern IDs the main_agent should bias toward)
  - constraints (hard rules the user wrote or strongly implied)

The downstream stages are unchanged in their interface — they just receive
richer text. The original_prompt is preserved for traceability.
"""
from __future__ import annotations

import json
from pathlib import Path

from .llm import call_llm_json, MODEL_DEFAULT
from .schema_utils import make_validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS = Path(__file__).resolve().parent / "prompts"


def _validator():
    return make_validator("expanded_prompt.schema.json")


def expand(user_prompt: str, *, model: str = MODEL_DEFAULT) -> dict:
    """Expand a raw user prompt into a richer ExpandedPrompt dict.

    Robust to common LLM failure modes: retries once on schema-violation,
    falls back to a minimal pass-through (original prompt verbatim) if the
    LLM persistently fails. Never raises — guarantees the pipeline can
    continue with at least the original_prompt + expanded_description = raw.
    """
    system = (PROMPTS / "expander.md").read_text(encoding="utf-8")
    validator = _validator()

    user_payload = json.dumps({"prompt": user_prompt}, ensure_ascii=False)

    last_err = None
    for attempt in range(2):
        try:
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=2048, temperature=0.4)
        except Exception as e:
            last_err = e
            if attempt == 0:
                continue
            return _fallback(user_prompt, reason=f"LLM error: {e}")

        # Normalize before strict validation
        _normalize(doc, user_prompt)

        errs = list(validator.iter_errors(doc))
        if not errs:
            return doc

        last_err = errs[0]
        if attempt == 0:
            user_payload = json.dumps({
                "prompt": user_prompt,
                "previous_error": f"{last_err.message[:200]} at /{'/'.join(str(p) for p in last_err.absolute_path)}",
            })
            continue
        return _fallback(user_prompt, reason=f"schema invalid after retry: {last_err.message[:120]}")

    return _fallback(user_prompt, reason="unreachable")


def _normalize(doc: dict, user_prompt: str) -> None:
    """Fix common LLM glitches in-place before schema validation."""
    # Force original_prompt to the raw input no matter what the LLM emitted
    doc["original_prompt"] = user_prompt
    # Trim expanded_description if too long
    desc = doc.get("expanded_description") or ""
    if len(desc) > 2000:
        doc["expanded_description"] = desc[:2000]
    # Coerce missing arrays
    for k in ("implied_rooms", "implied_exterior_features",
               "alexander_intent_keywords", "constraints"):
        if k not in doc or doc[k] is None:
            doc[k] = []
        elif isinstance(doc[k], str):  # LLM occasionally emits a single string
            doc[k] = [doc[k]]
    # Normalize None for optional fields
    for k in ("implied_style", "implied_size_bucket", "implied_category",
               "atmosphere"):
        if k not in doc:
            doc[k] = None


def _fallback(user_prompt: str, *, reason: str) -> dict:
    """Minimal pass-through when the LLM fails. The pipeline still proceeds
    using the raw prompt — degraded experience but no broken generation."""
    print(f"[prompt_expander] fallback engaged ({reason}); using raw prompt verbatim",
          file=__import__("sys").stderr)
    return {
        "original_prompt": user_prompt,
        "expanded_description": user_prompt,
        "implied_style": None,
        "implied_size_bucket": None,
        "implied_category": None,
        "implied_rooms": [],
        "implied_exterior_features": [],
        "atmosphere": None,
        "alexander_intent_keywords": [],
        "constraints": [],
    }


# ────────────────────────────────────────────────────────────────────────
#  Pipeline v4 path — minimal text expansion only.
#
#  v4 prompt_expander emits ONLY {schema_version, original_prompt,
#  expanded_description}. Style / size / category / room list / Alexander
#  patterns are derived downstream by the global_designer + floor_planner
#  via RAG retrieval — not propagated from here.
# ────────────────────────────────────────────────────────────────────────


def _validator_v4():
    return make_validator("expanded_prompt_v4.schema.json")


def expand_v4(user_prompt: str, *, model: str = MODEL_DEFAULT,
                max_attempts: int = 4) -> dict:
    """Pipeline v4 prompt expander — text expansion only.

    Returns a minimal dict {schema_version, original_prompt,
    expanded_description}. On persistent failure RAISES — no silent
    fallbacks (gym constraint: LLM must succeed for variety, no
    deterministic shortcuts).
    """
    system = (PROMPTS / "expander_v4.md").read_text(encoding="utf-8")
    validator = _validator_v4()
    user_payload = json.dumps({"prompt": user_prompt}, ensure_ascii=False)

    last_err = None
    for attempt in range(max_attempts):
        try:
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=1024, temperature=0.4)
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                continue
            raise RuntimeError(
                f"prompt_expander_v4 failed after {max_attempts} attempts: {e}"
            ) from e

        _normalize_v4(doc, user_prompt)
        errs = list(validator.iter_errors(doc))
        if not errs:
            return doc

        last_err = errs[0]
        if attempt < max_attempts - 1:
            user_payload = json.dumps({
                "prompt": user_prompt,
                "previous_error": (f"{last_err.message[:200]} at "
                                    f"/{'/'.join(str(p) for p in last_err.absolute_path)}"),
            })
            continue
        raise ValueError(
            f"prompt_expander_v4 schema invalid after {max_attempts} "
            f"attempts: {last_err.message[:200]}")
    raise RuntimeError("prompt_expander_v4 unreachable")


_NUM_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4,
              "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
              "couple": 2, "pair": 2, "several": 3, "few": 3}
# patrón de rol (singular/plural) → rol canónico
_ROOM_WORDS = [
    (r"bed\s?rooms?", "bedroom"), (r"kitchens?", "kitchen"),
    (r"bath\s?rooms?|toilets?|wash\s?rooms?", "bathroom"),
    (r"living\s?rooms?|lounges?|sitting\s?rooms?", "living_room"),
    (r"dining\s?rooms?", "dining_room"), (r"libraries|library", "library"),
    (r"stud(?:y|ies)|offices?", "study"), (r"hallways?|corridors?", "hallway"),
    (r"entry\s?halls?|foyers?|vestibules?", "entry_hall"),
    (r"chapels?", "chapel"), (r"throne\s?rooms?", "throne_room"),
    (r"great\s?halls?|ballrooms?", "great_hall"), (r"music\s?rooms?", "music_room"),
    (r"nurser(?:y|ies)", "nursery"), (r"pantr(?:y|ies)|storage\s?rooms?", "pantry"),
    (r"attics?", "attic"), (r"basements?|cellars?", "basement"),
    (r"courtyards?", "courtyard_indoor"),
]


def _parse_implied_rooms(prompt: str) -> list:
    """Extrae deterministamente las salas pedidas explícitamente en el prompt.
    'a house with 4 bedrooms and 2 kitchens' → ['bedroom']*4 + ['kitchen']*2."""
    import re
    p = (prompt or "").lower()
    out: list = []
    for pat, role in _ROOM_WORDS:
        for m in re.finditer(r"(\b\w+\b\s+)?(?:" + pat + r")", p):
            pre = (m.group(1) or "").strip()
            n = _NUM_WORDS.get(pre)
            if n is None and pre.isdigit():
                n = int(pre)
            n = n if n else 1
            out.extend([role] * min(n, 12))
    return out


_FLOOR_WORDS = (r"floors?|stor(?:y|ies|ey|eys)|levels?|"
                r"plantas?|pisos?|niveles?|nivel")
# material/colour family -> trigger words in the prompt (English).
_MATERIAL_HINTS = {
    "wood":      ["wood", "wooden", "timber", "oak", "spruce", "log", "plank"],
    "stone":     ["stone", "cobblestone", "granite", "andesite", "rock"],
    "brick":     ["brick"],
    "glass":     ["glass", "glazed"],
    "white":     ["white", "whitewash", "whitewashed", "quartz", "marble"],
    "concrete":  ["concrete"],
    "sandstone": ["sandstone", "adobe", "clay", "desert"],
}


def parse_requests(prompt: str) -> dict:
    """Deterministically extract EXPLICIT user requests from the prompt so the
    downstream agents can design FOR them (rooms, floor count, materials).

    Returns {"rooms": [roles...], "floors": int|None, "materials": [families...]}.
    Used only to GUIDE the LLM (soft) — it never blocks; the evaluator does its
    own parsing for scoring.
    """
    import re
    p = (prompt or "").lower()
    rooms = _parse_implied_rooms(prompt)
    floors = None
    m = re.search(r"\b([a-z]+|\d+)[\s\-]+(?:" + _FLOOR_WORDS + r")\b", p)
    if m:
        tok = m.group(1)
        floors = _NUM_WORDS.get(tok) or (int(tok) if tok.isdigit() else None)
    materials = [fam for fam, kws in _MATERIAL_HINTS.items()
                 if any(re.search(r"\b" + re.escape(k) + r"\b", p) for k in kws)]
    return {"rooms": rooms, "floors": floors, "materials": materials}


def _normalize_v4(doc: dict, user_prompt: str) -> None:
    """Strip extraneous keys (v4 schema forbids them) and pin the fields
    we control (schema_version + original_prompt + implied_rooms parseados)."""
    allowed = {"schema_version", "original_prompt", "expanded_description",
               "implied_rooms"}
    for k in list(doc.keys()):
        if k not in allowed:
            del doc[k]
    doc["schema_version"] = "v4"
    doc["original_prompt"] = user_prompt
    # FIX A: salas pedidas explícitamente (parse determinista del prompt) →
    # se propagan a space_planner (siembra de hints) y a la métrica adherence.
    doc["implied_rooms"] = _parse_implied_rooms(user_prompt)
    desc = doc.get("expanded_description") or ""
    if len(desc) > 2000:
        doc["expanded_description"] = desc[:2000]


def _fallback_v4(user_prompt: str, *, reason: str) -> dict:
    print(f"[prompt_expander v4] fallback engaged ({reason}); "
          f"using raw prompt verbatim",
          file=__import__("sys").stderr)
    # Pad the prompt to satisfy minLength=50 — append a neutral marker the
    # downstream global_designer can ignore. This keeps v4 schema-compliant
    # even when the LLM is unreachable.
    desc = user_prompt
    if len(desc) < 50:
        desc = desc + "  [unexpanded — using the raw user prompt verbatim]"
    return {
        "schema_version": "v4",
        "original_prompt": user_prompt,
        "expanded_description": desc,
    }


if __name__ == "__main__":
    import sys
    prompt = " ".join(sys.argv[1:]) or "small cottage"
    out = expand(prompt)
    print(json.dumps(out, indent=2, ensure_ascii=False))
