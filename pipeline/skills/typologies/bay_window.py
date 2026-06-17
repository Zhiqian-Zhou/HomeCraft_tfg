"""Bay Window — ground-floor 3-wide projecting bay.

Source: TFGv2 `windows_v2.py:92-147` (WindowBaySkill).

5-cell horizontal layout perpendicular to facing: two corner posts at the
wall plane, two angled returns one block out, a central glass panel one
block out. Slab cornice on top. Victorian / queen-anne / cottage.
"""
from __future__ import annotations

from ..base import AABB, Materials, Op, PlaceBlock
from .base import TypologyMetadata


METADATA = TypologyMetadata(
    name="bay_window",
    kind="window",
    title="Bay Window",
    description=(
        "Ground-floor 3-wide bay window projecting one block from the wall "
        "with angled side returns, full-height glass, and a slab cornice. "
        "Victorian / queen anne / cottage signature."
    ),
    style_affinities=["victorian", "queen_anne", "cottage", "edwardian"],
    scale_affinities=["small", "medium", "large"],
    typical_footprint=(5, 3, 2),
    cost_blocks=30,
    mc_version_min="1.16.5",
)


def build(aabb: AABB, materials: Materials, style: str, **kwargs) -> list[Op]:
    """Build a south-facing bay window at the AABB's z0 wall plane."""
    ops: list[Op] = []
    a = aabb
    h = kwargs.get("height", min(3, max(2, a.h - 1)))
    cx = a.cx
    base_y = a.y0
    wall_z = a.z0      # wall plane
    bay_z = a.z0 - 1   # 1 block out

    for yo in range(h):
        y = base_y + yo
        # Two corner posts at the wall plane (offsets -2 and +2).
        ops.append(PlaceBlock(x=cx - 2, y=y, z=wall_z, block="@primary"))
        ops.append(PlaceBlock(x=cx + 2, y=y, z=wall_z, block="@primary"))
        # Two angled returns one block out (offsets -1 and +1).
        ops.append(PlaceBlock(x=cx - 1, y=y, z=bay_z, block="@glass"))
        ops.append(PlaceBlock(x=cx + 1, y=y, z=bay_z, block="@glass"))
        # Central glass panel one block out.
        ops.append(PlaceBlock(x=cx,     y=y, z=bay_z, block="@glass"))

    # Slab cornice on top (5 cells across, returning to wall plane at edges).
    cornice_y = base_y + h
    ops.append(PlaceBlock(x=cx - 2, y=cornice_y, z=wall_z, block="@accent"))
    ops.append(PlaceBlock(x=cx + 2, y=cornice_y, z=wall_z, block="@accent"))
    for dx in (-1, 0, 1):
        ops.append(PlaceBlock(x=cx + dx, y=cornice_y, z=bay_z, block="@accent"))
    return ops
