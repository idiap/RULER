# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Solver-neutral mathematical optimization and real backend adapters."""

from ruler.optimization.contracts import (
    BackendReceipt,
    LinearConstraint,
    LinearExpression,
    LinearObjective,
    LinearTerm,
    OptimizationProblem,
    OptimizationResult,
    OptimizationStatus,
    OptimizationVariable,
    Scenario,
)
from ruler.optimization.highs import solve_highs
from ruler.optimization.diagnostics import diagnose_infeasibility
from ruler.optimization.verification import verify_result

__all__ = [
    "BackendReceipt",
    "LinearConstraint",
    "LinearExpression",
    "LinearObjective",
    "LinearTerm",
    "OptimizationProblem",
    "OptimizationResult",
    "OptimizationStatus",
    "OptimizationVariable",
    "Scenario",
    "solve_highs",
    "diagnose_infeasibility",
    "verify_result",
]
