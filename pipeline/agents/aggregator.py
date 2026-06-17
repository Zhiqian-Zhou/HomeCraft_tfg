"""Aggregator: design_intent + room_plans + exterior_plan → master_plan.

Pure Python, no LLM. Builds the BOT decomposition tree from design_intent
rooms, concatenates ops in the right order for the composer's later-wins
semantics, and injects connectors at the end so they survive any room
agent that filled their position with a wall or floor.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .schema_utils import make_validator

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAG = REPO_ROOT / "rag"

# BOT function enum requires hyphenated names; map skill-style underscore.
_ROLE_TO_BOT_FUNCTION = {
    "kitchen": "kitchen",
    "bathroom": "bathroom",
    "bedroom": "bedroom",
    "living_room": "living-room",
    "dining_room": "dining-room",
    "library": "library",
    "study": "study",
    "hallway": "hallway",
    "staircase": "staircase",
    "entry_hall": "entry-hall",
    "basement": "basement",
    "attic": "attic",
    "courtyard_indoor": "courtyard",
    "throne_room": "throne-room",
    "great_hall": "great-hall",
    "chapel": "chapel",
    "pantry": "storage",
    "nursery": "bedroom",
    "music_room": "other",
}


def _bot_function_for(role: str) -> str:
    return _ROLE_TO_BOT_FUNCTION.get(role, "other")


def _facing_to_minecraft(f: str) -> str:
    return {"n": "north", "s": "south", "e": "east", "w": "west"}.get(f, "north")


def _aabb_overlap_volume(a: list[int], b: list[int]) -> int:
    dx = max(0, min(a[3], b[3]) - max(a[0], b[0]))
    dy = max(0, min(a[4], b[4]) - max(a[1], b[1]))
    dz = max(0, min(a[5], b[5]) - max(a[2], b[2]))
    return dx * dy * dz


def _build_bot_decomposition(design_intent: dict) -> dict:
    """Build the bot_decomposition tree from rooms grouped by floor."""
    by_floor: dict[int, list[dict]] = {}
    for room in design_intent.get("rooms", []):
        by_floor.setdefault(room["floor"], []).append(room)
    storeys = []
    for f in design_intent.get("floors", []):
        ix = f["index"]
        rooms = by_floor.get(ix, [])
        spaces = []
        for r in rooms:
            spaces.append({
                "id":       r["id"],
                "function": _bot_function_for(r["role"]),
                "aabb":     r["aabb"],
            })
        storey_id = f.get("name") or f"floor-{ix}"
        # AABB for the storey is the union of its rooms (or the floor band)
        storey_aabb = None
        if rooms:
            xs0 = min(r["aabb"][0] for r in rooms)
            ys0 = min(r["aabb"][1] for r in rooms)
            zs0 = min(r["aabb"][2] for r in rooms)
            xs1 = max(r["aabb"][3] for r in rooms)
            ys1 = max(r["aabb"][4] for r in rooms)
            zs1 = max(r["aabb"][5] for r in rooms)
            storey_aabb = [xs0, ys0, zs0, xs1, ys1, zs1]
        storey = {
            "id":     storey_id,
            "spaces": spaces,
        }
        if storey_aabb is not None:
            storey["aabb"] = storey_aabb
        storeys.append(storey)
    return {"building": {"storeys": storeys}}


def _terrain_prep_ops(site_aabb: list[int]) -> list[dict]:
    """Lay a 1-block-thick grass slab at the bottom of the site."""
    if not site_aabb:
        return []
    return [{
        "kind": "rect",
        "aabb": [site_aabb[0], site_aabb[1], site_aabb[2],
                 site_aabb[3], site_aabb[1]+1, site_aabb[5]],
        "axis": "y",
        "level": site_aabb[1],
        "block": "minecraft:grass_block",
    }]


def _connector_ops(design_intent: dict) -> list[dict]:
    """Emit the final-pass ops that materialize doors, windows, staircases."""
    out = []
    c = design_intent.get("connectors", {})
    for d in c.get("doors", []):
        x, y, z = d["at"]
        facing = _facing_to_minecraft(d.get("facing", "n"))
        block_key = d.get("block_key", "@door")
        # 2-block-tall door
        if block_key.startswith("@"):
            base_block = block_key
        else:
            base_block = block_key
        # Use blockstate suffixes
        lower = f"{base_block}[half=lower,facing={facing}]"
        upper = f"{base_block}[half=upper,facing={facing}]"
        out.append({"kind": "place", "at": [x, y,   z], "block": lower})
        out.append({"kind": "place", "at": [x, y+1, z], "block": upper})

    for w in c.get("windows", []):
        a = w.get("aabb")
        if not (isinstance(a, list) and len(a) == 6):
            continue
        block_key = w.get("block_key", "@glass_pane")
        out.append({"kind": "fill", "aabb": a, "block": block_key})

    for s in c.get("staircases", []):
        a = s.get("aabb")
        if not (isinstance(a, list) and len(a) == 6):
            continue
        # Emit a Stairs op from one corner to the opposite, then clear above
        # (the composer's Stairs op walks one step per Y level).
        block_key = s.get("block_key", "@stairs")
        out.append({
            "kind": "stairs",
            "from": [a[0], a[1], a[2]],
            "to":   [a[3]-1, a[4]-1, a[5]-1],
            "block": block_key,
        })

    return out


def _detect_warnings(design_intent: dict, room_plans: list[dict]) -> list[str]:
    warnings = []
    # Room overlap (same floor)
    rooms = design_intent.get("rooms", [])
    by_floor: dict[int, list[dict]] = {}
    for r in rooms:
        by_floor.setdefault(r["floor"], []).append(r)
    for fix, rs in by_floor.items():
        for i in range(len(rs)):
            for j in range(i+1, len(rs)):
                vol = _aabb_overlap_volume(rs[i]["aabb"], rs[j]["aabb"])
                if vol > 0:
                    warnings.append(
                        f"rooms {rs[i]['id']!r} and {rs[j]['id']!r} overlap by {vol} voxels on floor {fix}")
    return warnings


def aggregate(design_intent: dict, room_plans: list[dict],
              exterior_plan: dict | None = None,
              *, gen_id: str | None = None) -> dict:
    """Compose the master_plan from design_intent + child plans."""
    style = design_intent["style"]
    site_aabb = design_intent.get("site_aabb")
    if site_aabb is None:
        # Fallback: take the bounding box of all rooms
        rooms = design_intent.get("rooms", [])
        if rooms:
            xs0 = min(r["aabb"][0] for r in rooms)
            ys0 = min(r["aabb"][1] for r in rooms)
            zs0 = min(r["aabb"][2] for r in rooms)
            xs1 = max(r["aabb"][3] for r in rooms)
            ys1 = max(r["aabb"][4] for r in rooms)
            zs1 = max(r["aabb"][5] for r in rooms)
            site_aabb = [xs0, ys0, zs0, xs1, ys1, zs1]
        else:
            site_aabb = [0, 0, 0, 1, 1, 1]

    ops = []
    # 1. Terrain prep
    ops.extend(_terrain_prep_ops(site_aabb))
    # 2. Exterior plan (gardens, paths, perimeter)
    if exterior_plan is not None:
        ops.extend(exterior_plan.get("ops", []))
    # 3. Room plans in floor → id order
    rooms_sorted = sorted(
        design_intent.get("rooms", []),
        key=lambda r: (r["floor"], r["id"]))
    plans_by_id = {p["room_id"]: p for p in room_plans}
    for r in rooms_sorted:
        p = plans_by_id.get(r["id"])
        if p is None:
            continue
        ops.extend(p.get("ops", []))
    # 4. Connectors LAST (later-wins guarantees override)
    ops.extend(_connector_ops(design_intent))

    bot = _build_bot_decomposition(design_intent)

    if gen_id is None:
        gen_id = "gen-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    gen_id = gen_id.lower()
    # Schema-strict id pattern
    gen_id = "".join(c for c in gen_id if c.isalnum() or c in "_-")[:64]
    if len(gen_id) < 3:
        gen_id = "gen-" + gen_id

    master = {
        "id":                gen_id,
        "prompt":            design_intent.get("prompt", ""),
        "style":             style,
        "category":          _mp_category(design_intent.get("category")),
        "site_aabb":         site_aabb,
        "ops":               ops,
        "bot_decomposition": bot,
        # Propagate connectors so downstream consumers (evaluator metrics
        # main_entrance, voxel_connectivity, light_on_two_sides, etc.) can
        # see where doors, windows, and staircases were planned. Without
        # this, those metrics fall back to Y=0 BFS or return null.
        "connectors":        design_intent.get("connectors", {}),
        "warnings":          _detect_warnings(design_intent, room_plans),
    }
    _validate(master)
    return master


# master_plan.schema.json enforces this category enum. The LLM may emit a
# free-form category ('industrial', 'mausoleum', …) which is fine UPSTREAM (it
# steers the palette) but must be coerced to a valid enum value for the
# master_plan artifact, else schema validation hard-fails the whole build.
# No metric depends on this string, so unknown → 'other' is harmless.
_MP_CATEGORIES = {"residential", "castle", "tower", "temple", "shop", "tavern",
                  "barn", "windmill", "lighthouse", "monument", "other"}


def _mp_category(c) -> str:
    s = (c or "residential").strip().lower().replace("-", "_").replace(" ", "_")
    return s if s in _MP_CATEGORIES else "other"


def _validate(master: dict) -> None:
    validator = make_validator("master_plan.schema.json")
    errs = list(validator.iter_errors(master))
    if not errs:
        return
    # Pick the most informative error (deepest path), and if it's in
    # master.ops[i], surface the op so we can debug.
    err = errs[0]
    for e in errs:
        if len(list(e.absolute_path)) > len(list(err.absolute_path)):
            err = e
    path = list(err.absolute_path)
    detail = f"path=/{'/'.join(str(p) for p in path)}: {err.message[:200]}"
    if path and path[0] == "ops" and len(path) >= 2:
        try:
            offending = master["ops"][int(path[1])]
            detail += f"  failing_op={offending}"
        except (IndexError, KeyError, ValueError):
            pass
    raise __import__("jsonschema").exceptions.ValidationError(detail)


# ────────────────────────────────────────────────────────────────────────
#  Pipeline v3 aggregator — consumes 4 separate streams from sub-agents
# ────────────────────────────────────────────────────────────────────────

def aggregate_v3(global_intent: dict,
                  space_plan: dict,
                  architecture_plan: dict,
                  connector_plan: dict,
                  room_plans: list[dict],
                  exterior_plan: dict | None = None,
                  *, gen_id: str | None = None) -> dict:
    """Build master_plan from v3's four upstream artifacts + room plans.

    Op concatenation order (later-wins matters):
      1. Terrain prep
      2. Exterior ops
      3. Architecture envelope ops          ← guaranteed walls + floors + roof
      4. Room decoration ops                ← furniture, lights, decor
         (existing skills emit envelope+decor; the envelope is harmless
         redundancy since the architecture stream already drew walls)
      5. Carve_ops from connector_plan      ← punch holes for doors/windows
      6. Door/window/stair materialization  ← from validated connector_plan

    The output master_plan is byte-compatible with v2.6's schema. The
    evaluator + viewer consume it without changes.
    """
    style = global_intent.get("style", "medieval")
    site_aabb = global_intent.get("site_aabb") or _fallback_site_aabb(space_plan)

    # Synthesize a design_intent-shaped dict for back-compat:
    # the evaluator reads master_plan.connectors[].between to seed BFS.
    di_compat = _synth_design_intent(global_intent, space_plan, connector_plan)

    # Stream 1: terrain prep
    ops: list[dict] = []
    ops.extend(_terrain_prep_ops(site_aabb))

    # Stream 2: exterior
    if exterior_plan is not None:
        ops.extend(exterior_plan.get("ops", []))

    # Stream 3: architecture envelope ops (strip provenance tags before
    # passing to composer — it only understands shape_op kinds + fields).
    for op in architecture_plan.get("ops", []):
        ops.append(_strip_envelope_tags(op))

    # Stream 4: room decoration ops (existing skill output, ungated)
    rooms_sorted = sorted(space_plan.get("rooms", []),
                            key=lambda r: (r["floor"], r["id"]))
    plans_by_id = {p["room_id"]: p for p in room_plans}
    for r in rooms_sorted:
        p = plans_by_id.get(r["id"])
        if p is None:
            continue
        ops.extend(p.get("ops", []))

    # Stream 5: carve_ops (air punches) — must run BEFORE connector ops
    for door in connector_plan.get("doors", []):
        ops.extend(door.get("carve_ops", []))
    for win in connector_plan.get("windows", []):
        ops.extend(win.get("carve_ops", []))

    # Stream 6: connector materialization (doors/windows/stairs)
    ops.extend(_v3_connector_ops(connector_plan))

    # BOT decomposition from space_plan
    bot = _build_bot_from_space_plan(global_intent, space_plan)

    # gen_id
    if gen_id is None:
        gen_id = "gen-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    gen_id = gen_id.lower()
    gen_id = "".join(c for c in gen_id if c.isalnum() or c in "_-")[:64]
    if len(gen_id) < 3:
        gen_id = "gen-" + gen_id

    master = {
        "id":                gen_id,
        "prompt":            global_intent.get("prompt", ""),
        "style":             style,
        "category":          _mp_category(global_intent.get("category")),
        "site_aabb":         site_aabb,
        "ops":               ops,
        "bot_decomposition": bot,
        "connectors":        di_compat["connectors"],
        "warnings":          _v3_detect_warnings(connector_plan),
    }
    _validate(master)
    return master


def _synth_design_intent(global_intent: dict,
                          space_plan: dict,
                          connector_plan: dict) -> dict:
    """Synthesize the design_intent-shaped dict the evaluator expects.

    Returns a dict with ONLY the fields the evaluator + viewer read:
    rooms, floors, connectors. NOT a fully schema-valid design_intent.
    """
    # Flatten connectors back to v2.6 shape: between/at/facing only.
    doors_compat = []
    for d in connector_plan.get("doors", []):
        v = d.get("validated") or {}
        if v:
            doors_compat.append({
                "id":     d.get("id"),
                "between": v.get("between", []),
                "at":     v.get("at", [0, 0, 0]),
                "facing": v.get("facing", "n"),
                "block_key": v.get("block_key", "@door"),
            })
    windows_compat = []
    for w in connector_plan.get("windows", []):
        v = w.get("validated") or {}
        if v:
            windows_compat.append({
                "id":     w.get("id"),
                "in_room": v.get("in_room", ""),
                "wall":   v.get("wall", "n"),
                "aabb":   v.get("aabb", [0, 0, 0, 1, 1, 1]),
                "block_key": v.get("block_key", "@window"),
            })
    stairs_compat = []
    for s in connector_plan.get("staircases", []):
        v = s.get("validated") or {}
        if v:
            stairs_compat.append({
                "id":     s.get("id"),
                "from_floor": v.get("from_floor", 0),
                "to_floor":   v.get("to_floor", 1),
                "aabb":   v.get("aabb", [0, 0, 0, 1, 1, 1]),
                "shape":  v.get("shape", "straight"),
                "block_key": v.get("block_key", "@stairs"),
            })
    return {
        "prompt": global_intent.get("prompt", ""),
        "style":  global_intent.get("style", "medieval"),
        "category": _mp_category(global_intent.get("category")),
        "floors": global_intent.get("floors", []),
        "rooms":  space_plan.get("rooms", []),
        "connectors": {
            "doors":     doors_compat,
            "windows":   windows_compat,
            "staircases": stairs_compat,
        },
    }


def _strip_envelope_tags(op: dict) -> dict:
    """Remove room_id / envelope_role / shared_with before composer sees it.

    Composer understands shape_op fields only. Map architecture ops
    (fill_hollow with wall_block/floor_block/ceiling_block) back to
    composer's fill_hollow (wall/floor/ceiling).
    """
    out = {k: v for k, v in op.items()
           if k not in ("room_id", "envelope_role", "shared_with")}
    # Rename architecture_planner fields to composer fields
    if op.get("kind") == "fill_hollow":
        if "wall_block" in out:
            out["wall"] = out.pop("wall_block")
        if "floor_block" in out:
            out["floor"] = out.pop("floor_block")
        if "ceiling_block" in out:
            out["ceiling"] = out.pop("ceiling_block")
    return out


_WOODS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak",
          "crimson", "warped")


def _solid_for_stair(block: str) -> str:
    """Bloque SÓLIDO válido (1.16.5) del mismo material que una escalera, para
    rellenar bajo los peldaños. `X_stairs` → su base: maderas→*_planks,
    stone_brick→stone_bricks, cobblestone→cobblestone, etc. Evita inventar
    bloques inexistentes como 'stone_brick_planks'."""
    b = block.split("[")[0].replace("minecraft:", "")
    base = b[:-7] if b.endswith("_stairs") else b      # quita "_stairs"
    for w in _WOODS:
        if base == w:
            return f"minecraft:{w}_planks"
    explicit = {
        "stone_brick":  "minecraft:stone_bricks",
        "mossy_stone_brick": "minecraft:mossy_stone_bricks",
        "nether_brick": "minecraft:nether_bricks",
        "red_nether_brick": "minecraft:red_nether_bricks",
        "brick":        "minecraft:bricks",
        "end_stone_brick": "minecraft:end_stone_bricks",
        "cobblestone":  "minecraft:cobblestone",
        "mossy_cobblestone": "minecraft:mossy_cobblestone",
        "stone":        "minecraft:stone",
        "smooth_stone": "minecraft:smooth_stone",
        "sandstone":    "minecraft:sandstone",
        "red_sandstone": "minecraft:red_sandstone",
        "quartz":       "minecraft:quartz_block",
        "purpur":       "minecraft:purpur_block",
        "prismarine":   "minecraft:prismarine",
    }
    if base in explicit:
        return explicit[base]
    # variantes pulidas/lisas (polished_andesite, etc.) son bloques sólidos válidos
    return f"minecraft:{base}"


def _stair_facing(dx, dz):
    if dx > 0:
        return "east"
    if dx < 0:
        return "west"
    return "south" if dz > 0 else "north"


def _spiral_stair_ops(a: list, block: str) -> list[dict]:
    """Spiral staircase: sube por el PERÍMETRO de un hueco ≥3×3, un peldaño por
    nivel, con el centro abierto (pozo de la espiral). Cada peldaño mira hacia
    la siguiente celda del anillo → se lee como una escalera de caracol.
    BFS-climbable: peldaño en (cur,y) + aire encima → al siguiente (nxt,y+1).
    Al vaciarse el hueco a altura completa (caller), la espiral asciende sin
    cortes de forjado y es claramente visible."""
    sx0, y0, sz0, sx1, y1, sz1 = a
    ring: list[tuple[int, int]] = []
    for x in range(sx0, sx1):
        ring.append((x, sz0))
    for z in range(sz0 + 1, sz1):
        ring.append((sx1 - 1, z))
    for x in range(sx1 - 2, sx0 - 1, -1):
        ring.append((x, sz1 - 1))
    for z in range(sz1 - 2, sz0, -1):
        ring.append((sx0, z))
    if len(ring) < 2:
        return []
    ops: list[dict] = []
    y, i = y0, 0
    guard = (y1 - y0 + 1) * 2
    while y < y1 and i < guard:
        cur = ring[i % len(ring)]
        nxt = ring[(i + 1) % len(ring)]
        ops.append({"kind": "place", "at": [cur[0], y, cur[1]],
                    "block": f"{block}[facing={_stair_facing(nxt[0]-cur[0], nxt[1]-cur[1])}]"})
        y += 1
        i += 1
    return ops


def _straight_stair_ops(a: list, block: str) -> list[dict]:
    """Escalera RECTA de un tramo a lo largo del eje más largo. Cada celda sube
    1: peldaño + relleno sólido debajo (no flota). Sirve si run ≥ rise."""
    sx0, y0, sz0, sx1, y1, sz1 = a
    along_x = (sx1 - sx0) >= (sz1 - sz0)
    n = (sx1 - sx0 if along_x else sz1 - sz0)
    ops: list[dict] = []
    for k in range(min(n, y1 - y0)):
        x = sx0 + (k if along_x else 0)
        z = sz0 + (0 if along_x else k)
        y = y0 + k
        face = "east" if along_x else "south"
        ops.append({"kind": "place", "at": [x, y, z], "block": f"{block}[facing={face}]"})
        if y > y0:                              # relleno bajo el peldaño
            ops.append({"kind": "fill", "aabb": [x, y0, z, x + 1, y, z + 1],
                        "block": _solid_for_stair(block)})
    return ops


def _dogleg_stair_ops(a: list, block: str) -> list[dict]:
    """Escalera SWITCHBACK CONTINUA (dog-leg que sube TODA la altura del hueco).
    Tramos alternos a lo largo del eje largo, en dos carriles del eje corto, con
    rellano sólido en cada giro de 180°. A diferencia de un dogleg de un solo
    giro, repite tramos hasta llegar arriba → sirve para huecos de varias
    plantas (rise grande) en una huella compacta, y se LEE claramente como
    escalera. Necesita eje largo ≥3 y corto ≥2."""
    sx0, y0, sz0, sx1, y1, sz1 = a
    along_x = (sx1 - sx0) >= (sz1 - sz0)
    long0, long1 = (sx0, sx1) if along_x else (sz0, sz1)
    short0, short1 = (sz0, sz1) if along_x else (sx0, sx1)
    run = long1 - long0
    if run < 3 or (short1 - short0) < 2:
        return _spiral_stair_ops(a, block)
    plank = _solid_for_stair(block)
    ops: list[dict] = []

    def cell(lc, sc):                       # (long-coord, short-coord) → (x,z)
        return (lc, sc) if along_x else (sc, lc)

    y = y0
    lane = 0                                 # 0 = carril short0 ; 1 = carril short1-1
    direction = 1                            # +1 sube por long creciente, −1 al revés
    guard = (y1 - y0) * 4
    it = 0
    while y < y1 - 1 and it < guard:
        sc = short0 if lane == 0 else short1 - 1
        seq = range(long0, long1) if direction == 1 else range(long1 - 1, long0 - 1, -1)
        if along_x:
            face = "east" if direction == 1 else "west"
        else:
            face = "south" if direction == 1 else "north"
        last = None
        for lc in seq:
            if y >= y1 - 1:
                break
            x, z = cell(lc, sc)
            ops.append({"kind": "place", "at": [x, y, z], "block": f"{block}[facing={face}]"})
            # soporte: SOLO el bloque inmediatamente bajo el peldaño (no una
            # columna hasta el suelo → si no, queda una masa sólida ilegible).
            if y - 1 > y0:
                ops.append({"kind": "place", "at": [x, y - 1, z], "block": plank})
            last = (lc, y)
            y += 1
        if last is None:
            break
        # rellano sólido en el giro: cubre todo el eje corto a la altura actual
        lc_end = last[0]
        xa, za = cell(lc_end, short0)
        xb, zb = cell(lc_end, short1 - 1)
        ops.append({"kind": "fill",
                    "aabb": [min(xa, xb), y, min(za, zb),
                             max(xa, xb) + 1, y + 1, max(za, zb) + 1],
                    "block": plank})
        lane ^= 1
        direction *= -1
        it += 1
    return ops


def _stair_ops_for(a: list, block: str, shape: str) -> list[dict]:
    """Elige el generador de escalera por SHAPE pedido + lo que CABE en el hueco.
    Variedad real: straight / dogleg / spiral según forma y dimensiones."""
    sx0, y0, sz0, sx1, y1, sz1 = a
    run = max(sx1 - 1 - sx0, sz1 - 1 - sz0)
    rise = (y1 - 1) - y0
    long_axis = max(sx1 - sx0, sz1 - sz0)
    short_axis = min(sx1 - sx0, sz1 - sz0)
    sh = (shape or "").lower()
    # 1) HONRAR la forma pedida (adecuada al tipo de edificio, decidida en
    #    coherence_agent): caracol en torres, dogleg/switchback en casas, etc.
    if sh == "spiral" and long_axis >= 3 and short_axis >= 3:
        return _spiral_stair_ops(a, block)
    if sh in ("dogleg", "switchback", "split", "split-flight", "u") \
            and long_axis >= 3 and short_axis >= 2:
        return _dogleg_stair_ops(a, block)        # escalones + rellano (doméstico)
    # Recta sólo si el recorrido cubre toda la subida (raro salvo gran salón).
    if sh in ("straight", "grand") and run >= rise:
        return _straight_stair_ops(a, block)
    # 2) FALLBACK por lo que CABE (cuando la forma pedida no encaja).
    if run >= rise and run >= 4:
        return _straight_stair_ops(a, block)
    if long_axis >= 4 and short_axis >= 3:        # huella amplia → switchback
        return _dogleg_stair_ops(a, block)
    if long_axis >= short_axis + 2 and long_axis >= 3 and short_axis >= 2:
        return _dogleg_stair_ops(a, block)        # alargada → switchback
    # Hueco casi-cuadrado pequeño → espiral (continua, sube toda la altura).
    return _spiral_stair_ops(a, block)


def _v3_connector_ops(connector_plan: dict) -> list[dict]:
    """Materialize doors / windows / staircases from the connector_plan.

    Similar to v2's _connector_ops but reads from connector_plan.<kind>[].
    validated, not design_intent.connectors.
    """
    out: list[dict] = []
    for d in connector_plan.get("doors", []):
        v = d.get("validated") or {}
        at = v.get("at")
        if not at or len(at) != 3:
            continue
        x, y, z = at
        facing = _facing_to_minecraft(v.get("facing", "n"))
        base = v.get("block_key", "@door")
        lower = f"{base}[half=lower,facing={facing}]"
        upper = f"{base}[half=upper,facing={facing}]"
        out.append({"kind": "place", "at": [x, y, z], "block": lower})
        out.append({"kind": "place", "at": [x, y + 1, z], "block": upper})
    for w in connector_plan.get("windows", []):
        v = w.get("validated") or {}
        a = v.get("aabb")
        if not (isinstance(a, list) and len(a) == 6):
            continue
        out.append({"kind": "fill", "aabb": a,
                     "block": v.get("block_key", "@glass_pane")})
    out.extend(staircase_ops(connector_plan))
    return out


def staircase_shaft_aabbs(connector_plan: dict) -> list[list[int]]:
    """Huecos de escalera FUSIONADOS por footprint XZ (op-space). El visor los
    usa (tras trasladarlos a coords finales) para resaltar la escalera y para
    mostrarla al aislar plantas. Misma fusión que staircase_ops()."""
    by_shaft: dict[tuple, list[int]] = {}
    for s in connector_plan.get("staircases", []):
        v = s.get("validated") or {}
        a = v.get("aabb")
        if not (isinstance(a, list) and len(a) == 6):
            continue
        key = (int(a[0]), int(a[2]), int(a[3]), int(a[5]))
        e = by_shaft.get(key)
        if e is None:
            by_shaft[key] = [int(x) for x in a]
        else:
            e[1] = min(e[1], int(a[1]))
            e[4] = max(e[4], int(a[4]))
    return list(by_shaft.values())


def staircase_ops(connector_plan: dict) -> list[dict]:
    """Materializa SOLO las escaleras del connector_plan (vaciado del hueco +
    peldaños). Se expone aparte porque run.py las re-añade al FINAL del stream
    de ops — DESPUÉS de las ops de frame/envolvente/ventanas que se concatenan
    al final — para que la escalera NO quede sepultada por esa estructura.

    Las escaleras vienen como UNA por transición de planta compartiendo el mismo
    hueco XZ (núcleo unificado por coherence_agent): las FUSIONAMOS por footprint
    XZ en un único tramo de altura completa (un solo vaciado que perfora los
    forjados + una escalera densa y legible)."""
    out: list[dict] = []
    by_shaft: dict[tuple, dict] = {}
    for s in connector_plan.get("staircases", []):
        v = s.get("validated") or {}
        a = v.get("aabb")
        if not (isinstance(a, list) and len(a) == 6):
            continue
        key = (int(a[0]), int(a[2]), int(a[3]), int(a[5]))   # footprint XZ
        e = by_shaft.get(key)
        if e is None:
            by_shaft[key] = {"a": list(a),
                              "block": v.get("block_key", "@stairs"),
                              "shape": str(v.get("shape", "")).lower()}
        else:
            e["a"][1] = min(e["a"][1], a[1])     # y0 mínimo
            e["a"][4] = max(e["a"][4], a[4])     # y1 máximo
            if not e["shape"] and v.get("shape"):
                e["shape"] = str(v.get("shape", "")).lower()

    for e in by_shaft.values():
        a = e["a"]; block = e["block"]; shape = e["shape"]
        w_, d_ = a[3] - a[0], a[5] - a[2]
        # hueco con lado largo ≥3 y corto ≥2 → escalera real (espiral/switchback);
        # más apretado (p.ej. 2×2) → columna de escalera de mano.
        fits = max(w_, d_) >= 3 and min(w_, d_) >= 2
        if fits:
            # Vaciar el hueco COMPLETO a aire (atraviesa muros/forjados de todas
            # las plantas) y construir la escalera VISIBLE elegida por shape +
            # lo que cabe (straight / dogleg / spiral sólida).
            out.append({"kind": "fill",
                        "aabb": [a[0], a[1], a[2], a[3], a[4], a[5]],
                        "block": "minecraft:air"})
            out.extend(_stair_ops_for(a, block, shape))
        else:
            # hueco de 1 de ancho → columna de escalera de mano (último recurso)
            lx, lz = a[0], a[2]
            out.append({"kind": "fill",
                        "aabb": [lx, a[1], lz, lx + 1, a[4], lz + 1],
                        "block": block})
            out.append({"kind": "fill",
                        "aabb": [lx, a[1], lz + 1, lx + 1, a[4], lz + 2],
                        "block": "minecraft:ladder[facing=south]"})
    return out


def _build_bot_from_space_plan(global_intent: dict, space_plan: dict) -> dict:
    """Same BOT shape as v2.6, but reads rooms from space_plan."""
    floors = global_intent.get("floors", [])
    rooms = space_plan.get("rooms", [])
    by_floor: dict[int, list[dict]] = {}
    for r in rooms:
        by_floor.setdefault(r["floor"], []).append(r)
    storeys = []
    for f in floors:
        ix = int(f["index"])
        rs = by_floor.get(ix, [])
        spaces = [{
            "id":       r["id"],
            "function": _bot_function_for(r["role"]),
            "aabb":     r["aabb"],
        } for r in rs]
        storey = {"id": f.get("name") or f"floor-{ix}", "spaces": spaces}
        if rs:
            xs0 = min(r["aabb"][0] for r in rs)
            ys0 = min(r["aabb"][1] for r in rs)
            zs0 = min(r["aabb"][2] for r in rs)
            xs1 = max(r["aabb"][3] for r in rs)
            ys1 = max(r["aabb"][4] for r in rs)
            zs1 = max(r["aabb"][5] for r in rs)
            storey["aabb"] = [xs0, ys0, zs0, xs1, ys1, zs1]
        storeys.append(storey)
    return {"building": {"storeys": storeys}}


def _v3_detect_warnings(connector_plan: dict) -> list[str]:
    """Surface validator drops as master_plan warnings (audit trail)."""
    warns: list[str] = []
    for d in connector_plan.get("dropped", []):
        warns.append(
            f"connector {d.get('id')!r} ({d.get('kind')}) dropped: "
            f"{d.get('drop_code')} — {d.get('details', '')}")
    return warns


def _fallback_site_aabb(space_plan: dict) -> list[int]:
    rooms = space_plan.get("rooms") or []
    if not rooms:
        return [0, 0, 0, 1, 1, 1]
    xs0 = min(r["aabb"][0] for r in rooms)
    ys0 = min(r["aabb"][1] for r in rooms)
    zs0 = min(r["aabb"][2] for r in rooms)
    xs1 = max(r["aabb"][3] for r in rooms)
    ys1 = max(r["aabb"][4] for r in rooms)
    zs1 = max(r["aabb"][5] for r in rooms)
    return [xs0, ys0, zs0, xs1, ys1, zs1]


if __name__ == "__main__":
    # Minimal smoke test
    di = {
        "prompt": "test cottage",
        "style":  "medieval",
        "category": "residential",
        "site_aabb":     [0, 0, 0, 8, 5, 8],
        "building_aabb": [0, 0, 0, 8, 5, 8],
        "floors": [{"index": 0, "y0": 0, "y1": 4, "name": "ground"}],
        "rooms":  [{"id": "kitchen-1", "role": "kitchen", "floor": 0,
                    "aabb": [0, 0, 0, 8, 4, 8]}],
        "exterior": {"features": []},
        "connectors": {
            "doors": [{"id":"d1","between":["outside","kitchen-1"],
                        "at":[4,1,0],"facing":"s"}],
            "windows": [],
            "staircases": [],
        },
    }
    rp = {"room_id":"kitchen-1","role":"kitchen","aabb":[0,0,0,8,4,8],
          "style":"medieval","patterns_applied":[],"skill_chosen":"kitchen",
          "ops":[{"kind":"skill","skill_id":"kitchen","aabb":[0,0,0,8,4,8],"style":"medieval"}]}
    master = aggregate(di, [rp], None, gen_id="smoke")
    print(json.dumps({"id": master["id"], "n_ops": len(master["ops"]),
                       "warnings": master["warnings"]}, indent=2))
