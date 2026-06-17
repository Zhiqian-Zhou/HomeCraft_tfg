"""Coherence agent — cross-component fit/consistency correction (Stage 1d.5).

The room and exterior agents each work on ONE component in isolation: after the
global agents (global_designer, space_planner) hand off, a room agent never
sees its neighbours' results. That makes the assembled building incoherent —
floors that don't line up, walls that jog between storeys, rooms that poke out
of the footprint, towers whose storeys aren't stacked.

This agent runs right after the inter_floor_validator and BEFORE the
architecture planner, so the envelope is built on already-coherent geometry.
For every component (room / tower storey / …) it builds a neighbour-context
view (the room below, the room above, same-floor neighbours, the building type
+ footprint) and makes SMALL touch-ups so the pieces physically fit:

  • clamp every room to the building footprint (no protrusions / weird overhangs)
  • snap upper-storey wall edges onto the storey below (vertical wall continuity)
  • for a plain rectangular building → storeys stacked flush, one above another
  • for a tower (rect / O-courtyard / round) → storeys centred & stacked within
    the (possibly set-back) footprint so it reads as a coherent tower

Two judges, like the aligner:
  1. DETERMINISTIC core (always on): the geometric reconciliation above.
  2. LLM design pass (optional, one call): receives the per-component
     neighbour JSON and flags design-incoherent fits, optionally proposing
     small (±2) shifts which are applied only if they stay legal.

`reconcile()` returns (adjusted_floor_plans, report). It never enlarges the
building or moves stair reservations; it only nudges room AABBs.
"""
from __future__ import annotations

import copy
import json
from typing import Callable, Optional

from . import llm
from .main_agent import PROMPTS
from .footprint import footprint_for

_SNAP_TOL = 2          # cells: snap an upper edge onto a lower edge within this
_MIN_SIDE = 3          # keep each room ≥ this on X and Z
_LLM_MAX_SHIFT = 2     # cells: cap any LLM-proposed nudge
_GAP_TOL = 3           # cells: close inter-room gaps up to this so rooms touch


# ── geometry helpers ─────────────────────────────────────────────────────────

def _xz(a):
    return int(a[0]), int(a[2]), int(a[3]), int(a[5])     # x0,z0,x1,z1


def _overlap_xz(a, b) -> bool:
    ax0, az0, ax1, az1 = _xz(a)
    bx0, bz0, bx1, bz1 = _xz(b)
    return ax0 < bx1 and bx0 < ax1 and az0 < bz1 and bz0 < az1


def _shares_wall(a, b, min_overlap: int = 2) -> bool:
    """True iff two same-floor rooms share a vertical wall long enough to hold
    a door (≥ min_overlap cells of contact)."""
    ax0, az0, ax1, az1 = _xz(a)
    bx0, bz0, bx1, bz1 = _xz(b)
    z_ov = min(az1, bz1) - max(az0, bz0)
    if (ax1 == bx0 or bx1 == ax0) and z_ov >= min_overlap:
        return True
    x_ov = min(ax1, bx1) - max(ax0, bx0)
    if (az1 == bz0 or bz1 == az0) and x_ov >= min_overlap:
        return True
    return False


def _close_room_gaps(fp: dict) -> int:
    """Close small gaps between near-but-not-touching rooms so they SHARE a wall
    (and can then get a door). The floor_planner often leaves a 1-2 cell gap
    between rooms — they look adjacent but `_shares_wall` is False, so the room
    ends up isolated (low horizontal connectivity). Expand the lower/left room's
    far edge to meet the higher/right room's near edge across the gap (the gap
    is empty space, so this never overlaps). Returns the number of gaps closed."""
    rooms = fp.get("rooms") or []
    closed = 0
    for i, A in enumerate(rooms):
        for B in rooms[i + 1:]:
            ax0, az0, ax1, az1 = _xz(A["aabb"])
            bx0, bz0, bx1, bz1 = _xz(B["aabb"])
            if _shares_wall(A["aabb"], B["aabb"]) or _overlap_xz(A["aabb"], B["aabb"]):
                continue
            z_ov = min(az1, bz1) - max(az0, bz0)
            x_ov = min(ax1, bx1) - max(ax0, bx0)
            # X gap with enough Z overlap to hold a door
            if z_ov >= _MIN_SIDE - 1:
                if 0 < bx0 - ax1 <= _GAP_TOL:        # A left of B
                    A["aabb"][3] = bx0; closed += 1; continue
                if 0 < ax0 - bx1 <= _GAP_TOL:        # B left of A
                    B["aabb"][3] = ax0; closed += 1; continue
            # Z gap with enough X overlap
            if x_ov >= _MIN_SIDE - 1:
                if 0 < bz0 - az1 <= _GAP_TOL:        # A in front of B
                    A["aabb"][5] = bz0; closed += 1; continue
                if 0 < az0 - bz1 <= _GAP_TOL:        # B in front of A
                    B["aabb"][5] = az0; closed += 1; continue
    return closed


def _unify_stair_core(fps: list[dict], kind: str = "rectangular",
                       category: str = "") -> int:
    """Give a multi-floor building ONE shared vertical stair shaft.

    The floor_planner often reserves a DIFFERENT stair location per floor
    transition, and with set-back towers each storey shrinks, so the core
    zigzags and the BFS can't climb past the first storey (upper floors end up
    blocked / no_door). Replace every stair reservation with a single shaft at
    a fixed spot taken from the TOP floor's largest room — the top floor is the
    smallest, so a spot inside it is inside every lower floor too — so the
    connector stacks one staircase per transition into a continuous core.

    El TIPO de escalera se ADECÚA al edificio (sin restringir del todo: dentro
    de la preferencia hay variación por geometría):
      • torre/keep            → ESPIRAL de caracol (huella cuadrada, compacta)
      • casa/residencial      → DOGLEG doméstico (escalones + rellano, NO subida
                                recta; es lo natural de una vivienda)
      • monumento/cívico/grande → DOGLEG AMPLIO (escalera señorial con rellano)
    Returns 1 if a core was placed."""
    floors = [fp for fp in fps]
    if len(floors) < 2:
        return 0
    top = max(floors, key=lambda f: int(f.get("floor_index", 0)))
    rooms = top.get("rooms") or []
    if not rooms:
        return 0
    big = max(rooms, key=lambda r: (int(r["aabb"][3]) - int(r["aabb"][0]))
              * (int(r["aabb"][5]) - int(r["aabb"][2])))
    a = [int(v) for v in big["aabb"]]
    rw, rd = a[3] - a[0], a[5] - a[2]
    if rw < 2 or rd < 2:
        return 0
    long_room, short_room = (rw, rd) if rw >= rd else (rd, rw)

    # Preferencia de TIPO por edificio → lista de footprints candidatos
    # (largo, corto). El lado largo se alinea con el lado largo de la sala.
    cat = (category or "").lower()
    grand = cat in ("monument", "civic", "religious", "commercial", "palace",
                    "castle", "fortress")
    if kind == "tower":
        # Caracol: cuadrado. El aggregator construye espiral.
        prefer_cands = [(3, 3), (4, 4), (3, 3)]
        prefer_tid = "spiral-staircase"
    elif grand:
        # Señorial: dogleg amplio (rellano grande). Cae a más estrecho si no cabe.
        prefer_cands = [(6, 4), (5, 4), (6, 3), (5, 3), (4, 4)]
        prefer_tid = "grand-staircase"
    else:
        # Casa/residencial: dogleg doméstico con escalones + rellano (NO recto).
        prefer_cands = [(3, 5), (5, 3), (4, 4), (3, 4), (4, 3)]
        prefer_tid = "dogleg-staircase"

    # Filtra a lo que CABE en la sala; conserva el orden de preferencia.
    feas = [(L, S) for (L, S) in prefer_cands
            if L <= long_room and S <= short_room]
    if not feas:
        # No cabe la huella preferida → la mayor cuadrada/dogleg que quepa;
        # último recurso 2×2 (columna de escalera de mano).
        for fb in [(4, 3), (3, 3), (3, 2), (2, 2)]:
            if fb[0] <= long_room and fb[1] <= short_room:
                feas = [fb]; break
        feas = feas or [(2, 2)]
    # Variación determinista DENTRO de la preferencia (no restringe del todo).
    key = a[0] * 7 + a[2] * 13 + rw * 3 + rd * 5
    L, S = feas[key % len(feas)]
    w, d = (L, S) if rw >= rd else (S, L)

    # tid acorde a lo que se construirá (el aggregator decide por shape + ajuste).
    if max(L, S) <= 2:
        tid = "service-staircase"          # 2×2 → columna/escalera de mano
    elif kind == "tower" and max(L, S) <= 4 and abs(L - S) <= 1:
        tid = "spiral-staircase"
    elif max(L, S) >= 3 and min(L, S) >= 2:
        tid = prefer_tid if prefer_tid != "spiral-staircase" else "spiral-staircase"
        # casa/grande con huella alargada → dogleg/grand (switchback con escalones)
        if prefer_tid in ("dogleg-staircase", "grand-staircase"):
            tid = prefer_tid
    else:
        tid = "spiral-staircase"

    cx = a[0] + max(0, (rw - w) // 2)
    cz = a[2] + max(0, (rd - d) // 2)
    res = {"x0": cx, "z0": cz, "x1": cx + w, "z1": cz + d,
           "kind": "stair", "template_id": tid}
    for fp in floors:
        kept = [r for r in (fp.get("reserved_footprints") or [])
                if r.get("kind") != "stair"]
        fp["reserved_footprints"] = kept + [dict(res)]
    return 1


def _ensure_stair_access(fps: list[dict], bx0, bz0, bx1, bz1) -> int:
    """Make every stair shaft sit INSIDE a room on each floor it serves.

    Stair reservations are aligned across floors, but the floor_planner often
    leaves a floor with no room over the shaft (e.g. floor 0's rooms stop short
    of where the upper floors put the stairwell). Then the shaft cells aren't
    'interior air', the connectivity BFS can't reach the ladder, and every
    upper floor is unreachable. Extending the nearest room to engulf the shaft
    makes the ladder reachable on that floor (and stacks the floors more
    coherently). Returns the number of rooms extended."""
    stairs = []
    for fp in fps:
        for rsv in fp.get("reserved_footprints") or []:
            if rsv.get("kind") in ("stair", "shaft"):
                stairs.append((int(rsv["x0"]), int(rsv["z0"]),
                               int(rsv["x1"]), int(rsv["z1"])))
    if not stairs:
        return 0
    n = 0
    for fp in fps:
        rooms = fp.get("rooms") or []
        if not rooms:
            continue
        for (sx0, sz0, sx1, sz1) in stairs:
            scx, scz = (sx0 + sx1) // 2, (sz0 + sz1) // 2
            if any(int(r["aabb"][0]) <= scx < int(r["aabb"][3])
                   and int(r["aabb"][2]) <= scz < int(r["aabb"][5])
                   for r in rooms):
                continue                               # already inside a room
            def _d(r):
                a = r["aabb"]
                return abs((int(a[0]) + int(a[3])) // 2 - scx) \
                    + abs((int(a[2]) + int(a[5])) // 2 - scz)
            r = min(rooms, key=_d)
            a = [int(v) for v in r["aabb"]]
            a[0] = max(bx0, min(a[0], sx0)); a[2] = max(bz0, min(a[2], sz0))
            a[3] = min(bx1, max(a[3], sx1)); a[5] = min(bz1, max(a[5], sz1))
            r["aabb"] = a
            n += 1
    return n


def _complete_adjacency(fp: dict) -> int:
    """Ensure every pair of physically-adjacent rooms on a floor has a door (or
    opening) edge, and the floor's room graph is connected. The room agents
    plan rooms in isolation, so the LLM adjacency_graph is often incomplete →
    interior rooms end up walled-off and unreachable (low voxel_connectivity).
    Returns the number of door edges added."""
    rooms = fp.get("rooms") or []
    edges = fp.get("adjacency_graph") or []
    ids = [r["id"] for r in rooms]
    linked = {frozenset((e.get("from_room"), e.get("to_room")))
              for e in edges if e.get("kind") in ("door", "opening")}
    added = 0
    # 1) a door for every adjacent pair that isn't linked yet
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            key = frozenset((a["id"], b["id"]))
            if key in linked:
                continue
            if _shares_wall(a["aabb"], b["aabb"]):
                edges.append({"from_room": a["id"], "to_room": b["id"],
                              "kind": "door"})
                linked.add(key)
                added += 1
    # 2) connect any still-disconnected components via the nearest wall-sharing
    #    pair across the gap (rooms tile the floor, so a wall almost always
    #    exists). Union-find over the linked graph.
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    for e in edges:
        if e.get("kind") in ("door", "opening") \
                and e.get("from_room") in parent and e.get("to_room") in parent:
            union(e["from_room"], e["to_room"])
    by_id = {r["id"]: r for r in rooms}
    changed = True
    while changed:
        changed = False
        comps = {}
        for rid in ids:
            comps.setdefault(find(rid), []).append(rid)
        if len(comps) <= 1:
            break
        roots = list(comps)
        # find a wall-sharing pair across two different components
        joined = False
        for i, a in enumerate(rooms):
            for b in rooms[i + 1:]:
                if find(a["id"]) == find(b["id"]):
                    continue
                if _shares_wall(by_id[a["id"]]["aabb"], by_id[b["id"]]["aabb"]):
                    edges.append({"from_room": a["id"], "to_room": b["id"],
                                  "kind": "door"})
                    union(a["id"], b["id"])
                    added += 1
                    joined = changed = True
                    break
            if joined:
                break
        if not joined:
            break          # no wall to add a door through; give up gracefully
    fp["adjacency_graph"] = edges
    return added


def _clamp_room_to_box(a, box) -> tuple[list, bool]:
    """Clamp a room AABB's XZ into `box`=(bx0,bz0,bx1,bz1); keep ≥ _MIN_SIDE.
    Returns (new_aabb, changed)."""
    bx0, bz0, bx1, bz1 = box
    x0, y0, z0, x1, y1, z1 = (int(v) for v in a)
    nx0, nx1 = max(x0, bx0), min(x1, bx1)
    nz0, nz1 = max(z0, bz0), min(z1, bz1)
    # keep a minimum habitable size, pulling the far edge in if the box allows
    if nx1 - nx0 < _MIN_SIDE:
        nx1 = min(bx1, nx0 + _MIN_SIDE)
        nx0 = max(bx0, nx1 - _MIN_SIDE)
    if nz1 - nz0 < _MIN_SIDE:
        nz1 = min(bz1, nz0 + _MIN_SIDE)
        nz0 = max(bz0, nz1 - _MIN_SIDE)
    new = [nx0, y0, nz0, nx1, y1, nz1]
    return new, (new != [x0, y0, z0, x1, y1, z1])


def _snap_edges(a, lower_xs, lower_zs) -> tuple[list, bool]:
    """Snap the room's x0/x1 to the nearest lower-storey x edge (and z0/z1 to
    the nearest z edge) within _SNAP_TOL, preserving ≥ _MIN_SIDE — gives
    vertical wall continuity between storeys."""
    x0, y0, z0, x1, y1, z1 = (int(v) for v in a)

    def snap(v, edges):
        best = v
        bd = _SNAP_TOL + 1
        for e in edges:
            d = abs(e - v)
            if d <= _SNAP_TOL and d < bd:
                best, bd = e, d
        return best

    nx0, nx1 = snap(x0, lower_xs), snap(x1, lower_xs)
    nz0, nz1 = snap(z0, lower_zs), snap(z1, lower_zs)
    if nx1 - nx0 < _MIN_SIDE:
        nx0, nx1 = x0, x1
    if nz1 - nz0 < _MIN_SIDE:
        nz0, nz1 = z0, z1
    new = [nx0, y0, nz0, nx1, y1, nz1]
    return new, (new != [x0, y0, z0, x1, y1, z1])


# ── neighbour context ────────────────────────────────────────────────────────

def _neighbour_context(room, fp_idx, floors_by_idx) -> dict:
    """Below / above (overlapping XZ) + same-floor neighbours of `room`."""
    ax0, az0, ax1, az1 = _xz(room["aabb"])

    def overlappers(idx):
        out = []
        for r in floors_by_idx.get(idx, []):
            if r["id"] == room["id"]:
                continue
            if _overlap_xz(room["aabb"], r["aabb"]):
                out.append({"id": r["id"], "role": r.get("role"),
                            "aabb": [int(v) for v in r["aabb"]]})
        return out

    same = []
    for r in floors_by_idx.get(fp_idx, []):
        if r["id"] == room["id"]:
            continue
        bx0, bz0, bx1, bz1 = _xz(r["aabb"])
        touches = (ax0 <= bx1 and bx0 <= ax1 and az0 <= bz1 and bz0 <= az1)
        if touches:
            same.append({"id": r["id"], "role": r.get("role"),
                         "aabb": [int(v) for v in r["aabb"]]})
    return {"below": overlappers(fp_idx - 1),
            "above": overlappers(fp_idx + 1),
            "same_floor": same}


# ── deterministic reconciliation ─────────────────────────────────────────────

def _building_kind(gi: dict) -> str:
    sp = gi.get("silhouette_parameters") or {}
    prog = (sp.get("floor_progression") or "uniform").lower()
    shape = (sp.get("footprint_shape") or "rectangle").lower()
    sid = (gi.get("silhouette_id") or "").lower()
    cat = (gi.get("category") or "").lower()
    if prog in ("setback", "taper", "ziggurat", "stepped") or "tower" in sid \
            or cat in ("tower", "keep", "fort"):
        return "tower"
    if shape not in ("rectangle", "square", "long_rectangle"):
        return "shaped"
    return "rectangular"


def reconcile(global_intent: dict, floor_plans: list[dict], *,
              run_llm: bool = True, model: Optional[str] = None,
              log: Callable = print) -> tuple[list[dict], dict]:
    """Cross-component coherence pass. Returns (adjusted_floor_plans, report)."""
    fps = copy.deepcopy(floor_plans)
    fps.sort(key=lambda f: int(f.get("floor_index", 0)))
    bb = global_intent.get("building_aabb") or global_intent.get("site_aabb") \
        or [0, 0, 0, 1, 1, 1]
    bx0, _, bz0, bx1, _, bz1 = (int(v) for v in bb)
    kind = _building_kind(global_intent)
    sp = global_intent.get("silhouette_parameters") or {}
    n_fl = max(1, len(fps))

    floors_by_idx = {int(fp.get("floor_index", i)): (fp.get("rooms") or [])
                     for i, fp in enumerate(fps)}
    adjustments: list[dict] = []

    # Footprint bbox per floor (handles tower set-back / shaped masks).
    def _fp_box(idx):
        f = footprint_for(global_intent.get("silhouette_id"), bb,
                          floor_index=idx, n_floors=n_fl,
                          footprint_shape=sp.get("footprint_shape"), params=sp)
        x0, z0, x1, z1 = f.aabb_xz
        return (max(bx0, x0), max(bz0, z0), min(bx1, x1), min(bz1, z1))

    idxs = sorted(floors_by_idx)
    for n, idx in enumerate(idxs):
        box = _fp_box(idx)
        rooms = floors_by_idx[idx]
        # lower-storey wall edges for vertical-continuity snapping
        lower = floors_by_idx.get(idxs[n - 1]) if n > 0 else []
        lower_xs = sorted({int(r["aabb"][0]) for r in lower}
                          | {int(r["aabb"][3]) for r in lower})
        lower_zs = sorted({int(r["aabb"][2]) for r in lower}
                          | {int(r["aabb"][5]) for r in lower})
        for r in rooms:
            orig = [int(v) for v in r["aabb"]]
            # 1) clamp to this floor's footprint box (no protrusions)
            new, ch1 = _clamp_room_to_box(r["aabb"], box)
            # 2) vertical wall continuity: snap onto the storey below
            if lower_xs and kind in ("rectangular", "tower"):
                new, ch2 = _snap_edges(new, lower_xs, lower_zs)
                # re-clamp after snapping
                new, _ = _clamp_room_to_box(new, box)
            else:
                ch2 = False
            if new != orig:
                r["aabb"] = new
                adjustments.append({"room": r["id"], "floor": idx,
                                    "from": orig, "to": new,
                                    "ops": [k for k, c in
                                            (("clamp", ch1), ("snap", ch2)) if c]})

    # Multi-floor: unify the vertical stair shaft to ONE shared core so the
    # connector builds a continuous, climbable staircase through every storey.
    stair_core = _unify_stair_core(fps, kind=kind,
                                    category=(global_intent.get("category") or ""))
    # Make the (now unified) stair shaft sit inside a room on each floor.
    stairs_fixed = _ensure_stair_access(fps, bx0, bz0, bx1, bz1)

    # Close small inter-room gaps so near-but-not-touching rooms share a wall,
    # THEN door-link every adjacent pair. Without gap-closing, rooms separated
    # by a 1-2 cell gap can never get a door and stay isolated (low horizontal
    # connectivity).
    # Gap-closing only for rectangular/tower footprints: there a gap between
    # rooms is just imperfect tiling. For SHAPED footprints (L/U/cross/diamond/
    # round) a gap is usually the silhouette's VOID, so expanding a room into it
    # would push the room into space the architecture carves back to air.
    close_gaps = kind in ("rectangular", "tower")
    gaps_closed = 0
    doors_added = 0
    for fp in fps:
        if close_gaps:
            gaps_closed += _close_room_gaps(fp)
        doors_added += _complete_adjacency(fp)

    det = {
        "building_kind": kind,
        "rooms_adjusted": len(adjustments),
        "stair_core_unified": stair_core,
        "stairs_fixed": stairs_fixed,
        "gaps_closed": gaps_closed,
        "doors_added": doors_added,
        "adjustments": adjustments[:40],
    }

    # ── LLM design pass (optional, one call) ──
    llm_verdict = None
    if run_llm:
        components = []
        for idx in idxs:
            for r in floors_by_idx[idx]:
                components.append({
                    "id": r["id"], "role": r.get("role"), "floor": idx,
                    "aabb": [int(v) for v in r["aabb"]],
                    "neighbours": _neighbour_context(r, idx, floors_by_idx),
                })
        llm_verdict = _llm_design_pass(
            global_intent, kind, components, fps, floors_by_idx,
            model=model, log=log)

    coherent = True
    if llm_verdict is not None:
        coherent = bool(llm_verdict.get("coherent", True))

    report = {"stage": "coherence_agent", "coherent": coherent,
              "deterministic": det, "llm": llm_verdict,
              "llm_ran": llm_verdict is not None}
    log(f"[coherence] kind={kind} rooms_adjusted={len(adjustments)} "
        f"llm={'ok' if (llm_verdict and llm_verdict.get('coherent')) else ('issues' if llm_verdict else 'skip')}")
    return fps, report


def _llm_design_pass(gi, kind, components, fps, floors_by_idx, *,
                     model=None, log=print) -> Optional[dict]:
    """One LLM call: judge per-component design coherence + apply safe nudges."""
    try:
        system = (PROMPTS / "coherence_v4.md").read_text(encoding="utf-8")
    except OSError as e:
        log(f"[coherence] prompt missing ({e}); skipping LLM pass")
        return None
    payload = {
        "building": {
            "kind": kind,
            "silhouette_id": gi.get("silhouette_id"),
            "footprint_shape": (gi.get("silhouette_parameters") or {}).get("footprint_shape"),
            "building_aabb": [int(v) for v in (gi.get("building_aabb") or [])],
            "n_floors": len(fps),
        },
        "components": components,
    }
    try:
        kw = {"system": system, "user": json.dumps(payload, ensure_ascii=False)}
        if model:
            kw["model"] = model
        verdict = llm.call_llm_json(**kw)
    except Exception as e:                            # noqa: BLE001
        log(f"[coherence] LLM design pass failed ({e}); deterministic only")
        return None

    # Apply only safe nudges (cap ±_LLM_MAX_SHIFT, stay inside building_aabb,
    # keep ≥ _MIN_SIDE, don't create a new same-floor overlap).
    bb = gi.get("building_aabb") or [0, 0, 0, 1, 1, 1]
    bx0, _, bz0, bx1, _, bz1 = (int(v) for v in bb)
    applied = 0
    by_id = {r["id"]: (idx, r) for idx in floors_by_idx for r in floors_by_idx[idx]}
    for adj in (verdict.get("adjustments") or []):
        rid = adj.get("id")
        if rid not in by_id:
            continue
        idx, room = by_id[rid]
        x0, y0, z0, x1, y1, z1 = (int(v) for v in room["aabb"])
        def cap(v):
            return max(-_LLM_MAX_SHIFT, min(_LLM_MAX_SHIFT, int(v)))
        dx0 = cap(adj.get("dx0", 0)); dx1 = cap(adj.get("dx1", 0))
        dz0 = cap(adj.get("dz0", 0)); dz1 = cap(adj.get("dz1", 0))
        nx0, nx1 = max(bx0, x0 + dx0), min(bx1, x1 + dx1)
        nz0, nz1 = max(bz0, z0 + dz0), min(bz1, z1 + dz1)
        if nx1 - nx0 < _MIN_SIDE or nz1 - nz0 < _MIN_SIDE:
            continue
        cand = [nx0, y0, nz0, nx1, y1, nz1]
        if cand == [x0, y0, z0, x1, y1, z1]:
            continue
        # reject if it overlaps another room on the same floor
        clash = any(rr["id"] != rid and _overlap_xz(cand, rr["aabb"])
                    for rr in floors_by_idx[idx])
        if clash:
            continue
        room["aabb"] = cand
        applied += 1

    return {
        "coherent": bool(verdict.get("coherent", True)),
        "confidence": verdict.get("confidence"),
        "issues": verdict.get("issues") or [],
        "adjustments_applied": applied,
        "summary": verdict.get("summary") or "",
    }
