"""Core types for the skill library.

A skill is a Python function that returns a list of `Op` (AST operations).
The composer materializes ops into concrete `(x, y, z, block_id)` voxels.

The AST is intentionally small. Each op only needs to know how to
`.compile(materials) -> Iterable[(x, y, z, str)]`. The composer collects
them all, applies "later wins" dedupe, filters air, and produces the final
voxel list.

Coordinate convention (matches `reference_building.schema.json`):
    x: width, y: height (up), z: depth.
    AABB is half-open: x in [x0, x1), etc. So `AABB(0,0,0, 5,4,5)` is a
    5x4x5 building with corners (0,0,0) inclusive and (4,3,4) inclusive.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Iterable


# ────────────────────────────────────────────────────────────────────────
#  AABB + Materials
# ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AABB:
    """Half-open axis-aligned bounding box: [x0..x1) × [y0..y1) × [z0..z1)."""
    x0: int; y0: int; z0: int
    x1: int; y1: int; z1: int

    @property
    def w(self) -> int: return self.x1 - self.x0
    @property
    def h(self) -> int: return self.y1 - self.y0
    @property
    def d(self) -> int: return self.z1 - self.z0
    @property
    def size(self) -> tuple[int, int, int]: return (self.w, self.h, self.d)
    @property
    def cx(self) -> int: return (self.x0 + self.x1 - 1) // 2
    @property
    def cz(self) -> int: return (self.z0 + self.z1 - 1) // 2

    def contains(self, x: int, y: int, z: int) -> bool:
        return (self.x0 <= x < self.x1
                and self.y0 <= y < self.y1
                and self.z0 <= z < self.z1)

    def shrink(self, dx: int = 0, dy: int = 0, dz: int = 0) -> "AABB":
        return AABB(self.x0 + dx, self.y0 + dy, self.z0 + dz,
                    self.x1 - dx, self.y1 - dy, self.z1 - dz)


@dataclass
class Materials:
    """Material slots, addressable by role. Block IDs are 1.16.5 namespaced.

    Skills pick role-appropriate blocks; the calling style pack populates
    these fields. Falls back to defaults if unset.
    """
    primary:   str = "minecraft:oak_planks"
    secondary: str = "minecraft:cobblestone"
    accent:    str = "minecraft:stone_bricks"
    roof:      str = "minecraft:dark_oak_planks"
    floor:     str = "minecraft:oak_planks"
    glass:     str = "minecraft:glass_pane"
    light:     str = "minecraft:torch"

    # Common detail blocks for skills
    door:       str = "minecraft:oak_door"
    stairs:     str = "minecraft:oak_stairs"
    fence:      str = "minecraft:oak_fence"
    slab:       str = "minecraft:oak_slab"
    carpet:     str = "minecraft:red_carpet"
    bed:        str = "minecraft:red_bed"
    bookshelf:  str = "minecraft:bookshelf"
    lantern:    str = "minecraft:lantern"
    fence_gate: str = "minecraft:oak_fence_gate"
    flower_pot: str = "minecraft:flower_pot"
    glass_pane: str = "minecraft:glass_pane"

    @classmethod
    def for_style(cls, style: str) -> "Materials":
        """Return a sensible Materials preset by style name."""
        s = style.lower()
        if s == "medieval":
            return cls()
        if s == "modern":
            return cls(
                primary="minecraft:smooth_quartz",
                secondary="minecraft:polished_andesite",
                accent="minecraft:smooth_stone",
                roof="minecraft:smooth_stone_slab",
                floor="minecraft:polished_andesite",
                glass="minecraft:white_stained_glass_pane",
                light="minecraft:redstone_lamp",
                door="minecraft:iron_door",
                stairs="minecraft:smooth_quartz_stairs",
                fence="minecraft:iron_bars",
                slab="minecraft:smooth_stone_slab",
                carpet="minecraft:gray_carpet",
                bed="minecraft:white_bed",
                bookshelf="minecraft:bookshelf",
                lantern="minecraft:end_rod",
                fence_gate="minecraft:iron_bars",
                flower_pot="minecraft:flower_pot",
                glass_pane="minecraft:white_stained_glass_pane",
            )
        if s == "fantasy":
            return cls(
                primary="minecraft:dark_oak_planks",
                secondary="minecraft:mossy_cobblestone",
                accent="minecraft:purpur_block",
                roof="minecraft:purpur_block",
                floor="minecraft:dark_oak_planks",
                glass="minecraft:purple_stained_glass_pane",
                light="minecraft:sea_lantern",
                door="minecraft:dark_oak_door",
                stairs="minecraft:dark_oak_stairs",
                fence="minecraft:dark_oak_fence",
                slab="minecraft:dark_oak_slab",
                carpet="minecraft:purple_carpet",
                bed="minecraft:purple_bed",
                bookshelf="minecraft:bookshelf",
                lantern="minecraft:soul_lantern",
                fence_gate="minecraft:dark_oak_fence_gate",
                flower_pot="minecraft:flower_pot",
                glass_pane="minecraft:purple_stained_glass_pane",
            )
        if s == "chinese":
            # Imperial Chinese palace (Tiananmen / Forbidden City) interior:
            # cinnabar walls, gilt accents, golden tile roof, white marble base.
            return cls(
                primary="minecraft:red_concrete",
                secondary="minecraft:smooth_quartz",
                accent="minecraft:gold_block",
                roof="minecraft:yellow_concrete",
                floor="minecraft:polished_andesite",
                glass="minecraft:red_stained_glass_pane",
                light="minecraft:lantern",
                door="minecraft:spruce_door",
                stairs="minecraft:red_nether_brick_stairs",
                fence="minecraft:spruce_fence",
                slab="minecraft:smooth_quartz_slab",
                carpet="minecraft:red_carpet",
                bed="minecraft:red_bed",
                bookshelf="minecraft:bookshelf",
                lantern="minecraft:lantern",
                fence_gate="minecraft:spruce_fence_gate",
                flower_pot="minecraft:flower_pot",
                glass_pane="minecraft:red_stained_glass_pane",
            )
        if s == "japanese":
            # Traditional Japanese palace/temple: dark spruce timber, white
            # plaster panels, charcoal roof, paper screens.
            return cls(
                primary="minecraft:spruce_planks",
                secondary="minecraft:white_terracotta",
                accent="minecraft:dark_oak_log",
                roof="minecraft:dark_oak_planks",
                floor="minecraft:spruce_planks",
                glass="minecraft:white_stained_glass_pane",
                light="minecraft:lantern",
                door="minecraft:spruce_door",
                stairs="minecraft:dark_oak_stairs",
                fence="minecraft:spruce_fence",
                slab="minecraft:spruce_slab",
                carpet="minecraft:white_carpet",
                bed="minecraft:white_bed",
                bookshelf="minecraft:bookshelf",
                lantern="minecraft:lantern",
                fence_gate="minecraft:spruce_fence_gate",
                flower_pot="minecraft:flower_pot",
                glass_pane="minecraft:white_stained_glass_pane",
            )
        if s == "gothic":
            # Cathedral / dark keep: dark stone, soul-fire light, stained glass.
            return cls(
                primary="minecraft:stone_bricks",
                secondary="minecraft:dark_oak_planks",
                accent="minecraft:chiseled_stone_bricks",
                roof="minecraft:dark_oak_planks",
                floor="minecraft:polished_andesite",
                glass="minecraft:purple_stained_glass_pane",
                light="minecraft:soul_lantern",
                door="minecraft:dark_oak_door",
                stairs="minecraft:stone_brick_stairs",
                fence="minecraft:dark_oak_fence",
                slab="minecraft:stone_brick_slab",
                carpet="minecraft:purple_carpet",
                bed="minecraft:purple_bed",
                bookshelf="minecraft:bookshelf",
                lantern="minecraft:soul_lantern",
                fence_gate="minecraft:dark_oak_fence_gate",
                flower_pot="minecraft:flower_pot",
                glass_pane="minecraft:purple_stained_glass_pane",
            )
        if s == "renaissance":
            # Italian palazzo: sandstone, polished diorite, gilded trim.
            return cls(
                primary="minecraft:smooth_sandstone",
                secondary="minecraft:polished_diorite",
                accent="minecraft:gold_block",
                roof="minecraft:red_terracotta",
                floor="minecraft:smooth_sandstone",
                glass="minecraft:glass_pane",
                light="minecraft:lantern",
                door="minecraft:oak_door",
                stairs="minecraft:smooth_sandstone_stairs",
                fence="minecraft:oak_fence",
                slab="minecraft:smooth_sandstone_slab",
                carpet="minecraft:red_carpet",
                bed="minecraft:red_bed",
                bookshelf="minecraft:bookshelf",
                lantern="minecraft:lantern",
                fence_gate="minecraft:oak_fence_gate",
                flower_pot="minecraft:flower_pot",
                glass_pane="minecraft:glass_pane",
            )
        if s == "mediterranean":
            # Whitewashed villa with terracotta tile, sandy floors.
            return cls(
                primary="minecraft:white_terracotta",
                secondary="minecraft:smooth_sandstone",
                accent="minecraft:orange_terracotta",
                roof="minecraft:red_terracotta",
                floor="minecraft:smooth_sandstone",
                glass="minecraft:glass_pane",
                light="minecraft:lantern",
                door="minecraft:oak_door",
                stairs="minecraft:smooth_sandstone_stairs",
                fence="minecraft:oak_fence",
                slab="minecraft:smooth_sandstone_slab",
                carpet="minecraft:orange_carpet",
                bed="minecraft:white_bed",
                bookshelf="minecraft:bookshelf",
                lantern="minecraft:lantern",
                fence_gate="minecraft:oak_fence_gate",
                flower_pot="minecraft:flower_pot",
                glass_pane="minecraft:glass_pane",
            )
        if s == "minimalist":
            # Stark white concrete with grey accents, no carpets.
            return cls(
                primary="minecraft:white_concrete",
                secondary="minecraft:light_gray_concrete",
                accent="minecraft:gray_concrete",
                roof="minecraft:light_gray_concrete",
                floor="minecraft:white_concrete",
                glass="minecraft:glass_pane",
                light="minecraft:end_rod",
                door="minecraft:iron_door",
                stairs="minecraft:cobblestone_stairs",
                fence="minecraft:iron_bars",
                slab="minecraft:smooth_stone_slab",
                carpet="minecraft:white_carpet",
                bed="minecraft:white_bed",
                bookshelf="minecraft:bookshelf",
                lantern="minecraft:end_rod",
                fence_gate="minecraft:iron_bars",
                flower_pot="minecraft:flower_pot",
                glass_pane="minecraft:glass_pane",
            )
        if s == "rustic":
            # Spruce timber + cobble, hay roof, simple farmhouse.
            return cls(
                primary="minecraft:spruce_planks",
                secondary="minecraft:cobblestone",
                accent="minecraft:stripped_spruce_log",
                roof="minecraft:hay_block",
                floor="minecraft:spruce_planks",
                glass="minecraft:glass_pane",
                light="minecraft:lantern",
                door="minecraft:spruce_door",
                stairs="minecraft:cobblestone_stairs",
                fence="minecraft:spruce_fence",
                slab="minecraft:spruce_slab",
                carpet="minecraft:brown_carpet",
                bed="minecraft:red_bed",
                bookshelf="minecraft:bookshelf",
                lantern="minecraft:lantern",
                fence_gate="minecraft:spruce_fence_gate",
                flower_pot="minecraft:flower_pot",
                glass_pane="minecraft:glass_pane",
            )
        return cls()


# ────────────────────────────────────────────────────────────────────────
#  AST operations
# ────────────────────────────────────────────────────────────────────────

class Op(ABC):
    """Base class for AST ops."""
    @abstractmethod
    def compile(self, materials: Materials) -> Iterable[tuple[int, int, int, str]]:
        ...


@dataclass
class PlaceBlock(Op):
    x: int; y: int; z: int
    block: str
    def compile(self, materials):
        return [(self.x, self.y, self.z, _resolve(self.block, materials))]


@dataclass
class Fill(Op):
    """Solid fill of an AABB."""
    aabb: AABB
    block: str
    def compile(self, materials):
        b = _resolve(self.block, materials)
        out = []
        for x in range(self.aabb.x0, self.aabb.x1):
            for y in range(self.aabb.y0, self.aabb.y1):
                for z in range(self.aabb.z0, self.aabb.z1):
                    out.append((x, y, z, b))
        return out


@dataclass
class FillHollow(Op):
    """Hollow shell of an AABB (walls + floor + ceiling). Optional interior fill."""
    aabb: AABB
    wall: str
    fill: str | None = None  # interior block; None = leave air
    floor: str | None = None  # override for y == y0 plane
    ceiling: str | None = None  # override for y == y1 - 1 plane
    def compile(self, materials):
        out = []
        a = self.aabb
        wall = _resolve(self.wall, materials)
        floor = _resolve(self.floor, materials) if self.floor else wall
        ceiling = _resolve(self.ceiling, materials) if self.ceiling else wall
        interior = _resolve(self.fill, materials) if self.fill else None
        for x in range(a.x0, a.x1):
            for y in range(a.y0, a.y1):
                for z in range(a.z0, a.z1):
                    on_floor   = y == a.y0
                    on_ceiling = y == a.y1 - 1
                    on_wall_xz = x == a.x0 or x == a.x1 - 1 or z == a.z0 or z == a.z1 - 1
                    if on_floor:
                        out.append((x, y, z, floor))
                    elif on_ceiling:
                        out.append((x, y, z, ceiling))
                    elif on_wall_xz:
                        out.append((x, y, z, wall))
                    elif interior is not None:
                        out.append((x, y, z, interior))
        return out


@dataclass
class Outline(Op):
    """Outline (only the edges of an AABB)."""
    aabb: AABB
    block: str
    def compile(self, materials):
        a = self.aabb
        b = _resolve(self.block, materials)
        out = []
        for x in range(a.x0, a.x1):
            for y in range(a.y0, a.y1):
                for z in range(a.z0, a.z1):
                    edges = (
                        (x in (a.x0, a.x1 - 1)) +
                        (y in (a.y0, a.y1 - 1)) +
                        (z in (a.z0, a.z1 - 1))
                    )
                    if edges >= 2:
                        out.append((x, y, z, b))
        return out


@dataclass
class Line(Op):
    """Bresenham-like 3D line between two integer points (inclusive on both ends)."""
    x1: int; y1: int; z1: int
    x2: int; y2: int; z2: int
    block: str
    def compile(self, materials):
        b = _resolve(self.block, materials)
        x1, y1, z1, x2, y2, z2 = self.x1, self.y1, self.z1, self.x2, self.y2, self.z2
        dx, dy, dz = abs(x2 - x1), abs(y2 - y1), abs(z2 - z1)
        sx = 1 if x2 >= x1 else -1
        sy = 1 if y2 >= y1 else -1
        sz = 1 if z2 >= z1 else -1
        steps = max(dx, dy, dz)
        out = []
        if steps == 0:
            return [(x1, y1, z1, b)]
        for i in range(steps + 1):
            t = i / steps
            x = round(x1 + (x2 - x1) * t)
            y = round(y1 + (y2 - y1) * t)
            z = round(z1 + (z2 - z1) * t)
            out.append((x, y, z, b))
        return out


@dataclass
class Rect(Op):
    """Filled rectangle on an axis-aligned plane (used for floors, ceilings, walls)."""
    aabb: AABB
    block: str
    axis: str = "y"  # plane normal: 'x', 'y', or 'z'
    level: int | None = None  # if None, use first coord of that axis from aabb
    def compile(self, materials):
        a = self.aabb
        b = _resolve(self.block, materials)
        out = []
        if self.axis == "y":
            lv = self.level if self.level is not None else a.y0
            for x in range(a.x0, a.x1):
                for z in range(a.z0, a.z1):
                    out.append((x, lv, z, b))
        elif self.axis == "x":
            lv = self.level if self.level is not None else a.x0
            for y in range(a.y0, a.y1):
                for z in range(a.z0, a.z1):
                    out.append((lv, y, z, b))
        else:  # z
            lv = self.level if self.level is not None else a.z0
            for x in range(a.x0, a.x1):
                for y in range(a.y0, a.y1):
                    out.append((x, y, lv, b))
        return out


@dataclass
class Cylinder(Op):
    """Hollow or solid cylinder. cx, cz = center; radius in blocks; height = h."""
    cx: int; cz: int; y0: int
    radius: int
    height: int
    block: str
    hollow: bool = True
    def compile(self, materials):
        b = _resolve(self.block, materials)
        out = []
        r = self.radius
        r2_outer = r * r
        r2_inner = (r - 1) * (r - 1)
        for dy in range(self.height):
            for dx in range(-r, r + 1):
                for dz in range(-r, r + 1):
                    d2 = dx * dx + dz * dz
                    if d2 > r2_outer:
                        continue
                    if self.hollow and d2 < r2_inner:
                        continue
                    out.append((self.cx + dx, self.y0 + dy, self.cz + dz, b))
        return out


@dataclass
class Stairs(Op):
    """Staircase between two Y levels.

    Goes from (x0, y0, z0) up to (x1, y1, z1) — one step per Y. Direction is
    inferred from horizontal delta. Adds a single stairs block per step.
    """
    x0: int; y0: int; z0: int
    x1: int; y1: int; z1: int
    block: str = "@stairs"
    def compile(self, materials):
        b = _resolve(self.block, materials)
        dy = self.y1 - self.y0
        if dy == 0:
            return []
        # Decide step direction: largest horizontal delta
        dx = self.x1 - self.x0
        dz = self.z1 - self.z0
        if abs(dx) >= abs(dz):
            sign = 1 if dx > 0 else -1
            steps = abs(dx)
            out = []
            for i in range(min(steps + 1, dy + 1)):
                facing = "east" if sign > 0 else "west"
                out.append((self.x0 + i * sign, self.y0 + i, self.z0, f"{b}[facing={facing}]"))
            return out
        else:
            sign = 1 if dz > 0 else -1
            steps = abs(dz)
            out = []
            for i in range(min(steps + 1, dy + 1)):
                facing = "south" if sign > 0 else "north"
                out.append((self.x0, self.y0 + i, self.z0 + i * sign, f"{b}[facing={facing}]"))
            return out


# ────────────────────────────────────────────────────────────────────────
#  Skill base class
# ────────────────────────────────────────────────────────────────────────

class Skill(ABC):
    """Optional class-based skill. Most skills are just a module-level
    `build()` function — using the class is for skills that want shared
    state across multiple build calls."""
    @abstractmethod
    def build(self, aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
        ...


# ────────────────────────────────────────────────────────────────────────
#  Helpers
# ────────────────────────────────────────────────────────────────────────

def _resolve(block: str, materials: Materials) -> str:
    """Resolve material placeholders like `@primary` to the actual block.

    Supported forms:
        "@primary"                              → "minecraft:oak_planks"
        "@stairs[facing=east]"                  → "minecraft:oak_stairs[facing=east]"
        "@door[half=lower,facing=south]"        → "minecraft:oak_door[half=lower,facing=south]"
        "minecraft:oak_planks"                  → returned as-is
        "minecraft:oak_stairs[facing=west]"     → returned as-is

    Placeholders defined on Materials:
        @primary, @secondary, @accent, @roof, @floor, @glass, @light,
        @door, @stairs, @fence, @slab, @carpet, @bed, @bookshelf,
        @lantern, @fence_gate, @flower_pot, @glass_pane
    Unknown placeholders fall back to "minecraft:stone".
    """
    if not block.startswith("@"):
        return block
    # Split key and optional blockstate suffix `[...]`
    bracket = block.find("[")
    if bracket == -1:
        key, suffix = block[1:], ""
    else:
        key, suffix = block[1:bracket], block[bracket:]
    val = getattr(materials, key, None)
    if val is None:
        return "minecraft:stone"
    # If the resolved value already has a blockstate, drop the placeholder's
    # suffix to avoid double-bracket like minecraft:foo[a=b][c=d].
    if suffix and "[" not in val:
        return val + suffix
    return val


# ────────────────────────────────────────────────────────────────────────
#  Op ↔ JSON serialization (for the pipeline shape-op format)
# ────────────────────────────────────────────────────────────────────────

def _aabb_list(a: AABB) -> list[int]:
    return [a.x0, a.y0, a.z0, a.x1, a.y1, a.z1]


def _aabb_from_list(arr: list[int]) -> AABB:
    return AABB(arr[0], arr[1], arr[2], arr[3], arr[4], arr[5])


def op_to_dict(op: Op) -> dict:
    """Serialize a built-in Op subclass to the shape_op.schema.json format.

    The result is JSON-roundtrippable: `op_from_dict(op_to_dict(o))` produces
    an equivalent Op (same compile output for the same Materials).
    """
    if isinstance(op, PlaceBlock):
        return {"kind": "place", "at": [op.x, op.y, op.z], "block": op.block}
    if isinstance(op, Fill):
        return {"kind": "fill", "aabb": _aabb_list(op.aabb), "block": op.block}
    if isinstance(op, FillHollow):
        d = {"kind": "fill_hollow", "aabb": _aabb_list(op.aabb), "wall": op.wall}
        if op.fill    is not None: d["fill"]    = op.fill
        if op.floor   is not None: d["floor"]   = op.floor
        if op.ceiling is not None: d["ceiling"] = op.ceiling
        return d
    if isinstance(op, Outline):
        return {"kind": "outline", "aabb": _aabb_list(op.aabb), "block": op.block}
    if isinstance(op, Rect):
        d = {"kind": "rect", "aabb": _aabb_list(op.aabb), "axis": op.axis, "block": op.block,
             "level": op.level if op.level is not None
                      else (op.aabb.y0 if op.axis == "y"
                            else op.aabb.x0 if op.axis == "x"
                            else op.aabb.z0)}
        return d
    if isinstance(op, Line):
        return {"kind": "line",
                "from": [op.x1, op.y1, op.z1],
                "to":   [op.x2, op.y2, op.z2],
                "block": op.block}
    if isinstance(op, Cylinder):
        return {"kind": "cylinder",
                "cx": op.cx, "cz": op.cz, "y0": op.y0,
                "radius": op.radius, "height": op.height,
                "block": op.block, "hollow": op.hollow}
    if isinstance(op, Stairs):
        return {"kind": "stairs",
                "from": [op.x0, op.y0, op.z0],
                "to":   [op.x1, op.y1, op.z1],
                "block": op.block}
    raise TypeError(f"op_to_dict: unsupported op type {type(op).__name__}")


def op_from_dict(d: dict) -> Op:
    """Deserialize a shape-op JSON dict into the corresponding Op subclass.

    `kind == "skill"` is NOT handled here; skill invocations are expanded by
    the voxelizer (which has access to `get_skill`).
    """
    k = d.get("kind")
    if k == "place":
        x, y, z = d["at"]
        return PlaceBlock(x=x, y=y, z=z, block=d["block"])
    if k == "fill":
        return Fill(aabb=_aabb_from_list(d["aabb"]), block=d["block"])
    if k == "fill_hollow":
        return FillHollow(
            aabb=_aabb_from_list(d["aabb"]),
            wall=d["wall"],
            fill=d.get("fill"),
            floor=d.get("floor"),
            ceiling=d.get("ceiling"))
    if k == "outline":
        return Outline(aabb=_aabb_from_list(d["aabb"]), block=d["block"])
    if k == "rect":
        return Rect(aabb=_aabb_from_list(d["aabb"]), block=d["block"],
                    axis=d.get("axis", "y"), level=d.get("level"))
    if k == "line":
        x1, y1, z1 = d["from"]
        x2, y2, z2 = d["to"]
        return Line(x1=x1, y1=y1, z1=z1, x2=x2, y2=y2, z2=z2, block=d["block"])
    if k == "cylinder":
        return Cylinder(cx=d["cx"], cz=d["cz"], y0=d["y0"],
                        radius=d["radius"], height=d["height"],
                        block=d["block"], hollow=d.get("hollow", True))
    if k == "stairs":
        x0, y0, z0 = d["from"]
        x1, y1, z1 = d["to"]
        return Stairs(x0=x0, y0=y0, z0=z0, x1=x1, y1=y1, z1=z1,
                       block=d.get("block", "@stairs"))
    if k == "skill":
        raise ValueError("op_from_dict: 'skill' ops must be expanded by the voxelizer, not converted to Op directly.")
    raise ValueError(f"op_from_dict: unknown kind {k!r}")
