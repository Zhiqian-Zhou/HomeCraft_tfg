"""End-to-end driver: text prompt → ReferenceBuilding JSON in scratch/generations/.

    python3 -m pipeline.agents.run "a small medieval cottage with a kitchen and a bedroom"
    python3 -m pipeline.agents.run --gen-id my-test "a tall fantasy wizard tower"

Saves all intermediate JSONs under scratch/generations/<gen_id>/:
    design_intent.json
    rooms/<room_id>.plan.json
    exterior.plan.json
    master_plan.json
    <gen_id>.json                ← final ReferenceBuilding, openable in viewer

Pre-requisite:
    export OPENROUTER_API_KEY=sk-or-v1-...

Viewer deep-link after generation:
    http://localhost:8000/viewer/?file=../scratch/generations/<gen_id>.json
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import (main_agent, room_agent, exterior_agent, aggregator, voxelizer,
                prompt_expander, evaluator, aligner, coherence_agent,
                global_designer, space_planner, architecture_planner,
                connector_planner,
                floor_planner, inter_floor_validator, connector_planner_v4,
                envelope_decorator, physical_fixer,
                typology_chooser, typology_injector, trim_decorator, massing,
                envelope_closer, furnish)
from .footprint import footprint_for
from .llm import call_llm_json
from ._fallback import fallback_enabled

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GENS = REPO_ROOT / "scratch" / "generations"


def _new_gen_id() -> str:
    return "gen-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _save_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def run(prompt: str, *, gen_id: Optional[str] = None,
        parallel_rooms: bool = True, verbose: bool = True,
        pipeline_version: str = "v2.6",
        out_base_dir: Optional[Path] = None) -> Path:
    """Generate a building end-to-end.

    pipeline_version:
        "v2.6": single main_agent LLM call producing design_intent.
                (Current default, kept for back-compat and iter05/iter06 replay.)
        "v3":   four sub-agents (global_designer → space_planner →
                architecture_planner → connector_planner) replacing main_agent.
                Connectors validated geometrically; envelope built
                deterministically; no y=0 door bugs.

    Returns the absolute path of the final ReferenceBuilding JSON.
    """
    if pipeline_version == "v4":
        return _run_v4(prompt, gen_id=gen_id, parallel_rooms=parallel_rooms,
                        verbose=verbose, out_base_dir=out_base_dir)
    if pipeline_version == "v3":
        return _run_v3(prompt, gen_id=gen_id, parallel_rooms=parallel_rooms,
                        verbose=verbose)
    # else: fall through to v2.6
    gen_id = (gen_id or _new_gen_id()).lower()
    workdir = GENS / gen_id
    rooms_dir = workdir / "rooms"
    workdir.mkdir(parents=True, exist_ok=True)
    rooms_dir.mkdir(parents=True, exist_ok=True)

    log = (lambda *a, **k: print(*a, **k, flush=True)) if verbose else (lambda *a, **k: None)

    log(f"[run] gen_id={gen_id}")
    log(f"[run] prompt={prompt!r}")

    # ── Stage 0: prompt expansion ──
    t = time.time()
    log("[run] 0/6  prompt_expander ...")
    expanded = prompt_expander.expand(prompt)
    _save_json(expanded, workdir / "expanded_prompt.json")
    log(f"       style={expanded.get('implied_style')!r}  "
        f"size={expanded.get('implied_size_bucket')!r}  "
        f"rooms={len(expanded.get('implied_rooms', []))}  "
        f"({time.time()-t:.1f}s)")

    # ── Stage 1: main agent (now fed the expanded description + hints) ──
    t = time.time()
    log("[run] 1/6  design_intent (main_agent) ...")
    di = main_agent.design_intent(expanded["expanded_description"], hints=expanded)
    # Preserve the original raw prompt in design_intent so downstream traceability works
    di.setdefault("prompt", prompt)
    _save_json(di, workdir / "design_intent.json")
    log(f"       style={di['style']!r}  rooms={len(di['rooms'])}  "
        f"doors={len(di['connectors']['doors'])}  "
        f"windows={len(di['connectors']['windows'])}  "
        f"staircases={len(di['connectors']['staircases'])}  "
        f"({time.time()-t:.1f}s)")

    # ── Stage 2: room agents (parallel I/O on LLM) ──
    t = time.time()
    log(f"[run] 2/6  room agents x{len(di['rooms'])} {'(parallel)' if parallel_rooms else '(serial)'} ...")
    room_plans = _plan_rooms(di, parallel=parallel_rooms, log=log)
    for rp in room_plans:
        _save_json(rp, rooms_dir / f"{rp['room_id']}.plan.json")
    log(f"       wrote {len(room_plans)} room plans  ({time.time()-t:.1f}s)")

    # ── Stage 3: exterior agent ──
    t = time.time()
    log("[run] 3/6  exterior_agent ...")
    if di.get("exterior", {}).get("features") or di.get("site_aabb"):
        ext = exterior_agent.plan_exterior(di)
        _save_json(ext, workdir / "exterior.plan.json")
        log(f"       ops={len(ext['ops'])}  ({time.time()-t:.1f}s)")
    else:
        ext = None
        log(f"       skipped (no exterior features) ({time.time()-t:.1f}s)")

    # ── Stage 4: aggregator (deterministic) ──
    t = time.time()
    log("[run] 4/6  aggregator ...")
    master = aggregator.aggregate(di, room_plans, ext, gen_id=gen_id)
    _save_json(master, workdir / "master_plan.json")
    log(f"       n_ops={len(master['ops'])}  warnings={len(master['warnings'])}  ({time.time()-t:.1f}s)")
    for w in master["warnings"]:
        log(f"       ⚠  {w}")

    # ── Stage 5: voxelizer (deterministic) ──
    t = time.time()
    log("[run] 5/6  voxelizer ...")
    final_path = voxelizer.voxelize(master, out_dir=GENS)
    doc = json.loads(final_path.read_text())
    log(f"       voxels={len(doc['voxels'])}  palette={len(doc['block_palette'])}  "
        f"size={doc['bounding_box']['size']}  ({time.time()-t:.1f}s)")

    # ── Stage 6: evaluator (8 physical + 10 Alexander + LLM critique) ──
    t = time.time()
    log("[run] 6/6  evaluator ...")
    try:
        report = evaluator.evaluate(doc, design_intent=di, master_plan=master,
                                      run_critique=True)
        _save_json(report, workdir / "evaluation_report.json")
        # Sibling file the viewer fetches (viewer/js/app.js::reportPathFor)
        _save_json(report, GENS / f"{gen_id}.evaluation.json")
        c = report["composite"]
        log(f"       overall={c.get('overall')}  physical={c.get('physical_total')}  "
            f"alexander={c.get('alexander_total')}  ({time.time()-t:.1f}s)")
    except Exception as e:
        log(f"       evaluator skipped (error: {e})")

    log(f"[run] OK -> {final_path.relative_to(REPO_ROOT)}")
    log(f"[run] open with viewer:")
    log(f"       python3 -m http.server 8000")
    log(f"       http://localhost:8000/viewer/?file=../scratch/generations/{gen_id}.json")
    return final_path


def _plan_rooms(di, *, parallel: bool, log) -> list[dict]:
    """Call room_agent.plan_room for every room, optionally in parallel.

    NO deterministic room fallback (fallback_on_failure=False). If the LLM
    cannot design a room after its retries, that room's decoration is DROPPED
    (logged); the room still exists structurally via the architecture envelope.
    A canned plan is never substituted (it would contaminate the metrics).
    """
    rooms = di["rooms"]
    style = di["style"]

    def _safe_plan(i: int, r: dict) -> Optional[dict]:
        # fallback_on_failure follows the ablation toggle. OFF (default): NO
        # deterministic room plan — if the LLM cannot design this room after its
        # retries, DROP its decoration and log loudly (never substitute a canned
        # plan, which would contaminate the metrics). ON: room_agent returns its
        # canned plan instead of raising.
        try:
            p = room_agent.plan_room(r, style, di, fallback_on_failure=fallback_enabled())
            log(f"       ✓ room[{i}] {r['id']}")
            return p
        except Exception as e:  # noqa: BLE001
            log(f"       ✗ room[{i}] {r['id']}: LLM failed ({e}) — "
                f"{'kept(fallback)' if fallback_enabled() else 'DROPPED (no fallback)'}")
            return None

    if not parallel or len(rooms) <= 1:
        return [p for p in (_safe_plan(i, r) for i, r in enumerate(rooms))
                if p is not None]
    plans: list[Optional[dict]] = [None] * len(rooms)
    with cf.ThreadPoolExecutor(max_workers=min(16, len(rooms))) as pool:
        futs = {pool.submit(_safe_plan, i, r): i for i, r in enumerate(rooms)}
        for fut in cf.as_completed(futs):
            plans[futs[fut]] = fut.result()
    return [p for p in plans if p is not None]


def _run_v3(prompt: str, *, gen_id: Optional[str] = None,
             parallel_rooms: bool = True, verbose: bool = True) -> Path:
    """Pipeline v3 orchestrator: 4 sub-agents replace main_agent.

    Stages:
      0. prompt_expander (shared with v2.6)
      1a. global_designer  → global_intent.json
      1b. space_planner    → space_plan.json
      1c. architecture_planner (deterministic) → architecture_plan.json
      1d. connector_planner (LLM + validator)  → connector_plan.json
      2. room_agents (existing skills; envelope they paint is redundant
         but harmless thanks to composer later-wins)
      3. exterior_agent (shared)
      4. aggregator.aggregate_v3 (consumes 4 streams + room_plans)
      5. voxelizer (deterministic)
      6. evaluator (deterministic + LLM critique)
    """
    gen_id = (gen_id or _new_gen_id()).lower()
    workdir = GENS / gen_id
    rooms_dir = workdir / "rooms"
    workdir.mkdir(parents=True, exist_ok=True)
    rooms_dir.mkdir(parents=True, exist_ok=True)

    log = (lambda *a, **k: print(*a, **k, flush=True)) if verbose else (lambda *a, **k: None)

    log(f"[run-v3] gen_id={gen_id}")
    log(f"[run-v3] prompt={prompt!r}")

    # ── Stage 0: prompt expansion ──
    t = time.time()
    log("[run-v3] 0/8  prompt_expander ...")
    expanded = prompt_expander.expand(prompt)
    _save_json(expanded, workdir / "expanded_prompt.json")
    log(f"       style={expanded.get('implied_style')!r}  "
        f"size={expanded.get('implied_size_bucket')!r}  "
        f"({time.time()-t:.1f}s)")

    # ── Stage 1a: global_designer (LLM) ──
    t = time.time()
    log("[run-v3] 1/8  global_designer ...")
    gi = global_designer.design_global(expanded["expanded_description"],
                                          hints=expanded)
    gi.setdefault("prompt", prompt)
    _save_json(gi, workdir / "global_intent.json")
    log(f"       style={gi['style']!r}  floors={len(gi['floors'])}  "
        f"({time.time()-t:.1f}s)")

    # ── Stage 1b: space_planner (LLM) ──
    t = time.time()
    log("[run-v3] 2/8  space_planner ...")
    sp = space_planner.plan_spaces(gi)
    _save_json(sp, workdir / "space_plan.json")
    log(f"       rooms={len(sp['rooms'])}  "
        f"edges={len(sp['adjacency_graph'])}  ({time.time()-t:.1f}s)")

    # ── Stage 1c: architecture_planner (deterministic) ──
    t = time.time()
    log("[run-v3] 3/8  architecture_planner (deterministic) ...")
    ap = architecture_planner.plan_architecture(gi, sp)
    _save_json(ap, workdir / "architecture_plan.json")
    log(f"       envelope_ops={len(ap['ops'])}  "
        f"materials={len(ap['materials_used'])}  ({time.time()-t:.1f}s)")

    # ── Stage 1d: connector_planner (LLM + validator) ──
    t = time.time()
    log("[run-v3] 4/8  connector_planner ...")
    cp = connector_planner.plan_connectors(gi, sp)
    _save_json(cp, workdir / "connector_plan.json")
    summary = cp.get("summary", {})
    log(f"       doors={len(cp['doors'])}  windows={len(cp['windows'])}  "
        f"staircases={len(cp['staircases'])}  "
        f"dropped={summary.get('dropped', 0)}  "
        f"auto_fixed={summary.get('auto_fixed', 0)}  "
        f"({time.time()-t:.1f}s)")

    # ── Stage 2: room agents (decoration; envelope is redundant) ──
    # Build a v2.6-shaped design_intent on the fly for room_agent compat.
    di_compat = aggregator._synth_design_intent(gi, sp, cp)
    di_compat["building_aabb"] = gi.get("building_aabb", gi["site_aabb"])
    di_compat["site_aabb"] = gi["site_aabb"]
    di_compat["exterior"] = {"features": []}
    di_compat["floors"] = gi["floors"]

    t = time.time()
    log(f"[run-v3] 5/8  room_agents x{len(sp['rooms'])} ...")
    room_plans = _plan_rooms(di_compat, parallel=parallel_rooms, log=log)
    for rp in room_plans:
        _save_json(rp, rooms_dir / f"{rp['room_id']}.plan.json")
    log(f"       wrote {len(room_plans)} room plans  ({time.time()-t:.1f}s)")

    # ── Stage 3: exterior_agent ──
    t = time.time()
    log("[run-v3] 6/8  exterior_agent ...")
    try:
        ext = exterior_agent.plan_exterior(di_compat)
        _save_json(ext, workdir / "exterior.plan.json")
        log(f"       ops={len(ext['ops'])}  ({time.time()-t:.1f}s)")
    except Exception as e:
        ext = None
        log(f"       skipped ({e}) ({time.time()-t:.1f}s)")

    # ── Stage 4: aggregator v3 ──
    t = time.time()
    log("[run-v3] 7/8  aggregator (v3, 4-stream) ...")
    master = aggregator.aggregate_v3(gi, sp, ap, cp, room_plans, ext,
                                       gen_id=gen_id)
    _save_json(master, workdir / "master_plan.json")
    log(f"       n_ops={len(master['ops'])}  "
        f"warnings={len(master['warnings'])}  ({time.time()-t:.1f}s)")
    for w in master["warnings"][:5]:
        log(f"       ⚠  {w}")

    # ── Stage 5: voxelizer ──
    t = time.time()
    log("[run-v3] 8/8  voxelizer + evaluator ...")
    final_path = voxelizer.voxelize(master, out_dir=GENS)
    doc = json.loads(final_path.read_text())

    # ── Stage 6: evaluator ──
    try:
        # Pass di_compat as design_intent for back-compat with evaluator
        report = evaluator.evaluate(doc, design_intent=di_compat,
                                      master_plan=master, run_critique=True)
        _save_json(report, workdir / "evaluation_report.json")
        # Sibling file the viewer fetches (viewer/js/app.js::reportPathFor)
        _save_json(report, GENS / f"{gen_id}.evaluation.json")
        c = report["composite"]
        log(f"       voxels={len(doc['voxels'])}  palette={len(doc['block_palette'])}")
        log(f"       overall={c.get('overall')}  "
            f"physical={c.get('physical_total')}  "
            f"alexander={c.get('alexander_total')}  ({time.time()-t:.1f}s)")
    except Exception as e:
        log(f"       evaluator skipped ({e})")

    log(f"[run-v3] OK -> {final_path.relative_to(REPO_ROOT)}")
    log(f"[run-v3] viewer: http://localhost:8000/viewer/?file=../scratch/generations/{gen_id}.json")
    return final_path


def _floor_plans_to_v3_space_plan(floor_plans: list[dict]) -> dict:
    """Aggregate v4 floor_plans into a v3-shape space_plan (rooms +
    adjacency_graph) so the downstream v3 aggregator / room_agent /
    exterior_agent see a familiar input."""
    rooms: list[dict] = []
    edges: list[dict] = []
    for fp in floor_plans:
        rooms.extend(fp.get("rooms") or [])
        edges.extend(fp.get("adjacency_graph") or [])
    return {
        "schema_version": "1.0",
        "rooms": rooms,
        "adjacency_graph": edges,
    }


def _v4_global_intent_to_v3(gi_v4: dict, prompt: str) -> dict:
    """Adapt global_intent_v4 → v3 shape (renames expanded_description→
    prompt, drops v4-only fields the v3 aggregator doesn't read)."""
    out = dict(gi_v4)
    out["schema_version"] = "1.0"
    out["prompt"] = out.get("expanded_description") or prompt
    # v3 aggregator looks at common fields; v4-only keys are harmless if
    # left in (additional_properties is not strictly enforced downstream
    # of the schema_utils boundary).
    return out


def _run_v4(prompt: str, *, gen_id: Optional[str] = None,
             parallel_rooms: bool = True, verbose: bool = True,
             out_base_dir: Optional[Path] = None) -> Path:
    """Pipeline v4 orchestrator: silhouette + per-floor + skill_category.

    Stages:
      0.  prompt_expander.expand_v4    → expanded_prompt_v4.json
      1a. global_designer.design_global_v4  (+ retrieve global_silhouette)
      1b. space_planner.plan_spaces_v4 (+ retrieve floor_layout & connector)
      1c. floor_planner.plan_floors_parallel × N (one LLM per floor)
      1d. inter_floor_validator.validate (stair alignment, id collisions)
      1e. architecture_planner.plan_architecture_v4 (deterministic)
      1f. connector_planner_v4.materialize_connectors_v4 (no LLM)
      2.  room_agents (v4 filter; envelope is redundant but harmless)
      3.  exterior_agent (shared)
      4.  aggregator.aggregate_v3 (reused via v4→v3 shim)
      5.  voxelizer (deterministic)
      6.  evaluator (deterministic + LLM critique)
    """
    gen_id = (gen_id or _new_gen_id()).lower()
    base_dir = Path(out_base_dir) if out_base_dir else GENS
    workdir = base_dir / gen_id
    rooms_dir = workdir / "rooms"
    floors_dir = workdir / "floors"
    workdir.mkdir(parents=True, exist_ok=True)
    rooms_dir.mkdir(parents=True, exist_ok=True)
    floors_dir.mkdir(parents=True, exist_ok=True)

    log = (lambda *a, **k: print(*a, **k, flush=True)) if verbose else (lambda *a, **k: None)

    # Coste de generación (tokens + tiempo) para comparar LLMs: reset del
    # contador y cronómetro de pared al ARRANCAR la generación.
    from . import llm as _llm
    _llm.reset_usage()
    _gen_t0 = time.time()

    log(f"[run-v4] gen_id={gen_id}  out_base={base_dir}")
    log(f"[run-v4] prompt={prompt!r}")

    # ── Stage 0: prompt_expander v4 ──
    t = time.time()
    log("[run-v4] 0/9  prompt_expander (v4) ...")
    expanded = prompt_expander.expand_v4(prompt)
    _save_json(expanded, workdir / "expanded_prompt.json")
    log(f"       chars={len(expanded.get('expanded_description', ''))}"
        f"  ({time.time()-t:.1f}s)")

    # ── Stage 1a: global_designer v4 (LLM + silhouette retrieval) ──
    t = time.time()
    log("[run-v4] 1/9  global_designer (v4 + silhouette) ...")
    gi = global_designer.design_global_v4(
        expanded["expanded_description"], original_prompt=prompt)
    # Thread the user's intent DOWNSTREAM so space/floor/room agents design FOR
    # the prompt instead of blind to it (root fix for prompt-coherence). These
    # are soft guidance fields read by the per-stage prompts.
    gi["user_prompt"] = prompt
    gi["expanded_description"] = expanded.get("expanded_description", "")
    gi["requested"] = prompt_expander.parse_requests(prompt)
    log(f"       silhouette={gi['silhouette_id']!r}  style={gi['style']!r}"
        f"  floors={len(gi['floors'])}  req={gi['requested']}  ({time.time()-t:.1f}s)")

    # ── Stage 1a-bis: typology_chooser (Fase 4 — typology catalog selection) ──
    # Picks one tower / roof / window / garden typology that fits the style +
    # silhouette + scale. Stored in gi["selected_typologies"]; the
    # typology_injector at Stage 1f-bis turns these picks into `kind="typology"`
    # ops that the voxelizer materializes via
    # `pipeline.skills.typologies.get_typology`.
    #
    # A/B switch — set HOMECRAFT_CATALOG_OFF=1 to disable the chooser (and
    # implicitly the injector, which becomes a no-op without selections).
    # Useful for gym A/B comparisons: same pipeline, branch ON vs branch OFF.
    catalog_off = os.environ.get("HOMECRAFT_CATALOG_OFF", "").strip() not in ("", "0", "false")
    t = time.time()
    if catalog_off:
        log("[run-v4] 1b/9 typology_chooser SKIPPED "
            "(HOMECRAFT_CATALOG_OFF=1)")
        gi["selected_typologies"] = {}
    else:
        log("[run-v4] 1b/9 typology_chooser ...")
        try:
            gi["selected_typologies"] = typology_chooser.choose_typologies(
                gi, llm_caller=call_llm_json, k_parallel=1)
            log(f"       picks={gi['selected_typologies']}"
                f"  ({time.time()-t:.1f}s)")
        except Exception as e:  # noqa: BLE001 — never break the build on chooser
            log(f"       typology_chooser skipped ({e})")
            gi["selected_typologies"] = {}
    _save_json(gi, workdir / "global_intent.json")

    # ── Stage 1b: space_planner v4 (LLM + floor_layout + connector_template) ──
    t = time.time()
    log("[run-v4] 2/9  space_planner (v4 floor-skeleton) ...")
    sp = space_planner.plan_spaces_v4(gi)
    _save_json(sp, workdir / "space_plan.json")
    log(f"       layouts={sp['floor_layout_id_per_floor']}"
        f"  connectors={len(sp['connector_templates_used'])}"
        f"  ({time.time()-t:.1f}s)")

    # ── Stage 1c: floor_planner v4 (parallel, one LLM per floor) ──
    t = time.time()
    log(f"[run-v4] 3/9  floor_planner x{len(gi['floors'])} (parallel) ...")
    floor_plans = floor_planner.plan_floors_parallel(
        global_intent=gi, space_plan=sp)
    for fp in floor_plans:
        _save_json(fp, floors_dir / f"floor_{fp['floor_index']}.json")
    log(f"       wrote {len(floor_plans)} floor plans  ({time.time()-t:.1f}s)")

    # ── Stage 1d: inter_floor_validator (deterministic) ──
    t = time.time()
    log("[run-v4] 4/9  inter_floor_validator ...")
    floor_plans, fix_report = inter_floor_validator.validate(
        global_intent=gi, space_plan=sp, floor_plans=floor_plans)
    if fix_report.total:
        log(f"       fixes: stairs_snapped={len(fix_report.snapped_stairs)}"
            f"  outside_edges_added={len(fix_report.synthesized_outside_edges)}"
            f"  ids_renamed={len(fix_report.renamed_room_ids)}")
    log(f"       ({time.time()-t:.1f}s)")

    # ── Stage 1d.5: coherence_agent — cross-component fit correction ──
    # Rooms were planned in isolation; reconcile them against their neighbours
    # (storey below/above, same-floor) so floors stack/align and nothing pokes
    # out of the footprint, BEFORE the envelope is built on top.
    t = time.time()
    log("[run-v4] 4b/9 coherence_agent (cross-component fit) ...")
    try:
        floor_plans, coh_report = coherence_agent.reconcile(
            gi, floor_plans, run_llm=True, log=log)
        for fp in floor_plans:
            _save_json(fp, floors_dir / f"floor_{fp['floor_index']}.json")
        _save_json(coh_report, workdir / "coherence_report.json")
        log(f"       rooms_adjusted={coh_report['deterministic']['rooms_adjusted']}"
            f"  coherent={coh_report['coherent']}  ({time.time()-t:.1f}s)")
    except Exception as e:  # noqa: BLE001 — coherence must never break a build
        log(f"       coherence_agent skipped ({e})")

    # ── Stage 1e: architecture_planner v4 (deterministic) ──
    t = time.time()
    log("[run-v4] 5/9  architecture_planner (v4 deterministic) ...")
    ap_v4 = architecture_planner.plan_architecture_v4(gi, floor_plans)
    log(f"       ops={len(ap_v4['ops'])}"
        f"  wall_fittings={len(ap_v4.get('wall_fittings_applied') or [])}"
        f"  ({time.time()-t:.1f}s)")

    # ── Stage 1f: connector_planner_v4 (deterministic) ──
    t = time.time()
    log("[run-v4] 6/9  connector_planner_v4 (materialize, no LLM) ...")
    cp_wrap = connector_planner_v4.materialize_connectors_v4(
        gi, sp, floor_plans)
    cp = cp_wrap["connector_plan"]
    _save_json(cp, workdir / "connector_plan.json")
    _save_json(cp_wrap["connector_templates_realized"],
                workdir / "connector_templates_realized.json")
    log(f"       doors={len(cp['doors'])}  staircases={len(cp['staircases'])}"
        f"  realized={len(cp_wrap['connector_templates_realized'])}"
        f"  ({time.time()-t:.1f}s)")

    # ── Stage 1f-bis: typology_injector (Fases 4.5 + extended) ──
    # Translates gi.selected_typologies into concrete `kind="typology"` ops
    # appended to the architecture plan. Runs AFTER connector_planner so it
    # has access to validated door/window slots (needed for window typology
    # placement). Composer "later wins" ensures the typology geometry
    # overrides the deterministic envelope at the overlapping cells. Safe:
    # failures degrade silently to the deterministic envelope.
    try:
        ap_v4 = typology_injector.inject(global_intent=gi,
                                          architecture_plan=ap_v4,
                                          connector_plan=cp,
                                          log=log)
    except Exception as e:  # noqa: BLE001 — never break the build on inject
        log(f"       typology_injector skipped ({e})")
    _save_json(ap_v4, workdir / "architecture_plan.json")

    # ── Stage 1g: envelope_decorator (LLM) — emits voxel ops for
    # sheltering_roof, light_on_two_sides, light_coverage.
    # Per gym constraint: variety-affecting ops come from LLM, not from
    # deterministic stages. No fallback. Skips door-coordinate cells so
    # the connector_validator's carve_ops aren't overwritten (which
    # broke voxel_connectivity in iters 5-10).
    t = time.time()
    log("[run-v4] 7/9  envelope_decorator (LLM, gym fix) ...")
    rooms_all = []
    for fp in floor_plans:
        rooms_all.extend(fp.get("rooms") or [])
    try:
        env_plan = envelope_decorator.decorate_envelope(
            global_intent=gi, rooms=rooms_all, connector_plan=cp)
    except Exception as e:  # noqa: BLE001
        # Envelope decoration is OPTIONAL polish (cosmetic ops), not core to a
        # scorable building. A persistent LLM failure here (common with small
        # backbones) must never abort an otherwise complete build, in EITHER
        # fallback mode: skip the decoration and continue. The on/off ablation
        # then tests the deterministic GEOMETRY nets (BSP floor + post-voxel
        # repairs), not whether a cosmetic stage aborts.
        log(f"       envelope_decorator skipped ({str(e)[:80]})")
        env_plan = {"role": "exterior", "room_id": "exterior", "ops": []}
    # Strip env ops at door-adjacent cells (door.at ± facing). The
    # carve_ops at those cells must remain air for BFS connectivity.
    door_blocked = set()
    for d in (cp.get("doors") or []):
        v = d.get("validated") or {}
        at = v.get("at")
        if at and len(at) == 3:
            for dx in (-2, -1, 0, 1, 2):
                for dz in (-2, -1, 0, 1, 2):
                    door_blocked.add((at[0] + dx, at[1], at[2] + dz))
                    door_blocked.add((at[0] + dx, at[1] + 1, at[2] + dz))
    # Footprint mask: drop envelope ops that fall in the void (courtyard /
    # outside a round tower) so windows, eaves and lanterns don't float in the
    # empty space the architecture carved out.
    _sp = gi.get("silhouette_parameters") or {}
    _envfp = footprint_for(gi.get("silhouette_id"),
                           gi.get("building_aabb") or gi.get("site_aabb"),
                           floor_index=0, n_floors=max(1, len(gi.get("floors") or [])),
                           footprint_shape=_sp.get("footprint_shape"), params=_sp)
    _mask = _envfp.cells
    _mask_active = (_envfp.shape != "rectangle")

    def _xz_in_mask(op) -> bool:
        if not _mask_active:
            return True
        at = op.get("at")
        if at and len(at) == 3:
            return (at[0], at[2]) in _mask
        a = op.get("aabb")
        if isinstance(a, list) and len(a) == 6:
            return any((x, z) in _mask
                       for x in range(a[0], a[3]) for z in range(a[2], a[5]))
        for key in ("from", "to"):
            p = op.get(key)
            if isinstance(p, list) and len(p) == 3 and (p[0], p[2]) in _mask:
                return True
        return op.get("from") is None and op.get("aabb") is None and at is None

    # The architecture_planner now OWNS the roof (gable/hip/spire/pagoda/dome/
    # crenellated). Drop any envelope op at/above the wall top so the LLM's
    # eave/roof slab can't float over or overwrite the real roof.
    _wall_top = max((int(r["aabb"][4]) for r in rooms_all
                     if isinstance(r.get("aabb"), list) and len(r["aabb"]) == 6),
                    default=10**9)

    def _at_roof_level(op):
        a = op.get("at") or (op.get("aabb") or [None, None, None])[:3]
        return isinstance(a, list) and len(a) == 3 and a[1] is not None \
            and a[1] >= _wall_top

    filtered = []
    n_skipped = n_void = n_roof = 0
    for op in (env_plan.get("ops") or []):
        at = op.get("at")
        if at and tuple(at) in door_blocked:
            n_skipped += 1
            continue
        if _at_roof_level(op):
            n_roof += 1
            continue
        if not _xz_in_mask(op):
            n_void += 1
            continue
        filtered.append(op)
    env_plan["ops"] = filtered
    _save_json(env_plan, workdir / "envelope_decoration.json")
    log(f"       envelope_ops={len(env_plan.get('ops') or [])}"
        f"  (skipped {n_skipped} door, {n_void} void, {n_roof} roof-level) "
        f"({time.time()-t:.1f}s)")

    # ── Stage 2: room_agents — feed via v3-shim space_plan + global_intent ──
    sp_v3_shim = _floor_plans_to_v3_space_plan(floor_plans)
    gi_v3_shim = _v4_global_intent_to_v3(gi, prompt)
    di_compat = aggregator._synth_design_intent(gi_v3_shim, sp_v3_shim, cp)
    di_compat["building_aabb"] = gi.get("building_aabb", gi["site_aabb"])
    di_compat["site_aabb"] = gi["site_aabb"]
    # Decide exterior features by category/style/silhouette so the
    # exterior_agent has direction (it produced nothing when this was empty).
    di_compat["exterior"] = {"features": exterior_agent.select_exterior_features(
        gi.get("category"), gi.get("style"), gi.get("silhouette_id"),
        di_compat["building_aabb"], di_compat["site_aabb"])}
    di_compat["floors"] = gi["floors"]
    # Carry the user's intent into room decoration so interiors match the
    # requested atmosphere/materials, not just the bare role+style.
    di_compat["user_prompt"] = gi.get("user_prompt", "")
    di_compat["expanded_description"] = gi.get("expanded_description", "")

    # ── Stages 7+8: room_agents AND exterior_agent in parallel ──
    # Both consume di_compat (already built) and have NO dependency on
    # each other's output. The aggregator (stage 9) is the joinpoint.
    # Wall-clock saved ≈ min(rooms_time, exterior_time) per run, typically
    # 60-200s on real runs since exterior_agent retries cost the most.
    t = time.time()
    log(f"[run-v4] 7+8/9  room_agents x{len(sp_v3_shim['rooms'])} || exterior_agent ...")

    room_plans: list[dict] = []
    ext = None

    def _plan_rooms_and_strip():
        rps = _plan_rooms(di_compat, parallel=parallel_rooms, log=log)
        # Strip ops referencing v4 metadata-only skills (kebab-case ids) —
        # they have no Python build() and shape_op schema rejects them.
        n_dropped = 0
        for rp in rps:
            kept = []
            for op in rp.get("ops") or []:
                if op.get("kind") == "skill":
                    sid = op.get("skill_id") or ""
                    if "-" in sid:
                        n_dropped += 1
                        continue
                kept.append(op)
            rp["ops"] = kept
        return rps, n_dropped

    def _plan_exterior_safe():
        try:
            # fallback_on_failure follows the ablation toggle. OFF (default): if
            # the LLM exterior fails after its retries, the build gets NO
            # exterior (the metric then honestly reflects the LLM). ON: the
            # exterior agent returns its canned deterministic exterior.
            return exterior_agent.plan_exterior(
                di_compat, fallback_on_failure=fallback_enabled()), None
        except Exception as e:  # noqa: BLE001
            log(f"       exterior: LLM failed ({e}) — "
                f"{'kept(fallback)' if fallback_enabled() else 'no exterior (no fallback)'}")
            return None, e

    # Run room agents and exterior agent concurrently (they share no state).
    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        rooms_fut = pool.submit(_plan_rooms_and_strip)
        ext_fut = pool.submit(_plan_exterior_safe)
        room_plans, n_dropped = rooms_fut.result()
        ext, ext_err = ext_fut.result()

    for rp in room_plans:
        _save_json(rp, rooms_dir / f"{rp['room_id']}.plan.json")
    if n_dropped:
        log(f"       (dropped {n_dropped} metadata-only skill ops)")
    log(f"       wrote {len(room_plans)} room plans  ({time.time()-t:.1f}s)")

    if ext is not None:
        _save_json(ext, workdir / "exterior.plan.json")
        log(f"       exterior ops={len(ext['ops'])}")
    elif ext_err is not None:
        log(f"       exterior skipped ({ext_err})")

    # Inject envelope_decorator ops as a synthetic "envelope" room_plan
    # — the aggregator will concatenate it just like a real room.
    room_plans.append(env_plan)

    # ── Stage 4: aggregator v3 (consumes 4 streams + room_plans) ──
    # The v4 architecture_plan_v4 has the same ops shape v3 expects;
    # aggregate_v3 only reads ops + materials_used so we re-key.
    ap_v3_shim = {
        "schema_version": "1.0",
        "ops": ap_v4["ops"],
        "materials_used": list(ap_v4.get("materials_usage", {}).values()),
        "generated_by": ap_v4.get("generated_by", {}),
    }
    t = time.time()
    log("[run-v4] 9/9  aggregator (v3-shim, 4-stream) ...")
    master = aggregator.aggregate_v3(gi_v3_shim, sp_v3_shim, ap_v3_shim, cp,
                                       room_plans, ext, gen_id=gen_id)
    # FIX 5: seed reproducible derivado del gen_id → variabilidad entre runs
    # (gen_id distinto) y reproducibilidad (mismo gen_id → mismo edificio).
    from pipeline.skills.seedutil import seed_from
    master["seed"] = seed_from(gen_id)
    master["implied_rooms"] = gi.get("implied_rooms") or []   # FIX A/B
    _save_json(master, workdir / "master_plan.json")
    log(f"       n_ops={len(master['ops'])}  warnings={len(master['warnings'])}"
        f"  ({time.time()-t:.1f}s)")
    for w in master["warnings"][:5]:
        log(f"       ⚠  {w}")

    # Append envelope_decorator ops + deterministic edge frame ops LAST
    # so composer later-wins makes them visible. The aggregator's stream
    # 4 (room decoration) and stream 3 (architecture envelope ops) come
    # earlier so they would otherwise overwrite the perimeter ring.
    # Frame ops (envelope_role="frame") from architecture_plan are
    # extracted here so they fire AT THE END.
    env_ops = list(env_plan.get("ops") or [])
    frame_ops = [op for op in (ap_v4.get("ops") or [])
                  if op.get("envelope_role") == "frame"
                  and op.get("kind") in ("fill", "outline", "rect", "place", "line")]
    # Re-assert exterior windows at the tail so they survive room/envelope
    # over-painting (the agents-overwrite problem). Skip cells next to a door
    # so the entrance stays a door, not a window.
    window_ops = [op for op in (ap_v4.get("ops") or [])
                  if op.get("kind") == "place"
                  and "glass" in str(op.get("block", ""))
                  and tuple(op.get("at") or ()) not in door_blocked]
    tail_ops = frame_ops + env_ops + window_ops
    # Las ESCALERAS deben ir LO ÚLTIMO de todo: las ops de frame/envolvente/
    # ventana de arriba rellenan estructura y, si se aplicaran después, taparían
    # el hueco de la escalera (la dejaban sepultada → "no se ve la escalera").
    # Re-materializamos las escaleras y las ponemos tras tail_ops para que ganen.
    stair_tail = aggregator.staircase_ops(cp)
    if tail_ops or stair_tail:
        master["ops"] = list(master["ops"]) + tail_ops + stair_tail
        log(f"       + appended {len(frame_ops)} frame + {len(env_ops)} "
            f"envelope + {len(window_ops)} window + {len(stair_tail)} stair ops "
            f"at tail (total n_ops={len(master['ops'])})")
        # Persist the updated master_plan
        _save_json(master, workdir / "master_plan.json")

    # ── Stage 5: voxelizer + post-proceso, con BEST-OF-K por seed (FIX 6) ──
    # El pipeline LLM ya corrió UNA vez. Aquí solo el tramo DETERMINISTA
    # (voxelize → physical_fixer → trim → massing → evaluate) se repite con K
    # seeds distintos (FIX 1 da layouts distintos por seed) y nos quedamos con
    # el de mayor composite → variabilidad SIN sacrificar calidad (neutraliza la
    # varianza de las variantes de sala). Coste: K× barato, sin LLM extra.
    from pipeline.skills.seedutil import seed_from as _seed_from
    t = time.time()
    log("[run-v4] +   voxelizer + best-of-K + evaluator ...")
    _K = 3
    cand_dir = workdir / "cand"

    def _build_candidate(cand_seed: int):
        m = dict(master); m["seed"] = cand_seed
        cpath = voxelizer.voxelize(m, out_dir=cand_dir)
        cdoc = json.loads(cpath.read_text())
        # ABLATION: the deterministic post-processing chain (physical_fixer,
        # envelope_closer, trim_decorator, massing, furnish) is RE-ENABLED only
        # when HOMECRAFT_FALLBACK_MODE=on. OFF (default): evaluate the raw
        # voxelized LLM-driven plan (these passes inflated/saturated metrics
        # regardless of the LLM).
        if fallback_enabled():
            for fn in (lambda d: physical_fixer.fix(d, master_plan=m, log=lambda *a, **k: None)[0],
                       lambda d: envelope_closer.close(d, master_plan=m, global_intent=gi,
                                                       door_cells=frozenset(door_blocked))[0],
                       lambda d: trim_decorator.decorate_doc(d, gi, door_cells=frozenset(door_blocked))[0],
                       lambda d: massing.add_masses(d, gi)[0],
                       lambda d: furnish.furnish(d, style=gi.get("style", "medieval"),
                                                 door_cells=frozenset(door_blocked))[0]):
                try:
                    cdoc = fn(cdoc)
                except Exception:  # noqa: BLE001
                    pass
        try:
            rep = evaluator.evaluate(cdoc, design_intent=di_compat,
                                      master_plan=m, run_critique=False)
            score = rep["composite"].get("overall") or 0.0
        except Exception:  # noqa: BLE001
            score = 0.0
        return score, cand_seed, cdoc

    cands = [_build_candidate(_seed_from(gen_id, "cand", k)) for k in range(_K)]
    cands.sort(key=lambda c: c[0], reverse=True)
    best_score, best_seed, doc = cands[0]
    master["seed"] = best_seed
    log(f"       best-of-{_K}: scores={[round(c[0], 3) for c in cands]} "
        f"→ elegido {best_score:.3f} (seed {best_seed})  ({time.time()-t:.1f}s)")
    final_path = base_dir / f"{gen_id}.json"
    final_path.write_text(json.dumps(doc), encoding="utf-8")
    _save_json(master, workdir / "master_plan.json")

    # ── Stage 5b: aligner — final alignment/coherence pass ──
    # Deterministic floater-removal + LLM coherence verdict. Polishes the
    # assembled result (nothing floating/out of place) and writes a report.
    t = time.time()
    log("[run-v4] +   aligner (LLM coherence verdict, REPORT-ONLY) ...")
    try:
        # ABLATION: OFF (default) is REPORT-ONLY — keep the coherence verdict but
        # DISCARD the polished doc (the deterministic floater-removal masked the
        # LLM's structural quality). ON: adopt the polished doc and persist it.
        polished, align_report = aligner.align(
            doc, master_plan=master, global_intent=gi, run_llm=True, log=log)
        if fallback_enabled():
            doc = polished
            final_path.write_text(json.dumps(doc), encoding="utf-8")
            log(f"       coherent={align_report.get('coherent')}  "
                f"(polished doc persisted)  ({time.time()-t:.1f}s)")
        else:
            log(f"       coherent={align_report.get('coherent')}  "
                f"(report-only, doc unchanged)  ({time.time()-t:.1f}s)")
        _save_json(align_report, workdir / "alignment_report.json")
    except Exception as e:  # noqa: BLE001 — aligner must never break a build
        log(f"       aligner skipped ({e})")

    # Coste de generación (tokens + tiempo de pared + tiempo de espera del LLM
    # + nº de llamadas + modelo) → para comparar LLMs de forma objetiva.
    _usage = _llm.usage_snapshot()
    # modelo REALMENTE usado (el de más llamadas), no solo el por-defecto → así
    # la comparación de LLMs refleja el modelo efectivo aunque se mezclen.
    _bm = _usage.get("by_model") or {}
    _primary_model = (max(_bm.items(), key=lambda kv: kv[1].get("calls", 0))[0]
                      if _bm else _llm.MODEL_MAIN)
    generation_cost = {
        "model": _primary_model,
        "wall_time_s": round(time.time() - _gen_t0, 2),
        "llm_wait_s": round(_usage.get("llm_wait_s", 0.0), 2),
        "llm_calls": _usage.get("calls", 0),
        "prompt_tokens": _usage.get("prompt_tokens", 0),
        "completion_tokens": _usage.get("completion_tokens", 0),
        "total_tokens": _usage.get("total_tokens", 0),
        "by_model": _usage.get("by_model", {}),
    }
    log(f"[run-v4] coste: {generation_cost['total_tokens']} tokens "
        f"({generation_cost['prompt_tokens']}+{generation_cost['completion_tokens']}) "
        f"en {generation_cost['llm_calls']} llamadas · "
        f"{generation_cost['wall_time_s']}s pared / {generation_cost['llm_wait_s']}s LLM · "
        f"modelo {generation_cost['model']}")
    _save_json(generation_cost, workdir / "generation_cost.json")

    # ── Stage 6: evaluator ──
    # The LLM critique is qualitative-only (report["critique"]) and does NOT
    # affect composite.overall, so bulk experiments can disable it for cost via
    # HOMECRAFT_RUN_CRITIQUE=0. Default keeps the critique (no regression).
    _run_crit = os.environ.get("HOMECRAFT_RUN_CRITIQUE", "1").strip().lower() \
        not in ("0", "off", "false", "no")
    try:
        report = evaluator.evaluate(doc, design_intent=di_compat,
                                      master_plan=master, run_critique=_run_crit)
        report["generation"] = generation_cost      # coste embebido en el reporte
        _save_json(report, workdir / "evaluation_report.json")
        # Also write the sibling <gen_id>.evaluation.json — that's what
        # the viewer fetches (see viewer/js/app.js::reportPathFor).
        _save_json(report, base_dir / f"{gen_id}.evaluation.json")
        c = report["composite"]
        log(f"       voxels={len(doc['voxels'])}  palette={len(doc['block_palette'])}")
        log(f"       overall={c.get('overall')}"
            f"  physical={c.get('physical_total')}"
            f"  alexander={c.get('alexander_total')}  ({time.time()-t:.1f}s)")
    except Exception as e:
        log(f"       evaluator skipped ({e})")

    log(f"[run-v4] OK -> {final_path}")
    try:
        _rel = final_path.resolve().relative_to(REPO_ROOT)
        log(f"[run-v4] viewer: http://localhost:8000/viewer/?file=../{_rel}")
    except ValueError:
        # output-dir outside the repo (or relative) — skip the viewer hint.
        pass
    return final_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="+", help="user prompt (in quotes)")
    ap.add_argument("--gen-id", default=None, help="override gen_id (default: timestamped)")
    ap.add_argument("--serial", action="store_true",
                     help="run room agents serially (default: parallel)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--pipeline-version", "-V",
                     choices=["v2.6", "v3", "v4"], default="v2.6",
                     help="pipeline architecture (v2.6 = single planner; "
                          "v3 = 4 specialized sub-agents; "
                          "v4 = silhouette + per-floor + skill_category)")
    ap.add_argument("--output-dir", default=None, type=Path,
                     help="base output directory (default: scratch/generations). "
                          "Used by the gym to write into output/gym/iterNN/.")
    args = ap.parse_args(argv)
    prompt = " ".join(args.prompt)
    try:
        run(prompt, gen_id=args.gen_id,
            parallel_rooms=not args.serial, verbose=not args.quiet,
            pipeline_version=args.pipeline_version,
            out_base_dir=args.output_dir)
    except Exception as e:
        import traceback
        # Full traceback (file:line) so uncaught errors are diagnosable, not
        # just the message (e.g. "'str' object has no attribute 'get'").
        print(f"[run] ERROR: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
