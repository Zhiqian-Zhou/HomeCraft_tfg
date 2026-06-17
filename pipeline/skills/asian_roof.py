"""Skill: asian_roof — East-Asian roof with curved upturned (flying) eaves.

Parametric (kwargs):
  * variant ∈ {hip_upturn, pagoda, temple_double_eave, irimoya, gable_upturn}
  * tier_count (pagoda tiers, 1..6)
  * flare (0..1.5) — eave overhang / corner-upturn intensity
  * palette / color — @roof/@accent overrides (red-and-yellow palace by default
    when style is chinese/chinese_imperial)

Geometry is delegated to `pipeline.skills.eaves` so the same flying-eave maths is
shared with the whole-building roofs in `pipeline/agents/roofs.py`. The roof fills
the AABB footprint and rises from `aabb.y0`.

Coordinate convention (matches `base.py`): x=width, y=up, z=depth; AABB half-open.
"""
from __future__ import annotations

from typing import List

from . import eaves, params
from .base import AABB, Materials, Op, PlaceBlock

_VARIANTS = {"hip_upturn", "pagoda", "temple_double_eave", "irimoya", "gable_upturn"}


def _ops_from_tuples(tups, mats: Materials) -> List[Op]:
    return [PlaceBlock(x, y, z, params.resolve(role, mats)) for (x, y, z, role) in tups]


def _gable(x0, z0, x1, z1, y, role, ridge_role):
    """Simple gable: slopes rise from the two long edges toward a central ridge."""
    out = []
    w, d = x1 - x0 + 1, z1 - z0 + 1
    # ridge runs along the longer axis
    if w >= d:
        half = d // 2
        for k in range(half + 1):
            za, zb = z0 + k, z1 - k
            for x in range(x0, x1 + 1):
                out.append((x, y + k, za, role))
                out.append((x, y + k, zb, role))
        zr = (z0 + z1) // 2
        for x in range(x0, x1 + 1):
            out.append((x, y + half, zr, ridge_role))
    else:
        half = w // 2
        for k in range(half + 1):
            xa, xb = x0 + k, x1 - k
            for z in range(z0, z1 + 1):
                out.append((xa, y + k, z, role))
                out.append((xb, y + k, z, role))
        xr = (x0 + x1) // 2
        for z in range(z0, z1 + 1):
            out.append((xr, y + half, z, ridge_role))
    return out


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> List[Op]:
    variant = params.resolve_variant(kwargs, _VARIANTS, "hip_upturn")
    flare = params.resolve_flare(kwargs, 1.0)
    mats = params.with_overrides(materials, kwargs, style, rag_id="asian_roof")

    x0, z0 = aabb.x0, aabb.z0
    x1, z1 = aabb.x1 - 1, aabb.z1 - 1
    y = aabb.y0

    if variant == "pagoda":
        tiers = params.resolve_int(kwargs, "tier_count", 3, lo=1, hi=6)
        tups = eaves.pagoda(x0, z0, x1, z1, y, tiers=tiers, flare=flare)
        return _ops_from_tuples(tups, mats)

    if variant == "gable_upturn":
        oh = max(1, min(3, min(x1 - x0 + 1, z1 - z0 + 1) // 4))
        tups = eaves.eave_shelf(x0, z0, x1, z1, y, oh, "@roof")
        tups += eaves.eave_upturn(x0, z0, x1, z1, y, oh, flare, "@roof", "@accent", "@stairs")
        tups += _gable(x0, z0, x1, z1, y + 1, "@roof", "@accent")
        return _ops_from_tuples(tups, mats)

    if variant == "temple_double_eave":
        oh = max(1, min(3, min(x1 - x0 + 1, z1 - z0 + 1) // 3))
        tups = eaves.eave_shelf(x0, z0, x1, z1, y, oh, "@roof")
        tups += eaves.eave_upturn(x0, z0, x1, z1, y, oh, flare, "@roof", "@accent", "@stairs")
        # wall drum, then an upper hip over an inset footprint
        ins = max(1, oh)
        for x in range(x0 + ins, x1 - ins + 1):
            for z in range(z0 + ins, z1 - ins + 1):
                if x in (x0 + ins, x1 - ins) or z in (z0 + ins, z1 - ins):
                    tups.append((x, y + 1, z, "@primary"))
                    tups.append((x, y + 2, z, "@primary"))
        tups += eaves.asian_hip(x0 + ins, z0 + ins, x1 - ins, z1 - ins, y + 3,
                                flare=flare, roof_role="@roof", accent_role="@accent",
                                stairs_role="@stairs")
        return _ops_from_tuples(tups, mats)

    if variant == "irimoya":  # hip-and-gable
        tups = eaves.asian_hip(x0, z0, x1, z1, y, flare=flare)
        # small accent gable ridge near the peak
        cx, cz = (x0 + x1) // 2, (z0 + z1) // 2
        peak = y + 1 + min(x1 - x0, z1 - z0) // 2
        if x1 - x0 >= z1 - z0:
            for x in range(cx - 1, cx + 2):
                tups.append((x, peak, cz, "@accent"))
        else:
            for z in range(cz - 1, cz + 2):
                tups.append((cx, peak, z, "@accent"))
        return _ops_from_tuples(tups, mats)

    # default: hip_upturn
    tups = eaves.asian_hip(x0, z0, x1, z1, y, flare=flare)
    return _ops_from_tuples(tups, mats)
