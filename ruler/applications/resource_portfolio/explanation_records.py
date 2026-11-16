# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic records for scenario coverage and objective-cost provenance."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from ruler.applications.resource_portfolio.argumentation import (
    DecisionArgumentCertificate,
)
from ruler.applications.resource_portfolio.demonstrator_grounding import (
    DemonstratorGrounding,
)
from ruler.applications.resource_portfolio.optimization import VerifiedPlan
from ruler.applications.resource_portfolio.robustness import ScenarioSet, StressReport
from ruler.contracts.common import StrictContract
from ruler.io import stable_hash
from ruler.optimization.contracts import OptimizationProblem, OptimizationStatus


class CoverageExclusion(StrictContract):
    """A reviewed boundary that an explanation must not imply was tested."""

    dimension: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    origin_refs: tuple[str, ...] = Field(min_length=1)


class ScenarioCoverageDeclaration(StrictContract):
    """Human-reviewed scope needed to name the limits of a finite experiment."""

    coverage_id: str = Field(min_length=1)
    planning_horizon: str = Field(min_length=1)
    investigated_question: str = Field(min_length=1)
    exclusions: tuple[CoverageExclusion, ...] = Field(min_length=1)
    origin_refs: tuple[str, ...] = Field(min_length=1)


class TestedParameterRange(StrictContract):
    parameter_id: str
    minimum_multiplier: Decimal
    maximum_multiplier: Decimal
    tested_values: tuple[Decimal, ...]
    scenario_ids: tuple[str, ...]
    assumption_refs: tuple[str, ...]


class TestedScenarioExecution(StrictContract):
    scenario_id: str
    probability: Decimal = Field(gt=0, le=1)
    parameter_multipliers: dict[str, Decimal]
    assumption_refs: tuple[str, ...] = Field(min_length=1)
    status: str
    objective_value: Decimal | None


class ExecutedAnalysisClass(StrictContract):
    analysis_kind: Literal[
        "parameter_stress",
        "same_model_exclusion",
        "variable_forcedness",
        "constraint_ablation",
        "policy_sensitivity",
    ]
    run_count: int = Field(ge=0)
    statuses: dict[str, int]
    changes_approved_model: bool


class ScenarioEnvelopeExplanation(StrictContract):
    """Digest-closed statement of finite tested coverage and declared omissions."""

    schema_version: Literal["resource-scenario-envelope-explanation/v1"] = (
        "resource-scenario-envelope-explanation/v1"
    )
    coverage_id: str
    planning_horizon: str
    investigated_question: str
    base_model_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    scenario_set_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    scenario_count: int = Field(gt=0)
    tested_scenarios: tuple[TestedScenarioExecution, ...] = Field(min_length=1)
    tested_parameters: tuple[TestedParameterRange, ...] = Field(min_length=1)
    executed_analysis_classes: tuple[ExecutedAnalysisClass, ...] = Field(min_length=1)
    all_stress_runs_solved: bool
    distinct_assignment_count: int = Field(ge=0)
    assignment_stable_across_tested_scenarios: bool
    objective_minimum: Decimal | None
    objective_maximum: Decimal | None
    expected_objective: Decimal | None
    conditional_value_at_risk: Decimal | None
    exclusions: tuple[CoverageExclusion, ...] = Field(min_length=1)
    scope_origin_refs: tuple[str, ...] = Field(min_length=1)
    coverage_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def digest_closes(self) -> "ScenarioEnvelopeExplanation":
        expected = stable_hash(self.model_dump(mode="json", exclude={"coverage_sha256"}))
        if self.coverage_sha256 != expected:
            raise ValueError("coverage_sha256 does not authenticate the explanation")
        return self


class ObjectiveTermContribution(StrictContract):
    variable_id: str
    coefficient: Decimal
    selected_value: Decimal
    contribution: Decimal
    objective_origin_refs: tuple[str, ...] = Field(min_length=1)
    variable_origin_refs: tuple[str, ...] = Field(min_length=1)
    grounding_binding_id: str | None = None
    grounding_span_id: str | None = None


class ObjectiveConstantContribution(StrictContract):
    constant: Decimal
    contribution: Decimal
    objective_origin_refs: tuple[str, ...] = Field(min_length=1)
    grounding_binding_id: str | None = None
    grounding_span_id: str | None = None


class CostContrast(StrictContract):
    comparison_kind: Literal["same_model_alternative", "policy_sensitivity"]
    changes_approved_model: bool
    available: bool
    compared_objective_value: Decimal | None
    selected_minus_compared: Decimal | None


class CostObjectiveExplanation(StrictContract):
    """Exact, digest-closed decomposition of one verified objective component."""

    schema_version: Literal["resource-cost-objective-explanation/v1"] = (
        "resource-cost-objective-explanation/v1"
    )
    problem_id: str
    model_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    result_semantic_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    objective_id: str
    objective_sense: Literal["minimize", "maximize"]
    objective_unit: str
    objective_component: str
    objective_priority: int = Field(ge=0)
    time_basis: str = Field(min_length=1)
    time_basis_origin_refs: tuple[str, ...] = Field(min_length=1)
    terms: tuple[ObjectiveTermContribution, ...]
    constant: ObjectiveConstantContribution
    reconstructed_objective_value: Decimal
    verified_objective_value: Decimal
    grounding_complete: bool
    contrasts: tuple[CostContrast, ...]
    explanation_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @model_validator(mode="after")
    def arithmetic_and_digest_close(self) -> "CostObjectiveExplanation":
        reconstructed = self.constant.contribution + sum(
            (term.contribution for term in self.terms), Decimal(0)
        )
        if reconstructed != self.reconstructed_objective_value:
            raise ValueError("objective contribution arithmetic does not close")
        if reconstructed != self.verified_objective_value:
            raise ValueError("reconstructed objective differs from verified objective")
        expected = stable_hash(self.model_dump(mode="json", exclude={"explanation_sha256"}))
        if self.explanation_sha256 != expected:
            raise ValueError("explanation_sha256 does not authenticate the explanation")
        return self


def build_scenario_envelope_explanation(
    problem: OptimizationProblem,
    scenario_set: ScenarioSet,
    stress: StressReport,
    declaration: ScenarioCoverageDeclaration,
    *,
    certificate: DecisionArgumentCertificate | None = None,
) -> ScenarioEnvelopeExplanation:
    """Summarize only executed scenario evidence, preserving finite-test limits."""

    if stress.base_model_digest != problem.digest:
        raise ValueError("stress report is not bound to the supplied base model")
    if stress.scenario_set_digest != scenario_set.digest:
        raise ValueError("stress report is not bound to the supplied scenario set")
    expected_ids = {scenario.scenario_id for scenario in scenario_set.scenarios}
    outcome_ids = {outcome.scenario_id for outcome in stress.outcomes}
    if expected_ids != outcome_ids or len(stress.outcomes) != len(expected_ids):
        raise ValueError("stress report must contain exactly one outcome per scenario")
    for outcome in stress.outcomes:
        if outcome.result.model_digest != outcome.variant_model_digest:
            raise ValueError("stress outcome is not bound to its variant model")
    if certificate is not None and certificate.base_model_digest != problem.digest:
        raise ValueError("decision certificate is not bound to the supplied base model")

    parameter_ids = sorted(
        {
            parameter_id
            for scenario in scenario_set.scenarios
            for parameter_id in scenario.parameter_multipliers
        }
    )
    if not parameter_ids:
        raise ValueError("scenario set must vary at least one typed parameter")
    parameter_ranges = []
    for parameter_id in parameter_ids:
        applicable = list(scenario_set.scenarios)
        values = tuple(
            sorted(
                {
                    scenario.parameter_multipliers.get(parameter_id, Decimal(1))
                    for scenario in applicable
                }
            )
        )
        parameter_ranges.append(
            TestedParameterRange(
                parameter_id=parameter_id,
                minimum_multiplier=min(values),
                maximum_multiplier=max(values),
                tested_values=values,
                scenario_ids=tuple(sorted(scenario.scenario_id for scenario in applicable)),
                assumption_refs=tuple(
                    sorted({ref for scenario in applicable for ref in scenario.assumption_refs})
                ),
            )
        )

    status_counts: dict[str, int] = {}
    feasible_assignments = []
    objective_values = []
    for outcome in stress.outcomes:
        status_counts[outcome.result.status.value] = (
            status_counts.get(outcome.result.status.value, 0) + 1
        )
        if outcome.result.status in {OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE}:
            feasible_assignments.append(tuple(sorted(outcome.result.assignments.items())))
        if outcome.result.objective_value is not None:
            objective_values.append(outcome.result.objective_value)

    classes = [
        ExecutedAnalysisClass(
            analysis_kind="parameter_stress",
            run_count=len(stress.outcomes),
            statuses=dict(sorted(status_counts.items())),
            changes_approved_model=True,
        )
    ]
    if certificate is not None:
        classes.extend(_certificate_analysis_classes(certificate))
    all_solved = all(
        outcome.result.status in {OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE}
        for outcome in stress.outcomes
    )
    distinct_assignments = len(set(feasible_assignments))
    outcomes = {outcome.scenario_id: outcome for outcome in stress.outcomes}
    tested_scenarios = tuple(
        TestedScenarioExecution(
            scenario_id=scenario.scenario_id,
            probability=scenario.probability,
            parameter_multipliers=scenario.parameter_multipliers,
            assumption_refs=scenario.assumption_refs,
            status=outcomes[scenario.scenario_id].result.status.value,
            objective_value=outcomes[scenario.scenario_id].result.objective_value,
        )
        for scenario in scenario_set.scenarios
    )
    payload = {
        "coverage_id": declaration.coverage_id,
        "planning_horizon": declaration.planning_horizon,
        "investigated_question": declaration.investigated_question,
        "base_model_digest": problem.digest,
        "scenario_set_digest": scenario_set.digest,
        "scenario_count": len(scenario_set.scenarios),
        "tested_scenarios": tested_scenarios,
        "tested_parameters": tuple(parameter_ranges),
        "executed_analysis_classes": tuple(classes),
        "all_stress_runs_solved": all_solved,
        "distinct_assignment_count": distinct_assignments,
        "assignment_stable_across_tested_scenarios": all_solved and distinct_assignments == 1,
        "objective_minimum": min(objective_values) if objective_values else None,
        "objective_maximum": max(objective_values) if objective_values else None,
        "expected_objective": stress.risk.expected_loss if stress.risk else None,
        "conditional_value_at_risk": (
            stress.risk.conditional_value_at_risk if stress.risk else None
        ),
        "exclusions": declaration.exclusions,
        "scope_origin_refs": declaration.origin_refs,
    }
    serialized = {
        **payload,
        "schema_version": "resource-scenario-envelope-explanation/v1",
    }
    return ScenarioEnvelopeExplanation(
        **payload,
        coverage_sha256=stable_hash(
            ScenarioEnvelopeExplanation.model_construct(
                **serialized, coverage_sha256=""
            ).model_dump(mode="json", exclude={"coverage_sha256"})
        ),
    )


def _certificate_analysis_classes(
    certificate: DecisionArgumentCertificate,
) -> list[ExecutedAnalysisClass]:
    classes = []
    same_model = certificate.same_model_alternative.probe.result.status.value
    classes.append(
        ExecutedAnalysisClass(
            analysis_kind="same_model_exclusion",
            run_count=1,
            statuses={same_model: 1},
            changes_approved_model=False,
        )
    )
    for kind, probes in (
        ("variable_forcedness", tuple(item.probe for item in certificate.variable_forcedness)),
        ("constraint_ablation", tuple(item.probe for item in certificate.constraint_roles)),
    ):
        statuses: dict[str, int] = {}
        for probe in probes:
            status = probe.result.status.value
            statuses[status] = statuses.get(status, 0) + 1
        classes.append(
            ExecutedAnalysisClass.model_validate(
                dict(
                    analysis_kind=kind,
                    run_count=len(probes),
                    statuses=dict(sorted(statuses.items())),
                    changes_approved_model=kind == "constraint_ablation",
                )
            )
        )
    if certificate.policy_sensitivity is not None:
        status = certificate.policy_sensitivity.run.result.status.value
        classes.append(
            ExecutedAnalysisClass(
                analysis_kind="policy_sensitivity",
                run_count=1,
                statuses={status: 1},
                changes_approved_model=True,
            )
        )
    return classes


def build_cost_objective_explanation(
    problem: OptimizationProblem,
    plan: VerifiedPlan,
    *,
    objective_id: str,
    time_basis: str,
    time_basis_origin_refs: tuple[str, ...],
    grounding: DemonstratorGrounding | None = None,
    certificate: DecisionArgumentCertificate | None = None,
) -> CostObjectiveExplanation:
    """Reconstruct one verified cost objective from constants and selected terms."""

    if not time_basis.strip() or not time_basis_origin_refs:
        raise ValueError("time basis and its origin references are required")
    if plan.result.model_digest != problem.digest or (
        plan.verification.model_digest != problem.digest
    ):
        raise ValueError("verified plan is not bound to the supplied model")
    if not plan.verification.verified:
        raise ValueError("cost explanation requires an independently verified plan")
    objective = next(
        (item for item in problem.objectives if item.objective_id == objective_id), None
    )
    if objective is None:
        raise ValueError(f"unknown objective {objective_id}")
    verified_value = plan.verification.objective_values.get(objective_id)
    if verified_value is None:
        raise ValueError("verification does not contain the requested objective")
    if certificate is not None and (
        certificate.base_model_digest != problem.digest
        or certificate.objective_id != objective_id
        or certificate.selected_assignment != plan.result.assignments
    ):
        raise ValueError("decision certificate does not authenticate this objective")

    variables = {item.variable_id: item for item in problem.variables}
    term_groundings = (
        {(item.objective_id, item.variable_id): item for item in grounding.objective_term_bindings}
        if grounding
        else {}
    )
    constant_groundings = (
        {item.objective_id: item for item in grounding.objective_constant_bindings}
        if grounding
        else {}
    )
    terms = []
    for term in objective.expression.terms:
        selected_value = plan.result.assignments[term.variable_id]
        binding = term_groundings.get((objective_id, term.variable_id))
        if binding is not None and (
            binding.coefficient != term.coefficient
            or binding.objective_sense != objective.sense
            or binding.objective_priority != objective.priority
            or binding.objective_unit != objective.unit
            or binding.objective_component != objective.component
            or binding.objective_origin_refs != objective.origin_refs
        ):
            raise ValueError("objective term grounding contradicts the supplied model")
        terms.append(
            ObjectiveTermContribution(
                variable_id=term.variable_id,
                coefficient=term.coefficient,
                selected_value=selected_value,
                contribution=term.coefficient * selected_value,
                objective_origin_refs=objective.origin_refs,
                variable_origin_refs=variables[term.variable_id].origin_refs,
                grounding_binding_id=binding.binding_id if binding else None,
                grounding_span_id=binding.span.span_id if binding else None,
            )
        )
    constant_binding = constant_groundings.get(objective_id)
    if constant_binding is not None and (
        constant_binding.constant != objective.expression.constant
        or constant_binding.objective_sense != objective.sense
        or constant_binding.objective_priority != objective.priority
        or constant_binding.objective_unit != objective.unit
        or constant_binding.objective_component != objective.component
        or constant_binding.objective_origin_refs != objective.origin_refs
    ):
        raise ValueError("objective constant grounding contradicts the supplied model")
    constant = ObjectiveConstantContribution(
        constant=objective.expression.constant,
        contribution=objective.expression.constant,
        objective_origin_refs=objective.origin_refs,
        grounding_binding_id=constant_binding.binding_id if constant_binding else None,
        grounding_span_id=constant_binding.span.span_id if constant_binding else None,
    )
    terms_grounded = all(item.grounding_binding_id is not None for item in terms)
    constant_grounded = objective.expression.constant == 0 or constant_binding is not None
    grounding_complete = grounding is not None and terms_grounded and constant_grounded
    reconstructed = constant.contribution + sum((term.contribution for term in terms), Decimal(0))
    contrasts = _cost_contrasts(certificate) if certificate else ()
    payload = {
        "problem_id": problem.problem_id,
        "model_digest": problem.digest,
        "result_semantic_digest": plan.result.semantic_digest,
        "objective_id": objective.objective_id,
        "objective_sense": objective.sense,
        "objective_unit": objective.unit,
        "objective_component": objective.component,
        "objective_priority": objective.priority,
        "time_basis": time_basis,
        "time_basis_origin_refs": time_basis_origin_refs,
        "terms": tuple(terms),
        "constant": constant,
        "reconstructed_objective_value": reconstructed,
        "verified_objective_value": verified_value,
        "grounding_complete": grounding_complete,
        "contrasts": contrasts,
    }
    serialized = {**payload, "schema_version": "resource-cost-objective-explanation/v1"}
    return CostObjectiveExplanation(
        **payload,
        explanation_sha256=stable_hash(
            CostObjectiveExplanation.model_construct(
                **serialized, explanation_sha256=""
            ).model_dump(mode="json", exclude={"explanation_sha256"})
        ),
    )


def _cost_contrasts(
    certificate: DecisionArgumentCertificate,
) -> tuple[CostContrast, ...]:
    alternative = certificate.same_model_alternative
    output = [
        CostContrast(
            comparison_kind="same_model_alternative",
            changes_approved_model=False,
            available=alternative.alternative_objective_value is not None,
            compared_objective_value=alternative.alternative_objective_value,
            selected_minus_compared=(
                certificate.selected_objective_value - alternative.alternative_objective_value
                if alternative.alternative_objective_value is not None
                else None
            ),
        )
    ]
    sensitivity = certificate.policy_sensitivity
    if sensitivity is not None:
        value = sensitivity.run.result.objective_value
        output.append(
            CostContrast(
                comparison_kind="policy_sensitivity",
                changes_approved_model=True,
                available=value is not None,
                compared_objective_value=value,
                selected_minus_compared=(
                    certificate.selected_objective_value - value if value is not None else None
                ),
            )
        )
    return tuple(output)


__all__ = [
    "CostContrast",
    "CostObjectiveExplanation",
    "CoverageExclusion",
    "ExecutedAnalysisClass",
    "ObjectiveConstantContribution",
    "ObjectiveTermContribution",
    "ScenarioCoverageDeclaration",
    "ScenarioEnvelopeExplanation",
    "TestedScenarioExecution",
    "TestedParameterRange",
    "build_cost_objective_explanation",
    "build_scenario_envelope_explanation",
]
