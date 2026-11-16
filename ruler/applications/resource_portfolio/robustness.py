# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic scenarios, CVaR, non-anticipativity, and executed counterfactuals."""

from __future__ import annotations

import random
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.io import stable_hash
from ruler.optimization.contracts import OptimizationProblem, OptimizationResult, Scenario
from ruler.optimization.highs import solve_highs


class ScenarioFactor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    parameter_id: str
    low: Decimal
    high: Decimal

    @model_validator(mode="after")
    def ordered(self) -> "ScenarioFactor":
        if self.low > self.high:
            raise ValueError("scenario factor low exceeds high")
        return self


class ScenarioSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["resource-scenarios/v1"] = "resource-scenarios/v1"
    scenario_set_id: str
    seed: int
    scenarios: tuple[Scenario, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def probability_measure(self) -> "ScenarioSet":
        ids = [item.scenario_id for item in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario IDs must be unique")
        if sum((item.probability for item in self.scenarios), Decimal(0)) != 1:
            raise ValueError("scenario probabilities must sum exactly to 1")
        return self

    @property
    def digest(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


def build_scenarios(
    scenario_set_id: str,
    factors: tuple[ScenarioFactor, ...],
    *,
    count: int,
    seed: int,
    assumption_refs: tuple[str, ...],
) -> ScenarioSet:
    """Create a reproducible joint scenario set from bounded factors."""
    if count < 1:
        raise ValueError("scenario count must be positive")
    if not factors or not assumption_refs:
        raise ValueError("scenario factors and assumption refs are required")
    rng = random.Random(seed)
    base = Decimal(1) / Decimal(count)
    remaining = Decimal(1)
    scenarios = []
    for index in range(count):
        probability = remaining if index == count - 1 else base
        remaining -= probability
        multipliers = {
            factor.parameter_id: factor.low
            + (factor.high - factor.low) * Decimal(str(rng.random()))
            for factor in factors
        }
        scenarios.append(
            Scenario(
                scenario_id=f"scenario-{index + 1:04d}",
                probability=probability,
                information_set="initial",
                parameter_multipliers=multipliers,
                assumption_refs=assumption_refs,
            )
        )
    return ScenarioSet(scenario_set_id=scenario_set_id, seed=seed, scenarios=tuple(scenarios))


class CVarResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    alpha: Decimal
    value_at_risk: Decimal
    conditional_value_at_risk: Decimal
    expected_loss: Decimal


def calculate_cvar(
    losses: dict[str, Decimal], scenarios: tuple[Scenario, ...], alpha: Decimal
) -> CVarResult:
    """Calculate finite-distribution CVaR by the exact linear zeta formulation."""
    if not Decimal(0) <= alpha < Decimal(1):
        raise ValueError("alpha must lie in [0, 1)")
    scenario_ids = {item.scenario_id for item in scenarios}
    if set(losses) != scenario_ids:
        raise ValueError("losses must name every scenario exactly once")
    candidates = sorted(set(losses.values()))
    scored = []
    for zeta in candidates:
        excess = sum(
            scenario.probability * max(Decimal(0), losses[scenario.scenario_id] - zeta)
            for scenario in scenarios
        )
        scored.append((zeta + excess / (Decimal(1) - alpha), zeta))
    cvar, zeta = min(scored)
    expected = sum(item.probability * losses[item.scenario_id] for item in scenarios)
    return CVarResult.model_validate(
        dict(
            alpha=alpha, value_at_risk=zeta, conditional_value_at_risk=cvar, expected_loss=expected
        )
    )


class NonAnticipativityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    valid: bool
    violations: tuple[str, ...]


def check_non_anticipativity(
    assignments_by_scenario: dict[str, dict[str, Decimal]],
    information_sets: dict[str, str],
    here_and_now_variable_ids: tuple[str, ...],
) -> NonAnticipativityReport:
    """Ensure declared here-and-now decisions agree within an information set."""
    violations = []
    grouped: dict[str, list[str]] = {}
    for scenario_id, info_set in information_sets.items():
        grouped.setdefault(info_set, []).append(scenario_id)
    for info_set, scenario_ids in grouped.items():
        for variable_id in here_and_now_variable_ids:
            values = {
                assignments_by_scenario[scenario_id].get(variable_id)
                for scenario_id in scenario_ids
            }
            if len(values) > 1:
                violations.append(f"{info_set}:{variable_id}")
    return NonAnticipativityReport(valid=not violations, violations=tuple(sorted(violations)))


class CounterfactualChange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["constraint_rhs", "objective_coefficient", "variable_upper_bound"]
    target_id: str
    value: Decimal
    variable_id: str | None = None


class CounterfactualRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    run_id: str
    base_model_digest: str
    variant_model_digest: str
    transformation_digest: str
    result: OptimizationResult


class ScenarioOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scenario_id: str
    probability: Decimal
    variant_model_digest: str
    result: OptimizationResult


class StressReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    base_model_digest: str
    scenario_set_digest: str
    outcomes: tuple[ScenarioOutcome, ...]
    risk: CVarResult | None


def apply_counterfactual(
    problem: OptimizationProblem, changes: tuple[CounterfactualChange, ...]
) -> OptimizationProblem:
    """Apply a typed transformation and fully revalidate the resulting IR."""
    payload = problem.model_dump(mode="python")
    for change in changes:
        if change.kind == "constraint_rhs":
            target = next(
                (
                    item
                    for item in payload["constraints"]
                    if item["constraint_id"] == change.target_id
                ),
                None,
            )
            if target is None:
                raise ValueError(f"unknown constraint {change.target_id}")
            target["rhs"] = change.value
        elif change.kind == "variable_upper_bound":
            target = next(
                (item for item in payload["variables"] if item["variable_id"] == change.target_id),
                None,
            )
            if target is None:
                raise ValueError(f"unknown variable {change.target_id}")
            target["upper_bound"] = change.value
        else:
            objective = next(
                (
                    item
                    for item in payload["objectives"]
                    if item["objective_id"] == change.target_id
                ),
                None,
            )
            if objective is None or change.variable_id is None:
                raise ValueError(
                    "objective coefficient change requires a known objective and variable_id"
                )
            term = next(
                (
                    item
                    for item in objective["expression"]["terms"]
                    if item["variable_id"] == change.variable_id
                ),
                None,
            )
            if term is None:
                raise ValueError("objective does not contain requested variable")
            term["coefficient"] = change.value
    return OptimizationProblem.model_validate(payload)


def run_counterfactual(
    problem: OptimizationProblem,
    changes: tuple[CounterfactualChange, ...],
    *,
    run_id: str,
    seed: int = 0,
) -> CounterfactualRun:
    variant = apply_counterfactual(problem, changes)
    result = solve_highs(variant, seed=seed, threads=1)
    return CounterfactualRun(
        run_id=run_id,
        base_model_digest=problem.digest,
        variant_model_digest=variant.digest,
        transformation_digest=stable_hash([item.model_dump(mode="json") for item in changes]),
        result=result,
    )


def solve_stress_scenario(
    problem: OptimizationProblem, scenario: Scenario, seed: int
) -> ScenarioOutcome:
    """Derive one variant independently from the base and execute its native solve."""
    changes = []
    for parameter_id, multiplier in sorted(scenario.parameter_multipliers.items()):
        parts = parameter_id.split(":")
        if parts[0] == "constraint_rhs" and len(parts) == 2:
            constraint = next(
                (item for item in problem.constraints if item.constraint_id == parts[1]), None
            )
            if constraint is None:
                raise ValueError(f"unknown scenario constraint target {parts[1]}")
            changes.append(
                CounterfactualChange(
                    kind="constraint_rhs",
                    target_id=parts[1],
                    value=constraint.rhs * multiplier,
                )
            )
        elif parts[0] == "objective_term" and len(parts) == 3:
            objective = next(
                (item for item in problem.objectives if item.objective_id == parts[1]), None
            )
            term = (
                next(
                    (item for item in objective.expression.terms if item.variable_id == parts[2]),
                    None,
                )
                if objective
                else None
            )
            if term is None:
                raise ValueError(f"unknown scenario objective target {parameter_id}")
            changes.append(
                CounterfactualChange(
                    kind="objective_coefficient",
                    target_id=parts[1],
                    variable_id=parts[2],
                    value=term.coefficient * multiplier,
                )
            )
        else:
            raise ValueError(f"unsupported scenario parameter path {parameter_id}")
    variant = apply_counterfactual(problem, tuple(changes))
    result = solve_highs(variant, seed=seed, threads=1)
    return ScenarioOutcome(
        scenario_id=scenario.scenario_id,
        probability=scenario.probability,
        variant_model_digest=variant.digest,
        result=result,
    )


def stress_test(
    problem: OptimizationProblem,
    scenario_set: ScenarioSet,
    *,
    alpha: Decimal = Decimal("0.95"),
) -> StressReport:
    """Execute one full HiGHS re-solve per scenario and calculate objective CVaR.

    Factor identifiers are explicit typed paths: ``constraint_rhs:<id>`` and
    ``objective_term:<objective-id>:<variable-id>``. Unknown paths fail closed.
    """
    outcomes = []
    losses: dict[str, Decimal] = {}
    for scenario in scenario_set.scenarios:
        outcome = solve_stress_scenario(problem, scenario, scenario_set.seed)
        outcomes.append(outcome)
        if outcome.result.objective_value is not None:
            losses[scenario.scenario_id] = outcome.result.objective_value
    return finish_stress(problem, scenario_set, tuple(outcomes), losses, alpha=alpha)


def finish_stress(
    problem: OptimizationProblem,
    scenario_set: ScenarioSet,
    outcomes: tuple[ScenarioOutcome, ...],
    losses: dict[str, Decimal],
    *,
    alpha: Decimal = Decimal("0.95"),
) -> StressReport:
    """Build the source-owned stress report from the complete accumulated history."""
    risk = (
        calculate_cvar(losses, scenario_set.scenarios, alpha)
        if len(losses) == len(outcomes)
        else None
    )
    return StressReport(
        base_model_digest=problem.digest,
        scenario_set_digest=scenario_set.digest,
        outcomes=tuple(outcomes),
        risk=risk,
    )
