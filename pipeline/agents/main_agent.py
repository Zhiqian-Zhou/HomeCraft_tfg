"""Main planner agent: text prompt → design_intent JSON (BOT skeleton + connectors).

Pulls from RAG-B (styles), RAG-C (curated house-level patterns), RAG-A (skill
role catalog) and RAG-E (top-K exemplars via retriever). The LLM call returns
a design_intent that the room/exterior specialists then build from.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .llm import call_llm_json, MODEL_MAIN
from .retriever import retrieve
from .schema_utils import make_validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAG = REPO_ROOT / "rag"
PROMPTS = Path(__file__).resolve().parent / "prompts"

# Curated subset of patterns most relevant to designing a building skeleton.
# These are the only patterns we hand to the main agent (compressing context).
_HOUSE_LEVEL_PATTERNS = [
    "intimacy-gradient",
    "light-on-two-sides",
    "common-areas-at-the-heart",
    "the-family-room",
    "the-farmhouse-kitchen",
    "main-entrance",
    "entrance-transition",
    "window-place",
    "building-edge",
    "sheltering-roof",
    "roof-layout",
    "bed-alcove",
    "sequence-of-sitting-spaces",
    "strong-centers",
]

_ROOM_ROLES = [
    "kitchen", "bedroom", "bathroom", "living_room", "dining_room",
    "library", "study", "hallway", "entry_hall", "basement", "attic",
    "courtyard_indoor", "chapel", "throne_room", "great_hall", "music_room",
    "nursery", "pantry",
]

_EXTERIOR_FEATURE_ROLES = [
    "garden_bed", "perimeter_wall", "fountain", "pergola", "gazebo",
    "stable", "dovecote", "statue_pedestal", "bridge_arched", "drawbridge",
    "moat", "gatehouse", "path", "tree",
]


def _load_styles_compact() -> list[dict]:
    out = []
    for f in sorted((RAG / "styles").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        # Compress to a single object per style; pick first item per palette slot.
        palette = d.get("palette", {})
        flat = {k: (v[0] if isinstance(v, list) and v else v) for k, v in palette.items()}
        out.append({
            "id":          d["id"],
            "name":        d.get("name", d["id"]),
            "palette":     flat,
            "signature":   d.get("signature_elements", []),
            "ratios":      d.get("ratios", {}),
            "patterns":    d.get("alexander_patterns", []),
        })
    return out


def _styles_for_prompt(text: str, k: int = 3) -> list[dict]:
    """Return top-K style packs most relevant to the prompt text.

    Avoids dumping all 10 styles into LLM context when the prompt
    clearly leans toward 2-3 of them. Uses simple overlap scoring
    against style id + signature_elements.
    """
    import re as _re
    all_styles = _load_styles_compact()
    if not text:
        return all_styles[:k]
    text_lc = text.lower()
    tokens = set(_re.findall(r"[a-z][a-z0-9-]+", text_lc))

    def _score(s: dict) -> float:
        sid = s.get("id", "").lower()
        # id presence is worth more than signature overlap
        score = 3.0 if sid in text_lc else 0.0
        sigs = " ".join(s.get("signature", [])).lower()
        sig_tokens = set(_re.findall(r"[a-z][a-z0-9-]+", sigs))
        score += len(tokens & sig_tokens)
        return score
    ranked = sorted(all_styles, key=_score, reverse=True)
    return ranked[:k]


def _load_patterns_compact() -> list[dict]:
    out = []
    for pid in _HOUSE_LEVEL_PATTERNS:
        f = RAG / "patterns" / f"{pid}.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))
        out.append({
            "id":         d["id"],
            "name":       d.get("name", d["id"]),
            "paraphrase": (d.get("paraphrase") or "")[:250],
            "skills":     d.get("skills_embodying", [])[:6],
        })
    return out


def _exemplar_brief(hit: dict) -> dict:
    return {
        "id":           hit["id"],
        "title":        hit["title"][:80],
        "style":        hit["style"],
        "category":     hit["category"],
        "size_bucket":  hit["size_bucket"],
        "bbox_size":    hit["bbox_size"],
        "score":        round(hit["score"], 3),
        "description":  (hit.get("description_short") or "")[:200],
    }


def _design_intent_validator():
    return make_validator("design_intent.schema.json")


def design_intent(user_prompt: str, *, k_exemplars: int = 5,
                  model: str = MODEL_MAIN,
                  hints: dict | None = None) -> dict:
    """Produce a design_intent JSON for the given user prompt.

    Pipeline:
      1. Retrieve top-K exemplars from RAG-E.
      2. Assemble compact context (styles, curated patterns, room roles).
      3. Call the LLM with the prompts/main.md system message.
      4. Validate against design_intent.schema.json. On failure, retry once
         with the error message appended to the user content.

    Args:
      user_prompt: the (possibly already-expanded) prompt text to drive
        retrieval + main planning.
      hints: optional dict from the prompt_expander Stage 0 with
        implied_style / implied_size_bucket / implied_rooms /
        alexander_intent_keywords / constraints. Passed to the LLM as
        extra context — main agent treats them as strong suggestions but
        is still free to override if the prompt conflicts.

    Returns: the parsed and validated design_intent dict.
    """
    hits = retrieve(user_prompt, k=k_exemplars)
    exemplars = [_exemplar_brief(h) for h in hits]

    context = {
        "user_prompt": user_prompt,
        "exemplars":   exemplars,
        "styles":      _load_styles_compact(),
        "patterns":    _load_patterns_compact(),
        "room_roles":  _ROOM_ROLES,
        "exterior_feature_roles": _EXTERIOR_FEATURE_ROLES,
    }
    if hints:
        # Surface the expander's structured suggestions to the LLM.
        # The main_agent prompt template treats `hints` as soft guidance.
        context["expander_hints"] = {
            k: v for k, v in hints.items()
            if k in ("implied_style", "implied_size_bucket", "implied_category",
                      "implied_rooms", "implied_exterior_features",
                      "atmosphere", "alexander_intent_keywords", "constraints")
            and v not in (None, [], "")
        }
    system = (PROMPTS / "main.md").read_text(encoding="utf-8")
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)

    validator = _design_intent_validator()

    last_err = None
    for attempt in range(2):  # one initial + one retry
        try:
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=16384, temperature=0.4)
        except Exception as e:
            if attempt == 0:
                last_err = e
                continue
            raise RuntimeError(f"main_agent LLM call failed: {e}") from e

        # Coerce common LLM glitches before strict schema check.
        _normalize_design_intent(doc)

        errs = list(validator.iter_errors(doc))
        if not errs:
            # Sanity post-checks (cheap rule-based) — not in schema
            _post_validate(doc)
            return doc

        last_err = errs[0]
        if attempt == 0:
            # Retry with the error message as feedback
            feedback = (
                f"\n\n[VALIDATION ERROR — retry now]\n"
                f"Your previous response failed schema validation:\n"
                f"  {last_err.message[:300]}\n"
                f"At path: {'/'.join(str(p) for p in last_err.absolute_path) or '(root)'}\n"
                f"Fix this and return ONLY the corrected JSON object.")
            user_payload = user_payload + feedback
            continue
        raise ValueError(
            f"main_agent output failed validation after retry: {last_err.message[:300]} "
            f"at /{'/'.join(str(p) for p in last_err.absolute_path)}")

    raise RuntimeError("unreachable")


def _post_validate(doc: dict) -> None:
    """Cheap rule-based checks beyond schema, with auto-fix for common slips."""
    # site_aabb encloses building_aabb: auto-expand site if needed (LLM
    # frequently puts y1=0 on the site when only the ground layer matters).
    s = doc.get("site_aabb")
    b = doc.get("building_aabb")
    if s and b:
        new_s = [
            min(s[0], b[0]), min(s[1], b[1]), min(s[2], b[2]),
            max(s[3], b[3]), max(s[4], b[4]), max(s[5], b[5]),
        ]
        if new_s != s:
            doc["site_aabb"] = new_s
    # Every room.floor must be a valid floor index
    floor_ix = {f["index"] for f in doc.get("floors", [])}
    for r in doc.get("rooms", []):
        if r["floor"] not in floor_ix:
            raise ValueError(f"room {r['id']} references floor index {r['floor']} not in floors")
    # Room AABBs may overlap when the LLM is sloppy. The aggregator will
    # flag this in master_plan.warnings; the composer's later-wins picks
    # the later room's blocks. We tolerate it instead of failing so the
    # pipeline produces a viewable building even on imperfect designs.


def _normalize_dir(v):
    """Normalize compass direction to short form: 'north'/'NORTH'/'n' → 'n'.

    Unknown values (e.g. 'u', 'up', 'down', '') fall back to 'n' — this
    keeps schema validation happy even when the LLM invents directions.
    """
    if not isinstance(v, str):
        return "n"
    lv = v.lower().strip()
    return {"north": "n", "south": "s", "east": "e", "west": "w",
            "n": "n", "s": "s", "e": "e", "w": "w"}.get(lv, "n")


def _normalize_design_intent(doc: dict) -> None:
    """Coerce common LLM glitches in-place so the schema validates.

    - Normalize compass directions: 'north'/'NORTH' → 'n', etc.
    - Default block_keys when missing.
    The schema now allows additional properties on connector items, so
    stray fields the LLM occasionally adds (e.g. "type") no longer fail.
    """
    c = doc.get("connectors", {})
    for d in c.get("doors", []) or []:
        if "facing" in d:
            d["facing"] = _normalize_dir(d["facing"])
        d.setdefault("block_key", "@door")
    for w in c.get("windows", []) or []:
        if "wall" in w:
            w["wall"] = _normalize_dir(w["wall"])
        w.setdefault("block_key", "@glass_pane")
    for s in c.get("staircases", []) or []:
        s.setdefault("block_key", "@stairs")
        s.setdefault("shape", "straight")


def _aabb_overlap_volume(a: list[int], b: list[int]) -> int:
    dx = max(0, min(a[3], b[3]) - max(a[0], b[0]))
    dy = max(0, min(a[4], b[4]) - max(a[1], b[1]))
    dz = max(0, min(a[5], b[5]) - max(a[2], b[2]))
    return dx * dy * dz


if __name__ == "__main__":
    import sys
    prompt = " ".join(sys.argv[1:]) or "a small medieval cottage with a kitchen and a bedroom"
    di = design_intent(prompt)
    print(json.dumps(di, indent=2, ensure_ascii=False))
