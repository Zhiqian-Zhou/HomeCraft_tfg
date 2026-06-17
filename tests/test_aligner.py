"""Tests for the aligner — deterministic floater removal + coherence verdict.

LLM is always disabled here (run_llm=False) so the tests are hermetic.
"""
from __future__ import annotations

from pipeline.agents import aligner


def _box(W=4, H=4, D=4, pal_idx=0):
    """A hollow grounded box on y=0."""
    vox = []
    for x in range(W):
        for z in range(D):
            for y in range(H):
                if x in (0, W - 1) or z in (0, D - 1) or y == 0:
                    vox.append([x, y, z, pal_idx])
    return vox


def _doc(vox, size, pal=None):
    return {"bounding_box": {"size": list(size)},
            "block_palette": pal or {"0": "minecraft:stone"},
            "voxels": vox}


def test_removes_airborne_floater():
    vox = _box()
    vox += [[2, 8, 2, 0], [2, 8, 3, 0]]          # disconnected floating chunk
    doc = _doc(vox, [6, 10, 6])
    before = len(doc["voxels"])
    polished, rep = aligner.align(doc, run_llm=False)
    coords = {(v[0], v[1], v[2]) for v in polished["voxels"]}
    assert (2, 8, 2) not in coords and (2, 8, 3) not in coords
    assert rep["deterministic"]["floaters_removed"] == 2
    assert len(polished["voxels"]) == before - 2
    assert rep["coherent"] is True


def test_keeps_grounded_exterior_prop():
    """A separate ground-resting object (e.g. a tree) is NOT a floater."""
    vox = _box()
    pal = {"0": "minecraft:stone", "1": "minecraft:oak_log"}
    for y in range(4):                            # a tree trunk to the ground
        vox.append([10, y, 10, 1])
    doc = _doc(vox, [14, 6, 14], pal)
    polished, rep = aligner.align(doc, run_llm=False)
    coords = {(v[0], v[1], v[2]) for v in polished["voxels"]}
    assert (10, 3, 10) in coords           # tree kept (grounded)
    assert rep["deterministic"]["floaters_removed"] == 0
    assert rep["coherent"] is True


def test_clean_build_is_coherent_no_changes():
    doc = _doc(_box(6, 5, 6), [6, 5, 6])
    before = len(doc["voxels"])
    polished, rep = aligner.align(doc, run_llm=False)
    assert len(polished["voxels"]) == before
    assert rep["deterministic"]["action"] == "none"
    assert rep["coherent"] is True


def test_massive_floating_is_reported_not_deleted():
    """If 'floaters' exceed the safe threshold, report instead of nuking."""
    # tiny grounded speck + a big airborne mass → don't delete the big mass.
    vox = [[0, 0, 0, 0]]
    for x in range(6):
        for y in range(5, 9):
            for z in range(6):
                vox.append([x, y, z, 0])
    doc = _doc(vox, [6, 9, 6])
    polished, rep = aligner.align(doc, run_llm=False)
    assert rep["deterministic"]["action"] == "reported_only"
    assert rep["deterministic"]["floaters_removed"] == 0
    assert rep["coherent"] is False        # flagged for attention
    assert len(polished["voxels"]) == len(doc["voxels"])  # nothing deleted


def test_stair_pitched_roof_not_removed():
    """REGRESSION: a stepped (stair) gable roof steps diagonally and is
    6-disconnected from the walls, but it visually RESTS on them. The aligner
    uses 26-connectivity, so it must NOT be removed as a floater."""
    W = D = 8
    pal = {"0": "minecraft:oak_planks", "1": "minecraft:oak_stairs"}
    vox = []
    # solid-ish box: walls + floor + a full ceiling at y=4
    for x in range(W):
        for z in range(D):
            vox.append([x, 0, z, 0])               # floor
            vox.append([x, 4, z, 0])               # ceiling (roof base support)
            if x in (0, W - 1) or z in (0, D - 1):
                for y in range(1, 4):
                    vox.append([x, y, z, 0])       # walls
    # stepped gable rising from the ceiling: each step Δy=1, Δz=1 (diagonal)
    for i in range(3):
        y = 5 + i
        for x in range(W):
            vox.append([x, y, i, 1])               # south slope (z = i)
            vox.append([x, y, D - 1 - i, 1])       # north slope
    doc = _doc(vox, [W, 9, D], pal)
    before = len(doc["voxels"])
    polished, rep = aligner.align(doc, run_llm=False)
    # the whole roof + box is one grounded component → nothing removed
    assert rep["deterministic"]["floaters_removed"] == 0, rep["deterministic"]
    assert len(polished["voxels"]) == before
    assert rep["coherent"] is True


def test_empty_doc_is_not_coherent():
    doc = _doc([], [4, 4, 4])
    _, rep = aligner.align(doc, run_llm=False)
    assert rep["coherent"] is False


def test_report_shape():
    doc = _doc(_box(), [6, 6, 6])
    _, rep = aligner.align(doc, run_llm=False)
    assert rep["stage"] == "aligner"
    assert "deterministic" in rep and "llm" in rep
    assert rep["llm"] is None and rep["llm_ran"] is False
    det = rep["deterministic"]
    assert {"components", "grounded_ratio", "action"} <= set(det)
