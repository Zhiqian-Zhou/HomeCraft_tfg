"""Aligner — the final alignment / coherence pass (last stage of the pipeline).

Runs on the assembled voxel doc, AFTER the voxelizer and BEFORE the evaluator.
Its job is to polish the whole result and confirm everything fits together —
nothing left floating or out of place. It combines two judges:

  1. DETERMINISTIC pass (rule-based): 6-connected component labelling of the
     solid voxels. A component is "grounded" if it touches the base plane
     (y == min). Airborne components that reach nothing (the classic "roof
     block floating in the sky") are *removed*; ground-resting things (the
     building, exterior trees, walls) are kept. Also reports the grounded
     ratio, component count and a roof-on-walls gap check.

  2. LLM pass (model judgment): a compact structural summary + the
     deterministic findings are handed to the model, which returns a coherence
     verdict (is it coherent? what is floating / misaligned / out of place, and
     how to fix). This is the "does it all look right together" check that
     rules alone can't make.

Final verdict = deterministic_ok AND (llm.coherent if the LLM answered, else
deterministic_ok). The LLM is advisory + a second opinion; if it errors we log
and fall back to the deterministic verdict (never block the pipeline).

`align()` returns (polished_doc, report) and is pure w.r.t. the input doc
(returns a new doc when it removes floaters).
"""
from __future__ import annotations

import json
from typing import Callable, Optional

import numpy as np
from scipy.ndimage import label as _ndi_label

from . import llm
from .main_agent import PROMPTS
from .evaluator import (_build_voxel_map, _bare, _STRUCT_NON_SOLID,
                        _STRUCT_LEGIT_FLOATING_RX)

# 26-connectivity (face + edge + corner). Pitched roofs built from stair rows
# step DIAGONALLY (Δy=1, Δz=1), so they are 6-DISCONNECTED from the walls below
# even though they visually rest on them. Using full 3×3×3 adjacency means a
# stepped gable/mansard reads as one component with the building, while a truly
# isolated airborne block (the "floating roof block" bug) is still flagged.
_KERNEL26 = np.ones((3, 3, 3), dtype=np.uint8)

# If removing "floaters" would delete more than this fraction of the solid
# mass, something is structurally off (e.g. the whole build is elevated and
# our ground heuristic missed it) — report it but DON'T auto-delete.
_MAX_REMOVE_FRAC = 0.40


def _deterministic_pass(doc: dict) -> tuple[dict, dict]:
    """Detect + remove airborne floaters; report structural coherence."""
    vmap = _build_voxel_map(doc)
    try:
        size = doc["bounding_box"]["size"]
        W, H, D = int(size[0]), int(size[1]), int(size[2])
    except (KeyError, TypeError, ValueError, IndexError):
        return doc, {"ok": False, "notes": "missing/bad bounding_box",
                     "components": 0, "floaters_removed": 0}
    if W <= 0 or H <= 0 or D <= 0 or not vmap:
        return doc, {"ok": False, "notes": "empty/degenerate",
                     "components": 0, "floaters_removed": 0}

    solid = np.zeros((W, H, D), dtype=bool)
    bare_at: dict[tuple[int, int, int], str] = {}
    for (x, y, z), bid in vmap.items():
        if not (0 <= x < W and 0 <= y < H and 0 <= z < D):
            continue
        b = _bare(bid)
        bare_at[(x, y, z)] = b
        if b not in _STRUCT_NON_SOLID:
            solid[x, y, z] = True
    total = int(solid.sum())
    if total == 0:
        return doc, {"ok": False, "notes": "no solids",
                     "components": 0, "floaters_removed": 0}

    lbl, ncomp = _ndi_label(solid, structure=_KERNEL26)
    sizes = np.bincount(lbl.ravel())
    sizes[0] = 0

    # Grounded = any component label present on the base plane (y == 0).
    grounded = set(int(v) for v in np.unique(lbl[:, 0, :]) if v != 0)
    if not grounded:
        # Nothing touches the floor (elevated build / odd bbox): anchor on the
        # largest component so we don't delete everything.
        grounded = {int(sizes.argmax())}

    floater_labels = [l for l in range(1, ncomp + 1) if l not in grounded]
    floater_cells: list[tuple[int, int, int]] = []
    kept_decor = 0
    for l in floater_labels:
        for x, y, z in np.argwhere(lbl == l):
            cell = (int(x), int(y), int(z))
            if _STRUCT_LEGIT_FLOATING_RX.match(bare_at.get(cell, "")):
                kept_decor += 1            # torches/lanterns/banners — leave be
                continue
            floater_cells.append(cell)

    # Isolated blocks: solid cells with NO face-adjacent (6-conn) solid
    # neighbour. The 26-conn grounding keeps them (they corner/edge-touch the
    # build), but they read as FLOATING — e.g. a window pane the envelope laid
    # on a building edge that has no wall behind it. Remove them too. (Stair-
    # roof steps, cone apices and finials all keep a face neighbour, so they
    # are safe.)
    nbr = np.zeros_like(solid)
    nbr[1:, :, :] |= solid[:-1, :, :]
    nbr[:-1, :, :] |= solid[1:, :, :]
    nbr[:, 1:, :] |= solid[:, :-1, :]
    nbr[:, :-1, :] |= solid[:, 1:, :]
    nbr[:, :, 1:] |= solid[:, :, :-1]
    nbr[:, :, :-1] |= solid[:, :, 1:]
    isolated = solid & ~nbr
    n_isolated = 0
    for x, y, z in np.argwhere(isolated):
        cell = (int(x), int(y), int(z))
        if _STRUCT_LEGIT_FLOATING_RX.match(bare_at.get(cell, "")):
            continue
        floater_cells.append(cell)
        n_isolated += 1

    remove = set(floater_cells)
    grounded_solid = sum(int(sizes[l]) for l in grounded)
    report = {
        "ok": True,
        "components": int(ncomp),
        "grounded_components": len(grounded),
        "floater_components": len(floater_labels),
        "grounded_ratio": round(grounded_solid / total, 4),
        "kept_decor_cells": kept_decor,
        "isolated_blocks": n_isolated,
        "solid_total": total,
    }

    # Safety guard: never auto-delete a big chunk of the build.
    if remove and len(remove) > _MAX_REMOVE_FRAC * total:
        report.update(action="reported_only", floaters_removed=0,
                      floaters_found=len(remove),
                      notes="floaters exceed safe-removal threshold; left in place")
        report["ok"] = False
        return doc, report

    if remove:
        new_doc = dict(doc)
        new_doc["voxels"] = [v for v in doc.get("voxels", [])
                             if (v[0], v[1], v[2]) not in remove]
        report.update(action="removed", floaters_removed=len(remove),
                      floaters_found=len(remove),
                      removed_sample=sorted(remove)[:8])
        # ok iff what's LEFT is fully grounded (one or more grounded comps).
        report["ok"] = report["grounded_ratio"] >= 0.98 or len(remove) == total - grounded_solid
        return new_doc, report

    report.update(action="none", floaters_removed=0, floaters_found=0)
    report["ok"] = report["grounded_ratio"] >= 0.999
    return doc, report


def _structural_summary(doc: dict, det: dict,
                        global_intent: Optional[dict]) -> dict:
    """Compact, LLM-friendly description of the polished build."""
    size = doc.get("bounding_box", {}).get("size", [0, 0, 0])
    palette = doc.get("block_palette") or {}
    # top blocks by count
    counts: dict[str, int] = {}
    for v in doc.get("voxels", []):
        b = palette.get(str(v[3]))
        if b:
            counts[b] = counts.get(b, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:10]
    gi = global_intent or {}
    hi = gi.get("height_intent") or {}
    return {
        "dimensions_whd": size,
        "voxel_count": len(doc.get("voxels", [])),
        "palette_size": len(palette),
        "top_blocks": [{"block": b, "count": c} for b, c in top],
        "silhouette_id": gi.get("silhouette_id"),
        "footprint_shape": (gi.get("silhouette_parameters") or {}).get("footprint_shape"),
        "style": gi.get("style"),
        "category": gi.get("category"),
        "roof_style": hi.get("roof_style"),
        "roof_features": hi.get("roof_features") or [],
        "n_floors": len(gi.get("floors") or []),
        "deterministic_findings": det,
    }


def _llm_pass(summary: dict, *, model: Optional[str] = None,
              log: Callable = print) -> Optional[dict]:
    """Ask the model for a coherence verdict. Returns None on any failure."""
    try:
        system = (PROMPTS / "aligner_v4.md").read_text(encoding="utf-8")
    except OSError as e:
        log(f"[aligner] prompt missing ({e}); skipping LLM check")
        return None
    user = json.dumps(summary, ensure_ascii=False)
    try:
        kw = {"system": system, "user": user}
        if model:
            kw["model"] = model
        verdict = llm.call_llm_json(**kw)
    except Exception as e:                            # noqa: BLE001
        log(f"[aligner] LLM coherence check failed ({e}); using deterministic verdict")
        return None
    # normalise
    out = {
        "coherent": bool(verdict.get("coherent", True)),
        "confidence": verdict.get("confidence"),
        "issues": verdict.get("issues") or [],
        "summary": verdict.get("summary") or verdict.get("notes") or "",
    }
    return out


def align(doc: dict, *, master_plan: Optional[dict] = None,
          global_intent: Optional[dict] = None, run_llm: bool = True,
          model: Optional[str] = None,
          log: Callable = print) -> tuple[dict, dict]:
    """Final alignment + coherence pass.

    Returns (polished_doc, report). The deterministic pass removes airborne
    floaters; the LLM pass (optional) adds a model coherence verdict. The
    report's ``coherent`` is the combined verdict.
    """
    polished, det = _deterministic_pass(doc)
    llm_verdict = None
    if run_llm:
        summary = _structural_summary(polished, det, global_intent)
        llm_verdict = _llm_pass(summary, model=model, log=log)

    coherent = bool(det.get("ok"))
    if llm_verdict is not None:
        coherent = coherent and bool(llm_verdict.get("coherent"))

    report = {
        "stage": "aligner",
        "coherent": coherent,
        "deterministic": det,
        "llm": llm_verdict,
        "llm_ran": llm_verdict is not None,
    }
    n = det.get("floaters_removed", 0)
    log(f"[aligner] components={det.get('components')} "
        f"grounded_ratio={det.get('grounded_ratio')} "
        f"floaters_removed={n} "
        f"llm={'coherent' if (llm_verdict and llm_verdict['coherent']) else ('issues' if llm_verdict else 'skip')} "
        f"→ coherent={coherent}")
    return polished, report
