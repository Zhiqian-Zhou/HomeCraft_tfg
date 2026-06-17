"""The 10 diverse prompts the gym uses for each iteration.

Synthesized from Pre-A research agents (2026-05-28). Each prompt:
  - covers a distinct style + culture + building category combination
  - is 15-25 words long, avoiding scale adjectives (small/tall) for ambiguity
  - mentions 2-3 specific room types
  - has an expected silhouette family that the gym can sanity-check
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class GymPrompt:
    slot: str                       # short slug, used as gen_id suffix
    prompt: str                     # the actual user prompt
    expected_silhouettes: list[str] # acceptable silhouette skill ids
    expected_floors: str            # range or single int as string
    rationale: str                  # why this prompt is in the cohort


GYM_PROMPTS: list[GymPrompt] = [
    GymPrompt(
        slot="medieval-cottage",
        prompt=("A rural cottage with a central hearth room, a kitchen with "
                 "a shuttered window, and a bedroom upstairs with a low "
                 "oak-beamed ceiling."),
        expected_silhouettes=["gable-cottage-silhouette",
                                "longhouse-silhouette",
                                "gambrel-barn-silhouette"],
        expected_floors="1-2",
        rationale=("Rural domestic baseline. 'upstairs' signals 2 floors; "
                    "3 distinct rooms test room_role coverage."),
    ),
    GymPrompt(
        slot="mediterranean-villa",
        prompt=("Mediterranean villa with central courtyard, featuring "
                 "kitchen, dining terrace, and study with arched windows."),
        expected_silhouettes=["u-courtyard-silhouette",
                                "atrium-modern-silhouette",
                                "hip-roof-villa-silhouette"],
        expected_floors="1-2",
        rationale=("Tests courtyard silhouettes + arched openings (lintel-"
                    "arched wall_fitting). Patio is the defining feature."),
    ),
    GymPrompt(
        slot="modern-minimalist",
        prompt=("Clean-lined single-family home with open-concept living "
                 "space flowing into minimalist master suite, flat roof, "
                 "neutral materials."),
        expected_silhouettes=["monolith-modern-silhouette",
                                "atrium-modern-silhouette",
                                "stilt-house-silhouette"],
        expected_floors="1-2",
        rationale=("Tests flat-parapet wall_fitting + open-plan-loft layout; "
                    "low-ornament style stresses material_consistency."),
    ),
    GymPrompt(
        slot="fantasy-tower",
        prompt=("Wizard's tower with circular footprint, four floors "
                 "featuring study, bedroom, spiral staircase, and rooftop "
                 "observatory for stargazing."),
        expected_silhouettes=["tower-cylinder-silhouette",
                                "tower-square-silhouette"],
        expected_floors="3-5",
        rationale=("Tests vertical stair coherence across 4 floors + "
                    "central-core-layout; high alexander.sheltering_roof "
                    "challenge."),
    ),
    GymPrompt(
        slot="japanese-temple",
        prompt=("A two-story meditation temple with a tatami prayer room, "
                 "elevated entrance gate, and gently sloped roof eaves "
                 "extending over wooden verandas."),
        expected_silhouettes=["pagoda-stack-silhouette",
                                "hip-roof-villa-silhouette"],
        expected_floors="2-3",
        rationale=("Japanese style coverage gap — tests if catalog handles "
                    "sliding-shoji-door + eaves-overhang."),
    ),
    GymPrompt(
        slot="chinese-pavilion",
        prompt=("An open-air pavilion with a grand central hall, curved "
                 "tile roof, side alcoves for reading, and ornamental "
                 "columns supporting the colonnaded gallery."),
        expected_silhouettes=["hip-roof-villa-silhouette",
                                "pagoda-stack-silhouette",
                                "cross-plan-temple-silhouette"],
        expected_floors="1-2",
        rationale=("Chinese style is the catalog's biggest gap (0 native "
                    "wall_fittings). Tests retrieval cross-cultural fallback."),
    ),
    GymPrompt(
        slot="gothic-chapel",
        prompt=("A single-nave gothic chapel with a pointed-arch window, "
                 "an altar within the apse, and a small side chapel with "
                 "ribbed vault ceiling."),
        expected_silhouettes=["cross-plan-temple-silhouette",
                                "dome-chapel-silhouette",
                                "longhouse-silhouette"],
        expected_floors="1",
        rationale=("Tests temple silhouettes + gothic wall_fittings "
                    "(lintel-arched, fluted-pilaster). Specialized chapel "
                    "rooms."),
    ),
    GymPrompt(
        slot="renaissance-palace",
        prompt=("A symmetrical Renaissance palace with grand stone façade, "
                 "central grand staircase, expansive ballroom, library, and "
                 "private chambers across three floors."),
        expected_silhouettes=["l-shape-mansion-silhouette",
                                "u-courtyard-silhouette",
                                "hip-roof-villa-silhouette"],
        expected_floors="3",
        rationale=("Large multi-floor; tests grand-staircase + symmetric "
                    "layout + corner-quoin wall_fittings. Ballroom + library "
                    "= specialized rooms."),
    ),
    GymPrompt(
        slot="rustic-tavern",
        prompt=("A sprawling tavern with a cavernous great hall, a bustling "
                 "kitchen, and timber-framed guest chambers upstairs."),
        expected_silhouettes=["longhouse-silhouette",
                                "gambrel-barn-silhouette",
                                "l-shape-mansion-silhouette"],
        expected_floors="1-2",
        rationale=("Commercial+residential hybrid. Tests great_hall room "
                    "+ half-timber-wall. Wide horizontal footprint."),
    ),
    GymPrompt(
        slot="stilt-house",
        prompt=("A tropical stilt house with wooden supporting pillars, a "
                 "single elevated room with woven walls, and a wraparound "
                 "porch accessed by a wooden ladder."),
        expected_silhouettes=["stilt-house-silhouette",
                                "gable-cottage-silhouette"],
        expected_floors="1-2",
        rationale=("Stresses non-AABB silhouettes (stilts under floor 0). "
                    "Tests ladder connector + porch/veranda treatment."),
    ),
]


# Sanity check: 10 unique slots
_slots = [p.slot for p in GYM_PROMPTS]
assert len(_slots) == len(set(_slots)) == 10, \
    f"Slot collision or count != 10: {_slots}"
