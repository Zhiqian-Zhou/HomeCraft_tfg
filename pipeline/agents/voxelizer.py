"""Voxelizer: master_plan JSON → ReferenceBuilding JSON.

Translates each shape op to a pipeline.skills.base.Op instance (expanding
`skill` ops via get_skill), runs the composer (later-wins + air-stripping)
and wraps the result in a schema-valid ReferenceBuilding document the
viewer can load directly.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from pipeline.skills import get_skill
from pipeline.skills.base import AABB, Materials, op_from_dict
from pipeline.skills.composer import compose

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RAG = REPO_ROOT / "rag"
GENS_DIR = REPO_ROOT / "scratch" / "generations"

_STYLE_ENUM = {
    "medieval", "fantasy", "gothic", "renaissance", "modern", "minimalist",
    "japanese", "chinese", "mediterranean", "rustic", "viking", "egyptian",
    "victorian", "industrial", "futuristic", "other",
}

_CATEGORY_ENUM = {
    "residential", "castle", "tower", "temple", "shop", "tavern", "barn",
    "windmill", "lighthouse", "village", "ruin", "monument", "other",
}

_FURNITURE_BARE = {
    "minecraft:bed", "minecraft:red_bed", "minecraft:white_bed",
    "minecraft:blue_bed", "minecraft:black_bed", "minecraft:purple_bed",
    "minecraft:pink_bed", "minecraft:gray_bed", "minecraft:yellow_bed",
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


def _size_bucket(size: list[int]) -> str:
    m = max(size)
    if m <= 8:  return "small"
    if m <= 16: return "medium"
    if m <= 32: return "large"
    return "xlarge"


_FACING_FLIP_X = {"east": "west", "west": "east"}
_FACING_FLIP_Z = {"north": "south", "south": "north"}


def _flip_facing(block: str, fx: bool, fz: bool) -> str:
    """Voltea facing=… en el blockstate al espejar (stairs/bed/door…)."""
    if "facing=" not in block:
        return block
    import re
    def repl(m):
        d = m.group(1)
        if fx and d in _FACING_FLIP_X: d = _FACING_FLIP_X[d]
        if fz and d in _FACING_FLIP_Z: d = _FACING_FLIP_Z[d]
        return "facing=" + d
    return re.sub(r"facing=([a-z]+)", repl, block)


class _MirrorOp:
    """Envuelve un Op y espeja sus voxels dentro del AABB de la sala (FIX 1):
    da 3-4 variantes de layout deterministas por seed SIN tocar cada skill."""
    __slots__ = ("inner", "x0", "x1", "z0", "z1", "fx", "fz")

    def __init__(self, inner, x0, x1, z0, z1, fx, fz):
        self.inner, self.x0, self.x1, self.z0, self.z1 = inner, x0, x1, z0, z1
        self.fx, self.fz = fx, fz

    def compile(self, materials):
        for (x, y, z, block) in self.inner.compile(materials):
            nx = (self.x0 + self.x1 - 1 - x) if self.fx else x
            nz = (self.z0 + self.z1 - 1 - z) if self.fz else z
            yield (nx, y, nz, _flip_facing(block, self.fx, self.fz))


def _expand_ops(master_ops: list[dict], style: str, materials: Materials,
                seed: int = 0):
    """Yield Op instances from the master_plan ops list.

    Dispatch:
      * `kind == "skill"`    → `pipeline.skills.get_skill(id)` → list of Ops
      * `kind == "typology"` → `pipeline.skills.typologies.get_typology(name)`
                                → list of Ops (Fase 4 catalog)
      * anything else        → `op_from_dict(d)` (atomic AST op)

    FIX 5: a cada skill se le pasa un `seed` derivado de (seed_global, room_id,
    skill_id, índice) para que pueda elegir variante de layout de forma
    determinista-pero-variada (FIX 1). Skills que no lo usen lo ignoran (**kwargs).
    """
    from pipeline.skills.seedutil import seed_from
    for idx, d in enumerate(master_ops):
        k = d.get("kind")
        if k == "skill":
            sid = d["skill_id"]
            aabb = AABB(*d["aabb"])
            sub_style = d.get("style", style)
            kwargs = dict(d.get("kwargs") or {})
            kwargs.setdefault("seed", seed_from(seed, d.get("room_id") or "", sid, idx))
            try:
                build = get_skill(sid)
            except Exception as e:  # noqa: BLE001
                # Skill referenced in RAG but no loadable Python module (or it
                # errors on import). Skip the op rather than crash the whole
                # build — one broken skill must not nuke an otherwise-fine house.
                print(f"[voxelizer] skipping op: skill {sid!r} failed to load ({e})",
                      file=sys.stderr)
                continue
            try:
                produced = list(build(aabb=aabb, materials=materials, style=sub_style, **kwargs))
            except TypeError:
                # Skill may not accept arbitrary kwargs — retry without
                produced = list(build(aabb=aabb, materials=materials, style=sub_style))
            except Exception as e:  # noqa: BLE001
                print(f"[voxelizer] skipping op: skill {sid!r} build() error ({e})",
                      file=sys.stderr)
                continue
            # FIX 1: variante de layout por seed — espejo X/Z DENTRO del AABB de
            # la skill (no mueve nada fuera → sin colisiones). 4 variantes:
            # 0 identidad · 1 espejo-X · 2 espejo-Z · 3 ambos.
            v = seed_from(seed, d.get("room_id") or "", sid, idx) % 4
            if v == 0:
                yield from produced
            else:
                fx, fz = bool(v & 1), bool(v & 2)
                for op in produced:
                    yield _MirrorOp(op, aabb.x0, aabb.x1, aabb.z0, aabb.z1, fx, fz)
        elif k == "typology":
            # Lazy import keeps the import surface small for callers that
            # never touch typologies (e.g. gym smoke runs without RAG).
            from pipeline.skills.typologies import get_typology
            name = d["name"]
            aabb = AABB(*d["aabb"])
            sub_style = d.get("style", style)
            kwargs = d.get("kwargs") or {}
            try:
                build = get_typology(name)
            except Exception as e:  # noqa: BLE001
                # Typology referenced but no loadable module — skip the op
                # rather than crash the whole build (mirrors the skill path).
                print(f"[voxelizer] skipping op: typology {name!r} failed to load ({e})",
                      file=sys.stderr)
                continue
            try:
                yield from build(aabb=aabb, materials=materials,
                                 style=sub_style, **kwargs)
            except TypeError:
                yield from build(aabb=aabb, materials=materials,
                                 style=sub_style)
            except Exception as e:  # noqa: BLE001
                print(f"[voxelizer] skipping op: typology {name!r} build() error ({e})",
                      file=sys.stderr)
                continue
        else:
            yield op_from_dict(d)


def voxelize(master_plan: dict, *, out_dir: Path | None = None) -> Path:
    """Voxelize a master_plan and write the ReferenceBuilding JSON.

    Returns the absolute path to the written file.
    """
    out_dir = out_dir or GENS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    style = master_plan["style"]
    category = (master_plan.get("category") or "").lower() or None
    materials = Materials.for_style(style)
    # Category override: swap a handful of slots when the (style, category)
    # combination calls for a clearly different look (e.g. medieval CASTLE
    # uses stone, modern TOWER uses glass + black trim). Source of truth is
    # architecture_planner._CATEGORY_OVERRIDES so palette stays consistent
    # between the architecture envelope and the room/skill interior.
    if category:
        from dataclasses import replace
        from pipeline.agents.architecture_planner import _CATEGORY_OVERRIDES
        override = _CATEGORY_OVERRIDES.get((style, category))
        if override:
            materials = replace(materials, **{
                k: v for k, v in override.items()
                if k in {f.name for f in materials.__dataclass_fields__.values()}
            })

    ops = list(_expand_ops(master_plan["ops"], style, materials,
                           seed=int(master_plan.get("seed") or 0)))
    voxels, palette, (W, H, D), origin = compose(ops, materials)
    if not voxels:
        raise ValueError("voxelizer: composed result is empty (no voxels)")
    ox0, oy0, oz0 = origin   # traslación que aplicó compose (final = op − origin)

    style_in_enum = style if style in _STYLE_ENUM else "other"
    category = (master_plan.get("category") or "residential").lower()
    if category not in _CATEGORY_ENUM:
        category = "other"

    furniture_blocks = _count_furniture(voxels, palette)
    interior_populated = furniture_blocks >= 20

    gen_id = master_plan["id"]
    prompt = master_plan.get("prompt", "")
    title = prompt[:80] if prompt else f"generation {gen_id}"

    doc = {
        "id":          gen_id,
        "source":      "synthetic",
        "source_url":  f"https://homecraft.tfg/generation/{gen_id}",
        "license":     "MIT",
        "license_notes": "Generated by pipeline.agents.voxelizer from a HomeCraft v2 master_plan.",
        "title":       title,
        "description": prompt,
        "tags": {
            "category":    category,
            "style":       [style_in_enum],
            "size_bucket": _size_bucket([W, H, D]),
        },
        "bounding_box": {"size": [W, H, D]},
        "block_palette": palette,
        "voxels":        voxels,
        "bot_decomposition": master_plan.get("bot_decomposition"),
        # connectors trasladados a coords FINALES (compose normaliza al origen):
        # así el visor resalta/aísla la escalera (y puertas/ventanas) en el sitio
        # EXACTO de los vóxeles, no desplazado por el margen de terreno.
        "connectors":    _shift_connectors(master_plan.get("connectors"),
                                            ox0, oy0, oz0),
        "metadata_quality": {
            "interior_populated": interior_populated,
            "has_labels":         master_plan.get("bot_decomposition") is not None,
            "furniture_blocks":   furniture_blocks,
            "ingest_warnings":    ["generated"] + master_plan.get("warnings", []),
        },
        "ingest": {
            "tool":          "pipeline.agents.voxelizer",
            "tool_version":  "0.1.0",
            "source_format": "json",
            "ingested_at":   datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "ingester_path": str(__file__),
        },
    }

    _validate_reference_building(doc)

    out_path = out_dir / f"{gen_id}.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return out_path


def _shift_connectors(conn: dict | None, ox: int, oy: int, oz: int) -> dict | None:
    """Traslada las coordenadas (aabb/at, también en .validated) de los
    conectores por (−ox,−oy,−oz) → del espacio-op al espacio FINAL de vóxeles
    (compose normaliza el mínimo al origen). Devuelve una copia."""
    if not isinstance(conn, dict) or (ox == 0 and oy == 0 and oz == 0):
        return conn
    import copy
    c = copy.deepcopy(conn)

    def shift_aabb(a):
        return [a[0]-ox, a[1]-oy, a[2]-oz, a[3]-ox, a[4]-oy, a[5]-oz] \
            if isinstance(a, list) and len(a) == 6 else a

    def shift_at(a):
        return [a[0]-ox, a[1]-oy, a[2]-oz] \
            if isinstance(a, list) and len(a) == 3 else a

    for kind in ("doors", "windows", "staircases"):
        for item in c.get(kind) or []:
            if not isinstance(item, dict):
                continue
            for obj in (item, item.get("validated") if isinstance(item.get("validated"), dict) else None):
                if not isinstance(obj, dict):
                    continue
                if "aabb" in obj:
                    obj["aabb"] = shift_aabb(obj["aabb"])
                if "at" in obj:
                    obj["at"] = shift_at(obj["at"])
    return c


def _count_furniture(voxels, palette) -> int:
    furn_idxs = {int(i) for i, b in palette.items() if _bare(b) in _FURNITURE_BARE}
    if not furn_idxs:
        return 0
    return sum(1 for _, _, _, p in voxels if p in furn_idxs)


def _validate_reference_building(doc: dict) -> None:
    schema = json.loads((RAG / "schema" / "reference_building.schema.json").read_text())
    Draft202012Validator(schema).validate(doc)


if __name__ == "__main__":
    # Smoke test on a hand-crafted minimal master_plan
    master = {
        "id": "voxsmoke",
        "prompt": "tiny test kitchen",
        "style": "medieval",
        "category": "residential",
        "site_aabb": [0, 0, 0, 8, 5, 8],
        "ops": [
            {"kind": "rect", "aabb": [0,0,0, 8,1,8], "axis": "y", "level": 0,
             "block": "minecraft:grass_block"},
            {"kind": "skill", "skill_id": "kitchen", "aabb": [0,1,0, 7,5,7],
             "style": "medieval"},
        ],
        "bot_decomposition": {
            "building": {"storeys": [
                {"id": "ground", "spaces": [
                    {"id": "kitchen-1", "function": "kitchen", "aabb": [0,1,0,7,5,7]}
                ]}
            ]}
        },
        "warnings": [],
    }
    p = voxelize(master)
    print(f"wrote {p}")
    doc = json.loads(p.read_text())
    print(f"  voxels={len(doc['voxels'])}, palette={len(doc['block_palette'])}, size={doc['bounding_box']['size']}")
