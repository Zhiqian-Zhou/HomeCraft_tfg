"""Aleatoriedad determinista y reproducible (FIX 5).

Un seed se deriva del gen_id en run.py y se propaga a las etapas deterministas
(skills de sala, trim, massing, exterior). Mismo seed → mismo edificio
(reproducible); seeds distintos (gen_id distinto por run) → edificios distintos
(variabilidad). NO usa el RNG global del proceso, así que es thread-safe en el
gym (10 builds en paralelo).
"""
from __future__ import annotations

import hashlib
import random


def seed_from(*keys) -> int:
    """Entero estable a partir de claves arbitrarias (str/int)."""
    h = hashlib.sha1("|".join(str(k) for k in keys).encode("utf-8")).hexdigest()
    return int(h[:12], 16)


def rng_for(seed, *keys) -> random.Random:
    """random.Random aislado, sembrado por (seed, *keys). Reproducible."""
    return random.Random(seed_from(seed, *keys))


def variant_index(seed, n: int, *keys) -> int:
    """Índice de variante en [0, n) determinista por (seed, *keys)."""
    if n <= 1:
        return 0
    return seed_from(seed, *keys) % n
