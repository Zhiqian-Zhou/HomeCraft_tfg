"""Typology catalog — named, opinionated building components ported from TFGv2.

Each typology module exposes:
    METADATA: TypologyMetadata
    def build(aabb, materials, style, **kwargs) -> list[Op]

Discovery is lazy via `importlib`, mirroring the pattern in
`pipeline/skills/__init__.py:37-43`. Typologies are NOT registered in any
central file; just drop a new module into this directory and it becomes
discoverable by `get_typology(name)` and `list_typologies()`.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Callable

from .base import AABB, Materials, Op, Typology, TypologyMetadata  # re-exports

_TYPOLOGY_DIR = Path(__file__).resolve().parent

# Modules in this directory that are infrastructure, not typologies.
_INFRA = {"base", "__init__"}


def list_typologies() -> list[str]:
    """Return the available typology module names (without `.py`)."""
    out: list[str] = []
    for info in pkgutil.iter_modules([str(_TYPOLOGY_DIR)]):
        if info.name in _INFRA or info.name.startswith("_"):
            continue
        out.append(info.name)
    return sorted(out)


def get_typology(name: str) -> Callable:
    """Import the typology module and return its `build` callable."""
    mod = importlib.import_module(f"pipeline.skills.typologies.{name}")
    fn = getattr(mod, "build", None)
    if not callable(fn):
        raise AttributeError(f"typology '{name}' has no callable build()")
    return fn


def get_metadata(name: str) -> TypologyMetadata:
    """Import the typology module and return its `METADATA` constant."""
    mod = importlib.import_module(f"pipeline.skills.typologies.{name}")
    meta = getattr(mod, "METADATA", None)
    if meta is None:
        raise AttributeError(f"typology '{name}' has no METADATA constant")
    return meta


def filter_by(kind: str | None = None,
              style: str | None = None,
              scale: str | None = None) -> list[str]:
    """Return typology names whose metadata matches all provided filters.

    Affinity lists with no entries are treated as "fits anywhere" and pass
    every filter — this lets generic typologies stay available.
    """
    names: list[str] = []
    for n in list_typologies():
        meta = get_metadata(n)
        if kind is not None and meta.kind != kind:
            continue
        if style is not None and meta.style_affinities \
                and style not in meta.style_affinities:
            continue
        if scale is not None and meta.scale_affinities \
                and scale not in meta.scale_affinities:
            continue
        names.append(n)
    return names


__all__ = [
    "AABB", "Materials", "Op", "Typology", "TypologyMetadata",
    "list_typologies", "get_typology", "get_metadata", "filter_by",
]
