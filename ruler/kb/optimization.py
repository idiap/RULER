# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Neutral optimization profile and serialization boundary."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract
from ruler.reasoning.solver_contracts import SolverProblem


class OptimizationProfile(StrictContract):
    """Declares what a generic optimization backend may truthfully execute."""

    profile_id: str
    backend_id: str
    domain_scope: Literal["neutral"] = "neutral"
    supported_constraint_kinds: frozenset[
        Literal["exactly_one", "cardinality", "forbid", "requires", "excludes", "budget"]
    ] = Field(min_length=1)
    claim_boundary: str = Field(min_length=1)


class NeutralOptimizationArtifact(StrictContract):
    """Portable profile plus a fully typed, closed optimization problem."""

    schema_version: Literal["ruler-optimization/1"] = "ruler-optimization/1"
    profile: OptimizationProfile
    problem: SolverProblem

    @model_validator(mode="after")
    def profile_covers_problem(self) -> "NeutralOptimizationArtifact":
        actual = {item.constraint.kind for item in self.problem.hard_constraints}
        missing = actual - set(self.profile.supported_constraint_kinds)
        if missing:
            raise ValueError(f"optimization profile does not support: {sorted(missing)}")
        if self.problem.solver_backend != self.profile.backend_id:
            raise ValueError("problem solver_backend must match the optimization profile")
        return self


GENERIC_MAXSMT_PROFILE = OptimizationProfile(
    profile_id="neutral-maxsmt-v1",
    backend_id="z3_optimize_maxsmt",
    supported_constraint_kinds=frozenset(
        {"exactly_one", "cardinality", "forbid", "requires", "excludes", "budget"}
    ),
    claim_boundary="Optimization is relative to digest-bound variables, constraints, and objective terms; it does not establish compliance or grounding.",
)
