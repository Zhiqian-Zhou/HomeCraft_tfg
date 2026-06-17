"""Export a skill's output as a ReferenceBuilding JSON the viewer can load.

    from pipeline.skills.preview import export_skill
    path = export_skill('kitchen', style='medieval', size='small')
    # → scratch/skill_previews/kitchen__medieval__small.json
"""
from __future__ import annotations

import json
from pathlib import Path

from . import get_skill
from .base import AABB, Materials
from .composer import compose


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PREVIEWS_DIR = REPO_ROOT / "scratch" / "skill_previews"


# Synthetic sizes per skill category — small for fast iteration, medium for
# stress-testing the skill's scaling behavior.
SIZES = {
    "small":  AABB(0, 0, 0,  6, 4,  6),
    "medium": AABB(0, 0, 0, 12, 6, 12),
    "large":  AABB(0, 0, 0, 20, 8, 20),
}


def export_skill(skill_id: str, *, style: str = "medieval",
                  size: str = "small", aabb: AABB | None = None,
                  out_dir: Path = PREVIEWS_DIR) -> Path:
    """Run the skill, compose, and write a ReferenceBuilding JSON.

    Returns the output path. The output is schema-valid (no air in palette,
    no air voxels, valid category/style enums).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if aabb is None:
        aabb = SIZES.get(size, SIZES["small"])
    materials = Materials.for_style(style)
    build = get_skill(skill_id)
    ops = build(aabb=aabb, materials=materials, style=style)
    if not ops:
        raise ValueError(f"skill '{skill_id}' returned no ops")
    voxels, palette, (W, H, D), _origin = compose(ops, materials)
    if not voxels:
        raise ValueError(f"skill '{skill_id}' produced zero voxels after compose")

    doc = {
        "id": f"skill-{skill_id}-{style}-{size}",
        "source": "synthetic",
        "source_url": f"https://homecraft.tfg/skill/{skill_id}",
        "license": "MIT",
        "license_notes": f"skill preview: pipeline/skills/{skill_id}.py",
        "title": f"{skill_id} ({style}, {size})",
        "tags": {
            "category": _category_for_skill(skill_id),
            "style": [style if style in _STYLE_ENUM else "other"],
        },
        "bounding_box": {"size": [W, H, D]},
        "block_palette": palette,
        "voxels": voxels,
        "bot_decomposition": None,
        "metadata_quality": {
            "interior_populated": _has_furniture(palette),
            "has_labels": False,
            "furniture_blocks": _count_furniture_voxels(voxels, palette),
            "ingest_warnings": ["skill_preview"],
        },
        "ingest": {
            "tool": "pipeline.skills.preview",
            "tool_version": "0.1.0",
            "source_format": "other",
            "ingested_at": _now_iso(),
            "ingester_path": __file__,
        },
    }
    out = out_dir / f"{skill_id}__{style}__{size}.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ────────────────────────────────────────────────────────────────────────

_STYLE_ENUM = {
    "medieval", "fantasy", "gothic", "renaissance", "modern", "minimalist",
    "japanese", "chinese", "mediterranean", "rustic", "viking", "egyptian",
    "victorian", "industrial", "futuristic", "other",
}

_CATEGORY_OVERRIDES = {
    "round_tower": "tower", "square_tower": "tower",
    "dovecote": "tower",
    "courtyard_well": "monument", "courtyard_indoor": "other",
    "garden_bed": "other",
    "perimeter_wall_fortified": "other", "perimeter_wall_with_windows": "other",
    "chimney": "other", "gabled_roof": "other", "hip_roof": "other",
    "dome_roof": "other", "flat_roof": "other",
    "door_with_frame": "other", "double_door": "other", "window_bay": "other",
    "staircase": "other", "arch": "other",
    "balcony": "other",
    "pergola": "other",
    "column": "monument",
    "wall_partition": "other",
    "gatehouse": "castle",
    "parapet": "other",
    "drawbridge": "other",
    "bridge_arched": "other",
    "archway_passage": "other",
    "stained_glass_window": "other",
    "moat": "other",
    "fountain": "monument",
    "gazebo": "monument",
    "stable": "barn",
    "statue_pedestal": "monument",
}


def _category_for_skill(skill_id: str) -> str:
    if skill_id in _CATEGORY_OVERRIDES:
        return _CATEGORY_OVERRIDES[skill_id]
    # rooms map to residential
    return "residential"


_FURNITURE_BARE = {
    "minecraft:bed", "minecraft:red_bed", "minecraft:white_bed", "minecraft:blue_bed",
    "minecraft:crafting_table", "minecraft:furnace", "minecraft:smoker",
    "minecraft:blast_furnace", "minecraft:chest", "minecraft:barrel",
    "minecraft:bookshelf", "minecraft:lectern", "minecraft:cauldron",
    "minecraft:brewing_stand", "minecraft:enchanting_table",
    "minecraft:loom", "minecraft:cartography_table", "minecraft:smithing_table",
    "minecraft:stonecutter", "minecraft:grindstone", "minecraft:anvil",
    "minecraft:flower_pot", "minecraft:lantern", "minecraft:torch",
    "minecraft:campfire", "minecraft:soul_campfire", "minecraft:jukebox",
}


def _bare(block_id: str) -> str:
    idx = block_id.find("[")
    return block_id[:idx] if idx != -1 else block_id


def _has_furniture(palette: dict) -> bool:
    return any(_bare(b) in _FURNITURE_BARE for b in palette.values())


def _count_furniture_voxels(voxels, palette) -> int:
    furn_idxs = {int(i) for i, b in palette.items() if _bare(b) in _FURNITURE_BARE}
    return sum(1 for _, _, _, p in voxels if p in furn_idxs)


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
