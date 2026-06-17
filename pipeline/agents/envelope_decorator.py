"""Envelope decorator — Stage 1g of v4 (NEW, LLM-driven).

Per gym constraint (2026-05-28): LLMs must drive variety, no silent
fallbacks. This stage materializes voxel ops that the deterministic
stages miss — specifically targeting the four evaluator metrics that
chronically score below 0.3 in iter01-04:

  - sheltering_roof   (mean 0.20)
  - building_edge     (mean 0.00)
  - light_on_two_sides (mean 0.18)
  - light_coverage    (mean 0.46)

The LLM consumes the building envelope + style + room AABBs + door
coords and emits a list of shape_ops layered on top of architecture_
plan_v4.ops. Validated against pipeline/agents/prompts/expanded_prompt
shape (reuse room_plan schema).

NO FALLBACK — on persistent LLM failure, raises.
"""
from __future__ import annotations

import json

from .llm import call_llm_json, MODEL_WORKER
from .main_agent import PROMPTS
from .schema_utils import make_validator


def _validator():
    return make_validator("room_plan.schema.json")


def decorate_envelope(*,
                       global_intent: dict,
                       rooms: list[dict],
                       connector_plan: dict,
                       model: str = MODEL_WORKER,
                       max_attempts: int = 4) -> dict:
    """Emit envelope decoration ops via LLM.

    Args:
      global_intent: v4 global_intent dict (style, building_aabb, site_aabb).
      rooms: aggregated rooms list from floor_plans.
      connector_plan: validated v3-shape connector_plan with doors[].

    Returns: dict with shape compatible with room_plan.schema.json:
      {schema_version, room_id="exterior", role="exterior", style, ops[]}
    """
    style = global_intent.get("style", "medieval")
    site_aabb = global_intent.get("site_aabb")
    building_aabb = global_intent.get("building_aabb")
    silhouette_id = global_intent.get("silhouette_id")
    height_intent = global_intent.get("height_intent") or {}

    # Compact room AABBs + centroids for the LLM
    room_briefs = []
    for r in rooms:
        a = r.get("aabb") or []
        if len(a) != 6:
            continue
        room_briefs.append({
            "id": r.get("id"),
            "role": r.get("role"),
            "aabb": list(a),
            "centroid": [(a[0] + a[3]) // 2, (a[1] + a[4]) // 2,
                          (a[2] + a[5]) // 2],
            "y1": a[4],
        })

    # Door coords (so the LLM can skip those wall cells for windows)
    door_coords = []
    for d in (connector_plan.get("doors") or []):
        v = d.get("validated") or {}
        at = v.get("at")
        if at and len(at) == 3:
            door_coords.append(list(at))

    context = {
        "style":          style,
        "silhouette_id":  silhouette_id,
        "site_aabb":      site_aabb,
        "building_aabb":  building_aabb,
        "height_intent":  height_intent,
        "rooms":          room_briefs,
        "door_coords":    door_coords,
    }
    system = (PROMPTS / "envelope_v4.md").read_text(encoding="utf-8")
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)

    validator = _validator()
    last_err = None
    for attempt in range(max_attempts):
        try:
            doc = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=4096, temperature=0.6)
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                continue
            raise RuntimeError(
                f"envelope_decorator LLM failed after {max_attempts} "
                f"attempts: {e}") from e

        # Force required fields the schema needs. room_plan.schema.json
        # requires {room_id, role, aabb, style, ops}, no schema_version.
        doc["room_id"] = "exterior"
        doc["role"] = "exterior"
        doc["aabb"] = list(building_aabb) if building_aabb else [0, 0, 0, 1, 1, 1]
        if not isinstance(doc.get("style"), str):
            doc["style"] = style
        doc.pop("schema_version", None)

        # Strip null optional fields + filter malformed ops. The LLM
        # sometimes emits place-with-aabb or fill-without-aabb — coerce
        # to the schema's expected shape. Ops still unrecoverable are
        # DROPPED (not replaced — gym constraint: no deterministic
        # substitutes for LLM decisions).
        clean_ops = []
        for op in doc.get("ops", []) or []:
            if not isinstance(op, dict):
                continue
            for k in list(op.keys()):
                if op[k] is None and k in ("fill", "floor", "ceiling", "level",
                                              "hollow", "style", "kwargs"):
                    del op[k]
            kind = op.get("kind")
            # Coerce common LLM mistakes
            if kind == "place":
                # Place needs `at`. If LLM gave aabb, take its origin.
                if "at" not in op and "aabb" in op:
                    aabb = op["aabb"]
                    if isinstance(aabb, list) and len(aabb) >= 3:
                        op["at"] = list(aabb[:3])
                if "at" not in op or "block" not in op:
                    continue   # drop unrecoverable
            elif kind in ("fill", "fill_hollow", "outline", "rect"):
                # These need aabb. If LLM gave at, expand to a 1×1×1 aabb.
                if "aabb" not in op and "at" in op:
                    at = op["at"]
                    if isinstance(at, list) and len(at) == 3:
                        op["aabb"] = [at[0], at[1], at[2],
                                       at[0] + 1, at[1] + 1, at[2] + 1]
                if "aabb" not in op or "block" not in op:
                    continue
            elif kind == "line":
                if "from" not in op or "to" not in op or "block" not in op:
                    continue
            else:
                continue   # unknown kind
            clean_ops.append(op)
        doc["ops"] = clean_ops

        errs = list(validator.iter_errors(doc))
        if not errs:
            return doc

        last_err = errs[0]
        if attempt < max_attempts - 1:
            user_payload += (
                f"\n\n[VALIDATION ERROR — retry now]\n"
                f"Your previous output failed schema validation:\n"
                f"  {last_err.message[:300]}\n"
                f"Return ONLY the corrected JSON.")
            continue
        raise ValueError(
            f"envelope_decorator output invalid after {max_attempts} "
            f"attempts: {last_err.message[:300]}")
    raise RuntimeError("envelope_decorator unreachable")
