"""Validación del enriquecimiento de interior determinista (palanca B).

Comprueba que `_enrich_room_ops`:
  * produce ornamento (faroles + friso),
  * NUNCA pisa una celda reservada (puerta/ventana/escalera),
  * al voxelizar+alinear una sala enriquecida NO aparecen flotantes
    (coherencia intacta) y SÍ aumenta la iluminación/detalle.
"""
from __future__ import annotations

import json

from pipeline.agents import room_agent, voxelizer, aligner, aggregator


def _master(ops, gen_id):
    composer_ops = [aggregator._strip_envelope_tags(o) for o in ops]
    return {"id": gen_id, "style": "medieval", "category": "residential",
            "ops": composer_ops,
            "bot_decomposition": {"building": {"storeys": []}},
            "connectors": {"doors": [], "windows": [], "staircases": []},
            "warnings": []}


def test_enrichment_respects_reserved():
    room = {"id": "r1", "role": "bedroom", "aabb": [0, 0, 0, 8, 5, 8]}
    reserved = {(1, 2, 1), (4, 4, 0), (4, 4, 7)}    # farol + dos de friso
    ops = room_agent._enrich_room_ops(room, reserved)
    assert ops, "no se generó ornamento"
    placed = {tuple(o["at"]) for o in ops}
    assert reserved.isdisjoint(placed), "el enriquecimiento pisó celdas reservadas"
    assert any(o["block"] == "@lantern" for o in ops), "faltan faroles"
    assert any(o["block"] == "@accent" for o in ops), "falta friso"


def test_enriched_room_has_no_floaters(tmp_path):
    room = {"id": "r1", "role": "bedroom", "aabb": [0, 0, 0, 8, 5, 8]}
    # fallback sin skills → fill_hollow + enriquecimiento (sin LLM)
    plan = room_agent._fallback_room_plan(room, "medieval", candidates=[])

    path = voxelizer.voxelize(_master(plan["ops"], "enrich-test"), out_dir=tmp_path)
    doc = json.loads(path.read_text())
    _polished, report = aligner.align(doc, master_plan=_master(plan["ops"], "x"),
                                      global_intent=None, run_llm=False,
                                      log=lambda *a, **k: None)
    floaters = report["deterministic"].get("floaters_removed", 0)
    assert floaters == 0, f"el interior enriquecido creó flotantes: {floaters}"

    bares = {b.split("[")[0].split(":")[-1] for b in doc["block_palette"].values()}
    assert "lantern" in bares, "no se materializaron faroles"
    print(f"enriched bedroom: voxels={len(doc['voxels'])} "
          f"palette={sorted(bares)} floaters={floaters} "
          f"enrich_ops={len(room_agent._enrich_room_ops(room, set()))}")


if __name__ == "__main__":
    import tempfile
    from pathlib import Path
    test_enrichment_respects_reserved()
    with tempfile.TemporaryDirectory() as td:
        test_enriched_room_has_no_floaters(Path(td))
    print("OK")
