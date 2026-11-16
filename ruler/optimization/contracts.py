# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Strict, unit-aware linear and scenario optimization contracts.

The representation deliberately contains no executable strings.  Every expression is
a closed list of coefficients over declared, finitely bounded variables.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.io import stable_hash


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OptimizationStatus(StrEnum):
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    UNBOUNDED = "UNBOUNDED"
    TIME_LIMIT = "TIME_LIMIT"
    ERROR = "ERROR"


class OptimizationVariable(StrictModel):
    variable_id: str = Field(min_length=1)
    domain: Literal["binary", "integer", "continuous"]
    lower_bound: Decimal
    upper_bound: Decimal
    unit: str = Field(min_length=1)
    stage: Literal["here_and_now", "recourse"] = "here_and_now"
    scenario_id: str | None = None
    information_set: str | None = None
    decision_key: str | None = None
    origin_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_bounds(self) -> "OptimizationVariable":
        if not self.lower_bound.is_finite() or not self.upper_bound.is_finite():
            raise ValueError("optimization variables require finite bounds")
        if self.lower_bound > self.upper_bound:
            raise ValueError("variable lower_bound exceeds upper_bound")
        if self.domain == "binary" and (self.lower_bound < 0 or self.upper_bound > 1):
            raise ValueError("binary bounds must lie within [0, 1]")
        if self.stage == "recourse" and not self.scenario_id:
            raise ValueError("recourse variables require scenario_id")
        if self.stage == "recourse" and (not self.information_set or not self.decision_key):
            raise ValueError("recourse variables require information_set and decision_key")
        if self.stage == "here_and_now" and self.scenario_id is not None:
            raise ValueError("here-and-now variables cannot name a scenario")
        return self


class LinearTerm(StrictModel):
    variable_id: str = Field(min_length=1)
    coefficient: Decimal


class LinearExpression(StrictModel):
    terms: tuple[LinearTerm, ...] = ()
    constant: Decimal = Decimal(0)

    @model_validator(mode="after")
    def unique_terms(self) -> "LinearExpression":
        ids = [term.variable_id for term in self.terms]
        if len(ids) != len(set(ids)):
            raise ValueError("linear expression contains duplicate variable terms")
        if not self.constant.is_finite() or any(
            not term.coefficient.is_finite() for term in self.terms
        ):
            raise ValueError("linear expressions require finite coefficients")
        return self


class LinearConstraint(StrictModel):
    constraint_id: str = Field(min_length=1)
    expression: LinearExpression
    sense: Literal["<=", "=", ">="]
    rhs: Decimal
    unit: str = Field(min_length=1)
    hard: bool = True
    penalty: Decimal | None = Field(default=None, ge=0)
    origin_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_softness(self) -> "LinearConstraint":
        if not self.rhs.is_finite():
            raise ValueError("constraint RHS must be finite")
        if self.hard and self.penalty is not None:
            raise ValueError("hard constraints cannot have a penalty")
        if not self.hard and self.penalty is None:
            raise ValueError("soft constraints require a penalty")
        return self


class LinearObjective(StrictModel):
    objective_id: str = Field(min_length=1)
    expression: LinearExpression
    sense: Literal["minimize", "maximize"] = "minimize"
    priority: int = Field(default=0, ge=0)
    unit: str = Field(min_length=1)
    component: Literal[
        "lifecycle",
        "operation",
        "service",
        "movement",
        "external_supply",
        "shortfall",
        "rule_penalty",
        "risk",
        "emissions",
        "plan_stability",
        "other",
    ] = "other"
    origin_refs: tuple[str, ...] = Field(min_length=1)


class Scenario(StrictModel):
    scenario_id: str = Field(min_length=1)
    probability: Decimal = Field(gt=0, le=1)
    information_set: str = Field(min_length=1)
    parameter_multipliers: dict[str, Decimal] = Field(default_factory=dict)
    assumption_refs: tuple[str, ...] = Field(min_length=1)


class OptimizationProblem(StrictModel):
    schema_version: Literal["resource-optimization-ir/v1"] = "resource-optimization-ir/v1"
    problem_id: str = Field(min_length=1)
    snapshot_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    variables: tuple[OptimizationVariable, ...] = Field(min_length=1)
    constraints: tuple[LinearConstraint, ...] = ()
    objectives: tuple[LinearObjective, ...] = Field(min_length=1)
    scenarios: tuple[Scenario, ...] = ()
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def closed_references(self) -> "OptimizationProblem":
        variable_ids = [variable.variable_id for variable in self.variables]
        if len(variable_ids) != len(set(variable_ids)):
            raise ValueError("variable IDs must be unique")
        constraint_ids = [constraint.constraint_id for constraint in self.constraints]
        if len(constraint_ids) != len(set(constraint_ids)):
            raise ValueError("constraint IDs must be unique")
        objective_ids = [objective.objective_id for objective in self.objectives]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("objective IDs must be unique")
        known = set(variable_ids)
        referenced = {
            term.variable_id
            for expression in (
                [constraint.expression for constraint in self.constraints]
                + [objective.expression for objective in self.objectives]
            )
            for term in expression.terms
        }
        if referenced - known:
            raise ValueError(
                f"expressions reference unknown variables: {sorted(referenced - known)}"
            )
        scenario_ids = [scenario.scenario_id for scenario in self.scenarios]
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("scenario IDs must be unique")
        if self.scenarios and sum((item.probability for item in self.scenarios), Decimal(0)) != 1:
            raise ValueError("scenario probabilities must sum exactly to 1")
        unknown_scenarios = {
            variable.scenario_id for variable in self.variables if variable.scenario_id
        } - set(scenario_ids)
        if unknown_scenarios:
            raise ValueError(f"variables reference unknown scenarios: {sorted(unknown_scenarios)}")
        return self

    @property
    def digest(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class BackendReceipt(StrictModel):
    backend_id: Literal["pyomo_highs"] = "pyomo_highs"
    library: Literal["highspy"] = "highspy"
    library_version: str
    adapter: Literal["pyomo.contrib.appsi.solvers.highs.Highs"] = (
        "pyomo.contrib.appsi.solvers.highs.Highs"
    )
    model_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    seed: int
    threads: int
    time_limit_seconds: float | None
    native_termination_condition: str
    native_best_feasible_objective: Decimal | None = None
    native_best_objective_bound: Decimal | None = None


class OptimizationResult(StrictModel):
    schema_version: Literal["resource-optimization-result/v1"] = "resource-optimization-result/v1"
    problem_id: str
    model_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    status: OptimizationStatus
    assignments: dict[str, Decimal] = Field(default_factory=dict)
    objective_value: Decimal | None = None
    objective_bound: Decimal | None = None
    relative_gap: Decimal | None = Field(default=None, ge=0)
    objective_components: dict[str, Decimal] = Field(default_factory=dict)
    variable_count: int = Field(ge=0)
    constraint_count: int = Field(ge=0)
    runtime_seconds: float = Field(ge=0)
    receipt: BackendReceipt

    @property
    def semantic_digest(self) -> str:
        data = self.model_dump(mode="json", exclude={"runtime_seconds"})
        return stable_hash(data)
