"""Validación de coherencia del trim_decorator (palanca A).

Corre la cadena DETERMINISTA completa sobre intents reales de generaciones
existentes:  architecture_planner → trim_decorator → voxelizer → aligner.

Verifica las invariantes de coherencia:
  * el trim AÑADE bloques (más elaboración),
  * el trim NO crea flotantes nuevos (aligner.floaters_removed no sube vs
    baseline) → no rompe la coherencia estructural,
  * la paleta no se infla con bloques basura.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.agents import (architecture_planner, trim_decorator, aligner,
                             voxelizer, aggregator)

REPO = Path(__file__).resolve().parents[1]
GENS = REPO / "scratch" / "generations"

# Intents reales reutilizables (global_intent.json + floors/*.json).
_CANDIDATES = [
    "demo-1-mansion-victoriana",
    "demo-4-castillo-gotico",
    "castillo-medieval-v2",
    "biblioteca-victoriana-v3",
]


def _load_case(name: str):
    d = GENS / name
    gi = json.loads((d / "global_intent.json").read_text())
    floors = sorted((d / "floors").glob("floor_*.json"))
    floor_plans = [json.loads(f.read_text()) for f in floors]
    return gi, floor_plans


def _door_cells(name: str) -> frozenset:
    cp_path = GENS / name / "connector_plan.json"
    if not cp_path.exists():
        return frozenset()
    cp = json.loads(cp_path.read_text())
    cells = set()
    for door in (cp.get("doors") or []):
        at = (door.get("validated") or {}).get("at")
        if at and len(at) == 3:
            for dx in (-2, -1, 0, 1, 2):
                for dz in (-2, -1, 0, 1, 2):
                    cells.add((at[0] + dx, at[1], at[2] + dz))
                    cells.add((at[0] + dx, at[1] + 1, at[2] + dz))
    return frozenset(cells)


def _master(gi: dict, ops: list[dict], gen_id: str) -> dict:
    # Mapea las ops de arquitectura (wall_block/…) al esquema del composer,
    # igual que hace el aggregator en el pipeline real.
    composer_ops = [aggregator._strip_envelope_tags(o) for o in ops]
    return {
        "id": gen_id,
        "style": gi.get("style", "medieval"),
        "category": gi.get("category", "residential"),
        "ops": composer_ops,
        "bot_decomposition": {"building": {"storeys": []}},
        "connectors": {"doors": [], "windows": [], "staircases": []},
        "warnings": [],
    }


def _align_floaters(doc: dict, master: dict):
    _polished, report = aligner.align(doc, master_plan=master,
                                      global_intent=None, run_llm=False,
                                      log=lambda *a, **k: None)
    return report["deterministic"].get("floaters_removed", 0)


def _available_cases():
    return [n for n in _CANDIDATES
            if (GENS / n / "global_intent.json").exists()
            and (GENS / n / "floors").is_dir()]


@pytest.mark.parametrize("name", _available_cases() or ["__none__"])
def test_trim_adds_detail_without_floaters(name, tmp_path):
    if name == "__none__":
        pytest.skip("no hay generaciones intermedias para validar")
    gi, floor_plans = _load_case(name)
    ap = architecture_planner.plan_architecture_v4(gi, floor_plans)
    door_cells = _door_cells(name)
    master = _master(gi, list(ap["ops"]), f"trimtest-{name}")

    # Baseline: voxelizar + medir flotantes.
    base_path = voxelizer.voxelize(master, out_dir=tmp_path)
    base_doc = json.loads(base_path.read_text())
    base_v = len(base_doc["voxels"])
    base_pal = len(base_doc["block_palette"])
    base_fl = _align_floaters(json.loads(json.dumps(base_doc)), master)

    # Con trim: decorar el doc voxelizado.
    trim_doc, counts = trim_decorator.decorate_doc(
        json.loads(json.dumps(base_doc)), gi, door_cells=door_cells)
    trim_v = len(trim_doc["voxels"])
    trim_pal = len(trim_doc["block_palette"])
    trim_fl = _align_floaters(json.loads(json.dumps(trim_doc)), master)

    # 1) El trim AÑADE elaboración (recolor + alero).
    assert sum(counts.values()) > 0, f"{name}: el trim no decoró nada"
    assert trim_v >= base_v, f"{name}: el trim perdió bloques ({base_v}→{trim_v})"
    # 2) NO crea flotantes nuevos → no rompe coherencia estructural.
    assert trim_fl <= base_fl, (
        f"{name}: trim creó flotantes ({base_fl}→{trim_fl})")
    # 3) La paleta no se descontrola.
    assert trim_pal <= base_pal + 4, (
        f"{name}: paleta inflada ({base_pal}→{trim_pal})")

    print(f"{name}: voxels {base_v}→{trim_v} (+{trim_v-base_v})  "
          f"floaters {base_fl}→{trim_fl}  palette {base_pal}→{trim_pal}  "
          f"counts={counts}")


if __name__ == "__main__":
    cases = _available_cases()
    print(f"casos disponibles: {cases}")
    for nm in cases:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            try:
                test_trim_adds_detail_without_floaters(nm, Path(td))
            except AssertionError as e:
                print(f"FALLO {nm}: {e}")
