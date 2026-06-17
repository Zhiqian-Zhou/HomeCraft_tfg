"""Validación de la capa lush del exterior (palanca D, siguiendo la lógica
del exterior_agent: decoración determinista del apron).

Comprueba que el fallback determinista produce un apron poblado (árboles,
flores, SETO perimetral, FAROLAS, BANCOS) y que al voxelizar+alinear NO
aparecen flotantes (coherencia intacta).
"""
from __future__ import annotations

import json

from pipeline.agents import exterior_agent, voxelizer, aligner, aggregator


def _master(ops, gen_id):
    composer_ops = [aggregator._strip_envelope_tags(o) for o in ops]
    return {"id": gen_id, "style": "medieval", "category": "residential",
            "ops": composer_ops,
            "bot_decomposition": {"building": {"storeys": []}},
            "connectors": {"doors": [], "windows": [], "staircases": []},
            "warnings": []}


def _design_intent():
    return {
        "style": "medieval",
        "site_aabb":     [0, 0, 0, 16, 6, 14],
        "building_aabb": [4, 0, 4, 12, 6, 10],
        "exterior": {"features": []},      # sin skills → solo apron determinista
        "connectors": {"doors": [
            {"id": "d1", "between": ["outside", "entry-1"],
             "at": [8, 1, 4], "facing": "n"}
        ], "windows": [], "staircases": []},
    }


def test_lush_apron_is_populated():
    di = _design_intent()
    plan = exterior_agent._fallback_plan(di)
    blocks = {str(o.get("block", "")) for o in plan["ops"]}
    bare = {b.split("[")[0].split(":")[-1] for b in blocks}
    # árbol (log + leaves), seto (leaves), farola (fence + lantern), banco (stairs)
    assert "lantern" in bare, "faltan farolas"
    assert any("fence" in b for b in bare), "faltan postes de farola"
    assert any("leaves" in b for b in bare), "falta seto/árboles"
    assert any("stairs" in b for b in bare), "faltan bancos"
    assert any("flower" not in b for b in bare)  # sanity


def test_lush_apron_no_floaters(tmp_path):
    di = _design_intent()
    plan = exterior_agent._fallback_plan(di)
    master = _master(plan["ops"], "lush-test")
    path = voxelizer.voxelize(master, out_dir=tmp_path)
    doc = json.loads(path.read_text())
    _polished, report = aligner.align(doc, master_plan=master,
                                      global_intent=None, run_llm=False,
                                      log=lambda *a, **k: None)
    floaters = report["deterministic"].get("floaters_removed", 0)
    assert floaters == 0, f"el apron lush creó flotantes: {floaters}"
    print(f"lush apron: voxels={len(doc['voxels'])} ops={len(plan['ops'])} "
          f"floaters={floaters}")


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    test_lush_apron_is_populated()
    with tempfile.TemporaryDirectory() as td:
        test_lush_apron_no_floaters(Path(td))
    print("OK")
