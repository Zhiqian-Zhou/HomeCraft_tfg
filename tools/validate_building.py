"""Validate a ReferenceBuilding JSON against the canonical schema.

Usage:
    python tools/validate_building.py rag/reference_buildings/processed/*.json
    python tools/validate_building.py --schema rag/schema/reference_building.schema.json <file>

Exits 0 if all files pass, 1 otherwise. Reports per-file errors with file:offset format.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

try:
    from jsonschema import Draft202012Validator
except ImportError:
    print("[validate] jsonschema not installed. Run: pip install jsonschema", file=sys.stderr)
    sys.exit(2)


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = REPO_ROOT / "rag" / "schema" / "reference_building.schema.json"


def load_schema(schema_path: Path) -> Draft202012Validator:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


AIR_VARIANTS = {"minecraft:air", "minecraft:cave_air", "minecraft:void_air"}


def cross_check_voxels(doc: dict) -> list[str]:
    issues: list[str] = []
    bb = doc.get("bounding_box", {}).get("size")
    if not (isinstance(bb, list) and len(bb) == 3):
        return issues
    W, H, D = bb
    palette = doc.get("block_palette", {})
    palette_keys = {int(k) for k in palette.keys()}

    for idx_str, block_id in palette.items():
        bare = block_id.split("[", 1)[0]
        if bare in AIR_VARIANTS:
            issues.append(
                f"block_palette[{idx_str}]: '{block_id}' is air — "
                "air must be implicit (not stored in palette/voxels)"
            )

    seen: set[tuple[int, int, int]] = set()
    for idx, vox in enumerate(doc.get("voxels", [])):
        if len(vox) != 4:
            issues.append(f"voxels[{idx}]: expected [x,y,z,palette_idx]")
            continue
        x, y, z, p = vox
        if not (0 <= x < W and 0 <= y < H and 0 <= z < D):
            issues.append(f"voxels[{idx}]: ({x},{y},{z}) outside [0..{W-1}]x[0..{H-1}]x[0..{D-1}]")
        if p not in palette_keys:
            issues.append(f"voxels[{idx}]: palette_idx {p} not in block_palette")
        coord = (x, y, z)
        if coord in seen:
            issues.append(f"voxels[{idx}]: duplicate coord {coord}")
        seen.add(coord)
    return issues


def validate_file(path: Path, validator: Draft202012Validator) -> list[str]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON ({exc.msg} at line {exc.lineno})"]

    errors: list[str] = []
    for err in sorted(validator.iter_errors(doc), key=lambda e: e.path):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        errors.append(f"{path}: [{loc}] {err.message}")

    if not errors:
        errors.extend(f"{path}: {msg}" for msg in cross_check_voxels(doc))

    return errors


def gather_paths(args: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            out.extend(sorted(p.glob("*.json")))
        else:
            out.append(p)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    args = parser.parse_args(argv)

    validator = load_schema(args.schema)
    paths = gather_paths(args.paths)

    total_failures = 0
    for path in paths:
        errs = validate_file(path, validator)
        if errs:
            total_failures += 1
            for e in errs:
                print(e, file=sys.stderr)

    summary = f"[validate] {len(paths) - total_failures}/{len(paths)} files OK"
    print(summary, file=sys.stderr)
    return 0 if total_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
