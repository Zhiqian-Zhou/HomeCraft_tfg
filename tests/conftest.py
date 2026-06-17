"""Shared test fixtures for evaluator metric tests.

Provides `build_doc` to construct synthetic ReferenceBuilding documents
without needing to run the whole pipeline. Each metric test can use it
to assemble a minimal voxel-and-palette doc and a bot_decomposition.
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Iterable
import pytest


def build_doc(
    voxels: list[tuple[int, int, int, str]],
    *,
    size: tuple[int, int, int] | None = None,
    bot_storeys: list[dict] | None = None,
    building_id: str = "test-building",
    style: str = "medieval",
    category: str = "residential",
) -> dict:
    """Build a synthetic ReferenceBuilding doc from a list of (x, y, z, block_id).

    Args:
      voxels: list of (x, y, z, block_id) tuples. block_id is namespaced
        like "minecraft:oak_planks[half=lower]" or just "minecraft:stone".
      size: explicit bounding_box.size [W, H, D]. If None, computed from voxels.
      bot_storeys: list of storey dicts each with `id` and `spaces`.
        Each space is {id, function, aabb}. None for no bot_decomposition.
      building_id, style, category: metadata.

    Returns: dict matching reference_building.schema.json (loose).
    """
    # Build palette as OrderedDict (first-seen order)
    palette_str: dict[str, str] = OrderedDict()
    vox_entries = []
    for x, y, z, bid in voxels:
        full = bid if bid.startswith("minecraft:") else f"minecraft:{bid}"
        if full not in palette_str.values():
            palette_str[str(len(palette_str))] = full
        idx = next(k for k, v in palette_str.items() if v == full)
        vox_entries.append([x, y, z, int(idx)])

    if size is None:
        if not voxels:
            size = (1, 1, 1)
        else:
            W = max(v[0] for v in voxels) + 1
            H = max(v[1] for v in voxels) + 1
            D = max(v[2] for v in voxels) + 1
            size = (W, H, D)

    doc: dict = {
        "id": building_id,
        "source": "synthetic",
        "source_url": f"https://test/{building_id}",
        "license": "MIT",
        "title": building_id,
        "tags": {"category": category, "style": [style]},
        "bounding_box": {"size": list(size)},
        "block_palette": dict(palette_str),
        "voxels": vox_entries,
        "bot_decomposition": None,
        "metadata_quality": {
            "interior_populated": False,
            "has_labels": bot_storeys is not None,
            "furniture_blocks": 0,
            "ingest_warnings": ["synthetic_test"],
        },
        "ingest": {
            "tool": "tests.conftest.build_doc",
            "tool_version": "1.0",
            "source_format": "json",
            "ingested_at": "2026-05-26T00:00:00Z",
            "ingester_path": __file__,
        },
    }
    if bot_storeys:
        doc["bot_decomposition"] = {"building": {"storeys": bot_storeys}}
        doc["metadata_quality"]["has_labels"] = True
    return doc


def build_master_plan(
    *,
    doors: list[dict] | None = None,
    windows: list[dict] | None = None,
    staircases: list[dict] | None = None,
    gen_id: str = "test-master",
    style: str = "medieval",
) -> dict:
    """Build a minimal master_plan with the given connectors."""
    return {
        "id": gen_id,
        "style": style,
        "category": "residential",
        "site_aabb": [0, 0, 0, 16, 8, 16],
        "ops": [],
        "bot_decomposition": {"building": {"storeys": []}},
        "warnings": [],
        "connectors": {
            "doors": doors or [],
            "windows": windows or [],
            "staircases": staircases or [],
        },
    }


def solid_box(x0: int, y0: int, z0: int, x1: int, y1: int, z1: int,
              block: str = "minecraft:oak_planks") -> list[tuple]:
    """Generate a solid box of voxels for the given AABB (half-open)."""
    return [(x, y, z, block)
            for x in range(x0, x1)
            for y in range(y0, y1)
            for z in range(z0, z1)]


def hollow_box(x0: int, y0: int, z0: int, x1: int, y1: int, z1: int,
               wall: str = "minecraft:oak_planks",
               floor: str | None = None,
               ceiling: str | None = None) -> list[tuple]:
    """Generate a hollow box: walls, floor (optional), ceiling (optional)."""
    out = []
    floor = floor or wall
    ceiling = ceiling or wall
    for x in range(x0, x1):
        for y in range(y0, y1):
            for z in range(z0, z1):
                if y == y0:
                    out.append((x, y, z, floor))
                elif y == y1 - 1:
                    out.append((x, y, z, ceiling))
                elif x in (x0, x1 - 1) or z in (z0, z1 - 1):
                    out.append((x, y, z, wall))
    return out
