# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Independent Decimal arithmetic verification of optimization results."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ruler.io import stable_hash
from ruler.optimization.contracts import LinearExpression, OptimizationProblem, OptimizationResult


class ConstraintCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    constraint_id: str
    lhs: Decimal
    rhs: Decimal
    sense: str
    satisfied: bool
    violation: Decimal = Field(ge=0)
    origin_refs: tuple[str, ...]


class VerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    problem_id: str
    model_digest: str
    result_semantic_digest: str
    verified: bool
    assignment_violations: tuple[str, ...]
    constraint_checks: tuple[ConstraintCheck, ...]
    objective_values: dict[str, Decimal]
    verification_backend: str = "independent_decimal_arithmetic/v1"

    @property
    def digest(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


def evaluate(expression: LinearExpression, assignments: dict[str, Decimal]) -> Decimal:
    return expression.constant + sum(
        term.coefficient * assignments[term.variable_id] for term in expression.terms
    )


def verify_result(
    problem: OptimizationProblem,
    result: OptimizationResult,
    *,
    tolerance: Decimal = Decimal("1e-7"),
) -> VerificationReport:
    """Verify bounds, integrality, every named constraint, and objectives.

    This module never imports Pyomo or the backend adapter.
    """
    if result.model_digest != problem.digest or result.problem_id != problem.problem_id:
        raise ValueError("result is not bound to this problem")
    violations: list[str] = []
    known = {variable.variable_id for variable in problem.variables}
    if set(result.assignments) != known:
        violations.append("assignment_variable_set_mismatch")
    for variable in problem.variables:
        value = result.assignments.get(variable.variable_id)
        if value is None:
            continue
        if value < variable.lower_bound - tolerance or value > variable.upper_bound + tolerance:
            violations.append(f"bound:{variable.variable_id}")
        if (
            variable.domain in {"binary", "integer"}
            and abs(value - value.to_integral_value()) > tolerance
        ):
            violations.append(f"integrality:{variable.variable_id}")
    checks: list[ConstraintCheck] = []
    if set(result.assignments) == known:
        for constraint in problem.constraints:
            lhs = evaluate(constraint.expression, result.assignments)
            if constraint.sense == "<=":
                violation = max(Decimal(0), lhs - constraint.rhs)
            elif constraint.sense == ">=":
                violation = max(Decimal(0), constraint.rhs - lhs)
            else:
                violation = abs(lhs - constraint.rhs)
            satisfied = violation <= tolerance or not constraint.hard
            checks.append(
                ConstraintCheck(
                    constraint_id=constraint.constraint_id,
                    lhs=lhs,
                    rhs=constraint.rhs,
                    sense=constraint.sense,
                    satisfied=satisfied,
                    violation=violation,
                    origin_refs=constraint.origin_refs,
                )
            )
    objectives = {
        objective.objective_id: evaluate(objective.expression, result.assignments)
        for objective in problem.objectives
        if set(result.assignments) == known
    }
    return VerificationReport(
        problem_id=problem.problem_id,
        model_digest=problem.digest,
        result_semantic_digest=result.semantic_digest,
        verified=not violations and all(check.satisfied for check in checks),
        assignment_violations=tuple(violations),
        constraint_checks=tuple(checks),
        objective_values=objectives,
    )
