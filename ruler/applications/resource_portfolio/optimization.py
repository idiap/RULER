# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Application boundary for portfolio optimization and independent verification."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from ruler.io import stable_hash
from ruler.optimization import (
    LinearConstraint,
    LinearExpression,
    LinearTerm,
    OptimizationProblem,
    OptimizationResult,
    solve_highs,
)
from ruler.optimization.verification import VerificationReport, verify_result


class VerifiedPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    result: OptimizationResult
    verification: VerificationReport
    advisory_only: bool = True
    review_status: str = "pending"


class BaselineDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    baseline_id: str
    fixed_assignments: dict[str, Decimal]
    origin_ref: str

    @property
    def digest(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class BaselineResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    baseline_id: str
    baseline_digest: str
    plan: VerifiedPlan


def optimize_portfolio(
    problem: OptimizationProblem,
    *,
    time_limit_seconds: float | None = None,
    seed: int = 0,
    threads: int = 1,
    tolerance: Decimal = Decimal("1e-7"),
) -> VerifiedPlan:
    """Solve using HiGHS and independently check any returned incumbent."""
    result = solve_highs(
        problem,
        time_limit_seconds=time_limit_seconds,
        seed=seed,
        threads=threads,
    )
    verification = verify_result(problem, result, tolerance=tolerance)
    return VerifiedPlan(result=result, verification=verification)


def compare_baselines(
    problem: OptimizationProblem,
    baselines: tuple[BaselineDefinition, ...],
) -> tuple[BaselineResult, ...]:
    """Execute declared baselines through the same solve and verification path."""
    known = {variable.variable_id for variable in problem.variables}
    outputs = []
    for baseline in baselines:
        if set(baseline.fixed_assignments) - known:
            raise ValueError(f"baseline {baseline.baseline_id} fixes unknown variables")
        constraints = list(problem.constraints)
        for variable_id, value in sorted(baseline.fixed_assignments.items()):
            constraints.append(
                LinearConstraint(
                    constraint_id=f"baseline:{baseline.baseline_id}:{variable_id}",
                    expression=LinearExpression(
                        terms=(
                            LinearTerm.model_validate(dict(variable_id=variable_id, coefficient=1)),
                        )
                    ),
                    sense="=",
                    rhs=value,
                    unit=next(
                        item.unit for item in problem.variables if item.variable_id == variable_id
                    ),
                    origin_refs=(baseline.origin_ref,),
                )
            )
        variant = OptimizationProblem.model_validate(
            {
                **problem.model_dump(mode="python"),
                "problem_id": f"{problem.problem_id}:baseline:{baseline.baseline_id}",
                "constraints": [item.model_dump(mode="python") for item in constraints],
            }
        )
        outputs.append(
            BaselineResult(
                baseline_id=baseline.baseline_id,
                baseline_digest=baseline.digest,
                plan=optimize_portfolio(variant),
            )
        )
    return tuple(outputs)
