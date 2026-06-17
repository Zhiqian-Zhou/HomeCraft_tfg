"""Stage 6: rigorous building evaluator.

Computes 18 metrics over a ReferenceBuilding JSON:
  - 8 physical Minecraft 1.16.5 constraints
  - 10 Christopher Alexander pattern adherence scores

Plus a composite aggregator and an LLM-generated qualitative critique.

Each metric is documented in scratch/evaluation_specs/<metric_id>.md. This
module is the consolidated Python implementation.

Public API:
    from pipeline.agents.evaluator import evaluate
    report = evaluate(ref_building_doc, design_intent=..., master_plan=..., run_critique=True)
    # report is a dict matching rag/schema/evaluation_report.schema.json
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.ndimage import label as _ndi_label
from scipy.stats import rankdata

from .schema_utils import make_validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPTS = Path(__file__).resolve().parent / "prompts"

# ────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────

def _bare(block_id: str) -> str:
    """Strip [blockstate] suffix + 'minecraft:' prefix."""
    bid = block_id.split("[")[0] if "[" in block_id else block_id
    return bid.replace("minecraft:", "")


def _blockstate(block_id: str) -> dict[str, str]:
    """Extract {key: value} from '...[a=b,c=d]' or {}."""
    if "[" not in block_id:
        return {}
    inside = block_id.split("[", 1)[1].rstrip("]")
    return dict(part.split("=") for part in inside.split(",") if "=" in part)


def _build_voxel_map(doc: dict) -> dict[tuple[int, int, int], str]:
    """Build {(x,y,z): block_id_with_state} from voxels + palette."""
    palette = doc.get("block_palette") or {}
    out = {}
    for vx in doc.get("voxels") or []:
        if len(vx) != 4:
            continue
        x, y, z, p = vx
        bid = palette.get(str(p))
        if bid:
            out[(x, y, z)] = bid
    return out


# Block-family classifiers
_DOOR_RX = re.compile(r"_door$")
_TRAPDOOR_RX = re.compile(r"_trapdoor$")
_GLASS_RX = re.compile(r"^glass(_pane)?$|_stained_glass(_pane)?$|^iron_bars$")
_GRAVITY_RX = re.compile(r"^(sand|red_sand|gravel|.*_concrete_powder|scaffolding)$")
_LIGHT_RX = re.compile(
    r"^(torch|wall_torch|soul_torch|soul_wall_torch|redstone_torch|redstone_wall_torch|"
    r"lantern|soul_lantern|sea_lantern|glowstone|jack_o_lantern|end_rod|"
    r"campfire|soul_campfire|beacon|magma_block|shroomlight|redstone_lamp)$"
)
_FURNITURE_RX = re.compile(
    r"^(crafting_table|furnace|smoker|blast_furnace|chest|barrel|bookshelf|lectern|"
    r"cauldron|brewing_stand|enchanting_table|anvil|chipped_anvil|damaged_anvil|"
    r"loom|cartography_table|smithing_table|stonecutter|grindstone|jukebox|"
    r"red_bed|white_bed|black_bed|blue_bed|.*_bed)$"
)
_SEATING_RX = re.compile(
    r"_bed$|_stairs$|_slab$|_carpet$|_wool$|^lectern$|^bookshelf$|^crafting_table$|"
    r"^cartography_table$|^smithing_table$|^loom$|^enchanting_table$|^barrel$|^chest$"
)
_EDGE_TREATMENT_RX = re.compile(
    r"_stairs$|_slab$|^dirt_path$|^grass_path$|^cobblestone$|^mossy_cobblestone$|"
    r"^stone_bricks$|^podzol$|_fence$|^lantern$|_planks$|^flower_pot$"
)
# Strict apron set for building_edge: genuine transition/ground-treatment
# blocks only — NOT wall materials (cobblestone/planks/bricks) which would
# false-positive on the wall base and on the roof-overhang the envelope lays.
_EDGE_APRON_RX = re.compile(
    r"_stairs$|_slab$|^dirt_path$|^grass_path$|^gravel$|^path$|"
    r"_carpet$|^flower_pot$|^potted_|_fence$|^lantern$"
)

# ──────── main_entrance (APL #110) ────────
_MAIN_ENTRANCE_MARKER_RX = re.compile(
    r"^(lantern|soul_lantern|torch|wall_torch|soul_torch|soul_wall_torch|"
    r"redstone_torch|redstone_wall_torch|jack_o_lantern|campfire|soul_campfire|"
    r"flower_pot|potted_.+)$"
)
_MAIN_ENTRANCE_STAIR_RX = re.compile(r"_stairs$")
_MAIN_ENTRANCE_MARKER_RADIUS = 3
_MAIN_ENTRANCE_FRONT_MARGIN = 1
_MAIN_ENTRANCE_FACING_DELTA = {
    "north": (0, 0, -1), "south": (0, 0, 1),
    "east":  (1, 0, 0),  "west":  (-1, 0, 0),
}
_MAIN_ENTRANCE_OPPOSITE = {
    "south": "north", "north": "south", "east": "west", "west": "east",
}


def _stair_faces_door(stair_xyz, state, door_xyz) -> bool:
    """True si el `facing` de un bloque _stairs apunta hacia la puerta."""
    f = state.get("facing")
    if f not in _MAIN_ENTRANCE_FACING_DELTA:
        return False
    dx = door_xyz[0] - stair_xyz[0]
    dz = door_xyz[2] - stair_xyz[2]
    fx, _, fz = _MAIN_ENTRANCE_FACING_DELTA[f]
    if abs(dx) >= abs(dz):
        return fx == (1 if dx > 0 else -1 if dx < 0 else 0)
    return fz == (1 if dz > 0 else -1 if dz < 0 else 0)


# Block family for material_consistency
_FAMILY = [
    ("wood",      re.compile(r"_planks$|_log$|_stem$|^stripped_.+_log$|^stripped_.+_stem$|_wood$|_hyphae$")),
    ("stone",     re.compile(r"^cobblestone$|^stone$|^smooth_stone$|^andesite$|^polished_andesite$|^granite$|^polished_granite$|^diorite$|^polished_diorite$|^mossy_cobblestone$|^blackstone$|^polished_blackstone$")),
    ("brick",     re.compile(r"^stone_bricks$|^mossy_stone_bricks$|^cracked_stone_bricks$|^chiseled_stone_bricks$|^bricks$|^nether_bricks$|^red_nether_bricks$|^end_stone_bricks$|^polished_blackstone_bricks$|^prismarine_bricks$")),
    ("sandstone", re.compile(r"^sandstone$|^smooth_sandstone$|^chiseled_sandstone$|^cut_sandstone$|^red_sandstone$|^smooth_red_sandstone$|^chiseled_red_sandstone$|^cut_red_sandstone$")),
    ("quartz",    re.compile(r"quartz")),
    ("glass",     re.compile(r"^glass$|^.+_stained_glass$")),
    ("concrete",  re.compile(r"_concrete$")),
    ("terracotta", re.compile(r"terracotta")),
    ("soil",      re.compile(r"^dirt$|^grass_block$|^podzol$|^coarse_dirt$|^mycelium$|^sand$|^red_sand$|^gravel$|^netherrack$|^soul_sand$|^soul_soil$")),
]


def _family(bare: str) -> str:
    for fam, rx in _FAMILY:
        if rx.search(bare):
            return fam
    return "other"


# Role privacy levels for intimacy_gradient
_PRIVACY = {
    "entry-hall": 0, "entry_hall": 0, "hallway": 0, "courtyard": 0,
    "living-room": 1, "living_room": 1, "dining-room": 1, "dining_room": 1,
    "kitchen": 1, "great-hall": 1, "great_hall": 1, "music-room": 1, "music_room": 1, "library": 1,
    "study": 2, "throne-room": 2, "throne_room": 2, "chapel": 2,
    "bedroom": 3, "bathroom": 3, "nursery": 3,
    "storage": 1, "pantry": 1, "basement": 2, "attic": 2,
}
_COMMON_ROLES = {"kitchen", "living-room", "living_room", "dining-room", "dining_room",
                  "great-hall", "great_hall", "family-room", "family_room"}
_PRIVATE_ROLES = {"bedroom", "bathroom", "nursery", "study"}

# ────────────────────────────────────────────────────────────────────────
#  Metric implementations
# ────────────────────────────────────────────────────────────────────────


# ──────── structural_integrity ────────
_STRUCT_GRAVITY_BLOCKS = {
    "sand", "red_sand", "gravel", "anvil", "chipped_anvil", "damaged_anvil",
    "dragon_egg", "scaffolding",
    *(f"{c}_concrete_powder" for c in (
        "white", "orange", "magenta", "light_blue",
        "yellow", "lime", "pink", "gray", "light_gray",
        "cyan", "purple", "blue", "brown", "green",
        "red", "black",
    )),
}
_STRUCT_NON_SOLID = {"air", "cave_air", "void_air", "water", "lava"}
_STRUCT_LEGIT_FLOATING_RX = re.compile(
    r"^(torch|wall_torch|redstone_torch|redstone_wall_torch|lantern|.*_lantern|"
    r"ladder|vine|cobweb|.*_button|lever|.*_sign|.*_wall_sign|flower_pot|end_rod)$"
)
_STRUCT_WEIGHTS = (0.5, 0.3, 0.2)  # (float, gravity, holes)
_STRUCT_MAX_VIOLATIONS = 20
_STRUCT_KERNEL6 = np.array(
    [[[0, 0, 0], [0, 1, 0], [0, 0, 0]],
     [[0, 1, 0], [1, 1, 1], [0, 1, 0]],
     [[0, 0, 0], [0, 1, 0], [0, 0, 0]]],
    dtype=np.uint8,
)
# Full 26-connectivity (face+edge+corner). Stair-stepped roofs (gable, mansard,
# sawtooth, …) climb DIAGONALLY, so 6-conn wrongly split them into dozens of
# "floating" fragments; 26-conn keeps a pitched roof joined to its walls.
_STRUCT_KERNEL26 = np.ones((3, 3, 3), dtype=np.uint8)


def _structural_integrity(doc: dict, vmap: dict, master_plan: dict | None = None) -> dict:
    """Three-signal structural integrity: connected components + gravity + wall holes.

    Combines (a) floating-cluster detection via 6-conn labeling, (b) gravity check
    for falling blocks (sand/gravel/concrete_powder/anvil/scaffolding), and
    (c) flood-fill detection of unplanned wall holes against master_plan
    connectors. Output ∈ [0,1] with weighted penalties (0.5/0.3/0.2).
    """
    if not vmap:
        return {"score": 0.0, "notes": "empty building", "violations": []}
    try:
        size = doc["bounding_box"]["size"]
        W, H, D = int(size[0]), int(size[1]), int(size[2])
    except (KeyError, TypeError, ValueError, IndexError):
        return {"score": 0.0, "notes": "missing or malformed bounding_box",
                "violations": []}
    if W <= 0 or H <= 0 or D <= 0:
        return {"score": 0.0, "notes": "degenerate bbox", "violations": []}

    solid = np.zeros((W, H, D), dtype=bool)
    bare_at: dict[tuple[int, int, int], str] = {}
    for (x, y, z), bid in vmap.items():
        if not (0 <= x < W and 0 <= y < H and 0 <= z < D):
            continue
        bare = _bare(bid)
        bare_at[(x, y, z)] = bare
        if bare not in _STRUCT_NON_SOLID:
            solid[x, y, z] = True
    total = int(solid.sum())
    if total == 0:
        return {"score": 0.0, "notes": "empty (no solids)", "violations": []}

    # (a) floating = a solid component NOT anchored to the ground plane (y==0).
    # 26-conn + grounded (matches the aligner). The old "6-conn, not the
    # largest component" flagged stair-stepped roofs (diagonally disconnected)
    # as floating and penalised every gable/mansard/sawtooth build.
    lbl, ncomp = _ndi_label(solid, structure=_STRUCT_KERNEL26)
    grounded = set(int(v) for v in np.unique(lbl[:, 0, :]) if v != 0)
    if not grounded and ncomp >= 1:                 # nothing on the floor →
        sizes = np.bincount(lbl.ravel()); sizes[0] = 0
        grounded = {int(sizes.argmax())}            # anchor on the largest mass
    grounded_arr = (np.isin(lbl, list(grounded)) if grounded
                    else np.zeros_like(lbl, dtype=bool))
    floating_mask = (lbl > 0) & ~grounded_arr
    float_coords: list[tuple[int, int, int]] = []
    for x, y, z in np.argwhere(floating_mask):
        cell = (int(x), int(y), int(z))
        bare = bare_at.get(cell, "")
        if _STRUCT_LEGIT_FLOATING_RX.match(bare):
            # Legit decorative: keep only if it lacks any adjacent solid face.
            adj = False
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nx, ny, nz = cell[0] + dx, cell[1] + dy, cell[2] + dz
                if (0 <= nx < W and 0 <= ny < H and 0 <= nz < D
                        and solid[nx, ny, nz]):
                    adj = True
                    break
            if adj:
                continue
        float_coords.append(cell)

    # (b) gravity check — falling blocks need solid below (or lateral scaffolding).
    grav_viol: list[tuple[int, int, int]] = []
    for (x, y, z), bare in bare_at.items():
        if bare not in _STRUCT_GRAVITY_BLOCKS or y == 0:
            continue
        if solid[x, y - 1, z]:
            continue
        if bare == "scaffolding":
            # BFS at same Y over scaffolding chain ≤6, seeking a column with support.
            supported = False
            seen = {(x, y, z)}
            frontier = [(x, y, z, 0)]
            while frontier and not supported:
                cx, cy, cz, dist = frontier.pop()
                if dist >= 6:
                    continue
                for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, nz = cx + dx, cz + dz
                    if not (0 <= nx < W and 0 <= nz < D):
                        continue
                    if (nx, cy, nz) in seen:
                        continue
                    if bare_at.get((nx, cy, nz)) != "scaffolding":
                        continue
                    if cy == 0 or solid[nx, cy - 1, nz]:
                        supported = True
                        break
                    seen.add((nx, cy, nz))
                    frontier.append((nx, cy, nz, dist + 1))
            if supported:
                continue
        grav_viol.append((x, y, z))

    # (c) wall holes — flood-fill air from bbox shell; unplanned shell-air with
    # solid neighbor = hole. Skipped if no master_plan connectors.
    hole_viol: list[tuple[int, int, int]] = []
    conns = (master_plan or {}).get("connectors") or {}
    skip_holes = master_plan is None or not conns
    if not skip_holes:
        planned: set[tuple[int, int, int]] = set()
        for kind in ("doors", "windows"):
            for c in (conns.get(kind) or []):
                at = c.get("at") if isinstance(c, dict) else None
                if isinstance(at, list) and len(at) == 3:
                    planned.add((int(at[0]), int(at[1]), int(at[2])))
        air_visited = np.zeros_like(solid)
        stack: list[tuple[int, int, int]] = []
        # Seed shell cells (any non-solid on bbox boundary).
        for x in range(W):
            for y in range(H):
                for z in range(D):
                    on_shell = (
                        x in (0, W - 1) or y in (0, H - 1) or z in (0, D - 1)
                    )
                    if on_shell and not solid[x, y, z] and not air_visited[x, y, z]:
                        air_visited[x, y, z] = True
                        stack.append((x, y, z))
        # Flood-fill 6-conn through non-solid cells.
        while stack:
            x, y, z = stack.pop()
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nx, ny, nz = x + dx, y + dy, z + dz
                if not (0 <= nx < W and 0 <= ny < H and 0 <= nz < D):
                    continue
                if air_visited[nx, ny, nz] or solid[nx, ny, nz]:
                    continue
                air_visited[nx, ny, nz] = True
                stack.append((nx, ny, nz))
        # A hole = visited air on the bbox shell with a solid 6-neighbor and
        # not in planned. (Interior reachable air is a consequence of the
        # breach, not extra holes; we only count the shell-breach cells.)
        for x, y, z in np.argwhere(air_visited):
            cell = (int(x), int(y), int(z))
            on_shell = (
                cell[0] in (0, W - 1)
                or cell[1] in (0, H - 1)
                or cell[2] in (0, D - 1)
            )
            if not on_shell:
                continue
            if cell in planned:
                continue
            for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                nx, ny, nz = cell[0] + dx, cell[1] + dy, cell[2] + dz
                if (0 <= nx < W and 0 <= ny < H and 0 <= nz < D
                        and solid[nx, ny, nz]):
                    hole_viol.append(cell)
                    break

    # Combine penalties with weights.
    nf, ng, nh = len(float_coords), len(grav_viol), len(hole_viol)
    wf, wg, wh = _STRUCT_WEIGHTS
    pen_f = min(nf / total, 1.0) * wf
    pen_g = min(ng / max(total * 0.05, 1.0), 1.0) * wg
    pen_h = (
        min(nh / max(total * 0.10, 1.0), 1.0) * wh
        if not skip_holes else 0.0
    )
    score = max(0.0, 1.0 - pen_f - pen_g - pen_h)

    notes = f"float={nf} grav={ng} holes={nh}"
    if skip_holes:
        notes += " skip-hole-check"
    viols = (float_coords + grav_viol + hole_viol)[:_STRUCT_MAX_VIOLATIONS]
    return {"score": round(score, 3),
            "notes": notes,
            "violations": [list(v) for v in viols]}


# ──────── voxel_connectivity (per-voxel BFS from declared exterior doors) ────────
# Spec: scratch/evaluation_specs/voxel_connectivity.md.
# Three signals: (a) seed from master_plan.connectors.doors, (b) per-voxel
# reachability of interior air (exterior detected via complementary flood-fill),
# (c) vertical traversability via *_stairs / ladder / vine / open trapdoor.
_VOXEL_CONN_STAIRS_RX     = re.compile(r"_stairs$")
_VOXEL_CONN_LADDER_RX     = re.compile(r"^(ladder|vine)$")
_VOXEL_CONN_FENCE_GATE_RX = re.compile(r"_fence_gate$")
def _is_vertical_passable(src: tuple[int, int, int],
                          dst: tuple[int, int, int],
                          vmap: dict) -> bool:
    """True iff a player can traverse src → dst when |Δy| == 1.

    Allowed mechanisms (spec §5-6):
      * ``_stairs`` at src OR dst (step up/down: ramp into or out of)
      * ladder/vine at src or dst (climbable column)
      * open ``*_trapdoor`` at src or dst with an adjacent ladder/vine column

    Horizontal moves (dy=0) trivially return True.
    """
    if dst[1] == src[1]:
        return True
    bid_dst = vmap.get(dst)
    bid_src = vmap.get(src)
    # Stairs act as a ramp: passing into a stair-cell from below or out of
    # a stair-cell to the upper floor both count as one Δy step.
    for bid in (bid_src, bid_dst):
        if bid and _VOXEL_CONN_STAIRS_RX.search(_bare(bid)):
            return True
    # Ladder / vine columns: presence at either end is enough.
    for bid in (bid_src, bid_dst):
        if bid and _VOXEL_CONN_LADDER_RX.search(_bare(bid)):
            return True
    # Open trapdoor sitting at the boundary of a ladder column. Spec §6
    # accepts: trapdoor open with a ladder/vine directly above OR below it,
    # or a ladder/vine in any horizontal neighbour at the same y.
    for cell, bid in ((dst, bid_dst), (src, bid_src)):
        if not bid:
            continue
        bare = _bare(bid)
        if not _TRAPDOOR_RX.search(bare):
            continue
        if _blockstate(bid).get("open") != "true":
            continue
        x, y, z = cell
        # vertical neighbours (ladder above or below the trapdoor)
        for ny in (y - 1, y + 1):
            adj_v = vmap.get((x, ny, z))
            if adj_v and _VOXEL_CONN_LADDER_RX.search(_bare(adj_v)):
                return True
        # horizontal neighbours at the same y
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            adj = vmap.get((x + dx, y, z + dz))
            if adj and _VOXEL_CONN_LADDER_RX.search(_bare(adj)):
                return True
    return False


def _voxel_connectivity(doc: dict, vmap: dict,
                        design_intent, master_plan) -> dict:
    """Door-reachability of room interior air (robust, hole-tolerant).

    Spec intent: "can a player walk from an exterior door to every interior
    space?"  Interior air = air cells inside each room's AABB (walls are
    solid and so excluded automatically), read from ``bot_decomposition``.
    Each interior cell is tagged with its room.  A 6-conn BFS is seeded at
    the interior cells near every exterior door and may:

      * move freely **within the same room**,
      * step onto a passable connector block (door / trapdoor / open
        fence-gate / ladder-vine / stair),
      * cross to another room **only through a door port** (interior cells
        within Chebyshev ≤2 of a planned door) — never through an unplanned
        wall hole, because moving between two different rooms' air cells is
        forbidden unless a door joins them.

    This decouples the metric from the fragile exterior flood-fill that
    collapsed whenever the envelope had a single gap (wall holes are
    penalised separately by structural_integrity).  Open courtyards
    (``function``/``role`` == "courtyard") are treated as outdoor and
    excluded from the interior denominator.

    Per-room status is reported for traceability:
      ``reachable`` | ``blocked`` (has interior + a door but unreachable,
      e.g. furniture-blocked) | ``no_interior`` (room is solid/degenerate) |
      ``no_door`` (no connector references the room).
    """
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    if not storeys:
        return {"score": None, "notes": "no bot_decomposition"}
    if not vmap:
        return {"score": None, "notes": "empty vmap"}
    bbox = doc.get("bounding_box") or {}
    size = bbox.get("size")
    if not (isinstance(size, list) and len(size) == 3):
        return {"score": None, "notes": "missing or malformed bounding_box"}
    try:
        W, H, D = int(size[0]), int(size[1]), int(size[2])
    except (TypeError, ValueError):
        return {"score": None, "notes": "missing or malformed bounding_box"}
    if W <= 0 or H <= 0 or D <= 0:
        return {"score": None, "notes": "degenerate bbox"}

    # ── 1. Room interior air (full AABB minus solids); tag each cell. ──
    cell_room: dict = {}
    room_cells: dict = {}
    room_order: list = []
    for s in storeys:
        for sp in s.get("spaces") or []:
            a = sp.get("aabb")
            rid = sp.get("id")
            if rid is None or not (isinstance(a, list) and len(a) == 6):
                continue
            fn = (sp.get("function") or sp.get("role") or "").lower()
            if "courtyard" in fn:        # open/semi-outdoor → not interior
                continue
            cells: set = set()
            for x in range(a[0], a[3]):
                for y in range(a[1], a[4]):
                    for z in range(a[2], a[5]):
                        c = (x, y, z)
                        if c not in vmap and c not in cell_room:
                            cells.add(c)
                            cell_room[c] = rid
            room_cells[rid] = cells
            room_order.append(rid)

    interior_air = set(cell_room.keys())
    total = len(interior_air)
    doors = ((master_plan or {}).get("connectors") or {}).get("doors") or []
    rooms_with_door: set = set()
    for d in doors:
        for r in (d.get("between") or []):
            rooms_with_door.add(r)

    if total == 0:
        per_room = [{"room_id": rid, "status": "no_interior",
                     "interior_cells": 0, "reached_cells": 0}
                    for rid in room_order]
        return {"score": 0.0,
                "notes": "no room interior air — rooms are solid/degenerate",
                "per_room": per_room,
                "unreachable_rooms": list(room_order)}

    # ── 2. Door ports: interior cells within Chebyshev ≤2 of a door. A door
    # teleports between all its ports, so the flood crosses walls only at
    # planned openings. Exterior-door ports are the BFS seeds. ──
    from collections import defaultdict as _dd
    door_ports: list = []
    for d in doors:
        at = d.get("at") or d.get("pos")
        if not (isinstance(at, list) and len(at) == 3):
            continue
        try:
            dx0, dy0, dz0 = int(at[0]), int(at[1]), int(at[2])
        except (TypeError, ValueError):
            continue
        ports = {c for c in interior_air
                 if abs(c[0] - dx0) <= 2 and abs(c[1] - dy0) <= 2
                 and abs(c[2] - dz0) <= 2}
        is_ext = "outside" in (d.get("between") or [])
        door_ports.append((ports, is_ext))
    cell_doors: dict = _dd(list)
    for i, (ports, _ext) in enumerate(door_ports):
        for c in ports:
            cell_doors[c].append(i)
    seeds: set = set()
    seed_doors = 0
    for ports, is_ext in door_ports:
        if is_ext:
            seed_doors += 1
            seeds |= ports

    if not seeds:
        per_room = [{"room_id": rid,
                     "status": ("no_interior" if not room_cells[rid]
                                else ("no_door" if rid not in rooms_with_door
                                      else "blocked")),
                     "interior_cells": len(room_cells[rid]),
                     "reached_cells": 0}
                    for rid in room_order]
        note = ("no exterior door reachable (opens onto no room interior cell)"
                if seed_doors else "no exterior door declared")
        return {"score": 0.0, "notes": note,
                "per_room": per_room,
                "unreachable_rooms": list(room_order)}

    # ── 3. BFS: free within a room; cross rooms only via door ports/stairs. ──
    def _passable(cell) -> bool:
        bid = vmap.get(cell)
        if bid is None:
            return False
        bare = _bare(bid)
        st = _blockstate(bid)
        return (bool(_DOOR_RX.search(bare))
                or bool(_TRAPDOOR_RX.search(bare))
                or (bool(_VOXEL_CONN_FENCE_GATE_RX.search(bare))
                    and st.get("open") == "true")
                or bool(_VOXEL_CONN_LADDER_RX.search(bare))
                or bool(_VOXEL_CONN_STAIRS_RX.search(bare)))

    visited: set = set(seeds)
    queue: deque = deque(visited)
    while queue:
        x, y, z = queue.popleft()
        cur = (x, y, z)
        cur_room = cell_room.get(cur)
        # Door teleport: jump to every co-port of any door this cell joins.
        for di in cell_doors.get(cur, ()):
            for p in door_ports[di][0]:
                if p not in visited:
                    visited.add(p)
                    queue.append(p)
        for dx, dy, dz in ((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                           (0, -1, 0), (0, 0, 1), (0, 0, -1)):
            n = (x + dx, y + dy, z + dz)
            if n in visited:
                continue
            if n in interior_air:
                # within-room move, or entering a room from a connector cell
                if cur_room is not None and cell_room[n] != cur_room:
                    continue
            elif not _passable(n):
                continue
            # 2-voxel head clearance: the cell above the target must be air
            # or a passable architectural element.
            up = (n[0], n[1] + 1, n[2])
            if up in vmap:
                ub = _bare(vmap[up])
                if not (_DOOR_RX.search(ub) or _TRAPDOOR_RX.search(ub)
                        or _VOXEL_CONN_LADDER_RX.search(ub)
                        or _VOXEL_CONN_STAIRS_RX.search(ub)):
                    continue
            if dy != 0 and not _is_vertical_passable((x, y, z), n, vmap):
                continue
            visited.add(n)
            queue.append(n)

    reached = visited & interior_air
    # Connectivity = reachable FLOOR POSITIONS (a player walks, it cannot fly).
    # Key each position by (room, x, z): counting one cell per room-column stops
    # tall open rooms (cathedral naves, tower shafts) being penalised for
    # ceiling air nobody could stand in — while keying by ROOM keeps stacked
    # storeys distinct, so an unreachable upper floor still counts as missed
    # (their x,z overlap would otherwise hide it).
    all_cols = {(cell_room[c], c[0], c[2]) for c in interior_air}
    reached_cols = {(cell_room[c], c[0], c[2]) for c in reached}
    score = (len(reached_cols) / len(all_cols)) if all_cols else 0.0

    # ── 4. Per-room traceability (by column / floor position). ──
    per_room = []
    unreachable_rooms = []
    for rid in room_order:
        cells = room_cells[rid]
        rcols = {(x, z) for (x, _, z) in cells}
        rreached = {(x, z) for (x, _, z) in (cells & reached)}
        if not cells:
            status = "no_interior"
        elif rreached:
            status = "reachable"
        elif rid not in rooms_with_door:
            status = "no_door"
        else:
            status = "blocked"
        if status != "reachable":
            unreachable_rooms.append(rid)
        per_room.append({
            "room_id": rid,
            "status": status,
            "interior_cells": len(rcols),
            "reached_cells": len(rreached),
        })

    return {"score": round(score, 3),
            "notes": f"{len(reached_cols)}/{len(all_cols)} floor positions "
                     f"reached via doors from {seed_doors} exterior door(s)",
            "per_room": per_room,
            "unreachable_rooms": unreachable_rooms}

# ──────── vertical_clearance (refined) ────────
_VC_PLAYER_HEIGHT = 2          # blk; hitbox 1.8 → 2 blk libres erguido (Wiki Player)
_VC_CROUCH = 1.5               # blk; sneak 1.5 m
_VC_NON_CEILING_RX = re.compile(
    r"(_trapdoor$|_carpet$|_banner$|_wall_banner$|^air$|^cave_air$|^void_air$|"
    r"_sapling$|_flower$|tall_grass$|_button$|_pressure_plate$|torch$)"
)


def _VC_is_ceiling_solid(bid: str | None) -> bool:
    """True iff `bid` counts as a ceiling/floor solid for clearance purposes.

    None (no entry in vmap) and the families listed in `_VC_NON_CEILING_RX`
    (trapdoors, carpets, banners, flowers, buttons, plates, torches…) are
    treated as non-solid: they cannot bound a habitable column.
    """
    if bid is None:
        return False
    return _VC_NON_CEILING_RX.search(_bare(bid)) is None


def _VC_first_solid_from_below(vmap, x, z, y_range) -> int | None:
    """First y in `y_range` (iterated low→high) whose block is ceiling-solid."""
    for y in y_range:
        if _VC_is_ceiling_solid(vmap.get((x, y, z))):
            return y
    return None


def _VC_first_solid_above(vmap, x, z, y_range) -> int | None:
    """First y in `y_range` (iterated low→high) whose block is ceiling-solid.

    Same semantics as `_VC_first_solid_from_below`; the distinct name marks
    intent at call site (scanning *above* a known floor toward the ceiling).
    """
    for y in y_range:
        if _VC_is_ceiling_solid(vmap.get((x, y, z))):
            return y
    return None


def _vertical_clearance(doc: dict, vmap: dict) -> dict:
    """Per-room habitable clearance: floor→ceiling per column, mean over room.

    For each column (x,z) inside the room AABB, find the first ceiling-solid
    block from below (floor_y) and the first ceiling-solid above floor_y
    (ceil_y). The column clearance is `ceil_y - floor_y - 1` (empty voxels
    between floor and ceiling). Columns without a detectable floor *or*
    ceiling are skipped (open courtyards do not contribute). Rooms with no
    detectable column return `per_room[id] is None` and are excluded from the
    aggregate score. The output also reports `min_clearance` and
    `p10_clearance` as diagnostics for isolated low spots (e.g. hanging
    beams) that the mean would otherwise mask.
    """
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    if not storeys:
        return {"score": None, "notes": "no bot_decomposition",
                "per_room": {}, "lowest_room": None,
                "min_clearance": None, "p10_clearance": None}
    per_room: dict = {}
    room_scores: list[float] = []
    all_clear: list[int] = []
    lowest = (None, math.inf)
    for storey in storeys:
        for sp in storey.get("spaces") or []:
            a = sp.get("aabb")
            sid = sp.get("id")
            if not (isinstance(a, list) and len(a) == 6):
                continue
            clearances: list[int] = []
            # AABB half-open. Measure INTERIOR columns only: inset by the wall
            # thickness (1) so the perimeter wall ring — solid floor-to-ceiling,
            # clearance 0 — isn't averaged into the room's habitable headroom.
            # A genuinely solid interior still scores 0 (not hidden).
            ix0, ix1 = ((a[0] + 1, a[3] - 1) if a[3] - a[0] > 2 else (a[0], a[3]))
            iz0, iz1 = ((a[2] + 1, a[5] - 1) if a[5] - a[2] > 2 else (a[2], a[5]))
            for x in range(ix0, ix1):
                for z in range(iz0, iz1):
                    floor_y = _VC_first_solid_from_below(
                        vmap, x, z, range(a[1], a[4]))
                    if floor_y is None:
                        continue
                    ceil_y = _VC_first_solid_above(
                        vmap, x, z, range(floor_y + 1, a[4]))
                    if ceil_y is None:
                        continue
                    clearances.append(ceil_y - floor_y - 1)
            if not clearances:
                per_room[sid] = None
                continue
            mean_h = sum(clearances) / len(clearances)
            per_room[sid] = round(mean_h, 2)
            all_clear.extend(clearances)
            rs = (1.0 if mean_h >= _VC_PLAYER_HEIGHT
                  else (0.5 if mean_h >= _VC_CROUCH else 0.0))
            room_scores.append(rs)
            if mean_h < lowest[1]:
                lowest = (sid, mean_h)
    if not room_scores:
        return {"score": None,
                "notes": "no rooms with detectable floor/ceiling",
                "per_room": per_room, "lowest_room": None,
                "min_clearance": None, "p10_clearance": None}
    sorted_c = sorted(all_clear)
    p10 = sorted_c[max(0, len(sorted_c) // 10)]
    return {
        "score": round(sum(room_scores) / len(room_scores), 3),
        "notes": (f"lowest mean {lowest[1]:.1f} in {lowest[0]}; "
                  f"min={min(all_clear)} p10={p10}"),
        "per_room": per_room,
        "lowest_room": lowest[0],
        "min_clearance": min(all_clear),
        "p10_clearance": p10,
    }


def _door_functionality(doc: dict, vmap: dict) -> dict:
    """Each door has air on front and back."""
    doors = [(c, b) for c, b in vmap.items() if _DOOR_RX.search(_bare(b))]
    if not doors:
        return {"score": None, "notes": "no doors"}
    facing_to_delta = {"north": (0,0,-1), "south": (0,0,1), "east": (1,0,0), "west": (-1,0,0)}
    blocked = []
    total_score = 0.0
    counted = 0
    for (x, y, z), bid in doors:
        st = _blockstate(bid)
        if st.get("half") == "upper":
            continue  # only count lower half to avoid double-counting
        facing = st.get("facing", "north")
        delta = facing_to_delta.get(facing, (0, 0, -1))
        front = (x+delta[0], y+delta[1], z+delta[2])
        back  = (x-delta[0], y-delta[1], z-delta[2])
        front_free = front not in vmap
        back_free  = back not in vmap
        if front_free and back_free:
            total_score += 1.0
        elif front_free or back_free:
            total_score += 0.5
            blocked.append({"coord": [x, y, z], "side": "front" if back_free else "back"})
        else:
            blocked.append({"coord": [x, y, z], "side": "both"})
        counted += 1
    if not counted:
        return {"score": None, "notes": "no lower-half doors"}
    return {"score": round(total_score / counted, 3),
            "notes": f"{len(blocked)} of {counted} doors blocked",
            "blocked_doors": blocked[:10]}


# ── light_coverage helpers (added; _LIGHT_RX above kept intact) ──
_LIGHT_COV_EMISSION: dict[str, int] = {
    "glowstone": 15, "sea_lantern": 15, "jack_o_lantern": 15, "lantern": 15,
    "shroomlight": 15, "beacon": 15, "campfire": 15, "redstone_lamp": 15,
    "torch": 14, "wall_torch": 14, "end_rod": 14,
    "soul_torch": 10, "soul_wall_torch": 10, "soul_lantern": 10, "soul_campfire": 10,
    "furnace": 13, "smoker": 13, "blast_furnace": 13,
    "redstone_torch": 7, "redstone_wall_torch": 7,
    "magma_block": 3,
}
# Need block_state.lit == "true" to emit
_LIGHT_COV_LIT_REQUIRED: set[str] = {
    "redstone_lamp", "redstone_torch", "redstone_wall_torch",
    "furnace", "smoker", "blast_furnace",
}
# Emit by default; only excluded when block_state.lit == "false"
_LIGHT_COV_LIT_DEFAULT_ON: set[str] = {"campfire", "soul_campfire"}
# Blocks that propagate light with attenuation 1/block (same as air)
_LIGHT_COV_TRANSPARENT: set[str] = {
    "glass", "glass_pane", "iron_bars",
    "ice", "packed_ice", "blue_ice", "frosted_ice",
    "water",
    # leaves and stained glass matched by regex suffix below
}
_LIGHT_COV_TRANSPARENT_RX = re.compile(
    r"_stained_glass(_pane)?$|_leaves$"
)


def _light_cov_emission(bid: str) -> int:
    """Resolve light emission for a block_id (with optional [blockstate])."""
    bare = _bare(bid)
    base = _LIGHT_COV_EMISSION.get(bare, 0)
    if base == 0:
        return 0
    state = _blockstate(bid)
    if bare in _LIGHT_COV_LIT_REQUIRED and state.get("lit") != "true":
        return 0
    if bare in _LIGHT_COV_LIT_DEFAULT_ON and state.get("lit") == "false":
        return 0
    return base


def _light_cov_is_transparent(bid: str) -> bool:
    """True if light propagates through this block with attenuation 1/block."""
    bare = _bare(bid)
    return bare in _LIGHT_COV_TRANSPARENT or bool(_LIGHT_COV_TRANSPARENT_RX.search(bare))


def _light_coverage(doc: dict, vmap: dict) -> dict:
    """Interior air <= (emission-8) Manhattan from a light source (per-source radius).

    Multi-source BFS; transparent blocks (glass/ice/water/leaves) propagate with
    attenuation 1/block. Honors block_state.lit on redstone_lamp / redstone_torch
    / furnace / smoker / blast_furnace / campfire.
    """
    if not vmap:
        return {"score": 1.0, "notes": "empty voxel map", "dark_voxels_count": 0}
    W, H, D = doc["bounding_box"]["size"]

    # 1) Collect effective sources (coord, emission)
    sources: list[tuple[tuple[int, int, int], int]] = []
    for coord, bid in vmap.items():
        e = _light_cov_emission(bid)
        if e > 0:
            sources.append((coord, e))

    # 2) Multi-source BFS with per-source radius = max(0, e - 8)
    # dist[cell] = min light-cost reached so far (lower is better)
    dist: dict[tuple[int, int, int], int] = {}
    q: deque = deque()
    for coord, e in sources:
        dist[coord] = 0
        q.append((coord, 0, max(0, e - 8)))
    while q:
        p, d, r = q.popleft()
        # `r` is the radius of the source that put this entry on the queue.
        # If `dist[p]` has improved since enqueue, skip stale.
        if dist.get(p, 10**9) < d:
            continue
        if d >= r:
            continue
        x, y, z = p
        for dx, dy, dz in ((1,0,0),(-1,0,0),(0,1,0),(0,-1,0),(0,0,1),(0,0,-1)):
            nx, ny, nz = x+dx, y+dy, z+dz
            if not (0 <= nx < W and 0 <= ny < H and 0 <= nz < D):
                continue
            nb = vmap.get((nx, ny, nz))
            if nb is not None and not _light_cov_is_transparent(nb):
                continue  # opaque solid blocks light
            nd = d + 1
            if dist.get((nx, ny, nz), 10**9) <= nd:
                continue
            dist[(nx, ny, nz)] = nd
            q.append(((nx, ny, nz), nd, r))

    # 3) Interior = air cells strictly below the topmost filled y of their column
    columns_top: dict[tuple[int, int], int] = {}
    for (x, y, z) in vmap:
        if columns_top.get((x, z), -1) < y:
            columns_top[(x, z)] = y
    interior_total = 0
    interior_dark = 0
    dark_examples: list[list[int]] = []
    for x in range(W):
        for z in range(D):
            ymax = columns_top.get((x, z), -1)
            if ymax <= 0:
                continue
            for y in range(ymax):
                if (x, y, z) in vmap:
                    continue
                interior_total += 1
                if (x, y, z) not in dist:
                    interior_dark += 1
                    if len(dark_examples) < 10:
                        dark_examples.append([x, y, z])
    if interior_total == 0:
        return {"score": 1.0, "notes": "no interior space", "dark_voxels_count": 0}
    score = (interior_total - interior_dark) / interior_total
    return {
        "score": round(score, 3),
        "notes": f"{interior_dark} dark of {interior_total} interior cells",
        "dark_voxels_count": interior_dark,
        "dark_voxels_examples": dark_examples,
    }


_CREATIVE_ONLY = {
    "barrier", "structure_block", "structure_void", "jigsaw_block", "jigsaw",
    "command_block", "chain_command_block", "repeating_command_block",
    "light_block", "debug_stick", "spawner",
}

# Prefijos 1.17+ no permitidos en paleta 1.16.5.
# IMPORTANTE: el prefijo poroso "moss" se eliminó (rechazaba mossy_cobblestone
# y mossy_stone_bricks, ambos 1.16-nativos); moss_block / moss_carpet se
# cubren ahora como entradas exactas mediante el prefix completo.
_POST_1_16_PREFIXES = (
    # 1.17 Caves & Cliffs I
    "deepslate_", "cobbled_deepslate", "calcite", "tuff", "smooth_basalt",
    "dripstone_block", "pointed_dripstone",
    "amethyst_block", "budding_amethyst", "amethyst_cluster",
    "small_amethyst_bud", "medium_amethyst_bud", "large_amethyst_bud",
    "tinted_glass", "lightning_rod",
    "copper_", "waxed_", "oxidized_", "weathered_", "exposed_",
    "powder_snow", "rooted_dirt", "hanging_roots", "spore_blossom",
    "cave_vines", "glow_lichen", "glow_berries", "glow_ink_sac",
    "azalea", "flowering_azalea",
    "moss_block", "moss_carpet",
    "big_dripleaf", "small_dripleaf", "candle",
    "raw_iron_block", "raw_copper_block", "raw_gold_block",
    # 1.19 Wild
    "sculk", "mangrove_", "mud", "packed_mud", "mud_brick",
    "reinforced_deepslate", "frogspawn",
    "ochre_froglight", "verdant_froglight", "pearlescent_froglight",
)


def _block_legitimacy(doc: dict) -> dict:
    raw = doc.get("block_palette") or {}
    entries = list(raw.values()) if isinstance(raw, dict) else list(raw)
    creative, post, invalid = [], [], []
    for bid in entries:
        bare = _bare(bid)
        if bare in _CREATIVE_ONLY:
            creative.append(bid); invalid.append(bid)
        elif any(bare.startswith(p) for p in _POST_1_16_PREFIXES):
            post.append(bid); invalid.append(bid)
    total = max(len(entries), 1)
    score = 1.0 - len(invalid) / total
    return {"score": round(score, 3),
            "notes": f"{len(invalid)} invalid of {len(entries)} palette entries",
            "invalid_blocks": sorted(set(invalid)),
            "creative_only_blocks": sorted(set(creative)),
            "post_1_16_blocks": sorted(set(post))}


def _material_consistency(doc: dict, vmap: dict) -> dict:
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    if not storeys:
        return {"score": None, "notes": "no bot_decomposition"}
    per_room = {}
    room_scores = []
    for storey in storeys:
        for sp in storey.get("spaces") or []:
            a = sp.get("aabb")
            if not (isinstance(a, list) and len(a) == 6):
                continue
            fam_count = Counter()
            for x in range(a[0], a[3]):
                for y in range(a[1], a[4]):
                    for z in range(a[2], a[5]):
                        b = vmap.get((x, y, z))
                        if b:
                            fam = _family(_bare(b))
                            if fam != "other":
                                fam_count[fam] += 1
            total = sum(fam_count.values())
            if total == 0:
                continue
            significant = sum(1 for f, n in fam_count.items() if n / total >= 0.1)
            # RELAJADO (2026-05-31): una paleta deliberada de acento (primary +
            # secondary + floor + roof + accent + molduras) es elaboración, no
            # incoherencia. Solo se penaliza el caos real (>6 familias).
            if significant <= 5:
                rs = 1.0
            elif significant == 6:
                rs = 0.7
            elif significant == 7:
                rs = 0.4
            else:
                rs = 0.2
            per_room[sp.get("id")] = {
                "dominant": fam_count.most_common(1)[0][0] if fam_count else None,
                "n_families": significant,
                "score": rs,
            }
            room_scores.append(rs)
    if not room_scores:
        return {"score": None, "notes": "no rooms scored"}
    return {"score": round(sum(room_scores)/len(room_scores), 3),
            "notes": f"{len(room_scores)} rooms evaluated",
            "per_room": per_room}


# ---------------------------------------------------------------------------
# volume_density — calibrado al corpus RAG-E (n=2746 buildings, 4.7M voxels;
# fuente: scratch/material_frequencies.json + recalculo audit académico).
# Stats: median=0.218, p25/p75=0.123/0.330, p05/p95=0.025/0.500.
# Justificación de la ventana en informe_seguimiento.tex §Limitaciones.
# ---------------------------------------------------------------------------
_VOL_DENSITY_LO_OK         = 0.12   # p25 — borde inferior ventana óptima
_VOL_DENSITY_HI_OK         = 0.33   # p75 — borde superior ventana óptima
_VOL_DENSITY_LO_ZERO       = 0.05   # p05 — debajo: score=0 (cage/frame)
_VOL_DENSITY_HI_ZERO       = 0.50   # p95 — encima: score=0 (mausoleo)
_VOL_DENSITY_SMALL_LO_OK   = 0.08   # rama permissive: bbox<100 celdas
_VOL_DENSITY_SMALL_HI_OK   = 0.45
_VOL_DENSITY_SMALL_LO_ZERO = 0.02
_VOL_DENSITY_SMALL_HI_ZERO = 0.70
_VOL_DENSITY_SMALL_BBOX    = 100    # umbral W*H*D para activar rama permissive


def _volume_density(doc: dict, vmap: dict) -> dict:
    # 1. Bounding box robusto
    try:
        size = doc["bounding_box"]["size"]
        W, H, D = int(size[0]), int(size[1]), int(size[2])
    except (KeyError, TypeError, ValueError, IndexError):
        return {"score": 0.0, "notes": "missing or malformed bounding_box",
                "solid_ratio": 0.0, "total_cells": 0, "solid_blocks": 0}

    total = W * H * D
    if total <= 0:
        return {"score": 0.0, "notes": "degenerate bbox",
                "solid_ratio": 0.0, "total_cells": 0, "solid_blocks": 0}

    # 2. Ratio + clamp explícito para input corrupto
    solid = len(vmap) if vmap is not None else 0
    corrupt = solid > total
    ratio = min(solid / total, 1.0) if total > 0 else 0.0

    # 3. Selección de thresholds (rama small-building según spec)
    if total < _VOL_DENSITY_SMALL_BBOX:
        lo_ok, hi_ok = _VOL_DENSITY_SMALL_LO_OK, _VOL_DENSITY_SMALL_HI_OK
        lo_z,  hi_z  = _VOL_DENSITY_SMALL_LO_ZERO, _VOL_DENSITY_SMALL_HI_ZERO
        regime = "small"
    else:
        lo_ok, hi_ok = _VOL_DENSITY_LO_OK, _VOL_DENSITY_HI_OK
        lo_z,  hi_z  = _VOL_DENSITY_LO_ZERO, _VOL_DENSITY_HI_ZERO
        regime = "default"

    # 4. Rampa lineal piecewise
    if lo_ok <= ratio <= hi_ok:
        score = 1.0
    elif ratio <= lo_z or ratio >= hi_z:
        score = 0.0
    elif ratio < lo_ok:
        denom = (lo_ok - lo_z) or 1.0
        score = max(0.0, min(1.0, (ratio - lo_z) / denom))
    else:  # hi_ok < ratio < hi_z
        denom = (hi_z - hi_ok) or 1.0
        score = max(0.0, min(1.0, (hi_z - ratio) / denom))

    # 5. Notes
    notes = f"solid ratio {ratio:.3f} [{regime} regime]"
    if corrupt:
        notes += " [corrupt: solid>total, clamped]"

    return {"score": round(float(score), 3),
            "notes": notes,
            "solid_ratio": round(ratio, 3),
            "total_cells": total,
            "solid_blocks": solid}


def _norm_wall(w):
    """Normalize wall direction tokens (``north``/``N``/``n``) → ``n``.

    Returns one of ``{"n","s","e","w"}`` for recognised inputs; otherwise the
    first char of the lowercased input (``""`` if input is empty/None).
    """
    w = (w or "").strip().lower()
    return {"north": "n", "south": "s", "east": "e", "west": "w"}.get(w, w[:1])


def _light_on_two_sides(doc: dict, vmap: dict, master_plan) -> dict:
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    if not storeys:
        return {"score": None, "notes": "no bot_decomposition"}

    rooms = []
    for storey in storeys:
        for sp in storey.get("spaces") or []:
            a = sp.get("aabb")
            if isinstance(a, list) and len(a) == 6:
                rooms.append((sp.get("id"), sp.get("function"), a))
    if not rooms:
        return {"score": None, "notes": "no rooms"}

    # --- FIX 1: index master_plan.connectors.windows (preferred over voxel scan)
    windows_by_room: dict[str, set[str]] = {}
    mp_windows = ((master_plan or {}).get("connectors") or {}).get("windows") or []
    for w in mp_windows:
        rid_in = w.get("in_room") or w.get("room")
        wall = _norm_wall(w.get("wall") or w.get("facing"))
        if rid_in and wall in ("n", "s", "e", "w"):
            windows_by_room.setdefault(rid_in, set()).add(wall)

    def has_glass_in_wall(room_aabb, wall):
        a = room_aabb
        if wall == "n":   xs, ys, zs = range(a[0],a[3]), range(a[1],a[4]), [a[2]]
        elif wall == "s": xs, ys, zs = range(a[0],a[3]), range(a[1],a[4]), [a[5]-1]
        elif wall == "w": xs, ys, zs = [a[0]],          range(a[1],a[4]), range(a[2],a[5])
        else:             xs, ys, zs = [a[3]-1],        range(a[1],a[4]), range(a[2],a[5])
        for x in xs:
            for y in ys:
                for z in zs:
                    b = vmap.get((x, y, z))
                    if b and _GLASS_RX.search(_bare(b)):
                        return True
        return False

    # --- FIX 3: compare by rid, not by aabb value (handles duplicate AABBs)
    def is_exterior_wall(rid, room_aabb, wall):
        a = room_aabb
        for (orid, _, ob) in rooms:
            if orid == rid:
                continue
            if wall == "n" and ob[5] == a[2] and not (ob[3] <= a[0] or ob[0] >= a[3]):
                return False
            if wall == "s" and ob[2] == a[5] and not (ob[3] <= a[0] or ob[0] >= a[3]):
                return False
            if wall == "w" and ob[3] == a[0] and not (ob[5] <= a[2] or ob[2] >= a[5]):
                return False
            if wall == "e" and ob[0] == a[3] and not (ob[5] <= a[2] or ob[2] >= a[5]):
                return False
        return True

    per_room: dict = {}
    scored: list[tuple[float, float]] = []
    for (rid, fn, a) in rooms:
        ext_walls = [w for w in ("n", "s", "e", "w") if is_exterior_wall(rid, a, w)]
        if len(ext_walls) < 2:
            per_room[rid] = {"n_exterior_walls": len(ext_walls),
                             "room_score": None,
                             "note": "interior room, excluded"}
            continue
        mp_walls = windows_by_room.get(rid, set())
        used_mp = bool(mp_walls) or (rid in windows_by_room)
        if used_mp:
            windows_walls = len(mp_walls & set(ext_walls))
            source = "master_plan"
        else:
            windows_walls = sum(1 for w in ext_walls if has_glass_in_wall(a, w))
            source = "glass_scan"
        rs = 1.0 if windows_walls >= 2 else (0.5 if windows_walls == 1 else 0.0)
        # --- FIX 2: weight=0.5 for narrow rooms (<3 in either XZ dim)
        weight = 0.5 if (a[3] - a[0] < 3 or a[5] - a[2] < 3) else 1.0
        per_room[rid] = {"n_exterior_walls": len(ext_walls),
                         "n_walls_with_windows": windows_walls,
                         "room_score": rs,
                         "weight": weight,
                         "source": source}
        scored.append((rs, weight))

    if not scored:
        return {"score": None,
                "notes": "no rooms with 2+ exterior walls",
                "per_room": per_room,
                "pattern_id": "light-on-two-sides"}
    num = sum(rs * w for rs, w in scored)
    den = sum(w for _, w in scored)
    return {"score": round(num / den, 3),
            "notes": f"{len(scored)} rooms evaluated",
            "per_room": per_room,
            "pattern_id": "light-on-two-sides"}


_ENTRY_FUNCTIONS = {"entry_hall", "entry-hall", "hallway", "foyer", "vestibule"}


def _aabbs_adjacent(a, b):
    """True iff AABBs share a non-degenerate face (half-open convention)."""
    if a[3] == b[0] or b[3] == a[0]:
        return not (a[5] <= b[2] or a[2] >= b[5]) and not (a[4] <= b[1] or a[1] >= b[4])
    if a[5] == b[2] or b[5] == a[2]:
        return not (a[3] <= b[0] or a[0] >= b[3]) and not (a[4] <= b[1] or a[1] >= b[4])
    if a[4] == b[1] or b[4] == a[1]:
        return not (a[3] <= b[0] or a[0] >= b[3]) and not (a[5] <= b[2] or a[2] >= b[5])
    return False


def _aabbs_near(a, b, gap: int = 2) -> bool:
    """Adyacencia TOLERANTE: dos salas son contiguas si sus caras X o Z están a
    ≤`gap` celdas (grosor del muro que las separa) y solapan en los otros ejes.
    `_aabbs_adjacent` exige contacto EXACTO y por eso fallaba con salas separadas
    por un muro de 1 celda (el caso normal) → grafo de salas vacío."""
    def overlap(lo1, hi1, lo2, hi2):
        return min(hi1, hi2) > max(lo1, lo2)
    yov = overlap(a[1], a[4], b[1], b[4])
    if not yov:
        return False
    # vecinas en X: gap entre caras X, solapando en Z
    gx = max(b[0] - a[3], a[0] - b[3])
    if -1 <= gx <= gap and overlap(a[2], a[5], b[2], b[5]):
        return True
    # vecinas en Z: gap entre caras Z, solapando en X
    gz = max(b[2] - a[5], a[2] - b[5])
    if -1 <= gz <= gap and overlap(a[0], a[3], b[0], b[3]):
        return True
    return False


def _aabbs_vertically_linked(a, b, tol: int = 1) -> bool:
    """True si dos salas están en plantas consecutivas (la y1 de una ≈ la y0 de
    la otra) y sus footprints XZ se SOLAPAN → unidas por la escalera/forjado.
    Permite que el grafo de salas alcance las plantas altas en multi-planta."""
    xz_overlap = (min(a[3], b[3]) > max(a[0], b[0]) and
                  min(a[5], b[5]) > max(a[2], b[2]))
    consecutive = abs(a[4] - b[1]) <= tol or abs(b[4] - a[1]) <= tol
    return xz_overlap and consecutive


def _find_entry_room(rooms, master_plan, bbox, graph):
    """Cascade: outside-door → entry-function → boundary-touch → max-degree.

    `rooms` is a list of (rid, function, aabb). `graph` is a dict adjacency list.
    Returns the room id chosen as the BFS source.
    """
    doors = ((master_plan or {}).get("connectors") or {}).get("doors") or []
    room_ids = {rid for rid, _, _ in rooms}
    # (1) door with "outside" endpoint (schema uses `between: [a, b]`)
    for d in doors:
        btw = d.get("between") or []
        if "outside" not in btw:
            continue
        for endpoint in btw:
            if endpoint != "outside" and endpoint in room_ids:
                return endpoint
    # (2) function-based entry
    for rid, fn, _ in rooms:
        if fn in _ENTRY_FUNCTIONS:
            return rid
    # (3) AABB touching bbox boundary
    if bbox and isinstance(bbox.get("size"), list) and len(bbox["size"]) == 3:
        origin = bbox.get("origin") or [0, 0, 0]
        if isinstance(origin, list) and len(origin) == 3:
            ox, oy, oz = origin
            W, H, D = bbox["size"]
            for rid, _, a in rooms:
                if a is None or len(a) != 6:
                    continue
                if (a[0] == ox or a[3] == ox + W
                        or a[2] == oz or a[5] == oz + D):
                    return rid
    # (4) max-degree node (fallback)
    return max(room_ids, key=lambda r: len(graph.get(r, ())))


def _intimacy_gradient(doc: dict, master_plan=None) -> dict:
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    rooms = [(sp.get("id"), sp.get("function"), sp.get("aabb"))
             for s in storeys for sp in (s.get("spaces") or [])
             if sp.get("id") is not None]
    if len(rooms) < 2:
        return {"score": None, "notes": "<2 rooms",
                "pattern_id": "intimacy-gradient"}

    priv = {rid: _PRIVACY.get(fn) for rid, fn, _ in rooms}
    unknown_n = sum(1 for v in priv.values() if v is None)
    if unknown_n > len(rooms) / 2:
        return {"score": None,
                "notes": f"unknown functions dominate ({unknown_n}/{len(rooms)})",
                "pattern_id": "intimacy-gradient"}

    room_ids = {rid for rid, _, _ in rooms}
    graph = {rid: set() for rid in room_ids}
    doors = ((master_plan or {}).get("connectors") or {}).get("doors") or []
    # Schema uses `between: [a, b]`; treat any door with both endpoints inside
    # room_ids as an internal door.
    internal_doors = []
    for d in doors:
        btw = d.get("between") or []
        if len(btw) == 2 and btw[0] in room_ids and btw[1] in room_ids:
            internal_doors.append(btw)
    # Grafo de circulación. Fuente PRIMARIA = puertas internas declaradas (si
    # las hay y conectan bien, definen la circulación → respetar el gradiente).
    # Pero el grafo de puertas en v4 suele ser INCOMPLETO (no toda sala contigua
    # tiene puerta declarada) y NO cruza plantas → dejaba 60-84% de salas
    # "desconectadas" y el gradiente sin calcular. Por eso, si las puertas no
    # conectan a la mayoría, AUMENTAMOS con adyacencia geométrica (salas que
    # comparten muro, o apiladas en plantas consecutivas vía escalera).
    for a, b in internal_doors:
        graph[a].add(b)
        graph[b].add(a)

    def _largest_component_fraction(g) -> float:
        if not g:
            return 0.0
        seen, best = set(), 0
        for start in g:
            if start in seen:
                continue
            comp, stack = 0, [start]
            while stack:
                c = stack.pop()
                if c in seen:
                    continue
                seen.add(c); comp += 1
                stack.extend(g[c])
            best = max(best, comp)
        return best / len(g)

    door_frac = _largest_component_fraction(graph) if internal_doors else 0.0
    if door_frac >= 0.6:
        graph_source = "doors"
    else:
        graph_source = "doors+geometry" if internal_doors else "geometry"
        for i, (ra, _, aa) in enumerate(rooms):
            if aa is None or len(aa) != 6:
                continue
            for rb, _, ab in rooms[i + 1:]:
                if ab is None or len(ab) != 6:
                    continue
                if (_aabbs_near(aa, ab) or _aabbs_vertically_linked(aa, ab)):
                    graph[ra].add(rb)
                    graph[rb].add(ra)

    entry_rid = _find_entry_room(rooms, master_plan,
                                 doc.get("bounding_box"), graph)
    dist = {entry_rid: 0}
    q = deque([entry_rid])
    while q:
        cur = q.popleft()
        for nb in graph[cur]:
            if nb not in dist:
                dist[nb] = dist[cur] + 1
                q.append(nb)

    ids = [rid for rid, _, _ in rooms
           if priv[rid] is not None and rid in dist]
    disconnected_n = len(rooms) - sum(1 for rid, _, _ in rooms if rid in dist)
    disconnected_fraction = round(disconnected_n / len(rooms), 3)
    # Need >=3 connected privacy-typed rooms AND most rooms connected. A
    # Spearman gradient over 2 rooms is meaningless, and scoring over a small
    # connected subset while most rooms are unreachable was producing a
    # misleading 1.0. Report disconnected_fraction so the caller sees WHY.
    if len(ids) < 3 or disconnected_fraction > 0.5:
        return {"score": None,
                "notes": (f"insufficient connected rooms "
                          f"(n={len(ids)}, disconnected_fraction="
                          f"{disconnected_fraction}); graph_source={graph_source}"),
                "disconnected_fraction": disconnected_fraction,
                "pattern_id": "intimacy-gradient"}

    pv = [priv[i] for i in ids]
    dv = [dist[i] for i in ids]
    rx = rankdata(pv, method="average")
    ry = rankdata(dv, method="average")
    n = len(ids)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    den = math.sqrt(sum((rx[i] - mx) ** 2 for i in range(n))
                    * sum((ry[i] - my) ** 2 for i in range(n)))
    rho = num / den if den > 0 else 0.0
    if math.isnan(rho):
        rho = 0.0
    score = (rho + 1) / 2

    per_room = {rid: {"privacy_level": priv[rid],
                      "graph_distance": dist.get(rid)}
                for rid, _, _ in rooms if priv[rid] is not None}
    return {"score": round(score, 3),
            "spearman": round(rho, 3),
            "notes": (f"graph_source={graph_source} entry={entry_rid} "
                      f"unknowns={unknown_n} n={n} "
                      f"disconnected_fraction={disconnected_fraction}"),
            "disconnected_fraction": disconnected_fraction,
            "per_room": per_room,
            "pattern_id": "intimacy-gradient"}


def _common_areas_at_heart(doc: dict) -> dict:
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    rooms = [(sp.get("id"), sp.get("function"), sp.get("aabb"))
              for s in storeys for sp in (s.get("spaces") or [])
              if isinstance(sp.get("aabb"), list) and len(sp.get("aabb")) == 6]
    if not rooms:
        return {"score": None, "notes": "no rooms"}
    # Centroid of building from room centroids
    centroids = [((a[0]+a[3])/2, (a[2]+a[5])/2) for _, _, a in rooms]
    bx = sum(c[0] for c in centroids) / len(centroids)
    bz = sum(c[1] for c in centroids) / len(centroids)
    W, _, D = doc["bounding_box"]["size"]
    max_dim = max(W, D, 1)

    def norm_dist(c):
        return math.sqrt((c[0]-bx)**2 + (c[1]-bz)**2) / max_dim

    common_dists = [norm_dist(centroids[i]) for i, (_, fn, _) in enumerate(rooms) if fn in _COMMON_ROLES]
    private_dists = [norm_dist(centroids[i]) for i, (_, fn, _) in enumerate(rooms) if fn in _PRIVATE_ROLES]
    if not common_dists or not private_dists:
        return {"score": None, "notes": "missing common or private rooms"}
    cmd = sum(common_dists)/len(common_dists)
    pmd = sum(private_dists)/len(private_dists)
    # 0.5-centred: equal distances → 0.5 (neutral); private farther than
    # common (the desired gradient) → >0.5; common pushed to the periphery
    # → <0.5. The old (pmd-cmd)/0.3 mapping started at 0 and demanded an
    # implausibly large 0.3-normalised gap, pinning real layouts near 0.1.
    score = max(0.0, min(1.0, 0.5 + (pmd - cmd) / 0.4))
    return {"score": round(score, 3),
            "notes": (f"common_dist={cmd:.2f} private_dist={pmd:.2f} "
                      f"gradient={pmd - cmd:+.2f}"),
            "common_mean_dist": round(cmd, 3),
            "private_mean_dist": round(pmd, 3),
            "n_common": len(common_dists),
            "n_private": len(private_dists),
            "pattern_id": "common-areas-at-the-heart"}


_ROOF_TERRAIN = {"grass_block", "dirt", "grass_path", "dirt_path",
                 "coarse_dirt", "podzol", "sand", "stone", "water"}


def _roof_wall_split(vmap: dict):
    """Split a build into walls vs roof by the cross-sectional AREA profile.

    Walls keep a roughly CONSTANT footprint with height; a roof (gable, hip,
    spire, dome, …) SHRINKS with height. So the wall top is the highest y whose
    occupied-column count is still ≥60% of the max — above it is the roof zone.
    This is robust to tall/pointed roofs (the old y_max-relative bands measured
    the ridge point and wrongly scored tall roofs ≈ 0).

    Returns (wall_top_y, footprint_cols, roof_proj_cols) or None.
    """
    if not vmap:
        return None
    ys = [y for (_, y, _) in vmap]
    y_min, y_max = min(ys), max(ys)
    cols_at: dict[int, set] = {}
    foot: set = set()
    for (x, y, z), b in vmap.items():
        if _bare(b) in _ROOF_TERRAIN and y <= y_min + 1:    # skip ground pad
            continue
        cols_at.setdefault(y, set()).add((x, z))
        foot.add((x, z))
    if not foot:
        return None
    areas = {y: len(c) for y, c in cols_at.items()}
    max_area = max(areas.values()) or 1
    wall_top = y_min
    for y in range(y_min, y_max + 1):
        if areas.get(y, 0) >= 0.6 * max_area:
            wall_top = y
    roof_proj: set = set()
    for y in range(wall_top + 1, y_max + 1):
        roof_proj |= cols_at.get(y, set())
    return wall_top, foot, roof_proj, cols_at


def _sheltering_roof(doc: dict, vmap: dict) -> dict:
    """A sheltering roof is a real, pitched roof mass that covers the building
    and ideally overhangs it (eaves). Measured relative to the wall line so a
    tall pointed roof (spire/cone/tower) scores HIGH, not ≈0 as the old
    ridge-only overhang did.
      flat roof (no pitch)        → 0.4   (covers, but doesn't shelter)
      pitched roof                → 0.5 + 0.3·min(1,(h-1)/4) + 0.2·overhang
    """
    if not vmap:
        return {"score": None, "notes": "empty"}
    split = _roof_wall_split(vmap)
    if split is None:
        return {"score": None, "notes": "empty"}
    wall_top, foot, roof_proj, _cols_at = split
    if not foot:
        return {"score": 0.0, "notes": "no footprint"}
    y_max = max(y for (_, y, _) in vmap)
    roof_height = y_max - wall_top
    overhang = len(roof_proj - foot) / max(1, len(foot))
    overhang_s = min(1.0, overhang / 0.3)
    if roof_height <= 1:                         # flat / parapet
        score = 0.4 + 0.1 * overhang_s
    else:
        score = 0.5 + 0.3 * min(1.0, (roof_height - 1) / 4.0) + 0.2 * overhang_s
    score = max(0.0, min(1.0, score))
    return {"score": round(score, 3),
            "notes": f"roof_height={roof_height} overhang={overhang:.2f} "
                     f"(wall_top={wall_top})",
            "roof_height": roof_height,
            "overhang_ratio": round(overhang, 3),
            "pattern_id": "sheltering-roof"}


def _building_edge(doc: dict, vmap: dict) -> dict:
    if not vmap:
        return {"score": None, "notes": "empty"}
    W, H, D = doc["bounding_box"]["size"]
    y_ground = min(y for (_, y, _) in vmap)
    # Footprint = columns that RISE (a block at y>=ground+2): walls/structure.
    # Using rising columns (not any low block) keeps the edge ring fixed:
    # placing ground-level treatment (stairs/slabs/paths at y=ground) no longer
    # joins the footprint and pushes the ring outward — the old paradox that
    # pinned this metric at 0.0.
    structural_fp = {(x, z) for (x, y, z) in vmap
                     if y >= y_ground + 2
                     and _bare(vmap[(x, y, z)]) != "grass_block"}
    if not structural_fp:
        return {"score": None, "notes": "no rising structure for footprint"}
    # Perimeter = footprint columns with at least one non-footprint 8-neighbour.
    perimeter = {(x, z) for (x, z) in structural_fp
                 if any((x + dx, z + dz) not in structural_fp
                        for dx in (-1, 0, 1) for dz in (-1, 0, 1)
                        if not (dx == 0 and dz == 0))}
    if not perimeter:
        return {"score": None, "notes": "no perimeter (degenerate footprint)"}
    # A perimeter cell is "treated" if there is an apron block (stairs / slab /
    # path / gravel / carpet / flower_pot / fence / lantern — NOT wall
    # materials) at ground level in the cell itself or a Chebyshev-1 neighbour.
    # We do NOT exclude structural cells: the roof-overhang the envelope lays
    # makes the apron columns structural, so excluding them mis-counted to 0.
    treated = 0
    for (px, pz) in perimeter:
        hit = False
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                nx, nz = px + dx, pz + dz
                for y in (y_ground, y_ground + 1):
                    b = vmap.get((nx, y, nz))
                    if b and _EDGE_APRON_RX.search(_bare(b)):
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        if hit:
            treated += 1
    score = treated / len(perimeter)
    return {"score": round(score, 3),
            "notes": f"{treated} of {len(perimeter)} perimeter cells "
                     f"have adjacent edge treatment",
            "edge_blocks_treated": treated,
            "total_edge_blocks": len(perimeter),
            "pattern_id": "building-edge"}


def _window_place(doc: dict, vmap: dict) -> dict:
    windows = [c for c, b in vmap.items() if _GLASS_RX.search(_bare(b))]
    if not windows:
        return {"score": None, "notes": "no windows"}
    with_seating = 0
    lonely = []
    for (x, y, z) in windows:
        found = False
        for dx in (-3, -2, -1, 0, 1, 2, 3):
            for dz in (-3, -2, -1, 0, 1, 2, 3):
                for dy in (-1, 0):
                    if dx == 0 and dz == 0 and dy == 0:
                        continue
                    b = vmap.get((x+dx, y+dy, z+dz))
                    if b and _SEATING_RX.search(_bare(b)):
                        found = True
                        break
                if found: break
            if found: break
        if found:
            with_seating += 1
        elif len(lonely) < 10:
            lonely.append([x, y, z])
    score = with_seating / len(windows)
    return {"score": round(score, 3),
            "notes": f"{with_seating} of {len(windows)} windows have seating",
            "windows_total": len(windows),
            "windows_with_seating": with_seating,
            "lonely_windows": lonely,
            "pattern_id": "window-place"}


def _entrance_transition(doc: dict, master_plan) -> dict:
    if not master_plan:
        return {"score": None, "notes": "no master_plan"}
    doors = (master_plan.get("connectors") or {}).get("doors") or []
    ext_doors = [d for d in doors if "outside" in (d.get("between") or [])]
    if not ext_doors:
        return {"score": None, "notes": "no outside doors in connectors"}
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    rid_to_fn = {sp.get("id"): sp.get("function")
                 for s in storeys for sp in (s.get("spaces") or [])}
    scores = []
    first_rooms = []
    fn_map = {
        "entry-hall": 1.0, "entry_hall": 1.0, "hallway": 1.0, "courtyard": 1.0, "great-hall": 1.0, "great_hall": 1.0,
        "living-room": 0.7, "living_room": 0.7, "dining-room": 0.7, "dining_room": 0.7, "kitchen": 0.7,
        "library": 0.4, "study": 0.4, "chapel": 0.4,
        "bedroom": 0.0, "bathroom": 0.0, "nursery": 0.0,
    }
    for d in ext_doors:
        other = [r for r in (d.get("between") or []) if r != "outside"]
        if not other: continue
        first_rid = other[0]
        fn = rid_to_fn.get(first_rid, "other")
        scores.append(fn_map.get(fn, 0.5))
        first_rooms.append({"room_id": first_rid, "function": fn})
    if not scores:
        return {"score": None, "notes": "could not identify first rooms"}
    return {"score": round(min(scores), 3),  # worst-case if multi-door
            "notes": f"first rooms: {first_rooms}",
            "first_rooms": first_rooms,
            "pattern_id": "entrance-transition"}


def _main_entrance(doc: dict, vmap: dict = None, master_plan=None) -> dict:
    if not master_plan:
        return {"score": None, "notes": "no master_plan", "pattern_id": "main-entrance"}
    if not vmap:
        return {"score": None, "notes": "empty vmap", "pattern_id": "main-entrance"}
    doors = (master_plan.get("connectors") or {}).get("doors") or []
    ext = [d for d in doors if "outside" in (d.get("between") or [])]
    if not ext:
        return {"score": None, "notes": "no outside doors", "pattern_id": "main-entrance"}

    # 1. Building footprint = the union of ROOM AABBs (bot_decomposition).
    # Using rising structural columns wrongly swept in exterior features —
    # perimeter walls, corner towers, garden structures — which inflated the
    # footprint so the building's own entrance landed "interior" (score 0.3).
    # The rooms are the building; exterior props are not.
    y_ground = min(y for (_, y, _) in vmap)
    fp = set()
    for s in ((doc.get("bot_decomposition") or {}).get("building") or {}).get("storeys") or []:
        for sp in s.get("spaces") or []:
            a = sp.get("aabb")
            if isinstance(a, list) and len(a) == 6:
                for x in range(int(a[0]), int(a[3])):
                    for z in range(int(a[2]), int(a[5])):
                        fp.add((x, z))
    if not fp:                                       # fallback: rising structure
        fp = {(x, z) for (x, y, z) in vmap
              if y >= y_ground + 2 and _bare(vmap[(x, y, z)]) != "grass_block"}
    if not fp:
        return {"score": None, "notes": "no building footprint", "pattern_id": "main-entrance"}
    x0, x1 = min(x for x, _ in fp), max(x for x, _ in fp)
    z0, z1 = min(z for _, z in fp), max(z for _, z in fp)

    # 2. Primary facades: the long walls. North/south walls run along X so
    # their length is the X-span; east/west walls run along Z. For a (near-)
    # square footprint there is no geometric "front", so ALL four walls are
    # primary and prominence is judged purely by entrance markers — this
    # removes the old bug that defaulted square buildings to south and scored
    # every real entrance as "lateral" (0.5).
    ns_len = x1 - x0 + 1     # length of the north & south walls
    ew_len = z1 - z0 + 1     # length of the east & west walls
    square = abs(ns_len - ew_len) <= 1
    if square:
        primary = {"north", "south", "east", "west"}
    elif ns_len > ew_len:
        primary = {"north", "south"}
    else:
        primary = {"east", "west"}

    margin = _MAIN_ENTRANCE_FRONT_MARGIN

    def door_walls(at):
        x, _, z = at
        hits = []
        if abs(z - z1) <= margin: hits.append("south")
        if abs(z - z0) <= margin: hits.append("north")
        if abs(x - x1) <= margin: hits.append("east")
        if abs(x - x0) <= margin: hits.append("west")
        return hits

    R = _MAIN_ENTRANCE_MARKER_RADIUS

    def n_markers(at):
        x, y, z = at
        n = 0
        for dx in range(-R, R + 1):
            for dy in range(-R, R + 1):
                for dz in range(-R, R + 1):
                    b = vmap.get((x + dx, y + dy, z + dz))
                    if not b:
                        continue
                    bare = _bare(b)
                    if _MAIN_ENTRANCE_MARKER_RX.match(bare):
                        n += 1
                    elif _MAIN_ENTRANCE_STAIR_RX.search(bare) and _stair_faces_door(
                            (x + dx, y + dy, z + dz), _blockstate(b), at):
                        n += 1
        return n

    best = None
    for d in ext:
        at = d.get("at")
        if at is None or len(at) != 3:
            continue
        walls = door_walls(at)
        nm = n_markers(at)
        on_primary = any(w in primary for w in walls)
        if not walls:
            s = 0.3                       # door not near any exterior wall
            wall_label = "interior?"
        elif on_primary:
            s = 1.0 if nm >= 1 else 0.7    # on a primary facade
            wall_label = next(w for w in walls if w in primary)
        else:
            s = 0.6 if nm >= 1 else 0.4    # on a secondary (short) wall
            wall_label = walls[0]
        cand = {"score": s, "door_wall": wall_label,
                "n_markers_nearby": nm, "at": at,
                "on_primary_facade": on_primary}
        if best is None or s > best["score"]:
            best = cand
    if best is None:
        return {"score": None, "notes": "outside doors lack 'at'",
                "pattern_id": "main-entrance"}

    fac = "square (all facades primary)" if square else (
        "north/south" if "north" in primary else "east/west")
    notes = (f"primary_facade={fac}; n_outside_doors={len(ext)}; "
             f"chosen_at={best['at']}; door_wall={best['door_wall']}; "
             f"markers={best['n_markers_nearby']}")
    return {"score": round(best["score"], 3),
            "door_wall": best["door_wall"],
            "n_markers_nearby": best["n_markers_nearby"],
            "on_primary_facade": best["on_primary_facade"],
            "notes": notes,
            "pattern_id": "main-entrance"}


def _farmhouse_kitchen(doc: dict, vmap: dict, master_plan) -> dict:
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    kitchen = None
    rooms = []
    for s in storeys:
        for sp in (s.get("spaces") or []):
            rooms.append(sp)
            if sp.get("function") == "kitchen":
                kitchen = sp
    if not kitchen:
        return {"score": None, "notes": "no kitchen"}
    a = kitchen.get("aabb")
    if not (isinstance(a, list) and len(a) == 6):
        return {"score": None, "notes": "kitchen has no aabb"}
    # Sub 1: cooking elements
    COOK = {"furnace", "smoker", "blast_furnace", "cauldron", "crafting_table"}
    seen_cook = set()
    for x in range(a[0], a[3]):
        for y in range(a[1], a[4]):
            for z in range(a[2], a[5]):
                b = vmap.get((x, y, z))
                if b:
                    bare = _bare(b)
                    if bare in COOK:
                        seen_cook.add(bare)
    if len(seen_cook) >= 3: cook_s = 1.0
    elif len(seen_cook) == 2: cook_s = 0.7
    elif len(seen_cook) == 1: cook_s = 0.4
    else: cook_s = 0.0
    # Sub 2: eating space — slab/lectern/table-like within or adjacent
    eat_s = 0.0
    for dx in range(-3, a[3] - a[0] + 3):
        for dz in range(-3, a[5] - a[2] + 3):
            x, z = a[0] + dx, a[2] + dz
            for y in range(a[1], a[4]):
                b = vmap.get((x, y, z))
                if b and _SEATING_RX.search(_bare(b)):
                    eat_s = 1.0; break
            if eat_s: break
        if eat_s: break
    # Sub 3: adjacency to common area (master_plan.connectors)
    adj_s = 0.0
    if master_plan:
        doors = (master_plan.get("connectors") or {}).get("doors") or []
        kitchen_id = kitchen.get("id")
        common_ids = {sp.get("id") for sp in rooms if sp.get("function") in _COMMON_ROLES and sp.get("id") != kitchen_id}
        for d in doors:
            btw = d.get("between") or []
            if kitchen_id in btw and any(o in common_ids for o in btw):
                adj_s = 1.0
                break
    score = (cook_s + eat_s + adj_s) / 3
    return {"score": round(score, 3),
            "notes": f"cook={cook_s:.1f} eat={eat_s:.1f} adj={adj_s:.1f}",
            "subs": {"cooking": cook_s, "eating": eat_s, "common_adjacency": adj_s},
            "pattern_id": "the-farmhouse-kitchen"}


def _roof_layout(doc: dict, vmap: dict) -> dict:
    """Roof coverage of the footprint + a modest articulation bonus.

    The old heuristic (footprint-corner count vs distinct stair facings)
    collapsed to 1/1 → 1.0 for every box and never discriminated. We instead
    measure whether the building is actually capped: for each footprint
    column, does its topmost block reach the upper height band (so the
    interior is roofed, not open to the sky)?  A small bonus rewards pitched
    roofs (distinct stair facings) without punishing legitimately flat roofs.
    """
    if not vmap:
        return {"score": None, "notes": "empty"}
    try:
        W, H, D = doc["bounding_box"]["size"]
    except (KeyError, TypeError, ValueError, IndexError):
        return {"score": None, "notes": "missing bounding_box"}
    y_max = max(y for (_, y, _) in vmap)
    y_ground = min(y for (_, y, _) in vmap)
    if y_max < 2:
        return {"score": 0.0, "notes": "no roof (building too flat)"}
    # Topmost block per BUILDING column (exclude the grass/dirt terrain slab,
    # which otherwise floods the footprint with low-topped columns and tanks
    # coverage).
    col_top: dict = {}
    for (x, y, z), b in vmap.items():
        if _bare(b) in _ROOF_TERRAIN and y <= y_ground + 1:
            continue
        if col_top.get((x, z), -1) < y:
            col_top[(x, z)] = y
    if not col_top:
        return {"score": None, "notes": "no footprint"}
    # "Roofed" = the building cross-section at the wall line is capped by a
    # roof above. Use the wall/roof split and the BUILDING footprint at the
    # wall line (cols_at[wall_top]) as the denominator — this excludes ground
    # props (trees, apron, garden), which otherwise tanked coverage, and works
    # for tall pointed roofs whose ridge is far above the eaves.
    split = _roof_wall_split(vmap)
    if split:
        wall_top, _foot, _roof_proj, cols_at = split
        bldg_fp = cols_at.get(wall_top) or set(col_top)
    else:
        wall_top = y_max - max(2, H // 4)
        bldg_fp = set(col_top)
    covered = sum(1 for c in bldg_fp if col_top.get(c, -1) >= wall_top)
    coverage = covered / max(1, len(bldg_fp))
    roof_depth = max(2, H // 4)
    # Articulation: distinct stair facings in the roof band (pitched roofs).
    facings = set()
    for (x, y, z), b in vmap.items():
        if y >= y_max - roof_depth and _bare(b).endswith("_stairs"):
            st = _blockstate(b)
            if "facing" in st:
                facings.add(st["facing"])
    articulation = min(len(facings), 2) / 2.0   # 0 / 0.5 / 1.0
    score = 0.8 * coverage + 0.2 * articulation
    return {"score": round(score, 3),
            "notes": (f"roof_coverage={coverage:.2f} "
                      f"stair_facings={len(facings)}"),
            "roof_coverage": round(coverage, 3),
            "stair_facings": len(facings),
            "pattern_id": "roof-layout"}


# ────────────────────────────────────────────────────────────────────────
#  Composite aggregation
# ────────────────────────────────────────────────────────────────────────

# FÍSICA = corrección estructural + habitabilidad (calidad del edificio EN SÍ,
# independiente del prompt). La adecuación al prompt vive en su propio apartado
# (_PROMPT_WEIGHTS) para no mezclar CALIDAD con FIDELIDAD (controlabilidad).
_PHYSICAL_WEIGHTS = {
    # PHYSICAL = sólo corrección ESTRUCTURAL (independiente del uso/estética).
    "structural_integrity": 0.40, "voxel_connectivity": 0.35,
    "volume_density": 0.15, "block_legitimacy": 0.10,
}
# INTERIOR = habitabilidad + aprovechamiento del espacio + muebles + relación de
# salas (las NO-Alexander). `space_utilization` y `room_size` son NUEVAS.
_INTERIOR_WEIGHTS = {
    "space_utilization": 0.20, "room_size": 0.18, "room_furnishing": 0.18,
    "vertical_clearance": 0.16, "light_coverage": 0.16,
    "material_consistency": 0.06, "door_functionality": 0.06,
}
# EXTERIOR = integridad de la envolvente (muros/perímetro PLANEADOS completos).
_EXTERIOR_WEIGHTS = {
    "envelope_integrity": 1.0,
}
# APARTADO PROMPT-ADHERENCE = fidelidad del edificio al texto pedido (salas,
# muebles tipo 'camas pedidas vs generadas', material/color, nº de plantas).
_PROMPT_WEIGHTS = {
    "generation_success": 0.30,   # ★ ¿es un edificio coherente y usable?
    "room_count": 0.25, "materials": 0.15, "floors": 0.15, "furniture": 0.15,
}
_ALEXANDER_WEIGHTS = {
    "intimacy_gradient": 0.15, "light_on_two_sides": 0.13, "main_entrance": 0.12,
    "entrance_transition": 0.10, "common_areas_at_heart": 0.10, "farmhouse_kitchen": 0.08,
    "sheltering_roof": 0.08, "window_place": 0.08, "building_edge": 0.08, "roof_layout": 0.08,
}
_OVERALL_WEIGHTS = (0.55, 0.45)  # (physical, alexander)
_SCORE_PRECISION = 3

# metric_id → skill_category(ies) most responsible for the deficit. Used to
# point the worst_metrics traceability summary at the part of the pipeline a
# fix should target. Canonical source; tools/gym/diagnose.py imports this.
_METRIC_TO_SKILL_CATEGORY: dict[str, list[str]] = {
    "structural_integrity":   ["global_silhouette"],
    "voxel_connectivity":     ["connector_template", "floor_layout"],
    "vertical_clearance":     ["room_role", "floor_layout"],
    "door_functionality":     ["connector_template"],
    "light_coverage":         ["room_decoration"],
    "block_legitimacy":       [],
    "material_consistency":   ["room_decoration", "wall_fitting"],
    "volume_density":         ["global_silhouette"],
    "envelope_integrity":     ["wall_fitting", "global_silhouette"],
    "room_furnishing":        ["room_role", "room_decoration"],
    "prompt_adherence":       ["floor_layout", "room_role"],
    "light_on_two_sides":     ["wall_fitting", "floor_layout"],
    "intimacy_gradient":      ["room_role", "floor_layout"],
    "common_areas_at_heart":  ["floor_layout", "room_role"],
    "sheltering_roof":        ["global_silhouette"],
    "building_edge":          ["exterior_feature"],
    "window_place":           ["wall_fitting", "room_decoration"],
    "entrance_transition":    ["connector_template", "room_role"],
    "main_entrance":          ["connector_template", "global_silhouette"],
    "farmhouse_kitchen":      ["room_decoration", "connector_template"],
    "roof_layout":            ["global_silhouette"],
    # apariencia → skills que mejoran la elaboración visual
    "facade_articulation":    ["wall_fitting", "room_decoration", "exterior_feature"],
    "fine_detail":            ["room_decoration", "wall_fitting"],
    "silhouette_complexity":  ["global_silhouette", "exterior_feature"],
    "decoration_density":     ["room_decoration"],
    "material_richness":      ["room_decoration", "wall_fitting"],
}
# ── Provenance / soporte bibliográfico de cada métrica ──────────────────────
# Para que la evaluación sea INFORMATIVA (saber qué aspecto —exterior/interior—
# mide cada número) y DEFENDIBLE ante el tribunal (cada métrica apoyada en
# trabajo previo). `scope` permite el tratamiento posterior por agrupación.
#   scope ∈ {structural, interior, exterior, prompt}
# Las 10 métricas de Alexander citan su patrón en *A Pattern Language* (1977).
_METRIC_META: dict[str, dict] = {
    # — Física / estructural y habitabilidad —
    "structural_integrity":   {"axis": "physical", "scope": "structural",
        "measures": "estabilidad física: todo sólido soportado hasta y=0 (nada flotante)",
        "source": "Validez de generación procedimental con restricciones; cf. Merrell et al., 'Model Synthesis' (2010)"},
    "voxel_connectivity":     {"axis": "physical", "scope": "structural",
        "measures": "navegabilidad: cada sala alcanzable por el grafo de circulación",
        "source": "Accesibilidad por alcanzabilidad de grafo; cf. Hillier & Hanson, 'Space Syntax' (1984)"},
    "vertical_clearance":     {"axis": "physical", "scope": "interior",
        "measures": "altura libre habitable sobre el suelo de cada sala",
        "source": "Ergonomía/habitabilidad (códigos de edificación; altura mínima)"},
    "door_functionality":     {"axis": "physical", "scope": "interior",
        "measures": "las puertas conectan espacios y son transitables",
        "source": "Conectividad de circulación; cf. Alexander, A Pattern Language P.98"},
    "light_coverage":         {"axis": "physical", "scope": "interior",
        "measures": "cobertura de iluminación interior (anti-monstruos / habitabilidad)",
        "source": "Iluminación natural; cf. Alexander, A Pattern Language P.159"},
    "block_legitimacy":       {"axis": "physical", "scope": "structural",
        "measures": "todos los bloques existen en Minecraft Java 1.16.5",
        "source": "Validez respecto a la versión objetivo (1.16.5)"},
    "material_consistency":   {"axis": "physical", "scope": "both",
        "measures": "nº de familias de material acotado (paleta coherente)",
        "source": "Coherencia de paleta; cf. Ching, 'Architecture: Form, Space & Order'"},
    "volume_density":         {"axis": "physical", "scope": "structural",
        "measures": "razón sólido/vacío del volumen (ni hueco ni macizo)",
        "source": "Relación masa/vacío (poché / massing arquitectónico)"},
    "space_utilization":      {"axis": "interior", "scope": "interior",
        "measures": "las salas aprovechan el espacio (cobertura de su extensión; penaliza salas dispersas/escasas)",
        "source": "Eficiencia espacial / ocupación de planta; cf. space syntax (Hillier & Hanson 1984)"},
    "room_size":              {"axis": "interior", "scope": "interior",
        "measures": "tamaño interior de cada sala adecuado a su rol (ni degenerada ni inhabitable)",
        "source": "Habitabilidad / antropometría; cf. Neufert 'Architects' Data'"},
    "envelope_integrity":     {"axis": "physical", "scope": "exterior",
        "measures": "muros exteriores planeados realmente cerrados (sin huecos de fallo)",
        "source": "Envolvente del edificio (building science / cerramiento)"},
    "room_furnishing":        {"axis": "physical", "scope": "interior",
        "measures": "cada sala tiene el mueble clave de su función (dormitorio→cama, …)",
        "source": "Completitud funcional/affordances por actividad; cf. Alexander P.139, P.180; Gibson, 'affordances' (1979)"},
    # — Adecuación al prompt (FIDELIDAD / controlabilidad texto→3D) —
    "generation_success": {"axis": "prompt", "scope": "both",
        "measures": "edificio coherente y usable: navegable + cerrado por arriba + con entrada + estable",
        "source": "Coherencia semántica + traversabilidad; cf. SceneEval (2025); T3Bench (2023)"},
    "room_count":  {"axis": "prompt", "scope": "prompt",
        "measures": "salas PEDIDAS en el prompt presentes (conteo por rol: '4 bedrooms'→4)",
        "source": "Fidelidad texto→3D / controlabilidad; cf. CLIP-score (Hessel et al. 2021); text-conditioned generation eval"},
    "furniture":   {"axis": "prompt", "scope": "prompt",
        "measures": "muebles clave pedidos vs presentes (camas pedidas vs generadas, …)",
        "source": "Completitud funcional + fidelidad al prompt; cf. Gibson 'affordances' (1979)"},
    "materials":   {"axis": "prompt", "scope": "prompt",
        "measures": "el edificio usa el MATERIAL/COLOR pedido en el prompt",
        "source": "Fidelidad texto→3D (atributos de material/color); cf. CLIP-score (Hessel et al. 2021)"},
    "floors":      {"axis": "prompt", "scope": "prompt",
        "measures": "nº de PLANTAS pedido vs construido ('three-story'→3)",
        "source": "Fidelidad texto→3D (atributos estructurales)"},
    # — Patrones de Christopher Alexander (diseño interior/relación) —
    "intimacy_gradient":     {"axis": "alexander", "scope": "interior",
        "measures": "gradiente público→privado al adentrarse",
        "source": "Alexander, A Pattern Language (1977), Pattern 127 'Intimacy Gradient'"},
    "common_areas_at_heart": {"axis": "alexander", "scope": "interior",
        "measures": "zonas comunes en el corazón circulatorio",
        "source": "Alexander, A Pattern Language (1977), Pattern 129 'Common Areas at the Heart'"},
    "light_on_two_sides":    {"axis": "alexander", "scope": "interior",
        "measures": "salas con luz por dos lados (ventanas en ≥2 muros)",
        "source": "Alexander, A Pattern Language (1977), Pattern 159 'Light on Two Sides of Every Room'"},
    "sheltering_roof":       {"axis": "alexander", "scope": "exterior",
        "measures": "cubierta que cobija (presente y proporcionada)",
        "source": "Alexander, A Pattern Language (1977), Pattern 117 'Sheltering Roof'"},
    "building_edge":         {"axis": "alexander", "scope": "exterior",
        "measures": "borde del edificio habitable/transicional",
        "source": "Alexander, A Pattern Language (1977), Pattern 160 'Building Edge'"},
    "window_place":          {"axis": "alexander", "scope": "interior",
        "measures": "ventanas como lugar (no meros huecos)",
        "source": "Alexander, A Pattern Language (1977), Pattern 180 'Window Place'"},
    "entrance_transition":   {"axis": "alexander", "scope": "exterior",
        "measures": "transición gradual exterior→interior en la entrada",
        "source": "Alexander, A Pattern Language (1977), Pattern 112 'Entrance Transition'"},
    "main_entrance":         {"axis": "alexander", "scope": "exterior",
        "measures": "entrada principal clara y visible",
        "source": "Alexander, A Pattern Language (1977), Pattern 110 'Main Entrance'"},
    "farmhouse_kitchen":     {"axis": "alexander", "scope": "interior",
        "measures": "cocina amplia y central (si aplica al tipo)",
        "source": "Alexander, A Pattern Language (1977), Pattern 139 'Farmhouse Kitchen'"},
    "roof_layout":           {"axis": "alexander", "scope": "exterior",
        "measures": "disposición de cubierta coherente con la planta",
        "source": "Alexander, A Pattern Language (1977), Pattern 209 'Roof Layout'"},
    # — Apariencia (elaboración visual exterior/interior) —
    "facade_articulation":   {"axis": "appearance", "scope": "exterior",
        "measures": "relieve/articulación de fachada (salientes, ritmo)",
        "source": "Composición de fachada; cf. Ching, 'Architecture: Form, Space & Order'"},
    "fine_detail":           {"axis": "appearance", "scope": "both",
        "measures": "densidad de detalle fino (ornamento)",
        "source": "Riqueza visual / ornamento arquitectónico"},
    "decoration_density":    {"axis": "appearance", "scope": "interior",
        "measures": "densidad de decoración interior por volumen",
        "source": "Densidad de amueblado/decoración (ambientación interior)"},
    "silhouette_complexity": {"axis": "appearance", "scope": "exterior",
        "measures": "variedad de la silueta/roofline (masa 3D)",
        "source": "Complejidad de masa/skyline (composición volumétrica)"},
    "material_richness":     {"axis": "appearance", "scope": "both",
        "measures": "variedad de materiales (sin caer en incoherencia)",
        "source": "Riqueza de paleta material"},
}

# Metrics kept in the report for QA but EXCLUDED from the composite/gym signal
# (they do not discriminate generated builds). See evaluate().
# block_legitimacy is always 1.0; material_consistency / door_functionality /
# room_furnishing stay ~1.0 because they are satisfied by the deterministic
# architecture/connector stages (saturated BY DESIGN, not by the LLM) — they do
# not discriminate, so they are excluded from the composite (kept in the report).
_COMPOSITE_EXCLUDED: set[str] = {
    "block_legitimacy",        # siempre ~1.0 (todos los bloques existen)
    "material_consistency",    # ~1.0: paleta coherente por diseño del stage
    "door_functionality",      # ~1.0: conectores deterministas por diseño
    # room_furnishing YA NO se excluye: sin furnish.py determinista, refleja al
    # LLM (varía), y el usuario quiere puntuar los muebles por rol.
}

# Sanity asserts: each category must sum to 1.0 (tolerance for float arithmetic)
assert abs(sum(_PHYSICAL_WEIGHTS.values()) - 1.0) < 1e-9, "physical weights must sum to 1.0"
assert abs(sum(_INTERIOR_WEIGHTS.values()) - 1.0) < 1e-9, "interior weights must sum to 1.0"
assert abs(sum(_EXTERIOR_WEIGHTS.values()) - 1.0) < 1e-9, "exterior weights must sum to 1.0"
assert abs(sum(_ALEXANDER_WEIGHTS.values()) - 1.0) < 1e-9, "alexander weights must sum to 1.0"
assert abs(sum(_PROMPT_WEIGHTS.values()) - 1.0) < 1e-9, "prompt weights must sum to 1.0"


def _weighted_mean(
    metrics: dict, weights: dict
) -> tuple[float | None, dict, list[dict]]:
    """Weighted mean with null-skip + renormalization.

    Returns ``(total, effective_weights, skipped)`` where ``skipped`` is a list
    of ``{"name", "reason"}`` dicts. The reason is harvested from the metric
    report's ``notes`` field (the canonical field emitted by all metric
    functions in this module) and falls back to ``"null score"``.
    """
    skipped: list[dict] = []
    effective: dict[str, float] = {}
    total_w = 0.0
    acc = 0.0
    for k, w in weights.items():
        m = metrics.get(k, {})
        s = m.get("score")
        if s is None:
            reason = m.get("reason") or m.get("notes") or "null score"
            skipped.append({"name": k, "reason": reason})
            continue
        effective[k] = w
        total_w += w
        acc += w * s
    if not effective:
        return None, {}, skipped
    # Renormalize effective weights
    for k in effective:
        effective[k] = effective[k] / total_w
    return acc / total_w, effective, skipped


# ════════════════════════════════════════════════════════════════════════
#  ELABORATION / APPEARANCE  — recompensa la riqueza visual (estilo TFGv2).
#  Investigado en scratch/research_elaboration.py: los rasgos que separan un
#  edificio elaborado de una caja son la articulación de fachada, el detalle
#  fino, la complejidad de silueta/masa, la riqueza (acotada) de paleta y la
#  densidad de decoración. Targets calibrados un punto POR ENCIMA de la media
#  de TFGv2 → alcanzar 0.9 exige mejora real de los skills de apariencia.
# ════════════════════════════════════════════════════════════════════════
_ELAB_DETAIL_RX = re.compile(
    r"(_stairs$|_slab$|_wall$|_fence$|_fence_gate$|_trapdoor$|_pane$|iron_bars$|"
    r"_log$|_door$|banner$|lantern$|^torch$|chiseled|_button$|campfire$|"
    r"flower_pot$|candle$|cobblestone_wall$)")
_ELAB_DECOR_RX = re.compile(
    r"(bed$|chest$|barrel$|bookshelf$|lectern$|furnace$|smoker$|crafting_table$|"
    r"loom$|_table$|anvil$|cauldron$|lantern$|torch$|glowstone$|redstone_lamp$|"
    r"sea_lantern$|flower|potted|_carpet$|painting$|armor_stand$|sapling$|leaves$)")
_ELAB_FAMS = ("planks", "bricks", "cobblestone", "stone", "concrete", "terracotta",
              "quartz", "log", "deepslate", "sandstone", "andesite", "diorite",
              "granite", "wool", "wood", "prismarine", "purpur")
_ELAB_TARGETS = {"surf_detail": 0.30, "fp_nonrect": 0.40,
                 "detail_ratio": 0.24, "decor_ratio": 0.08}
# Pesos: priorizan los rasgos que CONTROLAN LOS SKILLS (fachada, detalle fino,
# decoración) sobre la silueta (que depende del global_designer, no de skills),
# de modo que 0.9 sea alcanzable mejorando skills de apariencia.
_APPEARANCE_WEIGHTS = {
    "facade_articulation":   0.34,
    "fine_detail":           0.26,
    "decoration_density":    0.16,
    "silhouette_complexity": 0.12,
    "material_richness":     0.12,
}
# Overall = 5 familias (SIN appearance: la belleza es subjetiva y se elimina).
#   physical = corrección estructural (soporte, navegabilidad, densidad, bloques)
#   alexander = los 10 patrones de Christopher Alexander
#   prompt    = fidelidad al texto pedido (salas/plantas/material) + generación
#   interior  = aprovechamiento del espacio, tamaño de sala, muebles, luz, clearance
#   exterior  = integridad de la envolvente (muros/perímetro planeados completos)
# La fidelidad al prompt (controllability) pesa más (cf. SceneEval 2025).
_OVERALL_WEIGHTS5 = {"physical": 0.20, "alexander": 0.15, "prompt": 0.30,
                     "interior": 0.20, "exterior": 0.15}
assert abs(sum(_OVERALL_WEIGHTS5.values()) - 1.0) < 1e-9, "overall5 weights must sum to 1.0"


def _elab_family(bn: str):
    for f in _ELAB_FAMS:
        if f in bn:
            return f
    return None


def _appearance(doc: dict, vmap: dict) -> dict:
    """5 sub-métricas 0-1 de elaboración visual. Reusa vmap del evaluador."""
    none = lambda: {"score": None, "notes": "empty"}
    if not vmap:
        return {k: none() for k in _APPEARANCE_WEIGHTS}
    solid = {c: _bare(b) for c, b in vmap.items()
             if _bare(b) not in _STRUCT_NON_SOLID}
    if not solid:
        return {k: none() for k in _APPEARANCE_WEIGHTS}
    cellset = set(vmap)
    ext_total = ext_detail = 0
    for (x, y, z), b in solid.items():
        if any((x+dx, y, z+dz) not in cellset
               for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))):
            ext_total += 1
            if _ELAB_DETAIL_RX.search(b):
                ext_detail += 1
    tot = len(vmap)
    surf_detail = ext_detail / max(1, ext_total)
    detail_ratio = sum(1 for b in vmap.values()
                       if _ELAB_DETAIL_RX.search(_bare(b))) / max(1, tot)
    decor_ratio = sum(1 for b in vmap.values()
                      if _ELAB_DECOR_RX.search(_bare(b))) / max(1, tot)
    topy: dict = {}
    miny = 10**9
    for (x, y, z) in solid:
        topy[(x, z)] = max(topy.get((x, z), -(10**9)), y)
        if y < miny:
            miny = y
    xs = [c[0] for c in solid]; zs = [c[2] for c in solid]
    bbox = (max(xs)-min(xs)+1) * (max(zs)-min(zs)+1)
    fp_nonrect = 1 - len(topy) / max(1, bbox)
    nf = len({f for f in (_elab_family(b) for b in solid.values()) if f})

    # Silueta = planta no-caja (L/U/patio) MEZCLADA con masa 3D (variación de la
    # línea de tejado: torres, tejados, dormers, setbacks). Un edificio con
    # roofline rica es elaborado aunque su planta sea rectangular; medir solo la
    # planta 2D penalizaba injustamente esos casos. Ambos son skill-addressable.
    tops = list(topy.values())
    mean_t = sum(tops) / len(tops)
    top_std = (sum((t - mean_t) ** 2 for t in tops) / len(tops)) ** 0.5
    height = max(tops) - miny + 1
    massing = max(0.0, min(1.0, (top_std / max(1, height)) / 0.28))

    def _n(v, t): return max(0.0, min(1.0, v / t))
    facade = _n(surf_detail, _ELAB_TARGETS["surf_detail"])
    fp_norm = _n(fp_nonrect, _ELAB_TARGETS["fp_nonrect"])
    silh = 0.45 * fp_norm + 0.55 * massing
    fine = _n(detail_ratio, _ELAB_TARGETS["detail_ratio"])
    decor = _n(decor_ratio, _ELAB_TARGETS["decor_ratio"])
    material = (0.3 * nf / 2 if nf <= 2 else
                1.0 if nf <= 6 else max(0.4, 1.0 - 0.12 * (nf - 6)))

    def mk(s, note): return {"score": round(float(s), 3), "notes": note}
    return {
        "facade_articulation":   mk(facade, f"{ext_detail}/{ext_total} ext detail (surf={surf_detail:.2f})"),
        "fine_detail":           mk(fine, f"detail_ratio={detail_ratio:.3f}"),
        "silhouette_complexity": mk(silh, f"fp_nonrect={fp_nonrect:.2f} massing={massing:.2f}"),
        "decoration_density":    mk(decor, f"decor_ratio={decor_ratio:.3f}"),
        "material_richness":     mk(material, f"{nf} material families"),
    }


_ENV_HORIZ = ((1, 0), (-1, 0), (0, 1), (0, -1))


def planned_exterior_walls(master_plan: dict | None) -> set:
    """Celdas (x,y,z) de muro de PERÍMETRO EXTERIOR que el diseño planeó (ops
    fill_hollow). Lo comparten el evaluador (métrica) y envelope_closer (cierre)."""
    ops = (master_plan or {}).get("ops") or []
    fh = [o for o in ops if o.get("kind") == "fill_hollow"
          and isinstance(o.get("aabb"), list) and len(o["aabb"]) == 6]
    if not fh:
        return set()
    occ: dict = {}
    for o in fh:
        x0, y0, z0, x1, y1, z1 = (int(v) for v in o["aabb"])
        for y in range(y0, y1):
            s = occ.setdefault(y, set())
            for x in range(x0, x1):
                for z in range(z0, z1):
                    s.add((x, z))
    walls = set()
    for o in fh:
        x0, y0, z0, x1, y1, z1 = (int(v) for v in o["aabb"])
        # y0 (floor slab) excluded; INCLUDE the top wall course (y1-1, just under
        # the roof) so a missing wall section beneath a roof IS detected.
        for y in range(y0 + 1, y1):
            layer = occ.get(y, set())
            for x in range(x0, x1):
                for z in range(z0, z1):
                    if not (x in (x0, x1 - 1) or z in (z0, z1 - 1)):
                        continue
                    if any((x + dx, z + dz) not in layer for dx, dz in _ENV_HORIZ):
                        walls.add((x, y, z))
    return walls


# rol → familias de bloque que cuentan como "amueblado para ese rol".
# Compartido con furnish.py (la pasada que garantiza estos muebles).
_ROLE_REQUIRED_FURNITURE = {
    "bedroom":  ("bed",), "nursery": ("bed",),
    "kitchen":  ("furnace", "smoker", "blast_furnace"),
    "bathroom": ("cauldron",),
    "library":  ("bookshelf",), "study": ("bookshelf",),
    "pantry":   ("barrel", "chest"),
}


def _room_furnishing(doc: dict, vmap: dict, master_plan: dict | None = None) -> dict:
    """Fracción de salas que tienen el MUEBLE CLAVE de su rol (dormitorio→cama,
    cocina→horno, baño→caldero, biblioteca/estudio→estantería, despensa→barril).
    Penaliza un dormitorio sin cama, etc. Solo cuenta salas con rol en el mapa."""
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    if not storeys:
        return {"score": None, "notes": "no bot_decomposition"}
    checked = 0
    furnished = 0
    missing = []
    import collections
    by_role_ok = collections.Counter()
    by_role_tot = collections.Counter()
    for st in storeys:
        for sp in st.get("spaces") or []:
            role = (sp.get("function") or "").strip().lower().replace("-", "_")
            fams = _ROLE_REQUIRED_FURNITURE.get(role)
            a = sp.get("aabb")
            if not fams or not (isinstance(a, list) and len(a) == 6):
                continue
            checked += 1
            by_role_tot[role] += 1
            x0, y0, z0, x1, y1, z1 = a
            has = any(any(f in _bare(b) for f in fams)
                      for (cx, cy, cz), b in vmap.items()
                      if x0 <= cx < x1 and y0 <= cy < y1 and z0 <= cz < z1)
            if has:
                furnished += 1
                by_role_ok[role] += 1
            else:
                missing.append(f"{sp.get('id')}({role})")
    if checked == 0:
        return {"score": None, "notes": "no rooms with required furniture"}
    # Desglose POR TIPO de room (informativo: ¿qué rol falla el amueblado?).
    by_role = {r: {"furnished": by_role_ok.get(r, 0), "total": by_role_tot[r],
                   "required": list(_ROLE_REQUIRED_FURNITURE[r])}
               for r in by_role_tot}
    return {"score": round(furnished / checked, 3),
            "notes": f"{furnished}/{checked} rooms have role furniture"
                     + (f"; missing: {', '.join(missing[:6])}" if missing else ""),
            "missing": missing,
            "by_role": by_role}


_ROOM_SIZE_CRAMPED = {"hallway", "pantry", "attic", "basement",
                      "entry_hall", "courtyard_indoor"}


def _space_utilization(doc: dict) -> dict:
    """¿Las salas APROVECHAN el espacio sin dejar huecos? Cobertura (XZ, unión
    sobre plantas) del rectángulo envolvente de las salas por las propias salas.
    Alto = salas compactas que tilean su huella; bajo = salas dispersas con
    huecos vacíos entre ellas (el defecto "edificio escaso/disperso"). Se mide
    contra la extensión de las SALAS (no el sitio), así que un edificio pequeño
    en un solar grande no se penaliza; los patios PLANEADOS cuentan como sala."""
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    if not storeys:
        return {"score": None, "notes": "no bot_decomposition"}
    cells: set = set()
    minx = minz = 10 ** 9
    maxx = maxz = -10 ** 9
    n = 0
    for st in storeys:
        for sp in st.get("spaces") or []:
            a = sp.get("aabb")
            if not (isinstance(a, list) and len(a) == 6):
                continue
            if a[3] <= a[0] or a[5] <= a[2]:
                continue
            n += 1
            minx, maxx = min(minx, a[0]), max(maxx, a[3])
            minz, maxz = min(minz, a[2]), max(maxz, a[5])
            for x in range(a[0], a[3]):
                for z in range(a[2], a[5]):
                    cells.add((x, z))
    extent = (maxx - minx) * (maxz - minz)
    if n == 0 or not cells or extent <= 0:
        return {"score": None, "notes": "no rooms"}
    cover = min(1.0, len(cells) / extent)   # raw coverage IS the score (0..1)
    return {"score": round(cover, 3),
            "notes": f"rooms cover {cover:.2f} of their {maxx-minx}x{maxz-minz} extent ({n} rooms)",
            "coverage": round(cover, 3)}


def _room_size(doc: dict) -> dict:
    """Adecuación del TAMAÑO interior de cada sala a su rol. Interior tras muros
    de 1 = (dx-2)×(dz-2). Salas habitables: 1.0 si el lado interior menor ≥3
    (cabe mobiliario y circulación), 0.5 si ≥2, 0.0 si degenerada. Salas de paso
    (hallway/pantry/ático/sótano/patio) toleran un lado menor. Detecta
    dormitorios 2×2, "salas" de 1 celda, etc."""
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    if not storeys:
        return {"score": None, "notes": "no bot_decomposition"}
    scores: list[float] = []
    small: list[str] = []
    for st in storeys:
        for sp in st.get("spaces") or []:
            a = sp.get("aabb")
            if not (isinstance(a, list) and len(a) == 6):
                continue
            role = (sp.get("function") or "").strip().lower().replace("-", "_")
            ix = max(0, (a[3] - a[0]) - 2)
            iz = max(0, (a[5] - a[2]) - 2)
            mind = min(ix, iz)
            if role in _ROOM_SIZE_CRAMPED:
                rs = 1.0 if mind >= 1 else 0.0
            else:
                rs = 1.0 if mind >= 3 else (0.5 if mind >= 2 else 0.0)
            scores.append(rs)
            if rs < 1.0:
                small.append(f"{sp.get('id')}({role} {a[3]-a[0]}x{a[5]-a[2]})")
    if not scores:
        return {"score": None, "notes": "no rooms"}
    return {"score": round(sum(scores) / len(scores), 3),
            "notes": f"{sum(1 for s in scores if s >= 1.0)}/{len(scores)} rooms "
                     f"well-sized" + (f"; small: {', '.join(small[:6])}" if small else ""),
            "undersized": small}


def _prompt_adherence(doc: dict, master_plan: dict | None = None,
                      design_intent: dict | None = None) -> dict:
    """¿El edificio tiene las salas PEDIDAS en el prompt? Compara implied_rooms
    (parse del prompt: '4 bedrooms 2 kitchens') con los roles reales del
    bot_decomposition. Score = fracción de salas pedidas satisfechas. None si el
    usuario no pidió salas concretas."""
    import collections
    requested = ((design_intent or {}).get("implied_rooms")
                 or (master_plan or {}).get("implied_rooms"))
    if requested is None:
        prompt = ((master_plan or {}).get("prompt")
                  or (design_intent or {}).get("prompt") or "")
        try:
            from .prompt_expander import _parse_implied_rooms
            requested = _parse_implied_rooms(prompt)
        except Exception:
            requested = []
    if not requested:
        return {"score": None, "notes": "no specific rooms requested"}
    want = collections.Counter(requested)
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    have = collections.Counter(
        (sp.get("function") or "").strip().lower().replace("-", "_")
        for st in storeys for sp in (st.get("spaces") or []))
    satisfied = sum(min(have.get(r, 0), c) for r, c in want.items())
    total = sum(want.values())
    short = {r: f"{have.get(r,0)}/{c}" for r, c in want.items() if have.get(r, 0) < c}
    return {"score": round(satisfied / total, 3) if total else None,
            "requested": dict(want), "built": {r: have.get(r, 0) for r in want},
            "notes": f"requested {dict(want)}; built {dict(have)}"
                     + (f"; short: {short}" if short else ""),
            "shortfall": short}


def _requested_rooms(master_plan, design_intent, doc) -> list[str]:
    """Roles de sala PEDIDOS en el prompt (implied_rooms o parse del texto)."""
    requested = ((design_intent or {}).get("implied_rooms")
                 or (master_plan or {}).get("implied_rooms")
                 or (doc or {}).get("implied_rooms"))
    if requested is None:
        prompt = ((master_plan or {}).get("prompt")
                  or (design_intent or {}).get("prompt")
                  or (doc or {}).get("description") or "")
        try:
            from .prompt_expander import _parse_implied_rooms
            requested = _parse_implied_rooms(prompt)
        except Exception:
            requested = []
    return list(requested or [])


def _prompt_furniture_adherence(doc: dict, vmap: dict,
                                master_plan: dict | None = None,
                                design_intent: dict | None = None) -> dict:
    """Adecuación EXPLÍCITA mueble↔prompt: para cada rol con mueble clave PEDIDO
    en el prompt, ¿cuántas de esas salas tienen el mueble? P.ej. prompt '2
    bedrooms' → 2 camas esperadas; cuenta dormitorios CON cama. Da el desglose
    'pedido vs presente' por tipo (camas, hornos, …). None si el prompt no pide
    salas con mueble clave."""
    import collections
    requested = _requested_rooms(master_plan, design_intent, doc)
    want = collections.Counter(r for r in requested if r in _ROLE_REQUIRED_FURNITURE)
    if not want:
        return {"score": None, "notes": "prompt pide 0 salas con mueble clave"}
    bot = doc.get("bot_decomposition") or {}
    storeys = (bot.get("building") or {}).get("storeys") or []
    # nº de salas de cada rol que TIENEN su mueble clave
    present = collections.Counter()
    for st in storeys:
        for sp in st.get("spaces") or []:
            role = (sp.get("function") or "").strip().lower().replace("-", "_")
            fams = _ROLE_REQUIRED_FURNITURE.get(role)
            a = sp.get("aabb")
            if role not in want or not fams or not (isinstance(a, list) and len(a) == 6):
                continue
            x0, y0, z0, x1, y1, z1 = a
            has = any(any(f in _bare(b) for f in fams)
                      for (cx, cy, cz), b in vmap.items()
                      if x0 <= cx < x1 and y0 <= cy < y1 and z0 <= cz < z1)
            if has:
                present[role] += 1
    # desglose pedido vs presente por TIPO de mueble (nombre legible del 1er fam)
    detail = {}
    for role, req in want.items():
        key = _ROLE_REQUIRED_FURNITURE[role][0]  # bed, furnace, cauldron, …
        detail[key] = {"role": role, "requested": req,
                       "present": min(present.get(role, 0), req)}
    satisfied = sum(d["present"] for d in detail.values())
    total = sum(d["requested"] for d in detail.values())
    short = {k: f"{d['present']}/{d['requested']}" for k, d in detail.items()
             if d["present"] < d["requested"]}
    return {"score": round(satisfied / total, 3) if total else None,
            "by_furniture": detail,
            "notes": "; ".join(f"{k}: {d['present']}/{d['requested']}"
                               for k, d in detail.items()),
            "shortfall": short}


# palabra→número para "two-story", "three floors", "tres plantas", …
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "single": 1, "double": 2,
             "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5,
             "seis": 6, "siete": 7, "ocho": 8}
_FLOOR_WORD = ("floor", "floors", "story", "stories", "storey", "storeys",
               "level", "levels", "planta", "plantas", "piso", "pisos", "nivel", "niveles")


def _prompt_floor_adherence(doc: dict, master_plan: dict | None = None,
                            design_intent: dict | None = None) -> dict:
    """¿El edificio tiene el nº de PLANTAS pedido? Parsea 'N floors/stories/
    plantas/pisos' o 'two-story', 'tres pisos'. Score = 1 − |built−req|/req
    (acotado a [0,1]). None si el prompt no especifica nº de plantas."""
    prompt = ((master_plan or {}).get("prompt")
              or (design_intent or {}).get("prompt")
              or doc.get("description") or "").lower()
    if not prompt:
        return {"score": None, "notes": "no prompt"}
    req = None
    # patrón "<num o palabra>[- ]<floor-word>"  (p.ej. "two-story", "3 floors")
    toks = re.findall(r"([a-z]+|\d+)[\s\-]+(" + "|".join(_FLOOR_WORD) + r")", prompt)
    for num, _w in toks:
        if num.isdigit():
            req = int(num); break
        if num in _WORD_NUM:
            req = _WORD_NUM[num]; break
    if not req:
        return {"score": None, "notes": "prompt no especifica nº de plantas"}
    bot = doc.get("bot_decomposition") or {}
    built = len((bot.get("building") or {}).get("storeys") or [])
    score = max(0.0, 1.0 - abs(built - req) / req)
    return {"score": round(score, 3), "requested_floors": req, "built_floors": built,
            "notes": f"plantas pedidas {req}, construidas {built}"}


# Vocabulario material/color del prompt → familias de bloque esperadas en la
# obra. Permite comprobar si el edificio CUMPLE el material/color pedido en el
# texto (p.ej. "casa de PIEDRA", "torre de LADRILLO ROJO", "villa BLANCA").
_PROMPT_MATERIAL_VOCAB: dict[str, tuple[str, ...]] = {
    # materiales
    "wood": ("planks", "log", "wood"), "wooden": ("planks", "log", "wood"),
    "timber": ("planks", "log"), "log": ("log", "planks"),
    "stone": ("stone", "cobblestone", "andesite", "granite", "diorite"),
    "stonework": ("stone", "cobblestone"), "rock": ("stone", "cobblestone"),
    "brick": ("brick",), "brickwork": ("brick",),
    "sandstone": ("sandstone",), "sand": ("sandstone",),
    "quartz": ("quartz",), "marble": ("quartz",),          # MC no tiene mármol → quartz
    "concrete": ("concrete", "smooth_stone"), "glass": ("glass",),
    "glazed": ("glass",), "prismarine": ("prismarine",),
    "stucco": ("quartz", "smooth_stone", "white"),
    "plaster": ("quartz", "smooth_stone", "white"),
    "whitewash": ("quartz", "white", "smooth_stone"),
    "adobe": ("terracotta", "sandstone"),
    # colores (mapeados a bloques de ese color en MC 1.16.5)
    "white": ("white", "quartz", "smooth_stone", "diorite"),
    "red": ("red", "brick", "terracotta"),
    "dark": ("dark_oak", "blackstone", "spruce", "black"),
    "black": ("black", "blackstone"),
    "grey": ("stone", "andesite", "cobblestone", "gray"),
    "gray": ("stone", "andesite", "cobblestone", "gray"),
    "blue": ("blue", "prismarine", "lapis"),
    "green": ("green", "moss", "leaves", "prismarine"),
    "brown": ("brown", "dark_oak", "spruce"),
    "yellow": ("yellow", "sandstone", "gold"),
}


def _prompt_material_adherence(doc: dict, vmap: dict,
                               master_plan: dict | None = None,
                               design_intent: dict | None = None) -> dict:
    """¿El edificio usa el MATERIAL/COLOR pedido en el prompt? Extrae términos de
    material/color del texto y comprueba que aparezcan (como familia de bloque
    dominante) en la obra. Score = fracción de términos satisfechos. None si el
    prompt no menciona material/color concreto.

    Soporte: faithfulness texto→3D / controlabilidad de modelos generativos
    condicionados por texto (análogo a CLIP-score; ver _METRIC_META)."""
    prompt = ((master_plan or {}).get("prompt")
              or (design_intent or {}).get("prompt")
              or doc.get("description") or "").lower()
    if not prompt:
        return {"score": None, "notes": "no prompt available"}
    # match por PALABRA COMPLETA (no subcadena: 'covered' no debe contar 'red').
    words = set(re.findall(r"[a-z]+", prompt))
    requested = [kw for kw in _PROMPT_MATERIAL_VOCAB if kw in words]
    if not requested:
        return {"score": None, "notes": "no material/colour requested in prompt"}
    # familias de bloque presentes (por nº de vóxeles → dominantes primero)
    import collections
    fam_counts: collections.Counter = collections.Counter()
    for b in vmap.values():
        fam_counts[_bare(b)] += 1
    present_bares = set(fam_counts)
    satisfied, short = 0, []
    seen = set()
    for kw in requested:
        fams = _PROMPT_MATERIAL_VOCAB[kw]
        if kw in seen:
            continue
        seen.add(kw)
        ok = any(any(f in bare for bare in present_bares) for f in fams)
        if ok:
            satisfied += 1
        else:
            short.append(kw)
    total = len(seen)
    return {"score": round(satisfied / total, 3) if total else None,
            "notes": f"requested material/colour {sorted(seen)}; "
                     f"{satisfied}/{total} present"
                     + (f"; missing: {short}" if short else ""),
            "missing": short}


def _envelope_integrity(doc: dict, vmap: dict, master_plan: dict | None = None) -> dict:
    """Fracción de muros EXTERIORES PLANEADOS que están realmente sólidos
    (cerrados). Penaliza casas con tramos de muro faltantes — pero NO penaliza
    estructuras abiertas por diseño (sin muro planeado → score None / n.a.).
    Ventanas (cristal) y puertas cuentan como cerradas (no son fallos)."""
    walls = planned_exterior_walls(master_plan)
    if not walls:
        return {"score": None, "notes": "no planned exterior walls (open/none)"}
    present = sum(1 for c in walls
                  if c in vmap and _bare(vmap[c]) not in _STRUCT_NON_SOLID)
    score = present / len(walls)
    holes = len(walls) - present
    return {"score": round(score, 3),
            "notes": f"{present}/{len(walls)} exterior wall cells solid "
                     f"({holes} holes)", "holes": holes}


def _generation_success(physical: dict, alexander: dict) -> dict:
    """Holistic 'is this a coherent, usable building?' gate (generation success).

    Combines four discriminative signals already computed elsewhere:
      navigable interior (voxel_connectivity), enclosed on top (sheltering_roof),
      enterable (main_entrance), structurally sound (structural_integrity).
    Mirrors SceneEval-style semantic-coherence + traversability. Mean gives
    partial credit; None only if every input is null (no data to judge).
    """
    def sc(fam: dict, k: str):
        v = fam.get(k)
        if isinstance(v, dict):
            v = v.get("score")
        return v if isinstance(v, (int, float)) else None
    gates = {
        "navigable": sc(physical, "voxel_connectivity"),
        "enclosed":  sc(alexander, "sheltering_roof"),
        "enterable": sc(alexander, "main_entrance"),
        "sound":     sc(physical, "structural_integrity"),
    }
    present = {k: v for k, v in gates.items() if v is not None}
    if not present:
        return {"score": None, "notes": "no gating metrics available"}
    score = sum(min(1.0, max(0.0, v)) for v in present.values()) / len(present)
    return {"score": round(score, _SCORE_PRECISION),
            "notes": " ".join(f"{k}={v:.2f}" for k, v in present.items())}


def _aggregate(physical: dict, alexander: dict, prompt: dict | None = None,
               interior: dict | None = None, exterior: dict | None = None) -> dict:
    """Composite over 5 families (physical, alexander, prompt, interior,
    exterior). Composite-excluded metrics are dropped BEFORE the weighted mean;
    `_weighted_mean` renormalises over the remaining weights. Families that score
    None are renormalised out of the overall (no hand-tuning)."""
    def _fam(metrics, weights):
        w = {k: v for k, v in weights.items() if k not in _COMPOSITE_EXCLUDED}
        return _weighted_mean(metrics or {}, w)

    p_total, p_w, p_skip = _fam(physical, _PHYSICAL_WEIGHTS)
    a_total, a_w, a_skip = _fam(alexander, _ALEXANDER_WEIGHTS)
    pr_total, pr_w, pr_skip = _fam(prompt, _PROMPT_WEIGHTS) if prompt else (None, {}, [])
    in_total, in_w, in_skip = _fam(interior, _INTERIOR_WEIGHTS) if interior else (None, {}, [])
    ex_total, ex_w, ex_skip = _fam(exterior, _EXTERIOR_WEIGHTS) if exterior else (None, {}, [])

    totals = {"physical": p_total, "alexander": a_total, "prompt": pr_total,
              "interior": in_total, "exterior": ex_total}
    parts = [(_OVERALL_WEIGHTS5[f], t) for f, t in totals.items() if t is not None]
    overall = None
    if parts:
        wsum = sum(w for w, _ in parts)
        overall = sum(w * t for w, t in parts) / wsum if wsum else None
    rnd = lambda v: round(v, _SCORE_PRECISION) if v is not None else None
    return {
        "physical_total":         rnd(p_total),
        "alexander_total":        rnd(a_total),
        "prompt_adherence_total": rnd(pr_total),
        "interior_total":         rnd(in_total),
        "exterior_total":         rnd(ex_total),
        "overall":                rnd(overall),
        "weight_table": {
            "physical": p_w, "alexander": a_w, "prompt_adherence": pr_w,
            "interior": in_w, "exterior": ex_w,
            "overall": dict(_OVERALL_WEIGHTS5),
        },
        "skipped_metrics": p_skip + a_skip + pr_skip + in_skip + ex_skip,
    }


def _primary_issue(m: dict) -> dict:
    """Extract a compact, traceable summary of WHY a metric scored low.

    Pulls the metric's note plus whichever salient diagnostic field it
    exposes (problem rooms, lonely windows, blocked doors, …) so the
    worst_metrics list points at concrete locations, not just a number.
    """
    issue: dict = {"note": (m.get("notes") or "")[:140]}
    pr = m.get("per_room")
    if isinstance(pr, list):           # voxel_connectivity-style per-room list
        bad = [{"room_id": p.get("room_id"), "status": p.get("status")}
               for p in pr if isinstance(p, dict)
               and p.get("status") not in (None, "reachable")]
        if bad:
            issue["problem_rooms"] = bad[:8]
    for key in ("unreachable_rooms", "lonely_windows", "blocked_doors",
                "lowest_room", "disconnected_fraction", "dark_voxels_examples"):
        v = m.get(key)
        if not v:
            continue
        issue[key] = v[:8] if isinstance(v, list) else v
    return issue


def _worst_metrics(composite: dict, families: dict, k: int = 5) -> list[dict]:
    """Rank the metrics dragging the composite down the most.

    `families` maps family name → its metrics dict (physical/alexander/prompt/
    interior/exterior). Impact = (overall family weight) × (effective
    within-family weight) × (1 − score). Composite-excluded and null metrics are
    omitted. Each entry carries the suggested skill_category and a primary_issue
    locator — the traceability spine the gym consumes to target edits.
    """
    wt = composite.get("weight_table") or {}
    fam_overall = wt.get("overall") or dict(_OVERALL_WEIGHTS5)
    # map family name → its effective within-family weight table key
    _wt_key = {"prompt": "prompt_adherence"}
    out: list[dict] = []
    for family, metrics in families.items():
        eff = wt.get(_wt_key.get(family, family)) or {}
        fw = float(fam_overall.get(family, 0.2))
        for mid, m in metrics.items():
            if mid in _COMPOSITE_EXCLUDED or not isinstance(m, dict):
                continue
            s = m.get("score")
            ew = eff.get(mid)
            if s is None or ew is None:      # null or skipped → not ranked
                continue
            weight = fw * float(ew)
            impact = weight * (1.0 - float(s))
            out.append({
                "metric_id": mid,
                "family": family,
                "score": round(float(s), 3),
                "weight": round(weight, 4),
                "impact_on_composite": round(impact, 4),
                "suggested_skill_categories":
                    _METRIC_TO_SKILL_CATEGORY.get(mid, []),
                "primary_issue": _primary_issue(m),
            })
    out.sort(key=lambda e: -e["impact_on_composite"])
    top = out[:k]
    for i, e in enumerate(top, 1):
        e["rank"] = i
    return top


# ────────────────────────────────────────────────────────────────────────
#  LLM critique — robust (linter + retry + cache + deterministic fallback)
# ────────────────────────────────────────────────────────────────────────

# Tuning constants (prefixed `_CRITIQUE_` to avoid clashes with metric consts).
_CRITIQUE_MAX_TOKENS = 300
_CRITIQUE_TEMPERATURE = 0.5
_CRITIQUE_NOTE_MAX_CHARS = 120
_CRITIQUE_MIN_WORDS = 60
_CRITIQUE_MAX_WORDS = 200          # relaxed vs spec (120) per empirical observation
_CRITIQUE_MAX_ATTEMPTS = 2          # 1 initial + 2 retries

_CRITIQUE_NUMERIC_RX = re.compile(r"\b\d+\.\d+\b|\b\d+%|\b\d+/10\b|\b\d+\s*pts?\b")
_CRITIQUE_MARKDOWN_RX = re.compile(r"(?m)^\s*[-*#]")
_CRITIQUE_GENERIC_PHRASES = (
    "mejorar el edificio", "más detalle", "añadir variedad",
    "mejorar la calidad", "en general bien",
)

_CRITIQUE_METRIC_LABELS = {
    # physical
    "structural_integrity": "la integridad estructural",
    "voxel_connectivity":   "la conectividad entre estancias",
    "vertical_clearance":   "la altura libre de las estancias",
    "door_functionality":   "la funcionalidad de las puertas",
    "light_coverage":       "la cobertura lumínica interior",
    "block_legitimacy":     "la legitimidad de la paleta de bloques",
    "material_consistency": "la coherencia material por estancia",
    "volume_density":       "la densidad volumétrica",
    # alexander
    "light_on_two_sides":    "la luz natural a dos lados",
    "intimacy_gradient":     "el gradiente de intimidad",
    "common_areas_at_heart": "la centralidad de las áreas comunes",
    "sheltering_roof":       "el techo protector",
    "building_edge":         "el tratamiento del borde del edificio",
    "window_place":          "el aprovechamiento de las ventanas como lugar",
    "entrance_transition":   "la transición de la entrada",
    "main_entrance":         "la posición de la entrada principal",
    "farmhouse_kitchen":     "la cocina como corazón doméstico",
    "roof_layout":           "la coherencia del trazado del tejado",
}


def _lint_critique(text: str) -> list[str]:
    """Pure validator over LLM output. Returns list of error tags (empty == OK)."""
    errs: list[str] = []
    if not text or not text.strip():
        errs.append("empty")
        return errs
    if _CRITIQUE_NUMERIC_RX.search(text):
        errs.append("contains_numbers")
    low = text.lower()
    if any(p in low for p in _CRITIQUE_GENERIC_PHRASES):
        errs.append("generic_phrase")
    wc = len(text.split())
    if wc < _CRITIQUE_MIN_WORDS:
        errs.append(f"word_count_{wc}_too_short")
    elif wc > _CRITIQUE_MAX_WORDS:
        errs.append(f"word_count_{wc}_too_long")
    if _CRITIQUE_MARKDOWN_RX.search(text):
        errs.append("contains_markdown")
    return errs


def _critique_template(report: dict) -> str:
    """Deterministic fallback critique (never empty, never numeric)."""
    cat = ((report.get("composite") or {}).get("category")) or "aceptable"
    flat = []
    for c in ("physical", "alexander"):
        for mid, m in (report.get(c) or {}).items():
            s = (m or {}).get("score")
            if isinstance(s, (int, float)):
                flat.append((mid, float(s)))
    flat.sort(key=lambda p: p[1])
    weak = [_CRITIQUE_METRIC_LABELS.get(m, m.replace("_", " "))
            for m, s in flat[:3] if s <= 0.5]
    strong = [_CRITIQUE_METRIC_LABELS.get(m, m.replace("_", " "))
              for m, s in flat[-2:][::-1] if s >= 0.85]
    parts = [f"El edificio resulta {cat} en su evaluación global."]
    if strong:
        parts.append(
            f"Destaca especialmente en {' y en '.join(strong)}, "
            f"aspectos que dan carácter al conjunto."
        )
    if weak:
        parts.append(
            f"Como debilidades a revisar en próximas iteraciones figuran "
            f"{', '.join(weak)}; conviene priorizar estos aspectos antes "
            f"de cerrar el diseño."
        )
    elif flat:
        worst = _CRITIQUE_METRIC_LABELS.get(
            flat[0][0], flat[0][0].replace("_", " ")
        )
        parts.append(
            f"Como única área de mejora menor, {worst} podría reforzarse "
            f"en una pasada futura."
        )
    else:
        parts.append(
            "No se dispone de métricas puntuables suficientes para emitir "
            "un juicio detallado; se recomienda revisar la generación antes "
            "de aceptar el resultado."
        )
    return " ".join(parts)


@functools.lru_cache(maxsize=128)
def _cached_critique_call(_sha1: str, payload_json: str) -> str:
    """LLM call wrapper cached by payload sha1 for idempotency across re-runs.

    The first arg participates in the cache key so retries (sha1#retryN) can
    bypass the cache while the happy path on the same payload is cached.
    """
    from .llm import call_llm, MODEL_DEFAULT
    system = (PROMPTS / "critique.md").read_text(encoding="utf-8")
    text = call_llm(
        system=system, user=payload_json, model=MODEL_DEFAULT,
        max_tokens=_CRITIQUE_MAX_TOKENS, temperature=_CRITIQUE_TEMPERATURE,
    )
    return (text or "").strip()


def _generate_critique(report: dict, doc: dict | None = None) -> str:
    """LLM critique with linter, bounded retry and deterministic fallback.

    Returns a non-empty Spanish paragraph (60-200 words, no numbers,
    no markdown). Never raises; never returns "" — falls back to a
    template on persistent failure.
    """
    metrics_with_notes = [
        {"id": mid, "category": cat,
         "score": (m or {}).get("score"),
         "notes": ((m or {}).get("notes") or "")[:_CRITIQUE_NOTE_MAX_CHARS]}
        for cat in ("physical", "alexander")
        for mid, m in (report.get(cat) or {}).items()
    ]
    bbox = ((doc or {}).get("bounding_box") or {}).get("size") or []
    storeys = (((doc or {}).get("bot_decomposition") or {})
               .get("building") or {}).get("storeys") or []
    building_meta = {
        "style_pack": (doc or {}).get("style_pack"),
        "footprint": (f"{bbox[0]}x{bbox[2]}"
                      if isinstance(bbox, list) and len(bbox) == 3 else None),
        "stories": len(storeys) or None,
    }
    payload = json.dumps(
        {"composite": report.get("composite"),
         "metrics_with_notes": metrics_with_notes,
         "building_meta": building_meta},
        ensure_ascii=False, sort_keys=True,
    )
    sha = hashlib.sha1(payload.encode("utf-8")).hexdigest()

    last_errs: list[str] = ["never_called"]
    for attempt in range(_CRITIQUE_MAX_ATTEMPTS + 1):
        cache_key = sha if attempt == 0 else f"{sha}#retry{attempt}"
        try:
            text = _cached_critique_call(cache_key, payload)
        except ImportError:
            break  # llm module not wired → fallback directly
        except Exception as e:
            print(
                f"[evaluator] critique LLM failed (attempt {attempt + 1}): {e}",
                file=sys.stderr,
            )
            break
        errs = _lint_critique(text)
        if not errs:
            return text
        last_errs = errs
        print(
            f"[evaluator] critique lint rejected (attempt {attempt + 1}): "
            f"{errs}",
            file=sys.stderr,
        )

    print(
        f"[evaluator] falling back to deterministic template "
        f"(last errors: {last_errs})",
        file=sys.stderr,
    )
    return _critique_template(report)


# ────────────────────────────────────────────────────────────────────────
#  Public entry point
# ────────────────────────────────────────────────────────────────────────


def evaluate(doc: dict, *, design_intent: dict | None = None,
             master_plan: dict | None = None,
             run_critique: bool = True) -> dict:
    """Run all 18 metrics + composite + optional LLM critique. Returns the report dict."""
    vmap = _build_voxel_map(doc)

    # PHYSICAL = corrección estructural pura.
    physical = {
        "structural_integrity": _structural_integrity(doc, vmap, master_plan),
        "voxel_connectivity":   _voxel_connectivity(doc, vmap, design_intent, master_plan),
        "volume_density":       _volume_density(doc, vmap),
        "block_legitimacy":     _block_legitimacy(doc),
    }
    # INTERIOR = aprovechamiento del espacio + tamaño de sala + muebles + luz +
    # clearance (las NO-Alexander). space_utilization y room_size son nuevas.
    interior = {
        "space_utilization":    _space_utilization(doc),
        "room_size":            _room_size(doc),
        "room_furnishing":      _room_furnishing(doc, vmap, master_plan),
        "vertical_clearance":   _vertical_clearance(doc, vmap),
        "light_coverage":       _light_coverage(doc, vmap),
        "material_consistency": _material_consistency(doc, vmap),
        "door_functionality":   _door_functionality(doc, vmap),
    }
    # EXTERIOR = integridad de la envolvente (muros/perímetro planeados completos).
    exterior = {
        "envelope_integrity":   _envelope_integrity(doc, vmap, master_plan),
    }
    # PROMPT = fidelidad EXPLÍCITA al texto pedido.
    prompt_adherence = {
        "room_count": _prompt_adherence(doc, master_plan, design_intent),
        "furniture":  _prompt_furniture_adherence(doc, vmap, master_plan, design_intent),
        "materials":  _prompt_material_adherence(doc, vmap, master_plan, design_intent),
        "floors":     _prompt_floor_adherence(doc, master_plan, design_intent),
    }
    # ALEXANDER = los 10 patrones de Christopher Alexander.
    alexander = {
        "light_on_two_sides":    _light_on_two_sides(doc, vmap, master_plan),
        "intimacy_gradient":     _intimacy_gradient(doc, master_plan),
        "common_areas_at_heart": _common_areas_at_heart(doc),
        "sheltering_roof":       _sheltering_roof(doc, vmap),
        "building_edge":         _building_edge(doc, vmap),
        "window_place":          _window_place(doc, vmap),
        "entrance_transition":   _entrance_transition(doc, master_plan),
        "main_entrance":         _main_entrance(doc, vmap, master_plan),
        "farmhouse_kitchen":     _farmhouse_kitchen(doc, vmap, master_plan),
        "roof_layout":           _roof_layout(doc, vmap),
    }
    # Holistic generation-success gate (needs physical+alexander scores).
    prompt_adherence["generation_success"] = _generation_success(physical, alexander)
    composite = _aggregate(physical, alexander, prompt_adherence, interior, exterior)
    worst_metrics = _worst_metrics(composite, {
        "physical": physical, "alexander": alexander, "prompt": prompt_adherence,
        "interior": interior, "exterior": exterior})

    # Resumen por ÁMBITO (structural/interior/exterior/prompt) para tratamiento
    # posterior: media de las métricas presentes de cada ámbito.
    _all_scores = {**physical, **alexander, **interior, **exterior, **prompt_adherence}
    scope_summary: dict = {}
    for scope in ("structural", "interior", "exterior", "prompt", "both"):
        vals = [m["score"] for mid, m in _all_scores.items()
                if isinstance(m, dict) and m.get("score") is not None
                and _METRIC_META.get(mid, {}).get("scope") == scope]
        scope_summary[scope] = {
            "mean": round(sum(vals) / len(vals), _SCORE_PRECISION) if vals else None,
            "n_metrics": len(vals),
        }

    report = {
        "building_id": doc.get("id", "unknown"),
        "schema_version": "1.2",
        "physical": physical,
        "alexander": alexander,
        "interior": interior,
        "exterior": exterior,
        "prompt_adherence": prompt_adherence,   # ★ fidelidad al texto pedido
        "composite": composite,
        "scope_summary": scope_summary,      # interior/exterior/prompt/structural
        "metric_metadata": _METRIC_META,     # qué mide + soporte bibliográfico
        "worst_metrics": worst_metrics,
        "critique": "",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    if run_critique:
        report["critique"] = _generate_critique(report, doc=doc)

    # Validate against schema (best-effort; don't raise if minor issue)
    try:
        make_validator("evaluation_report.schema.json").validate(report)
    except Exception as e:
        print(f"[evaluator] report schema-validation warning: {e}", file=sys.stderr)

    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="ReferenceBuilding JSON path")
    ap.add_argument("--no-critique", action="store_true")
    args = ap.parse_args()
    doc = json.loads(Path(args.path).read_text(encoding="utf-8"))
    report = evaluate(doc, run_critique=not args.no_critique)
    print(json.dumps(report, indent=2, ensure_ascii=False))
