# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Skill inventory discovery. It treats the grouped skills folder as a typed artifact
surface used by validators, routers, and workflow visualizations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ruler.paths import REPO_ROOT, SKILLS_DIR

SKILL_GROUPS = {
    "autoformalization",
    "demonstrators",
    "reasoning",
    "runtime",
    "source",
    "synthetic",
    "translation",
    "workflow",
}


@dataclass(frozen=True)
class SkillFile:
    """Typed skill file artifact used by the skill inventory workflow."""

    name: str
    group: str
    path: Path
    description: str


def discover_skill_files(skills_dir: Path | None = None) -> dict[str, SkillFile]:
    """Discover skill files for the skill inventory workflow."""
    inventory: dict[str, SkillFile] = {}
    for skill_file in sorted((skills_dir if skills_dir is not None else SKILLS_DIR).glob("*/*/SKILL.md")):
        group = skill_file.parents[1].name
        skill_dir = skill_file.parent
        text = skill_file.read_text(encoding="utf-8", errors="ignore")
        name_match = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
        desc_match = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
        name = name_match.group(1).strip() if name_match else skill_dir.name
        inventory[name] = SkillFile(
            name=name,
            group=group,
            path=skill_file,
            description=desc_match.group(1).strip() if desc_match else "",
        )
    return inventory


def repo_relative_skill_path(skill: SkillFile) -> str:
    """Repo relative skill path for the skill inventory workflow."""
    return str(skill.path.relative_to(REPO_ROOT))
