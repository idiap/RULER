# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Preparation preserves recorded evidence and fails before writes without tools."""

from click.testing import CliRunner

from ruler.cli import main
from ruler.runtime import check_prerequisites as prerequisites
from ruler.runtime.workflow_registry import load_workflow_registry, resolve_cli_command


def test_preparation_only_invokes_registered_offline_workflows():
    workflows = {item["id"]: item for item in load_workflow_registry()["workflows"]}
    for name in prerequisites.CHECK_WORKFLOWS:
        assert resolve_cli_command(f"uv run ruler workflow {name}") is None
        assert workflows[name]["network"] is False or prerequisites.CHECK_WORKFLOW_OPTIONS.get(
            name
        ) == {"offline": True}
        assert workflows[name]["deterministic"] is True


def test_missing_solver_fails_before_generating_reports(monkeypatch, tmp_path):
    monkeypatch.setattr(prerequisites.shutil, "which", lambda executable: None)
    monkeypatch.setattr(
        "ruler.cli.prepare_agent_config_command",
        lambda: (_ for _ in ()).throw(AssertionError("must fail before writes")),
    )
    result = CliRunner().invoke(main, ["prepare", "checks"])
    assert result.exit_code != 0
    assert "SWI-Prolog is required" in result.output
    assert not (tmp_path / "reports").exists()
