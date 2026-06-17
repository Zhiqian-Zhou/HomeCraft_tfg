"""Unit tests for `pipeline.agents.typology_injector` (Fases 4.5 + extended).

Verifies that the injector correctly translates `gi.selected_typologies`
into `kind="typology"` ops appended to the architecture plan for all 4
kinds (roof, tower, window, garden), and that it degrades gracefully
when inputs are missing.
"""
from __future__ import annotations

from pipeline.agents.typology_injector import (
    inject,
    _roof_bbox_from_ops,
    _pick_window_slot_aabb,
    _garden_aabb_from_site,
    _is_tower_silhouette,
)


# ────────────────────────────────────────────────────────────────────────
#  Fixtures
# ────────────────────────────────────────────────────────────────────────

def _mock_architecture_plan() -> dict:
    """Minimal v4 architecture plan with a couple of roof rectangle ops."""
    return {
        "schema_version": "1.0",
        "style_palette": {},
        "materials_usage": {},
        "ops": [
            {"kind": "fill_hollow", "envelope_role": "wall",
             "aabb": [0, 0, 0, 12, 5, 10], "room_id": None,
             "wall": "@primary"},
            {"kind": "rect", "envelope_role": "roof",
             "aabb": [0, 5, 0, 12, 6, 10], "axis": "y", "level": 5,
             "room_id": None, "block": "@roof"},
            {"kind": "rect", "envelope_role": "roof",
             "aabb": [2, 5, 2, 10, 6, 8], "axis": "y", "level": 6,
             "room_id": None, "block": "@roof"},
        ],
    }


def _mock_connector_plan() -> dict:
    """Minimal connector_plan with 2 validated windows on different walls."""
    return {
        "schema_version": "1.0",
        "doors": [],
        "windows": [
            {"id": "w0", "validated": {
                "in_room": "living_room", "wall": "s",
                "aabb": [4, 2, 0, 6, 4, 1]}},
            {"id": "w1", "validated": {
                "in_room": "bedroom", "wall": "n",
                "aabb": [4, 2, 9, 6, 4, 10]}},
        ],
        "staircases": [],
        "dropped": [],
    }


# ────────────────────────────────────────────────────────────────────────
#  Helper unit tests
# ────────────────────────────────────────────────────────────────────────

def test_roof_bbox_unions_all_roof_ops():
    ops = _mock_architecture_plan()["ops"]
    bb = _roof_bbox_from_ops(ops)
    assert bb == (0, 5, 0, 12, 6, 10)


def test_roof_bbox_returns_None_with_no_roofs():
    bb = _roof_bbox_from_ops([
        {"kind": "fill", "envelope_role": "wall",
         "aabb": [0, 0, 0, 5, 5, 5], "block": "@primary"},
    ])
    assert bb is None


def test_pick_window_slot_returns_first_validated_aabb():
    cp = _mock_connector_plan()
    assert _pick_window_slot_aabb(cp) == [4, 2, 0, 6, 4, 1]


def test_pick_window_slot_handles_empty_windows():
    assert _pick_window_slot_aabb({"windows": []}) is None
    assert _pick_window_slot_aabb({}) is None


def test_garden_aabb_clamps_y_span():
    """Garden footprint covers full site horizontally but only y0..y0+2."""
    garden = _garden_aabb_from_site([0, 0, 0, 40, 30, 40])
    assert garden == [0, 0, 0, 40, 2, 40]


def test_garden_aabb_returns_None_for_malformed_site():
    assert _garden_aabb_from_site([]) is None
    assert _garden_aabb_from_site([0, 0]) is None


def test_tower_silhouette_detection():
    assert _is_tower_silhouette("tower-cylinder-silhouette") is True
    assert _is_tower_silhouette("round_tower") is True
    assert _is_tower_silhouette("hexagon-keep-silhouette") is True
    assert _is_tower_silhouette("minaret_tall") is True
    assert _is_tower_silhouette("italian-campanile") is True
    assert _is_tower_silhouette("gable-cottage-silhouette") is False
    assert _is_tower_silhouette("u-courtyard-silhouette") is False
    assert _is_tower_silhouette(None) is False


# ────────────────────────────────────────────────────────────────────────
#  Per-kind injection tests
# ────────────────────────────────────────────────────────────────────────

def test_inject_roof_appends_one_typology_op():
    gi = {"style": "medieval", "silhouette_id": "manor",
          "selected_typologies": {"roof": "mansard_roof"}}
    ap = _mock_architecture_plan()
    out = inject(global_intent=gi, architecture_plan=ap,
                  connector_plan=_mock_connector_plan())
    typology_ops = [o for o in out["ops"] if o.get("kind") == "typology"]
    assert len(typology_ops) == 1
    assert typology_ops[0]["name"] == "mansard_roof"
    assert typology_ops[0]["envelope_role"] == "roof"
    assert typology_ops[0]["aabb"] == [0, 5, 0, 12, 6, 10]


def test_inject_tower_only_for_tower_silhouettes():
    """Cottage silhouette → tower typology dropped even if chooser picked it."""
    gi = {"style": "medieval", "silhouette_id": "gable-cottage-silhouette",
          "building_aabb": [0, 0, 0, 12, 8, 10],
          "selected_typologies": {"tower": "norman_keep"}}
    ap = _mock_architecture_plan()
    out = inject(global_intent=gi, architecture_plan=ap,
                  connector_plan=_mock_connector_plan())
    typology_ops = [o for o in out["ops"] if o.get("kind") == "typology"]
    assert typology_ops == [], (
        f"expected tower to be skipped for non-tower silhouette, got {typology_ops}")


def test_inject_tower_emitted_for_tower_silhouette():
    """Tower silhouette + tower pick + building_aabb → 1 typology op."""
    gi = {"style": "gothic", "silhouette_id": "tower-cylinder-silhouette",
          "building_aabb": [0, 0, 0, 12, 25, 12],
          "selected_typologies": {"tower": "norman_keep"}}
    out = inject(global_intent=gi, architecture_plan=_mock_architecture_plan(),
                  connector_plan=_mock_connector_plan())
    typology_ops = [o for o in out["ops"] if o.get("kind") == "typology"]
    assert len(typology_ops) == 1
    op = typology_ops[0]
    assert op["name"] == "norman_keep"
    assert op["envelope_role"] == "tower"
    assert op["aabb"] == [0, 0, 0, 12, 25, 12]


def test_inject_tower_skipped_when_building_aabb_missing():
    gi = {"style": "medieval", "silhouette_id": "round_tower",
          "selected_typologies": {"tower": "norman_keep"}}
    out = inject(global_intent=gi, architecture_plan=_mock_architecture_plan(),
                  connector_plan=_mock_connector_plan())
    assert all(o.get("kind") != "typology" for o in out["ops"])


def test_inject_window_uses_connector_slot():
    gi = {"style": "victorian", "silhouette_id": "manor",
          "selected_typologies": {"window": "oriel_window"}}
    cp = _mock_connector_plan()
    out = inject(global_intent=gi, architecture_plan=_mock_architecture_plan(),
                  connector_plan=cp)
    typology_ops = [o for o in out["ops"] if o.get("kind") == "typology"]
    assert len(typology_ops) == 1
    op = typology_ops[0]
    assert op["name"] == "oriel_window"
    assert op["envelope_role"] == "window"
    # AABB should match the first window slot.
    assert op["aabb"] == [4, 2, 0, 6, 4, 1]


def test_inject_window_skipped_when_no_slot():
    gi = {"style": "victorian", "silhouette_id": "manor",
          "selected_typologies": {"window": "oriel_window"}}
    out = inject(global_intent=gi, architecture_plan=_mock_architecture_plan(),
                  connector_plan={"windows": []})
    assert all(o.get("kind") != "typology" for o in out["ops"])


def test_inject_garden_uses_site_aabb():
    gi = {"style": "georgian", "silhouette_id": "manor",
          "site_aabb": [0, 0, 0, 40, 30, 40],
          "building_aabb": [10, 0, 10, 30, 25, 30],
          "selected_typologies": {"garden": "formal_garden"}}
    out = inject(global_intent=gi, architecture_plan=_mock_architecture_plan(),
                  connector_plan=_mock_connector_plan())
    typology_ops = [o for o in out["ops"] if o.get("kind") == "typology"]
    assert len(typology_ops) == 1
    op = typology_ops[0]
    assert op["name"] == "formal_garden"
    assert op["envelope_role"] == "garden"
    # Garden footprint = full site, y span = [0, 2].
    assert op["aabb"] == [0, 0, 0, 40, 2, 40]


def test_inject_garden_skipped_when_no_site_aabb():
    gi = {"style": "georgian", "silhouette_id": "manor",
          "selected_typologies": {"garden": "formal_garden"}}
    out = inject(global_intent=gi, architecture_plan=_mock_architecture_plan(),
                  connector_plan=_mock_connector_plan())
    assert all(o.get("kind") != "typology" for o in out["ops"])


def test_inject_all_four_kinds_emits_four_typology_ops():
    gi = {"style": "gothic", "silhouette_id": "tower-cylinder-silhouette",
          "building_aabb": [10, 0, 10, 30, 25, 30],
          "site_aabb":     [0, 0, 0, 40, 30, 40],
          "selected_typologies": {
              "tower":  "norman_keep",
              "roof":   "mansard_roof",
              "window": "oriel_window",
              "garden": "formal_garden",
          }}
    out = inject(global_intent=gi, architecture_plan=_mock_architecture_plan(),
                  connector_plan=_mock_connector_plan())
    typology_ops = [o for o in out["ops"] if o.get("kind") == "typology"]
    assert len(typology_ops) == 4
    roles = {o["envelope_role"] for o in typology_ops}
    assert roles == {"roof", "tower", "window", "garden"}


# ────────────────────────────────────────────────────────────────────────
#  Backwards compatibility + invariants
# ────────────────────────────────────────────────────────────────────────

def test_inject_no_selection_returns_plan_unchanged():
    gi = {"style": "medieval", "silhouette_id": "manor",
          "selected_typologies": {}}
    ap = _mock_architecture_plan()
    out = inject(global_intent=gi, architecture_plan=ap,
                  connector_plan=_mock_connector_plan())
    assert out["ops"] == ap["ops"]


def test_inject_missing_selected_typologies_key_is_safe():
    gi = {"style": "medieval", "silhouette_id": "manor"}
    ap = _mock_architecture_plan()
    out = inject(global_intent=gi, architecture_plan=ap)
    assert out["ops"] == ap["ops"]


def test_inject_connector_plan_optional():
    """connector_plan=None → only roof/tower/garden are eligible (no window)."""
    gi = {"style": "medieval", "silhouette_id": "manor",
          "selected_typologies": {"roof": "mansard_roof",
                                   "window": "oriel_window"}}
    out = inject(global_intent=gi, architecture_plan=_mock_architecture_plan(),
                  connector_plan=None)
    typology_ops = [o for o in out["ops"] if o.get("kind") == "typology"]
    # Roof appended; window dropped because no connector_plan.
    assert len(typology_ops) == 1
    assert typology_ops[0]["name"] == "mansard_roof"


def test_inject_does_not_mutate_input_plan():
    gi = {"style": "medieval", "silhouette_id": "manor",
          "selected_typologies": {"roof": "mansard_roof"}}
    ap = _mock_architecture_plan()
    ops_before = list(ap["ops"])
    inject(global_intent=gi, architecture_plan=ap,
            connector_plan=_mock_connector_plan())
    assert ap["ops"] == ops_before


def test_inject_drops_roof_when_no_envelope_roof_present():
    gi = {"style": "medieval", "silhouette_id": "manor",
          "selected_typologies": {"roof": "mansard_roof"}}
    ap = {"ops": [
        {"kind": "fill_hollow", "envelope_role": "wall",
         "aabb": [0, 0, 0, 5, 5, 5], "wall": "@primary"},
    ]}
    out = inject(global_intent=gi, architecture_plan=ap,
                  connector_plan=_mock_connector_plan())
    assert all(o.get("kind") != "typology" for o in out["ops"])
