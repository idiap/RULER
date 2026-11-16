# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Safety regression tests for the closed MaxSMT constraint AST."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ruler.reasoning.solver_contracts import (
    BudgetConstraint,
    BudgetTerm,
    ExactlyOneConstraint,
    ExcludesConstraint,
    HardConstraint,
    ObjectiveTerm,
    RequiresConstraint,
    SolverProblem,
    SolverVariable,
)
from ruler.solvers.maxsmt import solve_maxsmt_feature_choice


def _problem(*constraints: object) -> SolverProblem:
    variables = [
        SolverVariable(
            variable_id=f"select_{name}",
            variable_type="feature_selected",
            feature_id=name,
            label=name,
        )
        for name in ("a", "b", "c")
    ]
    hard = [
        HardConstraint(constraint_id=f"c{index}", label="typed", constraint=value)
        for index, value in enumerate(constraints)
    ]
    return SolverProblem(
        problem_id="p",
        case_id="case",
        profile_id="profile",
        solver_backend="z3",
        variables=variables,
        hard_constraints=hard,
        soft_constraints=[],
        objective_terms=[
            ObjectiveTerm(term_id=name, feature_id=name, label=name, value=value)
            for name, value in (("a", 30), ("b", 20), ("c", 10))
        ],
    )


def test_requires_is_compiled_not_silently_ignored() -> None:
    result = solve_maxsmt_feature_choice(
        _problem(
            ExactlyOneConstraint(variable_ids=("select_a", "select_b", "select_c")),
            RequiresConstraint(trigger_variable_id="select_a", required_variable_id="select_b"),
        )
    )
    assert result.trace.selected_feature_ids == ["b"]


def test_excludes_and_budget_are_compiled() -> None:
    result = solve_maxsmt_feature_choice(
        _problem(
            ExactlyOneConstraint(variable_ids=("select_a", "select_b", "select_c")),
            ExcludesConstraint(left_variable_id="select_a", right_variable_id="select_b"),
            BudgetConstraint(
                terms=(
                    BudgetTerm(variable_id="select_a", cost=50),
                    BudgetTerm(variable_id="select_b", cost=5),
                    BudgetTerm(variable_id="select_c", cost=5),
                ),
                limit=10,
            ),
        )
    )
    assert result.trace.selected_feature_ids == ["b"]


def test_unknown_constraint_variant_and_variable_fail_before_solver() -> None:
    with pytest.raises(ValidationError):
        HardConstraint.model_validate(
            {
                "constraint_id": "x",
                "label": "x",
                "constraint": {"kind": "raw", "expression": "true"},
            }
        )
    with pytest.raises(ValidationError, match="unknown variables"):
        _problem(ExactlyOneConstraint(variable_ids=("select_missing",)))


def test_feature_choice_rejects_problem_without_global_exactly_one() -> None:
    with pytest.raises(ValueError, match="exactly_one"):
        solve_maxsmt_feature_choice(
            _problem(BudgetConstraint(terms=(BudgetTerm(variable_id="select_a", cost=1),), limit=1))
        )
