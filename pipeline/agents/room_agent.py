"""Room specialist agent: one room from design_intent → room_plan.json (shape ops).

Pulls candidate skills from RAG-A filtered by the room role, the patterns
linked to those skills from RAG-C, plus the connector constraints assembled
by the driver. Calls the LLM with the prompts/room.md system message.
"""
from __future__ import annotations

import json
from pathlib import Path

from .llm import call_llm_json, MODEL_WORKER
from .schema_utils import make_validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAG = REPO_ROOT / "rag"
PROMPTS = Path(__file__).resolve().parent / "prompts"


def _load_skills_by_role(role: str, *, style: str | None = None) -> list[dict]:
    """Return compact descriptions of candidate skills for a room.

    Three acceptance modes (any of which surfaces a skill):
      1. Specific role match: `tags.category` ∈ {role, role_underscore,
         role_hyphen}.
      2. Universal skills: `tags.category == "any"` — generic patches
         that apply across all room roles (decorative floor patterns,
         lighting bands, corner accents, etc.).
      3. **Style-aware boost**: when `style` is provided, also surface skills
         whose `tags.style` list contains it (e.g. for a chinese bedroom we
         add shoji_screen, calligraphy_band, paper_lantern_string, etc.).
         These are RECOMMENDATIONS — the LLM stays free to ignore them.

    Also drops skills with kebab-case ids (metadata-only entries with no
    Python build()) — letting the LLM pick those crashes downstream when
    the voxelizer tries to invoke the missing `build()`.
    """
    role_norm_underscore = role.replace("-", "_")
    role_norm_hyphen     = role.replace("_", "-")
    accept = {role, role_norm_underscore, role_norm_hyphen, "any"}
    style_lc = (style or "").lower()
    out: list[dict] = []
    seen: set[str] = set()
    for f in sorted((RAG / "skills").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        sid = d.get("id", "")
        if "-" in sid or d.get("python_skill_signature") is None:
            continue  # metadata-only; no buildable skill
        tags = d.get("tags") or {}
        cat = tags.get("category", "")
        styles = [s.lower() for s in (tags.get("style") or [])]
        # Surface if: role/any match, OR style boost (when style provided).
        if cat in accept or (style_lc and style_lc in styles):
            if sid in seen:
                continue
            seen.add(sid)
            out.append(_skill_brief(d))
    return out


def _load_skills_for_room(role: str, *,
                            skill_category: str = "room_decoration",
                            fallback: str | None = "room_role") -> list[dict]:
    """v4 retrieval — filter by BOTH room role AND skill_category.

    Args:
        role: the room role (kitchen, bedroom, …).
        skill_category: primary v4 filter ("room_decoration" by default).
        fallback: secondary skill_category tried if the primary returns no
            hits — set to "room_role" so the v4 room_agent transparently
            uses the legacy 18 room_role skills until room_decoration
            entries get extracted (currently 0; see audit_skills_by_category).
            Pass None to disable fallback.

    Returns: list of compact briefs (same shape as _load_skills_by_role).
    """
    role_norm_underscore = role.replace("-", "_")
    role_norm_hyphen     = role.replace("_", "-")
    role_set = {role, role_norm_underscore, role_norm_hyphen}

    def _scan(target_category: str) -> list[dict]:
        hits = []
        for f in sorted((RAG / "skills").glob("*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            if d.get("skill_category") != target_category:
                continue
            cat = (d.get("tags") or {}).get("category", "")
            if cat in role_set:
                hits.append(_skill_brief(d))
        return hits

    primary = _scan(skill_category)
    if primary or fallback is None:
        return primary
    return _scan(fallback)


def _skill_brief(doc: dict) -> dict:
    brief = {
        "id":              doc["id"],
        "name":            doc.get("name", doc["id"]),
        "description":     (doc.get("description") or "")[:300],
        "typical_dims":    doc.get("typical_dimensions", {}),
        "patterns":        doc.get("alexander_patterns_relevant", []),
    }
    # Nota informativa de afinidad de estilo (si el skill la tiene) — el LLM la
    # usa para decidir si encaja en ESTE edificio. No restringe: el skill se
    # ofrece igualmente; la decisión es del LLM.
    if doc.get("style_affinity"):
        brief["style_affinity"] = doc["style_affinity"]
    return brief


def _patterns_for_skills(skill_ids: list[str]) -> list[dict]:
    """Return compact pattern entries for patterns linked to any of the given skills."""
    out = []
    seen = set()
    for f in sorted((RAG / "patterns").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        if any(s in d.get("skills_embodying", []) for s in skill_ids):
            if d["id"] in seen:
                continue
            seen.add(d["id"])
            out.append({
                "id":         d["id"],
                "paraphrase": (d.get("paraphrase") or "")[:200],
            })
    return out


def _style_pack_compact(style: str) -> dict:
    f = RAG / "styles" / f"{style}.json"
    if not f.exists():
        return {"id": style, "palette": {}, "signature_elements": [], "ratios": {}}
    d = json.loads(f.read_text(encoding="utf-8"))
    palette = d.get("palette", {})
    flat = {k: (v[0] if isinstance(v, list) and v else v) for k, v in palette.items()}
    return {
        "id":                  d["id"],
        "palette":             flat,
        "signature_elements":  d.get("signature_elements", [])[:6],
        "ratios":              d.get("ratios", {}),
    }


def _room_plan_validator():
    return make_validator("room_plan.schema.json")


def filter_room_connectors(design_intent: dict, room_id: str) -> dict:
    """Slice the global connectors block down to what concerns this room."""
    c = design_intent.get("connectors", {})
    doors_touching = [d for d in c.get("doors", [])
                       if room_id in d.get("between", [])]
    windows_in = [w for w in c.get("windows", [])
                  if w.get("in_room") == room_id]
    # staircase touches a room if its AABB intersects the room AABB
    room = next((r for r in design_intent.get("rooms", []) if r["id"] == room_id), None)
    staircase_touches = []
    if room is not None:
        ra = room["aabb"]
        for s in c.get("staircases", []):
            sa = s.get("aabb", [])
            if len(sa) == 6 and _aabb_intersect(ra, sa):
                staircase_touches.append(s)
    return {
        "doors_touching":    doors_touching,
        "windows_in":        windows_in,
        "staircase_touches": staircase_touches,
    }


def _aabb_intersect(a: list[int], b: list[int]) -> bool:
    return (a[0] < b[3] and b[0] < a[3]
            and a[1] < b[4] and b[1] < a[4]
            and a[2] < b[5] and b[2] < a[5])


def plan_room(room: dict, style: str, design_intent: dict, *,
              model: str = MODEL_WORKER,
              max_attempts: int = 4,
              fallback_on_failure: bool = False) -> dict:
    """Generate a room_plan for ONE room of the design_intent.

    Gym constraint: NO silent fallback. On persistent LLM failure raise
    so the gym runner sees the failure loudly. fallback_on_failure
    kept for legacy v2.6 callers but defaults to False now.
    """
    role = room["role"]
    candidates = _load_skills_by_role(role, style=style)
    room_connectors = filter_room_connectors(design_intent, room["id"])

    # 2026-05-30 RELAJADO: dropped `candidate_patterns` (RAG-C) and
    # `style_pack` (RAG-B) from context. The room_agent only needs the
    # SKILL candidates by role to produce decoration ops; everything else
    # was coercive context that pushed the LLM toward look-alike rooms.
    context = {
        "room":              room,
        "style":             style,
        # The user's intent so the decoration matches the requested
        # atmosphere/materials, not just the bare role+style.
        "user_prompt":       design_intent.get("user_prompt", ""),
        "building_description": design_intent.get("expanded_description", ""),
        "candidate_skills":  candidates,
        "room_connectors":   room_connectors,
        "reserved_coords":   _reserved_coords(room_connectors),
    }
    system = (PROMPTS / "room.md").read_text(encoding="utf-8")
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)

    validator = _room_plan_validator()

    last_err = None
    for attempt in range(max_attempts):
        try:
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=2048, temperature=0.5)
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                continue
            if fallback_on_failure:
                return _fallback_room_plan(room, style, candidates)
            raise RuntimeError(
                f"room_agent({room['id']}) LLM call failed after "
                f"{max_attempts} attempts: {e}") from e

        # Coerce common LLM glitches in shape ops before validating
        _normalize_room_plan(doc, room=room, style=style)

        errs = list(validator.iter_errors(doc))
        if not errs:
            # Palanca B: garantizar detalle de interior determinista.
            doc["ops"] = (doc.get("ops") or []) + _enrich_room_ops(
                room, {tuple(c) for c in _reserved_coords(room_connectors)})
            return doc

        last_err = errs[0]
        if attempt < max_attempts - 1:
            user_payload += (
                f"\n\n[VALIDATION ERROR — retry now]\n"
                f"Your previous output failed schema validation:\n"
                f"  {last_err.message[:300]}\n"
                f"At path: {'/'.join(str(p) for p in last_err.absolute_path) or '(root)'}\n"
                f"Return ONLY the corrected JSON.")
            continue
        if fallback_on_failure:
            return _fallback_room_plan(room, style, candidates)
        raise ValueError(
            f"room_agent({room['id']}) output invalid after "
            f"{max_attempts} attempts: {last_err.message[:300]}")

    raise RuntimeError("unreachable")


def _normalize_room_plan(doc: dict, *, room: dict, style: str) -> None:
    """Clean up common LLM glitches in a room plan before schema validation.

    - Force room_id/role/aabb/style to match the assigned room (the LLM
      sometimes invents these or copies wrong values).
    - Strip `null` values from optional shape-op fields (fill_hollow's
      `fill`/`floor`/`ceiling`, etc.) since the schema's string type
      doesn't accept null.
    """
    doc["room_id"] = room["id"]
    doc["role"] = room["role"]
    doc["aabb"] = room["aabb"]
    if not isinstance(doc.get("style"), str):
        doc["style"] = style
    ops = doc.get("ops") or []
    for op in ops:
        if not isinstance(op, dict):
            continue
        # Drop None-valued optional fields — keeping them violates the
        # string-typed block_ref pattern.
        for k in list(op.keys()):
            if op[k] is None and k in ("fill", "floor", "ceiling", "level",
                                         "hollow", "style", "kwargs"):
                del op[k]


def _fallback_room_plan(room: dict, style: str, candidates: list[dict]) -> dict:
    """Deterministic minimal room plan when the LLM keeps failing.

    Strategy: if there's a candidate skill matching the role, emit a single
    `skill` op for it covering the room AABB. Otherwise emit a `fill_hollow`
    with @primary walls + @floor floor (no ceiling — keeps roof-stackable).
    """
    if candidates:
        skill_id = candidates[0]["id"]
        ops = [{"kind": "skill", "skill_id": skill_id,
                 "aabb": room["aabb"], "style": style}]
        skill_chosen = skill_id
    else:
        ops = [{"kind": "fill_hollow", "aabb": room["aabb"],
                 "wall": "@primary", "floor": "@floor"}]
        skill_chosen = None
    ops = ops + _enrich_room_ops(room, set())
    return {
        "room_id":   room["id"],
        "role":      room["role"],
        "aabb":      room["aabb"],
        "style":     style,
        "patterns_applied": [],
        "skill_chosen":     skill_chosen,
        "ops":              ops,
        "notes":            "deterministic fallback (LLM failed or invalid)",
    }


def _enrich_room_ops(room: dict, reserved: set[tuple]) -> list[dict]:
    """Detalle de interior DETERMINISTA (palanca B): garantiza elaboración aun
    cuando el LLM es conservador. Añade:

      * faroles de pared a la altura de la cabeza (y0+2), embutidos 1 celda
        hacia dentro → mejoran `light_coverage` y dan ornamento. Los faroles
        están en la lista blanca del aligner (`.*_lantern`), así que son
        seguros aunque queden adyacentes al muro.
      * friso interior: recolorea la hilada superior del anillo de muro a
        @accent (cuenta-neutral, sobre muro real → anclado).

    Todo respeta `reserved` (puertas/ventanas/escaleras) y no invade el centro
    transitable. Devuelve ops `place` listas para el composer.
    """
    a = room.get("aabb")
    if not (isinstance(a, list) and len(a) == 6):
        return []
    x0, y0, z0, x1, y1, z1 = a
    w, h, d = x1 - x0, y1 - y0, z1 - z0
    if w < 4 or d < 4 or h < 3:
        return []                       # demasiado pequeño para decorar

    ops: list[dict] = []

    def _add(x, y, z, block):
        if (x, y, z) in reserved:
            return
        ops.append({"kind": "place", "at": [x, y, z], "block": block})

    # Faroles de pared embutidos, espaciados ~2 celdas en los muros interiores
    # (densidad → decoración + luz).
    lamp_y = y0 + 2
    inset_xs = list(range(x0 + 1, x1 - 1))
    inset_zs = list(range(z0 + 1, z1 - 1))
    for x in inset_xs[::2]:
        _add(x, lamp_y, z0 + 1, "@lantern")
        _add(x, lamp_y, z1 - 2, "@lantern")
    for z in inset_zs[::2]:
        _add(x0 + 1, lamp_y, z, "@lantern")
        _add(x1 - 2, lamp_y, z, "@lantern")

    # Salas grandes: rejilla de faroles colgantes del techo (decoración + luz
    # uniforme). Solo en h>=5 y a la altura del techo → NO invade la holgura de
    # cabeza (y0+1/y0+2). Nada a ras de suelo (las macetas a y0+1 hundían
    # vertical_clearance — medido en iter78).
    if w * d >= 36 and h >= 5:
        ceil_y = y1 - 2
        for x in inset_xs[2::3]:
            for z in inset_zs[2::3]:
                _add(x, ceil_y, z, "@lantern")

    # Friso interior: hilada superior del anillo de muro recoloreada a @accent.
    frieze_y = y1 - 1
    for x in range(x0, x1):
        _add(x, frieze_y, z0, "@accent")
        _add(x, frieze_y, z1 - 1, "@accent")
    for z in range(z0 + 1, z1 - 1):
        _add(x0, frieze_y, z, "@accent")
        _add(x1 - 1, frieze_y, z, "@accent")

    return ops


def _reserved_coords(rc: dict) -> list[list[int]]:
    """Flatten connector positions into a list of [x,y,z] coords to avoid."""
    coords = []
    for d in rc.get("doors_touching", []):
        if "at" in d:
            x, y, z = d["at"]
            coords.append([x, y, z])
            coords.append([x, y+1, z])  # door is 2 blocks tall
    for w in rc.get("windows_in", []):
        a = w.get("aabb", [])
        if len(a) == 6:
            for x in range(a[0], a[3]):
                for y in range(a[1], a[4]):
                    for z in range(a[2], a[5]):
                        coords.append([x, y, z])
    for s in rc.get("staircase_touches", []):
        a = s.get("aabb", [])
        if len(a) == 6:
            for x in range(a[0], a[3]):
                for y in range(a[1], a[4]):
                    for z in range(a[2], a[5]):
                        coords.append([x, y, z])
    return coords


if __name__ == "__main__":
    import sys
    # Smoke test with a synthetic minimal design_intent
    di = {
        "rooms": [{"id": "kitchen-1", "role": "kitchen", "floor": 0,
                   "aabb": [0,0,0, 6,4,5]}],
        "connectors": {"doors": [], "windows": [], "staircases": []},
    }
    plan = plan_room(di["rooms"][0], "medieval", di)
    print(json.dumps(plan, indent=2, ensure_ascii=False))
