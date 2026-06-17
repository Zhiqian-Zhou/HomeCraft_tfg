"""Skill library — each module exposes a `build(aabb, materials, style, **kwargs)`
function that returns a list of AST `Op` objects (defined in `base.py`).

The composer (`composer.py`) materializes the AST to a list of
`(x, y, z, block_id)` voxels. `preview.py` wraps that voxel list in a
ReferenceBuilding JSON so each skill output can be opened in the viewer.

Skill registration is lazy: callers do `from pipeline.skills import get_skill`
which loads the module on demand. Use `list_skills()` to enumerate.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Callable

from .base import AABB, Materials, Op  # re-exports

_SKILLS_DIR = Path(__file__).resolve().parent

# Modules in this directory that are infrastructure, not skills.
_INFRA = {"base", "composer", "preview", "test_harness", "eaves", "params",
          "__init__"}


def list_skills() -> list[str]:
    """Return the available skill module names (without `.py`)."""
    out = []
    for info in pkgutil.iter_modules([str(_SKILLS_DIR)]):
        if info.name in _INFRA or info.name.startswith("_"):
            continue
        out.append(info.name)
    return sorted(out)


def get_skill(name: str) -> Callable:
    """Import the skill module and return its `build` callable."""
    mod = importlib.import_module(f"pipeline.skills.{name}")
    fn = getattr(mod, "build", None)
    if not callable(fn):
        raise AttributeError(f"skill '{name}' has no callable build()")
    return fn


__all__ = ["AABB", "Materials", "Op", "list_skills", "get_skill"]
