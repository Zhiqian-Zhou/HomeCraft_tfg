"""Alexander-flavored geometric feature extraction for reference buildings.

DEPRECATED (v2.6, 2026-05-26): No longer used by the retriever. The
Stage-6 evaluator's composite score pre-filters the corpus to the top-30%
in `tools/build_retrieval_index.py`; retrieval is then pure TF-IDF over
that filtered subset. This module is retained for diagnostic introspection
— call `extract_features(doc)` directly if you need the 7-dim geometric
vector for a single building. Tests in tests/test_retriever.py do NOT
exercise this module.

Historical context: this module computed a 7-dim feature vector per
building used in a blended retriever score
(`alpha*tfidf + (1-alpha)*alex`). That signal turned out to be weaker
than the Stage-6 composite, which captures architectural quality across
18 metrics rather than geometric proximity to a parsed prompt.

The corpus has NO room labels (bot_decomposition is null in all sampled
buildings) — so semantic features ("intimacy gradient", "common areas at
the heart") are NOT extractable mechanically. We compute the subset of
features that ARE recoverable from voxels + palette + metadata_quality:

    size_log        normalized log volume (W*H*D)        — proxy for "scale"
    h_w_ratio       height / max(width, depth)            — proxy for "tower vs spread"
    door_count_log  log(1 + count of door voxels)         — proxy for "entry-readability"
    glass_density   (glass voxels) / total voxels         — proxy for "light on two sides"
    furniture_dens  furniture_blocks / total voxels       — proxy for "lived-in"
    palette_div     len(palette) / max(palette in corpus) — proxy for "levels of scale"
    populated       1.0 if interior_populated else 0.0    — coarse interior signal

All features are in [0, 1] after normalization. The retriever computes
similarity between the query target vector and the building vector as
1 - L1_distance/7.

This is documented honest: with no room-labels in RAG-E, semantic Alexander
features are out of scope. The TFG defends this as a corpus limitation.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

# Heuristic ceiling for log-normalization. Set so the largest reasonable
# building maps near 1.0; xlarge buildings cap at 1.0.
_VOLUME_CEIL = 32 * 32 * 32          # 32^3 → 1.0
_DOOR_CEIL = math.log(1 + 12)        # ~12 doors max signal → 1.0
_PALETTE_CEIL = 60                   # 60-block palette → 1.0


FEATURE_NAMES = (
    "size_log",
    "h_w_ratio",
    "door_count_log",
    "glass_density",
    "furniture_density",
    "palette_div",
    "populated",
)


def _is_glass(block_id: str) -> bool:
    return "glass" in block_id


def _is_door(block_id: str) -> bool:
    return "_door" in block_id


def extract_features(doc: dict) -> dict[str, float]:
    """Return the 7-dim Alexander geom feature vector for a building doc.

    Robust to missing optional fields; returns zeros for unavailable signals.
    """
    bb = doc.get("bounding_box", {}).get("size", [1, 1, 1])
    W, H, D = bb[0], bb[1], bb[2]
    volume = max(W * H * D, 1)
    size_log = min(math.log(volume) / math.log(_VOLUME_CEIL), 1.0)

    h_w_ratio = min(H / max(max(W, D), 1), 2.0) / 2.0  # clamp to 0..1

    palette = doc.get("block_palette", {})
    voxels = doc.get("voxels", [])
    total = max(len(voxels), 1)

    # Index palette idx → block_id for fast voxel lookup
    idx_to_bare = {}
    for k, v in palette.items():
        bare = v.split("[")[0] if "[" in v else v
        try:
            idx_to_bare[int(k)] = bare
        except ValueError:
            continue

    door_count = 0
    glass_count = 0
    for vx in voxels:
        if len(vx) >= 4:
            bare = idx_to_bare.get(vx[3], "")
            if _is_door(bare):
                door_count += 1
            elif _is_glass(bare):
                glass_count += 1

    door_count_log = min(math.log(1 + door_count) / _DOOR_CEIL, 1.0)
    glass_density = min(glass_count / total, 1.0)

    mq = doc.get("metadata_quality") or {}
    furniture_blocks = mq.get("furniture_blocks", 0) or 0
    furniture_density = min(furniture_blocks / total, 1.0)
    populated = 1.0 if mq.get("interior_populated") else 0.0

    palette_div = min(len(palette) / _PALETTE_CEIL, 1.0)

    return {
        "size_log":           size_log,
        "h_w_ratio":          h_w_ratio,
        "door_count_log":     door_count_log,
        "glass_density":      glass_density,
        "furniture_density":  furniture_density,
        "palette_div":        palette_div,
        "populated":          populated,
    }


def vector(features: dict[str, float]) -> list[float]:
    """Order-stable list view of a features dict (matches FEATURE_NAMES)."""
    return [features[name] for name in FEATURE_NAMES]


# Keyword → target shift map for prompt → ideal Alexander vector
# Each entry: keyword → dict of {feature_name: target_value_when_matched}
# Multiple matches blend toward an average.
_KEYWORD_BIAS: dict[str, dict[str, float]] = {
    # Scale
    "mansion":    {"size_log": 0.9},
    "manor":      {"size_log": 0.85},
    "castle":     {"size_log": 0.9, "door_count_log": 0.6},
    "palace":     {"size_log": 0.95},
    "great":      {"size_log": 0.7},
    "large":      {"size_log": 0.8},
    "big":        {"size_log": 0.8},
    "huge":       {"size_log": 0.95},
    "small":      {"size_log": 0.3},
    "tiny":       {"size_log": 0.2},
    "cottage":    {"size_log": 0.3, "populated": 1.0},
    "cabin":      {"size_log": 0.35},
    "hut":        {"size_log": 0.2},
    # Verticality
    "tower":      {"h_w_ratio": 0.9, "size_log": 0.5},
    "tall":       {"h_w_ratio": 0.8},
    "high":       {"h_w_ratio": 0.7},
    "skyscraper": {"h_w_ratio": 0.95, "size_log": 0.7},
    "lighthouse": {"h_w_ratio": 0.85},
    "bungalow":   {"h_w_ratio": 0.15},
    "single":     {"h_w_ratio": 0.15},      # "single-floor", "single-story"
    "flat":       {"h_w_ratio": 0.2},
    # Light
    "luminous":   {"glass_density": 0.4},
    "bright":     {"glass_density": 0.3},
    "airy":       {"glass_density": 0.35},
    "sunny":      {"glass_density": 0.3},
    "dark":       {"glass_density": 0.0},
    # Interior
    "cozy":       {"furniture_density": 0.15, "populated": 1.0},
    "homey":      {"furniture_density": 0.15, "populated": 1.0},
    "lived":      {"populated": 1.0},
    "furnished":  {"furniture_density": 0.2, "populated": 1.0},
    "habitable":  {"populated": 1.0},
    # Entry
    "grand":      {"door_count_log": 0.5, "size_log": 0.7},
    "fortified":  {"door_count_log": 0.6, "size_log": 0.7},
    "gated":      {"door_count_log": 0.5},
}


def query_target_vector(prompt: str) -> dict[str, float]:
    """Build a 7-dim target Alexander vector from a user prompt.

    Strategy: start from a neutral vector (all 0.5), then for each keyword
    match in `_KEYWORD_BIAS`, blend the matched targets in (simple average).
    """
    base = {name: 0.5 for name in FEATURE_NAMES}
    blends: dict[str, list[float]] = {name: [] for name in FEATURE_NAMES}

    lp = prompt.lower()
    for kw, shifts in _KEYWORD_BIAS.items():
        if kw in lp:
            for name, val in shifts.items():
                blends[name].append(val)

    out = {}
    for name in FEATURE_NAMES:
        vals = blends[name]
        if vals:
            out[name] = sum(vals) / len(vals)
        else:
            out[name] = base[name]
    return out


def similarity(building_vec: list[float], target_vec: list[float]) -> float:
    """Return similarity in [0, 1] between two 7-dim feature vectors.

    Uses 1 - L1_distance / N (where N = 7) so each feature contributes
    equally. Values >= 0.5 are "fairly aligned"; >= 0.8 are "very aligned".
    """
    if len(building_vec) != len(target_vec):
        raise ValueError("vectors must have same length")
    dist = sum(abs(a - b) for a, b in zip(building_vec, target_vec))
    return max(0.0, 1.0 - dist / len(building_vec))
