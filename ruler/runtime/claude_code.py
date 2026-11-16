# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Claude Code bridge validation. This module treats Claude-facing project memory, skills,
and documentation as first-class runtime surfaces that must stay synchronized with
RULER workflows.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ruler.paths import REPO_ROOT

CLAUDE_DIR = REPO_ROOT / ".claude"
CLAUDE_SKILLS_DIR = CLAUDE_DIR / "skills"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
CLAUDE_DOC = REPO_ROOT / "docs" / "guides" / "claude_code.md"

REQUIRED_CLAUDE_SKILLS = {
    "ruler-framework-runner",
    "ruler-validation-gates",
    "ruler-reasoning-workflows",
    "ruler-translation-control",
    "ruler-claude-bridge-maintainer",
}


class ClaudeSkillManifest(BaseModel):
    """Typed claude skill manifest artifact used by the Claude Code workflow."""

    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = Field(min_length=1)


def validate_claude_code_bridge() -> list[str]:
    """Validate Claude Code bridge for the Claude Code workflow."""
    errors: list[str] = []
    if not CLAUDE_MD.exists():
        errors.append("missing CLAUDE.md")
    else:
        content = CLAUDE_MD.read_text(encoding="utf-8")
        for fragment in [
            "uv run ruler validate all",
            "uv run ruler validate claude-code",
            ".claude/skills/",
        ]:
            if fragment not in content:
                errors.append(f"CLAUDE.md missing {fragment!r}")
    if not CLAUDE_DOC.exists():
        errors.append("missing docs/guides/claude_code.md")
    if not CLAUDE_SKILLS_DIR.exists():
        errors.append("missing .claude/skills")
        return errors

    skill_dirs = {path.name for path in CLAUDE_SKILLS_DIR.iterdir() if path.is_dir()}
    missing_skills = sorted(REQUIRED_CLAUDE_SKILLS - skill_dirs)
    if missing_skills:
        errors.append(f"missing Claude Code skills: {missing_skills}")
    unexpected_names = sorted(name for name in skill_dirs if not _valid_skill_name(name))
    if unexpected_names:
        errors.append(f"invalid Claude Code skill names: {unexpected_names}")

    for skill_name in sorted(REQUIRED_CLAUDE_SKILLS & skill_dirs):
        skill_file = CLAUDE_SKILLS_DIR / skill_name / "SKILL.md"
        if not skill_file.exists():
            errors.append(f"{skill_name}: missing SKILL.md")
            continue
        try:
            frontmatter = _read_skill_frontmatter(skill_file)
        except ValueError as exc:
            errors.append(f"{skill_name}: {exc}")
            continue
        if frontmatter.name != skill_name:
            errors.append(f"{skill_name}: frontmatter name must match folder")
        body = skill_file.read_text(encoding="utf-8")
        if "uv run ruler" not in body:
            errors.append(f"{skill_name}: must mention a uv run ruler command")

    return errors


def _read_skill_frontmatter(path: Path) -> ClaudeSkillManifest:
    """Internal helper for read skill frontmatter in the Claude Code workflow."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter must end with ---")
    payload = read_yaml_from_text(content[4:end])
    if not isinstance(payload, dict):
        raise ValueError("frontmatter must be a mapping")
    return ClaudeSkillManifest.model_validate(payload)


def read_yaml_from_text(content: str) -> object:
    """Read YAML from text for the Claude Code workflow."""
    import yaml

    return yaml.safe_load(content)


def _valid_skill_name(value: str) -> bool:
    return re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}[a-z0-9]", value) is not None
