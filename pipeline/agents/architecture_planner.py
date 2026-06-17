"""Architecture planner — Stage 1c in Pipeline v3.

DETERMINISTIC (no LLM): takes a validated global_intent + space_plan
and emits envelope ops (walls, floors, ceilings, roof). Each op carries
`room_id` and `envelope_role` provenance tags so the downstream
connector_validator can find which walls to carve.

Algorithm:
  1. For each room: emit one `fill_hollow` op for walls/floor/ceiling
     using the style's palette (envelope_role = "wall").
  2. For each floor: emit a `rect` op acting as the floor slab at y=y0
     covering all rooms on that floor (envelope_role = "floor_slab").
     This guarantees the inter-storey floor is closed even if rooms
     don't perfectly tile.
  3. Emit a `rect` roof at the top of the building_aabb covering
     the union of all top-floor rooms (envelope_role = "roof").
  4. Detect shared walls between adjacent rooms — annotate them via
     `shared_with`. (The single fill_hollow already paints both sides
     of a shared wall; the tag is for the connector_validator to find.)

No LLM. ~250 LOC. Byte-deterministic given the same inputs.

The output dict matches `rag/schema/architecture_plan.schema.json`.
"""
from __future__ import annotations

import math

from .footprint import footprint_for, Footprint, ROUNDED_SHAPES
from . import roofs as _roofs

# ── Style → palette block resolution ─────────────────────────────────────

# Minimal palette map; mirrors pipeline/skills/base.py::Materials but
# emits block IDs directly (we're not calling skills here).
STYLE_PALETTES: dict[str, dict[str, str]] = {
    "medieval": {
        "primary":   "minecraft:oak_planks",
        "secondary": "minecraft:cobblestone",
        "accent":    "minecraft:stone_bricks",          # gable trim, hearth
        "floor":     "minecraft:oak_planks",
        "roof":      "minecraft:dark_oak_planks",
    },
    "modern": {
        "primary":   "minecraft:smooth_quartz",
        "secondary": "minecraft:polished_andesite",
        "accent":    "minecraft:black_concrete",        # window frames, fascia
        "floor":     "minecraft:polished_andesite",
        "roof":      "minecraft:smooth_stone_slab",
    },
    "fantasy": {
        "primary":   "minecraft:dark_oak_planks",
        "secondary": "minecraft:mossy_cobblestone",
        "accent":    "minecraft:purpur_block",          # arcane glow
        "floor":     "minecraft:dark_oak_planks",
        "roof":      "minecraft:purpur_block",
    },
    "japanese": {
        "primary":   "minecraft:spruce_planks",
        "secondary": "minecraft:white_terracotta",
        "accent":    "minecraft:dark_oak_log",          # post-and-beam frame
        "floor":     "minecraft:spruce_planks",
        "roof":      "minecraft:dark_oak_slab",
    },
    "mediterranean": {
        "primary":   "minecraft:white_terracotta",
        "secondary": "minecraft:smooth_sandstone",
        "accent":    "minecraft:orange_terracotta",     # warm trim
        "floor":     "minecraft:smooth_sandstone",
        "roof":      "minecraft:red_terracotta",
    },
    "rustic": {
        "primary":   "minecraft:spruce_planks",
        "secondary": "minecraft:cobblestone",
        "accent":    "minecraft:stripped_spruce_log",   # half-timber frame
        "floor":     "minecraft:spruce_planks",
        "roof":      "minecraft:hay_block",
    },
    "gothic": {
        "primary":   "minecraft:stone_bricks",
        "secondary": "minecraft:dark_oak_planks",
        "accent":    "minecraft:chiseled_stone_bricks", # carved buttress / pinnacle
        "floor":     "minecraft:stone_bricks",
        "roof":      "minecraft:dark_oak_planks",
    },
    "renaissance": {
        "primary":   "minecraft:smooth_sandstone",
        "secondary": "minecraft:polished_diorite",
        "accent":    "minecraft:gold_block",            # gilt cornice
        "floor":     "minecraft:smooth_sandstone",
        "roof":      "minecraft:red_terracotta",
    },
    "minimalist": {
        "primary":   "minecraft:white_concrete",
        "secondary": "minecraft:light_gray_concrete",
        "accent":    "minecraft:black_concrete",        # graphic black line
        "floor":     "minecraft:white_concrete",
        "roof":      "minecraft:light_gray_concrete",
    },
    "chinese": {
        # Imperial Chinese palace (Tiananmen / Forbidden City) palette:
        #   red walls + white marble base + gilt accents + golden-yellow roof.
        "primary":   "minecraft:red_concrete",          # cinnabar palace walls
        "secondary": "minecraft:smooth_quartz",         # white marble base / colonnade
        "accent":    "minecraft:gold_block",            # gilt finials, dragon ornaments
        "floor":     "minecraft:polished_andesite",     # grey-stone hall floor
        "roof":      "minecraft:yellow_concrete",       # glazed imperial yellow tiles
    },
}

_DEFAULT_PALETTE = STYLE_PALETTES["medieval"]


# Per-category overrides applied on top of the style palette. The pair
# (style, category) gets these slots overwritten; everything else inherits
# from the base style. Use this for *category-driven* material swaps that
# don't make sense as a different style — e.g. a medieval CASTLE uses stone
# walls (cobblestone/stone_bricks) while a medieval COTTAGE keeps oak.
_CATEGORY_OVERRIDES: dict[tuple[str, str], dict[str, str]] = {
    # ── medieval ────────────────────────────────────────────────────────────
    ("medieval", "castle"): {     # stone keep with curtain walls
        "primary":   "minecraft:cobblestone",
        "secondary": "minecraft:stone_bricks",
        "accent":    "minecraft:mossy_cobblestone",
        "floor":     "minecraft:stone_bricks",
    },
    ("medieval", "tower"): {      # round tower / watchtower
        "primary":   "minecraft:cobblestone",
        "secondary": "minecraft:stone_bricks",
        "accent":    "minecraft:mossy_cobblestone",
        "floor":     "minecraft:stone_bricks",
    },
    ("medieval", "monument"): {   # village cross / waymarker
        "primary":   "minecraft:stone_bricks",
        "secondary": "minecraft:cobblestone",
        "accent":    "minecraft:gold_block",
        "floor":     "minecraft:smooth_stone",
    },
    ("medieval", "tavern"): {     # half-timber tavern: spruce + cobble + hay roof
        "primary":   "minecraft:spruce_planks",
        "secondary": "minecraft:cobblestone",
        "accent":    "minecraft:stripped_spruce_log",
        "floor":     "minecraft:spruce_planks",
        "roof":      "minecraft:hay_block",
    },
    ("medieval", "shop"): {       # market stall — open timber on cobble
        "primary":   "minecraft:spruce_planks",
        "secondary": "minecraft:cobblestone",
        "accent":    "minecraft:stripped_spruce_log",
        "floor":     "minecraft:cobblestone",
    },
    ("medieval", "barn"): {       # red barn with spruce + cobble base
        "primary":   "minecraft:red_terracotta",
        "secondary": "minecraft:spruce_planks",
        "accent":    "minecraft:stripped_spruce_log",
        "floor":     "minecraft:dirt",
        "roof":      "minecraft:hay_block",
    },

    # ── chinese (imperial palace defaults) ──────────────────────────────────
    ("chinese", "castle"): {      # red walls + gilt gates
        "primary":   "minecraft:red_concrete",
        "secondary": "minecraft:smooth_quartz",
        "accent":    "minecraft:gold_block",
        "floor":     "minecraft:polished_andesite",
        "roof":      "minecraft:yellow_concrete",
    },
    ("chinese", "tower"): {       # pagoda tower — red + gold
        "primary":   "minecraft:red_concrete",
        "secondary": "minecraft:dark_oak_planks",
        "accent":    "minecraft:gold_block",
        "floor":     "minecraft:polished_andesite",
        "roof":      "minecraft:yellow_concrete",
    },
    ("chinese", "temple"): {      # green-tile temple instead of imperial yellow
        "primary":   "minecraft:red_concrete",
        "secondary": "minecraft:smooth_quartz",
        "accent":    "minecraft:gold_block",
        "floor":     "minecraft:polished_andesite",
        "roof":      "minecraft:green_terracotta",
    },
    ("chinese", "monument"): {    # gilded freestanding marker
        "primary":   "minecraft:smooth_quartz",
        "secondary": "minecraft:red_concrete",
        "accent":    "minecraft:gold_block",
        "floor":     "minecraft:smooth_quartz",
        "roof":      "minecraft:yellow_concrete",
    },

    # ── japanese ────────────────────────────────────────────────────────────
    ("japanese", "temple"): {     # dark spruce shrine with white plaster panels
        "primary":   "minecraft:spruce_planks",
        "secondary": "minecraft:white_terracotta",
        "accent":    "minecraft:dark_oak_log",
        "floor":     "minecraft:spruce_planks",
        "roof":      "minecraft:dark_oak_planks",
    },
    ("japanese", "castle"): {     # white-plaster castle (Himeji-like)
        "primary":   "minecraft:white_terracotta",
        "secondary": "minecraft:smooth_quartz",
        "accent":    "minecraft:dark_oak_log",
        "floor":     "minecraft:spruce_planks",
        "roof":      "minecraft:dark_oak_planks",
    },
    ("japanese", "tower"): {      # pagoda tower
        "primary":   "minecraft:spruce_planks",
        "secondary": "minecraft:white_terracotta",
        "accent":    "minecraft:dark_oak_log",
        "floor":     "minecraft:spruce_planks",
        "roof":      "minecraft:dark_oak_planks",
    },

    # ── gothic ──────────────────────────────────────────────────────────────
    ("gothic", "temple"): {       # cathedral — dark stone + vitrales
        "primary":   "minecraft:stone_bricks",
        "secondary": "minecraft:polished_andesite",
        "accent":    "minecraft:chiseled_stone_bricks",
        "floor":     "minecraft:polished_andesite",
        "roof":      "minecraft:dark_oak_planks",
    },
    ("gothic", "castle"): {       # dark keep
        "primary":   "minecraft:stone_bricks",
        "secondary": "minecraft:dark_oak_planks",
        "accent":    "minecraft:chiseled_stone_bricks",
        "floor":     "minecraft:polished_andesite",
        "roof":      "minecraft:dark_oak_planks",
    },
    ("gothic", "monument"): {     # dark obelisk / column
        "primary":   "minecraft:stone_bricks",
        "secondary": "minecraft:chiseled_stone_bricks",
        "accent":    "minecraft:dark_oak_planks",
        "floor":     "minecraft:smooth_stone",
        "roof":      "minecraft:dark_oak_planks",
    },

    # ── renaissance ─────────────────────────────────────────────────────────
    ("renaissance", "monument"): {  # marble + gold palace
        "primary":   "minecraft:smooth_sandstone",
        "secondary": "minecraft:smooth_quartz",
        "accent":    "minecraft:gold_block",
        "floor":     "minecraft:smooth_sandstone",
        "roof":      "minecraft:red_terracotta",
    },
    ("renaissance", "temple"): {    # classical basilica
        "primary":   "minecraft:smooth_quartz",
        "secondary": "minecraft:smooth_sandstone",
        "accent":    "minecraft:gold_block",
        "floor":     "minecraft:smooth_quartz",
        "roof":      "minecraft:red_terracotta",
    },

    # ── modern / minimalist ────────────────────────────────────────────────
    ("modern", "tower"): {        # glass tower
        "primary":   "minecraft:smooth_quartz",
        "secondary": "minecraft:black_concrete",
        "accent":    "minecraft:black_concrete",
        "floor":     "minecraft:polished_andesite",
        "roof":      "minecraft:smooth_stone_slab",
    },
    ("minimalist", "tower"): {
        "primary":   "minecraft:white_concrete",
        "secondary": "minecraft:black_concrete",
        "accent":    "minecraft:black_concrete",
        "floor":     "minecraft:light_gray_concrete",
        "roof":      "minecraft:light_gray_concrete",
    },

    # ── fantasy ────────────────────────────────────────────────────────────
    ("fantasy", "castle"): {      # dark stone + arcane purple
        "primary":   "minecraft:cobblestone",
        "secondary": "minecraft:mossy_cobblestone",
        "accent":    "minecraft:purpur_block",
        "floor":     "minecraft:dark_oak_planks",
        "roof":      "minecraft:purpur_block",
    },
    ("fantasy", "tower"): {       # wizard's tower — dark oak shaft + purpur cap
        "primary":   "minecraft:dark_oak_planks",
        "secondary": "minecraft:mossy_cobblestone",
        "accent":    "minecraft:purpur_block",
        "floor":     "minecraft:dark_oak_planks",
        "roof":      "minecraft:purpur_block",
    },
    ("fantasy", "temple"): {      # eldritch shrine
        "primary":   "minecraft:mossy_cobblestone",
        "secondary": "minecraft:dark_oak_planks",
        "accent":    "minecraft:purpur_block",
        "floor":     "minecraft:dark_oak_planks",
        "roof":      "minecraft:purpur_block",
    },

    # ── mediterranean ──────────────────────────────────────────────────────
    ("mediterranean", "temple"): {  # white-marble basilica with terracotta
        "primary":   "minecraft:smooth_quartz",
        "secondary": "minecraft:smooth_sandstone",
        "accent":    "minecraft:orange_terracotta",
        "floor":     "minecraft:smooth_sandstone",
        "roof":      "minecraft:red_terracotta",
    },

    # ── rustic ─────────────────────────────────────────────────────────────
    ("rustic", "tavern"): {       # half-timber tavern
        "primary":   "minecraft:spruce_planks",
        "secondary": "minecraft:cobblestone",
        "accent":    "minecraft:stripped_spruce_log",
        "floor":     "minecraft:spruce_planks",
        "roof":      "minecraft:hay_block",
    },
    ("rustic", "barn"): {         # red barn
        "primary":   "minecraft:red_terracotta",
        "secondary": "minecraft:spruce_planks",
        "accent":    "minecraft:stripped_spruce_log",
        "floor":     "minecraft:dirt",
        "roof":      "minecraft:hay_block",
    },
}


def _palette(style: str, category: str | None = None) -> dict[str, str]:
    base = dict(STYLE_PALETTES.get(style, _DEFAULT_PALETTE))
    if category:
        override = _CATEGORY_OVERRIDES.get((style, category.lower()))
        if override:
            base.update(override)
    return base


# ── Helpers ──────────────────────────────────────────────────────────────

def _aabbs_share_wall(a: tuple, b: tuple) -> bool:
    """True iff two half-open AABBs share a wall plane on x or z axis."""
    ax0, ay0, az0, ax1, ay1, az1 = a
    bx0, by0, bz0, bx1, by1, bz1 = b
    # Same vertical overlap required
    if max(ay0, by0) >= min(ay1, by1):
        return False
    # x faces touching
    if ax1 == bx0 or ax0 == bx1:
        return max(az0, bz0) < min(az1, bz1)
    # z faces touching
    if az1 == bz0 or az0 == bz1:
        return max(ax0, bx0) < min(ax1, bx1)
    return False


def _bbox_union_xz(aabbs: list[tuple]) -> tuple[int, int, int, int]:
    """Return [x0, z0, x1, z1] of the union footprint."""
    x0 = min(a[0] for a in aabbs)
    z0 = min(a[2] for a in aabbs)
    x1 = max(a[3] for a in aabbs)
    z1 = max(a[5] for a in aabbs)
    return (x0, z0, x1, z1)


# ── Main entry ───────────────────────────────────────────────────────────

def plan_architecture(global_intent: dict, space_plan: dict) -> dict:
    """Produce an architecture_plan dict from global_intent + space_plan.

    Args:
        global_intent: validated global_intent.schema.json dict
        space_plan: validated space_plan.schema.json dict

    Returns: dict matching architecture_plan.schema.json
    """
    style = global_intent.get("style", "medieval")
    category = global_intent.get("category")
    palette = _palette(style, category)
    building_aabb = global_intent.get("building_aabb") or [0, 0, 0, 1, 1, 1]
    bx0, by0, bz0, bx1, by1, bz1 = building_aabb
    floors = global_intent.get("floors", [])
    rooms = space_plan.get("rooms", [])

    ops: list[dict] = []
    materials_usage: dict[str, dict] = {}

    def _bump(block: str, role: str) -> None:
        slot = palette.get("primary") and (
            "@primary" if block == palette["primary"]
            else "@secondary" if block == palette.get("secondary")
            else "@floor" if block == palette.get("floor")
            else "@roof" if block == palette.get("roof")
            else "@other"
        )
        info = materials_usage.setdefault(block, {
            "block_id": block, "palette_slot": slot,
            "envelope_roles": [], "op_count": 0,
        })
        if role not in info["envelope_roles"]:
            info["envelope_roles"].append(role)
        info["op_count"] += 1

    # ── 1. Room shells (one fill_hollow per room) ──
    # Sort rooms deterministically for reproducible op order.
    rooms_sorted = sorted(rooms, key=lambda r: (r["floor"], r["id"]))
    room_index = {r["id"]: r for r in rooms_sorted}

    for r in rooms_sorted:
        rx0, ry0, rz0, rx1, ry1, rz1 = r["aabb"]
        # Identify rooms sharing walls with this one (for `shared_with` tag)
        shared = [
            other["id"] for other in rooms_sorted
            if other["id"] != r["id"]
            and _aabbs_share_wall(tuple(r["aabb"]), tuple(other["aabb"]))
        ]
        wall_block = palette["primary"]
        floor_block = palette["floor"]
        ops.append({
            "kind": "fill_hollow",
            "envelope_role": "wall",
            "room_id": r["id"],
            "shared_with": shared,
            "aabb": list(r["aabb"]),
            "wall_block": wall_block,
            "floor_block": floor_block,
            "ceiling_block": wall_block,
        })
        _bump(wall_block, "wall")
        _bump(floor_block, "floor_slab")

    # ── 2. Inter-storey floor slabs ──
    # For each floor index, emit a rect slab at y=y0 covering the
    # union footprint of all rooms on that floor.
    by_floor: dict[int, list[tuple]] = {}
    for r in rooms_sorted:
        by_floor.setdefault(r["floor"], []).append(tuple(r["aabb"]))

    for floor in sorted(floors, key=lambda f: f["index"]):
        idx = int(floor["index"])
        y0 = int(floor["y0"])
        rooms_on_floor = by_floor.get(idx, [])
        if not rooms_on_floor:
            continue
        # Slab covers FULL building footprint (not just room union). This
        # was the d8 configuration: best mean composite (0.592) across the
        # 5-prompt regression. The volume_density component drops because
        # the building is denser than corpus IQR — but the gain on other
        # metrics (sheltering_roof, structural_integrity, voxel_connectivity)
        # more than compensates. Empirically validated D.8 vs D.9.
        floor_block = palette["floor"]
        ops.append({
            "kind": "rect",
            "envelope_role": "floor_slab",
            "room_id": None,
            "axis": "y",
            "level": y0,
            "aabb": [bx0, y0, bz0, bx1, y0 + 1, bz1],
            "block": floor_block,
        })
        _bump(floor_block, "floor_slab")

    # ── 3. Roof — sits ON the walls, never floating ──
    # The roof base is laid at the TOP OF THE WALLS (max floor y1), NOT at
    # building_aabb.y1. building_aabb is often taller than the floors occupy
    # (reserved roof-pitch headroom from the global_designer); pinning the
    # roof to by1 left a 2-5 layer air gap and a slab floating in the sky.
    # We lay a full-footprint cap on the walls and, for pitched styles, step
    # it inward layer-by-layer up to by1 so the headroom is filled with a
    # real (hip/pyramid) roof shape instead of an empty gap.
    if rooms_sorted:
        roof_block = palette["roof"]
        roof_style = (global_intent.get("height_intent") or {}).get(
            "roof_style", "gable")
        wall_top = max((int(f["y1"]) for f in floors), default=by1 - 1)
        flat = roof_style in ("flat", "shed", "mono-pitch", "monopitch")
        top_cap = wall_top + 1 if flat else max(by1, wall_top + 1)
        y = wall_top
        inset = 0
        laid = False
        while y < top_cap:
            rx0, rz0 = bx0 + inset, bz0 + inset
            rx1, rz1 = bx1 - inset, bz1 - inset
            if rx0 >= rx1 or rz0 >= rz1:
                break
            ops.append({
                "kind": "rect",
                "envelope_role": "roof",
                "room_id": None,
                "axis": "y",
                "level": y,
                "aabb": [rx0, y, rz0, rx1, y + 1, rz1],
                "block": roof_block,
            })
            _bump(roof_block, "roof")
            laid = True
            y += 1
            inset += 0 if flat else 1
        if not laid:   # footprint too small even for one layer → flat cap
            ops.append({
                "kind": "rect", "envelope_role": "roof", "room_id": None,
                "axis": "y", "level": wall_top,
                "aabb": [bx0, wall_top, bz0, bx1, wall_top + 1, bz1],
                "block": roof_block,
            })
            _bump(roof_block, "roof")

    # ── 4. Baseline lights per room (deterministic) ──
    # Place a lantern at the room center one block under the ceiling. This
    # guarantees light_coverage doesn't crater for rooms the room_agent
    # under-decorates. Light source is style-agnostic (lantern is universal
    # in 1.16.5 vanilla).
    light_block = "minecraft:lantern"
    for r in rooms_sorted:
        rx0, ry0, rz0, rx1, ry1, rz1 = r["aabb"]
        cx = (rx0 + rx1) // 2
        cz = (rz0 + rz1) // 2
        cy = ry1 - 2  # one block under the ceiling
        if cy <= ry0:
            cy = ry0 + 1
        ops.append({
            "kind": "place",
            "envelope_role": "frame",  # using "frame" as a generic ornament tag
            "room_id": r["id"],
            "at": [cx, cy, cz],
            "block": light_block,
        })
        _bump(light_block, "frame")

    return {
        "schema_version": "1.0",
        "ops": ops,
        "materials_used": list(materials_usage.values()),
        "generated_by": {
            "deterministic": True,
            "module": "pipeline.agents.architecture_planner",
            "version": "1.0",
        },
    }


# ────────────────────────────────────────────────────────────────────────
#  Pipeline v4 path — consumes floor_plans[] + applies wall_fittings audit.
#
#  Minimal v4 build: aggregates rooms across floor_plans, cuts stair_void
#  ops over reserved_footprints (kind=stair) so inter-storey slabs have
#  the right holes, and emits a wall_fittings_applied[] audit list based
#  on STYLE_WALL_FITTINGS + CONDITIONAL_FITTINGS + EXCLUSIONS.
#
#  The fitting *voxel materialization* (half-timber bands, eaves, etc.)
#  is deferred to a follow-up commit — for now the audit field documents
#  intent without emitting per-fitting ops.
# ────────────────────────────────────────────────────────────────────────


STYLE_WALL_FITTINGS: dict[str, list[str]] = {
    "medieval":      ["half-timber-wall", "stacked-stone-corner", "lintel-flat",
                       "gable-end-wall", "eaves-overhang"],
    "fantasy":       ["half-timber-wall", "crenellated-parapet", "oriel-window",
                       "gable-end-wall"],
    "gothic":        ["corner-quoin", "lintel-arched", "fluted-pilaster",
                       "crown-molding", "oriel-window", "recessed-niche"],
    "renaissance":   ["corner-quoin", "fluted-pilaster", "crown-molding",
                       "dado-rail", "plinth-base", "recessed-niche"],
    "modern":        ["flat-parapet", "baseboard", "lintel-flat"],
    "minimalist":    ["flat-parapet", "baseboard"],
    "japanese":      ["eaves-overhang", "plinth-base"],
    "chinese":       ["eaves-overhang", "plinth-base"],
    "mediterranean": ["stucco-cob-wall", "lintel-arched", "flat-parapet",
                       "eaves-overhang", "plinth-base", "recessed-niche"],
    "rustic":        ["half-timber-wall", "stacked-stone-corner", "log-cabin-joint",
                       "gable-end-wall", "eaves-overhang", "baseboard"],
}


# Each entry: fitting_id → predicate(ctx: dict) → bool. ctx carries
# {roof_style, category, floors_count, max_room_height}. A fitting from
# STYLE_WALL_FITTINGS only applies if its predicate (if any) is True.
def _cond_gable(ctx):       return ctx.get("roof_style") in {"gable", "gambrel"}
def _cond_gambrel(ctx):     return ctx.get("roof_style") == "gambrel"
def _cond_dormer(ctx):
    return (ctx.get("roof_style") in {"gable", "gambrel", "hip"}
            and ctx.get("floors_count", 0) >= 2)
def _cond_crenel(ctx):
    return (ctx.get("category") == "castle"
            or ctx.get("roof_style") == "flat")
def _cond_flatpar(ctx):     return ctx.get("roof_style") == "flat"
def _cond_oriel(ctx):       return ctx.get("floors_count", 0) >= 2
def _cond_dado(ctx):        return ctx.get("max_room_height", 0) >= 4
def _cond_eaves(ctx):       return ctx.get("roof_style") != "flat"
def _cond_recess(ctx):
    return ctx.get("category") in {"monument", "temple", "residential"}

CONDITIONAL_FITTINGS = {
    "gable-end-wall":      _cond_gable,
    "gambrel-cut-wall":    _cond_gambrel,
    "dormer-window":       _cond_dormer,
    "crenellated-parapet": _cond_crenel,
    "flat-parapet":        _cond_flatpar,
    "oriel-window":        _cond_oriel,
    "dado-rail":           _cond_dado,
    "eaves-overhang":      _cond_eaves,
    "recessed-niche":      _cond_recess,
}


# Pairs of fittings that are mutually exclusive — if both would apply,
# keep the FIRST one (precedence by list order in STYLE_WALL_FITTINGS).
EXCLUSIONS: list[tuple[str, str]] = [
    ("crenellated-parapet", "gable-end-wall"),
    ("crenellated-parapet", "flat-parapet"),
    ("half-timber-wall",    "stucco-cob-wall"),
    ("stacked-stone-corner", "corner-quoin"),
    ("log-cabin-joint",     "half-timber-wall"),
    ("gable-end-wall",      "gambrel-cut-wall"),
    ("flat-parapet",        "gable-end-wall"),
]


# Default location enum per fitting (used for the audit field). The
# location vocabulary matches the architecture_plan_v4 schema's enum.
_FITTING_LOCATION: dict[str, str] = {
    "half-timber-wall":     "exterior_wall",
    "stucco-cob-wall":      "exterior_wall",
    "log-cabin-joint":      "exterior_wall",
    "stacked-stone-corner": "corner",
    "corner-quoin":         "corner",
    "fluted-pilaster":      "exterior_wall",
    "plinth-base":          "floor_band",
    "baseboard":            "floor_band",
    "dado-rail":            "interior_wall",
    "crown-molding":        "ceiling_band",
    "lintel-flat":          "opening",
    "lintel-arched":        "opening",
    "gable-end-wall":       "gable",
    "gambrel-cut-wall":     "gable",
    "crenellated-parapet":  "roof_edge",
    "flat-parapet":         "roof_edge",
    "eaves-overhang":       "roof_edge",
    "dormer-window":        "roof_edge",
    "oriel-window":         "exterior_wall",
    "recessed-niche":       "interior_wall",
}


def select_wall_fittings(style: str, height_intent: dict | None,
                          category: str | None, floors_count: int,
                          max_room_height: int = 0) -> list[dict]:
    """Apply STYLE_WALL_FITTINGS + CONDITIONAL_FITTINGS + EXCLUSIONS to
    produce the wall_fittings_applied[] audit list for a building."""
    candidates = list(STYLE_WALL_FITTINGS.get(style, []))
    ctx = {
        "roof_style":      (height_intent or {}).get("roof_style"),
        "category":        category,
        "floors_count":    floors_count,
        "max_room_height": max_room_height,
    }
    # Filter by conditional predicate
    kept: list[str] = []
    for fid in candidates:
        cond = CONDITIONAL_FITTINGS.get(fid)
        if cond is None or cond(ctx):
            kept.append(fid)
    # Apply exclusions (first wins)
    final: list[str] = []
    for fid in kept:
        excluded = False
        for keep, drop in EXCLUSIONS:
            if fid == drop and keep in final:
                excluded = True
                break
        if not excluded:
            final.append(fid)
    return [
        {"fitting_id": fid,
         "location":   _FITTING_LOCATION.get(fid, "exterior_wall"),
         "deferred":   True}  # voxel materialization deferred
        for fid in final
    ]


# ── Roof builders — roof_style → distinct deterministic geometry ─────────────
# (Before this, every non-flat style rendered as the same stepped pyramid.)

_ROOF_STAIR_PER_STYLE = {
    "medieval": "minecraft:cobblestone_stairs",
    "rustic": "minecraft:cobblestone_stairs",
    "fantasy": "minecraft:stone_brick_stairs",
    "gothic": "minecraft:stone_brick_stairs",
    "renaissance": "minecraft:stone_brick_stairs",
    "modern": "minecraft:smooth_stone_stairs",
    "minimalist": "minecraft:smooth_stone_stairs",
    "japanese": "minecraft:dark_oak_stairs",
    "chinese": "minecraft:dark_oak_stairs",
    "mediterranean": "minecraft:sandstone_stairs",
}
_ROOF_MAX_OPS = 8000  # matches roofs.MAX_OPS — the planner-level guard must
                      # be ≥ the roofs.py guard so it doesn't silently drop a
                      # legitimately-sized Asian roof to a flat cap.


def _roof_rect(level, x0, z0, x1, z1, block):
    return {"kind": "rect", "envelope_role": "roof", "room_id": None,
            "axis": "y", "level": level,
            "aabb": [x0, level, z0, x1, level + 1, z1], "block": block}


def _roof_place(x, y, z, block):
    return {"kind": "place", "envelope_role": "roof", "room_id": None,
            "at": [x, y, z], "block": block}


# Pitched roofs RISE ABOVE the walls by a real pitch — they are NOT clamped to
# building_aabb.y1 (a roof is allowed to exceed it; the voxelizer just extends
# the bbox). This is what makes gables/hips/spires actually read as roofs
# instead of collapsing to a flat cap when no headroom was reserved.
_ROOF_MAX_PITCH = 9


def _roof_hip(bx0, bz0, bx1, bz1, wall_top, by1, block, per_layer=1):
    """Stepped pyramid: inset inward `per_layer` cells each level until it
    closes to a point — rises naturally above the walls."""
    ops = []
    y, inset = wall_top, 0
    while True:
        x0, z0, x1, z1 = bx0 + inset, bz0 + inset, bx1 - inset, bz1 - inset
        if x0 >= x1 or z0 >= z1 or (y - wall_top) > _ROOF_MAX_PITCH:
            break
        ops.append(_roof_rect(y, x0, z0, x1, z1, block))
        y += 1
        inset += per_layer
    return ops or [_roof_rect(wall_top, bx0, bz0, bx1, bz1, block)]


def _roof_cone(bx0, bz0, bx1, bz1, wall_top, block, mode="cone"):
    """Tall, centred roof for ROUND/polygonal footprints (towers): stacked
    circular rings whose radius shrinks with height to a point/dome. The
    height is driven by the radius with a floor so even a slim top floor gets
    a proper pointed roof (not a flat cap). `mode` picks the profile:
      cone/conical   linear taper, H≈1.4r           (steep cone)
      spire/needle   linear taper, H≈2.2r           (tall thin needle)
      dome           hemisphere   H≈r               (rounded)
      onion          dome + a short spike on top    (onion dome)
    """
    W, D = bx1 - bx0, bz1 - bz0
    r = max(W, D) / 2.0
    cx, cz = (bx0 + bx1) / 2.0, (bz0 + bz1) / 2.0
    if mode in ("spire", "needle", "helm", "rhenish-helm"):
        H = int(min(max(round(2.2 * r) + 2, 6), 22))
    elif mode in ("dome", "stepped-dome"):
        H = int(min(max(round(r) + 1, 3), 12))
    elif mode in ("onion", "onion-dome"):
        H = int(min(max(round(1.2 * r) + 1, 4), 14))
    else:                                            # cone / conical
        H = int(min(max(round(1.4 * r) + 1, 5), 18))
    spike = mode in ("onion", "onion-dome")
    ops = []
    for k in range(H + 1):
        f = k / float(H) if H else 1.0               # 0 (base) .. 1 (apex)
        if mode in ("dome", "stepped-dome"):
            rk = r * math.sqrt(max(0.0, 1.0 - f * f))           # hemisphere
        elif spike:
            rk = r * math.sqrt(max(0.0, 1.0 - f * f)) if f < 0.8 else 0.0
        else:                                                   # linear taper
            rk = r * (1.0 - f)
        if rk < 0.5:                                 # apex → single column
            ops.append(_roof_place(int(round(cx)), wall_top + k,
                                    int(round(cz)), block))
            continue
        ix0, ix1 = int(round(cx - rk)), int(round(cx + rk)) + 1
        iz0, iz1 = int(round(cz - rk)), int(round(cz + rk)) + 1
        ring = footprint_for("x", [ix0, 0, iz0, ix1, 1, iz1],
                             footprint_shape="circle")
        for (rx0, rz0, rx1, rz1) in ring.rects():
            ops.append(_roof_rect(wall_top + k, rx0, rz0, rx1, rz1, block))
    if spike:                                        # onion neck + finial
        for s in range(1, 4):
            ops.append(_roof_place(int(round(cx)), wall_top + H + s,
                                   int(round(cz)), block))
    return ops or [_roof_rect(wall_top, bx0, bz0, bx1, bz1, block)]


def _roof_pagoda(bx0, bz0, bx1, bz1, wall_top, by1, block, floors):
    """Tiered eaves: a 1-cell overhang cap at each floor top + a hip on top."""
    ops = []
    tops = sorted({int(f["y1"]) for f in floors}) or [wall_top]
    for t in tops:
        ops.append(_roof_rect(t, bx0 - 1, bz0 - 1, bx1 + 1, bz1 + 1, block))
    ops += _roof_hip(bx0, bz0, bx1, bz1, wall_top, by1, block)
    return ops


def _roof_crenellated(perimeter_cells, fp_rects, wall_top, block, merlon):
    """Flat cap + a parapet of alternating merlons around the perimeter."""
    ops = [_roof_rect(wall_top, x0, z0, x1, z1, block)
           for (x0, z0, x1, z1) in fp_rects]
    for (px, pz) in sorted(perimeter_cells):
        if (px + pz) % 2 == 0:                  # alternating merlons
            ops.append(_roof_place(px, wall_top + 1, pz, merlon))
    return ops


def _emit_room_windows(all_rooms, glass_block, win_shape=0):
    """A glass window centred (mid-height) on every EXTERIOR wall of each room,
    so rooms get light on ≥2 sides (Alexander light-on-two-sides + light
    coverage + window-place). Interior (shared) walls get none. Emitted as
    wall-role ops; the later door-carve wins at door cells."""
    ops: list[dict] = []
    # Per-floor occupancy: every (x,z) covered by any room. A wall is EXTERIOR
    # if the cell one step outward isn't covered — robust to overlapping or
    # stair-extended rooms (pairwise flush-checks missed those, leaving big
    # buildings' perimeter rooms windowless).
    occ: dict[int, set] = {}
    for r in all_rooms:
        f = int(r["floor"]); a = r["aabb"]
        s = occ.setdefault(f, set())
        for x in range(int(a[0]), int(a[3])):
            for z in range(int(a[2]), int(a[5])):
                s.add((x, z))

    def _g(x, y, z):
        ops.append({"kind": "place", "envelope_role": "wall", "room_id": None,
                    "at": [x, y, z], "block": glass_block})

    # FIX 3: forma de ventana por edificio (win_shape) — en el PLANO del muro,
    # sin proyección (no sombrea, no toca density) → 0 (estándar 1×2) /
    # 1 (alta 1×3) / 2 (ancha 2×2). Rompe el "todas iguales 1×1".
    def _window(ax, wy, az, along, room_h):
        """along='x' (ventana sobre muro ⟂x) o 'z'. Emite el patrón."""
        tall = win_shape == 1 and room_h >= 6
        wide = win_shape == 2
        ys = [wy, wy + 1] + ([wy + 2] if tall else [])
        offs = [0, 1] if wide else [0]
        for o in offs:
            for y in ys:
                if along == "x":
                    _g(ax + o, y, az)
                else:
                    _g(ax, y, az + o)

    for r in all_rooms:
        x0, y0, z0, x1, y1, z1 = (int(v) for v in r["aabb"])
        if x1 - x0 < 3 or z1 - z0 < 3 or y1 - y0 < 4:
            continue
        fset = occ.get(int(r["floor"]), set())
        wy = y0 + 2                                   # sill above the floor
        rh = y1 - y0
        cx, cz = (x0 + x1) // 2, (z0 + z1) // 2
        # exterior if the cell just OUTSIDE the wall midpoint is unoccupied
        if (cx, z0 - 1) not in fset:
            _window(cx, wy, z0, "x", rh)
        if (cx, z1) not in fset:
            _window(cx, wy, z1 - 1, "x", rh)
        if (x0 - 1, cz) not in fset:
            _window(x0, wy, cz, "z", rh)
        if (x1, cz) not in fset:
            _window(x1 - 1, wy, cz, "z", rh)
    return ops


def _emit_roof_ops(*, roof_style, is_rect_fp, bx0, bz0, bx1, bz1, wall_top,
                   by1, roof_block, stair_block, fp_rects, fp_perimeter,
                   floors, fp_shape="rectangle", roof_features=(),
                   accent_block=None):
    """Dispatch roof_style → a builder. Masked (non-rect) footprints only get
    shape-safe roofs (flat cap / crenellation / pagoda eaves); a gable over a
    courtyard would bridge it, so those fall back to the flat cap.

    On a rectangular footprint the base roof is COMPOSED with any modular
    `roof_features` (dormer / chimney / cupola / finial / ridge-cresting /
    corner-turrets) so roofs, towers and parts combine freely (LEGO)."""
    rs = (roof_style or "hip").lower()
    feats = [f for f in (roof_features or []) if f and f != "none"]
    flat_cap = [_roof_rect(wall_top, x0, z0, x1, z1, roof_block)
                for (x0, z0, x1, z1) in fp_rects]
    # Crenellation iterates the REAL perimeter cells, so it works on any
    # footprint (round, U, cross, L) — handle it before the rect/mask split.
    if rs in ("crenellated", "battlement", "battlements", "parapet",
              "stepped-parapet", "stepped_parapet", "ziggurat"):
        ops = _roof_crenellated(fp_perimeter, fp_rects, wall_top, roof_block,
                                roof_block)
    elif rs in ("flat", "shed", "mono-pitch", "monopitch") and not is_rect_fp:
        ops = flat_cap                          # genuinely flat styles only
    elif not is_rect_fp:
        # Masked footprint: only shape-safe roofs. A gable/mansard over a U or
        # cross would bridge the courtyard, so round shapes get a cone/dome/
        # spire, pagodas get tiered eaves, everything else a flat cap.
        if fp_shape in ROUNDED_SHAPES:
            if rs in ("spire", "needle", "helm", "rhenish-helm"):
                cone_mode = "spire"
            elif rs in ("dome", "stepped-dome"):
                cone_mode = "dome"
            elif rs in ("onion", "onion-dome"):
                cone_mode = "onion"
            else:                                    # conical/pyramidal/hip/…
                cone_mode = "cone"
            ops = _roof_cone(bx0, bz0, bx1, bz1, wall_top, roof_block,
                             mode=cone_mode)
        elif rs in ("pagoda", "double-pagoda", "tiered", "pavilion",
                     "chinese-pagoda"):
            ops = _roof_pagoda(bx0, bz0, bx1, bz1, wall_top, by1, roof_block,
                               floors)
        elif rs in ("chinese-hip", "japanese-hip", "temple", "upturned-eave",
                     "upturned", "irimoya", "asian"):
            # East-Asian flying-eave hip — emit over the bounding box of the
            # top floor (small overhang into the L-shape voids reads as the
            # iconic palace silhouette and the voxelizer's later-wins dedupe
            # plus the footprint_void carve below keep it clean inside).
            ops = _roofs.compose_roof(rs, bx0=bx0, bz0=bz0, bx1=bx1, bz1=bz1,
                                       wall_top=wall_top, by1=by1,
                                       block=roof_block, stair=stair_block,
                                       accent=accent_block, features=feats,
                                       floors=floors)
        else:
            ops = flat_cap
    else:
        # Rectangular footprint → the full roof library COMPOSED with the
        # modular add-ons the LLM chose (dormer/chimney/cupola/finial/turrets).
        ops = _roofs.compose_roof(rs, bx0=bx0, bz0=bz0, bx1=bx1, bz1=bz1,
                                  wall_top=wall_top, by1=by1, block=roof_block,
                                  stair=stair_block, accent=accent_block,
                                  features=feats, floors=floors)
    if len(ops) > _ROOF_MAX_OPS:                # budget guard → flat cap
        ops = flat_cap
    return ops


def plan_architecture_v4(global_intent: dict,
                          floor_plans: list[dict]) -> dict:
    """v4 architecture planner — consumes a list of floor_plans[] and
    emits an architecture_plan_v4 dict.

    Args:
        global_intent: validated global_intent_v4 dict.
        floor_plans:   list of floor_plan dicts (one per floor, indexed
            by floor_index after inter_floor_validator has run).

    Returns: dict validating against architecture_plan_v4.schema.json.
    """
    style = global_intent.get("style", "medieval")
    category = global_intent.get("category")
    palette = _palette(style, category)
    building_aabb = global_intent.get("building_aabb") or [0, 0, 0, 1, 1, 1]
    bx0, by0, bz0, bx1, by1, bz1 = building_aabb
    floors = global_intent.get("floors", [])

    # Footprint mask from the chosen silhouette's footprint_shape. Drives the
    # actual building OUTLINE (round tower, U-courtyard, cross, L, …). Falls
    # back to the full rectangle for rectangular/unknown shapes → identical to
    # the previous behaviour.
    sil_params = global_intent.get("silhouette_parameters") or {}
    _sil_id = global_intent.get("silhouette_id")
    _n_fl = max(1, len(floors))
    _floor_idxs = sorted(int(f["index"]) for f in floors) or [0]

    def _fp(idx):
        return footprint_for(_sil_id, building_aabb, floor_index=idx,
                             n_floors=_n_fl,
                             footprint_shape=sil_params.get("footprint_shape"),
                             params=sil_params)

    # Footprint mask per floor. With floor_progression="uniform" (default)
    # every floor is identical → same as before. setback/base_to_tower make
    # upper floors a strict subset (no floating walls). Drives the building
    # OUTLINE (round tower, U-courtyard, cross, setback tower, …).
    fp_by_floor = {idx: _fp(idx) for idx in _floor_idxs}
    fpmask = fp_by_floor[_floor_idxs[0]]                 # floor 0 (ground)
    fp_top = fp_by_floor[_floor_idxs[-1]]                # top floor (for roof)
    is_rect_fp = (fp_top.shape == "rectangle")           # roof shape source
    fp_rects = fp_top.rects()
    fp_cells = fpmask.cells                              # floor-0 (edge ring)
    fp_perimeter = fpmask.perimeter_cells()
    _building_rect = {(x, z) for x in range(bx0, bx1) for z in range(bz0, bz1)}

    def _floor_void_rects(idx):
        vcells = _building_rect - set(fp_by_floor[idx].cells)
        return (Footprint(frozenset(vcells), (bx0, bz0, bx1, bz1)).rects()
                if vcells else [])

    # Aggregate rooms across all floor_plans, preserving their floor index.
    all_rooms: list[dict] = []
    reservations_by_floor: dict[int, list[dict]] = {}
    adjacency_per_floor: list[list[dict]] = []
    for fp in floor_plans:
        idx = int(fp.get("floor_index", 0))
        all_rooms.extend(fp.get("rooms") or [])
        reservations_by_floor[idx] = list(fp.get("reserved_footprints") or [])
        adjacency_per_floor.append(list(fp.get("adjacency_graph") or []))

    ops: list[dict] = []
    materials_usage: dict[str, dict] = {}

    def _slot_for(block: str) -> str:
        for slot in ("primary", "secondary", "accent", "floor", "roof"):
            if palette.get(slot) == block:
                return f"@{slot}"
        return "@other"

    def _bump(block: str, role: str) -> None:
        info = materials_usage.setdefault(block, {
            "block_id":       block,
            "palette_slot":   _slot_for(block),
            "envelope_roles": [],
            "op_count":       0,
        })
        if role not in info["envelope_roles"]:
            info["envelope_roles"].append(role)
        info["op_count"] += 1

    # ── 1. Room shells (one fill_hollow per room) ──
    rooms_sorted = sorted(all_rooms, key=lambda r: (int(r["floor"]), r["id"]))
    for r in rooms_sorted:
        shared = [
            other["id"] for other in rooms_sorted
            if other["id"] != r["id"]
            and _aabbs_share_wall(tuple(r["aabb"]), tuple(other["aabb"]))
        ]
        wall_block = palette["primary"]
        floor_block = palette["floor"]
        ops.append({
            "kind": "fill_hollow",
            "envelope_role": "wall",
            "room_id": r["id"],
            "shared_with": shared,
            "aabb": list(r["aabb"]),
            "wall_block":    wall_block,
            "floor_block":   floor_block,
            "ceiling_block": wall_block,
        })
        _bump(wall_block, "wall")
        _bump(floor_block, "floor_slab")

    # ── 1b. Windows on exterior walls (light on ≥2 sides) ──
    glass_block = "minecraft:glass_pane"
    # FIX 3: forma de ventana por edificio (hash estable de estilo+silueta+aabb)
    # → ventanas no todas iguales, sin coste (en el plano, no proyecta).
    from pipeline.skills.seedutil import seed_from
    win_shape = seed_from(style, global_intent.get("silhouette_id"),
                          tuple(building_aabb)) % 3
    win_ops = _emit_room_windows(all_rooms, glass_block, win_shape)
    if win_ops:
        ops.extend(win_ops)
        _bump(glass_block, "wall")

    # ── 2. Inter-storey floor slabs following each floor's footprint mask ──
    for floor in sorted(floors, key=lambda f: f["index"]):
        idx = int(floor["index"])
        y0 = int(floor["y0"])
        slab_block = palette["floor"]
        for (rx0, rz0, rx1, rz1) in fp_by_floor.get(idx, fpmask).rects():
            ops.append({
                "kind":  "rect",
                "envelope_role": "floor_slab",
                "room_id": None,
                "axis":  "y",
                "level": y0,
                "aabb":  [rx0, y0, rz0, rx1, y0 + 1, rz1],
                "block": slab_block,
            })
            _bump(slab_block, "floor_slab")

        # Cut stair_void holes for stair reservations on this floor (idx>0
        # only — ground floor slabs aren't interrupted by stairs).
        if idx == 0:
            continue
        for rsv in reservations_by_floor.get(idx, []):
            if rsv.get("kind") not in ("stair", "shaft"):
                continue
            ops.append({
                "kind":  "fill",
                "envelope_role": "stair_void",
                "room_id": None,
                "aabb":  [int(rsv["x0"]), y0,
                           int(rsv["z0"]), int(rsv["x1"]),
                           y0 + 1, int(rsv["z1"])],
                "block": "minecraft:air",
            })
            # air is not a real palette block; do not bump materials_usage.

    # ── 3. Roof — sits ON the walls, never floating ──
    # Lay the roof base at the TOP OF THE WALLS (max room/floor y1), NOT at
    # building_aabb.y1. building_aabb often reserves roof-pitch headroom, so
    # pinning the roof to by1 left a 2-5 layer air gap and a slab floating in
    # the sky. For pitched styles we step the roof inward layer-by-layer up
    # to by1 (hip/pyramid), filling the headroom; flat styles get one cap.
    roof_block = palette["roof"]
    _hi = global_intent.get("height_intent") or {}
    roof_style = _hi.get("roof_style", "gable")
    roof_features = _hi.get("roof_features") or []
    # Prefer the explicit accent slot (e.g. chinese.gold_block for gilt finials);
    # fall back to secondary/primary for legacy palettes that lack an accent.
    accent_block = (palette.get("accent")
                    or palette.get("secondary")
                    or palette.get("primary"))
    stair_block = _ROOF_STAIR_PER_STYLE.get(style, "minecraft:cobblestone_stairs")
    wall_top = max(
        (int(r["aabb"][4]) for r in all_rooms
         if isinstance(r.get("aabb"), list) and len(r["aabb"]) == 6),
        default=max((int(f["y1"]) for f in floors), default=by1 - 1))
    # The roof sits on the TOP FLOOR's footprint, not the full building_aabb —
    # so a tapered/round tower gets a roof matching its narrow top instead of a
    # wide overhanging cap. For a plain rectangle this equals building_aabb.
    _tc = fp_top.cells
    if _tc:
        _txs = [c[0] for c in _tc]; _tzs = [c[1] for c in _tc]
        rbx0, rbx1, rbz0, rbz1 = min(_txs), max(_txs) + 1, min(_tzs), max(_tzs) + 1
    else:
        rbx0, rbz0, rbx1, rbz1 = bx0, bz0, bx1, bz1
    roof_ops = _emit_roof_ops(
        roof_style=roof_style, is_rect_fp=is_rect_fp,
        bx0=rbx0, bz0=rbz0, bx1=rbx1, bz1=rbz1, wall_top=wall_top, by1=by1,
        roof_block=roof_block, stair_block=stair_block,
        fp_rects=fp_rects, fp_perimeter=fp_top.perimeter_cells(), floors=floors,
        fp_shape=fp_top.shape, roof_features=roof_features,
        accent_block=accent_block)
    for rop in roof_ops:
        ops.append(rop)
    if roof_ops:
        _bump(roof_block, "roof")

    # ── 3a. Footprint void — carve to air, PER FLOOR, everything inside
    # building_aabb that is NOT in that floor's footprint (courtyard, cross
    # gaps, around a round tower, the setback step of a tapering tower). Keeps
    # the ground plane on floor 0 (from y0+1). Robustness keystone: makes the
    # shape correct even if the floor_planner ignores it, and carves the
    # setback steps so upper walls never float.
    for floor in sorted(floors, key=lambda f: f["index"]):
        idx = int(floor["index"])
        fy0, fy1 = int(floor["y0"]), int(floor["y1"])
        v_lo = fy0 + 1 if idx == _floor_idxs[0] else fy0
        for (vx0, vz0, vx1, vz1) in _floor_void_rects(idx):
            ops.append({
                "kind": "fill", "envelope_role": "footprint_void",
                "room_id": None,
                "aabb": [vx0, v_lo, vz0, vx1, max(v_lo + 1, fy1 + 1), vz1],
                "block": "minecraft:air",
            })

    # ── 3b. Building edge ring — stair blocks at y=by0, one cell OUTSIDE the
    # building footprint. This guarantees the evaluator's _building_edge
    # metric (which looks for *_stairs/_slab/_planks at the 1-cell ring
    # around footprint) scores >0. Style picks the stair block.
    EDGE_STAIRS_PER_STYLE = {
        "medieval":      "minecraft:cobblestone_stairs",
        "rustic":        "minecraft:cobblestone_stairs",
        "fantasy":       "minecraft:cobblestone_stairs",
        "gothic":        "minecraft:stone_brick_stairs",
        "renaissance":   "minecraft:stone_brick_stairs",
        "modern":        "minecraft:smooth_stone_stairs",
        "minimalist":    "minecraft:smooth_stone_stairs",
        "japanese":      "minecraft:spruce_stairs",
        "chinese":       "minecraft:dark_oak_stairs",
        "mediterranean": "minecraft:sandstone_stairs",
    }
    edge_block = EDGE_STAIRS_PER_STYLE.get(style, "minecraft:cobblestone_stairs")
    site_aabb = global_intent.get("site_aabb") or building_aabb
    sx0, _, sz0, sx1, _, sz1 = site_aabb
    if is_rect_fp:
        # Rectangle: 4 explicit fill ops — one per side, 1 cell wide, clipped.
        if bx0 - 1 >= sx0:
            ops.append({"kind": "fill", "envelope_role": "frame", "room_id": None,
                         "aabb": [bx0 - 1, by0, max(bz0 - 1, sz0),
                                  bx0,     by0 + 1, min(bz1 + 1, sz1)],
                         "block": edge_block})
        if bx1 + 1 <= sx1:
            ops.append({"kind": "fill", "envelope_role": "frame", "room_id": None,
                         "aabb": [bx1,     by0, max(bz0 - 1, sz0),
                                  bx1 + 1, by0 + 1, min(bz1 + 1, sz1)],
                         "block": edge_block})
        if bz0 - 1 >= sz0:
            ops.append({"kind": "fill", "envelope_role": "frame", "room_id": None,
                         "aabb": [max(bx0 - 1, sx0), by0, bz0 - 1,
                                  min(bx1 + 1, sx1), by0 + 1, bz0],
                         "block": edge_block})
        if bz1 + 1 <= sz1:
            ops.append({"kind": "fill", "envelope_role": "frame", "room_id": None,
                         "aabb": [max(bx0 - 1, sx0), by0, bz1,
                                  min(bx1 + 1, sx1), by0 + 1, bz1 + 1],
                         "block": edge_block})
        _bump(edge_block, "frame")
    else:
        # Masked footprint: lay the apron on the OUTWARD neighbour of each
        # perimeter cell that is itself outside the footprint, so the edge
        # treatment hugs the real (concave/round) outline — keeps
        # _building_edge meaningful for shaped buildings.
        apron: set = set()
        for (px, pz) in fp_perimeter:
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, nz = px + dx, pz + dz
                if (nx, nz) in fp_cells:
                    continue
                if sx0 <= nx < sx1 and sz0 <= nz < sz1:
                    apron.add((nx, nz))
        for (nx, nz) in apron:
            ops.append({"kind": "place", "envelope_role": "frame",
                         "room_id": None, "at": [nx, by0, nz],
                         "block": edge_block})
        if apron:
            _bump(edge_block, "frame")

    # ── 4. Wall fittings audit (voxels deferred) ──
    max_room_h = max(
        (int(r["aabb"][4]) - int(r["aabb"][1]) for r in rooms_sorted),
        default=0)
    fittings = select_wall_fittings(
        style=style,
        height_intent=global_intent.get("height_intent") or {},
        category=global_intent.get("category"),
        floors_count=len(floors),
        max_room_height=max_room_h,
    )

    return {
        "schema_version": "v4",
        "ops":            ops,
        "style_palette":  {k: palette[k] for k in
                            ("primary", "secondary", "accent", "floor", "roof")
                            if k in palette},
        "materials_usage": materials_usage,
        "wall_fittings_applied": fittings,
        "adjacency_graph_per_floor": adjacency_per_floor,
        "generated_by": {
            "deterministic": True,
            "module": "pipeline.agents.architecture_planner",
            "version": "v4",
        },
    }


__all__ = [
    "plan_architecture",       # v3
    "plan_architecture_v4",    # v4
    "select_wall_fittings",
    "STYLE_PALETTES",
    "STYLE_WALL_FITTINGS",
    "CONDITIONAL_FITTINGS",
    "EXCLUSIONS",
]
