"""Validación de la composición multi-masa (torres de esquina, palanca 2).

Comprueba que add_masses añade torres a un edificio grande/monument y que el
resultado NO tiene bloques flotantes (torres ancladas a las esquinas).
"""
from __future__ import annotations

import json

from pipeline.agents import massing, aligner


def _box_doc(w=30, h=10, d=30):
    """Cubo hueco simple (paredes) como edificio base, formato ReferenceBuilding."""
    pal = {"0": "minecraft:stone_bricks"}
    vox = []
    for x in range(w):
        for y in range(h):
            for z in range(d):
                if x in (0, w-1) or z in (0, d-1) or y == 0:
                    vox.append([x, y, z, 0])
    return {"id": "massing-test", "bounding_box": {"size": [w, h, d]},
            "block_palette": pal, "voxels": vox}


def test_design_driven_masses_no_floaters():
    # el diseño (LLM) pide masas coherentes: fortaleza → torres de esquina + keep
    doc = _box_doc()
    gi = {"building_aabb": [0, 0, 0, 30, 10, 30],
          "site_aabb": [-8, 0, -8, 38, 40, 38],
          "category": "castle", "style": "medieval",
          "secondary_masses": [
              {"type": "tower", "position": "corner-nw"},
              {"type": "tower", "position": "corner-ne"},
              {"type": "keep", "position": "center", "size": "large"},
          ]}
    n0 = len(doc["voxels"])
    doc2, counts = massing.add_masses(json.loads(json.dumps(doc)), gi)
    assert counts["masses_built"] == 3, f"esperadas 3 masas, {counts}"
    assert len(doc2["voxels"]) > n0, "las masas no añadieron voxels"
    assert doc2["bounding_box"]["size"][1] > 10, "las masas no suben"
    _polished, rep = aligner.align(doc2, run_llm=False, log=lambda *a, **k: None)
    assert rep["deterministic"].get("floaters_removed", 0) == 0, \
        f"las masas crearon flotantes: {rep['deterministic']}"
    print(f"massing: {counts['by_type']} +{counts['voxels']} voxels floaters=0")


def test_no_masses_when_design_does_not_ask():
    # sin secondary_masses → NO se añade nada (lo normal en edificios simples)
    doc = _box_doc(10, 6, 10)
    for gi in ({"building_aabb": [0, 0, 0, 10, 6, 10], "category": "castle"},
               {"building_aabb": [0, 0, 0, 30, 10, 30], "category": "monument",
                "secondary_masses": []}):
        _doc2, counts = massing.add_masses(json.loads(json.dumps(doc)), gi)
        assert counts["masses_built"] == 0, "no debe añadir masas sin pedirlas el diseño"


if __name__ == "__main__":
    test_design_driven_masses_no_floaters()
    test_no_masses_when_design_does_not_ask()
    print("OK")
