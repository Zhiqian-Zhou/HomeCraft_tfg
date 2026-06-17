"""Connector validator — the CRITIC pattern (Gou et al. 2023) applied to
LLM-proposed doors, windows, and staircases.

Pipeline v3 architecture: the connector_planner LLM proposes connectors
(positions, facings, between-rooms). This validator runs AFTER the LLM
and BEFORE op materialization. It performs DETERMINISTIC repair:

  * clamp_door_y         — force door at y >= floor.y0 + 1
                            (y=0 is the floor slab, y=1 is door bottom)
  * snap_door_to_wall    — project at[] to the shared wall edge of
                            the rooms in between=[A, B]
  * auto_facing          — compute facing perpendicular to wall,
                            pointing AWAY from room_inside
  * carve_opening_ops    — emit air ops at the door cell + perpendicular
                            cells (frame) so the door is reachable
  * validate_window      — ensure window AABB is on the EXTERIOR shell
                            of the building, not an interior partition
  * validate_staircase   — ensure staircase AABB lies inside a
                            circulation room AND connects 2 floors

Returns a `connector_plan.json`-shaped dict with full audit trail
(proposal, validated, warnings, carve_ops) per item. Items that
cannot be repaired land in `dropped[]` with a drop_code.

NO LLM here — pure Python, fully testable, byte-deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ── Constants ────────────────────────────────────────────────────────────

# Facing → unit delta in (x, y, z). Both short and long forms accepted.
FACING_DELTA: dict[str, tuple[int, int, int]] = {
    "n": (0, 0, -1), "north": (0, 0, -1),
    "s": (0, 0, 1),  "south": (0, 0, 1),
    "e": (1, 0, 0),  "east":  (1, 0, 0),
    "w": (-1, 0, 0), "west":  (-1, 0, 0),
}

# Canonical short forms (the validator normalizes everything to these).
FACING_NORMALIZE: dict[str, str] = {
    "n": "n", "north": "n",
    "s": "s", "south": "s",
    "e": "e", "east": "e",
    "w": "w", "west": "w",
}

# Roles considered "public / circulation" for staircase placement.
# Mirrors evaluator._PRIVACY public tier.
PUBLIC_ROOM_ROLES = {
    "entry_hall", "hallway", "great_hall", "throne_room",
    "courtyard_indoor", "living_room", "dining_room",
}


# ── Helpers ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Room:
    """Lightweight room view for the validator."""
    id: str
    role: str
    floor: int
    aabb: tuple[int, int, int, int, int, int]

    @classmethod
    def from_dict(cls, d: dict) -> "Room":
        a = tuple(d["aabb"])
        if len(a) != 6:
            raise ValueError(f"room {d.get('id')!r}: aabb must have 6 ints")
        return cls(id=d["id"], role=d.get("role", ""),
                   floor=int(d.get("floor", 0)), aabb=a)


def _make_warning(code: str, before: Any, after: Any, message: str) -> dict:
    return {"code": code, "before": before, "after": after, "message": message}


def _floor_y0(floors: list[dict], floor_index: int) -> int:
    for f in floors:
        if int(f.get("index", -1)) == floor_index:
            return int(f["y0"])
    return 0


def _room_lookup(rooms: list[Room]) -> dict[str, Room]:
    return {r.id: r for r in rooms}


def _is_in_aabb(p: tuple[int, int, int],
                aabb: tuple[int, int, int, int, int, int]) -> bool:
    """Half-open AABB (xyz lower inclusive, upper exclusive)."""
    return (aabb[0] <= p[0] < aabb[3]
            and aabb[1] <= p[1] < aabb[4]
            and aabb[2] <= p[2] < aabb[5])


# ── 1. clamp_door_y ──────────────────────────────────────────────────────

def clamp_door_y(at: tuple[int, int, int], floor_y0: int,
                  warnings: list[dict]) -> tuple[int, int, int]:
    """Force y >= floor_y0 + 1. A door at y == floor_y0 is the floor slab.

    Returns clamped at; appends a clamped_axis warning if changed.
    """
    target_y = floor_y0 + 1
    if at[1] < target_y:
        warnings.append(_make_warning(
            "clamped_axis", at[1], target_y,
            f"door.at[1] was {at[1]}, clamped to {target_y}"))
        return (at[0], target_y, at[2])
    return at


# ── 2. snap_door_to_wall ─────────────────────────────────────────────────

def snap_door_to_wall(at: tuple[int, int, int],
                       room_a: Room | None, room_b: Room | None,
                       building_aabb: tuple[int, int, int, int, int, int] | None,
                       warnings: list[dict]) -> tuple[int, int, int] | None:
    """Project at to the closest valid wall edge.

    For door between=[A, B] (both rooms): the door must lie on the shared
    wall between A and B. We find the wall plane where their AABBs touch
    on one of x0/x1/z0/z1, then project at to a cell on that wall.

    For door between=[outside, X]: the door must lie on an exterior wall
    of X (one of its 4 outer edges). We pick the closest outer wall.

    Returns the snapped at, or None if no valid wall exists.
    """
    if room_a is None and room_b is None:
        return None

    # Identify the room interior. For exterior doors, room_inside is
    # whichever of (A, B) is a real room (the other is "outside").
    if room_a and room_b:
        # Interior door — find shared wall between A and B.
        wall_cells = _shared_wall_cells(room_a, room_b)
    else:
        room_inside = room_a or room_b
        wall_cells = _exterior_wall_cells(room_inside, building_aabb)

    if not wall_cells:
        return None

    # Find the cell in wall_cells closest to at (Manhattan distance,
    # excluding y axis which is handled by clamp_door_y).
    target = min(wall_cells,
                  key=lambda c: abs(c[0] - at[0]) + abs(c[2] - at[2]))
    if (target[0], target[2]) != (at[0], at[2]):
        warnings.append(_make_warning(
            "aligned_to_wall", list(at), [target[0], at[1], target[2]],
            f"door.at moved from ({at[0]},{at[1]},{at[2]}) to "
            f"({target[0]},{at[1]},{target[2]}) to align with room wall"))
        return (target[0], at[1], target[2])
    return at


def _shared_wall_cells(room_a: Room,
                        room_b: Room) -> list[tuple[int, int, int]]:
    """Cells on the shared wall between two adjacent rooms (half-open AABB).

    Two rooms share a wall when their AABBs touch on exactly one axis face:
    e.g. A.x1 == B.x0 (A's east wall = B's west wall).
    """
    ax0, ay0, az0, ax1, ay1, az1 = room_a.aabb
    bx0, by0, bz0, bx1, by1, bz1 = room_b.aabb

    # Overlap on y axis required (same floor).
    y0 = max(ay0, by0)
    y1 = min(ay1, by1)
    if y0 >= y1:
        return []

    # A east = B west (A.x1 == B.x0)
    if ax1 == bx0:
        z0 = max(az0, bz0); z1 = min(az1, bz1)
        if z0 < z1:
            return [(ax1 - 1, y0, z) for z in range(z0, z1)]
    # A west = B east
    if ax0 == bx1:
        z0 = max(az0, bz0); z1 = min(az1, bz1)
        if z0 < z1:
            return [(ax0, y0, z) for z in range(z0, z1)]
    # A south = B north (A.z1 == B.z0)
    if az1 == bz0:
        x0 = max(ax0, bx0); x1 = min(ax1, bx1)
        if x0 < x1:
            return [(x, y0, az1 - 1) for x in range(x0, x1)]
    # A north = B south
    if az0 == bz1:
        x0 = max(ax0, bx0); x1 = min(ax1, bx1)
        if x0 < x1:
            return [(x, y0, az0) for x in range(x0, x1)]
    return []


def _exterior_wall_cells(room: Room,
                          building_aabb: tuple[int, int, int, int, int, int] | None
                          ) -> list[tuple[int, int, int]]:
    """Cells on a wall of `room` that coincides with the building exterior.

    For Alexander pattern #110 ("Main Entrance"), exterior doors should sit
    on the LONGEST wall facing south (+z) when possible. We order candidate
    walls by preference: south > longest-axis > others. The caller picks
    the cell closest to the proposed at[] from this ordered list.
    """
    rx0, ry0, rz0, rx1, ry1, rz1 = room.aabb
    y = ry0  # door at floor level (will be clamped to +1 by clamp_door_y)

    south_wall: list[tuple[int, int, int]] = []
    north_wall: list[tuple[int, int, int]] = []
    east_wall: list[tuple[int, int, int]] = []
    west_wall: list[tuple[int, int, int]] = []

    # If we have a building_aabb, prefer walls that match the building shell.
    on_shell = False
    if building_aabb:
        bx0, by0, bz0, bx1, by1, bz1 = building_aabb
        if rz1 == bz1:
            south_wall.extend((x, y, rz1 - 1) for x in range(rx0, rx1))
            on_shell = True
        if rz0 == bz0:
            north_wall.extend((x, y, rz0) for x in range(rx0, rx1))
            on_shell = True
        if rx1 == bx1:
            east_wall.extend((rx1 - 1, y, z) for z in range(rz0, rz1))
            on_shell = True
        if rx0 == bx0:
            west_wall.extend((rx0, y, z) for z in range(rz0, rz1))
            on_shell = True

    # Fallback: all 4 room walls.
    if not on_shell:
        south_wall.extend((x, y, rz1 - 1) for x in range(rx0, rx1))
        north_wall.extend((x, y, rz0) for x in range(rx0, rx1))
        east_wall.extend((rx1 - 1, y, z) for z in range(rz0, rz1))
        west_wall.extend((rx0, y, z) for z in range(rz0, rz1))

    # Order: south first (APL #110 main_entrance preference), then by
    # wall length (longer = more presence), then the rest. Returning a
    # FLAT list means the caller's min-distance pick picks within the
    # preferred subset only if it's non-empty.
    cells: list[tuple[int, int, int]] = []
    for w in (south_wall, east_wall, west_wall, north_wall):
        if w:
            cells.extend(w)
            # Stop after the first non-empty preferred wall set:
            # the caller will snap to a cell in this set, which keeps
            # the door on the front of the building when possible.
            break
    return cells


# ── 3. auto_facing ───────────────────────────────────────────────────────

def auto_facing(at: tuple[int, int, int], room_inside: Room,
                 warnings: list[dict],
                 original: str | None = None) -> str:
    """Compute facing perpendicular to wall, pointing OUT of room_inside.

    The door at[] is on a wall of room_inside. Determine which wall
    (which axis face) and emit the unit facing that points away from
    the room interior.
    """
    rx0, _, rz0, rx1, _, rz1 = room_inside.aabb

    # Which wall does at[] sit on?
    if at[0] == rx0:
        new_facing = "w"           # west wall → face west
    elif at[0] == rx1 - 1:
        new_facing = "e"           # east wall → face east
    elif at[2] == rz0:
        new_facing = "n"           # north wall → face north
    elif at[2] == rz1 - 1:
        new_facing = "s"           # south wall → face south
    else:
        # Inside the room — should not happen after snap_door_to_wall.
        new_facing = original or "n"

    norm_original = FACING_NORMALIZE.get(original or "", None)
    if norm_original != new_facing:
        warnings.append(_make_warning(
            "facing_normalized", original, new_facing,
            f"door.facing was {original!r}, set to {new_facing!r} "
            f"based on wall geometry"))
    return new_facing


# ── 4. carve_opening_ops ─────────────────────────────────────────────────

def carve_opening_ops(at: tuple[int, int, int],
                       facing: str) -> list[dict]:
    """Emit air ops to guarantee the door is reachable from both sides.

    Generates 6 ops:
      * door cell + cell above  (panels overwrite later via _connector_ops)
      * exterior pair (out + above)
      * interior pair (in + above)

    These run BEFORE the door materialization so later-wins lets the
    actual door panels overwrite the air at the door cell.
    """
    dx, dy, dz = FACING_DELTA.get(facing, (0, 0, 0))
    if (dx, dy, dz) == (0, 0, 0):
        return []
    x, y, z = at
    cells = [
        (x, y, z),               # door bottom
        (x, y + 1, z),           # door top
        (x + dx, y, z + dz),     # outside foot
        (x + dx, y + 1, z + dz), # outside head
        (x - dx, y, z - dz),     # inside foot
        (x - dx, y + 1, z - dz), # inside head
    ]
    return [
        {"kind": "place", "at": list(c), "block": "minecraft:air"}
        for c in cells
    ]


# ── 5. validate_window ───────────────────────────────────────────────────

def validate_window(window: dict,
                     room: Room | None,
                     building_aabb: tuple[int, int, int, int, int, int] | None,
                     warnings: list[dict]) -> dict | None:
    """Confirm window AABB lies on an EXTERIOR wall of the building.

    Returns a validated dict with normalized fields, or None if the
    window is on an interior partition (cannot be repaired here).
    """
    if room is None:
        return None
    raw_aabb = window.get("aabb") or []
    if len(raw_aabb) != 6:
        return None
    try:
        aabb = tuple(int(v) for v in raw_aabb)
    except (TypeError, ValueError):
        return None
    rx0, ry0, rz0, rx1, ry1, rz1 = room.aabb
    wx0, wy0, wz0, wx1, wy1, wz1 = aabb

    on_exterior = False
    if building_aabb:
        bx0, by0, bz0, bx1, by1, bz1 = building_aabb
        # Window touches one of the building's outer faces and is on
        # the room's wall coincident with that face.
        if wx0 == bx0 == rx0: on_exterior = True
        if wx1 == bx1 == rx1: on_exterior = True
        if wz0 == bz0 == rz0: on_exterior = True
        if wz1 == bz1 == rz1: on_exterior = True
    else:
        # Without building_aabb, accept any wall of the room.
        if wx0 == rx0 or wx1 == rx1 or wz0 == rz0 or wz1 == rz1:
            on_exterior = True

    if not on_exterior:
        return None

    return {
        "in_room": room.id,
        "wall": str(window.get("wall", "n")),
        "aabb": list(aabb),
        "block_key": window.get("block_key", "@window"),
    }


# ── 6. validate_staircase ────────────────────────────────────────────────

def validate_staircase(stair: dict,
                        rooms: list[Room], floors: list[dict],
                        warnings: list[dict]) -> dict | None:
    """Confirm staircase AABB lies inside a circulation room AND connects
    two consecutive floors. Returns validated dict or None if unfixable.
    """
    raw_aabb = stair.get("aabb") or []
    if len(raw_aabb) != 6:
        return None
    try:
        aabb = tuple(int(v) for v in raw_aabb)
    except (TypeError, ValueError):
        return None
    sx0, sy0, sz0, sx1, sy1, sz1 = aabb
    if sy1 - sy0 < 2:
        return None  # too short to be a staircase

    # Find a room that contains the stair footprint AND is circulation.
    host = None
    for r in rooms:
        rx0, ry0, rz0, rx1, ry1, rz1 = r.aabb
        if (rx0 <= sx0 and sx1 <= rx1
                and rz0 <= sz0 and sz1 <= rz1
                and r.role in PUBLIC_ROOM_ROLES):
            host = r
            break
    if host is None:
        return None

    # Floors connected: from_floor = floor containing sy0;
    # to_floor = floor containing sy1-1.
    from_floor = _floor_at_y(floors, sy0)
    to_floor = _floor_at_y(floors, sy1 - 1)
    if from_floor is None or to_floor is None or from_floor == to_floor:
        return None

    return {
        "from_floor": from_floor,
        "to_floor": to_floor,
        "aabb": list(aabb),
        "shape": str(stair.get("shape", "straight")),
        "block_key": stair.get("block_key", "@stairs"),
    }


def _floor_at_y(floors: list[dict], y: int) -> int | None:
    for f in floors:
        y0 = int(f.get("y0", -1))
        y1 = int(f.get("y1", -1))
        if y0 <= y < y1:
            return int(f.get("index", -1))
    return None


# ── 7. Orchestrator ──────────────────────────────────────────────────────

def validate_connectors(proposals: dict,
                          space_plan: dict,
                          global_intent: dict) -> dict:
    """Top-level entry: take raw LLM-proposed connectors + space + global,
    return a connector_plan.schema.json-shaped dict with full audit trail.

    Args:
        proposals: {"doors": [...], "windows": [...], "staircases": [...]}
                   (raw, possibly malformed LLM output)
        space_plan: validated space_plan dict (rooms[] + adjacency_graph)
        global_intent: validated global_intent dict (building_aabb, floors[])

    Returns: connector_plan dict.
    """
    rooms = [Room.from_dict(r) for r in space_plan.get("rooms", [])]
    by_id = _room_lookup(rooms)
    floors = global_intent.get("floors", [])
    building_aabb = tuple(global_intent.get("building_aabb") or ())
    if len(building_aabb) != 6:
        building_aabb = None

    out: dict = {
        "schema_version": "1.0",
        "doors": [], "windows": [], "staircases": [],
        "dropped": [],
        "summary": {"passthrough": 0, "auto_fixed": 0,
                     "dropped": 0, "warning_codes": {}},
    }

    # ── doors ──
    for prop in proposals.get("doors", []) or []:
        item = _validate_one_door(prop, by_id, floors, building_aabb)
        if item.get("dropped"):
            out["dropped"].append(item["dropped"])
        else:
            out["doors"].append(item["item"])

    # ── windows ──
    for prop in proposals.get("windows", []) or []:
        item = _validate_one_window(prop, by_id, building_aabb)
        if item.get("dropped"):
            out["dropped"].append(item["dropped"])
        else:
            out["windows"].append(item["item"])

    # ── staircases ──
    for prop in proposals.get("staircases", []) or []:
        item = _validate_one_staircase(prop, rooms, floors)
        if item.get("dropped"):
            out["dropped"].append(item["dropped"])
        else:
            out["staircases"].append(item["item"])

    # ── summary ──
    all_items = out["doors"] + out["windows"] + out["staircases"]
    pass_n = sum(1 for it in all_items if not it.get("warnings"))
    fix_n = sum(1 for it in all_items if it.get("warnings"))
    out["summary"]["passthrough"] = pass_n
    out["summary"]["auto_fixed"] = fix_n
    out["summary"]["dropped"] = len(out["dropped"])
    codes: dict[str, int] = {}
    for it in all_items:
        for w in it.get("warnings", []):
            codes[w["code"]] = codes.get(w["code"], 0) + 1
    out["summary"]["warning_codes"] = codes

    return out


def _validate_one_door(prop: dict,
                        by_id: dict[str, Room],
                        floors: list[dict],
                        building_aabb: tuple | None) -> dict:
    """Validate one door proposal. Returns either {"item": ...} or
    {"dropped": ...}.
    """
    warnings: list[dict] = []
    door_id = str(prop.get("id", "d?"))
    between = list(prop.get("between") or [])
    if len(between) != 2:
        return {"dropped": {"id": door_id, "kind": "door",
                             "drop_code": "room_not_found",
                             "details": "between must have 2 entries"}}

    room_a = by_id.get(between[0]) if between[0] != "outside" else None
    room_b = by_id.get(between[1]) if between[1] != "outside" else None
    if room_a is None and room_b is None:
        return {"dropped": {"id": door_id, "kind": "door",
                             "drop_code": "room_not_found",
                             "details": f"neither {between[0]} nor {between[1]} found"}}

    # Determine the inside room (the one to compute facing relative to).
    room_inside = room_a if (room_a and not room_b) else (
        room_b if (room_b and not room_a) else room_a
    )

    # 1. clamp y (coerce coords to int — LLMs sometimes emit floats)
    raw_at = prop.get("at") or [0, 0, 0]
    if len(raw_at) != 3:
        return {"dropped": {"id": door_id, "kind": "door",
                             "drop_code": "no_valid_wall",
                             "details": "at must have 3 ints"}}
    try:
        at = tuple(int(v) for v in raw_at)
    except (TypeError, ValueError):
        return {"dropped": {"id": door_id, "kind": "door",
                             "drop_code": "no_valid_wall",
                             "details": f"at coords not coercible to int: {raw_at}"}}
    floor_y0 = _floor_y0(floors, room_inside.floor) if room_inside else 0
    at = clamp_door_y(at, floor_y0, warnings)

    # 2. snap to wall
    snapped = snap_door_to_wall(at, room_a, room_b, building_aabb, warnings)
    if snapped is None:
        return {"dropped": {"id": door_id, "kind": "door",
                             "drop_code": "no_valid_wall",
                             "details": f"no shared wall between {between}"}}
    at = snapped

    # 3. auto facing
    facing = auto_facing(at, room_inside, warnings,
                          original=prop.get("facing"))

    # 4. carve
    carves = carve_opening_ops(at, facing)
    if carves:
        warnings.append(_make_warning(
            "carved_opening", None, len(carves),
            f"carved {len(carves)} air cells around the door for passability"))

    item = {
        "id": door_id,
        "proposal": prop,
        "validated": {
            "between": between,
            "at": list(at),
            "facing": facing,
            "block_key": prop.get("block_key", "@door"),
        },
        "warnings": warnings,
        "carve_ops": carves,
    }
    return {"item": item}


def _validate_one_window(prop: dict,
                          by_id: dict[str, Room],
                          building_aabb: tuple | None) -> dict:
    warnings: list[dict] = []
    win_id = str(prop.get("id", "w?"))
    in_room = prop.get("in_room")
    room = by_id.get(in_room) if in_room else None
    if room is None:
        return {"dropped": {"id": win_id, "kind": "window",
                             "drop_code": "room_not_found",
                             "details": f"in_room={in_room!r} not found"}}
    validated = validate_window(prop, room, building_aabb, warnings)
    if validated is None:
        return {"dropped": {"id": win_id, "kind": "window",
                             "drop_code": "outside_envelope",
                             "details": "window not on exterior wall"}}
    item = {
        "id": win_id, "proposal": prop, "validated": validated,
        "warnings": warnings, "carve_ops": [],
    }
    return {"item": item}


def _validate_one_staircase(prop: dict,
                              rooms: list[Room],
                              floors: list[dict]) -> dict:
    warnings: list[dict] = []
    st_id = str(prop.get("id", "st?"))
    validated = validate_staircase(prop, rooms, floors, warnings)
    if validated is None:
        return {"dropped": {"id": st_id, "kind": "staircase",
                             "drop_code": "staircase_no_floor_clearance",
                             "details": "stair AABB outside circulation room or floors mismatch"}}
    item = {
        "id": st_id, "proposal": prop, "validated": validated,
        "warnings": warnings, "carve_ops": [],
    }
    return {"item": item}
