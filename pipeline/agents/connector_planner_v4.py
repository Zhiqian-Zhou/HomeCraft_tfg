"""Connector planner — v4 path (deterministic, no LLM).

The v3 connector_planner is an LLM wrapper around the deterministic
validator (`connector_validator.validate_connectors`). v4 removes the
LLM: every connector_template was already picked by the v4 space_planner,
every per-floor door+opening edge was emitted by the v4 floor_planner,
and the validator already knows how to clamp / snap / face / carve. So
v4 just SYNTHESIZES the LLM-style proposals from the upstream artifacts
and delegates placement to the v3 validator.

Four synthesis sources:
  · space_plan_v4.entry_points[]                → exterior door proposals
  · floor_plans[i].adjacency_graph[].kind=door  → interior door proposals
  · floor_plans[i].adjacency_graph[].kind=opening → interior carved-opening
  · space_plan_v4.vertical_connections[] +
    floor_plans[i].reserved_footprints[kind=stair] → staircase proposals

Output: a v3-compatible connector_plan dict (schema_version "1.0"), so
existing downstream consumers (voxelizer, evaluator) work unchanged. A
`connector_templates_realized[]` audit list is appended for traceability.
"""
from __future__ import annotations

from .connector_validator import validate_connectors
from .schema_utils import make_validator


def _validator():
    return make_validator("connector_plan.schema.json")


# Block selection per connector_template_id (1.16.5 vanilla, no 1.17+).
# Used as a HINT for the validator (which falls back on style palettes).
TEMPLATE_TO_BLOCKS: dict[str, str] = {
    "formal-front-entrance":   "minecraft:oak_door",
    "secondary-side-entrance": "minecraft:oak_door",
    "vestibule-with-coatroom": "minecraft:oak_door",
    "garden-door":             "minecraft:oak_door",
    "covered-porch":           "minecraft:oak_door",
    "arched-portal":           "minecraft:oak_door",
    "sliding-shoji-door":      "minecraft:spruce_door",
    "balcony-door-pair":       "minecraft:birch_door",
    "french-doors":            "minecraft:birch_door",
    "pocket-door":             "minecraft:oak_door",
    "dutch-door":              "minecraft:oak_door",
    "threshold-step":          "minecraft:oak_door",
    "front_door":              "minecraft:oak_door",
    "side_door":               "minecraft:oak_door",
    "archway_passage":         "minecraft:oak_door",  # validator will carve
    # Staircases
    "dogleg-staircase":        "minecraft:oak_stairs",
    "spiral-staircase":        "minecraft:oak_stairs",
    "grand-staircase":         "minecraft:stone_brick_stairs",
    "service-staircase":       "minecraft:spruce_stairs",
    "split-flight-stair":      "minecraft:oak_stairs",
    "attic-ladder":            "minecraft:oak_stairs",
    "ramp-entry":              "minecraft:oak_stairs",
    "lift-shaft":              "minecraft:oak_stairs",
    "staircase":               "minecraft:oak_stairs",  # legacy
}


def _door_block_for(template_id: str | None, style: str | None) -> str:
    """Pick a door block. Template wins; otherwise style fallback."""
    if template_id and template_id in TEMPLATE_TO_BLOCKS:
        return TEMPLATE_TO_BLOCKS[template_id]
    style_fallback = {
        "japanese":      "minecraft:spruce_door",
        "chinese":       "minecraft:spruce_door",
        "renaissance":   "minecraft:birch_door",
        "modern":        "minecraft:iron_door",
        "minimalist":    "minecraft:iron_door",
        "mediterranean": "minecraft:birch_door",
    }.get(style or "", "minecraft:oak_door")
    return style_fallback


# Material de la escalera elegido para CONTRASTAR con el muro típico del estilo
# (si no contrasta, la escalera se camufla y no se distingue como tal en el
# visor / en juego). Combinaciones clásicas y coherentes:
#   estilos de MADERA  → escalera de PIEDRA (stone_brick/cobblestone)
#   estilos de PIEDRA  → escalera de MADERA cálida (oak/dark_oak)
_STAIR_CONTRAST = {
    # madera dominante → piedra
    "rustic":        "minecraft:cobblestone_stairs",
    "medieval":      "minecraft:stone_brick_stairs",
    "fantasy":       "minecraft:stone_brick_stairs",
    "tudor":         "minecraft:stone_brick_stairs",
    "japanese":      "minecraft:stone_brick_stairs",
    "chinese":       "minecraft:stone_brick_stairs",
    # piedra/hormigón dominante → madera cálida (resalta)
    "gothic":        "minecraft:oak_stairs",
    "renaissance":   "minecraft:dark_oak_stairs",
    "mediterranean": "minecraft:dark_oak_stairs",
    "modern":        "minecraft:oak_stairs",
    "minimalist":    "minecraft:oak_stairs",
}


def _stair_block_for(template_id: str | None, style: str | None) -> str:
    # El contraste por estilo tiene PRIORIDAD para que la escalera se VEA
    # (no se camufle con el muro). Solo si el estilo no está mapeado caemos al
    # material del template o a piedra (el caso común es muro de madera).
    s = (style or "").strip().lower()
    if s in _STAIR_CONTRAST:
        return _STAIR_CONTRAST[s]
    if template_id and template_id in TEMPLATE_TO_BLOCKS:
        return TEMPLATE_TO_BLOCKS[template_id]
    return "minecraft:cobblestone_stairs"


def _aggregate_rooms(floor_plans: list[dict]) -> list[dict]:
    out: list[dict] = []
    for fp in floor_plans:
        out.extend(fp.get("rooms") or [])
    return out


def _synthesize_proposals(global_intent: dict, space_plan: dict,
                           floor_plans: list[dict]) -> dict:
    """Build the dict the v3 validator expects: doors/windows/staircases."""
    style = global_intent.get("style")
    building_aabb = global_intent.get("building_aabb") or [0, 0, 0, 0, 0, 0]
    floors = global_intent.get("floors") or []

    # Index for quick lookup
    rooms_by_id: dict[str, dict] = {}
    for fp in floor_plans:
        for r in fp.get("rooms") or []:
            rooms_by_id[r["id"]] = r

    door_props: list[dict] = []
    stair_props: list[dict] = []

    # 1) Exterior doors from entry_points[]
    for i, ep in enumerate(space_plan.get("entry_points") or []):
        f_idx = int(ep.get("floor", 0))
        side = ep.get("side")
        tid = ep.get("template_id")
        # The room that the entry hits = the floor_plan's "outside" edge
        # target on this floor.
        host_room_id = _outside_edge_room(floor_plans, f_idx)
        if host_room_id is None:
            continue
        floor = next((f for f in floors if int(f.get("index", -1)) == f_idx),
                      None)
        y0 = int((floor or {}).get("y0", 0))
        # Best-effort coordinate hint (centroid of side); validator will
        # snap to the actual wall.
        at_xyz = _side_centroid(building_aabb, side, y0)
        door_props.append({
            "id": f"entry_{i+1}",
            "between": ["outside", host_room_id],
            "at": list(at_xyz),
            "facing": _facing_from_side(side),
            "block_key": _door_block_for(tid, style),
            "source": {"template_id": tid, "role": "entrance"},
        })

    # 2) Interior doors + openings from floor_plans adjacency_graph[]
    next_id = {"door": 1, "opening": 1}
    for fp in floor_plans:
        f_idx = int(fp.get("floor_index", 0))
        floor = next((f for f in floors if int(f.get("index", -1)) == f_idx),
                      None)
        y0 = int((floor or {}).get("y0", 0))
        for e in fp.get("adjacency_graph") or []:
            kind = e.get("kind")
            if kind not in ("door", "opening"):
                continue
            fr, to = e.get("from_room"), e.get("to_room")
            if fr == "outside" or to == "outside":
                # Already handled by entry_points above
                continue
            ra, rb = rooms_by_id.get(fr), rooms_by_id.get(to)
            if not ra or not rb:
                continue
            at_xyz = _shared_wall_midpoint(ra["aabb"], rb["aabb"], y0)
            tag = "door" if kind == "door" else "opening"
            door_props.append({
                "id": f"{tag}_{next_id[kind]}",
                "between": [fr, to],
                "at": list(at_xyz),
                "facing": "auto",  # validator will compute
                "block_key": ("minecraft:air"
                               if kind == "opening"
                               else _door_block_for(None, style)),
                "source": {"role": "interior_passage" if kind == "opening"
                            else "interior_door"},
            })
            next_id[kind] += 1

    # 3) Staircases from vertical_connections[] + reserved_footprints
    next_stair = 1
    for vc in space_plan.get("vertical_connections") or []:
        fa = int(vc.get("from_floor", 0))
        fb = int(vc.get("to_floor", 1))
        tid = vc.get("template_id")
        # Find the reservation on floor fa with this template_id
        rsv = _find_stair_reservation(floor_plans, fa, tid)
        if rsv is None:
            continue
        # La forma/bloque siguen el tid de la RESERVA (la huella realmente
        # carvada por coherence), no el de la vertical_connection.
        rsv_tid = rsv.get("template_id") or tid
        # y span
        fa_y0 = _floor_y0(floors, fa)
        fb_y1 = _floor_y1(floors, fb)
        if fa_y0 is None or fb_y1 is None:
            continue
        stair_props.append({
            "id": f"stair_{next_stair}",
            "aabb": [int(rsv["x0"]), fa_y0, int(rsv["z0"]),
                      int(rsv["x1"]), fb_y1, int(rsv["z1"])],
            "from_floor": fa,
            "to_floor": fb,
            "shape": _shape_from_template(rsv_tid),
            "block_key": _stair_block_for(rsv_tid, style),
            "source": {"template_id": rsv_tid, "role": "stair"},
        })
        next_stair += 1

    return {
        "doors": door_props,
        "windows": [],
        "staircases": stair_props,
    }


def _outside_edge_room(floor_plans: list[dict], f_idx: int) -> str | None:
    for fp in floor_plans:
        if int(fp.get("floor_index", -1)) != f_idx:
            continue
        for e in fp.get("adjacency_graph") or []:
            if e.get("from_room") == "outside":
                return e.get("to_room")
            if e.get("to_room") == "outside":
                return e.get("from_room")
    return None


def _side_centroid(building_aabb: list[int], side: str | None,
                    y0: int) -> tuple[int, int, int]:
    bx0, _, bz0, bx1, _, bz1 = building_aabb
    mx = (bx0 + bx1) // 2
    mz = (bz0 + bz1) // 2
    if side == "+x":
        return (bx1 - 1, y0 + 1, mz)
    if side == "-x":
        return (bx0, y0 + 1, mz)
    if side == "+z":
        return (mx, y0 + 1, bz1 - 1)
    if side == "-z":
        return (mx, y0 + 1, bz0)
    return (mx, y0 + 1, mz)


def _facing_from_side(side: str | None) -> str:
    return {"+x": "east", "-x": "west", "+z": "south", "-z": "north"}.get(
        side or "", "north")


def _shared_wall_midpoint(a: list[int], b: list[int],
                            y0: int) -> tuple[int, int, int]:
    """Compute the midpoint of the shared wall span between two AABBs."""
    ax0, _, az0, ax1, _, az1 = a
    bx0, _, bz0, bx1, _, bz1 = b
    # x faces
    if ax1 == bx0:
        z = (max(az0, bz0) + min(az1, bz1)) // 2
        return (ax1, y0 + 1, z)
    if bx1 == ax0:
        z = (max(az0, bz0) + min(az1, bz1)) // 2
        return (ax0, y0 + 1, z)
    # z faces
    if az1 == bz0:
        x = (max(ax0, bx0) + min(ax1, bx1)) // 2
        return (x, y0 + 1, az1)
    if bz1 == az0:
        x = (max(ax0, bx0) + min(ax1, bx1)) // 2
        return (x, y0 + 1, az0)
    # Fallback: midpoint of room A
    return ((ax0 + ax1) // 2, y0 + 1, (az0 + az1) // 2)


def _find_stair_reservation(floor_plans: list[dict], f_idx: int,
                              template_id: str | None) -> dict | None:
    for fp in floor_plans:
        if int(fp.get("floor_index", -1)) != f_idx:
            continue
        # coherence_agent unifica a UN único núcleo de escalera por edificio y
        # puede reasignar su template_id (p.ej. spiral→dogleg según el hueco
        # elegido). Por eso preferimos la coincidencia exacta de tid pero, si no
        # la hay, devolvemos la primera reserva de escalera de la planta (el
        # núcleo unificado) en vez de fallar y dejar el edificio sin escalera.
        stair_rsvs = [r for r in (fp.get("reserved_footprints") or [])
                      if r.get("kind") == "stair"]
        for rsv in stair_rsvs:
            if rsv.get("template_id") in (None, template_id):
                return rsv
        if stair_rsvs:
            return stair_rsvs[0]
    return None


def _floor_y0(floors: list[dict], idx: int) -> int | None:
    for f in floors:
        if int(f.get("index", -1)) == idx:
            return int(f["y0"])
    return None


def _floor_y1(floors: list[dict], idx: int) -> int | None:
    for f in floors:
        if int(f.get("index", -1)) == idx:
            return int(f["y1"])
    return None


def _shape_from_template(template_id: str | None) -> str:
    """Map a stair template_id → connector_plan staircase shape enum."""
    return {
        "spiral-staircase":      "spiral",
        "dogleg-staircase":      "dogleg",
        "split-flight-stair":    "dogleg",
        "grand-staircase":       "straight",
        "service-staircase":     "straight",
        "attic-ladder":          "straight",
        "staircase":             "straight",
    }.get(template_id or "", "straight")


def materialize_connectors_v4(global_intent: dict,
                                space_plan: dict,
                                floor_plans: list[dict]) -> dict:
    """v4 connector materialization — deterministic, no LLM.

    Builds proposals from the upstream artifacts and delegates the
    placement / snap / facing / carve to the v3 validator (for doors and
    windows). Stairs bypass the v3 validator's "host room contains
    footprint" check — that check assumes single-floor host rooms, but
    v4 stairs span building height and live in reserved_footprints (a
    floor_plan-level reservation, not a room). The inter_floor_validator
    has already enforced footprint alignment between floors.

    Returns:
        {"connector_plan": dict matching connector_plan.schema.json,
         "connector_templates_realized": list of audit entries}
    """
    proposals = _synthesize_proposals(global_intent, space_plan, floor_plans)

    # Build a shim space_plan that the v3 validator expects (rooms[] +
    # adjacency_graph). Concatenate rooms and edges across all floors.
    rooms_all = _aggregate_rooms(floor_plans)
    edges_all: list[dict] = []
    for fp in floor_plans:
        edges_all.extend(fp.get("adjacency_graph") or [])
    shim_space_plan = {
        "schema_version": "1.0",
        "rooms":  rooms_all,
        "adjacency_graph": edges_all,
    }

    # Delegate doors+windows to the v3 validator (stairs skipped here)
    proposals_no_stairs = {"doors": proposals["doors"],
                             "windows": proposals["windows"],
                             "staircases": []}
    plan = validate_connectors(proposals_no_stairs, shim_space_plan, global_intent)

    # Emit stairs DIRECTLY (bypass the host-room contains check). The
    # reserved_footprint + vertical_connection contract was already
    # validated by inter_floor_validator, so trust the input.
    for s in proposals["staircases"]:
        plan["staircases"].append({
            "id":        s["id"],
            "proposal":  s,
            "validated": {
                "aabb":      list(s["aabb"]),
                "from_floor": int(s["from_floor"]),
                "to_floor":   int(s["to_floor"]),
                "shape":     s["shape"],
                "block_key": s["block_key"],
            },
            "warnings": [],
            "carve_ops": [],
        })

    # Append audit field
    realized: list[dict] = []
    for d in plan.get("doors") or []:
        prop = d.get("proposal") or {}
        src = prop.get("source") or {}
        realized.append({
            "template_id": src.get("template_id"),
            "kind":        src.get("role") or "door",
            "target_id":   d.get("id"),
        })
    for s in plan.get("staircases") or []:
        prop = s.get("proposal") or {}
        src = prop.get("source") or {}
        realized.append({
            "template_id": src.get("template_id"),
            "kind":        "stair",
            "target_id":   s.get("id"),
        })

    return {
        "connector_plan": plan,
        "connector_templates_realized": realized,
    }


__all__ = [
    "materialize_connectors_v4",
    "TEMPLATE_TO_BLOCKS",
]
