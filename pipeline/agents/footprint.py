"""Deterministic footprint masks keyed by a silhouette's `footprint_shape`.

The global_designer picks a `silhouette_id` whose skill JSON declares a
`footprint_shape` ("circle", "U", "L", "cross", "T", "H", "O", "octagon", …),
but nothing downstream used it — every building came out as a filled
rectangle. This module turns that shape declaration into a 2D mask of which
(x, z) cells are *building* vs *void*, so the architecture_planner can carve
real courtyards / crosses / round towers and the floor_planner can keep
rooms inside the shape.

Pure stdlib, no project imports → safe to import from both
architecture_planner and floor_planner with no cycle.

Coordinate convention matches building_aabb = [bx0,by0,bz0,bx1,by1,bz1],
half-open: footprint cells are x in [bx0,bx1), z in [bz0,bz1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# Building footprints smaller than this (in the shorter XZ side) are too
# small to carve a sensible shape with >=4-wide arms — fall back to rect.
_MIN_SIDE_FOR_SHAPE = 7
_MIN_ARM = 4


@dataclass(frozen=True)
class Footprint:
    """Set of (x,z) cells that are building, plus cached rect cover."""
    cells: frozenset
    aabb_xz: tuple                      # (x0, z0, x1, z1) half-open bbox
    shape: str = "rectangle"
    _rects: list = field(default=None, compare=False, hash=False, repr=False)

    def contains(self, x: int, z: int) -> bool:
        return (x, z) in self.cells

    def clip_aabb(self, aabb6) -> bool:
        """True iff every XZ cell of a room AABB lies inside the footprint."""
        x0, _, z0, x1, _, z1 = aabb6
        for x in range(int(x0), int(x1)):
            for z in range(int(z0), int(z1)):
                if (x, z) not in self.cells:
                    return False
        return True

    def perimeter_cells(self) -> frozenset:
        out = set()
        for (x, z) in self.cells:
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                if (x + dx, z + dz) not in self.cells:
                    out.add((x, z))
                    break
        return frozenset(out)

    def rects(self) -> list:
        """Cover the cells with a few axis-aligned rects [x0,z0,x1,z1)
        (run-length per Z row, then merge vertically). Memoized."""
        if self._rects is not None:
            return self._rects
        by_z: dict = {}
        for (x, z) in self.cells:
            by_z.setdefault(z, set()).add(x)
        # x-runs per z row
        runs_by_z: dict = {}
        for z, xset in by_z.items():
            xs = sorted(xset)
            runs = []
            s = p = xs[0]
            for x in xs[1:]:
                if x == p + 1:
                    p = x
                else:
                    runs.append((s, p + 1))
                    s = p = x
            runs.append((s, p + 1))
            runs_by_z[z] = set(runs)
        # vertical merge: extend a run downward while identical in z+1
        out = []
        active: dict = {}     # (x0,x1) -> (z_start, z_last)
        for z in sorted(runs_by_z):
            cur = runs_by_z[z]
            for run in list(active):
                if run in cur and active[run][1] == z - 1:
                    active[run] = (active[run][0], z)
                else:
                    z0, z1 = active.pop(run)
                    out.append((run[0], z0, run[1], z1 + 1))
            for run in cur:
                if run not in active:
                    active[run] = (z, z)
        for run, (z0, z1) in active.items():
            out.append((run[0], z0, run[1], z1 + 1))
        object.__setattr__(self, "_rects", out)
        return out

    def inscribed_rect(self):
        """Largest centred axis-aligned rectangle fully inside the footprint
        (approx). Used to place rectangular rooms inside a rounded shape."""
        x0, z0, x1, z1 = self.aabb_xz
        cx, cz = (x0 + x1) // 2, (z0 + z1) // 2
        if (cx, cz) not in self.cells:
            return (x0, z0, x1, z1)            # not a centred shape → bbox
        # grow a rectangle outward from the centre while all 4 edges stay in.
        lo_x, hi_x, lo_z, hi_z = cx, cx, cz, cz
        grew = True
        while grew:
            grew = False
            if all((lo_x - 1, z) in self.cells for z in range(lo_z, hi_z + 1)) \
                    and lo_x - 1 >= x0:
                lo_x -= 1; grew = True
            if all((hi_x + 1, z) in self.cells for z in range(lo_z, hi_z + 1)) \
                    and hi_x + 1 < x1:
                hi_x += 1; grew = True
            if all((x, lo_z - 1) in self.cells for x in range(lo_x, hi_x + 1)) \
                    and lo_z - 1 >= z0:
                lo_z -= 1; grew = True
            if all((x, hi_z + 1) in self.cells for x in range(lo_x, hi_x + 1)) \
                    and hi_z + 1 < z1:
                hi_z += 1; grew = True
        return (lo_x, lo_z, hi_x + 1, hi_z + 1)

    def room_regions(self):
        """Rectangles to tile with rooms. Rounded shapes → the inscribed
        rectangle (rooms are rectangular inside the curve); axis-aligned
        shapes → the rect cover (wings/arms)."""
        if self.shape in ROUNDED_SHAPES:
            return [self.inscribed_rect()]
        return self.rects()

    def exit_cell(self, at, facing_delta):
        """Walk from `at`=(x,z) along facing_delta=(dx,dz) until the next step
        leaves the footprint; return the last in-footprint cell. Used to push a
        door outward onto the real (e.g. round) perimeter."""
        x, z = at
        if (x, z) not in self.cells:
            return at
        dx, dz = facing_delta
        while (x + dx, z + dz) in self.cells:
            x += dx
            z += dz
        return (x, z)


# ── helpers ────────────────────────────────────────────────────────────────

def _rect_cells(x0, z0, x1, z1, bounds):
    bx0, bz0, bx1, bz1 = bounds
    out = set()
    for x in range(max(x0, bx0), min(x1, bx1)):
        for z in range(max(z0, bz0), min(z1, bz1)):
            out.add((x, z))
    return out


def _full(bx0, bz0, bx1, bz1):
    return {(x, z) for x in range(bx0, bx1) for z in range(bz0, bz1)}


def _arm(W, D):
    """Arm/wing thickness: ~1/3 of the shorter side, clamped to >=4."""
    return max(_MIN_ARM, min(W, D) // 3)


# ── rasterised shapes ────────────────────────────────────────────────────────

def _mask_ellipse(bx0, bz0, bx1, bz1, **_):
    W, D = bx1 - bx0, bz1 - bz0
    cx, cz = bx0 + W / 2.0, bz0 + D / 2.0
    rx, rz = W / 2.0, D / 2.0
    out = set()
    for x in range(bx0, bx1):
        for z in range(bz0, bz1):
            nx = (x + 0.5 - cx) / rx
            nz = (z + 0.5 - cz) / rz
            if nx * nx + nz * nz <= 1.0:
                out.add((x, z))
    return out


def _mask_octagon(bx0, bz0, bx1, bz1, **_):
    W, D = bx1 - bx0, bz1 - bz0
    c = max(2, min(W, D) // 3)
    out = set()
    for x in range(bx0, bx1):
        lx = x - bx0
        for z in range(bz0, bz1):
            lz = z - bz0
            if (lx + lz < c or (W - 1 - lx) + lz < c
                    or lx + (D - 1 - lz) < c
                    or (W - 1 - lx) + (D - 1 - lz) < c):
                continue
            out.add((x, z))
    return out


def _mask_diamond(bx0, bz0, bx1, bz1, **_):
    W, D = bx1 - bx0, bz1 - bz0
    cx, cz = bx0 + W / 2.0, bz0 + D / 2.0
    out = set()
    for x in range(bx0, bx1):
        for z in range(bz0, bz1):
            if abs(x + 0.5 - cx) / (W / 2.0) + abs(z + 0.5 - cz) / (D / 2.0) <= 1.0:
                out.add((x, z))
    return out


def _mask_hexagon(bx0, bz0, bx1, bz1, **_):
    # Flat-top hexagon elongated along X: full height in the middle, the two
    # X-ends taper to a vertical edge.
    W, D = bx1 - bx0, bz1 - bz0
    taper = max(1, W // 4)
    out = set()
    for x in range(bx0, bx1):
        lx = x - bx0
        # half-depth available at this column (narrows near x ends)
        t = min(lx, W - 1 - lx)
        frac = min(1.0, (t + 1) / float(taper))
        half = (D / 2.0) * frac
        cz = bz0 + D / 2.0
        for z in range(bz0, bz1):
            if abs(z + 0.5 - cz) <= half:
                out.add((x, z))
    return out


# ── axis-aligned shapes (exact, via rect union/subtraction) ──────────────────

def _mask_L(bx0, bz0, bx1, bz1, params=None, **_):
    W, D = bx1 - bx0, bz1 - bz0
    t = _arm(W, D)
    b = (bx0, bz0, bx1, bz1)
    # bottom wing (full width) + left wing (full depth) → corner at (bx0,bz0)
    return (_rect_cells(bx0, bz0, bx1, bz0 + t, b)
            | _rect_cells(bx0, bz0, bx0 + t, bz1, b))


def _mask_U(bx0, bz0, bx1, bz1, params=None, **_):
    W, D = bx1 - bx0, bz1 - bz0
    t = _arm(W, D)
    b = (bx0, bz0, bx1, bz1)
    open_side = ((params or {}).get("open_side") or "south").lower()
    left = _rect_cells(bx0, bz0, bx0 + t, bz1, b)
    right = _rect_cells(bx1 - t, bz0, bx1, bz1, b)
    top = _rect_cells(bx0, bz0, bx1, bz0 + t, b)      # north bar (z min)
    bottom = _rect_cells(bx0, bz1 - t, bx1, bz1, b)   # south bar (z max)
    # open_side is the side WITHOUT a bar; the two perpendicular wings + back.
    if "north" in open_side or "-z" in open_side:
        return left | right | bottom
    if "east" in open_side or "+x" in open_side:
        return top | bottom | left
    if "west" in open_side or "-x" in open_side:
        return top | bottom | right
    return left | right | top                          # open south (default)


def _mask_T(bx0, bz0, bx1, bz1, **_):
    W, D = bx1 - bx0, bz1 - bz0
    t = _arm(W, D)
    b = (bx0, bz0, bx1, bz1)
    cx = bx0 + W // 2
    bar = _rect_cells(bx0, bz0, bx1, bz0 + t, b)            # top bar
    stem = _rect_cells(cx - t // 2, bz0, cx - t // 2 + t, bz1, b)
    return bar | stem


def _mask_H(bx0, bz0, bx1, bz1, **_):
    W, D = bx1 - bx0, bz1 - bz0
    t = _arm(W, D)
    b = (bx0, bz0, bx1, bz1)
    cz = bz0 + D // 2
    left = _rect_cells(bx0, bz0, bx0 + t, bz1, b)
    right = _rect_cells(bx1 - t, bz0, bx1, bz1, b)
    mid = _rect_cells(bx0, cz - t // 2, bx1, cz - t // 2 + t, b)
    return left | right | mid


def _mask_cross(bx0, bz0, bx1, bz1, **_):
    W, D = bx1 - bx0, bz1 - bz0
    tx = max(_MIN_ARM, W // 3)
    tz = max(_MIN_ARM, D // 3)
    b = (bx0, bz0, bx1, bz1)
    cx = bx0 + W // 2
    cz = bz0 + D // 2
    nave = _rect_cells(cx - tx // 2, bz0, cx - tx // 2 + tx, bz1, b)   # vertical
    transept = _rect_cells(bx0, cz - tz // 2, bx1, cz - tz // 2 + tz, b)
    return nave | transept


def _mask_E(bx0, bz0, bx1, bz1, **_):
    W, D = bx1 - bx0, bz1 - bz0
    t = _arm(W, D)
    b = (bx0, bz0, bx1, bz1)
    cz = bz0 + D // 2
    spine = _rect_cells(bx0, bz0, bx0 + t, bz1, b)
    top = _rect_cells(bx0, bz0, bx1, bz0 + t, b)
    mid = _rect_cells(bx0, cz - t // 2, bx1, cz - t // 2 + t, b)
    bot = _rect_cells(bx0, bz1 - t, bx1, bz1, b)
    return spine | top | mid | bot


def _mask_Z(bx0, bz0, bx1, bz1, **_):
    # Two staggered boxes overlapping in the middle (reads as Z / stagger).
    W, D = bx1 - bx0, bz1 - bz0
    b = (bx0, bz0, bx1, bz1)
    w = max(_MIN_ARM, (2 * W) // 3)
    d = max(_MIN_ARM, (D // 2) + 1)
    a = _rect_cells(bx0, bz0, bx0 + w, bz0 + d, b)         # top-left
    c = _rect_cells(bx1 - w, bz1 - d, bx1, bz1, b)         # bottom-right
    return a | c


def _mask_O(bx0, bz0, bx1, bz1, params=None, **_):
    W, D = bx1 - bx0, bz1 - bz0
    t = max(3, min(W, D) // 4)
    # need a real hole: void must be non-empty with >=3-thick ring
    if W - 2 * t < 2 or D - 2 * t < 2:
        return _full(bx0, bz0, bx1, bz1)
    full = _full(bx0, bz0, bx1, bz1)
    void = _rect_cells(bx0 + t, bz0 + t, bx1 - t, bz1 - t, (bx0, bz0, bx1, bz1))
    return full - void


def _mask_rectangle(bx0, bz0, bx1, bz1, **_):
    return _full(bx0, bz0, bx1, bz1)


_SHAPE_BUILDERS = {
    "rectangle": _mask_rectangle, "square": _mask_rectangle,
    "circle": _mask_ellipse, "ellipse": _mask_ellipse,
    "octagon": _mask_octagon, "diamond": _mask_diamond, "hexagon": _mask_hexagon,
    "L": _mask_L, "U": _mask_U, "T": _mask_T, "H": _mask_H,
    "cross": _mask_cross, "plus": _mask_cross,
    "E": _mask_E, "Z": _mask_Z, "S": _mask_Z,
    "O": _mask_O, "ring": _mask_O, "courtyard": _mask_O,
}
# Shapes that are inherently rounded → rooms use the inscribed rectangle and
# doors must be pushed to the perimeter via exit_cell.
ROUNDED_SHAPES = {"circle", "ellipse", "octagon", "diamond", "hexagon"}


def _normalize_shape(footprint_shape):
    """Map the silhouette's declared footprint_shape string → a builder key."""
    if not footprint_shape:
        return "rectangle"
    raw = str(footprint_shape).strip()
    if raw in _SHAPE_BUILDERS:
        return raw
    s = raw.lower()
    # case-insensitive direct match (letter shapes are stored uppercase)
    for k in _SHAPE_BUILDERS:
        if k.lower() == s:
            return k
    # descriptive aliases seen in the silhouette catalog
    if "central_void" in s or "atrium" in s or "donut" in s:
        return "O"
    if "octagon" in s:
        return "octagon"
    if "circle" in s or "cylinder" in s or "round" in s:
        return "circle"
    if s in ("l", "l-shape", "l_shape"):
        return "L"
    if s in ("u", "u-shape"):
        return "U"
    # long_rectangle, rectangle_or_two_boxes, rectangle_with_dome,
    # irregular_composition, … → safe rectangle
    return "rectangle"


def _largest_component(cells):
    """Keep only the largest 4-connected component (guards against a builder
    accidentally producing two islands)."""
    if not cells:
        return cells
    remaining = set(cells)
    best = set()
    while remaining:
        seed = next(iter(remaining))
        stack = [seed]
        comp = set()
        remaining.discard(seed)
        while stack:
            x, z = stack.pop()
            comp.add((x, z))
            for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, z + dz)
                if n in remaining:
                    remaining.discard(n)
                    stack.append(n)
        if len(comp) > len(best):
            best = comp
    return best


def _erode(cells, k):
    """Remove the outer `k` rings of cells (morphological erosion). Stops
    before emptying so a setback never shrinks to nothing."""
    cur = set(cells)
    for _ in range(max(0, k)):
        if not cur:
            break
        peri = {(x, z) for (x, z) in cur
                if any((x + dx, z + dz) not in cur
                       for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)))}
        nxt = cur - peri
        if len(nxt) < _MIN_ARM * _MIN_ARM:
            break
        cur = nxt
    return cur


def _apply_progression(cells, progression, floor_index, n_floors, bbox):
    """Vary the footprint per floor in a COHERENT way (upper ⊆ lower, always
    supported — no floating walls). floor 0 is always the full base shape."""
    p = (progression or "uniform").lower()
    if p in ("", "uniform") or floor_index <= 0 or not cells:
        return cells
    if p in ("setback", "taper", "ziggurat", "stepped"):
        # Inset one ring every TWO floors so towers read as slender vertical
        # shafts with a gentle batter, not an aggressive wedding-cake.
        return _erode(cells, floor_index // 2)
    if p in ("base_to_tower", "base-to-tower", "tower_on_base"):
        # upper floors = a centred core (~60%) sitting on the wider base
        bx0, bz0, bx1, bz1 = bbox
        W, D = bx1 - bx0, bz1 - bz0
        ix, iz = max(_MIN_ARM, int(W * 0.6)), max(_MIN_ARM, int(D * 0.6))
        cx, cz = bx0 + W // 2, bz0 + D // 2
        x0, z0 = cx - ix // 2, cz - iz // 2
        core = {(x, z) for x in range(x0, x0 + ix) for z in range(z0, z0 + iz)}
        return core & set(cells)
    return cells


def footprint_for(silhouette_id, building_aabb, floor_index=0, n_floors=1,
                  footprint_shape=None, params=None) -> Footprint:
    """Build the footprint mask for one floor. Always returns a non-empty,
    connected Footprint; falls back to the full rectangle for unknown shapes,
    too-small footprints, or any degenerate result."""
    bx0, _, bz0, bx1, _, bz1 = (list(building_aabb) + [0] * 6)[:6]
    bx0, bz0, bx1, bz1 = int(bx0), int(bz0), int(bx1), int(bz1)
    W, D = bx1 - bx0, bz1 - bz0
    rect = _full(bx0, bz0, bx1, bz1)
    if W <= 0 or D <= 0:
        return Footprint(frozenset(rect), (bx0, bz0, bx1, bz1), "rectangle")

    key = _normalize_shape(footprint_shape)
    # Shaped footprints need a minimum size; otherwise a plain rectangle.
    if key != "rectangle" and min(W, D) < _MIN_SIDE_FOR_SHAPE:
        key = "rectangle"

    builder = _SHAPE_BUILDERS.get(key, _mask_rectangle)
    try:
        cells = builder(bx0, bz0, bx1, bz1, params=params or {},
                        floor_index=floor_index, n_floors=n_floors)
    except Exception:
        cells = rect
    cells = _largest_component(cells)
    # Degenerate guard: a shape that collapsed to <50% of a thin rect or empty
    # → fall back to rectangle (never ship a broken footprint).
    if not cells or len(cells) < max(_MIN_ARM * _MIN_ARM, len(rect) // 8):
        cells, key = rect, "rectangle"
    # Per-floor progression (setback / base_to_tower / …). uniform → no-op.
    progression = (params or {}).get("floor_progression")
    if progression and floor_index > 0:
        prog = _apply_progression(cells, progression, floor_index, n_floors,
                                  (bx0, bz0, bx1, bz1))
        prog = _largest_component(prog)
        if prog:                          # never let a progression empty it
            cells = prog
    return Footprint(frozenset(cells), (bx0, bz0, bx1, bz1), key)
