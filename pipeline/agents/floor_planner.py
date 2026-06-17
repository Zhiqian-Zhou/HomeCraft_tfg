"""Floor planner — Stage 1c of Pipeline v4 (NEW).

One LLM call per floor (N parallel calls via ThreadPoolExecutor). Each
floor_planner instance receives:

  - global_intent_v4 (building_aabb, floors[], style, category, silhouette_id)
  - the per-floor slice of space_plan_v4 (floor_layout_id, role_hints,
    entry_points on this floor, reserved_footprints projected from
    vertical_connections involving this floor)
  - the full floor_layout skill JSON
  - room_role skill briefs (preloaded — catalog is tiny, no per-role retrieval)

…and emits a `floor_plan.json` with rooms[] + adjacency_graph[] +
reserved_footprints[] for THAT floor only.

Cross-floor coherence (stair landings, id collisions, entry-point match) is
handled by inter_floor_validator after all N floors complete.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import os
from .llm import call_llm_json, MODEL_MAIN
# Hybrid arm: let the floor stage use a different backbone (e.g. the base model
# while other stages use the SFT). Defaults to MODEL_MAIN so behaviour is unchanged.
MODEL_FLOOR = os.environ.get("MODEL_FLOOR", MODEL_MAIN)
from .main_agent import PROMPTS
from .schema_utils import make_validator
from .footprint import footprint_for
from ._fallback import fallback_enabled

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "rag" / "skills"


def _validator():
    return make_validator("floor_plan.schema.json")


_FLOOR_LAYOUT_FULL_CACHE: dict[str, dict] | None = None
_ROOM_ROLE_BRIEFS: list[dict] | None = None
_FLOOR_LAYOUT_FULL_LOCK = threading.Lock()
_ROOM_ROLE_LOCK = threading.Lock()


def _floor_layouts_full() -> dict[str, dict]:
    """All floor_layout skill JSONs (full content, not briefs) keyed by id.
    Thread-safe via double-checked locking."""
    global _FLOOR_LAYOUT_FULL_CACHE
    if _FLOOR_LAYOUT_FULL_CACHE is None:
        with _FLOOR_LAYOUT_FULL_LOCK:
            if _FLOOR_LAYOUT_FULL_CACHE is None:
                cache: dict[str, dict] = {}
                for p in sorted(SKILLS_DIR.glob("*.json")):
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        continue
                    if d.get("skill_category") == "floor_layout":
                        cache[d["id"]] = d
                _FLOOR_LAYOUT_FULL_CACHE = cache
    return _FLOOR_LAYOUT_FULL_CACHE


def _room_role_briefs() -> list[dict]:
    """All 18 room_role skills as slim briefs — catalog is small enough to
    preload (per C.4.5 research). Thread-safe via double-checked locking."""
    global _ROOM_ROLE_BRIEFS
    if _ROOM_ROLE_BRIEFS is None:
        with _ROOM_ROLE_LOCK:
            if _ROOM_ROLE_BRIEFS is None:
                out: list[dict] = []
                for p in sorted(SKILLS_DIR.glob("*.json")):
                    try:
                        d = json.loads(p.read_text(encoding="utf-8"))
                    except Exception:  # noqa: BLE001
                        continue
                    if d.get("skill_category") != "room_role":
                        continue
                    tags = d.get("tags") or {}
                    out.append({
                        "id":                 d.get("id"),
                        "name":               d.get("name", ""),
                        "description":        (d.get("description") or "")[:400],
                        "category":           tags.get("category"),
                        "typical_dimensions": d.get("typical_dimensions", {}),
                        "alexander_patterns": d.get("alexander_patterns_relevant", []),
                    })
                _ROOM_ROLE_BRIEFS = out
    return _ROOM_ROLE_BRIEFS


def _reset_v4_caches() -> None:
    """Test helper — invalidates floor_planner caches."""
    global _FLOOR_LAYOUT_FULL_CACHE, _ROOM_ROLE_BRIEFS
    _FLOOR_LAYOUT_FULL_CACHE = None
    _ROOM_ROLE_BRIEFS = None


_DEFAULT_STAIR_SIZE: dict[str, tuple[int, int]] = {
    # template_id → (x_span, z_span). XZ footprint of the stair shaft.
    "spiral-staircase":   (3, 3),
    "dogleg-staircase":   (3, 4),
    "split-flight-stair": (3, 4),
    "grand-staircase":    (4, 6),
    "service-staircase":  (1, 4),
    "attic-ladder":       (2, 2),
    "ramp-entry":         (3, 6),
    "lift-shaft":         (2, 2),
    "staircase":          (3, 3),  # legacy
}


def _synthesize_stair_footprint(building_aabb: list[int],
                                  template_id: str | None,
                                  index: int = 0) -> dict:
    """Pick a deterministic XZ rectangle inside the building for a stair
    shaft. Uses the template's typical footprint size and places it in a
    corner offset by `index` so multiple stairs don't overlap."""
    bx0, _, bz0, bx1, _, bz1 = building_aabb
    if template_id and template_id in _DEFAULT_STAIR_SIZE:
        w, d = _DEFAULT_STAIR_SIZE[template_id]
    else:
        # Sin template explícito: varía el tamaño del hueco DETERMINISTAMENTE por
        # edificio → el aggregator construye distintos tipos (espiral/recta/
        # dogleg) según lo que cabe. Da variedad de escaleras entre edificios.
        _variants = [(3, 3), (3, 5), (5, 3), (4, 4), (3, 6), (6, 3)]
        h = (abs(int(sum(building_aabb))) + index * 7) % len(_variants)
        w, d = _variants[h]
    # No dejar que el hueco devore el edificio (cap a ~mitad de cada lado).
    w = max(2, min(w, max(2, (bx1 - bx0) // 2)))
    d = max(2, min(d, max(2, (bz1 - bz0) // 2)))
    # Place the stair near a corner of the building, inset by 1 cell.
    # Multiple stairs (index>0) shift to a different corner.
    corners = [
        (bx1 - 1 - w, bz1 - 1 - d),  # +x, +z
        (bx0 + 1,      bz1 - 1 - d),  # -x, +z
        (bx1 - 1 - w, bz0 + 1),       # +x, -z
        (bx0 + 1,      bz0 + 1),      # -x, -z
    ]
    x0, z0 = corners[index % len(corners)]
    x0 = max(bx0 + 1, min(x0, bx1 - 1 - w))
    z0 = max(bz0 + 1, min(z0, bz1 - 1 - d))
    return {"x0": int(x0), "z0": int(z0),
             "x1": int(x0 + w), "z1": int(z0 + d)}


def _reserved_footprints_for_floor(space_plan: dict, floor_index: int,
                                     building_aabb: list[int] | None = None
                                     ) -> list[dict]:
    """Project space_plan.vertical_connections involving this floor into a
    list of reserved_footprints (XZ rectangles).

    If a vertical_connection lacks an explicit `footprint` field, a default
    is synthesized from `building_aabb` + the template's typical stair
    size — so the same shaft lands on both floors (the inter_floor_validator
    IoU check passes).

    If space_plan declares explicit `reserved_footprints` at the top
    level (future extension), those override the synthesis.
    """
    # Future override path
    declared = space_plan.get("reserved_footprints")
    if isinstance(declared, list):
        return [r for r in declared if int(r.get("floor", floor_index)) == floor_index]

    out: list[dict] = []
    vcs = space_plan.get("vertical_connections") or []
    for idx, vc in enumerate(vcs):
        fl_from = int(vc.get("from_floor", -1))
        fl_to = int(vc.get("to_floor", -1))
        if floor_index not in (fl_from, fl_to):
            continue
        tid = vc.get("template_id")
        fp = vc.get("footprint")
        if isinstance(fp, dict) and all(k in fp for k in ("x0", "z0", "x1", "z1")):
            entry = {
                "x0": int(fp["x0"]), "z0": int(fp["z0"]),
                "x1": int(fp["x1"]), "z1": int(fp["z1"]),
                "kind": "stair",
            }
        elif building_aabb and len(building_aabb) == 6:
            entry = _synthesize_stair_footprint(building_aabb, tid, index=idx)
            entry["kind"] = "stair"
        else:
            # No building_aabb available — skip. Floor_planner will produce
            # no reservation; inter_floor_validator will raise.
            continue
        if tid:
            entry["template_id"] = tid
        out.append(entry)
    return out


def plan_floor(*,
                floor_index: int,
                global_intent: dict,
                space_plan: dict,
                model: str = MODEL_FLOOR,
                floor_below_rooms: list | None = None) -> dict:
    """Synchronous single-floor planner. Returns a validated floor_plan dict.

    Args:
        floor_index: which floor (0-based).
        global_intent: validated global_intent_v4 dict.
        space_plan: validated space_plan_v4 dict.
        model: LLM model name.
        floor_below_rooms: optional [{id, role, aabb}] of the reference floor
            (floor 0). When given, the prompt asks the LLM to align this
            floor's interior walls to those XZ boundaries so walls stack
            vertically instead of floating.

    On persistent schema/post-validation failure (after all retries with
    feedback) it RAISES RuntimeError. The deterministic BSP fallback has been
    removed so the floor layout is always the LLM's own (fair LLM comparison).

    Raises:
        IndexError if floor_index out of range for global_intent.floors.
        RuntimeError if the LLM cannot produce a valid floor after all retries.
    """
    floors = global_intent.get("floors") or []
    if floor_index < 0 or floor_index >= len(floors):
        raise IndexError(f"floor_index {floor_index} out of range [0, {len(floors)})")
    floor = floors[floor_index]

    layout_id = (space_plan.get("floor_layout_id_per_floor") or [])
    if floor_index >= len(layout_id):
        raise ValueError(f"space_plan has no floor_layout_id for floor {floor_index}")
    layout_id = layout_id[floor_index]
    full = _floor_layouts_full().get(layout_id)
    if full is None:
        # Layout id not in the catalogue (LLM picked a free-form name). Pass a
        # minimal context object and KEEP the LLM's layout_id — no deterministic
        # substitution to a catalogue default.
        import sys
        full = {"id": layout_id, "tags": {"category": "any", "style": []},
                "parameters": {}, "placement_rules": []}
        print(f"[floor_planner WARN] layout '{layout_id}' not in catalog — "
              f"passing minimal context, keeping the LLM's id for floor {floor_index}.",
              file=sys.stderr)

    hints = space_plan.get("room_role_hints_per_floor") or []
    role_hints = hints[floor_index] if floor_index < len(hints) else []
    entry_points = [e for e in (space_plan.get("entry_points") or [])
                     if int(e.get("floor", -1)) == floor_index]
    reserved = _reserved_footprints_for_floor(
        space_plan, floor_index,
        building_aabb=global_intent.get("building_aabb"))

    # Footprint mask of the silhouette — rooms must live inside it (round
    # tower, U-courtyard, cross, …). allowed_rects is the LLM's buildable
    # region; the deterministic fallback tiles the same regions.
    _sil_params = global_intent.get("silhouette_parameters") or {}
    fpmask = footprint_for(
        global_intent.get("silhouette_id"),
        global_intent.get("building_aabb") or [0, 0, 0, 1, 1, 1],
        floor_index=floor_index, n_floors=len(floors),
        footprint_shape=_sil_params.get("footprint_shape"), params=_sil_params)
    allowed_rects = [list(r) for r in fpmask.rects()]

    # Filter room_role briefs to the hints + minimum viable vocabulary.
    # Sending all 18 briefs wastes ~1200 tokens per call; the LLM only
    # picks from the hinted roles + fallbacks for circulation.
    _MIN_ROLES = {"hallway", "entry_hall", "kitchen", "bedroom"}
    needed_roles = set(role_hints or []) | _MIN_ROLES
    all_briefs = _room_role_briefs()
    role_briefs = [b for b in all_briefs if b["id"] in needed_roles]
    if not role_briefs:
        role_briefs = all_briefs  # safety net if filter empties it

    # 2026-05-30 RELAJADO: dropped "patterns" from context. floor_planner
    # only needs its geometric inputs (footprint, layout skill, role hints,
    # reserved stairs). Alexander patterns belong to the designer's brief,
    # not to per-floor partition picking.
    context = {
        "user_prompt":         global_intent.get("user_prompt", ""),
        "expanded_description": global_intent.get("expanded_description", ""),
        "requested":           global_intent.get("requested", {}),
        "floor_index":         floor_index,
        "floor":               floor,
        "building_aabb":       global_intent.get("building_aabb"),
        "style":               global_intent.get("style"),
        "category":            global_intent.get("category"),
        "silhouette_id":       global_intent.get("silhouette_id"),
        "floor_layout":        full,
        "room_role_hints":     role_hints,
        "reserved_footprints": reserved,
        "entry_points":        entry_points,
        "room_role_briefs":    role_briefs,
        # Buildable footprint of the silhouette: place every room INSIDE one
        # of these rectangles (the void around them is courtyard/outside).
        "footprint_shape":     fpmask.shape,
        "allowed_rects":       allowed_rects,
        # Reference partition (floor 0) for vertical wall alignment. Empty on
        # floor 0 itself.
        "floor_below_rooms":   floor_below_rooms or [],
    }
    system = (PROMPTS / "floor_v4.md").read_text(encoding="utf-8")
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)

    validator = _validator()
    last_err: str | None = None
    _MAX_ATTEMPTS = 8   # 1 initial + 7 retries with validation feedback. The
                         # deterministic BSP fallback has been REMOVED: to
                         # compare LLMs fairly the floor layout must be the
                         # LLM's, so on persistent failure we raise (no
                         # deterministic substitution).

    def _fail() -> "dict":
        # ABLATION: with HOMECRAFT_FALLBACK_MODE=on, fall back to the
        # deterministic BSP partition instead of raising (roles still come from
        # the space_planner's hints — only the GEOMETRY is deterministic).
        if fallback_enabled():
            return _fallback_partition(
                floor=floor, floor_index=floor_index, layout_id=layout_id,
                building_aabb=global_intent.get("building_aabb"),
                reserved=reserved, role_hints=role_hints,
                entry_points=entry_points, regions=fpmask.room_regions())
        raise RuntimeError(
            f"floor_planner: LLM failed to produce a valid floor {floor_index} "
            f"after {_MAX_ATTEMPTS} attempts (last error: {last_err}). "
            f"Deterministic fallback disabled.")

    for attempt in range(_MAX_ATTEMPTS):
        try:
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=4096, temperature=0.4)
        except Exception as e:
            last_err = str(e)
            if attempt < _MAX_ATTEMPTS - 1:
                continue
            return _fail()   # provider failure → fail loudly, no fallback

        _normalize(doc, floor_index=floor_index, layout_id=layout_id,
                    reserved=reserved)
        # Repair the model's room boxes into valid placement before validating,
        # so geometric mistakes (outside the footprint / height past the storey
        # band) self-correct instead of failing 8 retries -> abort.
        _repair_room_geometry(doc, floor=floor, floor_index=floor_index,
                              building_aabb=global_intent.get("building_aabb"))
        errs = list(validator.iter_errors(doc))
        if not errs:
            post_errs = _post_validate(doc, floor=floor, floor_index=floor_index,
                                        building_aabb=global_intent.get("building_aabb"),
                                        reserved=reserved,
                                        entry_points=entry_points,
                                        expected_layout_id=layout_id,
                                        footprint=fpmask)
            if not post_errs:
                return doc
            last_err = "post-validation: " + "; ".join(
                str(e) for e in post_errs[:3])
            if attempt < _MAX_ATTEMPTS - 1:
                feedback = (
                    f"\n\n[POST-VALIDATION ERROR — retry now (floor {floor_index})]\n"
                    + "\n".join(f"  - {e}" for e in post_errs[:6])
                    + "\nFix and return ONLY the corrected JSON.")
                user_payload = user_payload + feedback
                continue
            return _fail()   # persistent post-validation failure → raise
        first = errs[0]
        last_err = (f"{first.message[:300]} at "
                     f"/{'/'.join(str(p) for p in first.absolute_path)}")
        if attempt < _MAX_ATTEMPTS - 1:
            feedback = (
                f"\n\n[VALIDATION ERROR — retry now (floor {floor_index})]\n"
                f"Schema error: {last_err}\n"
                f"Fix and return ONLY the corrected JSON object.")
            user_payload = user_payload + feedback
            continue
        return _fail()   # persistent schema failure → raise
    return _fail()       # exhausted attempts → raise


def plan_floors_parallel(*,
                          global_intent: dict,
                          space_plan: dict,
                          max_workers: int | None = None,
                          model: str = MODEL_FLOOR) -> list[dict]:
    """Run N floor_planners in parallel and return the list of floor_plans
    in floor-index order (NOT in completion order).

    Args:
        global_intent: validated global_intent_v4.
        space_plan: validated space_plan_v4.
        max_workers: defaults to min(floor_count, 16). Pool=100 was tested
            empirically (commit b0087d5+1) and DEGRADED performance — the
            DeepSeek backend queues internally past ~16 concurrent calls,
            so anything above that is wasted scheduling. 16 leaves headroom
            for room_agent's own pool to share the provider concurrency.
        model: LLM model name passed through to each plan_floor call.

    Each floor self-heals via a deterministic fallback on persistent LLM
    failure, so this no longer fail-fasts on a single bad floor; it only
    raises on a truly unexpected error inside a worker.
    """
    n_floors = len(global_intent.get("floors") or [])
    if n_floors == 0:
        return []

    # Plan floor 0 FIRST; its partition is the vertical-alignment reference
    # for the upper floors so their interior walls stack on top of floor 0's
    # instead of floating. Upper floors then run in parallel among themselves.
    floor0 = plan_floor(floor_index=0, global_intent=global_intent,
                         space_plan=space_plan, model=model)
    if n_floors == 1:
        return [floor0]
    ref_rooms = [{"id": r.get("id"), "role": r.get("role"), "aabb": r.get("aabb")}
                 for r in (floor0.get("rooms") or [])]

    results: dict[int, dict] = {0: floor0}
    upper = list(range(1, n_floors))
    workers = max_workers if max_workers is not None else min(len(upper), 16)
    if workers <= 1:
        for i in upper:
            results[i] = plan_floor(floor_index=i, global_intent=global_intent,
                                     space_plan=space_plan, model=model,
                                     floor_below_rooms=ref_rooms)
        return [results[i] for i in range(n_floors)]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(plan_floor, floor_index=i,
                         global_intent=global_intent,
                         space_plan=space_plan, model=model,
                         floor_below_rooms=ref_rooms): i
            for i in upper
        }
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                # Fail fast — let pending workers finish, then raise.
                for other in futures:
                    other.cancel()
                raise RuntimeError(
                    f"floor_planner failed for floor {i}: {e}") from e
    return [results[i] for i in range(n_floors)]


# ────────────────────────────────────────────────────────────────────────
#  Helpers — normalization + post-validation
# ────────────────────────────────────────────────────────────────────────


def _normalize(doc: dict, *, floor_index: int, layout_id: str,
                reserved: list[dict]) -> None:
    """Pin schema_version + floor_index + layout_skill_id; pass reserved
    through verbatim; coerce ints."""
    doc.setdefault("schema_version", "v4")
    doc["schema_version"] = "v4"
    doc["floor_index"] = int(floor_index)
    doc["layout_skill_id_used"] = layout_id
    # Always pass reserved_footprints through; the prompt asks the LLM to
    # echo them but we enforce the contract here.
    if reserved:
        doc["reserved_footprints"] = [dict(r) for r in reserved]
    elif "reserved_footprints" not in doc:
        doc["reserved_footprints"] = []

    # Coerce ints
    for r in doc.get("rooms") or []:
        if "floor" in r:
            r["floor"] = int(r["floor"])
        if "aabb" in r and isinstance(r["aabb"], list):
            r["aabb"] = [int(v) for v in r["aabb"]]
    for r in doc.get("reserved_footprints") or []:
        for k in ("x0", "z0", "x1", "z1"):
            if k in r:
                r[k] = int(r[k])


def _repair_room_geometry(doc: dict, *, floor: dict, floor_index: int,
                          building_aabb: list[int] | None) -> int:
    """Coerce each room's AABB into the building box and floor y-band.

    Small backbones routinely emit rooms that sit outside the footprint or whose
    height exceeds the storey band (e.g. aabb.y1=22 on a 0..5 floor) — both are
    HARD post-validation rejections that abort the build after 8 retries. Rather
    than reject, we REPAIR the model's own layout: translate each box back inside
    the building footprint (preserving its size where it fits) and clamp its y
    range to [floor.y0, floor.y1]. This keeps the model's room count, roles and
    relative placement while guaranteeing the geometry contract, so the floor
    plan validates without falling back to the deterministic BSP partition.
    Returns the number of rooms it had to move/clamp. Logs each repair.
    """
    import sys
    if not (building_aabb and len(building_aabb) == 6):
        return 0
    bx0, _, bz0, bx1, _, bz1 = (int(v) for v in building_aabb)
    fy0 = int(floor.get("y0", 0))
    fy1 = int(floor.get("y1", fy0 + 4))
    min_xz = 3                       # keep at least a 3-cell footprint
    n_repaired = 0

    def _fit(lo, hi, blo, bhi):
        """Translate [lo,hi] inside [blo,bhi]; clamp if larger than the bound."""
        size = max(min_xz, hi - lo)
        size = min(size, bhi - blo) if (bhi - blo) >= min_xz else (bhi - blo)
        lo = max(blo, min(lo, bhi - size))
        return lo, lo + size

    for r in (doc.get("rooms") or []):
        a = r.get("aabb")
        if not (isinstance(a, list) and len(a) == 6):
            continue
        x0, y0, z0, x1, y1, z1 = (int(v) for v in a)
        nx0, nx1 = _fit(min(x0, x1), max(x0, x1), bx0, bx1)
        nz0, nz1 = _fit(min(z0, z1), max(z0, z1), bz0, bz1)
        ny0 = fy0
        ny1 = max(fy0 + 1, min(max(y0, y1), fy1))
        new = [nx0, ny0, nz0, nx1, ny1, nz1]
        if new != [x0, y0, z0, x1, y1, z1]:
            r["aabb"] = new
            n_repaired += 1
    if n_repaired:
        print(f"[floor_planner] repaired geometry of {n_repaired} room(s) on "
              f"floor {floor_index} (clamped into building box + y-band).",
              file=sys.stderr)
    return n_repaired


def _aabb_xz_overlap_vol(a_aabb: list[int], r_rect: dict) -> int:
    """Overlap area in XZ between a room AABB [x0,y0,z0,x1,y1,z1] and a
    reserved_footprint {x0,z0,x1,z1}."""
    dx = max(0, min(a_aabb[3], r_rect["x1"]) - max(a_aabb[0], r_rect["x0"]))
    dz = max(0, min(a_aabb[5], r_rect["z1"]) - max(a_aabb[2], r_rect["z0"]))
    return dx * dz


def _aabb_vol_overlap(a: list[int], b: list[int]) -> int:
    dx = max(0, min(a[3], b[3]) - max(a[0], b[0]))
    dy = max(0, min(a[4], b[4]) - max(a[1], b[1]))
    dz = max(0, min(a[5], b[5]) - max(a[2], b[2]))
    return dx * dy * dz


def _fallback_partition(*, floor: dict, floor_index: int, layout_id: str,
                        building_aabb: list[int] | None,
                        reserved: list[dict], role_hints: list[str],
                        entry_points: list[dict],
                        regions: list | None = None) -> dict:
    """Deterministic recursive (BSP) partition of the floor footprint into
    rooms that always satisfy the min-size + shared-wall contract.

    LAST RESORT only — used (ONLY when HOMECRAFT_FALLBACK_MODE=on) when the LLM
    cannot produce a valid floor plan after all retries, so a single ungenerable
    floor never kills the whole build. Roles still come from the space_planner's
    `room_hints` (variety is preserved); only the GEOMETRY is made deterministic.
    This path logs a warning so it is never silent.
    """
    import sys
    bx0, _, bz0, bx1, _, bz1 = (building_aabb or [0, 0, 0, 8, 1, 8])
    y0 = int(floor.get("y0", 0))
    y1 = int(floor.get("y1", y0 + 4))
    min_xz = _ROOM_MIN_XZ + 1   # 5 -> interior 3 after walls

    # Tile WITHIN the footprint mask's regions (wings/arms, or the inscribed
    # rectangle for round shapes) so fallback rooms respect the building shape
    # instead of filling a box that the void air-fill would then carve.
    rects: list[tuple] = ([tuple(r) for r in regions] if regions
                          else [(bx0, bz0, bx1, bz1)])
    target = max(len(rects), min(len(role_hints) or 3, 8))

    def _splittable(r):
        return (r[2] - r[0]) >= 2 * min_xz or (r[3] - r[1]) >= 2 * min_xz

    while len(rects) < target and any(_splittable(r) for r in rects):
        rects.sort(key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True)
        for i, (x0, z0, x1, z1) in enumerate(rects):
            if (x1 - x0) >= (z1 - z0) and (x1 - x0) >= 2 * min_xz:
                mid = (x0 + x1) // 2
                rects[i] = (x0, z0, mid, z1)
                rects.append((mid, z0, x1, z1))
                break
            if (z1 - z0) >= 2 * min_xz:
                mid = (z0 + z1) // 2
                rects[i] = (x0, z0, x1, mid)
                rects.append((x0, mid, x1, z1))
                break
        else:
            break

    roles = role_hints or ["hallway"]
    rooms: list[dict] = []
    role_counts: dict[str, int] = {}
    for i, (x0, z0, x1, z1) in enumerate(rects):
        role = roles[i % len(roles)]
        role_counts[role] = role_counts.get(role, 0) + 1
        rooms.append({
            "id": f"{role.replace('_', '-')}-{role_counts[role]}",
            "role": role, "floor": floor_index,
            "aabb": [x0, y0, z0, x1, y1, z1],
        })

    # Pick the entry room: the one touching the declared entry side.
    side = (entry_points[0].get("side") if entry_points else None)
    def _touches(room):
        a = room["aabb"]
        return {"-z": a[2] == bz0, "+z": a[5] == bz1,
                "-x": a[0] == bx0, "+x": a[3] == bx1}.get(side, True)
    entry_room = next((r for r in rooms if _touches(r)), rooms[0] if rooms else None)

    adj: list[dict] = []
    if entry_points and entry_room is not None:
        adj.append({"from_room": "outside", "to_room": entry_room["id"],
                    "kind": "door"})
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            if _shares_full_wall_xz(rooms[i]["aabb"], rooms[j]["aabb"]):
                adj.append({"from_room": rooms[i]["id"],
                            "to_room": rooms[j]["id"], "kind": "opening"})

    print(f"[floor_planner] floor {floor_index}: LLM failed validation — "
          f"using deterministic BSP fallback ({len(rooms)} rooms)",
          file=sys.stderr)
    return {
        "schema_version": "v4", "floor_index": floor_index,
        "layout_skill_id_used": layout_id, "rooms": rooms,
        "adjacency_graph": adj,
        "reserved_footprints": [dict(r) for r in (reserved or [])],
    }


def _shares_full_wall_xz(a: list[int], b: list[int], min_overlap: int = 2) -> bool:
    """True iff AABBs `a` and `b` are face-adjacent in XZ with >= min_overlap
    cells of overlap on the shared wall — the geometric precondition for a
    door/opening between them (matches connector_planner's wall test)."""
    ax0, _, az0, ax1, _, az1 = a
    bx0, _, bz0, bx1, _, bz1 = b
    if ax1 == bx0 or bx1 == ax0:        # touch on the X face → overlap along Z
        return (min(az1, bz1) - max(az0, bz0)) >= min_overlap
    if az1 == bz0 or bz1 == az0:        # touch on the Z face → overlap along X
        return (min(ax1, bx1) - max(ax0, bx0)) >= min_overlap
    return False


# Minimum room dimensions (outer AABB, walls included). A 1-thick wall leaves
# (dim - 2) of interior; below these a room is uninhabitable. Genuinely cramped
# roles (corridors, attics, basements, pantries) may be one cell narrower —
# they are walked through or crawl spaces, not lived in, and a top-floor attic
# is often geometrically forced small (don't fail the whole build over it).
_ROOM_MIN_XZ = 4
_CRAMPED_MIN_XZ = 3
_CRAMPED_ROLES = {"hallway", "attic", "basement", "pantry"}

_PUBLIC_ROLES = {"living_room", "dining_room", "great_hall", "courtyard_indoor",
                  "chapel", "throne_room"}
_PRIVATE_ROLES = {"bedroom", "bathroom", "nursery"}


def _post_validate(doc: dict, *,
                    floor: dict,
                    floor_index: int,
                    building_aabb: list[int] | None,
                    reserved: list[dict],
                    entry_points: list[dict],
                    expected_layout_id: str,
                    footprint=None) -> list[str]:
    """Post-validation for one floor_plan — per C.4.1 nine rules."""
    errs: list[str] = []
    # Footprint mask: a room placed ENTIRELY in the void (courtyard / outside
    # a round tower) is misplaced — reject so the LLM moves it inside the
    # shape. Partial overlap is fine (the architecture void air-fill trims the
    # overhang). Only applies for non-rectangular footprints.
    if footprint is not None and getattr(footprint, "shape", "rectangle") != "rectangle":
        fp_cells = footprint.cells
        for r in (doc.get("rooms") or []):
            a = r.get("aabb")
            if not (isinstance(a, list) and len(a) == 6):
                continue
            inside = sum(1 for x in range(a[0], a[3]) for z in range(a[2], a[5])
                         if (x, z) in fp_cells)
            total = max(1, (a[3] - a[0]) * (a[5] - a[2]))
            if inside == 0:
                # SOFT (was hard reject): complex footprints (cross/U) are hard
                # for the LLM to tile. Accept — the architecture void-fill carves
                # away whatever sits in the courtyard/void — so the build still
                # completes. The LLM still gets footprint_shape + allowed_rects
                # as guidance. (feedback, not block.)
                import sys
                print(f"[floor_planner WARN] room {r.get('id')} sits outside the "
                      f"{footprint.shape} footprint — accepted (void-fill trims it).",
                      file=sys.stderr)

    # R1 layout_skill_id_used — soft warn (was hard error).
    # The floor_planner may legitimately diverge to a different layout when
    # the space_planner's pick does not fit this floor's footprint or role
    # (e.g. a single-room top of a tower). Warn but accept the chosen layout.
    if doc.get("layout_skill_id_used") != expected_layout_id:
        import sys
        print(f"[floor_planner WARN] floor {floor_index} used layout "
              f"'{doc.get('layout_skill_id_used')}' (space_planner suggested "
              f"'{expected_layout_id}') — accepting divergence.",
              file=sys.stderr)
    # R2 floor_index match
    if int(doc.get("floor_index", -1)) != floor_index:
        errs.append(
            f"floor_index={doc.get('floor_index')} must equal "
            f"input floor_index={floor_index}")

    rooms = doc.get("rooms") or []
    room_ids: set[str] = set()
    fy0 = int(floor.get("y0", 0))
    fy1 = int(floor.get("y1", 0))

    for r in rooms:
        rid = r.get("id")
        if rid in room_ids:
            errs.append(f"duplicate room id: {rid}")
        room_ids.add(rid)
        if int(r.get("floor", -1)) != floor_index:
            errs.append(
                f"room {rid}: rooms[].floor={r.get('floor')} != "
                f"floor_index={floor_index}")
        aabb = r.get("aabb") or []
        if len(aabb) != 6:
            errs.append(f"room {rid}: aabb has {len(aabb)} elements; need 6")
            continue
        # Minimum habitable size: reject degenerate rooms whose 1-thick walls
        # leave a 0- or 1-cell interior (the chronic defect — 3-wide bedrooms,
        # 2-deep "rooms"). Hallways may be one cell narrower.
        role = r.get("role", "")
        dx, dz = aabb[3] - aabb[0], aabb[5] - aabb[2]
        floor_min = (_CRAMPED_MIN_XZ if role in _CRAMPED_ROLES
                     else _ROOM_MIN_XZ)
        if min(dx, dz) < floor_min:
            # SOFT (was hard reject): a cramped room is a quality issue, not a
            # build-breaker. Accept it (the metrics will reflect the small
            # interior) instead of rejecting the whole plan — validators give
            # feedback, they don't block.
            import sys
            print(f"[floor_planner WARN] room {rid} ({role}): XZ {dx}x{dz} is "
                  f"small (interior {max(0, dx - 2)}x{max(0, dz - 2)}) — accepted.",
                  file=sys.stderr)
        if int(aabb[1]) != fy0:
            errs.append(
                f"room {rid}: aabb.y0={aabb[1]} != floors[{floor_index}].y0={fy0}")
        if int(aabb[4]) > fy1:
            errs.append(
                f"room {rid}: aabb.y1={aabb[4]} > floors[{floor_index}].y1={fy1}")
        if building_aabb and len(building_aabb) == 6:
            bx0, by0, bz0, bx1, by1, bz1 = building_aabb
            # How much of the room lies inside the building box?
            ix = max(0, min(aabb[3], bx1) - max(aabb[0], bx0))
            iz = max(0, min(aabb[5], bz1) - max(aabb[2], bz0))
            inside_area = ix * iz
            room_area = max(1, (aabb[3] - aabb[0]) * (aabb[5] - aabb[2]))
            frac_inside = inside_area / room_area
            if inside_area == 0:
                # Entirely outside → genuinely misplaced, reject with feedback.
                errs.append(
                    f"room {rid}: aabb is entirely outside building_aabb — "
                    f"place it inside [{bx0}..{bx1}]x[{bz0}..{bz1}].")
            elif frac_inside < 0.5:
                errs.append(
                    f"room {rid}: aabb is mostly ({(1-frac_inside)*100:.0f}%) "
                    f"outside building_aabb — move it inside.")
            elif frac_inside < 0.999:
                # Slight overhang: SOFT — the architecture void-fill trims it.
                import sys
                print(f"[floor_planner WARN] room {rid}: pokes "
                      f"{(1-frac_inside)*100:.0f}% outside building_aabb — "
                      f"accepted (overhang trimmed).", file=sys.stderr)
        for rsv in reserved or []:
            if _aabb_xz_overlap_vol(aabb, rsv) > 0:
                # Soft-warn only: the architecture_planner emits stair_void
                # air on upper floor slabs, and the composer's later-wins
                # erases room walls inside the shaft. Visually clean even
                # if the room AABB nominally contains the reservation.
                import sys
                print(f"[floor_planner WARN] room {rid}: aabb XZ overlaps "
                       f"reserved_footprint {rsv} (kind={rsv.get('kind')}) "
                       f"— composer later-wins will resolve",
                       file=sys.stderr)
                break

    # Same-floor pairwise overlap — warning only. The architecture_planner
    # emits one fill_hollow per room; composer later-wins handles voxel
    # collisions (later room's walls overwrite earlier room's at the seam).
    import sys
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            a = rooms[i].get("aabb") or []
            b = rooms[j].get("aabb") or []
            if len(a) == 6 and len(b) == 6 and _aabb_vol_overlap(a, b) > 0:
                print(f"[floor_planner WARN] rooms {rooms[i]['id']!r} and "
                       f"{rooms[j]['id']!r} overlap in volume "
                       f"— composer later-wins will resolve",
                       file=sys.stderr)

    # Adjacency graph
    import sys
    edges = doc.get("adjacency_graph") or []
    drop_edges: list = []   # edges to silently drop (impossible geometry)
    for e in edges:
        fr, to = e.get("from_room"), e.get("to_room")
        for v in (fr, to):
            if v != "outside" and v not in room_ids:
                errs.append(f"adjacency_graph references unknown room: {v}")
        # Geometric shared-wall check: a door/opening needs the two rooms to
        # actually touch on a full wall. If they don't, DROP the edge (the
        # design intent — "the connection will be dropped") instead of
        # rejecting the whole plan. validators give feedback, not blocks.
        if (e.get("kind") in ("door", "opening")
                and fr != "outside" and to != "outside"):
            a = next((r.get("aabb") for r in rooms if r.get("id") == fr), None)
            b = next((r.get("aabb") for r in rooms if r.get("id") == to), None)
            if (isinstance(a, list) and len(a) == 6
                    and isinstance(b, list) and len(b) == 6
                    and not _shares_full_wall_xz(a, b)):
                print(f"[floor_planner WARN] adjacency {fr}<->{to} "
                      f"({e.get('kind')}): rooms don't share a full wall — "
                      f"dropping the edge.", file=sys.stderr)
                drop_edges.append(e)
                continue
    # Apply drops, then recompute referenced/has_outside on surviving edges.
    if drop_edges:
        doc["adjacency_graph"] = [e for e in edges if e not in drop_edges]
        edges = doc["adjacency_graph"]
    referenced = set()
    has_outside = False
    for e in edges:
        fr, to = e.get("from_room"), e.get("to_room")
        referenced.add(fr); referenced.add(to)
        if fr == "outside" or to == "outside":
            has_outside = True
        # Intimacy gradient — Alexander #127 guidance, SOFT warning only.
        fr_role = next((r["role"] for r in rooms if r["id"] == fr), None)
        to_role = next((r["role"] for r in rooms if r["id"] == to), None)
        if (e.get("kind") in ("door", "opening")
            and (fr_role in _PRIVATE_ROLES and to_role in _PUBLIC_ROLES
                  or to_role in _PRIVATE_ROLES and fr_role in _PUBLIC_ROLES)):
            print(f"[floor_planner WARN] intimacy gradient: edge {fr}↔{to} "
                   f"connects {fr_role}/{to_role} directly (Alexander #127)",
                   file=sys.stderr)

    # Orphan rooms — SOFT (was hard reject). An orphan just won't get a planned
    # door (lower connectivity metric); it does not break the build.
    for rid in room_ids:
        if rid not in referenced:
            print(f"[floor_planner WARN] room {rid!r} has no adjacency edge "
                  f"(orphan) — accepted; it may be unreachable.", file=sys.stderr)

    # Entry points present but no outside edge — SOFT. The inter_floor_validator
    # (C2) auto-synthesizes an 'outside' edge to a room touching the entry side,
    # so this is recoverable downstream; warn instead of rejecting.
    if entry_points and not has_outside:
        print(f"[floor_planner WARN] floor {floor_index}: {len(entry_points)} "
              f"entry_point(s) but no 'outside' edge — inter_floor_validator "
              f"will synthesize one.", file=sys.stderr)
    if not entry_points and has_outside:
        # Soft: drop the stray outside edges in-place. Upper floors with
        # spurious outside edges materialize as floating exterior doors,
        # which is worse than no door. The inter_floor_validator's
        # auto-synthesize path won't reactivate it since entry_points is
        # empty for this floor.
        import sys
        before = len(doc.get("adjacency_graph") or [])
        doc["adjacency_graph"] = [
            e for e in (doc.get("adjacency_graph") or [])
            if e.get("from_room") != "outside" and e.get("to_room") != "outside"
        ]
        after = len(doc["adjacency_graph"])
        if before != after:
            print(f"[floor_planner WARN] floor {floor_index} had "
                   f"{before - after} 'outside' edge(s) but space_plan has "
                   f"no entry_point on this floor — dropped",
                   file=sys.stderr)

    return errs


__all__ = [
    "plan_floor",
    "plan_floors_parallel",
    "_reserved_footprints_for_floor",
    "_reset_v4_caches",
]
