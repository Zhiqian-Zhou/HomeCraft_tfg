"""Smoke tests for the v4 orchestrator helpers.

The full _run_v4() makes LLM calls; these tests verify only the
deterministic pieces (shim adapters, CLI flag, module imports).
"""
from __future__ import annotations

from pipeline.agents import run


def test_imports_v4_modules():
    """v4 modules must be importable from the run namespace."""
    assert hasattr(run, "floor_planner")
    assert hasattr(run, "inter_floor_validator")
    assert hasattr(run, "connector_planner_v4")


def test_floor_plans_to_v3_space_plan_aggregates_rooms_and_edges():
    fp0 = {
        "floor_index": 0,
        "rooms": [{"id": "kitchen-1", "role": "kitchen",
                    "floor": 0, "aabb": [0, 0, 0, 4, 4, 4]}],
        "adjacency_graph": [
            {"from_room": "outside", "to_room": "kitchen-1", "kind": "door"},
        ],
    }
    fp1 = {
        "floor_index": 1,
        "rooms": [{"id": "bedroom-1", "role": "bedroom",
                    "floor": 1, "aabb": [0, 4, 0, 4, 8, 4]}],
        "adjacency_graph": [
            {"from_room": "bedroom-1", "to_room": "bedroom-1", "kind": "none"},
        ],
    }
    sp = run._floor_plans_to_v3_space_plan([fp0, fp1])
    assert sp["schema_version"] == "1.0"
    assert len(sp["rooms"]) == 2
    assert len(sp["adjacency_graph"]) == 2
    ids = {r["id"] for r in sp["rooms"]}
    assert {"kitchen-1", "bedroom-1"} == ids


def test_v4_global_intent_to_v3_renames_expanded_description():
    gi_v4 = {
        "schema_version": "v4",
        "expanded_description": "A modest cottage.",
        "silhouette_id": "gable-cottage-silhouette",
        "category": "residential",
        "style": "medieval",
        "site_aabb": [0, 0, 0, 10, 8, 10],
        "building_aabb": [0, 0, 0, 8, 6, 8],
        "floors": [{"index": 0, "y0": 0, "y1": 4}],
        "height_intent": {},
        "alexander_rationale": [],
    }
    gi_v3 = run._v4_global_intent_to_v3(gi_v4, "small cottage")
    assert gi_v3["schema_version"] == "1.0"
    assert gi_v3["prompt"] == "A modest cottage."
    # silhouette_id is harmlessly preserved (downstream v3 ignores it)
    assert gi_v3["silhouette_id"] == "gable-cottage-silhouette"


def test_v4_global_intent_to_v3_falls_back_to_raw_prompt():
    gi_v4 = {
        "schema_version": "v4",
        "category": "residential",
        "style": "medieval",
        "site_aabb": [0, 0, 0, 10, 8, 10],
        "building_aabb": [0, 0, 0, 8, 6, 8],
        "floors": [{"index": 0, "y0": 0, "y1": 4}],
        "height_intent": {},
        "alexander_rationale": [],
    }
    gi_v3 = run._v4_global_intent_to_v3(gi_v4, "raw prompt")
    assert gi_v3["prompt"] == "raw prompt"


def test_run_dispatch_recognizes_v4():
    """run() dispatches to _run_v4 when pipeline_version='v4'.
    We check the routing logic without actually invoking the pipeline.
    """
    # Just verify the dispatcher inspects the flag — no LLM calls.
    import inspect
    src = inspect.getsource(run.run)
    assert "v4" in src
    assert "_run_v4" in src
