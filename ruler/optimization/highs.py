# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Real Pyomo/HiGHS adapter for the solver-neutral linear IR."""

from __future__ import annotations

import math
import time
from decimal import Decimal
from importlib.metadata import version
from typing import Any

import pyomo.environ as pyo
from pyomo.contrib.appsi.solvers.highs import Highs

from ruler.optimization.contracts import (
    BackendReceipt,
    LinearExpression,
    OptimizationProblem,
    OptimizationResult,
    OptimizationStatus,
)


def _decimal(value: float | None) -> Decimal | None:
    if value is None:
        return None
    numeric = float(value)
    if not math.isfinite(numeric):
        return None
    return Decimal(str(numeric))


def _expression(expression: LinearExpression, variables: dict[str, Any]) -> Any:
    # Pyomo expression and scalar-variable arithmetic is dynamically overloaded.
    return float(expression.constant) + sum(
        float(term.coefficient) * variables[term.variable_id] for term in expression.terms
    )


def _value(expression: Any) -> float:
    value = pyo.value(expression)
    if value is None:
        raise ValueError("solver expression has no numeric value")
    return float(value)


def _status(termination: object, has_incumbent: bool) -> OptimizationStatus:
    name = str(termination).rsplit(".", 1)[-1]
    if name == "optimal":
        return OptimizationStatus.OPTIMAL
    if name in {"infeasible", "infeasibleOrUnbounded"}:
        return OptimizationStatus.INFEASIBLE
    if name == "unbounded":
        return OptimizationStatus.UNBOUNDED
    if name in {"maxTimeLimit", "maxIterations", "maxEvaluations"}:
        return OptimizationStatus.FEASIBLE if has_incumbent else OptimizationStatus.TIME_LIMIT
    return OptimizationStatus.FEASIBLE if has_incumbent else OptimizationStatus.ERROR


def solve_highs(
    problem: OptimizationProblem,
    *,
    time_limit_seconds: float | None = None,
    seed: int = 0,
    threads: int = 1,
) -> OptimizationResult:
    """Build and solve a real Pyomo model using the bundled HiGHS library.

    Multiple priority levels are implemented lexicographically: each priority is
    solved independently and its attained value is fixed before solving the next.
    Objective components at the same priority must share a direction.
    """
    model = pyo.ConcreteModel(name=problem.problem_id)
    variables: dict[str, Any] = {}
    for item in problem.variables:
        domain = {
            "binary": pyo.Binary,
            "integer": pyo.Integers,
            "continuous": pyo.Reals,
        }[item.domain]
        variable: Any = pyo.Var(
            domain=domain,
            bounds=(float(item.lower_bound), float(item.upper_bound)),
        )
        model.add_component(f"v__{len(variables)}", variable)
        variables[item.variable_id] = variable

    constraint_count = 0
    model_variable_count = len(problem.variables)
    penalty_expressions: list[tuple[int, Any]] = []
    for index, item in enumerate(problem.constraints):
        lhs = _expression(item.expression, variables)
        rhs = float(item.rhs)
        if item.hard:
            relation = (
                lhs <= rhs
                if item.sense == "<="
                else lhs >= rhs if item.sense == ">=" else lhs == rhs
            )
            model.add_component(f"c__{index}", pyo.Constraint(expr=relation))
            constraint_count += 1
            continue
        assert item.penalty is not None  # Validated for every soft constraint.
        slack: Any = pyo.Var(domain=pyo.NonNegativeReals)
        model_variable_count += 1
        model.add_component(f"soft_slack__{index}", slack)
        if item.sense == "<=":
            relation = lhs <= rhs + slack
            constraint_count += 1
        elif item.sense == ">=":
            relation = lhs + slack >= rhs
            constraint_count += 1
        else:
            negative: Any = pyo.Var(domain=pyo.NonNegativeReals)
            model_variable_count += 1
            model.add_component(f"soft_negative_slack__{index}", negative)
            relation = lhs + slack - negative == rhs
            penalty_expressions.append((-1, float(item.penalty) * negative))
            constraint_count += 1
        model.add_component(f"c__{index}", pyo.Constraint(expr=relation))
        penalty_expressions.append((-1, float(item.penalty) * slack))

    grouped: dict[int, list] = {}
    for objective in problem.objectives:
        grouped.setdefault(objective.priority, []).append(objective)
    for priority, penalty in penalty_expressions:
        grouped.setdefault(priority, []).append(("penalty", penalty))

    solver = Highs()
    solver.config.load_solution = False
    solver.highs_options["random_seed"] = seed
    solver.highs_options["threads"] = threads
    if time_limit_seconds is not None:
        solver.config.time_limit = time_limit_seconds

    start = time.monotonic()
    final_results = None
    objective_components: dict[str, Decimal] = {}
    active_objective = None
    for position, priority in enumerate(sorted(grouped)):
        entries = grouped[priority]
        declared = [entry for entry in entries if not isinstance(entry, tuple)]
        senses = {entry.sense for entry in declared}
        if len(senses) > 1:
            raise ValueError(f"objectives at priority {priority} have inconsistent senses")
        sense = next(iter(senses), "minimize")
        expression = sum(
            _expression(entry.expression, variables) if not isinstance(entry, tuple) else entry[1]
            for entry in entries
        )
        active_objective = pyo.Objective(
            expr=expression,
            sense=pyo.minimize if sense == "minimize" else pyo.maximize,
        )
        model.add_component(f"objective__{priority}", active_objective)
        final_results = solver.solve(model)
        termination = final_results.termination_condition
        if final_results.best_feasible_objective is not None:
            solver.load_vars()
        if str(termination).rsplit(".", 1)[-1] != "optimal" or position == len(grouped) - 1:
            break
        attained = _value(active_objective)
        active_objective.deactivate()
        tolerance = 1e-8 * max(1.0, abs(attained))
        if sense == "minimize":
            relation = expression <= attained + tolerance
        else:
            relation = expression >= attained - tolerance
        model.add_component(f"lex_fix__{priority}", pyo.Constraint(expr=relation))
        constraint_count += 1

    assert final_results is not None and active_objective is not None
    runtime = time.monotonic() - start
    incumbent = _decimal(final_results.best_feasible_objective)
    bound = _decimal(final_results.best_objective_bound)
    has_incumbent = incumbent is not None
    status = _status(final_results.termination_condition, has_incumbent)
    assignments = {}
    if status in {OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE}:
        assignments = {
            variable_id: Decimal(str(_value(variable)))
            for variable_id, variable in sorted(variables.items())
        }
        for objective in problem.objectives:
            objective_components[objective.objective_id] = Decimal(
                str(_value(_expression(objective.expression, variables)))
            )
    gap = None
    if incumbent is not None and bound is not None:
        gap = abs(incumbent - bound) / max(Decimal(1), abs(incumbent))
    receipt = BackendReceipt(
        library_version=version("highspy"),
        model_digest=problem.digest,
        seed=seed,
        threads=threads,
        time_limit_seconds=time_limit_seconds,
        native_termination_condition=str(final_results.termination_condition).rsplit(".", 1)[-1],
        native_best_feasible_objective=incumbent,
        native_best_objective_bound=bound,
    )
    return OptimizationResult(
        problem_id=problem.problem_id,
        model_digest=problem.digest,
        status=status,
        assignments=assignments,
        objective_value=incumbent,
        objective_bound=bound,
        relative_gap=gap,
        objective_components=objective_components,
        variable_count=model_variable_count,
        constraint_count=constraint_count,
        runtime_seconds=runtime,
        receipt=receipt,
    )
