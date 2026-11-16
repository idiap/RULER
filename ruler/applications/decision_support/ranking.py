# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Optional deterministic ranking after rule evaluation and hard feasibility gates."""

from __future__ import annotations

import math
from typing import Any, Literal

from pydantic import Field, model_validator

from ruler.contracts.cases import CaseContext
from ruler.contracts.common import StrictContract


class CandidateOption(StrictContract):
    """A domain-neutral option that may be ranked after evaluation."""

    option_id: str
    label: str
    dimensions: dict[str, float] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    trace_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def dimension_values_are_finite(self) -> "CandidateOption":
        invalid = sorted(key for key, value in self.dimensions.items() if not math.isfinite(value))
        if invalid:
            raise ValueError(f"candidate dimensions must be finite: {', '.join(invalid)}")
        return self


class HardConstraintAssessment(StrictContract):
    """Precomputed hard feasibility result backed by evaluation artifacts."""

    constraint_id: str
    option_id: str
    satisfied: bool
    trace_refs: tuple[str, ...] = Field(min_length=1)


class SoftPreference(StrictContract):
    dimension_id: str
    weight: float = Field(ge=0.0)
    direction: Literal["maximize", "minimize"] = "maximize"
    trace_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def weight_is_finite(self) -> "SoftPreference":
        if not math.isfinite(self.weight):
            raise ValueError("soft preference weight must be finite")
        return self


class RankingProfile(StrictContract):
    profile_id: str
    preferences: tuple[SoftPreference, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def dimensions_are_unique(self) -> "RankingProfile":
        dimensions = [item.dimension_id for item in self.preferences]
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("soft preference dimensions must be unique")
        if sum(item.weight for item in self.preferences) <= 0:
            raise ValueError("ranking requires at least one positive soft weight")
        return self


class DecisionSupportRequest(StrictContract):
    request_id: str
    context: CaseContext
    candidates: tuple[CandidateOption, ...] = ()
    hard_constraints: tuple[HardConstraintAssessment, ...] = ()
    ranking: RankingProfile | None = None

    @model_validator(mode="after")
    def identifiers_and_references_are_valid(self) -> "DecisionSupportRequest":
        option_ids = [item.option_id for item in self.candidates]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("candidate option IDs must be unique")
        unknown = sorted({item.option_id for item in self.hard_constraints} - set(option_ids))
        if unknown:
            raise ValueError(f"hard constraints reference unknown options: {', '.join(unknown)}")
        return self


class RankedOption(StrictContract):
    rank: int = Field(ge=1)
    option_id: str
    score: float
    satisfied_hard_constraint_ids: tuple[str, ...]
    soft_contributions: dict[str, float]
    trace_refs: tuple[str, ...]


class DecisionTraceStep(StrictContract):
    sequence: int = Field(ge=0)
    phase: Literal["hard_constraints", "soft_ranking", "bypass"]
    artifact_ids: tuple[str, ...]


class DecisionSupportResult(StrictContract):
    request_id: str
    status: Literal["bypassed", "no_candidates", "ranked", "infeasible"]
    selected_option_id: str | None = None
    rankings: tuple[RankedOption, ...] = ()
    excluded_option_ids: tuple[str, ...] = ()
    trace: tuple[DecisionTraceStep, ...]

    @model_validator(mode="after")
    def result_shape_matches_status(self) -> "DecisionSupportResult":
        if self.status == "ranked" and (not self.rankings or not self.selected_option_id):
            raise ValueError("ranked results require rankings and a selected option")
        if self.status != "ranked" and (self.rankings or self.selected_option_id):
            raise ValueError("non-ranked results cannot invent a selection")
        return self


def rank_candidate_options(request: DecisionSupportRequest) -> DecisionSupportResult:
    """Apply hard gates before soft ranking; bypass when ranking was not requested."""
    if request.ranking is None:
        return DecisionSupportResult(
            request_id=request.request_id,
            status="bypassed",
            trace=(DecisionTraceStep(sequence=0, phase="bypass", artifact_ids=()),),
        )
    if not request.candidates:
        return DecisionSupportResult(
            request_id=request.request_id,
            status="no_candidates",
            trace=(DecisionTraceStep(sequence=0, phase="hard_constraints", artifact_ids=()),),
        )

    constraints_by_option: dict[str, list[HardConstraintAssessment]] = {
        item.option_id: [] for item in request.candidates
    }
    for constraint in request.hard_constraints:
        constraints_by_option[constraint.option_id].append(constraint)
    feasible = [
        item
        for item in request.candidates
        if all(constraint.satisfied for constraint in constraints_by_option[item.option_id])
    ]
    excluded = tuple(sorted(set(constraints_by_option) - {item.option_id for item in feasible}))
    hard_ids = tuple(sorted(item.constraint_id for item in request.hard_constraints))
    hard_step = DecisionTraceStep(sequence=0, phase="hard_constraints", artifact_ids=hard_ids)
    if not feasible:
        return DecisionSupportResult(
            request_id=request.request_id,
            status="infeasible",
            excluded_option_ids=excluded,
            trace=(hard_step,),
        )

    profile = request.ranking
    total_weight = sum(item.weight for item in profile.preferences)
    scored: list[tuple[CandidateOption, float, dict[str, float]]] = []
    for option in feasible:
        contributions: dict[str, float] = {}
        for preference in profile.preferences:
            raw = float(option.dimensions.get(preference.dimension_id, 0.0))
            oriented = raw if preference.direction == "maximize" else -raw
            contributions[preference.dimension_id] = oriented * preference.weight / total_weight
        scored.append((option, sum(contributions.values()), contributions))
    scored.sort(key=lambda item: (-item[1], item[0].option_id))
    rankings = tuple(
        RankedOption(
            rank=index,
            option_id=option.option_id,
            score=round(score, 12),
            satisfied_hard_constraint_ids=tuple(
                sorted(
                    item.constraint_id
                    for item in constraints_by_option[option.option_id]
                    if item.satisfied
                )
            ),
            soft_contributions={
                key: round(value, 12) for key, value in sorted(contributions.items())
            },
            trace_refs=tuple(
                sorted(
                    {
                        *option.trace_refs,
                        *(ref for item in profile.preferences for ref in item.trace_refs),
                    }
                )
            ),
        )
        for index, (option, score, contributions) in enumerate(scored, start=1)
    )
    return DecisionSupportResult(
        request_id=request.request_id,
        status="ranked",
        selected_option_id=rankings[0].option_id,
        rankings=rankings,
        excluded_option_ids=excluded,
        trace=(
            hard_step,
            DecisionTraceStep(
                sequence=1,
                phase="soft_ranking",
                artifact_ids=tuple(item.dimension_id for item in profile.preferences),
            ),
        ),
    )
