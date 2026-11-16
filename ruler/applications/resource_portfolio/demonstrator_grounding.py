# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Reviewer-approved source bindings for the portfolio demonstrator.

The generative logical candidate is deliberately absent from the solver authority
chain.  This module binds the independently reviewed optimization and scheduling
inputs to unique, exact spans in the synthetic natural-language dossier and then
replays every structured value against the actual typed requests.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ruler.applications.resource_portfolio.compiler import CompilationRequest
from ruler.applications.resource_portfolio.scheduling import SchedulingProblem
from ruler.contracts.common import StrictContract, validate_sha256
from ruler.io import stable_hash


class ReviewerApproval(StrictContract):
    """Named approval for this exact typed projection, not for model output."""

    reviewer_id: str = Field(min_length=1)
    approved_at: datetime
    version: str = Field(min_length=1)

    @model_validator(mode="after")
    def timestamp_is_aware(self) -> "ReviewerApproval":
        if self.approved_at.tzinfo is None or self.approved_at.utcoffset() is None:
            raise ValueError("approved_at must be timezone-aware")
        return self


class ExactGroundingSpan(StrictContract):
    """One exact, uniquely occurring character span in the dossier."""

    span_id: str = Field(min_length=1)
    exact_text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    span_sha256: str

    @model_validator(mode="after")
    def shape_and_digest(self) -> "ExactGroundingSpan":
        validate_sha256(self.span_sha256)
        if self.end_char - self.start_char != len(self.exact_text):
            raise ValueError("grounding span offsets do not match exact_text length")
        if self.span_sha256 != _sha256_text(self.exact_text):
            raise ValueError("grounding span digest does not authenticate exact_text")
        return self


class ApprovedRuleGrounding(StrictContract):
    """Exact source and structured mirror of one approved linear rule."""

    binding_id: str = Field(min_length=1)
    span: ExactGroundingSpan
    rule_id: str
    rule_version: str
    authority_ref: str
    constraint_id: str
    coefficients: dict[str, Decimal] = Field(min_length=1)
    sense: Literal["<=", "=", ">="]
    rhs: Decimal
    unit: str
    hard: bool
    penalty: Decimal | None = None
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class ObjectiveTermGrounding(StrictContract):
    """Exact source and structured mirror of one objective coefficient."""

    binding_id: str = Field(min_length=1)
    span: ExactGroundingSpan
    objective_id: str
    variable_id: str
    coefficient: Decimal
    objective_sense: Literal["minimize", "maximize"]
    objective_priority: int = Field(ge=0)
    objective_unit: str
    objective_component: str
    objective_origin_refs: tuple[str, ...] = Field(min_length=1)


class ObjectiveConstantGrounding(StrictContract):
    """Exact source and structured mirror of one non-zero objective constant."""

    binding_id: str = Field(min_length=1)
    span: ExactGroundingSpan
    objective_id: str
    constant: Decimal
    objective_sense: Literal["minimize", "maximize"]
    objective_priority: int = Field(ge=0)
    objective_unit: str
    objective_component: str
    objective_origin_refs: tuple[str, ...] = Field(min_length=1)


class ScheduleTaskGrounding(StrictContract):
    """Exact source and structured mirror of one complete schedule task."""

    binding_id: str = Field(min_length=1)
    span: ExactGroundingSpan
    task_id: str
    project_id: str = "unassigned_project"
    location_id: str = "unspecified_location"
    duration: int = Field(gt=0)
    earliest_start: int = Field(ge=0)
    latest_end: int = Field(gt=0)
    eligible_resource_ids: tuple[str, ...] = Field(min_length=1)
    required_capability_ids: tuple[str, ...] = ()
    allowed_location_ids: tuple[str, ...] = ()
    capacity_demands: dict[str, int] = Field(default_factory=dict)
    optional: bool
    origin_refs: tuple[str, ...] = Field(min_length=1)


class DemonstratorGrounding(StrictContract):
    """Digest-closed proof of the reviewed natural-language-to-solver bridge."""

    schema_version: Literal["resource-portfolio-demonstrator-grounding/v1"] = (
        "resource-portfolio-demonstrator-grounding/v1"
    )
    source_id: str = Field(min_length=1)
    source_sha256: str
    compilation_request_sha256: str
    scheduling_problem_sha256: str
    approval: ReviewerApproval
    approved_rule_bindings: tuple[ApprovedRuleGrounding, ...] = ()
    objective_term_bindings: tuple[ObjectiveTermGrounding, ...] = Field(min_length=1)
    objective_constant_bindings: tuple[ObjectiveConstantGrounding, ...] = ()
    schedule_task_bindings: tuple[ScheduleTaskGrounding, ...] = Field(min_length=1)
    generated_candidate_solver_authority: Literal[False] = False
    grounding_sha256: str

    @model_validator(mode="after")
    def identities_and_digest_are_closed(self) -> "DemonstratorGrounding":
        source_path = Path(self.source_id)
        if source_path.is_absolute() or ".." in source_path.parts:
            raise ValueError("source_id must be a repository-relative identity")
        for value in (
            self.source_sha256,
            self.compilation_request_sha256,
            self.scheduling_problem_sha256,
            self.grounding_sha256,
        ):
            validate_sha256(value)
        binding_ids = [
            *(item.binding_id for item in self.approved_rule_bindings),
            *(item.binding_id for item in self.objective_term_bindings),
            *(item.binding_id for item in self.objective_constant_bindings),
            *(item.binding_id for item in self.schedule_task_bindings),
        ]
        span_ids = [
            *(item.span.span_id for item in self.approved_rule_bindings),
            *(item.span.span_id for item in self.objective_term_bindings),
            *(item.span.span_id for item in self.objective_constant_bindings),
            *(item.span.span_id for item in self.schedule_task_bindings),
        ]
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("grounding binding IDs must be globally unique")
        if len(span_ids) != len(set(span_ids)):
            raise ValueError("grounding span IDs must be globally unique")
        expected = stable_hash(self.model_dump(mode="json", exclude={"grounding_sha256"}))
        if self.grounding_sha256 != expected:
            raise ValueError("grounding digest mismatch")
        return self


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def exact_grounding_span(source_text: str, span_id: str, exact_text: str) -> ExactGroundingSpan:
    """Locate a source fragment only when it occurs exactly once."""

    start = source_text.find(exact_text)
    if start < 0:
        raise ValueError(f"grounding text is absent from source: {span_id}")
    if source_text.find(exact_text, start + 1) >= 0:
        raise ValueError(f"grounding text is not unique in source: {span_id}")
    return ExactGroundingSpan(
        span_id=span_id,
        exact_text=exact_text,
        start_char=start,
        end_char=start + len(exact_text),
        span_sha256=_sha256_text(exact_text),
    )


def _verify_span(source_text: str, span: ExactGroundingSpan) -> None:
    if source_text[span.start_char : span.end_char] != span.exact_text:
        raise ValueError(f"grounding span does not resolve to source: {span.span_id}")
    if source_text.count(span.exact_text) != 1:
        raise ValueError(f"grounding span is not unique in source: {span.span_id}")


def verify_demonstrator_grounding(
    grounding: DemonstratorGrounding,
    *,
    source_text: str,
    compilation_request: CompilationRequest,
    scheduling_problem: SchedulingProblem,
) -> None:
    """Replay every span and typed value against the actual solver inputs."""

    if grounding.source_sha256 != _sha256_text(source_text):
        raise ValueError("grounding source digest mismatch")
    compilation_digest = stable_hash(compilation_request.model_dump(mode="json"))
    if grounding.compilation_request_sha256 != compilation_digest:
        raise ValueError("grounding compilation request digest mismatch")
    if grounding.scheduling_problem_sha256 != scheduling_problem.digest:
        raise ValueError("grounding scheduling problem digest mismatch")

    all_bindings = (
        *grounding.approved_rule_bindings,
        *grounding.objective_term_bindings,
        *grounding.objective_constant_bindings,
        *grounding.schedule_task_bindings,
    )
    for binding in all_bindings:
        _verify_span(source_text, binding.span)

    approved_rule_items = tuple(
        rule for rule in compilation_request.rules if rule.status == "approved"
    )
    approved_rules = {rule.rule_id: rule for rule in approved_rule_items}
    if len(approved_rules) != len(approved_rule_items):
        raise ValueError("approved rule IDs must be unique")
    rule_bindings = {item.rule_id: item for item in grounding.approved_rule_bindings}
    if len(rule_bindings) != len(grounding.approved_rule_bindings):
        raise ValueError("approved rule binding IDs must be unique")
    if set(rule_bindings) != set(approved_rules):
        raise ValueError("every approved rule must have exactly one grounding binding")
    for rule_id, binding in rule_bindings.items():
        rule = approved_rules[rule_id]
        observed = {
            "rule_version": binding.rule_version,
            "authority_ref": binding.authority_ref,
            "constraint_id": binding.constraint_id,
            "coefficients": binding.coefficients,
            "sense": binding.sense,
            "rhs": binding.rhs,
            "unit": binding.unit,
            "hard": binding.hard,
            "penalty": binding.penalty,
            "evidence_refs": binding.evidence_refs,
        }
        expected = {
            "rule_version": rule.version,
            "authority_ref": rule.authority_ref,
            "constraint_id": rule.constraint_id,
            "coefficients": rule.coefficients,
            "sense": rule.sense,
            "rhs": rule.rhs,
            "unit": rule.unit,
            "hard": rule.hard,
            "penalty": rule.penalty,
            "evidence_refs": rule.evidence_refs,
        }
        if observed != expected:
            raise ValueError(f"grounded rule differs from compilation request: {rule_id}")

    objective_term_count = sum(
        len(objective.expression.terms) for objective in compilation_request.objectives
    )
    objective_terms = {
        (objective.objective_id, term.variable_id): (objective, term)
        for objective in compilation_request.objectives
        for term in objective.expression.terms
    }
    if len(objective_terms) != objective_term_count:
        raise ValueError("objective IDs and term variables must form unique pairs")
    term_bindings = {
        (item.objective_id, item.variable_id): item for item in grounding.objective_term_bindings
    }
    if len(term_bindings) != len(grounding.objective_term_bindings):
        raise ValueError("objective term bindings must be unique")
    if set(term_bindings) != set(objective_terms):
        raise ValueError("every objective term must have exactly one grounding binding")
    for key, binding in term_bindings.items():
        objective, term = objective_terms[key]
        if (
            binding.coefficient != term.coefficient
            or binding.objective_sense != objective.sense
            or binding.objective_priority != objective.priority
            or binding.objective_unit != objective.unit
            or binding.objective_component != objective.component
            or binding.objective_origin_refs != objective.origin_refs
        ):
            raise ValueError(f"grounded objective term differs from request: {key}")

    objective_constants = {
        objective.objective_id: objective
        for objective in compilation_request.objectives
        if objective.expression.constant != 0
    }
    constant_bindings = {item.objective_id: item for item in grounding.objective_constant_bindings}
    if len(constant_bindings) != len(grounding.objective_constant_bindings):
        raise ValueError("objective constant bindings must be unique")
    if set(constant_bindings) != set(objective_constants):
        raise ValueError(
            "every non-zero objective constant must have exactly one grounding binding"
        )
    for objective_id, binding in constant_bindings.items():
        objective = objective_constants[objective_id]
        if (
            binding.constant != objective.expression.constant
            or binding.objective_sense != objective.sense
            or binding.objective_priority != objective.priority
            or binding.objective_unit != objective.unit
            or binding.objective_component != objective.component
            or binding.objective_origin_refs != objective.origin_refs
        ):
            raise ValueError(f"grounded objective constant differs from request: {objective_id}")

    tasks = {task.task_id: task for task in scheduling_problem.tasks}
    task_bindings = {item.task_id: item for item in grounding.schedule_task_bindings}
    if len(task_bindings) != len(grounding.schedule_task_bindings):
        raise ValueError("schedule task bindings must be unique")
    if set(task_bindings) != set(tasks):
        raise ValueError("every schedule task must have exactly one grounding binding")
    for task_id, binding in task_bindings.items():
        task = tasks[task_id]
        observed = binding.model_dump(exclude={"binding_id", "span"})
        expected = task.model_dump()
        if observed != expected:
            raise ValueError(f"grounded schedule task differs from request: {task_id}")


def build_demonstrator_grounding(
    *,
    source_id: str,
    source_text: str,
    compilation_request: CompilationRequest,
    scheduling_problem: SchedulingProblem,
    approval: ReviewerApproval,
    approved_rule_bindings: tuple[ApprovedRuleGrounding, ...],
    objective_term_bindings: tuple[ObjectiveTermGrounding, ...],
    objective_constant_bindings: tuple[ObjectiveConstantGrounding, ...] = (),
    schedule_task_bindings: tuple[ScheduleTaskGrounding, ...],
) -> DemonstratorGrounding:
    """Construct and immediately replay the reviewed bridge artifact."""

    payload = {
        "source_id": source_id,
        "source_sha256": _sha256_text(source_text),
        "compilation_request_sha256": stable_hash(compilation_request.model_dump(mode="json")),
        "scheduling_problem_sha256": scheduling_problem.digest,
        "approval": approval,
        "approved_rule_bindings": approved_rule_bindings,
        "objective_term_bindings": objective_term_bindings,
        "objective_constant_bindings": objective_constant_bindings,
        "schedule_task_bindings": schedule_task_bindings,
        "generated_candidate_solver_authority": False,
    }
    serialized = {
        key: (
            value.model_dump(mode="json")
            if isinstance(value, StrictContract)
            else (
                [item.model_dump(mode="json") for item in value]
                if isinstance(value, tuple)
                else value
            )
        )
        for key, value in payload.items()
    }
    serialized["schema_version"] = "resource-portfolio-demonstrator-grounding/v1"
    grounding = DemonstratorGrounding(
        **payload,
        grounding_sha256=stable_hash(serialized),
    )
    verify_demonstrator_grounding(
        grounding,
        source_text=source_text,
        compilation_request=compilation_request,
        scheduling_problem=scheduling_problem,
    )
    return grounding


__all__ = [
    "ApprovedRuleGrounding",
    "DemonstratorGrounding",
    "ExactGroundingSpan",
    "ObjectiveConstantGrounding",
    "ObjectiveTermGrounding",
    "ReviewerApproval",
    "ScheduleTaskGrounding",
    "build_demonstrator_grounding",
    "exact_grounding_span",
    "verify_demonstrator_grounding",
]
