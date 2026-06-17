"""Run every skill across 3 styles × 2 sizes and report failures.

    python3 -m pipeline.skills.test_harness
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Ensure repo root is on sys.path so `pipeline.*` imports work.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.skills import list_skills
from pipeline.skills.preview import export_skill


STYLES = ["medieval", "modern", "fantasy"]
SIZES = ["small", "medium"]


def main() -> int:
    skills = list_skills()
    if not skills:
        print("[test] no skills found in pipeline/skills/")
        return 1
    print(f"[test] running {len(skills)} skills × {len(STYLES)} styles × {len(SIZES)} sizes")

    failures: list[tuple[str, str, str, str]] = []  # (skill, style, size, error)
    ok = 0
    for skill in skills:
        for style in STYLES:
            for size in SIZES:
                try:
                    path = export_skill(skill, style=style, size=size)
                    ok += 1
                except Exception as exc:
                    failures.append((skill, style, size, str(exc)))

    total = len(skills) * len(STYLES) * len(SIZES)
    print(f"[test] {ok}/{total} OK, {len(failures)} failures")
    if failures:
        print("\n[test] failures:")
        for skill, style, size, err in failures:
            print(f"  - {skill} ({style}, {size}): {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
