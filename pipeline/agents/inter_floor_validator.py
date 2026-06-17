"""Inter-floor validator — Stage 1d of Pipeline v4 (NEW).

Runs after N parallel floor_planners. Deterministic cross-floor checks
that the LLMs cannot enforce in isolation:

  C1 stair shaft alignment    — every vertical_connection (F, F+1) has a
                                 matching reserved_footprint on both floors
                                 (IoU ≥ 0.5; IoU ∈ [0.2, 0.5) auto-snaps).
  C2 entry_point realization  — every space_plan.entry_points entry has an
                                 'outside' edge in the matching floor_plan.
  C3 layout_skill equality    — floor_plans[F].layout_skill_id_used ==
                                 space_plan.floor_layout_id_per_floor[F].
  C4 room id uniqueness       — no two floors share a rooms[].id.
  C5 floor_index consistency  — floor_plans[F].floor_index == F.

Hard errors raise InterFloorValidationError; auto-fixes mutate the plans
in place and are reported in the returned FixReport.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class InterFloorValidationError(Exception):
    """Raised when a hard cross-floor coherence rule fails."""


@dataclass
class FixReport:
    """Summary of auto-fixes applied during inter_floor validation."""
    snapped_stairs: list[dict] = field(default_factory=list)
    synthesized_outside_edges: list[dict] = field(default_factory=list)
    renamed_room_ids: list[tuple[str, str, int]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return (len(self.snapped_stairs)
                + len(self.synthesized_outside_edges)
                + len(self.renamed_room_ids))


def _rect_area(r: dict) -> int:
    return max(0, int(r["x1"]) - int(r["x0"])) \
           * max(0, int(r["z1"]) - int(r["z0"]))


def _rect_iou(a: dict, b: dict) -> float:
    """IoU between two XZ rectangles."""
    ix0 = max(int(a["x0"]), int(b["x0"]))
    iz0 = max(int(a["z0"]), int(b["z0"]))
    ix1 = min(int(a["x1"]), int(b["x1"]))
    iz1 = min(int(a["z1"]), int(b["z1"]))
    inter = max(0, ix1 - ix0) * max(0, iz1 - iz0)
    if inter == 0:
        return 0.0
    union = _rect_area(a) + _rect_area(b) - inter
    return inter / union if union > 0 else 0.0


def _stair_reservations(floor_plan: dict, template_id: str) -> list[dict]:
    """Return the reserved_footprints on a floor that match a given stair
    template_id. If no template_id stamp is present, return all kind==stair
    reservations (best-effort match)."""
    out = []
    for r in floor_plan.get("reserved_footprints") or []:
        if r.get("kind") != "stair":
            continue
        if r.get("template_id") in (None, template_id):
            out.append(r)
    return out


def validate(*,
              global_intent: dict,
              space_plan: dict,
              floor_plans: list[dict]) -> tuple[list[dict], FixReport]:
    """Run all C1-C5 checks across the N floor_plans.

    Args:
        global_intent: validated global_intent_v4 dict.
        space_plan: validated space_plan_v4 dict.
        floor_plans: list of floor_plan dicts, indexed by floor_index.

    Returns:
        (floor_plans, FixReport) — same list (mutated in place for auto-fixes).

    Raises:
        InterFloorValidationError on hard-error rules.
    """
    n_floors = len(global_intent.get("floors") or [])
    if len(floor_plans) != n_floors:
        raise InterFloorValidationError(
            f"floor_plans length {len(floor_plans)} != "
            f"global_intent.floors.length {n_floors}")

    report = FixReport()

    # C5 floor_index consistency (hard error — masks deeper bugs)
    for i, fp in enumerate(floor_plans):
        if int(fp.get("floor_index", -1)) != i:
            raise InterFloorValidationError(
                f"floor_plans[{i}].floor_index={fp.get('floor_index')} "
                f"!= expected {i}")

    # C3 layout_skill equality (hard)
    layouts = space_plan.get("floor_layout_id_per_floor") or []
    for i, fp in enumerate(floor_plans):
        if i >= len(layouts):
            raise InterFloorValidationError(
                f"space_plan has no floor_layout_id for floor {i}")
        if fp.get("layout_skill_id_used") != layouts[i]:
            raise InterFloorValidationError(
                f"floor_plans[{i}].layout_skill_id_used="
                f"'{fp.get('layout_skill_id_used')}' != "
                f"space_plan.floor_layout_id_per_floor[{i}]='{layouts[i]}'")

    # C1 stair alignment (auto-snap on IoU ∈ [0.2, 0.5); hard error <0.2)
    for vc in space_plan.get("vertical_connections") or []:
        fa = int(vc.get("from_floor", -1))
        fb = int(vc.get("to_floor", -1))
        tid = vc.get("template_id")
        if not (0 <= fa < n_floors and 0 <= fb < n_floors):
            raise InterFloorValidationError(
                f"vertical_connection ({fa}, {fb}) out of range")
        stairs_a = _stair_reservations(floor_plans[fa], tid)
        stairs_b = _stair_reservations(floor_plans[fb], tid)
        if not stairs_a or not stairs_b:
            raise InterFloorValidationError(
                f"vertical_connection (floor {fa}, floor {fb}, "
                f"template={tid}) lacks a reserved_footprint on "
                f"{'floor ' + str(fa) if not stairs_a else 'floor ' + str(fb)}")
        # Pick best-IoU pair
        best = (0.0, None, None)
        for a in stairs_a:
            for b in stairs_b:
                iou = _rect_iou(a, b)
                if iou > best[0]:
                    best = (iou, a, b)
        iou, a, b = best
        if iou < 0.2:
            raise InterFloorValidationError(
                f"stair shaft misaligned between floor {fa} and floor {fb} "
                f"(template={tid}): IoU={iou:.2f} < 0.2; cannot auto-snap")
        if iou < 0.5:
            # Auto-snap: copy floor a's footprint onto floor b's
            before = dict(b)
            for k in ("x0", "z0", "x1", "z1"):
                b[k] = int(a[k])
            report.snapped_stairs.append({
                "vertical_connection": {"from_floor": fa, "to_floor": fb,
                                          "template_id": tid},
                "iou_before": round(iou, 2),
                "before": {k: before[k] for k in ("x0", "z0", "x1", "z1")},
                "after": {k: b[k] for k in ("x0", "z0", "x1", "z1")},
            })

    # C2 entry_point realization (auto-fix: synthesize outside→nearest-room edge)
    for ep in space_plan.get("entry_points") or []:
        f = int(ep.get("floor", -1))
        if not (0 <= f < n_floors):
            raise InterFloorValidationError(
                f"entry_point floor {f} out of range")
        fp = floor_plans[f]
        has_outside = any(
            (e.get("from_room") == "outside" or e.get("to_room") == "outside")
            for e in (fp.get("adjacency_graph") or []))
        if has_outside:
            continue
        # Auto-fix: attach outside to the first room on this floor whose AABB
        # touches the entry_point.side. If none, use the first room as a
        # last-resort fallback.
        side = ep.get("side")
        candidate = _room_touching_side(fp, side,
                                          global_intent.get("building_aabb"))
        if candidate is None and (fp.get("rooms") or []):
            candidate = fp["rooms"][0]
        if candidate is None:
            raise InterFloorValidationError(
                f"floor {f} has no rooms but space_plan declares an entry_point")
        fp.setdefault("adjacency_graph", []).append({
            "from_room": "outside",
            "to_room":   candidate["id"],
            "kind":      "door",
        })
        report.synthesized_outside_edges.append({
            "floor": f, "side": side, "to_room": candidate["id"]})

    # C4 room id uniqueness.
    #  - SAME-floor duplicate ids are malformed LLM output: fail loudly rather
    #    than silently overwriting (which would leave two rooms sharing an id
    #    and ambiguous adjacency edges). No deterministic patch-over.
    #  - CROSS-floor duplicates are auto-renamed with a floor suffix (this is
    #    well-defined: edges live inside their own floor plan).
    seen: dict[str, int] = {}
    rename_pairs: list[tuple[str, str, int]] = []
    for i, fp in enumerate(floor_plans):
        floor_ids: set[str] = set()
        for r in fp.get("rooms") or []:
            rid = r["id"]
            if rid in floor_ids:
                raise InterFloorValidationError(
                    f"floor {i} has duplicate room id {rid!r} — the LLM must "
                    f"emit unique room ids per floor")
            floor_ids.add(rid)
            if rid in seen and seen[rid] != i:
                new_id = f"{rid}-f{i}"
                # Bump suffix until unique (across floors and within this floor)
                while new_id in seen or new_id in floor_ids:
                    new_id = new_id + "_"
                rename_pairs.append((rid, new_id, i))
                _rename_room(fp, rid, new_id)
                seen[new_id] = i
                floor_ids.discard(rid)
                floor_ids.add(new_id)
            else:
                seen[rid] = i
    report.renamed_room_ids = rename_pairs

    return floor_plans, report


def _room_touching_side(fp: dict, side: str | None,
                          building_aabb: list[int] | None) -> dict | None:
    """Find the first room in fp.rooms whose AABB touches the given side
    ('+x', '-x', '+z', '-z') of the building bounding box."""
    if not side or not building_aabb or len(building_aabb) != 6:
        return None
    bx0, _, bz0, bx1, _, bz1 = building_aabb
    target = {"+x": ("x1", bx1), "-x": ("x0", bx0),
               "+z": ("z1", bz1), "-z": ("z0", bz0)}.get(side)
    if target is None:
        return None
    axis, value = target
    idx = {"x0": 0, "x1": 3, "z0": 2, "z1": 5}[axis]
    for r in fp.get("rooms") or []:
        aabb = r.get("aabb") or []
        if len(aabb) == 6 and int(aabb[idx]) == int(value):
            return r
    return None


def _rename_room(fp: dict, old: str, new: str) -> None:
    """Rename a room id in fp.rooms and in fp.adjacency_graph edges."""
    for r in fp.get("rooms") or []:
        if r.get("id") == old:
            r["id"] = new
    for e in fp.get("adjacency_graph") or []:
        if e.get("from_room") == old:
            e["from_room"] = new
        if e.get("to_room") == old:
            e["to_room"] = new


__all__ = ["validate", "InterFloorValidationError", "FixReport"]
