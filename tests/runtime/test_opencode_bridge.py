# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the OpenCode compatibility surface.

OpenCode receives the same project concepts through AGENTS.md, mirrored skills, and
repo-local command files that call the validated RULER CLI.
"""

from __future__ import annotations

from ruler.runtime.opencode import (
    AGENTS_MD,
    OPENCODE_COMMANDS_DIR,
    OPENCODE_SKILLS_DIR,
    REQUIRED_OPENCODE_COMMANDS,
    REQUIRED_OPENCODE_SKILLS,
)
from ruler.runtime.validation import validate_opencode_bridge


def test_opencode_bridge_has_agents_skills_and_commands() -> None:
    """Every mirrored OpenCode skill and command should exist and be CLI-backed."""
    assert AGENTS_MD.exists()
    assert OPENCODE_SKILLS_DIR.exists()
    assert OPENCODE_COMMANDS_DIR.exists()

    for skill_name in REQUIRED_OPENCODE_SKILLS:
        skill_file = OPENCODE_SKILLS_DIR / skill_name / "SKILL.md"
        assert skill_file.exists()
        content = skill_file.read_text(encoding="utf-8")
        assert f"name: {skill_name}" in content
        assert "uv run ruler" in content

    for command_name in REQUIRED_OPENCODE_COMMANDS:
        command_file = OPENCODE_COMMANDS_DIR / f"{command_name}.md"
        assert command_file.exists()
        assert "uv run ruler" in command_file.read_text(encoding="utf-8")


def test_opencode_bridge_validator_passes() -> None:
    """The validator gives hooks a compact OpenCode bridge health signal."""
    assert validate_opencode_bridge() == [
        f"opencode_skills={len(REQUIRED_OPENCODE_SKILLS)}",
        f"opencode_commands={len(REQUIRED_OPENCODE_COMMANDS)}",
    ]
