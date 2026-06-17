"""Tests for category-aware silhouette selection + grand-prompt scaling.

These target the variety fixes: temple/palace prompts must surface the grand
temple/wing silhouettes (not a generic villa), and grand prompts must scale the
footprint toward the silhouette max.
"""
from __future__ import annotations

from pipeline.agents import global_designer as G
from pipeline.agents import retriever as R


# ── category inference ──

def test_infer_category_temple():
    for p in ["A meditation temple with a prayer hall",
              "a small wayside shrine", "a gothic cathedral with a nave",
              "an open-air pavilion"]:
        assert G._infer_category(p) == "temple", p


def test_infer_category_monument_for_palace():
    assert G._infer_category("A grand Renaissance palace") == "monument"
    assert G._infer_category("a sprawling manor estate") == "monument"


def test_infer_category_specific_before_generic():
    # "temple" wins over the generic "house"/"hall" words
    assert G._infer_category("a temple that also serves as a house") == "temple"
    # castle before tower
    assert G._infer_category("a castle keep with a tower") == "castle"


def test_infer_category_residential_and_none():
    assert G._infer_category("a cozy cottage") == "residential"
    assert G._infer_category("a nondescript structure") is None


def test_is_grand():
    assert G._is_grand("a GRAND palatial hall")
    assert G._is_grand("an expansive cathedral")
    assert not G._is_grand("a modest little cottage")


# ── silhouette ranking honours the category boost ──

def test_silhouette_boost_surfaces_temple_silhouettes():
    hits = R.retrieve_skills("global_silhouette", k=4,
                             query="meditation temple prayer hall eaves",
                             boost_category="temple")
    ids = [h["id"] for h in hits]
    # every top hit must be temple-applicable
    sils = R._skills()
    by_id = {e["id"]: e for e in sils.entries}
    for hid in ids:
        e = by_id[hid]
        appl = e.get("applicable_to") or []
        cat = (e.get("tags") or {}).get("category")
        assert "temple" == cat or "temple" in appl, (hid, cat, appl)


def test_silhouette_boost_changes_order_vs_unboosted():
    q = "a symmetrical palace with grand facade and ballroom"
    plain = [h["id"] for h in R.retrieve_skills("global_silhouette", k=6, query=q)]
    boosted = [h["id"] for h in R.retrieve_skills("global_silhouette", k=6,
                                                  query=q, boost_category="monument")]
    # the boosted list must lead with monument-applicable silhouettes
    sils = {e["id"]: e for e in R._skills().entries}
    top = sils[boosted[0]]
    assert "monument" in (top.get("applicable_to") or []) \
        or (top.get("tags") or {}).get("category") == "monument"


# ── grand prompts scale the footprint toward the silhouette max ──

def _doc(sil_id, bld):
    return {"schema_version": "v4", "silhouette_id": sil_id, "style": "renaissance",
            "category": "monument", "site_aabb": [0, 0, 0, bld[3] + 2, 16, bld[5] + 2],
            "building_aabb": list(bld), "silhouette_parameters": {},
            "height_intent": {"per_floor_height": 5, "roof_style": "hip"},
            "floors": [{"index": 0, "y0": 0, "y1": 5}, {"index": 1, "y0": 5, "y1": 10}],
            "alexander_rationale": [{"pattern_id": "x", "applied_to": ["roof"],
                                     "rationale": "y"}]}


def test_grand_prompt_no_longer_scales_footprint(capsys):
    """2026-05-30 RELAJADO: el auto-scale "grand prompt → silhouette.max" se
    eliminó. El LLM decide la dimensión XZ y normalize sólo logea a stderr.
    (Y se sigue ajustando para garantizar 2 celdas de headroom de tejado.)
    """
    original = [0, 0, 0, 20, 10, 18]
    doc = _doc("e-wing-silhouette", list(original))
    G._normalize_v4(doc, "A grand expansive palace", "A grand expansive palace")
    b = doc["building_aabb"]
    # XZ left UNCHANGED — no more auto-scale to silhouette max
    assert b[3] - b[0] == 20 and b[5] - b[2] == 18, b
    # a diagnostic was emitted
    captured = capsys.readouterr()
    assert "grand" in captured.err or "palace" in captured.err


def test_non_grand_prompt_leaves_footprint():
    doc = _doc("e-wing-silhouette", [0, 0, 0, 20, 10, 18])
    G._normalize_v4(doc, "A modest house", "A modest house")
    b = doc["building_aabb"]
    assert (b[3] - b[0]) == 20 and (b[5] - b[2]) == 18, b
