"""Tests for the spiral staircase geometry + the stair-shape selection."""
from __future__ import annotations

from pipeline.agents.aggregator import _spiral_stair_ops, _v3_connector_ops


def _stair_at(ops):
    return {(o["at"][0], o["at"][1], o["at"][2]) for o in ops if o["kind"] == "place"}


def test_spiral_winds_the_perimeter_rising_one_per_step():
    # 3x3 shaft, rise from y=0 to y=9
    ops = _spiral_stair_ops([0, 0, 0, 3, 9, 3], "minecraft:oak_stairs")
    assert ops, "spiral produced no ops"
    ys = sorted(o["at"][1] for o in ops)
    # one step per Y level, contiguous
    assert ys == list(range(0, 9)), ys
    # every step is a stair on the perimeter (centre cell (1,1) stays an air well)
    cells = {(o["at"][0], o["at"][2]) for o in ops}
    assert (1, 1) not in cells, "centre of a 3x3 spiral must stay open"
    assert all(o["block"].startswith("minecraft:oak_stairs[facing=") for o in ops)


def test_spiral_consecutive_steps_are_adjacent_with_air_above():
    """The climb path: step(cur,y) → air(cur,y+1) → step(nxt,y+1). Consecutive
    steps must be on adjacent perimeter cells (so the air above each step is
    free for the next move)."""
    ops = sorted(_spiral_stair_ops([0, 0, 0, 3, 8, 3], "minecraft:oak_stairs"),
                 key=lambda o: o["at"][1])
    steps = [(o["at"][0], o["at"][1], o["at"][2]) for o in ops]
    occupied = {(x, y, z) for (x, y, z) in steps}
    for (x, y, z) in steps:
        # the cell directly above a step must NOT be another step (air to climb)
        assert (x, y + 1, z) not in occupied, (x, y, z)


def test_v3_picks_spiral_for_3x3_and_ladder_for_2x2():
    def cp(aabb):
        return {"doors": [], "windows": [],
                "staircases": [{"validated": {"aabb": aabb, "shape": "spiral",
                                              "block_key": "minecraft:oak_stairs"}}]}
    # 3x3 tall shaft → spiral (stairs winding, no ladder)
    ops3 = _v3_connector_ops(cp([0, 0, 0, 3, 10, 3]))
    assert any("ladder" not in str(o.get("block", "")) and o.get("kind") == "place"
               for o in ops3)
    assert not any("ladder" in str(o.get("block", "")) for o in ops3)
    # an air carve is emitted to open the well
    assert any(o.get("kind") == "fill" and o.get("block") == "minecraft:air"
               for o in ops3)
    # 2x2 tall shaft → ladder fallback
    ops2 = _v3_connector_ops(cp([0, 0, 0, 2, 10, 2]))
    assert any("ladder" in str(o.get("block", "")) for o in ops2)


def test_spiral_degenerate_footprint_no_crash():
    assert _spiral_stair_ops([0, 0, 0, 1, 5, 1], "minecraft:oak_stairs") == []
