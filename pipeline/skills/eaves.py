"""Curved upturned-eave + multi-tier pagoda rasteriser (East-Asian roofs).

Single source of truth for the iconic flying-eave geometry, shared by the
skill modules (which wrap the output in `Op` objects) and `pipeline/agents/
roofs.py` (which wraps it in dict-ops). Every function is pure and returns a
list of ``(x, y, z, role)`` tuples where ``role`` is any string accepted by
``base._resolve`` — a ``@role`` placeholder (optionally with a blockstate
suffix like ``@stairs[facing=north]``) or a literal ``minecraft:`` block id.

Coordinate convention matches the rest of the library: x=width, z=depth,
y=up. Rect bounds passed here are **inclusive** integer corners
``(x0,z0)..(x1,z1)`` and ``y`` is the eave base level. All loops are bounded.
"""
from __future__ import annotations

Tup = tuple[int, int, int, str]


def _clamp_rect(x0: int, z0: int, x1: int, z1: int):
    if x1 < x0:
        x0, x1 = x1, x0
    if z1 < z0:
        z0, z1 = z1, z0
    return x0, z0, x1, z1


def eave_shelf(x0: int, z0: int, x1: int, z1: int, y: int, overhang: int,
               role: str = "@roof") -> list[Tup]:
    """Solid eave plate at height `y` covering the rect plus `overhang` cells
    beyond it on every side (the lowest, widest roof course)."""
    x0, z0, x1, z1 = _clamp_rect(x0, z0, x1, z1)
    o = max(0, overhang)
    out: list[Tup] = []
    for x in range(x0 - o, x1 + o + 1):
        for z in range(z0 - o, z1 + o + 1):
            out.append((x, y, z, role))
    return out


def eave_upturn(x0: int, z0: int, x1: int, z1: int, y: int, overhang: int,
                flare: float, roof_role: str = "@roof", accent_role: str = "@accent",
                stairs_role: str = "@stairs") -> list[Tup]:
    """The flying-eave detail: an inward-facing fascia lip around the eave edge
    plus an upturned horn climbing at each corner, capped with an accent finial."""
    x0, z0, x1, z1 = _clamp_rect(x0, z0, x1, z1)
    o = max(0, overhang)
    ex0, ez0, ex1, ez1 = x0 - o, z0 - o, x1 + o, z1 + o
    out: list[Tup] = []

    # Fascia lip: stairs along each outer edge, sloping inward (decorative tile edge).
    for x in range(ex0, ex1 + 1):
        out.append((x, y + 1, ez0, f"{stairs_role}[facing=south]"))   # north edge
        out.append((x, y + 1, ez1, f"{stairs_role}[facing=north]"))   # south edge
    for z in range(ez0, ez1 + 1):
        out.append((ex0, y + 1, z, f"{stairs_role}[facing=east]"))    # west edge
        out.append((ex1, y + 1, z, f"{stairs_role}[facing=west]"))    # east edge

    # Corner horns: climb up at each of the four expanded corners.
    horn = max(1, round(flare * (o + 1)))
    horn = min(horn, 4)
    corners = [(ex0, ez0), (ex1, ez0), (ex0, ez1), (ex1, ez1)]
    for (cx, cz) in corners:
        for k in range(1, horn + 1):
            role = accent_role if k == horn else roof_role
            out.append((cx, y + 1 + k, cz, role))
    return out


def hip_body(x0: int, z0: int, x1: int, z1: int, y: int, rise: int = 1,
             role: str = "@roof", max_layers: int = 24) -> list[Tup]:
    """Stepped hip roof body: solid plates shrinking inward one cell per side
    each layer (watertight, connected), rising `rise` blocks per layer, until it
    closes to a ridge/peak."""
    x0, z0, x1, z1 = _clamp_rect(x0, z0, x1, z1)
    rise = max(1, rise)
    out: list[Tup] = []
    cy = y
    layers = 0
    while x0 <= x1 and z0 <= z1 and layers < max_layers:
        for x in range(x0, x1 + 1):
            for z in range(z0, z1 + 1):
                out.append((x, cy, z, role))
        # shrink the shorter pair faster so a long rectangle resolves to a ridge
        if (x1 - x0) >= (z1 - z0):
            x0 += 1
            x1 -= 1
        else:
            z0 += 1
            z1 -= 1
        # also pull the other axis in slightly to keep the cone closing
        if x0 <= x1 and (x1 - x0) > (z1 - z0) + 1:
            pass
        cy += rise
        layers += 1
    return out


def finial(cx: int, cz: int, y: int, height: int, accent_role: str = "@accent") -> list[Tup]:
    """Vertical accent mast topped with an orb — the pagoda spire (sōrin)."""
    height = max(1, min(height, 12))
    out: list[Tup] = [(cx, y + k, cz, accent_role) for k in range(height)]
    return out


def asian_hip(x0: int, z0: int, x1: int, z1: int, y: int, *, flare: float = 1.0,
              rise: int = 1, overhang: int | None = None,
              roof_role: str = "@roof", accent_role: str = "@accent",
              stairs_role: str = "@stairs") -> list[Tup]:
    """A single East-Asian hip roof: deep eave shelf + flying-eave upturn + hip body."""
    x0, z0, x1, z1 = _clamp_rect(x0, z0, x1, z1)
    w, d = x1 - x0 + 1, z1 - z0 + 1
    if overhang is None:
        overhang = max(1, min(3, min(w, d) // 4))
    out: list[Tup] = []
    out += eave_shelf(x0, z0, x1, z1, y, overhang, roof_role)
    out += eave_upturn(x0, z0, x1, z1, y, overhang, flare, roof_role, accent_role, stairs_role)
    out += hip_body(x0, z0, x1, z1, y + 1, rise, roof_role)
    return out


def pagoda(x0: int, z0: int, x1: int, z1: int, y: int, *, tiers: int = 3,
           flare: float = 1.0, roof_role: str = "@roof", accent_role: str = "@accent",
           wall_role: str = "@primary", stairs_role: str = "@stairs") -> list[Tup]:
    """Multi-tier pagoda: stacked upturned-eave tiers, each over a smaller
    footprint, separated by a short wall drum, topped with a finial."""
    x0, z0, x1, z1 = _clamp_rect(x0, z0, x1, z1)
    tiers = max(1, min(tiers, 6))
    w, d = x1 - x0 + 1, z1 - z0 + 1
    inset = max(1, min(w, d) // (tiers + 2))
    drum = 2  # wall band height between tiers
    out: list[Tup] = []
    cy = y
    cx0, cz0, cx1, cz1 = x0, z0, x1, z1
    for t in range(tiers):
        last = (t == tiers - 1)
        cw, cd = cx1 - cx0 + 1, cz1 - cz0 + 1
        if cw < 3 or cd < 3:
            last = True
        oh = max(1, min(2, min(cw, cd) // 4))
        out += eave_shelf(cx0, cz0, cx1, cz1, cy, oh, roof_role)
        out += eave_upturn(cx0, cz0, cx1, cz1, cy, oh, flare, roof_role, accent_role, stairs_role)
        if last:
            out += hip_body(cx0, cz0, cx1, cz1, cy + 1, 1, roof_role)
            ccx = (cx0 + cx1) // 2
            ccz = (cz0 + cz1) // 2
            peak = cy + 1 + max(cw, cd) // 2
            out += finial(ccx, ccz, peak, 3, accent_role)
            break
        # wall drum up to the next tier, over the inset footprint
        nx0, nz0, nx1, nz1 = cx0 + inset, cz0 + inset, cx1 - inset, cz1 - inset
        if nx1 < nx0 or nz1 < nz0:
            out += hip_body(cx0, cz0, cx1, cz1, cy + 1, 1, roof_role)
            break
        for x in range(nx0, nx1 + 1):
            for z in range(nz0, nz1 + 1):
                on_wall = x in (nx0, nx1) or z in (nz0, nz1)
                if on_wall:
                    for h in range(1, drum + 1):
                        out.append((x, cy + h, z, wall_role))
        cy += drum + 1
        cx0, cz0, cx1, cz1 = nx0, nz0, nx1, nz1
    return out
