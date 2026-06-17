"""Tests for the coherence agent — deterministic cross-component fit.

LLM disabled (run_llm=False) so tests are hermetic.
"""
from __future__ import annotations

from pipeline.agents import coherence_agent as CA


def _gi(shape="rectangle", prog=None, bb=(0, 0, 0, 12, 10, 10), sid="gable-cottage-silhouette"):
    params = {"footprint_shape": shape}
    if prog:
        params["floor_progression"] = prog
    return {"silhouette_id": sid, "style": "medieval", "category": "residential",
            "building_aabb": list(bb), "silhouette_parameters": params,
            "floors": [{"index": 0}, {"index": 1}]}


def _fp(idx, rooms):
    return {"floor_index": idx, "rooms": rooms,
            "reserved_footprints": [], "adjacency_graph": []}


def test_protruding_room_clamped_to_building():
    gi = _gi()
    fps = [
        _fp(0, [{"id": "a", "role": "living_room", "aabb": [0, 0, 0, 12, 5, 10]}]),
        _fp(1, [{"id": "b", "role": "bedroom", "aabb": [1, 5, 1, 16, 10, 12]}]),  # x1,z1 protrude
    ]
    out, rep = CA.reconcile(gi, fps, run_llm=False, log=lambda *a, **k: None)
    bx = out[1]["rooms"][0]["aabb"]
    assert bx[3] <= 12 and bx[5] <= 10, bx          # no protrusion past building
    assert rep["deterministic"]["rooms_adjusted"] >= 1


def test_upper_room_snaps_onto_lower_walls():
    gi = _gi()
    fps = [
        _fp(0, [{"id": "a", "role": "living_room", "aabb": [0, 0, 0, 12, 5, 10]}]),
        _fp(1, [{"id": "b", "role": "bedroom", "aabb": [1, 5, 1, 11, 10, 9]}]),   # jogged in by 1
    ]
    out, _ = CA.reconcile(gi, fps, run_llm=False, log=lambda *a, **k: None)
    bx = out[1]["rooms"][0]["aabb"]
    # snapped onto the lower room's edges (0 and 12 / 0 and 10) within tol
    assert bx[0] == 0 and bx[3] == 12 and bx[2] == 0 and bx[5] == 10, bx


def test_aligned_building_is_unchanged():
    gi = _gi()
    fps = [
        _fp(0, [{"id": "a", "role": "kitchen", "aabb": [0, 0, 0, 12, 5, 10]}]),
        _fp(1, [{"id": "b", "role": "bedroom", "aabb": [0, 5, 0, 12, 10, 10]}]),
    ]
    out, rep = CA.reconcile(gi, fps, run_llm=False, log=lambda *a, **k: None)
    assert rep["deterministic"]["rooms_adjusted"] == 0
    assert out[1]["rooms"][0]["aabb"] == [0, 5, 0, 12, 10, 10]


def test_tower_kind_detected_from_setback():
    gi = _gi(shape="square", prog="setback", sid="tower-square-silhouette")
    fps = [_fp(0, [{"id": "a", "role": "hall", "aabb": [0, 0, 0, 12, 5, 12]}])]
    _, rep = CA.reconcile(gi, fps, run_llm=False, log=lambda *a, **k: None)
    assert rep["deterministic"]["building_kind"] == "tower"


def test_adjacency_completion_connects_all_rooms():
    """A floor of unlinked but wall-sharing rooms must end fully connected."""
    fp = {"floor_index": 0, "adjacency_graph": [], "rooms": [
        {"id": "a", "aabb": [0, 0, 0, 6, 5, 6]},
        {"id": "b", "aabb": [6, 0, 0, 12, 5, 6]},
        {"id": "c", "aabb": [0, 0, 6, 6, 5, 12]},
        {"id": "d", "aabb": [6, 0, 6, 12, 5, 12]},
    ]}
    added = CA._complete_adjacency(fp)
    assert added >= 3                      # ≥ enough to connect 4 rooms
    adj = {}
    for e in fp["adjacency_graph"]:
        adj.setdefault(e["from_room"], set()).add(e["to_room"])
        adj.setdefault(e["to_room"], set()).add(e["from_room"])
    seen, stack = {"a"}, ["a"]
    while stack:
        for m in adj.get(stack.pop(), ()):
            if m not in seen:
                seen.add(m); stack.append(m)
    assert seen == {"a", "b", "c", "d"}


def test_adjacency_completion_preserves_existing_links():
    fp = {"floor_index": 0, "rooms": [
        {"id": "a", "aabb": [0, 0, 0, 6, 5, 6]},
        {"id": "b", "aabb": [6, 0, 0, 12, 5, 6]}],
        "adjacency_graph": [{"from_room": "a", "to_room": "b", "kind": "opening"}]}
    added = CA._complete_adjacency(fp)
    assert added == 0                      # already linked → no duplicate door
    kinds = [e["kind"] for e in fp["adjacency_graph"]]
    assert kinds == ["opening"]


def test_stair_access_extends_room_over_shaft():
    """A stair shaft with no room over it on a floor → nearest room extends to
    engulf it (so the connectivity BFS can reach the ladder)."""
    fps = [
        {"floor_index": 0, "adjacency_graph": [],
         "reserved_footprints": [{"x0": 8, "z0": 8, "x1": 10, "z1": 10, "kind": "stair"}],
         "rooms": [{"id": "a", "role": "kitchen", "aabb": [0, 0, 0, 6, 5, 6]}]},
        {"floor_index": 1, "adjacency_graph": [],
         "reserved_footprints": [{"x0": 8, "z0": 8, "x1": 10, "z1": 10, "kind": "stair"}],
         "rooms": [{"id": "b", "role": "hallway", "aabb": [0, 5, 0, 12, 10, 12]}]},
    ]
    n = CA._ensure_stair_access(fps, 0, 0, 12, 12)
    assert n >= 1
    a = fps[0]["rooms"][0]["aabb"]              # floor-0 room engulfs (9,9)
    assert a[0] <= 9 < a[3] and a[2] <= 9 < a[5], a


def test_unify_stair_core_single_shared_shaft():
    """Multi-floor: all stair reservations collapse to ONE shared shaft at the
    same (x,z) on every floor (a continuous climbable core)."""
    fps = [
        {"floor_index": 0, "adjacency_graph": [], "rooms": [
            {"id": "a", "aabb": [0, 0, 0, 10, 5, 10]}],
         "reserved_footprints": [{"x0": 7, "z0": 7, "x1": 10, "z1": 10,
                                  "kind": "stair", "template_id": "spiral-staircase"}]},
        {"floor_index": 1, "adjacency_graph": [], "rooms": [
            {"id": "b", "aabb": [0, 5, 0, 10, 10, 10]}],
         "reserved_footprints": [{"x0": 0, "z0": 7, "x1": 3, "z1": 10,
                                  "kind": "stair", "template_id": "spiral-staircase"}]},
        {"floor_index": 2, "adjacency_graph": [], "rooms": [
            {"id": "c", "aabb": [2, 10, 2, 8, 15, 8]}],
         "reserved_footprints": [{"x0": 5, "z0": 2, "x1": 8, "z1": 5,
                                  "kind": "stair", "template_id": "spiral-staircase"}]},
    ]
    n = CA._unify_stair_core(fps)
    assert n == 1
    cores = []
    for fp in fps:
        st = [r for r in fp["reserved_footprints"] if r["kind"] == "stair"]
        assert len(st) == 1, "each floor must have exactly one stair shaft"
        cores.append((st[0]["x0"], st[0]["z0"], st[0]["x1"], st[0]["z1"]))
    assert len(set(cores)) == 1, f"shaft must be identical on all floors: {cores}"
    # and it sits inside the top floor's room [2..8, 2..8]
    x0, z0, x1, z1 = cores[0]
    assert 2 <= x0 and x1 <= 8 and 2 <= z0 and z1 <= 8, cores[0]


def test_close_room_gaps_makes_rooms_touch():
    """Two rooms with a 1-cell gap → the gap is closed so they share a wall."""
    fp = {"floor_index": 0, "adjacency_graph": [], "rooms": [
        {"id": "a", "aabb": [0, 0, 0, 6, 5, 8]},
        {"id": "b", "aabb": [7, 0, 0, 13, 5, 8]},   # 1-cell x-gap (a.x1=6, b.x0=7)
    ]}
    n = CA._close_room_gaps(fp)
    assert n == 1
    a, b = fp["rooms"][0]["aabb"], fp["rooms"][1]["aabb"]
    assert CA._shares_wall(a, b), (a, b)
    assert not CA._overlap_xz(a, b)


def test_close_room_gaps_ignores_large_gaps_and_void():
    fp = {"floor_index": 0, "rooms": [
        {"id": "a", "aabb": [0, 0, 0, 6, 5, 8]},
        {"id": "b", "aabb": [12, 0, 0, 18, 5, 8]},  # 6-cell gap (a courtyard) → leave
    ], "adjacency_graph": []}
    assert CA._close_room_gaps(fp) == 0


def test_unify_stair_core_skips_single_floor():
    fps = [{"floor_index": 0, "rooms": [{"id": "a", "aabb": [0, 0, 0, 8, 5, 8]}],
            "reserved_footprints": [], "adjacency_graph": []}]
    assert CA._unify_stair_core(fps) == 0


def test_min_room_size_preserved():
    """Clamping must not collapse a room below 3×3."""
    gi = _gi(bb=(0, 0, 0, 5, 10, 5))
    fps = [
        _fp(0, [{"id": "a", "role": "kitchen", "aabb": [0, 0, 0, 5, 5, 5]}]),
        _fp(1, [{"id": "b", "role": "bedroom", "aabb": [3, 5, 3, 9, 10, 9]}]),
    ]
    out, _ = CA.reconcile(gi, fps, run_llm=False, log=lambda *a, **k: None)
    bx = out[1]["rooms"][0]["aabb"]
    assert bx[3] - bx[0] >= 3 and bx[5] - bx[2] >= 3, bx
    assert bx[3] <= 5 and bx[5] <= 5, bx
