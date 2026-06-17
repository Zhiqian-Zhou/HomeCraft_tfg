"""Roof library — genuinely distinct, modular, composable roof geometry.

Two layers:

  1. BASE roofs (~20 distinct silhouettes): gable family, hip/pyramid family,
     mansard/gambrel, curved (cone / spire / helm / dome / onion), pagoda,
     parapets, industrial (sawtooth / butterfly / skillion / barrel), flat.
     Each produces a *visibly* different shape — curved roofs use a true
     radius profile (dome = hemisphere, spire = tall needle, cone = medium
     point, onion = bulb + finial, helm = square pyramid + spike) and the hip
     family varies pitch and eave flare. (Before, cone≡helm, spire≡dome and
     the whole hip family collapsed to one stepped pyramid.)

  2. MODULAR add-ons — the "LEGO" layer. Reusable pieces (dormer, chimney,
     cupola, finial, ridge_cresting, corner_turret) that `compose_roof()`
     snaps onto a base roof, so roofs / towers / parts are freely combinable.

Ops are rect / place dicts with envelope_role="roof" (add-ons also carry
"roof_feature"). Pure stdlib; imported by architecture_planner. Roofs RISE
above the walls (a roof may exceed building_aabb.y1 — the voxelizer extends
the bbox). hip is the safe fallback for an unknown base style.
"""
from __future__ import annotations

import math
import sys

from pipeline.skills import eaves as _eaves

MAX_PITCH = 12
MAX_OPS = 8000  # raised from 1400 — East-Asian flying-eave roofs over palace-
                # sized footprints (~22×22) emit ~4700 ops; 8000 leaves headroom
                # for a 30×30 palace. Cap voxel impact is bounded by the building
                # footprint area, so this stays small in the final voxel list.


# ── op helpers ───────────────────────────────────────────────────────────────

def _rect(level, x0, z0, x1, z1, block, role="roof"):
    return {"kind": "rect", "envelope_role": role, "room_id": None,
            "axis": "y", "level": level,
            "aabb": [x0, level, z0, x1, level + 1, z1], "block": block}


def _place(x, y, z, block, role="roof"):
    return {"kind": "place", "envelope_role": role, "room_id": None,
            "at": [x, y, z], "block": block}


def _eave_op(x, y, z, role, block, stair, accent, env="roof"):
    """Map an `eaves` role tuple to a concrete `_place` dict-op for roofs.py."""
    if role.startswith("@stairs"):
        suffix = role[role.find("["):] if "[" in role else ""
        b = (stair + suffix) if stair else block
    elif role.startswith("@accent"):
        b = accent or block
    else:  # @roof, @primary, anything else
        b = block
    return _place(x, y, z, b, env)


def _eave_ops(tuples, block, stair, accent):
    return [_eave_op(x, y, z, role, block, stair, accent)
            for (x, y, z, role) in tuples]


def _col(x, y0, y1, z, block, role="roof"):
    return {"kind": "fill", "envelope_role": role, "room_id": None,
            "aabb": [x, y0, z, x + 1, y1, z + 1], "block": block}


def _pitch(W, D, mult=1.0):
    return max(2, min(int((min(W, D) / 2) * mult), MAX_PITCH))


def _ctr(bx0, bz0, bx1, bz1):
    return (bx0 + bx1) / 2.0, (bz0 + bz1) / 2.0


# ── shared filled-disk rasteriser (for every curved roof) ────────────────────

def _disk_rects(level, cx, cz, r, block):
    """One layer of a solid circle of radius r centred at (cx, cz), emitted as
    one rect per Z-row (cheap, exact). r < 0.5 → a single apex column."""
    if r < 0.5:
        return [_place(int(round(cx - 0.5)), level, int(round(cz - 0.5)), block)]
    out = []
    zlo, zhi = int(math.floor(cz - r)), int(math.ceil(cz + r))
    for z in range(zlo, zhi):
        dz = (z + 0.5) - cz
        if abs(dz) > r:
            continue
        half = math.sqrt(max(0.0, r * r - dz * dz))
        x0, x1 = int(math.floor(cx - half)), int(math.ceil(cx + half))
        if x1 > x0:
            out.append(_rect(level, x0, z, x1, z + 1, block))
    return out


def _curved(bx0, bz0, bx1, bz1, wt, block, *, mode):
    """Curved roofs sharing one radius-profile rasteriser. `mode` sets the
    profile so each is a distinct silhouette:

      cone     medium point, straight taper          H ≈ 1.5 r
      spire    tall thin needle                       H ≈ 2.4 r
      dome     true rounded hemisphere                H ≈ r
      onion    bulb (overshoots r) + neck + finial    H ≈ 1.6 r
    """
    W, D = bx1 - bx0, bz1 - bz0
    r = max(W, D) / 2.0
    cx, cz = (bx0 + bx1) / 2.0, (bz0 + bz1) / 2.0
    if mode in ("spire", "needle"):
        H = int(min(max(round(2.4 * r) + 2, 7), 24))
        prof = lambda f: r * (1.0 - f)
    elif mode in ("dome", "stepped-dome"):
        H = int(min(max(round(r) + 1, 3), 14))
        prof = lambda f: r * math.sqrt(max(0.0, 1.0 - f * f))
    elif mode in ("onion", "onion-dome"):
        H = int(min(max(round(1.6 * r) + 2, 6), 18))
        # bulge past r in the lower third, pinch to a neck, then a spike
        def prof(f):
            if f < 0.55:
                return r * (1.0 + 0.28 * math.sin(f / 0.55 * math.pi))
            g = (f - 0.55) / 0.45
            return max(0.0, r * 0.9 * (1.0 - g))
    else:                                            # cone / conical
        H = int(min(max(round(1.5 * r) + 1, 5), 18))
        prof = lambda f: r * (1.0 - f)
    ops = []
    for k in range(H + 1):
        f = k / float(H) if H else 1.0
        ops += _disk_rects(wt + k, cx, cz, prof(f), block)
    if mode in ("onion", "onion-dome"):              # finial spike
        for s in range(1, 4):
            ops.append(_place(int(round(cx - 0.5)), wt + H + s,
                              int(round(cz - 0.5)), block))
    return ops or [_rect(wt, bx0, bz0, bx1, bz1, block)]


# ── gable family ─────────────────────────────────────────────────────────────

def gable(bx0, bz0, bx1, bz1, wt, by1, block, stair, *, mult=1.0,
          orient="auto", clipped=False, asym=False, **_):
    W, D = bx1 - bx0, bz1 - bz0
    along_x = (W >= D) if orient == "auto" else (orient == "x")
    ops = []
    if along_x:                                   # ridge ‖ X, slopes in Z
        half = _pitch(W, D, mult)
        for i in range(half):
            y = wt + i
            inset = i
            if clipped and i >= half - 2:          # jerkinhead: clip the top
                inset = max(0, half - 2)
            x0, x1 = (bx0 + i, bx1) if asym else (bx0, bx1)  # saltbox shifts
            ops.append(_rect(y, x0, bz0 + inset, x1, bz0 + inset + 1,
                             f"{stair}[facing=south]"))
            ops.append(_rect(y, x0, bz1 - inset - 1, x1, bz1 - inset,
                             f"{stair}[facing=north]"))
        ops.append(_rect(wt + half, bx0, bz0 + half, bx1, bz1 - half, block))
    else:
        half = _pitch(W, D, mult)
        for i in range(half):
            y = wt + i
            ops.append(_rect(y, bx0 + i, bz0, bx0 + i + 1, bz1,
                             f"{stair}[facing=east]"))
            ops.append(_rect(y, bx1 - i - 1, bz0, bx1 - i, bz1,
                             f"{stair}[facing=west]"))
        ops.append(_rect(wt + half, bx0 + half, bz0, bx1 - half, bz1, block))
    return ops


def cross_gable(bx0, bz0, bx1, bz1, wt, by1, block, stair, **_):
    a = gable(bx0, bz0, bx1, bz1, wt, by1, block, stair, orient="x")
    b = gable(bx0, bz0, bx1, bz1, wt, by1, block, stair, orient="z")
    return a + b


# ── hip / pyramid family (differentiated by pitch + eave flare + finial) ─────

def _hip_core(bx0, bz0, bx1, bz1, wt, block, *, rise=1, max_h=22):
    """Stepped hip/pyramid. `rise` = number of Y layers stacked per 1-cell
    inset, so larger rise → taller, steeper roof for the same footprint.
    Returns (ops, apex_y)."""
    ops, y, inset = [], wt, 0
    while (y - wt) <= max_h:
        x0, z0, x1, z1 = bx0 + inset, bz0 + inset, bx1 - inset, bz1 - inset
        if x0 >= x1 or z0 >= z1:
            break
        for _r in range(rise):
            ops.append(_rect(y, x0, z0, x1, z1, block))
            y += 1
        inset += 1
    if not ops:
        return [_rect(wt, bx0, bz0, bx1, bz1, block)], wt
    return ops, y - 1


def hip(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, *, rise=1, **_):
    ops, _ = _hip_core(bx0, bz0, bx1, bz1, wt, block, rise=rise)
    return ops


def pavilion(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    # hip with a flared overhanging eave at the base (1-cell skirt)
    eave = [_rect(wt, bx0 - 1, bz0 - 1, bx1 + 1, bz1 + 1, block)]
    ops, _ = _hip_core(bx0, bz0, bx1, bz1, wt + 1, block, rise=1)
    return eave + ops


def pyramidal(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    # moderate 4-sided pyramid that always closes to a single apex point
    ops, top = _hip_core(bx0, bz0, bx1, bz1, wt, block, rise=1)
    cx, cz = (bx0 + bx1) // 2, (bz0 + bz1) // 2
    ops.append(_place(cx, top + 1, cz, block))       # crown the apex
    return ops


def tented(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    # very steep, tall tent peak (3 layers per inset)
    ops, _ = _hip_core(bx0, bz0, bx1, bz1, wt, block, rise=3)
    return ops


def helm(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    # Rhenish helm: a steep SQUARE pyramid (distinct from the round cone)
    # capped by a finial spike — reads as four gabled faces meeting at a point.
    ops, top = _hip_core(bx0, bz0, bx1, bz1, wt, block, rise=2)
    cx, cz = (bx0 + bx1) // 2, (bz0 + bz1) // 2
    for s in range(1, 4):                            # finial spike
        ops.append(_place(cx, top + s, cz, block))
    return ops


# ── double-pitch (mansard / gambrel) ─────────────────────────────────────────

def mansard(bx0, bz0, bx1, bz1, wt, by1, block, stair, **_):
    W, D = bx1 - bx0, bz1 - bz0
    steep = max(2, min(W, D) // 3)
    ops = []
    for i in range(steep):                         # steep lower skirt
        y, ins = wt + i, max(1, i // 2)
        ops.append(_rect(y, bx0 + ins, bz0 + ins, bx1 - ins, bz0 + ins + 1,
                         f"{stair}[facing=south]"))
        ops.append(_rect(y, bx0 + ins, bz1 - ins - 1, bx1 - ins, bz1 - ins,
                         f"{stair}[facing=north]"))
        ops.append(_rect(y, bx0 + ins, bz0 + ins, bx0 + ins + 1, bz1 - ins,
                         f"{stair}[facing=east]"))
        ops.append(_rect(y, bx1 - ins - 1, bz0 + ins, bx1 - ins, bz1 - ins,
                         f"{stair}[facing=west]"))
    cap = wt + steep
    ins = max(1, steep // 2)
    ops.append(_rect(cap, bx0 + ins, bz0 + ins, bx1 - ins, bz1 - ins, block))
    return ops


def gambrel(bx0, bz0, bx1, bz1, wt, by1, block, stair, **_):
    # barn roof: steep lower slope then shallow upper, ridge ‖ long axis
    W, D = bx1 - bx0, bz1 - bz0
    along_x = W >= D
    ops = []
    span = (D if along_x else W)
    lower = max(1, span // 4)
    for i in range(lower):                         # steep part
        y = wt + i
        if along_x:
            ops.append(_rect(y, bx0, bz0 + i, bx1, bz0 + i + 1, f"{stair}[facing=south]"))
            ops.append(_rect(y, bx0, bz1 - i - 1, bx1, bz1 - i, f"{stair}[facing=north]"))
        else:
            ops.append(_rect(y, bx0 + i, bz0, bx0 + i + 1, bz1, f"{stair}[facing=east]"))
            ops.append(_rect(y, bx1 - i - 1, bz0, bx1 - i, bz1, f"{stair}[facing=west]"))
    top = _pitch(W, D, 0.6)
    for j in range(top):                           # shallow part
        y = wt + lower + j
        ins = lower + j * 2
        if along_x:
            if bz0 + ins >= bz1 - ins:
                break
            ops.append(_rect(y, bx0, bz0 + ins, bx1, bz0 + ins + 1, f"{stair}[facing=south]"))
            ops.append(_rect(y, bx0, bz1 - ins - 1, bx1, bz1 - ins, f"{stair}[facing=north]"))
        else:
            if bx0 + ins >= bx1 - ins:
                break
            ops.append(_rect(y, bx0 + ins, bz0, bx0 + ins + 1, bz1, f"{stair}[facing=east]"))
            ops.append(_rect(y, bx1 - ins - 1, bz0, bx1 - ins, bz1, f"{stair}[facing=west]"))
    return ops


def half_hip(bx0, bz0, bx1, bz1, wt, by1, block, stair, **_):
    # gable that turns into a small hip at the ridge ends
    return gable(bx0, bz0, bx1, bz1, wt, by1, block, stair, clipped=True)


# ── curved wrappers (all share _curved) ──────────────────────────────────────

def cone(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    return _curved(bx0, bz0, bx1, bz1, wt, block, mode="cone")


def spire(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    return _curved(bx0, bz0, bx1, bz1, wt, block, mode="spire")


def dome(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    return _curved(bx0, bz0, bx1, bz1, wt, block, mode="dome")


def onion(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    return _curved(bx0, bz0, bx1, bz1, wt, block, mode="onion")


# ── tiered (pagoda) — uses shared eaves rasteriser for upturned tiers ────────

def pagoda(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, *,
           floors=None, tiers=3, accent=None, flare=1.0, **_):
    """Multi-tier pagoda with curved flying eaves and a finial sōrin spire."""
    tups = _eaves.pagoda(bx0, bz0, bx1 - 1, bz1 - 1, wt,
                         tiers=tiers, flare=flare)
    return _eave_ops(tups, block, stair, accent)


# ── East-Asian hip with curved flying eaves ──────────────────────────────────

def asian_hip_roof(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, *,
                   accent=None, flare=1.0, rise=1, **_):
    """Single-tier upturned-eave hip roof (palace / temple silhouette)."""
    tups = _eaves.asian_hip(bx0, bz0, bx1 - 1, bz1 - 1, wt,
                            flare=flare, rise=rise)
    return _eave_ops(tups, block, stair, accent)


# ── flat-with-relief (not a plain rectangle slab) ────────────────────────────

def crenellated(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    ops = [_rect(wt, bx0, bz0, bx1, bz1, block)]
    for x in range(bx0, bx1):
        for z in range(bz0, bz1):
            on_edge = x in (bx0, bx1 - 1) or z in (bz0, bz1 - 1)
            if on_edge and (x + z) % 2 == 0:
                ops.append(_place(x, wt + 1, z, block))
    return ops


def stepped_parapet(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    ops, y, inset = [], wt, 0
    while (y - wt) <= 4:
        x0, z0, x1, z1 = bx0 + inset, bz0 + inset, bx1 - inset, bz1 - inset
        if x0 >= x1 or z0 >= z1:
            break
        ops.append(_rect(y, x0, z0, x1, z1, block))
        y += 1
        inset += 2
    return ops or [_rect(wt, bx0, bz0, bx1, bz1, block)]


def sawtooth(bx0, bz0, bx1, bz1, wt, by1, block, stair, **_):
    ops = []
    z = bz0
    while z + 3 <= bz1:
        for i in range(3):
            ops.append(_rect(wt + i, bx0, z + i, bx1, z + i + 1,
                             f"{stair}[facing=north]"))
        z += 3
    return ops or [_rect(wt, bx0, bz0, bx1, bz1, block)]


def butterfly(bx0, bz0, bx1, bz1, wt, by1, block, stair, **_):
    W, D = bx1 - bx0, bz1 - bz0
    h = _pitch(W, D, 0.7)
    ops = []
    for i in range(h):                              # rises toward both edges
        y = wt + i
        ops.append(_rect(y, bx0, bz0 + (h - 1 - i), bx1, bz0 + (h - i),
                         f"{stair}[facing=north]"))
        ops.append(_rect(y, bx0, bz1 - (h - i), bx1, bz1 - (h - 1 - i),
                         f"{stair}[facing=south]"))
    ops.append(_rect(wt, bx0, bz0 + h, bx1, bz1 - h, block))   # valley floor
    return ops


def clerestory(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    ops = [_rect(wt, bx0, bz0, bx1, bz1, block)]
    cx0, cz0 = bx0 + (bx1 - bx0) // 3, bz0 + (bz1 - bz0) // 3
    cx1, cz1 = bx1 - (bx1 - bx0) // 3, bz1 - (bz1 - bz0) // 3
    if cx0 < cx1 and cz0 < cz1:
        ops.append(_rect(wt + 2, cx0, cz0, cx1, cz1, block))    # raised monitor
    return ops


def skillion(bx0, bz0, bx1, bz1, wt, by1, block, stair, **_):
    W, D = bx1 - bx0, bz1 - bz0
    h = _pitch(W, D, 0.7)
    ops = []
    for i in range(D):                              # single slope along Z
        y = wt + min(i * h // max(1, D), h)
        ops.append(_rect(y, bx0, bz0 + i, bx1, bz0 + i + 1, f"{stair}[facing=south]"))
    return ops


def barrel(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    # half-cylinder vault along the long axis (rings narrowing in the short axis)
    W, D = bx1 - bx0, bz1 - bz0
    along_x = W >= D
    short = D if along_x else W
    h = max(2, short // 2)
    ops = []
    for i in range(h):
        ins = i
        y = wt + i
        if along_x:
            if bz0 + ins >= bz1 - ins:
                break
            ops.append(_rect(y, bx0, bz0 + ins, bx1, bz1 - ins, block))
        else:
            if bx0 + ins >= bx1 - ins:
                break
            ops.append(_rect(y, bx0 + ins, bz0, bx1 - ins, bz1, block))
    return ops


def flat(bx0, bz0, bx1, bz1, wt, by1, block, stair=None, **_):
    return [_rect(wt, bx0, bz0, bx1, bz1, block)]


# ── registry: named style → (builder, kwargs) ────────────────────────────────

ROOF_STYLES = {
    # gable family
    "gable": (gable, {}),
    "thatched": (gable, {"mult": 1.3}),       # steep gable (legacy enum alias)
    "gable-steep": (gable, {"mult": 1.6}),
    "gable-shallow": (gable, {"mult": 0.6}),
    "front-gable": (gable, {"orient": "z"}),
    "side-gable": (gable, {"orient": "x"}),
    "saltbox": (gable, {"asym": True}),
    "jerkinhead": (gable, {"clipped": True}),
    "half-hip": (half_hip, {}),
    "cross-gable": (cross_gable, {}),
    "dutch-gable": (gable, {"mult": 1.2, "clipped": True}),
    "a-frame": (gable, {"mult": 1.8}),
    # hip / pyramid family — now genuinely different shapes
    "hip": (hip, {}),
    "hip-steep": (hip, {"rise": 2}),
    "pyramidal": (pyramidal, {}),
    "pyramid": (pyramidal, {}),               # legacy enum alias
    "tented": (tented, {}),
    "pavilion": (pavilion, {}),
    # double pitch
    "mansard": (mansard, {}),
    "gambrel": (gambrel, {}),
    "barn": (gambrel, {}),
    # curved / pointed — distinct radius profiles
    "conical": (cone, {}),
    "cone": (cone, {}),
    "spire": (spire, {}),
    "needle": (spire, {}),
    "helm": (helm, {}),
    "rhenish-helm": (helm, {}),
    "dome": (dome, {}),
    "stepped-dome": (dome, {}),
    "onion": (onion, {}),
    "onion-dome": (onion, {}),
    # tiered
    "pagoda": (pagoda, {}),
    "double-pagoda": (pagoda, {"tiers": 4}),
    "tiered": (pagoda, {}),
    # East-Asian curved-eave family (chinese / japanese palaces & temples)
    "chinese-pagoda": (pagoda, {"tiers": 4}),
    "chinese-hip": (asian_hip_roof, {}),
    "temple": (asian_hip_roof, {"flare": 1.2}),
    "upturned-eave": (asian_hip_roof, {}),
    "upturned": (asian_hip_roof, {}),
    "irimoya": (asian_hip_roof, {}),
    "asian": (asian_hip_roof, {}),
    "japanese-hip": (asian_hip_roof, {"flare": 0.8}),
    # flat-with-relief
    "crenellated": (crenellated, {}),
    "battlement": (crenellated, {}),
    "battlements": (crenellated, {}),
    "parapet": (crenellated, {}),
    "stepped-parapet": (stepped_parapet, {}),
    "ziggurat": (stepped_parapet, {}),
    "sawtooth": (sawtooth, {}),
    "north-light": (sawtooth, {}),
    "butterfly": (butterfly, {}),
    "clerestory": (clerestory, {}),
    "monitor": (clerestory, {}),
    "skillion": (skillion, {}),
    "shed": (skillion, {}),
    "lean-to": (skillion, {}),
    "barrel": (barrel, {}),
    "barrel-vault": (barrel, {}),
    "flat": (flat, {}),
}
NON_FLAT_STYLES = [k for k in ROOF_STYLES if k != "flat"]

# Curved styles want a round/centred footprint to look right (towers).
ROUNDED_ROOFS = {"conical", "cone", "spire", "needle", "helm", "rhenish-helm",
                 "dome", "stepped-dome", "onion", "onion-dome", "pyramidal",
                 "pyramid", "tented"}


def build_roof(style, *, bx0, bz0, bx1, bz1, wall_top, by1, block, stair,
               floors=None, accent=None):
    """Dispatch to a base roof builder.

    NO deterministic style substitution: an unknown roof style returns NO roof
    ops (logged) instead of silently defaulting to a hip roof, so the roof
    metrics reflect the LLM's (unsupported) choice rather than a fixed fallback.
    """
    key = (style or "").lower()
    if key not in ROOF_STYLES:
        print(f"[roofs] unknown roof style {style!r} — emitting NO roof "
              f"(no deterministic hip fallback).", file=sys.stderr)
        return []
    fn, kw = ROOF_STYLES[key]
    kw = dict(kw)
    if fn is pagoda:
        kw.setdefault("floors", floors)
    if fn in (pagoda, asian_hip_roof):
        kw.setdefault("accent", accent)
    ops = fn(bx0, bz0, bx1, bz1, wall_top, by1, block, stair, **kw)
    if len(ops) > MAX_OPS:
        # Resource guard (not an LLM-decision fallback): a >MAX_OPS roof is
        # degenerate. Collapse to a flat cap and log so it is never silent.
        print(f"[roofs] roof style {key!r} produced {len(ops)} ops (>{MAX_OPS}) "
              f"— collapsing to flat cap.", file=sys.stderr)
        ops = [_rect(wall_top, bx0, bz0, bx1, bz1, block)]
    return ops


# ══ MODULAR ADD-ONS ("LEGO" pieces) ══════════════════════════════════════════
# Each returns roof ops carrying roof_feature=<id>. They are *additive*: snapped
# onto a base roof by compose_roof so roofs / towers / parts combine freely.

def _roof_apex_height(bx0, bz0, bx1, bz1, wall_top):
    """Rough apex height a hip/cone would reach — used to seat finials/cupolas."""
    return wall_top + max(2, min(bx1 - bx0, bz1 - bz0) // 2)


def dormer(bx0, bz0, bx1, bz1, wall_top, by1, block, stair, accent=None, **_):
    """Small gabled dormers poking out of the long slope, with a glass window."""
    accent = "minecraft:glass_pane"                  # windows are always glass
    W, D = bx1 - bx0, bz1 - bz0
    along_x = W >= D
    ops = []
    span = W if along_x else D
    n = max(1, min(3, span // 6))
    for k in range(n):
        if along_x:
            cx = bx0 + int((k + 1) * W / (n + 1))
            for side, z in ((1, bz0 + 1), (-1, bz1 - 2)):       # both slopes
                ox0, ox1 = cx - 1, cx + 2
                ops.append(_col(ox0, wall_top + 1, wall_top + 3, z, block, "roof_feature"))
                ops.append(_col(ox1 - 1, wall_top + 1, wall_top + 3, z, block, "roof_feature"))
                ops.append(_place(cx, wall_top + 1, z, accent, "roof_feature"))
                ops.append(_rect(wall_top + 3, ox0, z, ox1, z + 1, block, "roof_feature"))
        else:
            cz = bz0 + int((k + 1) * D / (n + 1))
            for side, x in ((1, bx0 + 1), (-1, bx1 - 2)):
                oz0, oz1 = cz - 1, cz + 2
                ops.append(_col(x, wall_top + 1, wall_top + 3, oz0, block, "roof_feature"))
                ops.append(_col(x, wall_top + 1, wall_top + 3, oz1 - 1, block, "roof_feature"))
                ops.append(_place(x, wall_top + 1, cz, accent, "roof_feature"))
                ops.append(_rect(wall_top + 3, x, oz0, x + 1, oz1, block, "roof_feature"))
    return ops


def chimney(bx0, bz0, bx1, bz1, wall_top, by1, block, stair, accent=None, **_):
    """A masonry chimney at a corner, rising a few blocks above the ridge."""
    accent = accent or "minecraft:bricks"
    apex = _roof_apex_height(bx0, bz0, bx1, bz1, wall_top)
    cx, cz = bx0 + 1, bz0 + 1                          # near-corner
    top = apex + 2
    ops = [_col(cx, wall_top, top, cz, accent, "roof_feature")]
    # a 2x2 cap lip
    ops.append(_rect(top, cx, cz, cx + 1, cz + 1, accent, "roof_feature"))
    return ops


def cupola(bx0, bz0, bx1, bz1, wall_top, by1, block, stair, accent=None, **_):
    """A small lantern/cupola seated on the apex: 4 corner posts, a clear
    band (glass windows) and a tiny domed cap."""
    accent = "minecraft:glass_pane"                  # windows are always glass
    apex = _roof_apex_height(bx0, bz0, bx1, bz1, wall_top)
    cx, cz = (bx0 + bx1) // 2, (bz0 + bz1) // 2
    s = 1                                              # half-size
    x0, z0, x1, z1 = cx - s, cz - s, cx + s + 1, cz + s + 1
    base = apex
    ops = []
    for (px, pz) in ((x0, z0), (x1 - 1, z0), (x0, z1 - 1), (x1 - 1, z1 - 1)):
        ops.append(_col(px, base, base + 3, pz, block, "roof_feature"))
    # window band
    for x in range(x0, x1):
        for z in range(z0, z1):
            if x in (x0, x1 - 1) or z in (z0, z1 - 1):
                ops.append(_place(x, base + 1, z, accent, "roof_feature"))
    # tiny cap
    ops += [_rect(base + 3, x0, z0, x1, z1, block, "roof_feature")]
    ops += [_place(cx, base + 4, cz, block, "roof_feature")]
    return ops


def finial(bx0, bz0, bx1, bz1, wall_top, by1, block, stair, accent=None, **_):
    """A slender decorative spike at the apex (post + tip)."""
    accent = accent or block
    apex = _roof_apex_height(bx0, bz0, bx1, bz1, wall_top)
    cx, cz = (bx0 + bx1) // 2, (bz0 + bz1) // 2
    return [_col(cx, apex, apex + 4, cz, accent, "roof_feature")]


def ridge_cresting(bx0, bz0, bx1, bz1, wall_top, by1, block, stair, accent=None, **_):
    """A line of cresting (fence/wall) running along the ridge line."""
    accent = accent or block
    W, D = bx1 - bx0, bz1 - bz0
    along_x = W >= D
    ridge_h = wall_top + _pitch(W, D)
    ops = []
    if along_x:
        cz = (bz0 + bz1) // 2
        for x in range(bx0 + 1, bx1 - 1):
            ops.append(_place(x, ridge_h, cz, accent, "roof_feature"))
    else:
        cx = (bx0 + bx1) // 2
        for z in range(bz0 + 1, bz1 - 1):
            ops.append(_place(cx, ridge_h, z, accent, "roof_feature"))
    return ops


def corner_turret(bx0, bz0, bx1, bz1, wall_top, by1, block, stair, accent=None,
                  *, corners=4, radius=1, cap="conical", **_):
    """A mini-tower at each chosen corner: a short round column rising above the
    eave, capped by its OWN curved roof. This is the 'tower as a LEGO piece'
    — combinable with any base roof."""
    accent = accent or block
    h = max(3, (by1 - wall_top) + 2)
    pts = [(bx0, bz0), (bx1 - 1, bz0), (bx0, bz1 - 1), (bx1 - 1, bz1 - 1)]
    if corners == 2:
        pts = [pts[0], pts[3]]
    ops = []
    R = max(1, radius)
    for (px, pz) in pts[:corners]:
        cx = px + (R if px == bx0 else -R)
        cz = pz + (R if pz == bz0 else -R)
        # circular shaft
        top = wall_top + h
        for y in range(wall_top, top):
            ops += [{"kind": "fill", "envelope_role": "roof_feature",
                     "room_id": None,
                     "aabb": [cx - R, y, cz - R, cx + R + 1, y + 1, cz + R + 1],
                     "block": accent}]
        # its own little cap
        ops += [dict(o, envelope_role="roof_feature")
                for o in _curved(cx - R, cz - R, cx + R + 1, cz + R + 1,
                                 top, block, mode=cap)]
    return ops


_FEATURE_BUILDERS = {
    "dormer": dormer, "dormers": dormer,
    "chimney": chimney, "chimneys": chimney,
    "cupola": cupola, "lantern": cupola, "roof-lantern": cupola,
    "finial": finial, "spire-tip": finial, "weathervane": finial,
    "ridge-cresting": ridge_cresting, "cresting": ridge_cresting,
    "corner-turrets": corner_turret, "turrets": corner_turret,
    "corner-turret": corner_turret,
}
ROOF_FEATURES = sorted(set(_FEATURE_BUILDERS))


def compose_roof(base_style, *, bx0, bz0, bx1, bz1, wall_top, by1, block,
                 stair, accent=None, features=(), floors=None):
    """Snap a base roof together with modular add-ons (LEGO).

    base_style  one of ROOF_STYLES (the main roof shape)
    features    iterable of feature ids (ROOF_FEATURES) to add on top —
                e.g. ["dormer", "chimney", "cupola"] or ["corner-turrets"].
                Unknown ids are ignored.
    Returns a single op list (base + add-ons), budget-guarded.
    """
    ops = build_roof(base_style, bx0=bx0, bz0=bz0, bx1=bx1, bz1=bz1,
                     wall_top=wall_top, by1=by1, block=block, stair=stair,
                     floors=floors, accent=accent)
    seen = set()
    for f in (features or []):
        key = (f or "").strip().lower()
        if key in ("", "none") or key in seen:
            continue
        seen.add(key)
        fn = _FEATURE_BUILDERS.get(key)
        if fn is None:
            continue
        try:
            ops += fn(bx0, bz0, bx1, bz1, wall_top, by1, block, stair,
                      accent=accent)
        except Exception:                              # never let a feature kill the roof
            continue
        if len(ops) > MAX_OPS:
            break
    return ops
