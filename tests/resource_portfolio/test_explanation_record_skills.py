# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from ruler.io import read_yaml
from ruler.paths import SKILL_HOOKS_FILE
from ruler.runtime.skill_inventory import discover_skill_files
from ruler.schemas import SkillHookBinding

SCENARIO_SKILL = "resource-scenario-coverage-explainer"
COST_SKILL = "resource-cost-objective-explainer"
IMPLEMENTATION = "ruler/applications/resource_portfolio/explanation_records.py"


def _bindings() -> dict[str, SkillHookBinding]:
    return {
        binding.skill: binding
        for binding in (
            SkillHookBinding.model_validate(item) for item in read_yaml(SKILL_HOOKS_FILE)
        )
    }


def _skill_text(name: str) -> str:
    return discover_skill_files()[name].path.read_text(encoding="utf-8")


def test_scenario_explainer_routes_to_typed_executed_evidence() -> None:
    binding = _bindings()[SCENARIO_SKILL]
    skill = _skill_text(SCENARIO_SKILL)

    assert binding.execution_mode == "deterministic"
    assert IMPLEMENTATION in binding.implementation_refs
    assert "uv run ruler portfolio stress" in binding.execution_commands
    assert "scenario_envelope_explanation.yaml" in binding.evidence_outputs
    assert "build_scenario_envelope_explanation" in skill
    assert "ScenarioCoverageDeclaration" in skill
    assert "assignment-stable across the tested scenarios" in skill
    assert "Do not shorten this to" in skill
    assert "List declared exclusions" in skill


def test_cost_explainer_requires_verified_arithmetic_and_comparison_type() -> None:
    binding = _bindings()[COST_SKILL]
    skill = _skill_text(COST_SKILL)

    assert binding.execution_mode == "deterministic"
    assert IMPLEMENTATION in binding.implementation_refs
    assert "uv run ruler portfolio optimize" in binding.execution_commands
    assert "uv run ruler portfolio verify-plan" in binding.execution_commands
    assert "cost_objective_explanation.yaml" in binding.evidence_outputs
    assert "build_cost_objective_explanation" in skill
    assert "coefficient × selected_value" in skill
    assert "objective unit and time basis are separate fields" in skill
    assert "changes_approved_model: false" in skill
    assert "policy sensitivity" in skill
