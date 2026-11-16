# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Fresh checkouts can provision optional local agent files without overwrites."""

from pathlib import Path
import shutil

from ruler.paths import REPO_ROOT
from ruler.runtime import claude_code, codex, opencode
from ruler.runtime.agent_setup import prepare_agent_config


def test_fresh_agent_setup_satisfies_bridge_contracts(tmp_path, monkeypatch):
    guides = tmp_path / "docs" / "guides"
    guides.mkdir(parents=True)
    for name in ("codex.md", "claude_code.md", "opencode.md"):
        shutil.copyfile(REPO_ROOT / "docs" / "guides" / name, guides / name)
    skill = tmp_path / "skills" / "sample" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: sample\n---\nuv run ruler validate all\n")
    for module in (codex, claude_code, opencode):
        for name, value in list(vars(module).items()):
            if isinstance(value, Path) and value.is_relative_to(REPO_ROOT):
                monkeypatch.setattr(module, name, tmp_path / value.relative_to(REPO_ROOT))
    prepare_agent_config(tmp_path)
    assert codex.validate_codex_bridge() == []
    assert claude_code.validate_claude_code_bridge() == []
    assert opencode.validate_opencode_bridge() == []


def test_setup_preserves_local_customizations_and_is_repeatable(tmp_path):
    guides = tmp_path / "docs" / "guides"
    guides.mkdir(parents=True)
    for name in ("codex.md", "claude_code.md", "opencode.md"):
        (guides / name).write_text(f"Public {name} documentation\n")
    prepare_agent_config(tmp_path)
    private = tmp_path / "AGENTS.md"
    private.write_text("Local instructions that must not be replaced\n")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert prepare_agent_config(tmp_path) == []
    assert {p: p.read_bytes() for p in before} == before
