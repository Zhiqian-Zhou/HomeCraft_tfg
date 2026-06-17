"""Stage 1a-bis — typology chooser.

After `global_designer.design_global_v4()` returns the style + silhouette
+ floor count, this stage presents the LLM with a filtered catalog of
typologies (towers, roofs, windows, gardens) and asks it to pick ONE per
kind that fits the building.

The choices are stored back into `global_intent` under
`selected_typologies` so downstream stages can emit
`{"kind": "typology", "name": "<name>", "aabb": [...]}` ops the voxelizer
will dispatch to `pipeline.skills.typologies.get_typology()`.

Design notes
------------
* The chooser is **soft**: if the LLM is unavailable or returns garbage,
  it falls back to the first candidate. The pipeline never fails because
  of typology selection.
* No selection means "no typology choice for this kind" — downstream
  agents are free to ignore the absence and emit their own deterministic
  ops as before.
* Filter relaxation: if a strict (kind + style + scale) filter returns
  zero candidates, the chooser progressively drops constraints (first
  scale, then style) so it always has something to offer the LLM.
* Anti-mode-collapse: optionally fire `k=3` parallel calls with stepped
  temperatures and prefer a less-frequent typology if a recent-history
  file is passed in `history_path` (used by the gym).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

from pipeline.skills.typologies import (
    get_metadata, filter_by,
)


# Kinds we attempt to choose for, in the order they appear in the prompt
# catalog presented to the LLM.
_KINDS: tuple[str, ...] = ("tower", "roof", "window", "garden")


def _scale_for_silhouette(silhouette_id: str | None) -> str:
    """Map a silhouette_id to a likely scale bucket.

    Cheap heuristic — silhouettes with 'monumental', 'cathedral', 'palace'
    in the name get 'monumental'; those with 'tower', 'castle', 'mansion'
    get 'large'; rest default to 'medium'. Used as a filter hint only.
    """
    s = (silhouette_id or "").lower()
    if any(k in s for k in ("monumental", "cathedral", "palace", "temple")):
        return "monumental"
    if any(k in s for k in ("tower", "castle", "mansion", "manor")):
        return "large"
    if any(k in s for k in ("small", "cottage", "shed", "hut")):
        return "small"
    return "medium"


def _candidates(kind: str, style: str, scale: str) -> list[str]:
    """Return a non-empty list of candidate typology names for `kind`,
    relaxing filters progressively if a strict match is empty."""
    out = filter_by(kind=kind, style=style, scale=scale)
    if out:
        return out
    # Drop scale.
    out = filter_by(kind=kind, style=style)
    if out:
        return out
    # Drop style.
    out = filter_by(kind=kind)
    return out


def _catalog_prompt(kind: str, candidates: list[str]) -> str:
    """Render a compact menu of candidates the LLM can read in one shot."""
    lines = []
    for name in candidates:
        m = get_metadata(name)
        lines.append(
            f"- {name} ({m.title}): {m.description.strip()} "
            f"| typical_footprint={m.typical_footprint} "
            f"| style_affinities={m.style_affinities or 'any'}"
        )
    return "\n".join(lines)


def _system_prompt(kind: str) -> str:
    return (
        f"You are an architectural typology selector. The user has a building "
        f"of a given style and silhouette and needs ONE {kind} typology from "
        f"the catalog below.\n\n"
        f"Pick the candidate whose style_affinities and description best fit "
        f"the building. If multiple candidates fit, prefer the one whose "
        f"typical_footprint matches the building's scale.\n\n"
        f"Respond with ONLY a JSON object: "
        f"{{\"typology\": \"<name>\"}} where <name> is one of the "
        f"candidate names. If absolutely none fit, respond with "
        f"{{\"typology\": null}}."
    )


def _user_payload(kind: str, candidates: list[str], style: str,
                  silhouette_id: str | None) -> str:
    return json.dumps({
        "kind": kind,
        "style": style,
        "silhouette_id": silhouette_id,
        "catalog": _catalog_prompt(kind, candidates),
    }, ensure_ascii=False)


def _safe_choose_one(kind: str, candidates: list[str], style: str,
                     silhouette_id: str | None,
                     llm_caller: Callable[..., dict] | None,
                     temperature: float = 0.7,
                     model: str | None = None) -> str | None:
    """Call the LLM once for `kind`. The choice is the LLM's.

    Returns the chosen typology name (must be in `candidates`) or None.
    NO deterministic first-candidate fallback: if the LLM is absent, errors,
    or returns an off-menu pick, we return None (this `kind` gets no typology)
    so the typology variety reflects the LLM only, not a fixed default.
    """
    if not candidates:
        return None
    if llm_caller is None:
        return None
    try:
        kwargs: dict = {
            "system": _system_prompt(kind),
            "user":   _user_payload(kind, candidates, style, silhouette_id),
            "temperature": temperature,
            "max_tokens": 256,
        }
        if model is not None:
            kwargs["model"] = model
        out = llm_caller(**kwargs)
    except Exception as e:  # noqa: BLE001
        print(f"[typology_chooser] LLM failed for kind {kind!r} ({e}) — "
              f"no typology (no fallback).", file=sys.stderr)
        return None

    pick = (out or {}).get("typology")
    if isinstance(pick, str) and pick in candidates:
        return pick
    # Absent or off-menu pick → no typology for this kind (no fallback).
    return None


def choose_typologies(global_intent: dict, *,
                      llm_caller: Callable[..., dict] | None = None,
                      model: str | None = None,
                      history_path: Path | None = None,
                      k_parallel: int = 1) -> dict:
    """Pick one typology per kind that fits the building.

    Args:
        global_intent: the v4 dict returned by `design_global_v4`. Must
            carry `"style"` and `"silhouette_id"`.
        llm_caller: a callable matching `call_llm_json(system=, user=,
            **kwargs) -> dict`. Pass None for a pure-deterministic mode
            (always picks the first candidate; useful in tests).
        model: optional model name forwarded to the LLM.
        history_path: optional path to a JSON file holding a list of
            previous build records, each with `selected_typologies`. If
            provided and `k_parallel > 1`, we attempt anti-mode-collapse
            by sampling at multiple temperatures and preferring an
            under-represented typology.
        k_parallel: number of LLM samples per kind (1 = single shot,
            3 = anti-collapse sweep with stepped temperatures).

    Returns:
        A dict {kind: typology_name_or_None} suitable to merge into
        `global_intent["selected_typologies"]`.
    """
    style = (global_intent.get("style") or "").lower()
    silhouette_id = global_intent.get("silhouette_id")
    scale = _scale_for_silhouette(silhouette_id)

    history_counts: Counter[str] = Counter()
    if history_path is not None and history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
            for rec in history[-10:]:
                for v in (rec.get("selected_typologies") or {}).values():
                    if v:
                        history_counts[v] += 1
        except Exception:
            pass

    selected: dict[str, str | None] = {}
    for kind in _KINDS:
        candidates = _candidates(kind, style, scale)
        if not candidates:
            selected[kind] = None
            continue

        # Anti-mode-collapse via stepped temperatures.
        if k_parallel > 1 and llm_caller is not None:
            picks: list[str | None] = []
            temps = [0.7, 0.95, 1.1][:k_parallel]
            for temp in temps:
                picks.append(_safe_choose_one(
                    kind, candidates, style, silhouette_id,
                    llm_caller, temperature=temp, model=model,
                ))
            valid = [p for p in picks if p is not None]
            if valid:
                # Prefer the pick with the lowest recent-history count.
                best = min(valid, key=lambda p: history_counts.get(p, 0))
                selected[kind] = best
            else:
                selected[kind] = None
        else:
            selected[kind] = _safe_choose_one(
                kind, candidates, style, silhouette_id,
                llm_caller, temperature=0.7, model=model,
            )

    return selected


__all__ = ["choose_typologies"]
