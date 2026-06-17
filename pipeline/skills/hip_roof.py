"""Hip roof — tejado a cuatro aguas (four-pitch pyramidal roof).

The AABB defines the BASE footprint of the building underneath. The roof
sits ON TOP of the AABB (its first layer is at ``y = aabb.y1``) and climbs
one block per layer, shrinking by one on every side at each step, so that
all four pitches converge on a single apex.

Layout per layer ``k`` above the base (0 ≤ k < layers):
    - Outer ring uses ``@stairs`` blocks facing *inward* toward the apex.
        * north edge (z = z0 + k)   → facing south
        * south edge (z = z1-1 - k) → facing north
        * west edge  (x = x0 + k)   → facing east
        * east edge  (x = x1-1 - k) → facing west
    - Inner cells (if any) are filled with ``@roof``.
    - Corner cells are stairs of one of the two adjacent sides (we pick the
      side belonging to the longer remaining dimension; ties go to the
      x-edges so the four corners always read consistently).

Apex (top-most cell) is a solid ``@primary`` block. For larger footprints
(min(W, D) ≥ 8) we crown it with a small chimney top (lantern over an accent
block) to break the silhouette — purely cosmetic.

Hip roofs need both horizontal dimensions to be comparable, so this skill
is defensive on small footprints (4×?×4 to 14×?×14). For anything outside
that range it returns no ops, letting the composer skip a degenerate roof.

The roof voxels extend ABOVE ``aabb.y1`` — the composer recomputes the final
bounding box from the actual voxel coordinates, so callers do not need to
include the roof height in the input AABB.
"""
from __future__ import annotations

from .base import AABB, Materials, Op, PlaceBlock, Rect


# Facing strings as understood by Minecraft 1.16.5 stairs blockstates.
_FACING_SOUTH = "south"
_FACING_NORTH = "north"
_FACING_EAST  = "east"
_FACING_WEST  = "west"


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    W, _H, D = aabb.size
    # Defensive: hip needs both dims in [4, 14]. Height of input AABB is
    # only used as the y-anchor (the roof sits at aabb.y1) — it does not
    # constrain the roof's own rise.
    if W < 4 or D < 4 or W > 14 or D > 14:
        return []

    layers = min(W, D) // 2  # how many shrinking rings before the apex
    if layers < 1:
        return []

    y_base = aabb.y1  # roof base layer sits immediately above the AABB top
    ops: list[Op] = []

    for k in range(layers):
        y = y_base + k
        x0 = aabb.x0 + k
        x1 = aabb.x1 - k         # half-open
        z0 = aabb.z0 + k
        z1 = aabb.z1 - k

        rw = x1 - x0
        rd = z1 - z0
        if rw <= 0 or rd <= 0:
            break

        # Single-cell ring → just one apex block (handled after the loop too,
        # but emitting here keeps coverage if loop runs to a 1×1 slice).
        if rw == 1 and rd == 1:
            ops.append(PlaceBlock(x0, y, z0, "@primary"))
            continue

        # Fill the inner area (everything but the outer ring) with @roof.
        # Inner is [x0+1, x1-1) × [z0+1, z1-1).
        if rw > 2 and rd > 2:
            ops.append(Rect(
                AABB(x0 + 1, y, z0 + 1, x1 - 1, y + 1, z1 - 1),
                "@roof", axis="y", level=y,
            ))

        stairs = materials.stairs

        # Place stairs on the four edges. For corners we pick the side that
        # has the longer remaining edge so the pitch reads cleanly.
        prefer_x = rw >= rd  # corners take the x-edge facing if x is longer

        for x in range(x0, x1):
            # north edge (z = z0): stairs face south
            block_n = f"{stairs}[facing={_FACING_SOUTH}]"
            # south edge (z = z1 - 1): stairs face north
            block_s = f"{stairs}[facing={_FACING_NORTH}]"
            ops.append(PlaceBlock(x, y, z0, block_n))
            ops.append(PlaceBlock(x, y, z1 - 1, block_s))

        for z in range(z0, z1):
            block_w = f"{stairs}[facing={_FACING_EAST}]"
            block_e = f"{stairs}[facing={_FACING_WEST}]"
            # If the previous (x-edge) pass owns the corners, skip them here.
            if prefer_x and (z == z0 or z == z1 - 1):
                continue
            ops.append(PlaceBlock(x0, y, z, block_w))
            ops.append(PlaceBlock(x1 - 1, y, z, block_e))

        # If we did NOT let the x-edges own the corners, overwrite them now
        # with the z-edge facings so all four corners are consistent on the
        # longer side. (later-wins in the composer makes this safe.)
        if not prefer_x:
            ops.append(PlaceBlock(x0, y, z0, f"{stairs}[facing={_FACING_EAST}]"))
            ops.append(PlaceBlock(x1 - 1, y, z0, f"{stairs}[facing={_FACING_WEST}]"))
            ops.append(PlaceBlock(x0, y, z1 - 1, f"{stairs}[facing={_FACING_EAST}]"))
            ops.append(PlaceBlock(x1 - 1, y, z1 - 1, f"{stairs}[facing={_FACING_WEST}]"))

    # ── Apex ──────────────────────────────────────────────────────────────
    apex_y = y_base + layers
    apex_x = aabb.x0 + (W // 2)
    apex_z = aabb.z0 + (D // 2)

    if min(W, D) >= 8:
        # Decorative chimney top: accent base + lantern on top.
        ops.append(PlaceBlock(apex_x, apex_y, apex_z, "@accent"))
        ops.append(PlaceBlock(apex_x, apex_y + 1, apex_z, "minecraft:lantern"))
    else:
        ops.append(PlaceBlock(apex_x, apex_y, apex_z, "@primary"))

    # If W and D differ in parity, the inner shrink may leave a leftover
    # rectangular "ridge" before the apex (the shorter dim collapses first).
    # We cap any such residual cells with @roof so the surface is closed.
    extra = abs(W - D)
    if extra > 0:
        # Determine the remaining inner extent on the longer axis after
        # `layers` shrinks. Whichever axis is longer keeps `extra + 1` cells
        # along that line, all at apex_y.
        if W > D:
            xs0 = aabb.x0 + layers
            xs1 = aabb.x1 - layers
            for x in range(xs0, xs1):
                if x == apex_x:
                    continue  # apex already placed
                ops.append(PlaceBlock(x, apex_y, apex_z, "@roof"))
        else:  # D > W
            zs0 = aabb.z0 + layers
            zs1 = aabb.z1 - layers
            for z in range(zs0, zs1):
                if z == apex_z:
                    continue
                ops.append(PlaceBlock(apex_x, apex_y, z, "@roof"))

    return ops
