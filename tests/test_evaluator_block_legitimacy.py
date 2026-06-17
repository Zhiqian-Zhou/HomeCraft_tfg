"""Tests for `_block_legitimacy` (refined plan).

Spec: scratch/evaluation_robustness/block_legitimacy.refined.md
Five tests covering: 1.16 valid palette, creative-only penalty,
deepslate post-1.16 penalty, mossy_cobblestone false-positive regression,
and dict|list input shape.
"""
from __future__ import annotations

from pipeline.agents.evaluator import _block_legitimacy


def test_block_legitimacy_all_valid_1_16():
    doc = {"block_palette": ["minecraft:oak_planks", "minecraft:stone"]}
    assert _block_legitimacy(doc)["score"] == 1.0


def test_block_legitimacy_barrier_penalised():
    doc = {"block_palette": ["minecraft:barrier", "minecraft:stone"]}
    out = _block_legitimacy(doc)
    assert out["score"] == 0.5
    assert "minecraft:barrier" in out["creative_only_blocks"]


def test_block_legitimacy_deepslate_penalised():
    doc = {"block_palette": ["minecraft:deepslate_tiles",
                             "minecraft:cobbled_deepslate"]}
    out = _block_legitimacy(doc)
    assert out["score"] == 0.0
    assert len(out["post_1_16_blocks"]) == 2


def test_block_legitimacy_mossy_cobblestone_native():
    # Regresión: el prefijo poroso "moss" rechazaba mossy_cobblestone /
    # mossy_stone_bricks (ambos 1.16-nativos). El fix los acepta.
    doc = {"block_palette": ["minecraft:mossy_cobblestone",
                             "minecraft:mossy_stone_bricks"]}
    assert _block_legitimacy(doc)["score"] == 1.0


def test_block_legitimacy_accepts_list_and_dict():
    as_list = {"block_palette": ["minecraft:oak_planks"]}
    as_dict = {"block_palette": {"0": "minecraft:oak_planks"}}
    assert _block_legitimacy(as_list)["score"] == 1.0
    assert _block_legitimacy(as_dict)["score"] == 1.0
