# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Solver contract schema. It defines the variables, hard constraints, soft constraints,
objectives, rankings, and traces exchanged between RULER and optimization backends.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SolverVariable(BaseModel):
    """Typed solver variable artifact used by the solver contracts workflow."""

    model_config = ConfigDict(extra="forbid")

    variable_id: str
    variable_type: Literal["feature_selected"]
    feature_id: str
    label: str


class ExactlyOneConstraint(BaseModel):
    """Select exactly one variable from an explicit, closed set."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["exactly_one"] = "exactly_one"
    variable_ids: tuple[str, ...] = Field(min_length=1)


class CardinalityConstraint(BaseModel):
    """Bound the number of selected variables in an explicit set."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["cardinality"] = "cardinality"
    variable_ids: tuple[str, ...] = Field(min_length=1)
    minimum: int = Field(default=0, ge=0)
    maximum: int | None = Field(default=None, ge=0)

    def model_post_init(self, __context: object) -> None:
        if self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("cardinality minimum cannot exceed maximum")


class ForbidConstraint(BaseModel):
    """Force one variable to false."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["forbid"] = "forbid"
    variable_id: str


class RequiresConstraint(BaseModel):
    """A selected trigger requires another variable or a pre-satisfied external fact."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["requires"] = "requires"
    trigger_variable_id: str
    required_variable_id: str | None = None
    requirement_satisfied: bool = False

    # Missing + unsatisfied deliberately lowers to ``not trigger``. An unavailable
    # prerequisite must never be silently ignored.


class ExcludesConstraint(BaseModel):
    """Prevent two variables from being selected together."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["excludes"] = "excludes"
    left_variable_id: str
    right_variable_id: str


class BudgetTerm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    variable_id: str
    cost: int = Field(ge=0)


class BudgetConstraint(BaseModel):
    """Bound the selected weighted cost without parsing solver expressions."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["budget"] = "budget"
    terms: tuple[BudgetTerm, ...] = Field(min_length=1)
    limit: int = Field(ge=0)


HardConstraintExpression = Annotated[
    ExactlyOneConstraint
    | CardinalityConstraint
    | ForbidConstraint
    | RequiresConstraint
    | ExcludesConstraint
    | BudgetConstraint,
    Field(discriminator="kind"),
]


class HardConstraint(BaseModel):
    """Typed hard constraint artifact used by the solver contracts workflow."""

    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    label: str
    constraint: HardConstraintExpression
    # Human-readable legacy display only. It is never parsed or executed.
    expression: str | None = None
    trace_refs: list[str] = Field(default_factory=list)
    feature_id: str | None = None


class SoftConstraint(BaseModel):
    """Typed soft constraint artifact used by the solver contracts workflow."""

    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    label: str
    feature_id: str
    dimension_id: str
    weight: float
    utility: float
    weighted_score: float
    trace_refs: list[str] = Field(default_factory=list)


class ObjectiveTerm(BaseModel):
    """Typed objective term artifact used by the solver contracts workflow."""

    model_config = ConfigDict(extra="forbid")

    term_id: str
    feature_id: str
    label: str
    value: int
    trace_refs: list[str] = Field(default_factory=list)


class SolverProblem(BaseModel):
    """Backend-neutral optimization problem compiled from RULER reasoning artifacts."""

    model_config = ConfigDict(extra="forbid")

    problem_id: str
    case_id: str
    profile_id: str
    solver_backend: str
    variables: list[SolverVariable]
    hard_constraints: list[HardConstraint]
    soft_constraints: list[SoftConstraint]
    objective_terms: list[ObjectiveTerm]

    def model_post_init(self, __context: object) -> None:
        variable_ids = {item.variable_id for item in self.variables}
        if len(variable_ids) != len(self.variables):
            raise ValueError("solver variable IDs must be unique")
        feature_ids = {item.feature_id for item in self.variables}
        if len(feature_ids) != len(self.variables):
            raise ValueError("solver feature IDs must be unique")
        referenced: set[str] = set()
        for item in self.hard_constraints:
            value = item.constraint
            if isinstance(value, (ExactlyOneConstraint, CardinalityConstraint)):
                referenced.update(value.variable_ids)
            elif isinstance(value, ForbidConstraint):
                referenced.add(value.variable_id)
            elif isinstance(value, RequiresConstraint):
                referenced.add(value.trigger_variable_id)
                if value.required_variable_id is not None:
                    referenced.add(value.required_variable_id)
            elif isinstance(value, ExcludesConstraint):
                referenced.update((value.left_variable_id, value.right_variable_id))
            elif isinstance(value, BudgetConstraint):
                referenced.update(term.variable_id for term in value.terms)
        unknown = referenced - variable_ids
        if unknown:
            raise ValueError(f"hard constraints reference unknown variables: {sorted(unknown)}")
        unknown_objectives = {item.feature_id for item in self.objective_terms} - feature_ids
        if unknown_objectives:
            raise ValueError(
                f"objective terms reference unknown features: {sorted(unknown_objectives)}"
            )
        ids = [item.constraint_id for item in self.hard_constraints]
        if len(ids) != len(set(ids)):
            raise ValueError("hard constraint IDs must be unique")


class SolverAssignment(BaseModel):
    """Typed solver assignment artifact used by the solver contracts workflow."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    selected: bool
    rank: int
    objective_value: int


class SolverRanking(BaseModel):
    """Typed solver ranking artifact used by the solver contracts workflow."""

    model_config = ConfigDict(extra="forbid")

    rank: int
    feature_id: str
    objective_value: int
    solver_iteration: int
    selected: bool
    exclusion_constraint_ids: list[str] = Field(default_factory=list)


class ViolatedSoftConstraint(BaseModel):
    """Typed violated soft constraint artifact used by the solver contracts workflow."""

    model_config = ConfigDict(extra="forbid")

    constraint_id: str
    label: str
    feature_id: str
    dimension_id: str
    winner_utility: float
    best_available_utility: float
    opportunity_score: float


class SolverTrace(BaseModel):
    """Typed solver trace artifact used by the solver contracts workflow."""

    model_config = ConfigDict(extra="forbid")

    solver_backend: str
    status: Literal["optimal", "feasible", "infeasible"]
    objective_value: int
    selected_feature_ids: list[str]
    runner_up_feature_ids: list[str]
    top_ranked_features: list[SolverRanking]
    hard_constraint_ids: list[str]
    satisfied_soft_constraint_ids: list[str]
    violated_soft_constraints: list[ViolatedSoftConstraint]
    explanation_atoms: list[str]
    trace_refs: list[str]


class SolverResult(BaseModel):
    """Backend-neutral optimization result with ranking and trace details."""

    model_config = ConfigDict(extra="forbid")

    problem_id: str
    solver_backend: str
    status: Literal["optimal", "feasible", "infeasible"]
    objective_value: int
    assignments: list[SolverAssignment]
    trace: SolverTrace
