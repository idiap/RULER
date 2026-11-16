# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Compile approved resource rules into the closed linear optimization IR."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

import z3
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.optimization.contracts import (
    LinearConstraint,
    LinearExpression,
    LinearObjective,
    LinearTerm,
    OptimizationProblem,
    OptimizationVariable,
    Scenario,
)


class ApprovedLinearRule(BaseModel):
    """Reviewed rule with an explicit, non-executable linear consequence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    version: str
    status: Literal["approved", "candidate", "retired"]
    authority_ref: str
    constraint_id: str
    coefficients: dict[str, Decimal] = Field(min_length=1)
    sense: Literal["<=", "=", ">="]
    rhs: Decimal
    unit: str
    hard: bool = True
    penalty: Decimal | None = None
    evidence_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def finite(self) -> "ApprovedLinearRule":
        if not self.rhs.is_finite() or any(
            not value.is_finite() for value in self.coefficients.values()
        ):
            raise ValueError("rule coefficients must be finite")
        return self


class CompilationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    problem_id: str
    snapshot_digest: str
    variables: tuple[OptimizationVariable, ...] = Field(min_length=1)
    rules: tuple[ApprovedLinearRule, ...] = ()
    axioms: tuple[LinearConstraint, ...] = ()
    objectives: tuple[LinearObjective, ...] = Field(min_length=1)
    scenarios: tuple[Scenario, ...] = ()
    metadata: dict[str, str] = Field(default_factory=dict)


class CompilationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    problem: OptimizationProblem
    z3_status: Literal["sat", "unsat"]
    compiled_rule_ids: tuple[str, ...]
    rejected_rule_ids: tuple[str, ...]


def _z3_number(value: Decimal) -> z3.RatNumRef:
    return z3.RealVal(str(value))


def compile_rules(request: CompilationRequest) -> CompilationReport:
    """Compile only approved rules and prove hard-model satisfiability with Z3.

    Candidate and retired rules are reported but never enter solver truth.
    An unsatisfiable compilation is rejected rather than passed to optimization.
    """
    known = {item.variable_id for item in request.variables}
    approved = [rule for rule in request.rules if rule.status == "approved"]
    rejected = tuple(sorted(rule.rule_id for rule in request.rules if rule.status != "approved"))
    constraints = list(request.axioms)
    recourse_groups: dict[tuple[str, str], list[OptimizationVariable]] = {}
    for variable in request.variables:
        if variable.stage == "recourse":
            recourse_groups.setdefault(
                (str(variable.information_set), str(variable.decision_key)), []
            ).append(variable)
    for (information_set, decision_key), variables in sorted(recourse_groups.items()):
        anchor, *followers = sorted(variables, key=lambda item: item.variable_id)
        for follower in followers:
            if follower.unit != anchor.unit or follower.domain != anchor.domain:
                raise ValueError(
                    f"non-anticipative decision {decision_key} has incompatible variables"
                )
            constraints.append(
                LinearConstraint.model_validate(
                    dict(
                        constraint_id=(
                            f"non_anticipativity:{information_set}:{decision_key}:"
                            f"{anchor.scenario_id}:{follower.scenario_id}"
                        ),
                        expression=LinearExpression(
                            terms=(
                                LinearTerm.model_validate(
                                    dict(variable_id=anchor.variable_id, coefficient=1)
                                ),
                                LinearTerm.model_validate(
                                    dict(variable_id=follower.variable_id, coefficient=-1)
                                ),
                            )
                        ),
                        sense="=",
                        rhs=0,
                        unit=anchor.unit,
                        origin_refs=("model_axiom:non_anticipativity",),
                    )
                )
            )
    for rule in approved:
        unknown = set(rule.coefficients) - known
        if unknown:
            raise ValueError(f"rule {rule.rule_id} references unknown variables: {sorted(unknown)}")
        constraints.append(
            LinearConstraint(
                constraint_id=rule.constraint_id,
                expression=LinearExpression(
                    terms=tuple(
                        LinearTerm(variable_id=variable_id, coefficient=coefficient)
                        for variable_id, coefficient in sorted(rule.coefficients.items())
                    )
                ),
                sense=rule.sense,
                rhs=rule.rhs,
                unit=rule.unit,
                hard=rule.hard,
                penalty=rule.penalty,
                origin_refs=(
                    f"rule:{rule.rule_id}@{rule.version}",
                    rule.authority_ref,
                    *rule.evidence_refs,
                ),
            )
        )
    problem = OptimizationProblem(
        problem_id=request.problem_id,
        snapshot_digest=request.snapshot_digest,
        variables=request.variables,
        constraints=tuple(constraints),
        objectives=request.objectives,
        scenarios=request.scenarios,
        metadata=request.metadata,
    )
    solver = z3.Solver()
    zvars: dict[str, z3.ArithRef] = {}
    for variable in problem.variables:
        zv = (
            z3.Int(variable.variable_id)
            if variable.domain in {"binary", "integer"}
            else z3.Real(variable.variable_id)
        )
        zvars[variable.variable_id] = zv
        solver.add(zv >= _z3_number(variable.lower_bound), zv <= _z3_number(variable.upper_bound))
    for constraint in problem.constraints:
        if not constraint.hard:
            continue
        lhs = _z3_number(constraint.expression.constant) + z3.Sum(
            _z3_number(term.coefficient) * zvars[term.variable_id]
            for term in constraint.expression.terms
        )
        rhs = _z3_number(constraint.rhs)
        solver.add(
            lhs <= rhs
            if constraint.sense == "<="
            else lhs >= rhs if constraint.sense == ">=" else lhs == rhs
        )
    status = solver.check()
    if status != z3.sat:
        raise ValueError("compiled hard constraints are unsatisfiable")
    return CompilationReport(
        problem=problem,
        z3_status="sat",
        compiled_rule_ids=tuple(sorted(rule.rule_id for rule in approved)),
        rejected_rule_ids=rejected,
    )
