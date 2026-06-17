"""Connector planner — Stage 1d of Pipeline v3.

Third LLM call. Receives global_intent + space_plan (with adjacency_graph
already declaring which rooms must be connected) and proposes connectors
(doors, windows, staircases). The deterministic connector_validator runs
AFTER the LLM and repairs all geometric mistakes (y=0 clamp, snap-to-wall,
auto-facing, carve openings, etc.).

This is the CRITIC pattern (Gou et al. 2023): LLM proposes topology,
deterministic post-validator imposes geometry. The LLM owns "which
rooms connect", the validator owns "where exactly does the door sit".

Returns a fully-validated connector_plan matching the schema, including
audit trail per connector.
"""
from __future__ import annotations

import json

from .connector_validator import validate_connectors
from .llm import call_llm_json, MODEL_MAIN
from .main_agent import PROMPTS
from .schema_utils import make_validator


def _validator():
    return make_validator("connector_plan.schema.json")


def plan_connectors(global_intent: dict, space_plan: dict, *,
                     model: str = MODEL_MAIN) -> dict:
    """Produce a connector_plan from validated global_intent + space_plan.

    Two-phase:
      1. LLM proposes raw doors/windows/staircases (best-effort coords).
      2. Deterministic validator repairs geometry + emits carve_ops.

    Returns: dict matching connector_plan.schema.json.
    """
    context = {
        "global_intent": global_intent,
        "space_plan": space_plan,
    }
    system = (PROMPTS / "connector.md").read_text(encoding="utf-8")
    user_payload = json.dumps(context, ensure_ascii=False, indent=2)

    # Phase 1: LLM proposes (temperature low — geometry is deterministic-ish)
    proposals = None
    last_err = None
    for attempt in range(2):
        try:
            raw = call_llm_json(system=system, user=user_payload, model=model,
                                max_tokens=6144, temperature=0.2)
        except Exception as e:
            if attempt == 0:
                last_err = e
                continue
            raise RuntimeError(f"connector_planner LLM call failed: {e}") from e
        if isinstance(raw, dict) and "doors" in raw:
            proposals = raw
            break
        if attempt == 0:
            user_payload = user_payload + (
                "\n\n[FORMAT ERROR — retry now]\n"
                "Output MUST have 'doors', 'windows', 'staircases' arrays "
                "(any of them may be empty). Return ONLY the JSON object.")
            continue
        proposals = {"doors": [], "windows": [], "staircases": []}

    if proposals is None:
        proposals = {"doors": [], "windows": [], "staircases": []}

    # Phase 2: deterministic validation + repair
    plan = validate_connectors(proposals, space_plan, global_intent)

    # Sanity: ensure schema validity
    validator = _validator()
    errs = list(validator.iter_errors(plan))
    if errs:
        # The validator output should always be schema-valid by construction.
        # If not, something is structurally wrong — surface immediately.
        raise RuntimeError(
            f"connector_planner output failed schema validation: "
            f"{errs[0].message[:300]} at "
            f"/{'/'.join(str(p) for p in errs[0].absolute_path)}")
    return plan
