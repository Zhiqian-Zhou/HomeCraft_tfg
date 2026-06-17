"""Global designer — Stage 1a of Pipeline v3 (and v4).

v3 (design_global): receives the expanded user prompt + RAG context
(exemplars, style packs, Alexander patterns) and produces a
global_intent.json containing the GLOBAL decisions only: style, category,
building envelope, floors[], height intent, Alexander rationale.

v4 (design_global_v4): same goal, but additionally retrieves k=8
candidate silhouettes from skill_category="global_silhouette" and forces
the LLM to endorse exactly one. The v4 schema mandates a `silhouette_id`
field plus optional `silhouette_parameters` / `silhouette_rationale`,
and renames `prompt` → `expanded_description` to match the v4 expander.

Neither variant decides rooms (space_planner) or connectors
(connector_planner) or envelope ops (architecture_planner).

Reuses RAG loaders + exemplar brief from main_agent.py to keep context
construction consistent.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

from .llm import call_llm_json, MODEL_MAIN
from .main_agent import (
    PROMPTS, _exemplar_brief, _load_patterns_compact, _load_styles_compact,
    _styles_for_prompt,
)
from .retriever import retrieve, retrieve_skills
from .schema_utils import make_validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "rag" / "skills"

# height_intent enums (roof_style/tower_axis/roof_features) cargados del schema
# una vez — para coercer glitches del LLM (más frecuentes con modelos pequeños).
_HI_ENUMS_CACHE: dict | None = None
_ROOF_SYNONYMS = {"asian_roof": "asian", "asian-roof": "asian", "pagoda": "chinese-pagoda",
                  "mixed_per_volume": "gable", "mixed": "gable", "varied": "gable",
                  "pitched": "gable", "sloped": "gable", "saltbox": "gable",
                  "tower_axis": "none"}


# category válida para los validadores downstream (design_intent/master_plan
# usan este enum de 11; el global_v4 promete free-form pero downstream rechaza).
_VALID_CATEGORIES = {"residential", "castle", "tower", "temple", "shop", "tavern",
                     "barn", "windmill", "lighthouse", "monument", "other"}
_CATEGORY_SYNONYMS = {
    "pavilion": "temple", "chapel": "temple", "cathedral": "temple",
    "church": "temple", "shrine": "temple", "mosque": "temple", "pagoda": "temple",
    "mansion": "residential", "manor": "residential", "villa": "residential",
    "house": "residential", "cottage": "residential", "hotel": "residential",
    "inn": "tavern", "palace": "monument", "estate": "monument",
    "library": "monument", "museum": "monument", "hall": "monument",
    "observatory": "monument", "opera_house": "monument", "monastery": "monument",
    "keep": "castle", "fortress": "castle", "fort": "castle", "citadel": "castle",
    "minaret": "tower", "belfry": "tower", "campanile": "tower",
    "barn": "barn", "windmill": "windmill", "lighthouse": "lighthouse",
}


_VALID_STYLES = {"medieval", "fantasy", "gothic", "renaissance", "modern",
                 "minimalist", "japanese", "chinese", "mediterranean", "rustic"}
_STYLE_SYNONYMS = {
    "victorian": "gothic", "baroque": "renaissance", "neoclassical": "renaissance",
    "georgian": "renaissance", "art_deco": "modern", "art-deco": "modern",
    "brutalist": "modern", "industrial": "modern", "contemporary": "modern",
    "colonial": "rustic", "tudor": "medieval", "romanesque": "medieval",
    "byzantine": "mediterranean", "moorish": "mediterranean", "spanish": "mediterranean",
    "greek": "mediterranean", "roman": "mediterranean", "oriental": "japanese",
    "asian": "japanese", "nordic": "rustic", "scandinavian": "minimalist",
}


def _coerce_style(style: str) -> str:
    s = (style or "").strip().lower().replace(" ", "_").replace("-", "_")
    if s in _VALID_STYLES:
        return s
    if s in _STYLE_SYNONYMS:
        return _STYLE_SYNONYMS[s]
    for v in _VALID_STYLES:
        if v in s:
            return v
    # NO coercion to a default: the schema explicitly allows free-form styles
    # ('victorian', 'baroque', …) and the palette resolver (Materials.for_style)
    # already defaults sensibly for unknown styles. Keep the LLM's own choice so
    # it survives into the doc (fidelity/report) — not a deterministic fallback.
    if s:
        print(f"[global_designer INFO] free-form style {s!r} kept "
              f"(palette will default).", file=sys.stderr)
        return s
    return "medieval"   # only when the LLM gave nothing at all


def _coerce_category(cat: str) -> str:
    c = (cat or "").strip().lower().replace(" ", "_").replace("-", "_")
    if c in _VALID_CATEGORIES:
        return c
    if c in _CATEGORY_SYNONYMS:
        return _CATEGORY_SYNONYMS[c]
    for v in _VALID_CATEGORIES:
        if v in c:
            return v
    # Keep the LLM's free-form category (schema allows it); downstream defaults.
    if c:
        print(f"[global_designer INFO] free-form category {c!r} kept.",
              file=sys.stderr)
        return c
    return "other"   # only when the LLM gave nothing at all


def _hi_enums() -> dict:
    global _HI_ENUMS_CACHE
    if _HI_ENUMS_CACHE is None:
        try:
            s = json.loads((REPO_ROOT / "rag" / "schema"
                            / "global_intent_v4.schema.json").read_text())
            hi = s["properties"]["height_intent"]["properties"]
            _HI_ENUMS_CACHE = {
                "roof_style": set(hi.get("roof_style", {}).get("enum") or []),
                "tower_axis": set(hi.get("tower_axis", {}).get("enum") or []),
                "roof_features": set((hi.get("roof_features", {})
                                      .get("items", {}) or {}).get("enum") or []),
            }
        except Exception:
            _HI_ENUMS_CACHE = {"roof_style": set(), "tower_axis": set(),
                               "roof_features": set()}
    return _HI_ENUMS_CACHE


def _validator():
    return make_validator("global_intent.schema.json")


def design_global(user_prompt: str, *,
                   k_exemplars: int = 5,
                   model: str = MODEL_MAIN,
                   hints: dict | None = None) -> dict:
    """Produce a global_intent JSON for the given user prompt.

    Pipeline:
      1. Retrieve top-K exemplars from RAG-E (already top-30% quality-filtered).
      2. Assemble compact context (styles, curated Alexander patterns).
      3. Call the LLM with prompts/global.md as system message (T=0.7 for
         architectural creativity).
      4. Validate against global_intent.schema.json. On failure, retry once
         with the error message appended.

    Returns: the parsed and validated global_intent dict.
    """
    hits = retrieve(user_prompt, k=k_exemplars)
    exemplars = [_exemplar_brief(h) for h in hits]

    context = {
        "user_prompt": user_prompt,
        "exemplars":   exemplars,
        "styles":      _load_styles_compact(),
        "patterns":    _load_patterns_compact(),
    }
    if hints:
        context["expander_hints"] = {
            k: v for k, v in hints.items()
            if k in ("implied_style", "implied_size_bucket", "implied_category",
                      "atmosphere", "alexander_intent_keywords", "constraints")
            and v not in (None, [], "")
        }
    system = (PROMPTS / "global.md").read_text(encoding="utf-8")
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)

    validator = _validator()
    last_err = None
    for attempt in range(2):
        try:
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=4096, temperature=0.7)
        except Exception as e:
            if attempt == 0:
                last_err = e
                continue
            raise RuntimeError(f"global_designer LLM call failed: {e}") from e

        _normalize(doc, user_prompt)
        errs = list(validator.iter_errors(doc))
        if not errs:
            post_errs = _post_validate(doc)
            if not post_errs:
                return doc
            if attempt == 0:
                feedback = (
                    f"\n\n[GEOMETRY ERROR — retry now]\n"
                    + "\n".join(f"  - {e}" for e in post_errs[:3])
                    + "\nFix and return ONLY the corrected JSON.")
                user_payload = user_payload + feedback
                continue
            raise ValueError(
                f"global_designer geometry failed: {post_errs[0]}")
        last_err = errs[0]
        if attempt == 0:
            feedback = (
                f"\n\n[VALIDATION ERROR — retry now]\n"
                f"Your previous response failed schema validation:\n"
                f"  {last_err.message[:300]}\n"
                f"At path: {'/'.join(str(p) for p in last_err.absolute_path) or '(root)'}\n"
                f"Fix this and return ONLY the corrected JSON object.")
            user_payload = user_payload + feedback
            continue
        raise ValueError(
            f"global_designer output failed validation: {last_err.message[:300]} "
            f"at /{'/'.join(str(p) for p in last_err.absolute_path)}")
    raise RuntimeError("unreachable")


def _post_validate(doc: dict) -> list[str]:
    """Cross-checks that JSON Schema cannot express.

    Catches the common LLM mistakes that cause downstream stages to fail:
    flat site (y1=0), floating buildings (y0>0), gapped floors.
    """
    errs: list[str] = []
    site = doc.get("site_aabb") or []
    bld = doc.get("building_aabb") or []
    floors = doc.get("floors") or []

    if len(site) != 6 or site[0] != 0 or site[2] != 0:
        errs.append(f"site_aabb.x0 and site_aabb.z0 must both be 0 (got "
                     f"x0={site[0] if len(site)==6 else '?'}, "
                     f"z0={site[2] if len(site)==6 else '?'}) — "
                     "negative coordinates break downstream voxelization")
    if len(site) != 6 or site[1] != 0:
        errs.append(f"site_aabb.y0 must be 0 (got {site[1] if len(site)==6 else 'malformed'})")
    if len(site) == 6 and site[4] <= site[1] + 1:
        errs.append(f"site_aabb has zero height: y0={site[1]} y1={site[4]} — "
                     "site must be tall enough to contain the building")
    if len(bld) != 6 or bld[1] != 0:
        errs.append(f"building_aabb.y0 must be 0 — the building sits on the "
                     f"ground (got y0={bld[1] if len(bld)==6 else 'malformed'})")
    if len(bld) == 6 and len(site) == 6:
        if not (site[0] <= bld[0] < bld[3] <= site[3]
                and site[1] <= bld[1] < bld[4] <= site[4]
                and site[2] <= bld[2] < bld[5] <= site[5]):
            errs.append(f"building_aabb {bld} is not contained in site_aabb {site}")

    if not floors:
        errs.append("at least one floor required")
    else:
        # Ground floor must start at y=0
        if int(floors[0].get("y0", -1)) != 0:
            errs.append(f"floors[0].y0 must be 0 (got {floors[0].get('y0')})")
        # No gaps between consecutive floors
        for i in range(len(floors) - 1):
            if int(floors[i]["y1"]) != int(floors[i+1]["y0"]):
                errs.append(
                    f"floor {i} ends at y={floors[i]['y1']} but floor {i+1} "
                    f"starts at y={floors[i+1]['y0']} — no gaps allowed")
        # Last floor must fit in building_aabb
        if len(bld) == 6 and int(floors[-1]["y1"]) > bld[4]:
            errs.append(
                f"top floor ends at y={floors[-1]['y1']} but building_aabb.y1={bld[4]}")
        # Per-floor height >= 3 (head clearance)
        for f in floors:
            h = int(f["y1"]) - int(f["y0"])
            if h < 3:
                errs.append(
                    f"floor {f.get('index')} too short (h={h}); need ≥ 3 blocks")
    return errs


def _normalize(doc: dict, user_prompt: str) -> None:
    """Apply common LLM-output coercions before strict schema check."""
    doc.setdefault("schema_version", "1.0")
    doc.setdefault("prompt", user_prompt)
    doc.setdefault("exemplars_used", [])
    doc.setdefault("alexander_rationale", [])
    doc.setdefault("height_intent", {})

    # Coerce roof_pitch to int if a float slipped through
    hi = doc.get("height_intent") or {}
    if isinstance(hi.get("roof_pitch"), float):
        hi["roof_pitch"] = int(hi["roof_pitch"])

    # Coerce floors[].y0/y1 to int
    for f in doc.get("floors") or []:
        if "y0" in f:
            f["y0"] = int(f["y0"])
        if "y1" in f:
            f["y1"] = int(f["y1"])
        if "index" in f:
            f["index"] = int(f["index"])


# ────────────────────────────────────────────────────────────────────────
#  Pipeline v4 path — silhouette-anchored global design.
#
#  Same LLM-call shape as v3 but adds:
#    · retrieve_skills("global_silhouette", k=8) for the context
#    · post-validation that the LLM picked a real silhouette_id, kept the
#      style within S.tags.style, sized within S.typical_dimensions, etc.
#    · schema = global_intent_v4 (renames prompt → expanded_description)
# ────────────────────────────────────────────────────────────────────────


def _validator_v4():
    return make_validator("global_intent_v4.schema.json")


_SILHOUETTE_CACHE: dict[str, dict] | None = None
_SILHOUETTE_LOCK = threading.Lock()


def _silhouettes() -> dict[str, dict]:
    """Lazy in-memory cache of all global_silhouette skills, keyed by id.
    Thread-safe via double-checked locking — gym runs 10 builds in parallel."""
    global _SILHOUETTE_CACHE
    if _SILHOUETTE_CACHE is None:
        with _SILHOUETTE_LOCK:
            if _SILHOUETTE_CACHE is None:
                cache: dict[str, dict] = {}
                for p in sorted(SKILLS_DIR.glob("*.json")):
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        continue
                    if d.get("skill_category") == "global_silhouette":
                        cache[d["id"]] = d
                _SILHOUETTE_CACHE = cache
    return _SILHOUETTE_CACHE


def _reset_silhouette_cache() -> None:
    """Test helper — invalidates the silhouette cache."""
    global _SILHOUETTE_CACHE
    _SILHOUETTE_CACHE = None


_STYLE_WORDS = (
    "medieval", "fantasy", "gothic", "renaissance", "modern", "minimalist",
    "japanese", "chinese", "mediterranean", "rustic",
)
_SHAPE_SCALE_WORDS = (
    "tower", "cottage", "villa", "mansion", "temple", "chapel", "longhouse",
    "barn", "courtyard", "atrium", "pagoda", "dome", "monolith", "stilt",
    "tiny", "small", "modest", "medium", "large", "huge", "imposing", "tall",
    "narrow", "wide", "low", "grounded", "spreading", "compact",
)

# Map prompt vocabulary → building category (the global_intent enum). Checked
# in order, specific before generic, so "temple palace" → temple. Used to BOOST
# silhouettes whose applicable_to/tags.category match, so a temple prompt picks
# a temple silhouette (not a generic villa) and a palace picks a grand wing/
# block (applicable_to: monument), not a cottage.
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("temple", ("temple", "shrine", "chapel", "cathedral", "pagoda",
                "sanctuary", "monastery", "church", "basilica", "pavilion",
                "altar", "nave")),
    ("castle", ("castle", "keep", "fortress", "fort ", "citadel",
                "stronghold", "bastion", "rampart")),
    ("lighthouse", ("lighthouse", "beacon")),
    ("tower", ("tower", "turret", "spire", "wizard", "watchtower")),
    ("tavern", ("tavern", "inn", "alehouse", "pub")),
    ("barn", ("barn", "stable", "granary", "farmstead")),
    ("windmill", ("windmill",)),
    ("shop", ("shop", "store", "market", "smithy", "forge", "workshop",
              "stall", "bakery", "apothecary")),
    ("monument", ("palace", "mansion", "manor", "estate", "great hall",
                  "ballroom", "monument", "palatial", "stately")),
    ("residential", ("house", "home", "cottage", "villa", "cabin",
                     "residence", "dwelling", "bungalow", "farmhouse",
                     "longhouse")),
)

# Prompts that ask for a big, imposing building → scale toward the silhouette
# MAX instead of its preferred size.
_GRAND_WORDS = (
    "grand", "great", "expansive", "imposing", "monumental", "palatial",
    "huge", "enormous", "vast", "sprawling", "cavernous", "towering",
    "majestic", "palace", "cathedral", "mansion", "stately", "large",
)


def _infer_category(text: str) -> str | None:
    """Best-guess building category from the prompt (None if unclear)."""
    t = (text or "").lower()
    for cat, words in _CATEGORY_KEYWORDS:
        if any(w in t for w in words):
            return cat
    return None


def _is_grand(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in _GRAND_WORDS)


def _distill_silhouette_query(text: str) -> str:
    """Compress the expanded_description to a short query (~30-40 tokens).

    The retrieve_skills() ranker is set-intersection scoring (|q∩doc|/|q|);
    long queries collapse all scores. We extract canonical style words and
    a hand-curated set of shape/scale nouns, then prepend the first
    sentence of the input for topic.
    """
    text_lc = text.lower()
    first_sent = re.split(r"(?<=[.!?])\s+", text)[0] if text else ""
    style_hits = [w for w in _STYLE_WORDS if w in text_lc]
    shape_hits = [w for w in _SHAPE_SCALE_WORDS if w in text_lc]
    parts = [first_sent[:160], " ".join(style_hits), " ".join(shape_hits)]
    return " ".join(p for p in parts if p)


def _silhouette_brief_v4(skill: dict) -> dict:
    """Compact silhouette view tailored for the v4 LLM context.

    Same shape as retriever._skill_brief but always includes the
    `parameters` and `typical_dimensions` blocks — the LLM needs them
    to commit to envelope dimensions.
    """
    tags = skill.get("tags") or {}
    return {
        "id":                  skill.get("id"),
        "name":                skill.get("name", ""),
        "description":         (skill.get("description") or "")[:400],
        "applicable_to":       skill.get("applicable_to", []),
        "style":               tags.get("style", []),
        "category":            tags.get("category"),
        "parameters":          skill.get("parameters", {}),
        "typical_dimensions":  skill.get("typical_dimensions", {}),
        "alexander_patterns":  skill.get("alexander_patterns_relevant", []),
    }


def design_global_v4(expanded_description: str, *,
                      original_prompt: str | None = None,
                      k_exemplars: int = 4,         # 2026-05-30: 2→4 (richer reference pool)
                      k_silhouettes: int = 12,      # 2026-05-30: 3→12 (recommendations, not restrictions)
                      model: str = MODEL_MAIN) -> dict:
    """Pipeline v4 global_designer.

    Args:
        expanded_description: rich 80-200 word paragraph from expand_v4().
        original_prompt: raw user prompt (passed for traceability, optional).
        k_exemplars: top-K reference buildings retrieved from RAG-E.
        k_silhouettes: top-K silhouette skills retrieved from RAG-A.
        model: LLM model name.

    Returns the validated global_intent_v4 dict. Raises ValueError on
    persistent validation failure (no pass-through fallback — every
    downstream stage requires silhouette_id).
    """
    # Inferred building category drives both retrievals below.
    cat = _infer_category(original_prompt or "") or _infer_category(expanded_description)

    # RAG-E exemplars (category-boosted so they match the building type).
    hits = retrieve(expanded_description, k=k_exemplars, boost_category=cat)
    exemplars = [_exemplar_brief(h) for h in hits]

    # RAG-A silhouettes (distill the query first for ranker robustness) +
    # boost by the inferred building category so temple/palace prompts surface
    # the grand temple/wing silhouettes instead of a generic villa.
    query = _distill_silhouette_query(expanded_description)
    sil_hits = retrieve_skills("global_silhouette", k=k_silhouettes,
                                 query=query, boost_category=cat)
    sil_cache = _silhouettes()
    silhouettes = [_silhouette_brief_v4(sil_cache[h["id"]])
                    for h in sil_hits if h["id"] in sil_cache]

    context = {
        "expanded_description": expanded_description,
        "original_prompt":      original_prompt or expanded_description,
        "inferred_category":    cat,
        "exemplars":   exemplars,
        "silhouettes": silhouettes,
        "styles":      _styles_for_prompt(expanded_description, k=3),
        "patterns":    _load_patterns_compact(),
    }
    system = (PROMPTS / "global_v4.md").read_text(encoding="utf-8")
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)

    validator = _validator_v4()
    last_err: str | None = None
    _N_ATTEMPTS = 5  # more feedback rounds: at temp 0.95 the LLM occasionally
                      # emits a malformed/extra-key global_intent; give it room
                      # to self-correct on the schema feedback before failing.
    for attempt in range(_N_ATTEMPTS):
        try:
            # 2026-05-30: temperature 0.7→0.95 — push hard for variety. The
            # post-validate is now mostly soft warns so the LLM has room to
            # produce diverse silhouettes/styles/roofs without rejection risk.
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=4096, temperature=0.95)
        except Exception as e:
            last_err = str(e)
            if attempt < _N_ATTEMPTS - 1:
                continue
            raise RuntimeError(
                f"global_designer_v4 LLM call failed: {e}") from e

        _normalize_v4(doc, expanded_description, original_prompt)
        errs = list(validator.iter_errors(doc))
        if not errs:
            # _post_validate_v4 ahora es prácticamente sólo soft warns
            # (V1-V6 relajados); cualquier `errs` real sería un bug residual
            # de geometría inconsistente (AABBs negativas, floors desordenados).
            post_errs = _post_validate_v4(doc, allowed_sil_ids={s["id"] for s in silhouettes})
            if not post_errs:
                return doc
            if attempt < _N_ATTEMPTS - 1:
                feedback = (
                    f"\n\n[GEOMETRY ERROR — retry now]\n"
                    + "\n".join(f"  - {e}" for e in post_errs[:5])
                    + "\nFix and return ONLY the corrected JSON.")
                user_payload = user_payload + feedback
                continue
            # Last attempt: log the residual errors and accept the doc anyway.
            # Variety > strict geometry coercion.
            print(f"[global_designer_v4 WARN] residual geometry errors after "
                  f"{_N_ATTEMPTS} attempts: {post_errs[:3]} — accepting doc",
                  file=sys.stderr)
            return doc
        first = errs[0]
        last_err = (f"{first.message[:300]} at "
                     f"/{'/'.join(str(p) for p in first.absolute_path)}")
        if attempt < _N_ATTEMPTS - 1:
            feedback = (
                f"\n\n[VALIDATION ERROR — retry now]\n"
                f"Your previous response failed schema validation:\n"
                f"  {last_err}\n"
                f"Fix this and return ONLY the corrected JSON object.")
            user_payload = user_payload + feedback
            continue
        # Hard schema errors still raise — these are structural (wrong types,
        # missing required fields) and can't be downstream-tolerated.
        raise ValueError(
            f"global_designer_v4 output failed schema validation: {last_err}")
    raise RuntimeError("unreachable")


_APPLIED_TO_ENUM = {"site", "building_envelope", "floors", "roof",
                     "orientation", "silhouette"}


def _normalize_alexander_rationale(rationale: list) -> None:
    """Coerce common LLM glitches in alexander_rationale entries:
    - applied_to as string → wrap in single-element list
    - applied_to values outside the schema enum (e.g. 'apse', 'building',
      'walls') → coerce to 'building_envelope' (the catch-all)
    - missing pattern_id field is left for schema to flag
    """
    if not isinstance(rationale, list):
        return
    for entry in rationale:
        if not isinstance(entry, dict):
            continue
        applied = entry.get("applied_to")
        if isinstance(applied, str):
            applied = [applied]
            entry["applied_to"] = applied
        if isinstance(applied, list):
            entry["applied_to"] = [
                a if a in _APPLIED_TO_ENUM else "building_envelope"
                for a in applied
            ]


def _normalize_v4(doc: dict, expanded_description: str,
                    original_prompt: str | None) -> None:
    """Coerce common LLM glitches before strict validation."""
    doc.setdefault("schema_version", "v4")
    if isinstance(doc.get("category"), str):
        doc["category"] = _coerce_category(doc["category"])
    if isinstance(doc.get("style"), str):
        doc["style"] = _coerce_style(doc["style"])   # free-form → enum válido (evita crash downstream)
    if doc.get("schema_version") != "v4":
        doc["schema_version"] = "v4"
    doc["expanded_description"] = expanded_description  # pin
    if original_prompt:
        doc["original_prompt"] = original_prompt
    elif "original_prompt" in doc and not doc["original_prompt"]:
        del doc["original_prompt"]
    # FIX A: salas pedidas explícitamente (parse determinista del prompt) →
    # se propagan a space_planner y a la métrica prompt_adherence.
    from .prompt_expander import _parse_implied_rooms
    doc["implied_rooms"] = _parse_implied_rooms(original_prompt or expanded_description)

    # Drop a stray v3 `prompt` field if the LLM emitted it.
    doc.pop("prompt", None)

    doc.setdefault("exemplars_used", [])
    doc.setdefault("alexander_rationale", [])
    doc.setdefault("height_intent", {})

    # Carry the chosen silhouette's documented parameters — crucially
    # `footprint_shape` — into silhouette_parameters so the downstream
    # planners can build the footprint mask (round tower, U-courtyard, …).
    # LLM-emitted overrides win; skill defaults fill the rest.
    sil = _silhouettes().get(doc.get("silhouette_id") or "")
    if sil:
        merged = dict(sil.get("parameters") or {})
        merged.update(doc.get("silhouette_parameters") or {})
        doc["silhouette_parameters"] = merged

    _normalize_alexander_rationale(doc["alexander_rationale"])

    hi = doc.get("height_intent") or {}
    # Coerce LLM key glitches: map common typos to the real field, then drop any
    # key outside the schema (height_intent is additionalProperties:false, so a
    # stray 'per_factor'/'levels' would fail validation and crash the build).
    _HI_ALIASES = {"per_factor": "per_floor_height", "per_floor": "per_floor_height",
                   "floor_height": "per_floor_height", "perfloorheight": "per_floor_height",
                   "story_height": "per_floor_height", "storey_height": "per_floor_height"}
    for bad, good in _HI_ALIASES.items():
        if bad in hi and good not in hi:
            hi[good] = hi.pop(bad)
    _HI_ALLOWED = {"per_floor_height", "roof_style", "roof_pitch",
                   "has_basement", "tower_axis", "roof_features"}
    for k in list(hi.keys()):
        if k not in _HI_ALLOWED:
            hi.pop(k, None)
    # Coerce enum-valued fields to schema-valid values (modelos pequeños emiten
    # roof_style/tower_axis inventados → fallaban la validación y tumbaban el build).
    enums = _hi_enums()
    rs = hi.get("roof_style")
    if enums["roof_style"] and isinstance(rs, str) and rs not in enums["roof_style"]:
        hi["roof_style"] = _ROOF_SYNONYMS.get(rs.lower().replace(" ", "_"),
                                              "gable" if "gable" in enums["roof_style"]
                                              else next(iter(enums["roof_style"]), "gable"))
    ta = hi.get("tower_axis")
    if enums["tower_axis"] and isinstance(ta, str) and ta not in enums["tower_axis"]:
        hi["tower_axis"] = "corner" if ta.lower() in ("front", "back", "side", "flanking") else "none"
    rf = hi.get("roof_features")
    if enums["roof_features"] and isinstance(rf, list):
        hi["roof_features"] = [x for x in rf if x in enums["roof_features"]]
    if isinstance(hi.get("roof_pitch"), float):
        hi["roof_pitch"] = int(hi["roof_pitch"])
    if isinstance(hi.get("per_floor_height"), float):
        hi["per_floor_height"] = int(hi["per_floor_height"])
    # Gym constraint: clearance metric needs >=4 cells of interior air,
    # which requires per_floor_height >= 5 (1 floor slab + 4 air + 1 ceiling
    # implicit). Force the floor 5+ so vertical_clearance can score.
    if isinstance(hi.get("per_floor_height"), int):
        # clamp a [5, 12] (el schema topa en 12; modelos pequeños ponen 20).
        hi["per_floor_height"] = max(5, min(12, hi["per_floor_height"]))
    doc["height_intent"] = hi

    # Coerce floors[].y1 to satisfy the bumped per_floor_height by
    # rebuilding the floor stack from height_intent. The LLM may have
    # emitted floors with y_size=4 — bump to 5 each.
    floors = doc.get("floors") or []
    if floors and hi.get("per_floor_height", 0) >= 5:
        target_h = int(hi["per_floor_height"])
        # Re-stack floors based on the original indexes
        cursor = 0
        for f in sorted(floors, key=lambda f: int(f.get("index", 0))):
            f["y0"] = int(cursor)
            f["y1"] = int(cursor + target_h)
            cursor += target_h
        # Re-fit building_aabb.y1 to the top of the last floor + 2 (roof)
        bld = doc.get("building_aabb") or []
        if len(bld) == 6 and floors:
            top_y = max(int(f["y1"]) for f in floors)
            if bld[4] < top_y + 2:
                bld[4] = top_y + 2
                doc["building_aabb"] = bld
        site = doc.get("site_aabb") or []
        if len(site) == 6 and len(bld) == 6:
            if site[4] < bld[4] + 2:
                site[4] = bld[4] + 2
                doc["site_aabb"] = site

    for f in doc.get("floors") or []:
        if "y0" in f:
            f["y0"] = int(f["y0"])
        if "y1" in f:
            f["y1"] = int(f["y1"])
        if "index" in f:
            f["index"] = int(f["index"])

    # Coerce building_aabb up to silhouette.typical_dimensions.min if the
    # LLM was too stingy. The LLM sometimes emits y-size 4 for monolith-
    # modern (min y=5) — that fails V2 even though the silhouette+style
    # RELAJADO 2026-05-30: Antes este bloque (a) expandía building_aabb hasta
    # el min de la silhouette y (b) lo escalaba al max para prompts "grand".
    # Ambas sustituían silenciosamente al LLM. Política nueva: sólo log a stderr
    # cuando la dimensión esté fuera de [min, max]; NO se altera la respuesta
    # del LLM. La validación V2/V3 ya emite el warn correspondiente.
    sil_cache = _silhouettes()
    sil_id = doc.get("silhouette_id")
    sil = sil_cache.get(sil_id) if sil_id else None
    if sil is not None:
        bld = doc.get("building_aabb") or []
        td = (sil.get("typical_dimensions") or {})
        mn = td.get("min") or [0, 0, 0]
        if len(bld) == 6 and len(mn) == 3:
            sizes = [bld[3] - bld[0], bld[4] - bld[1], bld[5] - bld[2]]
            below = [(axis, sizes[axis], mn[axis]) for axis in range(3)
                     if sizes[axis] < mn[axis]]
            if below:
                import sys
                print(f"[global_designer_v4 INFO] building_aabb below silhouette "
                      f"'{sil_id}' min on axes {below} — accepted as-is (no "
                      f"silent coercion)", file=sys.stderr)
        # Escalado para prompts 'grand'/'palace': el LLM tiende a quedarse cerca
        # del 'preferred' aunque pidan un palacio. Aquí escalamos building_aabb
        # hacia el max de la silueta (90%) — sin reducir lo que el LLM eligiera —
        # recalculamos las plantas para la nueva altura y crecemos el site.
        if _is_grand((original_prompt or "") + " " + (expanded_description or "")):
            import sys
            bld = doc.get("building_aabb") or []
            mx = td.get("max")
            pref = td.get("preferred") or []
            if len(bld) == 6 and isinstance(mx, list) and len(mx) == 3:
                cur = [bld[3]-bld[0], bld[4]-bld[1], bld[5]-bld[2]]
                tgt = [min(mx[a], max(cur[a], int(round(mx[a] * 0.9))))
                       for a in range(3)]
                if tgt != cur:
                    bld[3] = bld[0] + tgt[0]
                    bld[4] = bld[1] + tgt[1]
                    bld[5] = bld[2] + tgt[2]
                    doc["building_aabb"] = bld
                    # Plantas: rellenar la nueva altura con ~5/planta (más
                    # plantas para edificios altos), repartidas uniformemente.
                    floors = sorted(doc.get("floors") or [],
                                    key=lambda f: int(f.get("index", 0)))
                    n_old = max(1, len(floors))
                    n_new = max(n_old, min(8, round(tgt[1] / 5)))
                    per = max(3, tgt[1] // n_new)
                    new_floors = []
                    yy = bld[1]
                    for i in range(n_new):
                        y1 = bld[4] if i == n_new - 1 else yy + per
                        src = floors[i] if i < len(floors) else dict(floors[-1]) if floors else {}
                        nf = dict(src)
                        nf.update({"index": i, "y0": yy, "y1": y1})
                        nf.setdefault("name", ["ground", "upper", "upper", "upper",
                                               "upper", "upper", "attic", "attic"][min(i, 7)])
                        nf.setdefault("role_hint", "ground" if i == 0 else "upper")
                        new_floors.append(nf)
                        yy = y1
                    doc["floors"] = new_floors
                    # Crecer site para envolver el edificio + apron.
                    site = doc.get("site_aabb") or list(bld)
                    m = max(4, tgt[0] // 6)
                    doc["site_aabb"] = [
                        min(site[0], bld[0]-m), min(site[1], bld[1]), min(site[2], bld[2]-m),
                        max(site[3], bld[3]+m), max(site[4], bld[4]), max(site[5], bld[5]+m)]
                    print(f"[global_designer_v4] grand scale: size {cur} -> {tgt}, "
                          f"floors {n_old} -> {n_new}", file=sys.stderr)


def _parse_floor_range(spec: str) -> tuple[int, int] | None:
    """Parse strings like '1', '1-2', '3-7' into (lo, hi). None on malformed."""
    if not spec:
        return None
    s = str(spec).strip()
    m = re.match(r"^\s*(\d+)\s*$", s)
    if m:
        n = int(m.group(1))
        return (n, n)
    m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", s)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return None


def _post_validate_v4(doc: dict,
                       *, allowed_sil_ids: set[str] | None = None) -> list[str]:
    """v4 post-validation: silhouette rules V1-V6 + v3 geometry rules.

    Returns a list of human-readable error strings (empty = OK).
    Severity:
      hard (return as error → triggers retry):
        V1 silhouette_id unknown
        V2 building_aabb below silhouette.typical_dimensions.min
        V5 style not in silhouette.tags.style
        V6 footprint shape plausibility (L/U/cross/T need x>=6 AND z>=6)
        all v3 geometry rules
      soft (logged to stderr only, never returned as error):
        V3 building_aabb above typical_dimensions.max
        V4 floor count outside preferred_floors range
    """
    import sys
    errs: list[str] = []

    # First, run the inherited v3 geometry checks
    errs.extend(_post_validate(doc))

    sil_id = doc.get("silhouette_id")
    sil_cache = _silhouettes()

    # V1 (RELAJADO 2026-05-30): silhouette_id desconocida.
    # Antes era hard-fail que rechazaba la salida. Ahora es soft-warn + fallback:
    # si el LLM omite o inventa un id, sustituimos por una silueta segura
    # (la primera del set retrieved, o "rectangular-building-silhouette" si
    # ese no existe). El LLM tiene libertad para escoger fuera del set; sólo
    # garantizamos que downstream (footprint_for, palette) tenga un id válido.
    sil = sil_cache.get(sil_id) if sil_id else None
    if sil is None:
        fallback_id = None
        if allowed_sil_ids:
            for candidate in allowed_sil_ids:
                if candidate in sil_cache:
                    fallback_id = candidate
                    break
        if fallback_id is None:
            fallback_id = "rectangular-building-silhouette"
        print(f"[global_designer_v4 WARN] silhouette_id "
              f"{sil_id!r} unknown/missing — falling back to {fallback_id!r}",
              file=sys.stderr)
        doc["silhouette_id"] = fallback_id
        sil = sil_cache.get(fallback_id) or {}
        # Continue validation with the substituted silhouette.

    bld = doc.get("building_aabb") or []
    if len(bld) == 6:
        bw, bh, bd = bld[3] - bld[0], bld[4] - bld[1], bld[5] - bld[2]
        td = (sil.get("typical_dimensions") or {})
        mn = td.get("min") or [0, 0, 0]
        mx = td.get("max") or [9_999, 9_999, 9_999]
        # V2 (RELAJADO): below min → soft warn (antes hard-fail).
        if len(mn) == 3:
            for axis, label, got, mlow in zip(range(3), "xyz",
                                                 (bw, bh, bd), mn):
                if got < mlow:
                    print(f"[global_designer_v4 WARN] building_aabb {label}-size "
                          f"{got} below silhouette '{sil_id}'."
                          f"typical_dimensions.min[{axis}]={mlow}",
                          file=sys.stderr)
        # V3 soft-warn: above max on any axis (ya era soft).
        if len(mx) == 3:
            for axis, label, got, mhigh in zip(range(3), "xyz",
                                                  (bw, bh, bd), mx):
                if got > mhigh:
                    print(f"[global_designer_v4 WARN] building_aabb {label}-size "
                           f"{got} above silhouette '{sil_id}'.typical_dimensions"
                           f".max[{axis}]={mhigh}", file=sys.stderr)

    # V4 soft-warn: floor count outside preferred_floors range (ya era soft).
    floors = doc.get("floors") or []
    spec = (sil.get("parameters") or {}).get("preferred_floors")
    rng = _parse_floor_range(spec) if spec else None
    if rng and floors:
        lo, hi = rng
        if not (lo <= len(floors) <= hi):
            print(f"[global_designer_v4 WARN] floors count {len(floors)} "
                   f"outside silhouette '{sil_id}'.parameters.preferred_floors"
                   f"={spec}", file=sys.stderr)

    # V5 (RELAJADO): style ∉ silhouette.tags.style → soft warn (antes hard-fail).
    tags = sil.get("tags") or {}
    allowed_styles = tags.get("style") or []
    style = doc.get("style")
    if allowed_styles and style and style not in allowed_styles:
        print(f"[global_designer_v4 WARN] style '{style}' atypical for "
              f"silhouette '{sil_id}' (typically: {allowed_styles}); "
              f"accepted as-is", file=sys.stderr)

    # V6 (RELAJADO): footprint shape implausible → soft warn (antes hard-fail).
    fs = (sil.get("parameters") or {}).get("footprint_shape")
    if fs and len(bld) == 6:
        x, z = bld[3] - bld[0], bld[5] - bld[2]
        if fs in ("L", "U", "T", "cross", "cross-plan"):
            if x < 6 or z < 6:
                print(f"[global_designer_v4 WARN] footprint_shape '{fs}' "
                      f"prefers x>=6 AND z>=6 (got x={x}, z={z}); "
                      f"accepted as-is", file=sys.stderr)
        elif fs == "square":
            if abs(x - z) > 1:
                print(f"[global_designer_v4 WARN] footprint_shape 'square' "
                      f"prefers |x-z|<=1 (got x={x}, z={z}); "
                      f"accepted as-is", file=sys.stderr)

    return errs
