"""JSON Schema helpers shared across pipeline agents.

The pipeline schemas reference each other via `$ref` URLs like
`https://homecraft.tfg/schemas/shape_op.schema.json`. These URLs don't resolve
over the network — they're stable identifiers for our local copies. This
module exposes a `make_validator()` that builds a `Draft202012Validator`
with the needed sibling schemas already registered.
"""
from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCHEMA_DIR = REPO_ROOT / "rag" / "schema"

# Map $id URL → local file (relative to SCHEMA_DIR)
_SCHEMA_IDS = {
    "https://homecraft.tfg/schemas/shape_op.schema.json":         "shape_op.schema.json",
    "https://homecraft.tfg/schemas/room_plan.schema.json":        "room_plan.schema.json",
    "https://homecraft.tfg/schemas/master_plan.schema.json":      "master_plan.schema.json",
    "https://homecraft.tfg/schemas/design_intent.schema.json":    "design_intent.schema.json",
    "https://homecraft.tfg/schemas/expanded_prompt.schema.json":  "expanded_prompt.schema.json",
    "https://homecraft.tfg/schemas/expanded_prompt_v4.schema.json": "expanded_prompt_v4.schema.json",
    "https://homecraft.tfg/schemas/global_intent_v4.schema.json":  "global_intent_v4.schema.json",
    "https://homecraft.tfg/schemas/space_plan_v4.schema.json":     "space_plan_v4.schema.json",
    "https://homecraft.tfg/schemas/floor_plan.schema.json":        "floor_plan.schema.json",
    "https://homecraft.tfg/schemas/architecture_plan_v4.schema.json": "architecture_plan_v4.schema.json",
    "https://homecraft.tfg/schemas/evaluation_report.schema.json": "evaluation_report.schema.json",
}


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


_REGISTRY: Registry | None = None


def _registry() -> Registry:
    global _REGISTRY
    if _REGISTRY is not None:
        return _REGISTRY
    pairs = []
    for uri, filename in _SCHEMA_IDS.items():
        path = SCHEMA_DIR / filename
        if not path.exists():
            continue
        schema = json.loads(path.read_text(encoding="utf-8"))
        pairs.append((uri, DRAFT202012.create_resource(schema)))
    _REGISTRY = Registry().with_resources(pairs)
    return _REGISTRY


def make_validator(schema_filename: str) -> Draft202012Validator:
    """Build a validator for `rag/schema/<filename>` with cross-refs resolved.

    Example: `make_validator("master_plan.schema.json")`.
    """
    schema = _load_schema(schema_filename)
    return Draft202012Validator(schema, registry=_registry())
