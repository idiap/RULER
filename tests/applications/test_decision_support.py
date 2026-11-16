# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Optional neutral candidate ranking independent of retired_application recommendation."""

from __future__ import annotations

from ruler.applications.decision_support import (
    CandidateOption,
    DecisionSupportRequest,
    HardConstraintAssessment,
    RankingProfile,
    SoftPreference,
    rank_candidate_options,
)
from ruler.contracts.cases import CaseContext

CONTEXT = CaseContext(
    context_id="case:regulatory",
    domain_id="regulatory",
    subject_id="operator-a",
)


def _option(option_id: str, benefit: float, burden: float) -> CandidateOption:
    return CandidateOption(
        option_id=option_id,
        label=option_id,
        dimensions={"benefit": benefit, "burden": burden},
        trace_refs=(f"evaluation:{option_id}",),
    )


def test_no_ranking_and_no_candidate_paths_bypass_cleanly() -> None:
    bypassed = rank_candidate_options(
        DecisionSupportRequest(
            request_id="no-ranking", context=CONTEXT, candidates=(_option("a", 1, 1),)
        )
    )
    assert bypassed.status == "bypassed"
    assert bypassed.selected_option_id is None
    assert bypassed.rankings == ()

    no_candidates = rank_candidate_options(
        DecisionSupportRequest(
            request_id="no-candidates",
            context=CONTEXT,
            ranking=RankingProfile(
                profile_id="profile",
                preferences=(SoftPreference(dimension_id="benefit", weight=1),),
            ),
        )
    )
    assert no_candidates.status == "no_candidates"
    assert no_candidates.rankings == ()


def test_hard_constraints_precede_soft_ranking() -> None:
    request = DecisionSupportRequest(
        request_id="hard-before-soft",
        context=CONTEXT,
        candidates=(_option("blocked-high-score", 100, 0), _option("feasible", 1, 2)),
        hard_constraints=(
            HardConstraintAssessment(
                constraint_id="prohibition:blocked",
                option_id="blocked-high-score",
                satisfied=False,
                trace_refs=("consequence:prohibition",),
            ),
        ),
        ranking=RankingProfile(
            profile_id="balanced",
            preferences=(
                SoftPreference(dimension_id="benefit", weight=2),
                SoftPreference(dimension_id="burden", weight=1, direction="minimize"),
            ),
        ),
    )
    result = rank_candidate_options(request)
    assert result.status == "ranked"
    assert result.selected_option_id == "feasible"
    assert result.excluded_option_ids == ("blocked-high-score",)
    assert [item.phase for item in result.trace] == ["hard_constraints", "soft_ranking"]


def test_ranking_is_deterministic_and_all_blocked_is_valid() -> None:
    profile = RankingProfile(
        profile_id="tie", preferences=(SoftPreference(dimension_id="benefit", weight=1),)
    )
    tied = DecisionSupportRequest(
        request_id="tie",
        context=CONTEXT,
        candidates=(_option("z", 1, 0), _option("a", 1, 0)),
        ranking=profile,
    )
    assert [item.option_id for item in rank_candidate_options(tied).rankings] == ["a", "z"]

    blocked = tied.model_copy(
        update={
            "request_id": "blocked",
            "hard_constraints": tuple(
                HardConstraintAssessment(
                    constraint_id=f"blocked:{option_id}",
                    option_id=option_id,
                    satisfied=False,
                    trace_refs=(f"rule:{option_id}",),
                )
                for option_id in ("z", "a")
            ),
        }
    )
    result = rank_candidate_options(blocked)
    assert result.status == "infeasible"
    assert result.selected_option_id is None
    assert result.excluded_option_ids == ("a", "z")
