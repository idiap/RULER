# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""MaxSMT solver backend. It uses Z3 Optimize to satisfy hard feature constraints, rank
soft preferences, and return auditable top-k recommendation traces.
"""

from __future__ import annotations

from z3 import BoolRef, Bool, If, Implies, Not, Optimize, Or, Sum, is_true, sat

from ruler.reasoning.solver_contracts import (
    BudgetConstraint,
    CardinalityConstraint,
    ExactlyOneConstraint,
    ExcludesConstraint,
    ForbidConstraint,
    HardConstraint,
    RequiresConstraint,
    SolverAssignment,
    SolverProblem,
    SolverRanking,
    SolverResult,
    SolverTrace,
    ViolatedSoftConstraint,
)


def solve_maxsmt_feature_choice(problem: SolverProblem, top_k: int = 3) -> SolverResult:
    """Solve MaxSMT feature choice for the MaxSMT workflow."""
    variables_by_id = {
        variable.variable_id: Bool(variable.variable_id) for variable in problem.variables
    }
    variables_by_feature = {
        variable.feature_id: variables_by_id[variable.variable_id] for variable in problem.variables
    }
    if not variables_by_feature:
        return _infeasible_result(problem)
    declared_ids = set(variables_by_id)
    if not any(
        isinstance(item.constraint, ExactlyOneConstraint)
        and set(item.constraint.variable_ids) == declared_ids
        for item in problem.hard_constraints
    ):
        raise ValueError(
            "feature-choice MaxSMT requires an exactly_one constraint over every variable"
        )
    objective_by_feature = {term.feature_id: term.value for term in problem.objective_terms}
    hard_blocked = {
        variable.feature_id
        for variable in problem.variables
        if any(
            isinstance(item.constraint, ForbidConstraint)
            and item.constraint.variable_id == variable.variable_id
            for item in problem.hard_constraints
        )
    }

    ranking = _solve_top_k(
        problem,
        variables_by_feature,
        variables_by_id,
        objective_by_feature,
        hard_blocked,
        top_k,
    )
    if not ranking:
        return _infeasible_result(problem)

    selected_feature_id = ranking[0].feature_id
    ranked = _rank_assignments(objective_by_feature, hard_blocked, ranking)
    selected_assignment = next(item for item in ranked if item.selected)
    runner_ups = [item.feature_id for item in ranking[1:3]]
    trace = SolverTrace(
        solver_backend=problem.solver_backend,
        status="optimal",
        objective_value=selected_assignment.objective_value,
        selected_feature_ids=[selected_feature_id],
        runner_up_feature_ids=runner_ups,
        top_ranked_features=ranking,
        hard_constraint_ids=[constraint.constraint_id for constraint in problem.hard_constraints],
        satisfied_soft_constraint_ids=[
            constraint.constraint_id
            for constraint in problem.soft_constraints
            if constraint.feature_id == selected_feature_id and constraint.utility >= 0.65
        ],
        violated_soft_constraints=_violated_soft_constraints(problem, selected_feature_id),
        explanation_atoms=[
            f"selected({selected_feature_id})",
            f"objective_value({selected_assignment.objective_value})",
            f"top_k({','.join(item.feature_id for item in ranking)})",
            f"runner_up({runner_ups[0]})" if runner_ups else "runner_up(none)",
        ],
        trace_refs=[problem.case_id, problem.profile_id],
    )
    return SolverResult(
        problem_id=problem.problem_id,
        solver_backend=problem.solver_backend,
        status="optimal",
        objective_value=selected_assignment.objective_value,
        assignments=ranked,
        trace=trace,
    )


def _solve_top_k(
    problem: SolverProblem,
    variables_by_feature: dict[str, BoolRef],
    variables_by_id: dict[str, BoolRef],
    objective_by_feature: dict[str, int],
    hard_blocked: set[str],
    top_k: int,
) -> list[SolverRanking]:
    """Internal helper for solve top k in the MaxSMT workflow."""
    selected_feature_ids: list[str] = []
    rankings: list[SolverRanking] = []
    for iteration in range(1, top_k + 1):
        selected_feature_id = _solve_one_rank(
            variables_by_feature=variables_by_feature,
            variables_by_id=variables_by_id,
            hard_constraints=problem.hard_constraints,
            objective_by_feature=objective_by_feature,
            hard_blocked=hard_blocked,
            excluded_feature_ids=set(selected_feature_ids),
        )
        if selected_feature_id is None:
            break
        selected_feature_ids.append(selected_feature_id)
        rankings.append(
            SolverRanking(
                rank=iteration,
                feature_id=selected_feature_id,
                objective_value=objective_by_feature[selected_feature_id],
                solver_iteration=iteration,
                selected=iteration == 1,
                exclusion_constraint_ids=[
                    f"top_k_exclude:{feature_id}" for feature_id in selected_feature_ids[:-1]
                ],
            )
        )
    return rankings


def _solve_one_rank(
    variables_by_feature: dict[str, BoolRef],
    variables_by_id: dict[str, BoolRef],
    hard_constraints: list[HardConstraint],
    objective_by_feature: dict[str, int],
    hard_blocked: set[str],
    excluded_feature_ids: set[str],
) -> str | None:
    """Internal helper for solve one rank in the MaxSMT workflow."""
    optimizer = Optimize()
    _add_typed_constraints(optimizer, variables_by_id, hard_constraints)
    for feature_id in excluded_feature_ids:
        optimizer.add(Not(variables_by_feature[feature_id]))
    objective = Sum(
        [
            If(variables_by_feature[feature_id], value, 0)
            for feature_id, value in objective_by_feature.items()
        ]
    )
    optimizer.maximize(objective)
    status = optimizer.check()
    if status != sat:
        return None

    model = optimizer.model()
    return next(
        feature_id
        for feature_id, variable in variables_by_feature.items()
        if is_true(model.eval(variable))
    )


def _add_typed_constraints(
    optimizer: Optimize,
    variables: dict[str, BoolRef],
    constraints: list[HardConstraint],
) -> None:
    """Compile the complete closed constraint AST without evaluating display strings."""
    for hard in constraints:
        value = hard.constraint
        if isinstance(value, ExactlyOneConstraint):
            optimizer.add(Sum([If(variables[item], 1, 0) for item in value.variable_ids]) == 1)
        elif isinstance(value, CardinalityConstraint):
            count = Sum([If(variables[item], 1, 0) for item in value.variable_ids])
            optimizer.add(count >= value.minimum)
            if value.maximum is not None:
                optimizer.add(count <= value.maximum)
        elif isinstance(value, ForbidConstraint):
            optimizer.add(Not(variables[value.variable_id]))
        elif isinstance(value, RequiresConstraint):
            required = value.requirement_satisfied
            if value.required_variable_id is not None:
                required = Or(required, variables[value.required_variable_id])
            optimizer.add(Implies(variables[value.trigger_variable_id], required))
        elif isinstance(value, ExcludesConstraint):
            optimizer.add(
                Not(variables[value.left_variable_id] & variables[value.right_variable_id])
            )
        elif isinstance(value, BudgetConstraint):
            optimizer.add(
                Sum([If(variables[item.variable_id], item.cost, 0) for item in value.terms])
                <= value.limit
            )
        else:  # pragma: no cover - Pydantic's discriminated union is closed
            raise TypeError(f"unsupported hard constraint variant: {type(value).__name__}")


def _rank_assignments(
    objective_by_feature: dict[str, int],
    hard_blocked: set[str],
    top_rankings: list[SolverRanking],
) -> list[SolverAssignment]:
    """Internal helper for rank assignments in the MaxSMT workflow."""
    solver_rank_by_feature = {item.feature_id: item.rank for item in top_rankings}
    ranked_feature_ids = sorted(
        objective_by_feature,
        key=lambda feature_id: (
            feature_id in hard_blocked,
            solver_rank_by_feature.get(feature_id, len(objective_by_feature) + 1),
            -objective_by_feature[feature_id],
            feature_id,
        ),
    )
    selected_feature_id = top_rankings[0].feature_id
    assignments: list[SolverAssignment] = []
    for index, feature_id in enumerate(ranked_feature_ids):
        assignments.append(
            SolverAssignment(
                feature_id=feature_id,
                selected=feature_id == selected_feature_id,
                rank=index + 1,
                objective_value=objective_by_feature[feature_id],
            )
        )
    return assignments


def _violated_soft_constraints(
    problem: SolverProblem,
    selected_feature_id: str,
) -> list[ViolatedSoftConstraint]:
    """Internal helper for violated soft constraints in the MaxSMT workflow."""
    winner_by_dimension = {
        constraint.dimension_id: constraint
        for constraint in problem.soft_constraints
        if constraint.feature_id == selected_feature_id
    }
    best_by_dimension: dict[str, float] = {}
    for constraint in problem.soft_constraints:
        best_by_dimension[constraint.dimension_id] = max(
            best_by_dimension.get(constraint.dimension_id, 0.0),
            constraint.utility,
        )
    violated: list[ViolatedSoftConstraint] = []
    for dimension_id, winner_constraint in winner_by_dimension.items():
        best = best_by_dimension[dimension_id]
        if winner_constraint.utility + 1e-9 >= best:
            continue
        violated.append(
            ViolatedSoftConstraint(
                constraint_id=winner_constraint.constraint_id,
                label=winner_constraint.label,
                feature_id=selected_feature_id,
                dimension_id=dimension_id,
                winner_utility=winner_constraint.utility,
                best_available_utility=round(best, 6),
                opportunity_score=round(best - winner_constraint.utility, 6),
            )
        )
    return violated


def _infeasible_result(problem: SolverProblem) -> SolverResult:
    """Internal helper for infeasible result in the MaxSMT workflow."""
    trace = SolverTrace(
        solver_backend=problem.solver_backend,
        status="infeasible",
        objective_value=0,
        selected_feature_ids=[],
        runner_up_feature_ids=[],
        top_ranked_features=[],
        hard_constraint_ids=[constraint.constraint_id for constraint in problem.hard_constraints],
        satisfied_soft_constraint_ids=[],
        violated_soft_constraints=[],
        explanation_atoms=["infeasible"],
        trace_refs=[problem.case_id, problem.profile_id],
    )
    return SolverResult(
        problem_id=problem.problem_id,
        solver_backend=problem.solver_backend,
        status="infeasible",
        objective_value=0,
        assignments=[],
        trace=trace,
    )
