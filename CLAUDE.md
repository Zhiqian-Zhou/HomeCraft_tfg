# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

HomeCraft v2 is Pipeline v2 of a TFG (UPC/FIB final degree project) on **text → voxel Minecraft building generation**. v1 lives in a sibling directory `TFGv2/`. The source of truth is `informe_seguimiento.tex` (English LaTeX report).

The architecture is an LLM-agent pipeline backed by a five-collection RAG. This repo contains the **RAG itself**, the **executable skill library**, the **corpus tooling**, and a **viewer** — not the orchestrator agents yet.

**Target version:** Minecraft Java Edition 1.16.5. **No 1.17+ blocks** (deepslate, calcite, cut_copper, azalea, etc.) — the cross-ref verifier blocks them.

## Commands

```bash
pip install -r tools/requirements.txt           # one-time deps

python3 -m pipeline.skills.test_harness         # run 50 skills × 3 styles × 2 sizes (300 invocations)
python3 tools/verify_rag_cross_refs.py          # 6 cross-collection checks, exits 0 iff all pass
python3 tools/verify_rag_cross_refs.py --json   # machine-readable

python3 tools/validate_building.py rag/reference_buildings/processed/*.json   # schema check
python3 tools/audit_dataset.py                                                # corpus stats table
python3 tools/build_material_corpus.py          # → scratch/material_frequencies.json (top-150 blocks)
python3 tools/build_style_palettes.py           # → scratch/style_palettes.json (signature blocks per style)
python3 tools/build_viewer_index.py             # regenerate viewer/data/index.json after adding/removing buildings

python3 tools/score_corpus.py                   # evaluate every reference_building → scratch/corpus_evaluations/
python3 tools/build_retrieval_index.py          # rebuild top-30% filtered TF-IDF index (depends on score_corpus)

python3 -m http.server 8000                     # then open http://localhost:8000/viewer/
```

Run a single skill via the preview API:

```python
from pipeline.skills.preview import export_skill
export_skill('kitchen', style='medieval', size='small')
# → scratch/skill_previews/kitchen__medieval__small.json (openable in viewer)
```

## Architecture — big picture

### RAG (`rag/`): five collections, all schema-backed

| Code | Folder | Schema | What it stores |
|---|---|---|---|
| A | `skills/` | `skill_entry.schema.json` | 50 skill entries (rooms / structural / exterior) |
| B | `styles/` | `style_pack.schema.json` | 10 style packs (medieval, fantasy, modern, …) |
| C | `patterns/` | `architectural_pattern.schema.json` | 29 Christopher Alexander patterns w/ verified citations |
| D | `materials/` | `material.schema.json` | 182 Minecraft 1.16.5 blocks w/ properties |
| E | `reference_buildings/` | `reference_building.schema.json` | 2,746 air-stripped buildings as `{x,y,z,palette_idx}` voxels |

**Retrieval contract** (see `rag/README.md`): subgoal agents query **A + E together**. A and E share `tags.category` and `tags.style` so one filter spans both. C is queried for Alexander-based justification; B fixes the palette in design phase; D resolves block IDs.

### Skill library (`pipeline/skills/`): AST → composer → voxels

Each skill is **a Python module + a JSON entry**, paired by ID:
- `pipeline/skills/<id>.py` exposes `build(aabb, materials, style, **kwargs) -> list[Op]` returning AST ops (defined in `base.py`).
- `rag/skills/<id>.json` is the searchable metadata (description, dimensions, furniture, pattern refs, style variants).

The `composer.py` materializes ops to a voxel list with **"later wins" dedupe** + air-stripping (no `minecraft:air` in palette or voxels — 88% storage saving, project-wide convention). `preview.py` wraps the voxel list as a ReferenceBuilding JSON so any skill output drops directly into the viewer.

Skill discovery is lazy: `from pipeline.skills import get_skill, list_skills`. Modules `base`, `composer`, `preview`, `test_harness` are infrastructure, not skills.

**Coordinate convention** (`base.py`): x=width, y=height (up), z=depth. AABB is half-open: `AABB(0,0,0, 5,4,5)` = 5×4×5 building.

**Placeholder convention**: `required_furniture` items like `@bed`, `@carpet`, `@stairs[facing=…]` resolve via `style_variants.palette_overrides`. Bare block IDs in furniture lists that don't exist as catalogued materials will fail the cross-ref verifier.

### Cross-reference verifier (`tools/verify_rag_cross_refs.py`)

Six checks must all pass:
1. skill → pattern (kebab-id, display name, or curated alias map)
2. style → pattern
3. skill/style → material (every `minecraft:foo` referenced must be catalogued in D, or be in the 1.17+ remap whitelist)
4. building → material (top-N corpus blocks must be catalogued)
5. skill → skill (cross-references resolve to a real Python module)
6. schema validity (every JSON in A/B/C/D validates)

The verifier has a `_PATTERN_ALIASES` dict for legacy shorthand and a `_REMAPPED_POST_1_17` set treating known-remapped post-1.16 blocks as resolved. **Touch these when you add a new alias or migrate a block** — don't loosen the regex.

### Viewer (`viewer/`)

Three.js + InstancedMesh per palette index, textures from `mcasset.cloud/1.16.5/`. See `viewer/README.md` for keybinds and known limitations (no per-block geometry — stairs/slabs render as cubes; ~40 blockstates handled). Must be served over HTTP (`python3 -m http.server 8000`), not `file://`.

### Tools (`tools/`)

- **Ingest scripts** (`ingest_*.py`): one per upstream source (3D-Craft, HF datasets, schematic dumps). Each appends to `rag/reference_buildings/raw/manifest.jsonl` and emits processed JSONs only when license is identified.
- **Corpus analysis**: `build_material_corpus.py`, `build_style_palettes.py`, `audit_dataset.py` — all read `rag/reference_buildings/processed/` and write to `scratch/`.
- **Validators**: `validate_building.py`, `verify_rag_cross_refs.py`.

## Project conventions

**Licensing (hybrid policy):** everything ingested lands in `rag/reference_buildings/raw/` with license annotated in `manifest.jsonl`. **Only license-known assets move to `processed/`** and ship in this repo. `raw/` is gitignored (license-mixed, not redistributable). See `PROCESSING.md` for the per-source audit.

**Markdown language:** all project markdowns in **Spanish**. Only `informe_seguimiento.tex` (the dissertation) stays in English. This is a deliberate user preference.

**Data provenance:** `rag/PROVENANCE_AUDIT.md` documents what was verified against primary sources (patternlanguage.cc for patterns, minecraft.wiki for materials, corpus stats for styles) vs. what remains LLM synthesis (skill geometries, signature elements, ratios). Keep this distinction explicit when modifying RAG content.

**`scratch/` is reproducible.** Anything there can be regenerated from `tools/`. It's gitignored. Don't write source content there.

**Adding a new skill** requires four things to stay aligned: the Python module (`build()`), the JSON entry (schema-valid), the harness must pass for it (3 styles × 2 sizes), and the cross-ref verifier must still hit 6/6.
