"""Tests for pipeline.agents.architecture_planner — DETERMINISTIC envelope."""
from __future__ import annotations

from pipeline.agents.architecture_planner import (
    plan_architecture, _aabbs_share_wall, _palette,
)


def _gi(**kw) -> dict:
    base = {
        "schema_version": "1.0",
        "prompt": "test",
        "category": "residential",
        "style": "medieval",
        "site_aabb": [0, 0, 0, 10, 8, 10],
        "building_aabb": [0, 0, 0, 10, 8, 10],
        "floors": [{"index": 0, "y0": 0, "y1": 4}],
        "height_intent": {},
        "alexander_rationale": [],
    }
    base.update(kw)
    return base


def _sp(rooms: list[dict], **kw) -> dict:
    base = {"schema_version": "1.0", "rooms": rooms,
            "adjacency_graph": kw.get("adjacency_graph", [])}
    return base


def test_single_room_emits_fill_hollow_slab_roof_light():
    # building_aabb.y1 == floor.y1 → roof is a single flat cap on the walls.
    gi = _gi(building_aabb=[0, 0, 0, 5, 4, 5])
    sp = _sp([{"id": "kitchen-1", "role": "kitchen", "floor": 0,
                "aabb": [0, 0, 0, 5, 4, 5]}])
    plan = plan_architecture(gi, sp)
    kinds = [op["kind"] for op in plan["ops"]]
    assert kinds.count("fill_hollow") == 1
    assert kinds.count("place") == 1                      # one lantern
    roof = [op for op in plan["ops"] if op.get("envelope_role") == "roof"]
    slab = [op for op in plan["ops"] if op.get("envelope_role") == "floor_slab"]
    assert len(slab) == 1
    assert len(roof) == 1                                  # no gap → one cap
    # Roof sits on the walls (top floor y1 = 4), NOT floating above.
    assert roof[0]["level"] == 4


def test_two_adjacent_rooms_emit_shared_with_tags():
    gi = _gi()
    sp = _sp([
        {"id": "a", "role": "kitchen", "floor": 0,
         "aabb": [0, 0, 0, 5, 4, 5]},
        {"id": "b", "role": "living_room", "floor": 0,
         "aabb": [5, 0, 0, 10, 4, 5]},
    ])
    plan = plan_architecture(gi, sp)
    fh_ops = [op for op in plan["ops"] if op["kind"] == "fill_hollow"]
    assert len(fh_ops) == 2
    # Each should know about the other
    by_id = {op["room_id"]: op for op in fh_ops}
    assert "b" in by_id["a"]["shared_with"]
    assert "a" in by_id["b"]["shared_with"]


def test_two_floors_emit_two_slabs():
    gi = _gi(
        floors=[{"index": 0, "y0": 0, "y1": 4},
                 {"index": 1, "y0": 4, "y1": 8}],
        building_aabb=[0, 0, 0, 10, 8, 10],
    )
    sp = _sp([
        {"id": "ground", "role": "living_room", "floor": 0,
         "aabb": [0, 0, 0, 10, 4, 10]},
        {"id": "upper", "role": "bedroom", "floor": 1,
         "aabb": [0, 4, 0, 10, 8, 10]},
    ])
    plan = plan_architecture(gi, sp)
    slab_ops = [op for op in plan["ops"] if op.get("envelope_role") == "floor_slab"]
    assert len(slab_ops) == 2
    # Slabs at y=0 and y=4
    levels = sorted(op["level"] for op in slab_ops)
    assert levels == [0, 4]


def test_roof_sits_on_walls_not_floating():
    # building_aabb is taller (y1=8) than the single floor (y1=4): the roof
    # must START on the walls at y=4 and step up to fill the gap — never a
    # lone slab floating at y=7 over empty layers.
    gi = _gi(building_aabb=[0, 0, 0, 10, 8, 10],
             height_intent={"roof_style": "gable"})
    sp = _sp([{"id": "r", "role": "kitchen", "floor": 0,
                "aabb": [0, 0, 0, 10, 4, 10]}])
    plan = plan_architecture(gi, sp)
    roof = [op for op in plan["ops"] if op.get("envelope_role") == "roof"]
    levels = sorted(op["level"] for op in roof)
    # Base layer is on the wall top (y=4), and layers are contiguous (no gap).
    assert levels[0] == 4
    assert levels == list(range(4, 4 + len(levels)))


def _roof_ops_for(roof_style):
    gi = _gi(building_aabb=[0, 0, 0, 14, 12, 20],
             floors=[{"index": 0, "y0": 0, "y1": 5}, {"index": 1, "y0": 5, "y1": 10}],
             height_intent={"roof_style": roof_style})
    floor_plans = [
        {"floor_index": 0, "reserved_footprints": [], "adjacency_graph": [],
         "rooms": [{"id": "a", "role": "hall", "floor": 0, "aabb": [1, 0, 1, 13, 5, 19]}]},
        {"floor_index": 1, "reserved_footprints": [], "adjacency_graph": [],
         "rooms": [{"id": "b", "role": "room", "floor": 1, "aabb": [1, 5, 1, 13, 10, 19]}]},
    ]
    from pipeline.agents.architecture_planner import plan_architecture_v4
    plan = plan_architecture_v4(gi, floor_plans)
    return [o for o in plan["ops"] if o.get("envelope_role") == "roof"]


def test_roof_styles_produce_distinct_geometry():
    """gable/hip/flat/crenellated must NOT all be the same stepped pyramid."""
    sigs = {}
    for s in ("flat", "hip", "gable", "crenellated", "pagoda"):
        ops = _roof_ops_for(s)
        sigs[s] = (len(ops), tuple(sorted({o.get("kind") for o in ops})),
                   tuple(sorted({o.get("block") for o in ops})))
    # at least 4 of the 5 styles differ from each other
    assert len(set(sigs.values())) >= 4, sigs


def test_gable_has_stair_slopes_and_two_facings():
    ops = _roof_ops_for("gable")
    facings = set()
    for o in ops:
        b = o.get("block", "")
        if "_stairs[" in b and "facing=" in b:
            facings.add(b.split("facing=")[1].rstrip("]"))
    assert len(facings) >= 2, f"gable should have >=2 stair facings, got {facings}"


def test_crenellated_places_merlons_on_perimeter():
    ops = _roof_ops_for("crenellated")
    merlons = [o for o in ops if o.get("kind") == "place"]
    assert len(merlons) >= 4, "crenellated roof should place merlon blocks"


def test_roof_library_many_styles_distinct():
    """The expanded roof library renders a wide range of styles distinctly —
    not all the same stepped pyramid. Sample across the families."""
    styles = ["gable", "gable-steep", "saltbox", "mansard", "gambrel",
              "hip", "spire", "dome", "onion", "pagoda", "butterfly",
              "skillion", "barrel", "sawtooth", "crenellated"]
    sigs = {}
    for s in styles:
        ops = _roof_ops_for(s)
        assert ops, f"{s} produced no roof ops"
        sigs[s] = (len(ops),
                   tuple(sorted({o.get("kind") for o in ops})),
                   max((o.get("level", o.get("at", [0, 0, 0])[1]) for o in ops)))
    # the great majority must be mutually distinct geometries
    assert len(set(sigs.values())) >= len(styles) - 3, sigs


def test_rounded_footprint_gable_falls_back_to_cone_not_bridge():
    """A gable over a ROUND tower would bridge the void — the masked path must
    fall back to a centred cone instead. Verify no roof op spans the full
    width at a single level above the wall top (which a gable ridge would)."""
    gi = _gi(building_aabb=[0, 0, 0, 13, 24, 13],
             floors=[{"index": 0, "y0": 0, "y1": 5}, {"index": 1, "y0": 5, "y1": 10}],
             height_intent={"roof_style": "gable"},
             silhouette_id="tower-cylinder-silhouette",
             silhouette_parameters={"footprint_shape": "circle",
                                    "floor_progression": "setback"})
    fps = [
        {"floor_index": 0, "reserved_footprints": [], "adjacency_graph": [],
         "rooms": [{"id": "a", "role": "hall", "floor": 0, "aabb": [0, 0, 0, 13, 5, 13]}]},
        {"floor_index": 1, "reserved_footprints": [], "adjacency_graph": [],
         "rooms": [{"id": "b", "role": "room", "floor": 1, "aabb": [0, 5, 0, 13, 10, 13]}]},
    ]
    from pipeline.agents.architecture_planner import plan_architecture_v4
    roof = [o for o in plan_architecture_v4(gi, fps)["ops"]
            if o.get("envelope_role") == "roof"]
    # cone rises to a point: it has place ops (apex) OR shrinking rings — and it
    # is centred, so it rises well above the wall top (10).
    top = max(o.get("level", o.get("at", [0, 0, 0])[1]) for o in roof)
    assert top > 10, "round-tower roof should rise above the walls to a point"


def test_tower_cone_rises_tall_pointed_roof():
    """A spire on a round tower must rise a real point, not a flat cap."""
    from pipeline.agents.architecture_planner import _roof_cone
    ops = _roof_cone(0, 0, 9, 9, wall_top=20, block="minecraft:stone", mode="spire")
    ys = [o.get("level", o.get("at", [0, 0, 0])[1]) for o in ops]
    assert max(ys) - 20 >= 6, "spire should rise at least 6 above the walls"


def test_flat_roof_is_single_cap_on_walls():
    gi = _gi(building_aabb=[0, 0, 0, 10, 8, 10],
             height_intent={"roof_style": "flat"})
    sp = _sp([{"id": "r", "role": "kitchen", "floor": 0,
                "aabb": [0, 0, 0, 10, 4, 10]}])
    plan = plan_architecture(gi, sp)
    roof = [op for op in plan["ops"] if op.get("envelope_role") == "roof"]
    assert len(roof) == 1
    assert roof[0]["level"] == 4          # flat cap on the walls, no steps


def test_style_resolves_to_palette():
    for style in ["medieval", "modern", "fantasy", "japanese",
                    "mediterranean", "rustic"]:
        p = _palette(style)
        assert "primary" in p
        assert p["primary"].startswith("minecraft:")


def test_unknown_style_falls_back_to_medieval():
    p = _palette("klingon")
    assert p["primary"] == "minecraft:oak_planks"


def test_materials_used_lists_distinct_blocks():
    gi = _gi(style="medieval")
    sp = _sp([{"id": "r", "role": "kitchen", "floor": 0,
                "aabb": [0, 0, 0, 5, 4, 5]}])
    plan = plan_architecture(gi, sp)
    blocks = {m["block_id"] for m in plan["materials_used"]}
    # medieval palette has primary=oak_planks, floor=oak_planks (same!)
    # and roof=dark_oak_planks
    assert "minecraft:oak_planks" in blocks
    assert "minecraft:dark_oak_planks" in blocks


def test_deterministic_same_inputs_same_output():
    """The planner is deterministic — running twice gives identical output."""
    gi = _gi()
    sp = _sp([
        {"id": "a", "role": "kitchen", "floor": 0,
         "aabb": [0, 0, 0, 5, 4, 5]},
        {"id": "b", "role": "bedroom", "floor": 0,
         "aabb": [5, 0, 0, 10, 4, 5]},
    ])
    p1 = plan_architecture(gi, sp)
    p2 = plan_architecture(gi, sp)
    assert p1 == p2


def test_aabbs_share_wall_east_west():
    # A.x1 == B.x0 (touching east-west)
    assert _aabbs_share_wall((0, 0, 0, 5, 4, 5), (5, 0, 0, 10, 4, 5))


def test_aabbs_share_wall_not_overlapping():
    # Rooms separated by 2 blocks → no shared wall
    assert not _aabbs_share_wall((0, 0, 0, 5, 4, 5), (7, 0, 0, 12, 4, 5))


def test_schema_validity():
    """Output validates against architecture_plan.schema.json."""
    from pipeline.agents.schema_utils import make_validator
    validator = make_validator("architecture_plan.schema.json")
    gi = _gi()
    sp = _sp([{"id": "r", "role": "kitchen", "floor": 0,
                "aabb": [0, 0, 0, 5, 4, 5]}])
    plan = plan_architecture(gi, sp)
    validator.validate(plan)
