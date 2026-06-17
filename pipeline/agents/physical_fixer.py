"""Deterministic post-voxelize fixer for the 3 chronic physical metrics:

  - vertical_clearance  (most chronic; rooms with y0+1/y0+2 obstructed)
  - voxel_connectivity  (unreachable rooms → add interior doors / extra ext door)
  - light_coverage      (dim rooms → add a ceiling-level lantern grid)

Runs AFTER voxelizer and BEFORE aligner. Mutates the doc + master_plan in
place. No LLM call. Heavy on heuristic geometry — never raise (callers wrap
in try).

Usage (see pipeline/agents/run.py):
    doc = physical_fixer.fix(doc, master_plan=master, log=log)
"""
from __future__ import annotations

import re
from collections import deque

from . import aligner

# Block patterns that MUST be preserved when fixing vertical clearance —
# touching them would destroy room furniture / decoration / connectors and
# crater the evaluator metrics that depend on seating, lanterns, doors and
# glass (window_place, light_coverage, light_on_two_sides, …).
_PRESERVE_RX = re.compile(
    r"_bed$|_stairs$|_slab$|_carpet$|_wool$|^lectern$|^bookshelf$|"
    r"^crafting_table$|^cartography_table$|^smithing_table$|^loom$|"
    r"^enchanting_table$|^barrel$|^chest$|^flower_pot$|^lantern$|"
    r"^soul_lantern$|^sea_lantern$|^torch$|^wall_torch$|^soul_torch$|"
    r"^redstone_torch$|^redstone_lamp$|^glowstone$|^jack_o_lantern$|"
    r"_door$|_trapdoor$|_pressure_plate$|_button$|"
    r"glass(_pane)?$|_stained_glass(_pane)?$|^iron_bars$|"
    r"^vine$|^ladder$|^scaffolding$|"
    r"^cauldron$|^anvil$|_anvil$|^grindstone$|^stonecutter$|^smoker$|"
    r"^furnace$|^blast_furnace$|^campfire$|^soul_campfire$|^jukebox$|"
    r"^painting$|^banner$|_banner$|^armor_stand$|^item_frame$"
)


def _bare(block_id):
    """Strip blockstate suffix like '[facing=east]' and 'minecraft:' prefix."""
    bid = block_id.split("[")[0] if "[" in block_id else block_id
    if bid.startswith("minecraft:"):
        bid = bid[len("minecraft:"):]
    return bid


# ────────────────────────────────────────────────────────────────────────
#  Shared helpers
# ────────────────────────────────────────────────────────────────────────

def _vmap(doc):
    """(x,y,z) → palette_idx for every voxel."""
    out = {}
    for v in doc.get("voxels") or []:
        if isinstance(v, (list, tuple)) and len(v) == 4:
            out[(int(v[0]), int(v[1]), int(v[2]))] = int(v[3])
    return out


def _rooms(doc):
    """{room_id: aabb} from bot_decomposition (skip courtyards)."""
    rooms = {}
    bot = doc.get("bot_decomposition") or {}
    for s in (bot.get("building") or {}).get("storeys") or []:
        for sp in s.get("spaces") or []:
            rid = sp.get("id")
            a = sp.get("aabb")
            fn = (sp.get("function") or sp.get("role") or "").lower()
            if "courtyard" in fn:
                continue
            if rid and isinstance(a, list) and len(a) == 6:
                rooms[rid] = [int(v) for v in a]
    return rooms


def _palette_idx(doc, block_id):
    """Get-or-create palette index for `block_id` (e.g. 'minecraft:lantern')."""
    pal = doc.setdefault("block_palette", {})
    inv = {b: int(i) for i, b in pal.items()}
    if block_id in inv:
        return inv[block_id]
    new_idx = max((int(i) for i in pal.keys()), default=-1) + 1
    pal[str(new_idx)] = block_id
    return new_idx


# ────────────────────────────────────────────────────────────────────────
#  Fix 1 — vertical_clearance
#  Each room's interior columns must have ≥ 2 cells of air above the floor.
#  Strategy: for every interior cell at y0+1 and y0+2, if it's currently a
#  solid block, REMOVE the voxel. Skip cells that are connector ports (so we
#  don't carve doors closed).
# ────────────────────────────────────────────────────────────────────────

def _fix_vertical_clearance(doc, master_plan):
    rooms = _rooms(doc)
    if not rooms:
        return doc, {"removed": 0, "note": "no rooms"}
    vmap = _vmap(doc)
    # Track door cells so we don't accidentally seal them
    door_cells = set()
    for d in ((master_plan or {}).get("connectors") or {}).get("doors", []):
        at = d.get("at") or d.get("pos")
        if isinstance(at, list) and len(at) == 3:
            x, y, z = int(at[0]), int(at[1]), int(at[2])
            for dy in (-1, 0, 1, 2):
                door_cells.add((x, y + dy, z))

    # Palette lookup so we can check the block ID (not just its index)
    palette = doc.get("block_palette") or {}

    removed = set()
    preserved = 0
    for rid, a in rooms.items():
        # interior x,z (skip walls); y range = y0+1, y0+2 (the player's feet+head)
        x_lo, x_hi = a[0] + 1, a[3] - 1
        z_lo, z_hi = a[2] + 1, a[5] - 1
        if x_hi <= x_lo or z_hi <= z_lo:
            continue
        for x in range(x_lo, x_hi):
            for z in range(z_lo, z_hi):
                for y_off in (1, 2):  # feet + head
                    y = a[1] + y_off
                    if y >= a[4]:  # outside room top
                        continue
                    c = (x, y, z)
                    if c not in vmap or c in door_cells:
                        continue
                    # Only remove SOLID OPAQUE blocks. Skip furniture, lights,
                    # doors, glass, etc. — those are scored by other metrics
                    # and removing them craters window_place/light_*.
                    bid = palette.get(str(vmap[c])) or palette.get(vmap[c])
                    if bid and _PRESERVE_RX.search(_bare(bid)):
                        preserved += 1
                        continue
                    removed.add(c)

    if removed:
        doc["voxels"] = [v for v in (doc.get("voxels") or [])
                         if (int(v[0]), int(v[1]), int(v[2])) not in removed]
    return doc, {"removed": len(removed), "preserved": preserved,
                 "rooms": len(rooms)}


# ────────────────────────────────────────────────────────────────────────
#  Fix 2 — voxel_connectivity
#  BFS from each exterior door's interior cells through (a) free movement
#  within a room and (b) door ports (Chebyshev ≤ 2 of any door.at). For each
#  unreached room, either (i) carve a door into a face-adjacent reached room
#  or (ii) add a secondary exterior door on its furthest exterior wall.
# ────────────────────────────────────────────────────────────────────────

def _shared_wall(a, b):
    """Return (axis, plane, range_other, range_y) if rooms share a wall plane."""
    ay_lo, ay_hi = max(a[1], b[1]), min(a[4], b[4])
    if ay_hi - ay_lo < 2:
        return None
    for ex, bx in ((a[3], b[0]), (b[3], a[0])):
        if ex == bx:
            z_lo, z_hi = max(a[2], b[2]), min(a[5], b[5])
            if z_hi - z_lo >= 2:
                return ("x", ex, (z_lo, z_hi), (ay_lo, ay_hi))
    for ez, bz in ((a[5], b[2]), (b[5], a[2])):
        if ez == bz:
            x_lo, x_hi = max(a[0], b[0]), min(a[3], b[3])
            if x_hi - x_lo >= 2:
                return ("z", ez, (x_lo, x_hi), (ay_lo, ay_hi))
    return None


def _fix_room_connectivity(doc, master_plan):
    rooms = _rooms(doc)
    if not rooms:
        return doc, {"interior_doors": 0, "ext_doors": 0}
    vmap = _vmap(doc)
    doors = ((master_plan or {}).get("connectors") or {}).setdefault("doors", [])

    # Build per-room interior air cells
    cell_room, room_cells = {}, {}
    for rid, a in rooms.items():
        cells = set()
        for x in range(a[0], a[3]):
            for y in range(a[1], a[4]):
                for z in range(a[2], a[5]):
                    c = (x, y, z)
                    if c not in vmap and c not in cell_room:
                        cells.add(c)
                        cell_room[c] = rid
        room_cells[rid] = cells

    # Door port cells (Chebyshev ≤ 2)
    port_cells = set()
    for d in doors:
        at = d.get("at") or d.get("pos")
        if not (isinstance(at, list) and len(at) == 3):
            continue
        x, y, z = int(at[0]), int(at[1]), int(at[2])
        for dx in range(-2, 3):
            for dy in range(-1, 3):
                for dz in range(-2, 3):
                    port_cells.add((x + dx, y + dy, z + dz))

    # BFS seeded by exterior-door ports inside any room
    seeds = set()
    for d in doors:
        if "outside" not in (d.get("between") or []):
            continue
        at = d.get("at") or d.get("pos")
        if not (isinstance(at, list) and len(at) == 3):
            continue
        x, y, z = int(at[0]), int(at[1]), int(at[2])
        for dx in range(-3, 4):
            for dy in range(-1, 3):
                for dz in range(-3, 4):
                    c = (x + dx, y + dy, z + dz)
                    if c in cell_room:
                        seeds.add(c)

    reached = set()
    if seeds:
        fr = deque(seeds)
        while fr:
            c = fr.popleft()
            if c in reached:
                continue
            reached.add(c)
            cr = cell_room[c]
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                                (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                n = (c[0] + dx, c[1] + dy, c[2] + dz)
                if n in reached or n not in cell_room:
                    continue
                if cell_room[n] == cr or n in port_cells or c in port_cells:
                    fr.append(n)

    reachable = {rid for rid, cells in room_cells.items() if cells & reached}
    unreachable = [rid for rid, cells in room_cells.items()
                   if cells and rid not in reachable]

    # Pass 1: interior synthetic doors (shared wall with a reachable room)
    new_doors = []
    carved = set()
    for _ in range(len(rooms)):
        progress = False
        for u in list(unreachable):
            best = None
            for r in reachable:
                w = _shared_wall(rooms[u], rooms[r])
                if w:
                    best = (r, w)
                    break
            if not best:
                continue
            r, (axis, plane, oth, y_r) = best
            mid = (oth[0] + oth[1]) // 2
            y_door = max(rooms[u][1], rooms[r][1]) + 1
            if axis == "x":
                at = [plane - 1, y_door, mid]
                walls = [(plane - 1, y_door + k, mid) for k in (0, 1)] \
                      + [(plane, y_door + k, mid) for k in (0, 1)]
            else:
                at = [mid, y_door, plane - 1]
                walls = [(mid, y_door + k, plane - 1) for k in (0, 1)] \
                      + [(mid, y_door + k, plane) for k in (0, 1)]
            new_doors.append({"at": at, "between": [r, u],
                              "fixed_by": "physical_fixer"})
            for c in walls:
                if c in vmap:
                    carved.add(c)
            unreachable.remove(u)
            reachable.add(u)
            progress = True
        if not progress:
            break

    # Pass 2: still-unreachable rooms get a secondary EXTERIOR door
    n_ext = 0
    for u in unreachable:
        a = rooms[u]
        faces = [
            ("x", a[0],     (a[2], a[5]), (a[1], a[4])),
            ("x", a[3] - 1, (a[2], a[5]), (a[1], a[4])),
            ("z", a[2],     (a[0], a[3]), (a[1], a[4])),
            ("z", a[5] - 1, (a[0], a[3]), (a[1], a[4])),
        ]
        axis, plane, oth, _ = max(faces, key=lambda f: f[2][1] - f[2][0])
        mid = (oth[0] + oth[1]) // 2
        y_door = a[1] + 1
        if axis == "x":
            at = [plane, y_door, mid]
            walls = [(plane, y_door + k, mid) for k in (0, 1)]
        else:
            at = [mid, y_door, plane]
            walls = [(mid, y_door + k, plane) for k in (0, 1)]
        new_doors.append({"at": at, "between": ["outside", u],
                          "fixed_by": "physical_fixer_secondary"})
        for c in walls:
            if c in vmap:
                carved.add(c)
        n_ext += 1

    if new_doors:
        doors.extend(new_doors)
    if carved:
        doc["voxels"] = [v for v in (doc.get("voxels") or [])
                         if (int(v[0]), int(v[1]), int(v[2])) not in carved]

    return doc, {"interior_doors": len(new_doors) - n_ext,
                 "ext_doors": n_ext, "carved": len(carved)}


# ────────────────────────────────────────────────────────────────────────
#  Fix 3 — light_coverage
#  Each room ≥ 5 tall gets lanterns on a 7-cell grid at multiple Y levels
#  (y0+3 above head, every 7 cells up, y1-2 below ceiling). Skips short
#  rooms to preserve vertical_clearance.
# ────────────────────────────────────────────────────────────────────────

def _fix_light_coverage(doc):
    rooms = _rooms(doc)
    if not rooms:
        return doc, {"lanterns": 0}
    vmap = _vmap(doc)
    lantern_idx = _palette_idx(doc, "minecraft:lantern")

    added = []
    for _rid, a in rooms.items():
        if a[4] - a[1] < 5:
            continue
        span_x = max(1, a[3] - a[0] - 2)
        span_z = max(1, a[5] - a[2] - 2)
        nx = max(1, (span_x + 5) // 7)
        nz = max(1, (span_z + 5) // 7)
        # Y levels: y0+3 then every 7 then y1-2
        y_levels, y = [], a[1] + 3
        while y <= a[4] - 2:
            y_levels.append(y); y += 7
        if a[4] - 2 not in y_levels:
            y_levels.append(a[4] - 2)
        for i in range(nx):
            for j in range(nz):
                cx = a[0] + 1 + (2 * i + 1) * span_x // (2 * nx)
                cz = a[2] + 1 + (2 * j + 1) * span_z // (2 * nz)
                cx = max(a[0] + 1, min(cx, a[3] - 2))
                cz = max(a[2] + 1, min(cz, a[5] - 2))
                for cy in y_levels:
                    if (cx, cy, cz) in vmap:
                        continue
                    added.append([cx, cy, cz, lantern_idx])

    if added:
        doc["voxels"] = list(doc.get("voxels") or []) + added
    return doc, {"lanterns": len(added)}


# ────────────────────────────────────────────────────────────────────────
#  Public entry — runs all 3 in order
# ────────────────────────────────────────────────────────────────────────

def _fix_light_on_two_sides(doc):
    """For each room, ensure each EXTERIOR wall (a wall plane NOT shared with
    another room) has at least one glass_pane at mid-height. Directly lifts
    the `light_on_two_sides` Alexander metric.
    """
    rooms = _rooms(doc)
    if not rooms:
        return doc, {"glass_added": 0}
    vmap = _vmap(doc)
    glass_idx = _palette_idx(doc, "minecraft:glass_pane")

    # Build a flat room list with rid + aabb
    room_list = [(rid, a) for rid, a in rooms.items()]

    def _is_exterior(rid, a, axis, plane):
        """Wall is exterior if no OTHER room's AABB shares this wall plane
        (with vertical + perpendicular overlap)."""
        for orid, oa in room_list:
            if orid == rid:
                continue
            # vertical overlap
            y_lo, y_hi = max(a[1], oa[1]), min(a[4], oa[4])
            if y_hi - y_lo < 2:
                continue
            if axis == "x":
                if oa[0] == plane or oa[3] == plane:
                    z_lo, z_hi = max(a[2], oa[2]), min(a[5], oa[5])
                    if z_hi - z_lo >= 2:
                        return False
            else:  # z
                if oa[2] == plane or oa[5] == plane:
                    x_lo, x_hi = max(a[0], oa[0]), min(a[3], oa[3])
                    if x_hi - x_lo >= 2:
                        return False
        return True

    added = []
    for rid, a in rooms.items():
        if a[4] - a[1] < 4 or a[3] - a[0] < 4 or a[5] - a[2] < 4:
            continue
        y_mid = a[1] + 2          # consistent with _emit_room_windows
        for axis, plane in (("x", a[0]), ("x", a[3] - 1),
                             ("z", a[2]), ("z", a[5] - 1)):
            if not _is_exterior(rid, a, axis, plane):
                continue
            if axis == "x":
                # walk z and pick mid-cell as the glass slot
                cz = (a[2] + a[5] - 1) // 2
                for cell in ((plane, y_mid, cz), (plane, y_mid + 1, cz)):
                    if cell not in vmap:
                        continue  # cell is air → nothing to replace, skip
                    bid = doc["block_palette"].get(str(vmap[cell])) \
                            or doc["block_palette"].get(vmap[cell])
                    if bid and _PRESERVE_RX.search(_bare(bid)):
                        continue  # already glass/decor
                    added.append([cell[0], cell[1], cell[2], glass_idx])
            else:
                cx = (a[0] + a[3] - 1) // 2
                for cell in ((cx, y_mid, plane), (cx, y_mid + 1, plane)):
                    if cell not in vmap:
                        continue
                    bid = doc["block_palette"].get(str(vmap[cell])) \
                            or doc["block_palette"].get(vmap[cell])
                    if bid and _PRESERVE_RX.search(_bare(bid)):
                        continue
                    added.append([cell[0], cell[1], cell[2], glass_idx])

    if added:
        # Replace the wall block with glass at the chosen cells:
        # remove the old voxel(s), then append the glass.
        targets = {(c[0], c[1], c[2]) for c in added}
        doc["voxels"] = [v for v in (doc.get("voxels") or [])
                         if (int(v[0]), int(v[1]), int(v[2])) not in targets]
        doc["voxels"] = list(doc["voxels"]) + added
    return doc, {"glass_added": len(added)}


def fix(doc, *, master_plan=None, log=None):
    """Run vertical_clearance, then connectivity, then light_coverage, then
    light_on_two_sides. Order matters: clearance first (so carved cells aren't
    blocked by lanterns), then connectivity (which may carve walls), then
    lanterns, then glass on exterior walls."""
    report = {}
    doc, r1 = _fix_vertical_clearance(doc, master_plan)
    report["vertical_clearance"] = r1
    if master_plan is not None:
        doc, r2 = _fix_room_connectivity(doc, master_plan)
        report["connectivity"] = r2
    doc, r3 = _fix_light_coverage(doc)
    report["light_coverage"] = r3
    doc, r4 = _fix_light_on_two_sides(doc)
    report["light_on_two_sides"] = r4
    if log:
        log(f"       physical_fixer: clearance_removed="
            f"{r1.get('removed',0)} "
            f"int_doors={report.get('connectivity',{}).get('interior_doors',0)} "
            f"ext_doors={report.get('connectivity',{}).get('ext_doors',0)} "
            f"lanterns={r3.get('lanterns',0)} "
            f"glass={r4.get('glass_added',0)}")
    return doc, report
