# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from ruler.io import read_yaml
from ruler.paths import SKILL_HOOKS_FILE
from ruler.runtime.skill_inventory import discover_skill_files
from ruler.schemas import SkillHookBinding

SKILL = "resource-decision-tradeoff-communicator"
ARGUMENTATION = "ruler/applications/resource_portfolio/argumentation.py"
EXPLANATIONS = "ruler/applications/resource_portfolio/explanation_records.py"
RENDERER = "ruler/interfaces/resource_portfolio_demonstrator.py"


def test_tradeoff_communicator_uses_typed_solver_evidence() -> None:
    bindings = {
        binding.skill: binding
        for binding in (
            SkillHookBinding.model_validate(item) for item in read_yaml(SKILL_HOOKS_FILE)
        )
    }
    binding = bindings[SKILL]

    assert binding.execution_mode == "hybrid"
    assert {ARGUMENTATION, EXPLANATIONS, RENDERER}.issubset(binding.implementation_refs)
    assert {"pyomo-highs", "decimal-independent-verifier", "codex-exec"}.issubset(
        binding.backend_ids
    )
    assert {
        "decision_argument.yaml",
        "cost_objective_explanation.yaml",
        "scenario_envelope_explanation.yaml",
        "index.html",
    }.issubset(binding.evidence_outputs)


def test_tradeoff_communicator_rejects_tree_and_exhaustiveness_claims() -> None:
    skill = discover_skill_files()[SKILL].path.read_text(encoding="utf-8")

    assert "Use a trade-off map, not a decision tree" in skill
    assert "otherwise the tested changed-policy sensitivity" in skill
    assert "approved model" in skill
    assert "sum(run_count for analysis in executed_analysis_classes)" in skill
    assert "Do not hard-code 13" in skill
    assert "exhaustive search" in skill
    assert "DecisionArgumentCertificate" in skill
    assert "CostObjectiveExplanation" in skill
    assert "ScenarioEnvelopeExplanation" in skill
