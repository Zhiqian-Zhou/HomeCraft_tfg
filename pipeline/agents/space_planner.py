"""Space planner — Stage 1b of Pipeline v3 (and v4).

v3 (plan_spaces): emits a space_plan with rooms[] (AABBs + roles + floor)
PLUS an adjacency_graph declaring which rooms should be connected (with
kind=door|opening|none).

v4 (plan_spaces_v4): drops rooms[] and intra-floor adjacency_graph (both
move to the floor_planner added in C.4). Emits only a floor-level
skeleton: one floor_layout_id per floor (picked from RAG-A), the
connector_templates used building-wide, vertical_connections between
floors, entry_points where the building meets 'outside', and soft
room_role_hints_per_floor to guide the floor_planners.

Reuses RAG loaders from main_agent for consistency.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

from .llm import call_llm_json, MODEL_MAIN
from .main_agent import (
    PROMPTS, _exemplar_brief, _load_patterns_compact,
)
from .retriever import retrieve, retrieve_skills
from .schema_utils import make_validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "rag" / "skills"


def _validator():
    return make_validator("space_plan.schema.json")


def plan_spaces(global_intent: dict, *,
                 k_exemplars: int = 3,
                 model: str = MODEL_MAIN) -> dict:
    """Produce a space_plan from a validated global_intent.

    Returns: dict matching space_plan.schema.json.
    """
    prompt = global_intent.get("prompt", "")
    hits = retrieve(prompt, k=k_exemplars)
    exemplars = [_exemplar_brief(h) for h in hits]

    context = {
        "user_prompt": prompt,
        "global_intent": global_intent,
        "exemplars": exemplars,
        "patterns": _load_patterns_compact(),
    }
    system = (PROMPTS / "space.md").read_text(encoding="utf-8")
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)

    validator = _validator()
    last_err = None
    for attempt in range(2):
        try:
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=4096, temperature=0.3)
        except Exception as e:
            if attempt == 0:
                last_err = e
                continue
            raise RuntimeError(f"space_planner LLM call failed: {e}") from e

        _normalize(doc, global_intent)
        errs = list(validator.iter_errors(doc))
        if errs:
            last_err = errs[0]
            if attempt == 0:
                feedback = (
                    f"\n\n[VALIDATION ERROR — retry now]\n"
                    f"Schema error: {last_err.message[:300]}\n"
                    f"At path: {'/'.join(str(p) for p in last_err.absolute_path) or '(root)'}\n"
                    f"Fix this and return ONLY the corrected JSON.")
                user_payload = user_payload + feedback
                continue
            raise ValueError(
                f"space_planner output failed validation: {last_err.message[:300]} "
                f"at /{'/'.join(str(p) for p in last_err.absolute_path)}")

        # Post-validation: cross-checks against global_intent + topology
        post_errs = _post_validate(doc, global_intent)
        if not post_errs:
            return doc
        if attempt == 0:
            feedback = (
                f"\n\n[POST-VALIDATION ERROR — retry now]\n"
                + "\n".join(f"  - {e}" for e in post_errs[:3])
                + "\nFix and return ONLY the corrected JSON.")
            user_payload = user_payload + feedback
            continue
        # Last attempt: try deterministic auto-fix for common errors
        # (floor-y-mismatch, simple overlaps) before giving up.
        _autofix(doc, global_intent)
        remaining = _post_validate(doc, global_intent)
        if not remaining:
            return doc
        raise ValueError(
            f"space_planner post-validation failed after auto-fix: "
            f"{remaining[:3]}")

    raise RuntimeError("unreachable")


def _normalize(doc: dict, global_intent: dict) -> None:
    doc.setdefault("schema_version", "1.0")
    doc.setdefault("rooms", [])
    doc.setdefault("adjacency_graph", [])

    # Coerce ints
    for r in doc.get("rooms") or []:
        if "floor" in r:
            r["floor"] = int(r["floor"])
        if "aabb" in r and isinstance(r["aabb"], list):
            r["aabb"] = [int(v) for v in r["aabb"]]


def _post_validate(doc: dict, global_intent: dict) -> list[str]:
    """Cross-checks that JSON Schema cannot express."""
    errs: list[str] = []
    building_aabb = global_intent.get("building_aabb")
    floors = global_intent.get("floors", [])
    floor_by_idx = {int(f["index"]): f for f in floors}

    room_ids = set()
    by_floor: dict[int, list[dict]] = {}
    for r in doc.get("rooms") or []:
        rid = r["id"]
        if rid in room_ids:
            errs.append(f"duplicate room id: {rid}")
        room_ids.add(rid)
        if rid == "outside":
            errs.append(f"'outside' is a reserved vertex, not a valid room id")
        if building_aabb:
            bx0, by0, bz0, bx1, by1, bz1 = building_aabb
            rx0, ry0, rz0, rx1, ry1, rz1 = r["aabb"]
            if not (bx0 <= rx0 < rx1 <= bx1
                    and by0 <= ry0 < ry1 <= by1
                    and bz0 <= rz0 < rz1 <= bz1):
                errs.append(f"room {rid!r} aabb is outside building_aabb")
        floor = r["floor"]
        f = floor_by_idx.get(floor)
        if f and int(r["aabb"][1]) != int(f["y0"]):
            errs.append(f"room {rid!r}: aabb.y0={r['aabb'][1]} != floors[{floor}].y0={f['y0']}")
        by_floor.setdefault(floor, []).append(r)

    # Same-floor overlap check
    for floor, rs in by_floor.items():
        for i in range(len(rs)):
            for j in range(i + 1, len(rs)):
                if _aabb_overlap_vol(rs[i]["aabb"], rs[j]["aabb"]) > 0:
                    errs.append(
                        f"rooms {rs[i]['id']!r} and {rs[j]['id']!r} overlap on floor {floor}")

    # Adjacency graph: every room must have at least one edge
    edges = doc.get("adjacency_graph") or []
    referenced = set()
    has_outside_edge = False
    for e in edges:
        referenced.add(e["from_room"]); referenced.add(e["to_room"])
        if e["from_room"] == "outside" or e["to_room"] == "outside":
            has_outside_edge = True
    for rid in room_ids:
        if rid not in referenced:
            errs.append(f"room {rid!r} has no adjacency edge (orphan)")
    if not has_outside_edge and room_ids:
        errs.append("building must be enterable: at least one edge must touch 'outside'")

    return errs


def _autofix(doc: dict, global_intent: dict) -> None:
    """Last-resort deterministic repair of common post-validation errors.

    Two fixes:
    1. Snap each room.aabb.y0 to floors[room.floor].y0 (preserving room height
       by shifting y1 by the same delta).
    2. Drop rooms whose aabb overlaps a previously-kept room on the same floor
       (greedy: keep the first one, drop later overlappers + their edges).
    """
    floors = global_intent.get("floors", [])
    floor_by_idx = {int(f["index"]): f for f in floors}

    # 1. Snap y to declared floor
    for r in doc.get("rooms") or []:
        f = floor_by_idx.get(int(r.get("floor", 0)))
        if not f:
            continue
        target_y0 = int(f["y0"])
        current_y0 = int(r["aabb"][1])
        if current_y0 != target_y0:
            dy = target_y0 - current_y0
            r["aabb"][1] += dy
            r["aabb"][4] += dy

    # 2. Drop overlapping rooms (greedy: first wins)
    rooms = doc.get("rooms") or []
    kept_ids: set[str] = set()
    kept_rooms: list[dict] = []
    dropped: set[str] = set()
    for r in rooms:
        overlapped = False
        for kept in kept_rooms:
            if kept["floor"] != r["floor"]:
                continue
            if _aabb_overlap_vol(kept["aabb"], r["aabb"]) > 0:
                overlapped = True
                break
        if overlapped:
            dropped.add(r["id"])
        else:
            kept_rooms.append(r)
            kept_ids.add(r["id"])
    if dropped:
        doc["rooms"] = kept_rooms
        # Drop edges referencing dropped rooms
        doc["adjacency_graph"] = [
            e for e in doc.get("adjacency_graph") or []
            if e["from_room"] not in dropped and e["to_room"] not in dropped
        ]

    # 3. After room/edge dropping, also fix orphan rooms by adding a
    # fallback edge: connect each orphan to "outside" via a door so the
    # building remains enterable. This is a last-resort heuristic.
    referenced = set()
    for e in doc.get("adjacency_graph") or []:
        referenced.add(e["from_room"])
        referenced.add(e["to_room"])
    for r in doc.get("rooms") or []:
        if r["id"] not in referenced:
            doc.setdefault("adjacency_graph", []).append({
                "from_room": "outside" if not any(
                    e.get("from_room") == "outside" or e.get("to_room") == "outside"
                    for e in doc["adjacency_graph"]
                ) else doc["rooms"][0]["id"],
                "to_room": r["id"],
                "kind": "door",
            })


def _aabb_overlap_vol(a: list[int], b: list[int]) -> int:
    dx = max(0, min(a[3], b[3]) - max(a[0], b[0]))
    dy = max(0, min(a[4], b[4]) - max(a[1], b[1]))
    dz = max(0, min(a[5], b[5]) - max(a[2], b[2]))
    return dx * dy * dz


# ────────────────────────────────────────────────────────────────────────
#  Pipeline v4 path — floor-level skeleton (no rooms).
#
#  Drops rooms[] + intra-floor adjacency_graph. Emits only the two skill
#  bindings space_planner owns (floor_layout per floor,
#  connector_templates building-wide) plus vertical_connections,
#  entry_points, and soft room_role_hints_per_floor.
# ────────────────────────────────────────────────────────────────────────


def _validator_v4():
    return make_validator("space_plan_v4.schema.json")


_FLOOR_LAYOUT_CACHE: dict[str, dict] | None = None
_CONNECTOR_TEMPLATE_CACHE: dict[str, dict] | None = None
_FLOOR_LAYOUT_LOCK = threading.Lock()
_CONNECTOR_TEMPLATE_LOCK = threading.Lock()


def _floor_layouts() -> dict[str, dict]:
    """Thread-safe via double-checked locking."""
    global _FLOOR_LAYOUT_CACHE
    if _FLOOR_LAYOUT_CACHE is None:
        with _FLOOR_LAYOUT_LOCK:
            if _FLOOR_LAYOUT_CACHE is None:
                cache: dict[str, dict] = {}
                for p in sorted(SKILLS_DIR.glob("*.json")):
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        continue
                    if d.get("skill_category") == "floor_layout":
                        cache[d["id"]] = d
                _FLOOR_LAYOUT_CACHE = cache
    return _FLOOR_LAYOUT_CACHE


def _connector_templates() -> dict[str, dict]:
    """Thread-safe via double-checked locking."""
    global _CONNECTOR_TEMPLATE_CACHE
    if _CONNECTOR_TEMPLATE_CACHE is None:
        with _CONNECTOR_TEMPLATE_LOCK:
            if _CONNECTOR_TEMPLATE_CACHE is None:
                cache: dict[str, dict] = {}
                for p in sorted(SKILLS_DIR.glob("*.json")):
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        continue
                    if d.get("skill_category") == "connector_template":
                        cache[d["id"]] = d
                _CONNECTOR_TEMPLATE_CACHE = cache
    return _CONNECTOR_TEMPLATE_CACHE


def _reset_v4_caches() -> None:
    """Test helper — invalidates floor_layout + connector_template caches."""
    global _FLOOR_LAYOUT_CACHE, _CONNECTOR_TEMPLATE_CACHE
    _FLOOR_LAYOUT_CACHE = None
    _CONNECTOR_TEMPLATE_CACHE = None


# Floor-type → seed keywords that boost description matches in the
# set-intersection ranker (see C3 retrieval research).
# Roles válidos del schema (room_role_hints_per_floor). El LLM a veces inventa
# sinónimos ('storage', 'office', 'foyer'…) que rompen la validación → se
# coercen al rol válido más cercano en _normalize_v4 (evita fallos de build).
_VALID_ROOM_ROLES: set[str] = {
    "kitchen", "bedroom", "bathroom", "living_room", "dining_room", "library",
    "study", "hallway", "entry_hall", "basement", "attic", "courtyard_indoor",
    "chapel", "throne_room", "great_hall", "music_room", "nursery", "pantry",
}
_ROLE_SYNONYMS: dict[str, str] = {
    "storage": "pantry", "closet": "pantry", "utility": "pantry",
    "workshop": "study", "office": "study", "den": "study",
    "foyer": "entry_hall", "vestibule": "entry_hall", "lobby": "entry_hall",
    "corridor": "hallway", "passage": "hallway", "gallery": "hallway",
    "cellar": "basement", "vault": "basement", "garage": "basement",
    "loft": "attic", "wc": "bathroom", "toilet": "bathroom", "washroom": "bathroom",
    "lounge": "living_room", "sitting_room": "living_room", "parlor": "living_room",
    "parlour": "living_room", "ballroom": "great_hall", "hall": "great_hall",
    "dining": "dining_room", "diningroom": "dining_room", "bed_room": "bedroom",
    "kids_room": "nursery", "children_room": "nursery", "playroom": "nursery",
    "courtyard": "courtyard_indoor", "atrium": "courtyard_indoor",
    "reading_room": "library", "studio": "music_room", "scriptorium": "library",
    "prayer_room": "chapel", "shrine": "chapel", "larder": "pantry",
}


def _coerce_room_role(role: str) -> str:
    """Map an LLM-emitted role to a schema-valid one (synonym or sensible default)."""
    r = (role or "").strip().lower().replace(" ", "_").replace("-", "_")
    if r in _VALID_ROOM_ROLES:
        return r
    if r in _ROLE_SYNONYMS:
        return _ROLE_SYNONYMS[r]
    # substring fallback: pick the first valid role whose name appears in r
    for v in _VALID_ROOM_ROLES:
        if v in r or r in v:
            return v
    # No silent coercion: log loudly that the LLM role was unmappable.
    print(f"[space_planner WARN] room role {role!r} not mappable — using "
          f"'study' (LLM choice unmapped).", file=sys.stderr)
    return "study"          # genérico seguro


_ROLE_HINT_KEYWORDS: dict[str, str] = {
    "ground":   "ground floor entry public common kitchen living",
    "upper":    "upper floor private bedroom",
    "attic":    "attic loft eaves pitched roof dormer truss",
    "basement": "basement cellar vault below_grade",
    "roof":     "roof terrace open-air sky",
    "mezzanine": "mezzanine half-floor partial overlook",
}

# Layouts that are inherently bound to a floor role and must be hard-filtered.
_STRICT_FLOOR_ROLE: dict[str, set[str]] = {
    "attic-truss-layout":    {"attic"},
    "basement-vault-layout": {"basement"},
    "roof-terrace-layout":   {"roof"},
    "mezzanine-layout":      {"mezzanine"},
}


def _layout_query_for_floor(floor: dict, global_intent: dict) -> str:
    """Build a focused query string for retrieve_skills('floor_layout')."""
    role_hint = (floor.get("role_hint") or "").lower()
    style = (global_intent.get("style") or "").lower()
    sil = global_intent.get("silhouette_id") or ""
    sil_short = re.sub(r"-silhouette$", "", sil)
    seed = _ROLE_HINT_KEYWORDS.get(role_hint, "")
    parts = [role_hint, style, sil_short, seed]
    return " ".join(p for p in parts if p)


def _floor_layout_brief_v4(skill: dict) -> dict:
    tags = skill.get("tags") or {}
    return {
        "id":             skill.get("id"),
        "name":           skill.get("name", ""),
        "description":    (skill.get("description") or "")[:300],
        "applicable_to":  skill.get("applicable_to", []),
        "style":          tags.get("style", []),
        "category":       tags.get("category"),
        "parameters":     skill.get("parameters", {}),
    }


def _connector_brief_v4(skill: dict) -> dict:
    tags = skill.get("tags") or {}
    return {
        "id":             skill.get("id"),
        "name":           skill.get("name", ""),
        "description":    (skill.get("description") or "")[:300],
        "applicable_to":  skill.get("applicable_to", []),
        "style":          tags.get("style", []),
        "category":       tags.get("category"),
    }


def plan_spaces_v4(global_intent: dict, *,
                    k_layouts_per_floor: int = 10,    # 2026-05-30: 4→10 (broader recommendations)
                    k_connectors: int = 12,           # 2026-05-30: 5→12 (more connector ideas)
                    k_exemplars: int = 5,             # 2026-05-30: 3→5 (richer references)
                    model: str = MODEL_MAIN) -> dict:
    """Pipeline v4 space_planner.

    Args:
        global_intent: validated global_intent_v4 dict (must include
            silhouette_id, building_aabb, floors[], category, style,
            expanded_description).
        k_layouts_per_floor: top-K floor_layout skills retrieved per floor.
        k_connectors: top-K connector_template skills retrieved building-wide.
        k_exemplars: top-K reference buildings retrieved from RAG-E.
        model: LLM model name.

    Returns the validated space_plan_v4 dict. Raises ValueError on
    persistent validation failure.
    """
    expanded = global_intent.get("expanded_description") or ""
    floors = global_intent.get("floors") or []
    style = global_intent.get("style")
    category = global_intent.get("category")

    # Retrieve floor_layouts per floor (one list per floor)
    floor_layouts_per_floor: list[list[dict]] = []
    fl_cache = _floor_layouts()
    for f in floors:
        role_hint = (f.get("role_hint") or "").lower()
        query = _layout_query_for_floor(f, global_intent)
        hits = retrieve_skills("floor_layout", k=k_layouts_per_floor,
                                 query=query, applicable_to=category)
        # Filter out layouts that are strict-bound to a different role.
        cleaned: list[dict] = []
        for h in hits:
            strict_roles = _STRICT_FLOOR_ROLE.get(h["id"], set())
            if strict_roles and role_hint not in strict_roles:
                continue
            full = fl_cache.get(h["id"])
            if full is None:
                continue
            cleaned.append(_floor_layout_brief_v4(full))
        floor_layouts_per_floor.append(cleaned)

    # Retrieve connector_templates building-wide
    sil_id = global_intent.get("silhouette_id") or ""
    conn_query = " ".join(p for p in [style, category,
                                       re.sub(r"-silhouette$", "", sil_id),
                                       "entrance stair door"] if p)
    conn_hits = retrieve_skills("connector_template", k=k_connectors,
                                  query=conn_query, applicable_to=category)
    ct_cache = _connector_templates()
    connectors = [_connector_brief_v4(ct_cache[h["id"]])
                   for h in conn_hits if h["id"] in ct_cache]

    # 2026-05-30 RELAJADO: Antes inyectábamos top-k exemplars de RAG-E aquí.
    # Política nueva: el space_planner sólo necesita los SKILLS que va a picar
    # (floor_layouts + connector_templates ya retrievados arriba). Sin
    # exemplars y sin patterns — más variedad, menos coerción.
    context = {
        "user_prompt":         global_intent.get("user_prompt", ""),
        "expanded_description": global_intent.get("expanded_description", ""),
        "requested":           global_intent.get("requested", {}),
        "global_intent":       global_intent,
        "floor_layouts":       floor_layouts_per_floor,
        "connector_templates": connectors,
    }
    system = (PROMPTS / "space_v4.md").read_text(encoding="utf-8")
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)

    validator = _validator_v4()
    last_err: str | None = None
    _ATTEMPTS = 5                       # more feedback rounds for weaker LLMs
    for attempt in range(_ATTEMPTS):
        try:
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=6144, temperature=0.3)
        except Exception as e:
            last_err = str(e)
            if attempt < _ATTEMPTS - 1:
                continue
            raise RuntimeError(
                f"space_planner_v4 LLM call failed: {e}") from e

        _normalize_v4(doc, global_intent)
        errs = list(validator.iter_errors(doc))
        if not errs:
            post_errs = _post_validate_v4(doc, global_intent)
            if not post_errs:
                return doc
            if attempt < _ATTEMPTS - 1:
                feedback = (
                    f"\n\n[POST-VALIDATION ERROR — retry now]\n"
                    + "\n".join(f"  - {e}" for e in post_errs[:5])
                    + "\nFix and return ONLY the corrected JSON.")
                user_payload = user_payload + feedback
                continue
            raise ValueError(
                f"space_planner_v4 post-validation failed: {post_errs[0]}")
        first = errs[0]
        last_err = (f"{first.message[:300]} at "
                     f"/{'/'.join(str(p) for p in first.absolute_path)}")
        if attempt < _ATTEMPTS - 1:
            feedback = (
                f"\n\n[VALIDATION ERROR — retry now]\n"
                f"Your previous response failed schema validation:\n"
                f"  {last_err}\n"
                f"Fix this and return ONLY the corrected JSON object.")
            user_payload = user_payload + feedback
            continue
        raise ValueError(
            f"space_planner_v4 output failed schema validation: {last_err}")
    raise RuntimeError("unreachable")


_VALID_SIDES = ("+x", "-x", "+z", "-z")
_SIDE_SYNONYMS = {
    "north": "-z", "south": "+z", "east": "+x", "west": "-x",
    "n": "-z", "s": "+z", "e": "+x", "w": "-x",
    "front": "+z", "back": "-z", "rear": "-z", "left": "-x", "right": "+x",
    "+y": "+z", "-y": "+z", "top": "+z", "bottom": "+z",
}


def _coerce_side(side) -> str:
    """Devuelve un lado válido (+x/-x/+z/-z). Mapea sinónimos comunes; ante
    cualquier valor desconocido del LLM (p.ej. 'a_flat_face') cae en '+z'."""
    s = str(side or "").strip().lower()
    if s in _VALID_SIDES:
        return s
    if s in _SIDE_SYNONYMS:
        return _SIDE_SYNONYMS[s]
    for k, v in _SIDE_SYNONYMS.items():       # subcadena ('a_flat_face'→? ninguno)
        if k in s:
            return v
    print(f"[space_planner WARN] entry side {side!r} not mappable — using "
          f"'+z' (LLM choice unmapped).", file=sys.stderr)
    return "+z"


def _normalize_v4(doc: dict, global_intent: dict) -> None:
    import sys
    doc.setdefault("schema_version", "v4")
    if doc.get("schema_version") != "v4":
        doc["schema_version"] = "v4"

    # Mirror expanded_description if upstream has one (traceability)
    ed = global_intent.get("expanded_description")
    if ed and "expanded_description" not in doc:
        doc["expanded_description"] = ed

    # Strip stray v3 fields if the LLM emitted them
    for k in ("rooms", "adjacency_graph"):
        doc.pop(k, None)

    # Coerce room_role_hints to schema-valid roles (LLM invents synonyms like
    # 'storage'/'office' → map to nearest valid role, avoids a build failure).
    hints = doc.get("room_role_hints_per_floor")
    if isinstance(hints, list):
        for fi, floor_hints in enumerate(hints):
            if isinstance(floor_hints, list):
                hints[fi] = [_coerce_room_role(r) if isinstance(r, str) else r
                             for r in floor_hints]

    # FIX A: sembrar room_role_hints con las salas PEDIDAS en el prompt
    # (implied_rooms). Garantiza que el conteo/tipo solicitado se represente
    # (planta baja = comunes; plantas altas = dormitorios/privadas). El
    # floor_planner las honra como hints fuertes.
    implied = global_intent.get("implied_rooms") or []
    hints2 = doc.get("room_role_hints_per_floor")
    if implied and isinstance(hints2, list) and hints2:
        n = len(hints2)
        _GROUND = {"kitchen", "dining_room", "living_room", "entry_hall",
                   "bathroom", "great_hall", "library", "study", "chapel", "pantry"}
        import collections
        have = collections.Counter(r for fl in hints2 for r in fl)
        want = collections.Counter(implied)
        for role, cnt in want.items():
            for _ in range(max(0, cnt - have.get(role, 0))):
                fi = 0 if (role in _GROUND or n == 1) else 1 + (len(hints2[min(1, n-1)]) % max(1, n-1))
                fi = min(fi, n - 1)
                hints2[fi].append(role)
        doc["room_role_hints_per_floor"] = hints2

    # Coerce non-catalog floor layouts → 'central-hall-layout'. El floor_planner
    # usa ese mismo BSP fallback para layouts desconocidos, pero el inter_floor_
    # validator (C3) exige que space_plan y floor_plan coincidan: si dejamos un
    # id fuera de catálogo aquí, el fallback pone 'central-hall-layout' y C3
    # falla. Coercionar ahora mantiene el contrato consistente (mismo resultado).
    _layouts = doc.get("floor_layout_id_per_floor")
    if isinstance(_layouts, list):
        _cat = _floor_layouts()
        _layouts = [lid if lid in _cat else "central-hall-layout"
                    for lid in _layouts]
        # Pin the list length to floors.length (MECHANICAL — the LLM sometimes
        # emits too few/many ids). Pad with the last picked layout, truncate
        # extras. The LLM's picks are kept; only the length is made consistent.
        _nf = len(global_intent.get("floors") or [])
        if _nf:
            if len(_layouts) < _nf:
                _pad = _layouts[-1] if _layouts else "central-hall-layout"
                _layouts = _layouts + [_pad] * (_nf - len(_layouts))
            _layouts = _layouts[:_nf]
        doc["floor_layout_id_per_floor"] = _layouts
        # Pin room_role_hints_per_floor to the same length (MECHANICAL): pad
        # with [] (floor_planner falls back to its minimal role vocab), truncate
        # extras. Keeps the LLM's hints; only fixes the list length.
        _nf2 = len(global_intent.get("floors") or [])
        _hints = doc.get("room_role_hints_per_floor")
        if _nf2 and isinstance(_hints, list):
            if len(_hints) < _nf2:
                _hints = _hints + [[] for _ in range(_nf2 - len(_hints))]
            doc["room_role_hints_per_floor"] = _hints[:_nf2]

    # Infer missing role for connector_templates_used entries.
    # LLM occasionally emits just {"template_id": "..."} without role.
    for c in doc.get("connector_templates_used") or []:
        if not isinstance(c, dict):
            continue
        if "role" not in c or not c["role"]:
            tid = (c.get("template_id") or "").lower()
            if "stair" in tid or "ladder" in tid or "ramp" in tid:
                c["role"] = "stair"
            elif "balcony" in tid:
                c["role"] = "balcony"
            elif ("garden" in tid or "secondary" in tid
                  or "back-door" in tid):
                c["role"] = "secondary_entrance"
            elif "entrance" in tid or "front" in tid or "portal" in tid:
                c["role"] = "entrance"
            else:
                c["role"] = "interior_passage"

    # Coerce ints (robust to weak-model quirks: lists, floats, numeric strings).
    # Sanitisation, not a content fallback — a malformed scalar must not crash
    # the whole build with a raw TypeError.
    def _as_int(v):
        while isinstance(v, (list, tuple)) and v:   # LLM emitted [n] or [a,b]
            v = v[0]
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None
    for vc in doc.get("vertical_connections") or []:
        if "from_floor" in vc:
            vc["from_floor"] = _as_int(vc["from_floor"])
        if "to_floor" in vc:
            vc["to_floor"] = _as_int(vc["to_floor"])
    # Drop connections whose floors couldn't be coerced (malformed → unusable).
    if doc.get("vertical_connections"):
        doc["vertical_connections"] = [
            vc for vc in doc["vertical_connections"]
            if vc.get("from_floor") is not None and vc.get("to_floor") is not None]
    for ep in doc.get("entry_points") or []:
        if "floor" in ep:
            ep["floor"] = _as_int(ep["floor"]) or 0
        # Coerce el enum `side` a uno válido (el LLM débil a veces inventa
        # 'a_flat_face', 'front', 'north'…). Mapea sinónimos y, si no, +z.
        ep["side"] = _coerce_side(ep.get("side"))

    # Auto-fix: if any vertical_connection references a template_id not
    # marked as 'stair' in connector_templates_used, substitute the
    # first stair template found. If no stair exists, leave it and let
    # post_validate raise (the LLM forgot to pick a stair entirely).
    conns = doc.get("connector_templates_used") or []
    stair_ids = [c.get("template_id") for c in conns
                  if c.get("role") == "stair" and c.get("template_id")]
    if stair_ids:
        default_stair = stair_ids[0]
        for vc in doc.get("vertical_connections") or []:
            tid = vc.get("template_id")
            if tid not in stair_ids:
                print(f"[space_planner WARN] vertical_connection "
                       f"({vc.get('from_floor')}-{vc.get('to_floor')}) "
                       f"template_id='{tid}' is not a stair; "
                       f"replacing with '{default_stair}'",
                       file=sys.stderr)
                vc["template_id"] = default_stair

    # Auto-synthesize missing vertical_connections for multi-floor builds.
    # The LLM sometimes forgets the array entirely; without it the
    # connector_planner has no stair to materialize. Use the first stair
    # template_id if available; if no stair, add a placeholder that the
    # connector will skip.
    n_floors = len(global_intent.get("floors") or [])
    vcs = doc.get("vertical_connections") or []
    if n_floors > 1 and len(vcs) < n_floors - 1 and stair_ids:
        print(f"[space_planner WARN] vertical_connections has "
               f"{len(vcs)} entries, expected {n_floors - 1} — "
               f"auto-synthesizing missing pairs with "
               f"template_id='{stair_ids[0]}'", file=sys.stderr)
        existing_pairs = {(int(v.get("from_floor", -1)),
                            int(v.get("to_floor", -1))) for v in vcs}
        for i in range(n_floors - 1):
            if (i, i + 1) not in existing_pairs:
                vcs.append({"from_floor": i, "to_floor": i + 1,
                             "template_id": stair_ids[0]})
        doc["vertical_connections"] = vcs


def _post_validate_v4(doc: dict, global_intent: dict) -> list[str]:
    """v4 post-validation: skill-id resolution + cross-floor coherence."""
    errs: list[str] = []
    floors = global_intent.get("floors") or []
    n_floors = len(floors)
    fl_cache = _floor_layouts()
    ct_cache = _connector_templates()

    # V1 length match
    layouts = doc.get("floor_layout_id_per_floor") or []
    if len(layouts) != n_floors:
        errs.append(
            f"floor_layout_id_per_floor length {len(layouts)} != "
            f"floors.length {n_floors}")
    # V2 every layout id resolves — soft warn (was hard fail). _normalize_v4
    # already coerces unknown ids to 'central-hall-layout' before this runs, so
    # this normally never fires; the LLM keeps creative freedom on the name.
    import sys
    for i, lid in enumerate(layouts):
        if lid not in fl_cache:
            print(f"[space_planner_v4 WARN] floor_layout_id_per_floor[{i}]="
                  f"'{lid}' not in catalog — normalized to a catalog default.",
                  file=sys.stderr)
    # V3 every connector_template_id resolves — soft warn (was hard fail).
    conns = doc.get("connector_templates_used") or []
    for i, c in enumerate(conns):
        if c.get("template_id") not in ct_cache:
            print(f"[space_planner_v4 WARN] connector_templates_used[{i}]."
                  f"template_id='{c.get('template_id')}' not in catalog — "
                  "connector_planner will fall back to a generic door/stair.",
                  file=sys.stderr)

    # V4 secondary_entrance cap
    n_sec = sum(1 for c in conns if c.get("role") == "secondary_entrance")
    if n_sec > 2:
        errs.append(
            f"too many secondary_entrance connectors: {n_sec} (max 2)")

    # V5 vertical_connections count + coverage
    vcs = doc.get("vertical_connections") or []
    if n_floors > 1:
        expected = n_floors - 1
        if len(vcs) != expected:
            errs.append(
                f"vertical_connections count {len(vcs)} != floors.length-1 "
                f"({expected}); needs one entry per consecutive pair")
        pairs = {(int(v.get("from_floor", -1)), int(v.get("to_floor", -1)))
                  for v in vcs}
        for i in range(n_floors - 1):
            if (i, i + 1) not in pairs:
                errs.append(
                    f"missing vertical_connection for pair ({i},{i+1})")
    else:
        if vcs:
            errs.append(
                "vertical_connections must be empty for single-floor "
                "buildings")

    # V6 every vc.template_id appears in connector_templates_used with role=stair
    stair_ids = {c.get("template_id") for c in conns
                  if c.get("role") == "stair"}
    for vc in vcs:
        tid = vc.get("template_id")
        if tid not in stair_ids:
            errs.append(
                f"vertical_connections[(...)].template_id='{tid}' must also "
                f"appear in connector_templates_used with role='stair'")

    # V7 at least one entry_point at floor 0
    eps = doc.get("entry_points") or []
    if eps and not any(int(e.get("floor", -1)) == 0 for e in eps):
        errs.append("at least one entry_point MUST have floor=0")
    # V8 entry_point template_ids in connectors as entrance|secondary_entrance
    entry_ids = {c.get("template_id") for c in conns
                  if c.get("role") in ("entrance", "secondary_entrance")}
    for i, e in enumerate(eps):
        if e.get("template_id") not in entry_ids:
            errs.append(
                f"entry_points[{i}].template_id='{e.get('template_id')}' "
                f"must also appear in connector_templates_used with role "
                f"'entrance' or 'secondary_entrance'")

    # V9 silhouette coherence — soft warn (was hard fail). A tower silhouette
    # picking grand-staircase usually reads as wasteful, but a wide
    # ground-floor lobby may legitimately host a grand stair before the
    # tower body proper starts above. Let the LLM decide and warn instead.
    sil = (global_intent.get("silhouette_id") or "").lower()
    is_tower = ("tower" in sil or
                (global_intent.get("height_intent") or {}).get("tower_axis")
                in ("central", "corner"))
    if is_tower:
        for c in conns:
            if c.get("template_id") == "grand-staircase":
                import sys
                print("[space_planner_v4 WARN] tower silhouette/axis with "
                      "'grand-staircase' — usually wasteful; let through.",
                      file=sys.stderr)
                break

    # V10 room_role_hints_per_floor length (when present)
    hints = doc.get("room_role_hints_per_floor")
    if hints is not None and len(hints) != n_floors:
        errs.append(
            f"room_role_hints_per_floor length {len(hints)} != "
            f"floors.length {n_floors}")

    return errs
