"""Mini composer: AST ops → voxel list compatible with ReferenceBuilding.

Given a list of `Op` objects and a Materials, returns:
    voxels: List[(x, y, z, palette_idx)]   (palette_idx is an int)
    palette: dict[int, str]                (idx -> block_id)
    size: (W, H, D)                        (computed from the AABB bounds
                                            of the emitted voxels)

The composer applies "later wins" semantics — if two ops emit a block at
the same coord, the later one in the list overrides. Air blocks are
dropped (we use the air-stripped storage convention).
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Iterable

from .base import Materials, Op


AIR_VARIANTS = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}


def compose(ops: Iterable[Op], materials: Materials) -> tuple[list[list[int]], dict[str, str], tuple[int, int, int], tuple[int, int, int]]:
    """Run ops through the composer.

    Returns (voxels, palette_str_keyed, (W,H,D), (minx,miny,minz)). El 4º valor
    es el ORIGEN: la traslación aplicada (las coords finales = coord_op − min).
    Lo necesitan los consumidores que deben mapear coordenadas en espacio-op
    (p.ej. el footprint de la escalera del connector_plan) al espacio final.
    Palette keys are STRINGS so the result drops straight into a
    ReferenceBuilding JSON.
    """
    # later-wins dedupe
    cells: dict[tuple[int, int, int], str] = {}
    for op in ops:
        for (x, y, z, block) in op.compile(materials):
            if _bare(block) in AIR_VARIANTS:
                cells.pop((x, y, z), None)
                continue
            cells[(x, y, z)] = block

    if not cells:
        return [], {}, (0, 0, 0), (0, 0, 0)

    # bounding box (translate to origin)
    xs = [c[0] for c in cells]
    ys = [c[1] for c in cells]
    zs = [c[2] for c in cells]
    minx, miny, minz = min(xs), min(ys), min(zs)
    maxx, maxy, maxz = max(xs), max(ys), max(zs)
    W = maxx - minx + 1
    H = maxy - miny + 1
    D = maxz - minz + 1

    # palette by first-seen order
    palette_by_block: OrderedDict[str, int] = OrderedDict()
    voxels: list[list[int]] = []
    for (x, y, z), block in cells.items():
        if block not in palette_by_block:
            palette_by_block[block] = len(palette_by_block)
        voxels.append([x - minx, y - miny, z - minz, palette_by_block[block]])

    palette_str = {str(i): b for b, i in palette_by_block.items()}
    return voxels, palette_str, (W, H, D), (minx, miny, minz)


def _bare(block_id: str) -> str:
    idx = block_id.find("[")
    return block_id[:idx] if idx != -1 else block_id
