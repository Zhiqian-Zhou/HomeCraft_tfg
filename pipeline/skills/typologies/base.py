"""Contract for typology-level skills (named, opinionated building components).

A typology is a higher-level catalog entry over the atomic skills in
`pipeline/skills/`. Where an atomic skill is a primitive ("chimney",
"balcony"), a typology is a stylistically and geometrically committed
variant ("Norman Square Keep", "Italian Campanile", "Mansard Roof").

Each typology module exposes:
    METADATA: TypologyMetadata     # catalog entry the LLM reads
    def build(aabb, materials, style, **kwargs) -> list[Op]

The build contract is identical to the atomic-skill contract in
`pipeline/skills/base.py`. The composer materializes Ops into voxels with
"later wins" dedupe + air filter. Material placeholders ("@primary",
"@accent", "@roof", ...) are resolved at compile time against the passed
`Materials` object.

Design notes
------------
* `style_affinities` and `scale_affinities` are filters the LLM-side
  chooser uses to present a stratified candidate list. Empty lists mean
  "fits anywhere".
* `composability` is a free-form list of typology / skill names that
  pair well at the architectural level (e.g. a Norman Keep composes with
  "skill_arrow_loop_cross").
* `mc_version_min` is informational — the per-op block IDs are still
  audited by `tools/verify_rag_cross_refs.py` at RAG-build time.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..base import AABB, Materials, Op  # noqa: F401 (re-exports for convenience)


@dataclass(frozen=True)
class TypologyMetadata:
    """Catalog entry for one named, opinionated typology."""
    name: str                                    # "norman_keep"
    kind: str                                    # "tower" | "roof" | "window" | "garden"
    title: str                                   # "Norman Square Keep"
    description: str                             # 1-3 sentences, indexable by RAG
    style_affinities: list[str] = field(default_factory=list)
    scale_affinities: list[str] = field(default_factory=list)
    typical_footprint: tuple[int, int, int] = (10, 10, 10)
    composability: list[str] = field(default_factory=list)
    cost_blocks: int = 100
    mc_version_min: str = "1.16.5"


class Typology(ABC):
    """Optional class-based typology — most typology modules use a
    module-level `build()` function and a module-level `METADATA` constant.

    The class form is for typologies that want shared state across calls."""
    metadata: TypologyMetadata

    @abstractmethod
    def build(self, aabb: AABB, materials: Materials, style: str,
              **kwargs) -> list[Op]:
        ...
