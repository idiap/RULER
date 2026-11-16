# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from ruler.io import read_yaml
from ruler.paths import SKILL_HOOKS_FILE
from ruler.runtime.skill_inventory import discover_skill_files
from ruler.schemas import SkillHookBinding

GUARDIAN = "recommendation-trace-guardian"
COMPOSER = "recommendation-argument-composer"
LEGACY_ALIAS = "decision-point-explanation-builder"
ARGUMENTATION_MODULE = "ruler/applications/resource_portfolio/argumentation.py"


def _bindings() -> dict[str, SkillHookBinding]:
    return {
        binding.skill: binding
        for binding in (
            SkillHookBinding.model_validate(item) for item in read_yaml(SKILL_HOOKS_FILE)
        )
    }


def _skill_text(name: str) -> str:
    return discover_skill_files()[name].path.read_text(encoding="utf-8")


def test_certificate_guardian_is_the_deterministic_proof_boundary() -> None:
    binding = _bindings()[GUARDIAN]
    skill = _skill_text(GUARDIAN)

    assert binding.execution_mode == "deterministic"
    assert binding.execution_commands == ["uv run ruler workflow resource-portfolio-plan"]
    assert ARGUMENTATION_MODULE in binding.implementation_refs
    assert "decision_argument.yaml" in binding.evidence_outputs
    assert "DecisionArgumentCertificate" in skill
    assert "binding constraint is not causal evidence" in skill
    assert "same-model runner-up separate from policy sensitivity" in skill
    assert "unique_feasible" in skill
    assert "Candidate KB statements have no solver authority" in skill


def test_composer_requires_certificate_and_preserves_proof_classifications() -> None:
    binding = _bindings()[COMPOSER]
    skill = _skill_text(COMPOSER)

    assert binding.execution_mode == "hybrid"
    assert ARGUMENTATION_MODULE in binding.implementation_refs
    assert "decision_argument.yaml" in binding.evidence_outputs
    assert "recommendation_argument.yaml" in binding.evidence_outputs
    assert "require a validated `DecisionArgumentCertificate`" in skill
    assert "same-model runner-up" in skill
    assert "Policy sensitivity" in skill
    assert "unique_feasible" in skill
    assert "decision_class: unique_feasible | cost_preferred | multiple_optima" in skill
    assert "candidate_kb_relation: parallel_non_authoritative" in skill
    assert "candidate_kb_solver_authority: false" in skill
    assert "solver_authority_source: reviewed_model" in skill
    assert "one vertical reading flow" in skill


def test_legacy_decision_point_skill_is_a_non_executable_routing_alias() -> None:
    binding = _bindings()[LEGACY_ALIAS]
    skill = _skill_text(LEGACY_ALIAS)

    assert binding.execution_mode is None
    assert not binding.execution_commands
    assert not binding.implementation_refs
    assert not binding.evidence_outputs
    assert "Deprecated Alias" in skill
    assert "$recommendation-trace-guardian" in skill
    assert "$recommendation-argument-composer" in skill
    assert "Do not execute an explanation workflow under this skill" in skill


def test_demonstrator_routes_directly_to_canonical_certificate_skills() -> None:
    skill = _skill_text("resource-portfolio-grounded-demonstrator")

    assert "$recommendation-trace-guardian" in skill
    assert "$recommendation-argument-composer" in skill
    assert "$decision-point-explanation-builder" not in skill
