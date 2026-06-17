"""Dome roof — cúpula hemisférica sobre planta cuadrada.

The AABB defines the BASE footprint of the building underneath. The dome
sits ON TOP of the AABB (its first ring is at ``y = aabb.y1``) and rises
as a hemisphere whose radius equals ``R = min(W, D) // 2``.

For each layer ``y`` above the base (0 ≤ y < R), the ring radius is::

    r_y = floor( sqrt(R^2 - (y - R)^2) )   when y < R       (lower bowl)

Because we start at the equator (y=0 → r=R) and shrink to a single
column at the apex (y=R-1 → r≈1 → apex block at y=R), this gives a clean
half-dome silhouette. Each layer is emitted as a HOLLOW ``Cylinder``
ring of ``@roof`` material at the corresponding radius, so the dome is
a thin shell (no interior fill) — light blocks at the centre stay free
for an optional oculus.

Apex (top-most cell) is a single ``@accent`` block, except in the
``fantasy`` style where it becomes a ``minecraft:beacon`` for a glowing
crown. If the optional oculus is enabled (default: True when R ≥ 3) the
centre block of the next-to-apex ring is swapped for ``@glass``, opening
a small hole that admits light.

The skill is defensive on 5×?×5 (smallest sensible dome, R = 2) up to
18×?×18 (R = 9). For anything outside that range it returns no ops,
letting the composer skip a degenerate dome.

The roof voxels extend ABOVE ``aabb.y1`` — the composer recomputes the
final bounding box from the actual voxel coordinates, so callers do not
need to include the dome rise in the input AABB.
"""
from __future__ import annotations

from math import isqrt

from .base import AABB, Cylinder, Materials, Op, PlaceBlock


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    W, _H, D = aabb.size
    # Defensive bounds: dome reads cleanly only on roughly-square footprints
    # in [5, 18]. Anything outside that returns no ops.
    if W < 5 or D < 5 or W > 18 or D > 18:
        return []

    R = min(W, D) // 2  # hemisphere radius in cells
    if R < 2:
        return []

    y_base = aabb.y1  # equator ring sits immediately above the AABB top
    cx = aabb.x0 + (W // 2)
    cz = aabb.z0 + (D // 2)

    # Optional oculus: by default enabled on R ≥ 3 so the dome has a
    # visible "skylight" at the top. Callers may force via kwargs.
    oculus = kwargs.get("oculus", R >= 3)

    # Apex block — fantasy gets a beacon, everyone else uses @accent.
    apex_block = "minecraft:beacon" if style.lower() == "fantasy" else "@accent"

    ops: list[Op] = []

    # Track the per-layer radii so we know the next-to-apex one for the
    # oculus swap.
    layer_radii: list[tuple[int, int]] = []  # (y_local, r)

    # Build hemisphere layers. The standard parameterization used here is::
    #
    #     r_y = floor( sqrt(R^2 - y_local^2) )   for y_local in [0, R]
    #
    # which at y_local = 0 gives R (equator) and at y_local = R - 1 gives
    # 1 (the column just below the apex). We then place an apex block at
    # y_local = R. To keep the dome readable on small R we sample integer
    # y_local values but DO NOT skip duplicate radii — duplicate hollow
    # rings stack as a tiny vertical band on the silhouette, which is the
    # correct rasterization of a curve that locally stays at the same
    # horizontal radius for more than one block of height.
    for y_local in range(R):
        disc = R * R - y_local * y_local
        r = isqrt(disc) if disc > 0 else 0
        if r < 1:
            break
        layer_radii.append((y_local, r))

        ops.append(Cylinder(
            cx=cx,
            cz=cz,
            y0=y_base + y_local,
            radius=r,
            height=1,
            block="@roof",
            hollow=True,
        ))

    # Apex block sits one cell above the topmost hollow ring.
    if layer_radii:
        apex_y_local = layer_radii[-1][0] + 1
    else:
        apex_y_local = 0
    apex_y = y_base + apex_y_local
    ops.append(PlaceBlock(cx, apex_y, cz, apex_block))

    # Oculus: open a small hole at the crown by capping the cell just
    # below the apex with @glass instead of @roof. With hollow=True a
    # Cylinder of radius r places blocks where (r-1)^2 < d^2 <= r^2, so
    # the centre cell (d=0) is solid only when r = 1. We therefore swap
    # the centre of whichever ring was the last (smallest) one for glass,
    # which works whether that ring is r=1 (replacing the single solid
    # block) or r >= 2 (the swap is a no-op since the centre was air,
    # but the apex above still admits the visual idea of a closed crown).
    # In practice the topmost ring is r=1 for R in [2, 4], and r=2 or 3
    # for larger domes; for those larger domes we explicitly drop a glass
    # disk on top of the smallest ring to cap the opening cleanly.
    if oculus and len(layer_radii) >= 2:
        top_y_local, top_r = layer_radii[-1]
        if top_r == 1:
            # Replace the single solid block of the r=1 ring with glass.
            ops.append(PlaceBlock(cx, y_base + top_y_local, cz, "@glass"))
        else:
            # Cap the open air column of the small top ring with a glass
            # disk on the layer between the ring and the apex.
            ops.append(PlaceBlock(cx, apex_y - 1, cz, "@glass"))

    return ops
