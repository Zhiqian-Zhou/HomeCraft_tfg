"""Parametric-skill kwargs contract (shared vocabulary across parametric skills).

A *parametric* skill is still a pure function of `(aabb, materials, style, kwargs)`
— variety comes from the **caller (specialist agent) choosing different kwargs**,
NOT from internal RNG. With no kwargs a skill must behave exactly as before
(AABB+style driven), so existing skills keep working unchanged.

Canonical kwargs (all OPTIONAL):
    size_class : "xs"|"s"|"m"|"l"|"xl"   scale hint independent of AABB
    height     : int (absolute) | float (multiplier)
    variant    : str  (skill-specific enum; clamps to default if unknown)
    palette    : {"@role": "minecraft:..."}   per-build Materials overrides
    color      : str  named colour ("red","gold",…) → palette overrides
    tier_count : int  (pagoda tiers / fountain basins / mansard breaks)
    facing     : "north"|"south"|"east"|"west"  (a.k.a. orientation)
    flare      : float 0..1.5  eave overhang / upturn intensity
    seed       : int  OPTIONAL determinism knob; defaults to 0 (deterministic)

The load-bearing helper is :func:`with_overrides`, which finally makes the RAG
``style_variants[style].palette_overrides`` field functional by cloning the
``Materials`` dataclass with the overridden slots. A parametric skill that wants
overrides must **bake** the overridden roles to concrete blocks at build time
(see :func:`resolve`), because the composer resolves bare ``@role`` strings
against the *original* Materials, not the clone.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from .base import Materials, _resolve

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_RAG_SKILLS_DIR = REPO_ROOT / "rag" / "skills"

SIZE_CLASSES = ("xs", "s", "m", "l", "xl")

# Named colour → concrete block. Applied to the @accent and @roof slots by
# resolve_color() (the visible "colour" of a decorative element). For finer
# control the caller passes an explicit `palette` kwarg instead.
_COLOR_BLOCKS = {
    "white": "minecraft:white_concrete",
    "orange": "minecraft:orange_concrete",
    "magenta": "minecraft:magenta_concrete",
    "light_blue": "minecraft:light_blue_concrete",
    "yellow": "minecraft:yellow_concrete",
    "lime": "minecraft:lime_concrete",
    "pink": "minecraft:pink_concrete",
    "gray": "minecraft:gray_concrete",
    "light_gray": "minecraft:light_gray_concrete",
    "cyan": "minecraft:cyan_concrete",
    "purple": "minecraft:purple_concrete",
    "blue": "minecraft:blue_concrete",
    "brown": "minecraft:brown_concrete",
    "green": "minecraft:green_concrete",
    "red": "minecraft:red_concrete",
    "black": "minecraft:black_concrete",
    # aliases
    "gold": "minecraft:gold_block",
    "golden": "minecraft:gold_block",
    "stone": "minecraft:stone_bricks",
}


def size_class_of(aabb, kwargs: dict | None = None) -> str:
    """Return the size class. Explicit `size_class` kwarg wins; else bucket by max dim."""
    kwargs = kwargs or {}
    sc = kwargs.get("size_class")
    if isinstance(sc, str) and sc in SIZE_CLASSES:
        return sc
    m = max(aabb.w, aabb.h, aabb.d)
    if m <= 4:
        return "xs"
    if m <= 7:
        return "s"
    if m <= 12:
        return "m"
    if m <= 18:
        return "l"
    return "xl"


def resolve_height(aabb, kwargs: dict | None, default: int) -> int:
    """Resolve a height override. int=absolute, float=multiplier of default, None=default."""
    kwargs = kwargs or {}
    h = kwargs.get("height")
    if h is None:
        return int(default)
    if isinstance(h, bool):  # guard: bool is an int subclass
        return int(default)
    if isinstance(h, float):
        return max(1, round(default * h))
    try:
        return max(1, int(h))
    except (TypeError, ValueError):
        return int(default)


def resolve_int(kwargs: dict | None, key: str, default: int, *, lo: int = 1, hi: int = 64) -> int:
    """Resolve a clamped int kwarg (e.g. tier_count)."""
    kwargs = kwargs or {}
    v = kwargs.get(key)
    if v is None or isinstance(v, bool):
        return default
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def resolve_variant(kwargs: dict | None, allowed, default: str) -> str:
    """Return the chosen variant if it's in `allowed`, else `default` (no crash)."""
    kwargs = kwargs or {}
    v = kwargs.get("variant")
    if isinstance(v, str) and v in set(allowed):
        return v
    return default


def resolve_facing(aabb, kwargs: dict | None, default: str | None = None) -> str:
    """Resolve a cardinal facing/orientation kwarg; default derived from aspect."""
    kwargs = kwargs or {}
    f = kwargs.get("facing") or kwargs.get("orientation")
    if isinstance(f, str) and f in ("north", "south", "east", "west"):
        return f
    if default:
        return default
    # long axis → ridge runs along it; default face the wider span
    return "east" if aabb.w >= aabb.d else "south"


def resolve_flare(kwargs: dict | None, default: float = 1.0) -> float:
    kwargs = kwargs or {}
    v = kwargs.get("flare")
    if v is None or isinstance(v, bool):
        return default
    try:
        return max(0.0, min(1.5, float(v)))
    except (TypeError, ValueError):
        return default


def resolve_color(color_name: str | None) -> dict[str, str]:
    """Map a named colour to a small set of `@role` palette overrides."""
    if not color_name:
        return {}
    block = _COLOR_BLOCKS.get(str(color_name).lower().replace(" ", "_"))
    if not block:
        return {}
    return {"@accent": block, "@roof": block}


# ────────────────────────────────────────────────────────────────────────
#  Palette overrides — clone Materials so style_variants.palette_overrides works
# ────────────────────────────────────────────────────────────────────────

_RAG_CACHE: dict[str, dict] = {}


def _load_rag_skill(rag_id: str) -> dict:
    if rag_id in _RAG_CACHE:
        return _RAG_CACHE[rag_id]
    path = _RAG_SKILLS_DIR / f"{rag_id}.json"
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    _RAG_CACHE[rag_id] = data
    return data


def _slot_name(key: str) -> str:
    """`@primary` / `primary` → `primary`."""
    return key[1:] if key.startswith("@") else key


def _apply_palette(materials: Materials, overrides: dict[str, str]) -> Materials:
    """Return a clone of `materials` with the given `@role`→block overrides applied."""
    if not overrides:
        return materials
    updates = {}
    for key, block in overrides.items():
        slot = _slot_name(key)
        if hasattr(materials, slot) and isinstance(block, str) and block:
            updates[slot] = block
    if not updates:
        return materials
    return dataclasses.replace(materials, **updates)


def with_overrides(materials: Materials, kwargs: dict | None, style: str,
                   rag_id: str | None = None) -> Materials:
    """Clone `materials` merging palette overrides from three layers (low→high priority):

    1. base : the passed-in `materials` (from `Materials.for_style(style)`)
    2. RAG  : `style_variants[style].palette_overrides` of `rag_id` (now functional)
    3. caller: `kwargs["color"]` then `kwargs["palette"]` (explicit, highest)
    """
    kwargs = kwargs or {}
    mats = materials
    # Layer 2 — RAG style_variants
    if rag_id:
        sv = (_load_rag_skill(rag_id).get("style_variants") or {}).get(style) or {}
        mats = _apply_palette(mats, sv.get("palette_overrides") or {})
    # Layer 3a — named colour
    mats = _apply_palette(mats, resolve_color(kwargs.get("color")))
    # Layer 3b — explicit palette
    pal = kwargs.get("palette")
    if isinstance(pal, dict):
        mats = _apply_palette(mats, pal)
    return mats


def resolve(block_or_role: str, materials: Materials) -> str:
    """Bake an `@role` string (or literal block) to a concrete block id against
    `materials`. Use this in a parametric skill to lock overridden roles at
    build time (the composer would otherwise resolve `@role` against the
    original, un-overridden Materials)."""
    return _resolve(block_or_role, materials)
