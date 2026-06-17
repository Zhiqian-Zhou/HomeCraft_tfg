"""Ablation toggle for the deterministic-fallback experiment.

HOMECRAFT_FALLBACK_MODE=on  -> re-enable the deterministic fallbacks that were
                              removed in a9875e7 (pipeline WITH fallbacks).
HOMECRAFT_FALLBACK_MODE=off -> current HEAD behaviour: fail loudly (default).

The flag is read at *call time* (not cached at import) so a single process /
test can flip os.environ between builds.
"""
from __future__ import annotations

import os


def fallback_enabled() -> bool:
    return os.environ.get("HOMECRAFT_FALLBACK_MODE", "off").strip().lower() == "on"
