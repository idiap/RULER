# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Adversarial checks for the canonical workflow execution registry."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ruler.runtime.validation import ValidationErrorGroup
from ruler.runtime.workflow_registry import (
    build_execution_catalogue,
    resolve_cli_command,
    validate_workflow_registry,
    write_execution_catalogue,
)


def test_declared_commands_resolve_against_live_click_tree() -> None:
    assert resolve_cli_command("uv run ruler workflow resource-portfolio-plan") is None
    assert resolve_cli_command("uv run pytest -q") is None
    assert "missing CLI command" in resolve_cli_command("uv run ruler workflow removed")
    assert "unknown option" in resolve_cli_command(
        "uv run ruler workflow cbr-case --removed-option"
    )
    for profile in ("local", "pr", "integration", "release", "drift"):
        assert resolve_cli_command(f"uv run ruler workflow test-generative-{profile}") is None


def test_current_registry_has_zero_drift_and_complete_skill_inventory() -> None:
    messages = validate_workflow_registry()
    catalogue = build_execution_catalogue()
    assert f"workflows={len(catalogue['workflows'])}" in messages
    assert catalogue["workflows"]
    runtime_skills = catalogue["skill_inventory"]["runtime"]
    assert len(runtime_skills) == len(list(Path("skills").rglob("SKILL.md")))
    assert any("legal-multi-solver-orchestrator" in item for item in runtime_skills)
    assert any("formal-reasoning-flow-guardian" in item for item in runtime_skills)
    assert len(catalogue["skill_inventory"]["project_only"]) == len(
        list(Path("proj_skills").rglob("SKILL.md"))
    )
    assert len(catalogue["skill_inventory"]["client_wrapper"]) == 10
    assert catalogue["drift"] == []


def test_registry_rejects_duplicate_dangling_and_unclassified_workflows(tmp_path: Path) -> None:
    source = Path(".ruler/workflows.yaml")
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["workflows"].append(dict(payload["workflows"][0]))
    payload["workflows"][0]["classification"] = "mystery"
    payload["workflows"][1]["parent_workflow"] = "removed-parent"
    fixture = tmp_path / "workflows.yaml"
    fixture.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    with pytest.raises(ValidationErrorGroup) as raised:
        validate_workflow_registry(fixture)
    errors = "\n".join(raised.value.errors)
    duplicate_id = payload["workflows"][0]["id"]
    assert f"duplicate workflow id: {duplicate_id}" in errors
    assert f"{duplicate_id}: invalid classification 'mystery'" in errors
    dangling_id = payload["workflows"][1]["id"]
    assert f"{dangling_id}: unknown parent workflow removed-parent" in errors


def test_execution_catalogue_writes_machine_and_human_views(tmp_path: Path) -> None:
    paths = write_execution_catalogue(tmp_path)
    payload = yaml.safe_load(paths["yaml"].read_text(encoding="utf-8"))
    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert payload["drift"] == []
    assert "| `generative-kb-quality` | lifecycle_gate |" in markdown
    assert "## Project-only skills" in markdown
    assert "No unexplained drift." in markdown
