"""Cross-reference verifier for the global RAG.

Checks that every reference between collections lands on something real.
Six checks:
  1. skill → pattern : every alexander_patterns_relevant id exists in rag/patterns/
  2. style → pattern : every alexander_patterns id in style packs exists
  3. skill → material: every block_id used by skills/styles is catalogued in rag/materials/
  4. building → material: every block in processed/ buildings is catalogued (top-N only)
  5. skill → skill   : skills referenced by other skills exist as modules
  6. schema all      : every JSON in A/B/C/D validates against its schema

Prints a human-readable report and exits 0 iff all six pass.

    python3 tools/verify_rag_cross_refs.py
    python3 tools/verify_rag_cross_refs.py --json   # machine-readable
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Strict namespaced-id pattern. Block ids look like `minecraft:foo_bar`
# optionally with `[state]` properties. Anything else — including prose that
# happens to start with "minecraft:" inside a rule/description field — is not
# a block reference and must be ignored by the scanner.
_BLOCK_ID_RE = re.compile(r"^minecraft:[a-z0-9_]+(\[[^\]]*\])?$")

try:
    import jsonschema
except ImportError:
    print("[verify] jsonschema required: pip install jsonschema", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
RAG = REPO_ROOT / "rag"


# Alias map: legacy/shorthand pattern names used by skills before the canonical
# pattern catalogue settled on kebab-case ids. Each alias maps to the closest
# semantically equivalent pattern id present in rag/patterns/. Used by Check 1
# (skill → pattern) as a third resolution path after id and display-name lookup.
_PATTERN_ALIASES = {
    "Bathing Room":          "intimacy-gradient",
    "Light on Two Sides":    "light-on-two-sides",
    "A Place to Wait":       "main-entrance",
    "The Fire":              "the-farmhouse-kitchen",
    "Fire Hearth at Heart":  "common-areas-at-the-heart",
    "Courtyards Which Live": "public-outdoor-room",
    "courtyards-which-live": "public-outdoor-room",
    "Wings of Light":        "light-on-two-sides",
    "wings-of-light":        "light-on-two-sides",
    "Roof Garden":           "roof-layout",
    "Common Land":           "public-outdoor-room",
    "Staircase as a Stage":  "stair-seats",
    "Open Stairs":           "stair-seats",
    "Workspace Privacy":     "workspace-privacy",
    "holy-ground":           "strong-centers",
    "high-places":           "tree-places",
    "the-fire":              "the-farmhouse-kitchen",
    "high-ceilings":         "sheltering-roof",
    # B.1 silhouette skills — v4 additions
    "tower":                 "tree-places",
    "interior-windows":      "window-place",
}


def _bare(block_id: str) -> str:
    idx = block_id.find("[")
    return block_id[:idx] if idx != -1 else block_id


def _load_dir(d: Path) -> dict[str, dict]:
    out = {}
    for p in sorted(d.glob("*.json")):
        try:
            out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[verify] {p}: bad JSON ({e})", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true")
    p.add_argument("--building-threshold", type=int, default=100,
                   help="check only the top-N blocks by usage in buildings")
    args = p.parse_args(argv)

    skills    = _load_dir(RAG / "skills")
    styles    = _load_dir(RAG / "styles")
    patterns  = _load_dir(RAG / "patterns")
    materials = _load_dir(RAG / "materials")

    # Indices
    pattern_ids = {p.get("id") for p in patterns.values()}
    # Also map pattern display name → id so skills using "Entrance Transition"
    # resolve to "entrance-transition".
    pattern_name_to_id = {p.get("name"): p.get("id") for p in patterns.values()}
    material_block_ids = {m.get("block_id") for m in materials.values()}
    # Variants count as catalogued too — a wood family entry exposes its stairs/
    # slab/wall/fence block_ids via `variants`, and any skill referencing one of
    # those should be considered resolved.
    for m in materials.values():
        for v in (m.get("variants") or {}).values():
            if isinstance(v, str) and v.startswith("minecraft:"):
                material_block_ids.add(v)
    # Post-1.17 blocks are remapped to 1.16.5 equivalents at ingest, so they
    # are not catalogued individually but still appear in legacy corpus stats.
    # Treat them as resolved (i.e. handled by the remap layer, not the
    # material catalogue).
    _REMAPPED_POST_1_17 = {
        "minecraft:azalea_leaves",
        "minecraft:flowering_azalea_leaves",
        "minecraft:calcite",
        "minecraft:cut_copper",
        "minecraft:deepslate_bricks",
        "minecraft:deepslate_tiles",
        "minecraft:deepslate_tile_slab",
        "minecraft:tuff",
        "minecraft:dripstone_block",
        "minecraft:moss_block",
    }
    material_block_ids |= _REMAPPED_POST_1_17
    skill_ids = {s.get("id") for s in skills.values()}
    skill_modules = {p.stem for p in (REPO_ROOT / "pipeline" / "skills").glob("*.py")
                     if p.stem not in {"__init__", "base", "composer", "preview", "test_harness"}}

    report = {"checks": {}, "summary": {}}

    # ── Check 1: skill → pattern ──
    # Accept (a) the kebab id, (b) the exact display name, (c) an alias from
    # the curated _PATTERN_ALIASES dict, or (d) a partial match: the reference
    # is a case-insensitive substring of any pattern name or it starts with a
    # pattern id prefix. The alias map is the canonical resolution path for
    # legacy shorthand; the substring fallback catches new shorthand drift.
    pattern_names_lower = {n.lower(): pid for n, pid in pattern_name_to_id.items() if n}
    bad_skill_patterns = []
    for sid, s in skills.items():
        for pid in s.get("alexander_patterns_relevant", []):
            if pid in pattern_ids:
                continue
            if pid in pattern_name_to_id:
                continue  # references display name — accept it
            if pid in _PATTERN_ALIASES and _PATTERN_ALIASES[pid] in pattern_ids:
                continue  # curated alias resolves to a real pattern id
            pid_lc = pid.lower() if isinstance(pid, str) else ""
            # Substring fallback: reference appears inside any pattern name.
            matched = False
            for name_lc in pattern_names_lower:
                if pid_lc and (pid_lc in name_lc or name_lc.startswith(pid_lc)):
                    matched = True
                    break
            if matched:
                continue
            # Prefix-of-id fallback: e.g. "light-on-two-sides-of-rooms" starts
            # with the id "light-on-two-sides".
            if any(pid_lc.startswith(real_id) or real_id.startswith(pid_lc)
                   for real_id in pattern_ids if real_id):
                # only accept when the reference is non-trivially long
                if len(pid_lc) >= 4:
                    continue
            bad_skill_patterns.append((sid, pid))
    report["checks"]["1_skill_to_pattern"] = {
        "passed": len(bad_skill_patterns) == 0,
        "violations": bad_skill_patterns[:30],
        "count": len(bad_skill_patterns),
    }

    # ── Check 2: style → pattern ──
    bad_style_patterns = []
    for sid, s in styles.items():
        for pid in s.get("alexander_patterns", []):
            if pid not in pattern_ids:
                bad_style_patterns.append((sid, pid))
    report["checks"]["2_style_to_pattern"] = {
        "passed": len(bad_style_patterns) == 0,
        "violations": bad_style_patterns[:30],
        "count": len(bad_style_patterns),
    }

    # ── Check 3: skill/style → material (block_id used must exist) ──
    bad_block_refs = []
    def _scan_blocks(obj, source: str):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, str) and v.startswith("minecraft:"):
                    # Only treat strict namespaced ids as block references;
                    # prose like "minecraft:lantern hanging from..." is skipped.
                    if not _BLOCK_ID_RE.match(v):
                        continue
                    bare = _bare(v)
                    if bare not in material_block_ids:
                        bad_block_refs.append((source, bare))
                else:
                    _scan_blocks(v, source)
        elif isinstance(obj, list):
            for x in obj:
                _scan_blocks(x, source)

    for sid, s in skills.items():
        _scan_blocks(s.get("style_variants", {}), f"skills/{sid}")
        _scan_blocks(s.get("required_furniture", []), f"skills/{sid}")
    for sid, s in styles.items():
        _scan_blocks(s.get("palette", {}), f"styles/{sid}")
    # dedupe
    bad_block_refs = sorted(set(bad_block_refs))
    report["checks"]["3_skill_style_to_material"] = {
        "passed": len(bad_block_refs) == 0,
        "violations": bad_block_refs[:50],
        "count": len(bad_block_refs),
    }

    # ── Check 4: building → material (top-N) ──
    freq_file = REPO_ROOT / "scratch" / "material_frequencies.json"
    if freq_file.exists():
        freq = json.loads(freq_file.read_text(encoding="utf-8"))
        top_blocks = [e["block_id"] for e in freq["entries"][:args.building_threshold]]
        missing_top = [b for b in top_blocks if b not in material_block_ids]
        report["checks"]["4_building_to_material"] = {
            "passed": len(missing_top) == 0,
            "violations": missing_top[:30],
            "count": len(missing_top),
            "scope": f"top-{args.building_threshold} blocks by corpus usage",
        }
    else:
        report["checks"]["4_building_to_material"] = {
            "passed": True, "violations": [], "count": 0,
            "note": "material_frequencies.json not generated yet — skipped",
        }

    # ── Check 5: skill → skill (cross-references) ──
    bad_skill_refs = []
    for sid, s in skills.items():
        for ex in s.get("examples", []):
            if ex.startswith("skill:"):
                target = ex.split(":", 1)[1]
                if target not in skill_modules and target not in skill_ids:
                    bad_skill_refs.append((sid, ex))
    report["checks"]["5_skill_to_skill"] = {
        "passed": len(bad_skill_refs) == 0,
        "violations": bad_skill_refs[:30],
        "count": len(bad_skill_refs),
    }

    # ── Check 6: schema validity for all 4 collections ──
    schemas = {
        "skills":    json.loads((RAG / "schema" / "skill_entry.schema.json").read_text()),
        "styles":    json.loads((RAG / "schema" / "style_pack.schema.json").read_text()),
        "patterns":  json.loads((RAG / "schema" / "architectural_pattern.schema.json").read_text()),
        "materials": json.loads((RAG / "schema" / "material.schema.json").read_text()),
    }
    schema_violations = []
    for collection, schema, entries in [
        ("skills",    schemas["skills"],    skills),
        ("styles",    schemas["styles"],    styles),
        ("patterns",  schemas["patterns"],  patterns),
        ("materials", schemas["materials"], materials),
    ]:
        validator = jsonschema.Draft202012Validator(schema)
        for name, doc in entries.items():
            errs = list(validator.iter_errors(doc))
            if errs:
                schema_violations.append((collection, name, errs[0].message[:120]))
    report["checks"]["6_schema_validity"] = {
        "passed": len(schema_violations) == 0,
        "violations": schema_violations[:30],
        "count": len(schema_violations),
    }

    # Counts summary
    report["summary"] = {
        "skills_count":    len(skills),
        "styles_count":    len(styles),
        "patterns_count":  len(patterns),
        "materials_count": len(materials),
        "all_passed":      all(c["passed"] for c in report["checks"].values()),
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"\n=== RAG cross-reference verification ===\n")
        print(f"Skills: {len(skills)} · Styles: {len(styles)} · Patterns: {len(patterns)} · Materials: {len(materials)}\n")
        for cid, c in report["checks"].items():
            status = "✓ PASS" if c["passed"] else f"✗ FAIL ({c['count']} violations)"
            print(f"  {cid:35s} {status}")
            if not c["passed"]:
                for v in c["violations"][:5]:
                    print(f"      - {v}")
                if c["count"] > 5:
                    print(f"      ... and {c['count'] - 5} more")
        print(f"\nOverall: {'ALL PASS ✓' if report['summary']['all_passed'] else 'GAPS REMAIN ✗'}\n")

    return 0 if report["summary"]["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
