# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""OpenCode bridge validation. This module checks that OpenCode agents, commands, and skill
metadata expose the same controlled RULER workflows as the rest of the repo.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from ruler.paths import REPO_ROOT

AGENTS_MD = REPO_ROOT / "AGENTS.md"
OPENCODE_DIR = REPO_ROOT / ".opencode"
OPENCODE_SKILLS_DIR = OPENCODE_DIR / "skills"
OPENCODE_COMMANDS_DIR = OPENCODE_DIR / "commands"
OPENCODE_DOC = REPO_ROOT / "docs" / "guides" / "opencode.md"

REQUIRED_OPENCODE_SKILLS = {
    "ruler-framework-runner",
    "ruler-validation-gates",
    "ruler-reasoning-workflows",
    "ruler-translation-control",
    "ruler-opencode-bridge-maintainer",
}

REQUIRED_OPENCODE_COMMANDS = {"validate", "reason", "graphs"}


class OpenCodeFrontmatter(BaseModel):
    """Typed open code frontmatter artifact used by the OpenCode workflow."""

    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    description: str = Field(min_length=1)


def validate_opencode_bridge() -> list[str]:
    """Validate OpenCode bridge for the OpenCode workflow."""
    errors: list[str] = []
    errors.extend(_validate_agents_md())
    errors.extend(_validate_opencode_skills())
    errors.extend(_validate_opencode_commands())
    if not OPENCODE_DOC.exists():
        errors.append("missing docs/guides/opencode.md")
    return errors


def _validate_agents_md() -> list[str]:
    """Internal helper for validate agents md in the OpenCode workflow."""
    if not AGENTS_MD.exists():
        return ["missing AGENTS.md"]
    content = AGENTS_MD.read_text(encoding="utf-8")
    errors: list[str] = []
    for fragment in [
        "uv run ruler validate opencode",
        ".opencode/skills/",
        ".opencode/commands/",
    ]:
        if fragment not in content:
            errors.append(f"AGENTS.md missing {fragment!r}")
    return errors


def _validate_opencode_skills() -> list[str]:
    """Internal helper for validate OpenCode skills in the OpenCode workflow."""
    if not OPENCODE_SKILLS_DIR.exists():
        return ["missing .opencode/skills"]
    errors: list[str] = []
    skill_dirs = {path.name for path in OPENCODE_SKILLS_DIR.iterdir() if path.is_dir()}
    missing_skills = sorted(REQUIRED_OPENCODE_SKILLS - skill_dirs)
    if missing_skills:
        errors.append(f"missing OpenCode skills: {missing_skills}")
    invalid_names = sorted(name for name in skill_dirs if not _valid_skill_name(name))
    if invalid_names:
        errors.append(f"invalid OpenCode skill names: {invalid_names}")

    for skill_name in sorted(REQUIRED_OPENCODE_SKILLS & skill_dirs):
        skill_file = OPENCODE_SKILLS_DIR / skill_name / "SKILL.md"
        if not skill_file.exists():
            errors.append(f"{skill_name}: missing SKILL.md")
            continue
        try:
            frontmatter = _read_frontmatter(skill_file)
        except ValueError as exc:
            errors.append(f"{skill_name}: {exc}")
            continue
        if frontmatter.name != skill_name:
            errors.append(f"{skill_name}: frontmatter name must match folder")
        body = skill_file.read_text(encoding="utf-8")
        if "uv run ruler" not in body:
            errors.append(f"{skill_name}: must mention a uv run ruler command")
    return errors


def _validate_opencode_commands() -> list[str]:
    """Internal helper for validate OpenCode commands in the OpenCode workflow."""
    if not OPENCODE_COMMANDS_DIR.exists():
        return ["missing .opencode/commands"]
    errors: list[str] = []
    command_files = {path.stem: path for path in OPENCODE_COMMANDS_DIR.glob("*.md")}
    missing_commands = sorted(REQUIRED_OPENCODE_COMMANDS - set(command_files))
    if missing_commands:
        errors.append(f"missing OpenCode commands: {missing_commands}")
    invalid_names = sorted(name for name in command_files if not _valid_skill_name(name))
    if invalid_names:
        errors.append(f"invalid OpenCode command names: {invalid_names}")
    for command_name in sorted(REQUIRED_OPENCODE_COMMANDS & set(command_files)):
        command_file = command_files[command_name]
        try:
            frontmatter = _read_frontmatter(command_file)
        except ValueError as exc:
            errors.append(f"{command_name}: {exc}")
            continue
        if not frontmatter.description:
            errors.append(f"{command_name}: missing description")
        body = command_file.read_text(encoding="utf-8")
        if "uv run ruler" not in body:
            errors.append(f"{command_name}: must mention a uv run ruler command")
    return errors


def _read_frontmatter(path: Path) -> OpenCodeFrontmatter:
    """Internal helper for read frontmatter in the OpenCode workflow."""
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError("missing YAML frontmatter")
    end = content.find("\n---\n", 4)
    if end == -1:
        raise ValueError("frontmatter must end with ---")
    payload = read_yaml_from_text(content[4:end])
    if not isinstance(payload, dict):
        raise ValueError("frontmatter must be a mapping")
    return OpenCodeFrontmatter.model_validate(payload)


def read_yaml_from_text(content: str) -> object:
    """Read YAML from text for the OpenCode workflow."""
    import yaml

    return yaml.safe_load(content)


def _valid_skill_name(value: str) -> bool:
    return re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", value) is not None
