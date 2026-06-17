# Reference building corpus (Collection E)

Real Minecraft buildings, normalised to Minecraft 1.16.5 and stored as air-stripped voxel
arrays. Each building is one JSON file under `processed/` following
[`../schema/reference_building.schema.json`](../schema/reference_building.schema.json):

```json
{
  "id": "...",
  "source": "github | synthetic | ...",
  "source_url": "https://...",
  "license": "MIT",
  "tags": { "category": "residential", "style": ["medieval"], "size_bucket": "large" },
  "block_palette": { "0": "minecraft:oak_planks", "1": "minecraft:cobblestone" },
  "voxels": [[x, y, z, palette_idx], ...],
  "bot_decomposition": { ... }
}
```

## What ships here

The full corpus used in the project is ~2,700 buildings of **mixed provenance** — most carry
research / non-commercial (CC-BY-NC) or unknown licenses and are therefore **not
redistributable**. To keep this repository lightweight and license-clean, only the
**61 MIT-licensed buildings** are included as a working sample.

That sample is still diverse enough to exercise the whole stack:

- **11 styles** — chinese, medieval, fantasy, egyptian, viking, futuristic, industrial,
  rustic, mediterranean, japanese, gothic.
- **9 categories** — residential, castle, temple, tower, ruin, lighthouse, windmill,
  monument, other.

It is enough to run the browser viewer, the retrieval index, and the corpus tooling end-to-end.

## Rebuilding the corpus from your own sources

Use the ingest scripts in [`../../tools/`](../../tools/) to add buildings from upstream sources,
respecting their licenses:

```bash
python3 tools/ingest_schematic.py  path/to/build.schem
python3 tools/ingest_nbt.py        path/to/structure.nbt
python3 tools/ingest_hf_tuplelist.py <hf-dataset>
python3 tools/validate_building.py rag/reference_buildings/processed/*.json
python3 tools/build_viewer_index.py     # refresh the viewer index
```

See [`../PROVENANCE_AUDIT.md`](../PROVENANCE_AUDIT.md) for the per-source license audit.
