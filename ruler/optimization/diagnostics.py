# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Backend-neutral weighted elastic repair diagnostics."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ruler.optimization.contracts import (
    LinearConstraint,
    OptimizationProblem,
    OptimizationResult,
    OptimizationStatus,
)
from ruler.optimization.highs import solve_highs
from ruler.optimization.verification import evaluate


class RepairSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    constraint_id: str
    required_relaxation: Decimal
    unit: str
    origin_refs: tuple[str, ...]


class InfeasibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    original_model_digest: str
    original_status: OptimizationStatus
    relaxation_status: OptimizationStatus
    repairs: tuple[RepairSuggestion, ...]
    relaxation_result: OptimizationResult
    diagnostic_backend: str = "weighted_elastic_pyomo_highs/v1"


def diagnose_infeasibility(
    problem: OptimizationProblem,
    *,
    weights: dict[str, Decimal] | None = None,
) -> InfeasibilityReport:
    """Solve a separate elastic model and quantify minimum named repairs.

    The original model is solved first and its status is preserved.  Repair output
    therefore cannot relabel an infeasible source model as feasible.
    """
    original = solve_highs(problem, threads=1)
    if original.status not in {OptimizationStatus.INFEASIBLE, OptimizationStatus.UNBOUNDED}:
        raise ValueError("repair diagnostics require an infeasible or unbounded model")
    configured = weights or {}
    softened = tuple(
        LinearConstraint(
            constraint_id=item.constraint_id,
            expression=item.expression,
            sense=item.sense,
            rhs=item.rhs,
            unit=item.unit,
            hard=False,
            penalty=configured.get(item.constraint_id, Decimal(1)),
            origin_refs=item.origin_refs,
        )
        for item in problem.constraints
    )
    elastic = OptimizationProblem.model_validate(
        {
            **problem.model_dump(mode="python"),
            "problem_id": f"{problem.problem_id}:elastic-repair",
            "constraints": [item.model_dump(mode="python") for item in softened],
        }
    )
    relaxed = solve_highs(elastic, threads=1)
    repairs = []
    if relaxed.status in {OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE}:
        for item in problem.constraints:
            lhs = evaluate(item.expression, relaxed.assignments)
            violation = (
                max(Decimal(0), lhs - item.rhs)
                if item.sense == "<="
                else max(Decimal(0), item.rhs - lhs) if item.sense == ">=" else abs(lhs - item.rhs)
            )
            if violation > Decimal("1e-7"):
                repairs.append(
                    RepairSuggestion(
                        constraint_id=item.constraint_id,
                        required_relaxation=violation,
                        unit=item.unit,
                        origin_refs=item.origin_refs,
                    )
                )
    return InfeasibilityReport(
        original_model_digest=problem.digest,
        original_status=original.status,
        relaxation_status=relaxed.status,
        repairs=tuple(repairs),
        relaxation_result=relaxed,
    )
