# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ruler.applications.resource_portfolio.compiler import (
    ApprovedLinearRule,
    CompilationRequest,
)
from ruler.applications.resource_portfolio.demonstrator_grounding import (
    ApprovedRuleGrounding,
    DemonstratorGrounding,
    ObjectiveTermGrounding,
    ReviewerApproval,
    ScheduleTaskGrounding,
    build_demonstrator_grounding,
    exact_grounding_span,
    verify_demonstrator_grounding,
)
from ruler.applications.resource_portfolio.scheduling import (
    ScheduleTask,
    SchedulingProblem,
)
from ruler.optimization.contracts import (
    LinearExpression,
    LinearObjective,
    LinearTerm,
    OptimizationVariable,
)

RULE_TEXT = "The approved plan must retain at least two excavator units for the week."
OBJECTIVE_TEXT = "Each retained owned excavator contributes CHF 8,400 to verified total cost."
TASK_TEXT = "The rock-bench shift lasts six hours, runs between hour zero and hour eight, and Atlas is eligible."
SOURCE = f"Synthetic planning note.\n\n{RULE_TEXT}\n{OBJECTIVE_TEXT}\n{TASK_TEXT}\n"


def _requests() -> tuple[CompilationRequest, SchedulingProblem]:
    compilation = CompilationRequest(
        problem_id="grounded-demo",
        snapshot_digest="sha256:" + "a" * 64,
        variables=(
            OptimizationVariable(
                variable_id="retain_atlas",
                domain="integer",
                lower_bound=0,
                upper_bound=3,
                unit="unit",
                origin_refs=("resource:atlas",),
            ),
        ),
        rules=(
            ApprovedLinearRule(
                rule_id="minimum_weekly_capacity",
                version="2.1",
                status="approved",
                authority_ref="review:planning-board-17",
                constraint_id="minimum_capacity",
                coefficients={"retain_atlas": Decimal(1)},
                sense=">=",
                rhs=Decimal(2),
                unit="unit",
                hard=True,
                evidence_refs=("span:minimum-capacity",),
            ),
            ApprovedLinearRule(
                rule_id="generated_preference",
                version="0",
                status="candidate",
                authority_ref="candidate:autoformalization",
                constraint_id="candidate_only",
                coefficients={"retain_atlas": Decimal(1)},
                sense="<=",
                rhs=Decimal(0),
                unit="unit",
                evidence_refs=("candidate:not-authority",),
            ),
        ),
        objectives=(
            LinearObjective(
                objective_id="verified_total_cost",
                expression=LinearExpression(
                    terms=(LinearTerm(variable_id="retain_atlas", coefficient=Decimal(8400)),)
                ),
                unit="CHF",
                component="lifecycle",
                origin_refs=("cost-review:2026-09",),
            ),
        ),
    )
    schedule = SchedulingProblem(
        schedule_id="grounded-demo-schedule",
        plan_digest="sha256:" + "b" * 64,
        time_unit="hour",
        tasks=(
            ScheduleTask(
                task_id="rock_bench_shift",
                duration=6,
                earliest_start=0,
                latest_end=8,
                eligible_resource_ids=("excavator_atlas_35t",),
                required_capability_ids=("rock_excavation",),
                allowed_location_ids=("north_portal",),
                optional=False,
                origin_refs=("work:rock_bench",),
            ),
        ),
        resource_capability_ids={
            "excavator_atlas_35t": ("rock_excavation",),
        },
        resource_location_ids={"excavator_atlas_35t": "north_portal"},
    )
    return compilation, schedule


def _bindings():
    rule = ApprovedRuleGrounding(
        binding_id="bind:rule:minimum-capacity",
        span=exact_grounding_span(SOURCE, "span:minimum-capacity", RULE_TEXT),
        rule_id="minimum_weekly_capacity",
        rule_version="2.1",
        authority_ref="review:planning-board-17",
        constraint_id="minimum_capacity",
        coefficients={"retain_atlas": Decimal(1)},
        sense=">=",
        rhs=Decimal(2),
        unit="unit",
        hard=True,
        evidence_refs=("span:minimum-capacity",),
    )
    objective = ObjectiveTermGrounding(
        binding_id="bind:objective:atlas-cost",
        span=exact_grounding_span(SOURCE, "span:atlas-cost", OBJECTIVE_TEXT),
        objective_id="verified_total_cost",
        variable_id="retain_atlas",
        coefficient=Decimal(8400),
        objective_sense="minimize",
        objective_priority=0,
        objective_unit="CHF",
        objective_component="lifecycle",
        objective_origin_refs=("cost-review:2026-09",),
    )
    task = ScheduleTaskGrounding(
        binding_id="bind:task:rock-bench",
        span=exact_grounding_span(SOURCE, "span:rock-bench-task", TASK_TEXT),
        task_id="rock_bench_shift",
        duration=6,
        earliest_start=0,
        latest_end=8,
        eligible_resource_ids=("excavator_atlas_35t",),
        required_capability_ids=("rock_excavation",),
        allowed_location_ids=("north_portal",),
        capacity_demands={},
        optional=False,
        origin_refs=("work:rock_bench",),
    )
    return rule, objective, task


def _build() -> tuple[DemonstratorGrounding, CompilationRequest, SchedulingProblem]:
    compilation, schedule = _requests()
    rule, objective, task = _bindings()
    grounding = build_demonstrator_grounding(
        source_id="data/domains/construction_fleet/demonstrator/note.md",
        source_text=SOURCE,
        compilation_request=compilation,
        scheduling_problem=schedule,
        approval=ReviewerApproval(
            reviewer_id="fleet-reviewer-17",
            approved_at=datetime(2026, 9, 3, 15, 0, tzinfo=UTC),
            version="projection-v1",
        ),
        approved_rule_bindings=(rule,),
        objective_term_bindings=(objective,),
        schedule_task_bindings=(task,),
    )
    return grounding, compilation, schedule


def test_reviewed_bridge_replays_every_solver_relevant_binding() -> None:
    grounding, compilation, schedule = _build()

    verify_demonstrator_grounding(
        grounding,
        source_text=SOURCE,
        compilation_request=compilation,
        scheduling_problem=schedule,
    )

    assert grounding.generated_candidate_solver_authority is False
    assert {item.rule_id for item in grounding.approved_rule_bindings} == {
        "minimum_weekly_capacity"
    }
    assert "generated_preference" not in {item.rule_id for item in grounding.approved_rule_bindings}
    assert grounding.source_id.startswith("data/")


def test_bridge_rejects_structured_value_not_equal_to_typed_request() -> None:
    compilation, schedule = _requests()
    rule, objective, task = _bindings()
    changed = objective.model_copy(update={"coefficient": Decimal(6900)})

    with pytest.raises(ValueError, match="grounded objective term differs"):
        build_demonstrator_grounding(
            source_id="data/domains/construction_fleet/demonstrator/note.md",
            source_text=SOURCE,
            compilation_request=compilation,
            scheduling_problem=schedule,
            approval=ReviewerApproval(
                reviewer_id="fleet-reviewer-17",
                approved_at=datetime(2026, 9, 3, tzinfo=UTC),
                version="projection-v1",
            ),
            approved_rule_bindings=(rule,),
            objective_term_bindings=(changed,),
            schedule_task_bindings=(task,),
        )


def test_bridge_rejects_missing_approved_rule_or_schedule_task() -> None:
    compilation, schedule = _requests()
    _, objective, task = _bindings()
    approval = ReviewerApproval(
        reviewer_id="fleet-reviewer-17",
        approved_at=datetime(2026, 9, 3, tzinfo=UTC),
        version="projection-v1",
    )

    with pytest.raises(ValueError, match="every approved rule"):
        build_demonstrator_grounding(
            source_id="data/domains/construction_fleet/demonstrator/note.md",
            source_text=SOURCE,
            compilation_request=compilation,
            scheduling_problem=schedule,
            approval=approval,
            approved_rule_bindings=(),
            objective_term_bindings=(objective,),
            schedule_task_bindings=(task,),
        )


def test_exact_spans_and_source_identity_fail_closed() -> None:
    with pytest.raises(ValueError, match="not unique"):
        exact_grounding_span("same sentence. same sentence.", "span:ambiguous", "same sentence.")

    compilation, schedule = _requests()
    rule, objective, task = _bindings()
    with pytest.raises(ValidationError, match="repository-relative"):
        build_demonstrator_grounding(
            source_id="/tmp/private/dossier.md",
            source_text=SOURCE,
            compilation_request=compilation,
            scheduling_problem=schedule,
            approval=ReviewerApproval(
                reviewer_id="fleet-reviewer-17",
                approved_at=datetime(2026, 9, 3, tzinfo=UTC),
                version="projection-v1",
            ),
            approved_rule_bindings=(rule,),
            objective_term_bindings=(objective,),
            schedule_task_bindings=(task,),
        )


def test_review_metadata_requires_an_aware_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        ReviewerApproval(
            reviewer_id="fleet-reviewer-17",
            approved_at=datetime(2026, 9, 3),
            version="projection-v1",
        )
