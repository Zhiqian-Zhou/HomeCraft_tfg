"""Gabled Dormer — small projecting dormer on a sloped roof.

Source: TFGv2 `windows_v2.py:214-277` (WindowDormerGabledSkill).

3-wide front panel (sides solid, center glass), 2-block-deep side cheeks,
triangular gable roof with stair springers, full-block peak + capstone.
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="dormer_gabled",
    kind="window",
    title="Gabled Dormer",
    description=(
        "Small gabled dormer projecting from a sloped roof: 3-wide front "
        "panel (sides solid, center glass), 2-deep side cheeks, triangular "
        "gable roof. Victorian / Mansard / French roof signature."
    ),
    style_affinities=["victorian", "french", "mansard", "tudor", "fantasy"],
    scale_affinities=["medium", "large"],
    typical_footprint=(3, 4, 3),
    cost_blocks=20,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a south-facing gabled dormer at the AABB's z0 wall plane.

    The dormer's front face is at z == z0, and the side cheeks extend
    NORTH (increasing z) into the roof body.
    """
    ops: list[Op] = []
    a = aabb
    cx = a.cx
    z_front = a.z0
    base_y = a.y0

    # Front wall: 3 wide × 2 tall — center glass, sides @primary.
    for sign in (-1, 0, 1):
        for yo in (0, 1):
            block = "@glass" if sign == 0 else "@primary"
            ops.append(PlaceBlock(x=cx + sign, y=base_y + yo, z=z_front,
                                  block=block))
    # Side cheeks: 2 cells deep behind the dormer (increasing z).
    for sign in (-1, 1):
        for depth in (1, 2):
            for yo in (0, 1):
                ops.append(PlaceBlock(x=cx + sign, y=base_y + yo,
                                      z=z_front + depth,
                                      block="@primary"))
    # Front gable triangle: stair springers + peak.
    ops.append(PlaceBlock(x=cx - 1, y=base_y + 2, z=z_front,
                          block="@stairs[facing=south]"))
    ops.append(PlaceBlock(x=cx + 1, y=base_y + 2, z=z_front,
                          block="@stairs[facing=south]"))
    ops.append(PlaceBlock(x=cx,     y=base_y + 2, z=z_front, block="@primary"))
    ops.append(PlaceBlock(x=cx,     y=base_y + 3, z=z_front, block="@primary"))
    # Sloping side roof: 2 deep on each side.
    for depth in (1, 2):
        for sign in (-1, 0, 1):
            ops.append(PlaceBlock(x=cx + sign, y=base_y + 2, z=z_front + depth,
                                  block="@stairs[facing=south]"))
    return ops
