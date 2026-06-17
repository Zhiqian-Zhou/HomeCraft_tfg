"""Genericness validation for gym-authored skills.

The user's requirement: skills must be GENERIC — apply to multiple cultures
+ categories sharing features, not be specific to one situation. This
module enforces that programmatically before Claude commits a skill.

Hard rules (from Pre-B.3 research):
  1. applicable_to >= 3 categories         [MANDATORY]
  2. tags.style >= 2 styles                [soft, can fail 1]
  3. parameters has >= 1 range or enum     [MANDATORY]
  4. alexander_patterns_relevant >= 1      [soft]
  5. description names >= 2 of its declared styles/categories [soft]

A skill passes if BOTH mandatory rules pass AND total fails <= 1.
"""
from __future__ import annotations

import re

_RANGE_RE = re.compile(r"^\d+\s*-\s*\d+$")


def is_generic(skill: dict) -> tuple[bool, list[str]]:
    """Return (passes, list_of_failure_reasons).

    Empty reason list = perfect generic skill.
    Non-empty but passes=True = acceptable (1 soft failure).
    passes=False = rejected; Claude must revise the skill.
    """
    fails: list[str] = []
    apps = skill.get("applicable_to") or []
    if len(apps) < 3:
        fails.append(
            f"MANDATORY: applicable_to has {len(apps)} (<3) categories")

    styles = (skill.get("tags") or {}).get("style") or []
    if len(styles) < 2:
        fails.append(f"tags.style has {len(styles)} (<2) styles")

    params = skill.get("parameters") or {}
    has_variable = False
    for v in params.values():
        if isinstance(v, str):
            if _RANGE_RE.match(v):
                has_variable = True
                break
            if "|" in v or "_or_" in v:
                has_variable = True
                break
    if not has_variable:
        fails.append(
            "MANDATORY: parameters lacks any range (N-M) or "
            "enum (with | or _or_)")

    pats = skill.get("alexander_patterns_relevant") or []
    if len(pats) < 1:
        fails.append("alexander_patterns_relevant is empty")

    desc = (skill.get("description") or "").lower()
    declared = set(styles) | set(apps)
    hits = sum(1 for t in declared if t and t.lower() in desc)
    if hits < 2:
        fails.append(
            f"description names only {hits} (<2) of its "
            f"declared styles/categories")

    mandatory_failed = any(f.startswith("MANDATORY:") for f in fails)
    soft_passes = len([f for f in fails if not f.startswith("MANDATORY:")]) <= 1
    passes = (not mandatory_failed) and soft_passes
    return passes, fails


def report(skill: dict) -> str:
    """Pretty-print result for CLI use."""
    passes, fails = is_generic(skill)
    head = "✓ GENERIC" if passes else "✗ NOT GENERIC"
    lines = [f"{head}  {skill.get('id', '<unknown>')}"]
    for f in fails:
        lines.append(f"  - {f}")
    if not fails:
        lines.append("  (all rules satisfied)")
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse, json, sys
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skill_paths", nargs="+",
                     help="Paths to skill JSON files")
    args = ap.parse_args()
    failed_any = False
    for p in args.skill_paths:
        skill = json.loads(Path(p).read_text(encoding="utf-8"))
        print(report(skill))
        if not is_generic(skill)[0]:
            failed_any = True
    sys.exit(1 if failed_any else 0)
