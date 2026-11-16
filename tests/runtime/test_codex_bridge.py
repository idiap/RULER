# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the repository-local Codex execution surface."""

from ruler.runtime.codex import AGENTS_MD, CODEX_DOC
from ruler.runtime.validation import validate_codex_bridge


def test_codex_bridge_is_cli_backed_and_validated() -> None:
    assert AGENTS_MD.is_file()
    assert CODEX_DOC.is_file()
    assert "uv run ruler" in AGENTS_MD.read_text(encoding="utf-8")
    assert validate_codex_bridge() == ["instructions=AGENTS.md", "skills=canonical"]
