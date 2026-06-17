"""Tests for the robust qualitative critique pipeline in evaluator.py.

Covers the linter, the deterministic fallback template, and the
LLM-call wrapper (mocked — no real API consumption).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from pipeline.agents import evaluator as ev


# A well-formed mock critique (Spanish, ~95 words, no numbers, no markdown).
_GOOD_CRITIQUE = (
    "El edificio resulta sólido en su evaluación global. Destaca el "
    "gradiente de intimidad bien resuelto, con dormitorios al fondo y "
    "áreas comunes próximas a la entrada, lo que refuerza el ritual "
    "doméstico esperable en una cabaña medieval. El techo extendido "
    "ofrece sensación de refugio y los muros con doble luz garantizan "
    "habitabilidad diurna durante toda la jornada. Como área de mejora, "
    "el borde del edificio podría tratarse con un porche perimetral o "
    "un cambio de material en el umbral para suavizar la transición al "
    "jardín circundante sin alterar la coherencia material existente "
    "del conjunto residencial propuesto en esta iteración."
)

_REPORT = {
    "composite": {"category": "aceptable", "overall": 0.62},
    "physical": {
        "structural_integrity": {"score": 0.92, "notes": "ok"},
        "light_coverage":       {"score": 0.40, "notes": "dark west wing"},
    },
    "alexander": {
        "intimacy_gradient":  {"score": 0.30, "notes": "bedrooms at entry"},
        "sheltering_roof":    {"score": 0.88, "notes": "good overhang"},
    },
}


def setup_function(_):
    """Clear the LRU cache so tests don't contaminate one another."""
    ev._cached_critique_call.cache_clear()


# ── Happy path ────────────────────────────────────────────────────────────


def test_llm_ok_returns_text():
    """Well-formed LLM output passes the linter and is returned as-is."""
    with patch.object(ev, "_cached_critique_call", return_value=_GOOD_CRITIQUE):
        out = ev._generate_critique(_REPORT)
        assert out == _GOOD_CRITIQUE


# ── Linter rejection scenarios ────────────────────────────────────────────


def test_llm_empty_falls_back_to_template():
    """Empty LLM output triggers the deterministic fallback template."""
    with patch.object(ev, "_cached_critique_call", return_value=""):
        out = ev._generate_critique(_REPORT)
        assert out
        assert out.startswith("El edificio resulta")  # template signature


def test_llm_with_numbers_rejected_then_fallback():
    """Output containing numeric scores is rejected; template wins."""
    bad = "El edificio puntúa 0.45 lo que es bajo. " + _GOOD_CRITIQUE
    with patch.object(ev, "_cached_critique_call", return_value=bad):
        out = ev._generate_critique(_REPORT)
        assert "0.45" not in out


def test_llm_too_short_falls_back():
    """Sub-60-word output is rejected; template returned (>=10 words)."""
    with patch.object(ev, "_cached_critique_call", return_value="Edificio aceptable."):
        out = ev._generate_critique(_REPORT)
        assert len(out.split()) >= 10


def test_llm_too_long_falls_back():
    """200+ word output is rejected and template substituted."""
    long_text = " ".join(["palabra"] * 250)
    with patch.object(ev, "_cached_critique_call", return_value=long_text):
        out = ev._generate_critique(_REPORT)
        # Template never repeats "palabra palabra palabra".
        assert "palabra palabra palabra" not in out


def test_llm_markdown_rejected():
    """Output containing markdown bullets is rejected."""
    bad = "- " + _GOOD_CRITIQUE
    with patch.object(ev, "_cached_critique_call", return_value=bad):
        out = ev._generate_critique(_REPORT)
        # Markdown got stripped because template kicked in (no leading "- ").
        assert not out.lstrip().startswith("- ")


# ── Cache idempotency ──────────────────────────────────────────────────────


def test_cache_idempotency():
    """Two calls with the same payload should hit the LLM only once."""
    with patch("pipeline.agents.evaluator.call_llm",
               create=True, return_value=_GOOD_CRITIQUE):
        # We mock at the llm-module level since the cached wrapper imports it.
        with patch("pipeline.agents.llm.call_llm",
                   return_value=_GOOD_CRITIQUE) as mock:
            ev._generate_critique(_REPORT)
            ev._generate_critique(_REPORT)
            assert mock.call_count == 1  # second hit cached


# ── Template-only paths ────────────────────────────────────────────────────


def test_template_mentions_weak_metrics():
    """Template surfaces low-scoring metrics by name."""
    out = ev._critique_template(_REPORT)
    # `intimacy_gradient` scored 0.30 → must appear as weakness.
    assert "gradiente de intimidad" in out
    # Template MUST NOT contain numeric scores.
    assert not ev._CRITIQUE_NUMERIC_RX.search(out)


def test_template_trivial_when_no_scores():
    """Template handles empty metrics gracefully."""
    out = ev._critique_template({"composite": {"category": "aceptable"},
                                  "physical": {}, "alexander": {}})
    assert out.startswith("El edificio resulta aceptable")
    assert not ev._CRITIQUE_NUMERIC_RX.search(out)
