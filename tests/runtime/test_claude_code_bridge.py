# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the Claude Code compatibility surface.

The bridge should expose RULER workflows as repo-local memory and skills so Claude
Code can run the same validated commands as the native CLI.
"""

from __future__ import annotations

from ruler.runtime.claude_code import CLAUDE_MD, CLAUDE_SKILLS_DIR, REQUIRED_CLAUDE_SKILLS
from ruler.runtime.validation import validate_claude_code_bridge


def test_claude_code_bridge_has_project_memory_and_skills() -> None:
    """Every mirrored Claude skill should exist and point back to CLI commands."""
    assert CLAUDE_MD.exists()
    assert CLAUDE_SKILLS_DIR.exists()

    for skill_name in REQUIRED_CLAUDE_SKILLS:
        skill_file = CLAUDE_SKILLS_DIR / skill_name / "SKILL.md"
        assert skill_file.exists()
        content = skill_file.read_text(encoding="utf-8")
        assert f"name: {skill_name}" in content
        assert "uv run ruler" in content


def test_claude_code_bridge_validator_passes() -> None:
    """The validator provides the compact bridge health signal used by hooks."""
    assert validate_claude_code_bridge() == [f"claude_skills={len(REQUIRED_CLAUDE_SKILLS)}"]
