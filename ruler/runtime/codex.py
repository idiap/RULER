# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Codex project bridge validation.

Codex consumes ``AGENTS.md`` as repository instructions and executes the same
installed ``ruler`` console entry point used by every other client.  Keeping this
small bridge explicit prevents Codex support from being inferred only from prose.
"""

from __future__ import annotations

from pathlib import Path

from ruler.paths import REPO_ROOT, SKILLS_DIR

AGENTS_MD = REPO_ROOT / "AGENTS.md"
CODEX_DOC = REPO_ROOT / "docs" / "guides" / "codex.md"


def validate_codex_bridge() -> list[str]:
    """Return actionable errors for the repository-local Codex surface."""
    errors: list[str] = []
    if not AGENTS_MD.is_file():
        errors.append("missing AGENTS.md")
    else:
        content = AGENTS_MD.read_text(encoding="utf-8")
        for fragment in (
            "uv sync --extra dev",
            "uv run ruler validate codex",
            "uv run ruler validate all",
            "skills/",
        ):
            if fragment not in content:
                errors.append(f"AGENTS.md missing {fragment!r}")
    if not CODEX_DOC.is_file():
        errors.append("missing docs/guides/codex.md")
    if not SKILLS_DIR.is_dir():
        errors.append("missing canonical skills directory")
    elif not any(_is_skill(path) for path in SKILLS_DIR.rglob("SKILL.md")):
        errors.append("canonical skills directory contains no real skills")
    return errors


def _is_skill(path: Path) -> bool:
    """A Codex-visible skill must be a non-empty, CLI-backed skill definition."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return content.startswith("---\n") and "uv run ruler" in content
