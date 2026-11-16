# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from decimal import Decimal

import pytest

from ruler.applications.resource_portfolio.argumentation import (
    build_decision_argument_certificate,
)
from ruler.applications.resource_portfolio.explanation_records import (
    CoverageExclusion,
    ScenarioCoverageDeclaration,
    build_cost_objective_explanation,
    build_scenario_envelope_explanation,
)
from ruler.applications.resource_portfolio.optimization import optimize_portfolio
from ruler.applications.resource_portfolio.robustness import (
    CounterfactualChange,
    ScenarioSet,
    run_counterfactual,
    stress_test,
)
from ruler.optimization.contracts import (
    LinearConstraint,
    LinearExpression,
    LinearObjective,
    LinearTerm,
    OptimizationProblem,
    OptimizationVariable,
    Scenario,
)

SHA = "sha256:" + "a" * 64


def _problem() -> OptimizationProblem:
    return OptimizationProblem(
        problem_id="annual-fleet",
        snapshot_digest=SHA,
        variables=(
            OptimizationVariable(
                variable_id="owned",
                domain="binary",
                lower_bound=0,
                upper_bound=1,
                unit="unit",
                origin_refs=("asset:owned",),
            ),
            OptimizationVariable(
                variable_id="rental",
                domain="binary",
                lower_bound=0,
                upper_bound=1,
                unit="unit",
                origin_refs=("quote:rental",),
            ),
        ),
        constraints=(
            LinearConstraint(
                constraint_id="capacity",
                expression=LinearExpression(
                    terms=(
                        LinearTerm(variable_id="owned", coefficient=1),
                        LinearTerm(variable_id="rental", coefficient=1),
                    )
                ),
                sense=">=",
                rhs=1,
                unit="unit",
                origin_refs=("policy:capacity",),
            ),
        ),
        objectives=(
            LinearObjective(
                objective_id="annual_cost",
                expression=LinearExpression(
                    terms=(
                        LinearTerm(variable_id="owned", coefficient=10),
                        LinearTerm(variable_id="rental", coefficient=15),
                    ),
                    constant=2,
                ),
                unit="CHF",
                component="lifecycle",
                origin_refs=("finance:annual-cost",),
            ),
        ),
    )


def _scenarios() -> ScenarioSet:
    return ScenarioSet(
        scenario_set_id="rental-rates",
        seed=4,
        scenarios=(
            Scenario(
                scenario_id="low",
                probability=Decimal("0.5"),
                information_set="initial",
                parameter_multipliers={"objective_term:annual_cost:rental": Decimal("0.8")},
                assumption_refs=("assumption:low-rate",),
            ),
            Scenario(
                scenario_id="high",
                probability=Decimal("0.5"),
                information_set="initial",
                parameter_multipliers={"objective_term:annual_cost:rental": Decimal("1.2")},
                assumption_refs=("assumption:high-rate",),
            ),
        ),
    )


def _declaration() -> ScenarioCoverageDeclaration:
    return ScenarioCoverageDeclaration(
        coverage_id="annual-rate-envelope",
        planning_horizon="2027 annual planning horizon",
        investigated_question="Does the selected fleet change across reviewed rental rates?",
        exclusions=(
            CoverageExclusion(
                dimension="simultaneous project cancellation",
                reason="No approved cancellation distribution was supplied.",
                origin_refs=("review:scenario-boundary",),
            ),
        ),
        origin_refs=("review:scenario-scope",),
    )


def test_scenario_record_reports_finite_tested_range_and_explicit_omission() -> None:
    problem = _problem()
    scenarios = _scenarios()
    stress = stress_test(problem, scenarios, alpha=Decimal("0.5"))
    certificate = build_decision_argument_certificate(problem, optimize_portfolio(problem))

    record = build_scenario_envelope_explanation(
        problem, scenarios, stress, _declaration(), certificate=certificate
    )

    assert record.scenario_count == 2
    assert record.tested_parameters[0].minimum_multiplier == Decimal("0.8")
    assert record.tested_parameters[0].maximum_multiplier == Decimal("1.2")
    assert record.assignment_stable_across_tested_scenarios
    assert record.exclusions[0].dimension == "simultaneous project cancellation"
    assert {item.analysis_kind for item in record.executed_analysis_classes} >= {
        "parameter_stress",
        "same_model_exclusion",
        "variable_forcedness",
        "constraint_ablation",
    }


def test_scenario_record_rejects_a_report_from_another_model() -> None:
    problem = _problem()
    scenarios = _scenarios()
    stress = stress_test(problem, scenarios)
    changed = problem.model_copy(update={"problem_id": "other"})

    with pytest.raises(ValueError, match="base model"):
        build_scenario_envelope_explanation(changed, scenarios, stress, _declaration())


def test_cost_record_reconstructs_constant_terms_and_annual_basis() -> None:
    problem = _problem()
    plan = optimize_portfolio(problem)
    changes = (CounterfactualChange(kind="constraint_rhs", target_id="capacity", value=0),)
    certificate = build_decision_argument_certificate(
        problem,
        plan,
        policy_counterfactual=run_counterfactual(problem, changes, run_id="remove-capacity"),
        policy_changes=changes,
    )

    record = build_cost_objective_explanation(
        problem,
        plan,
        objective_id="annual_cost",
        time_basis="annual planning horizon",
        time_basis_origin_refs=("finance:annual-cost",),
        certificate=certificate,
    )

    assert record.objective_unit == "CHF"
    assert record.time_basis == "annual planning horizon"
    assert record.constant.contribution == Decimal(2)
    assert sum((term.contribution for term in record.terms), Decimal(0)) == Decimal(10)
    assert record.reconstructed_objective_value == Decimal(12)
    assert record.verified_objective_value == Decimal(12)
    assert not record.grounding_complete
    same_model = record.contrasts[0]
    assert same_model.comparison_kind == "same_model_alternative"
    assert not same_model.changes_approved_model
    assert same_model.available
    assert same_model.compared_objective_value == Decimal(17)
    assert same_model.selected_minus_compared == Decimal(-5)
    policy = record.contrasts[1]
    assert policy.comparison_kind == "policy_sensitivity"
    assert policy.changes_approved_model
    assert policy.compared_objective_value == Decimal(2)
    assert policy.selected_minus_compared == Decimal(10)


def test_cost_record_fails_when_time_basis_is_unattributed() -> None:
    problem = _problem()
    with pytest.raises(ValueError, match="time basis"):
        build_cost_objective_explanation(
            problem,
            optimize_portfolio(problem),
            objective_id="annual_cost",
            time_basis="annual",
            time_basis_origin_refs=(),
        )
