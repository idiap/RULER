# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Governed workflow plans for case-based reasoning and case-library curation.

The module is deliberately orchestration-only: formal conclusions remain owned by
the CBR verification service and retention is never an implicit workflow side effect.
"""

from __future__ import annotations

from enum import StrEnum
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import model_validator

from ruler.contracts.common import StrictContract, validate_sha256


class CBRWorkflowStage(StrEnum):
    INTAKE = "intake"
    RETRIEVE = "retrieve"
    AUDIT = "audit"
    ADAPT = "adapt"
    VERIFY = "verify"
    REVIEW = "review"
    RETAIN = "retain"


DECISION_SEQUENCE = (
    CBRWorkflowStage.INTAKE,
    CBRWorkflowStage.RETRIEVE,
    CBRWorkflowStage.AUDIT,
    CBRWorkflowStage.ADAPT,
    CBRWorkflowStage.VERIFY,
    CBRWorkflowStage.REVIEW,
)


class CBRWorkflowRequest(StrictContract):
    """Pinned identities and explicit mutation intent for a CBR journey."""

    case_id: str
    domain_id: str
    case_library_release_id: str
    case_library_release_sha256: str
    rule_release_id: str
    rule_release_sha256: str
    similarity_profile_sha256: str
    authorized_fields: frozenset[str]
    retain_observation: bool = False
    retention_confirmed: bool = False
    reviewer_ref: str | None = None

    @model_validator(mode="after")
    def validate_boundary(self) -> "CBRWorkflowRequest":
        validate_sha256(self.case_library_release_sha256)
        validate_sha256(self.rule_release_sha256)
        validate_sha256(self.similarity_profile_sha256)
        if self.retention_confirmed and not self.retain_observation:
            raise ValueError("retention confirmation requires an explicit retention request")
        if self.retain_observation and not self.retention_confirmed:
            raise ValueError("retention must be separately confirmed")
        if self.retain_observation and not self.reviewer_ref:
            raise ValueError("retention requires an independent reviewer reference")
        return self


class WorkflowStep(StrictContract):
    stage: CBRWorkflowStage
    skill: str
    mutates_case_library: bool = False
    confirmation_required: bool = False


class CBRWorkflowPlan(StrictContract):
    request: CBRWorkflowRequest
    steps: tuple[WorkflowStep, ...]

    @model_validator(mode="after")
    def fixed_gate_order(self) -> "CBRWorkflowPlan":
        stages = tuple(step.stage for step in self.steps)
        expected = DECISION_SEQUENCE + (
            (CBRWorkflowStage.RETAIN,) if self.request.retain_observation else ()
        )
        if stages != expected:
            raise ValueError(f"CBR workflow must follow {expected}")
        retention = [step for step in self.steps if step.stage == CBRWorkflowStage.RETAIN]
        if retention and (
            not retention[0].mutates_case_library or not retention[0].confirmation_required
        ):
            raise ValueError("retention must be a confirmed case-library mutation")
        if any(step.mutates_case_library for step in self.steps[:-1]):
            raise ValueError("decision stages must remain read-only")
        return self


DOMAIN_SKILLS = {
    "spending": "spending-procurement-case-specialist",
    "regulatory": "regulatory-deployment-case-specialist",
    "fiscal": "fiscal-vat-case-specialist",
    "trade": "trade-export-control-case-specialist",
    "technical_support": "technical-support-case-specialist",
}


def build_cbr_workflow(request: CBRWorkflowRequest) -> CBRWorkflowPlan:
    """Build the immutable, gate-ordered plan for a single case journey."""
    if request.domain_id not in DOMAIN_SKILLS:
        raise ValueError(f"unsupported CBR domain: {request.domain_id}")
    steps = [
        WorkflowStep(
            stage=CBRWorkflowStage.INTAKE,
            skill=f"cbr-case-intake-normalizer+{DOMAIN_SKILLS[request.domain_id]}",
        ),
        WorkflowStep(stage=CBRWorkflowStage.RETRIEVE, skill="cbr-case-retriever"),
        WorkflowStep(stage=CBRWorkflowStage.AUDIT, skill="cbr-retrieval-auditor"),
        WorkflowStep(stage=CBRWorkflowStage.ADAPT, skill="cbr-adaptation-planner"),
        WorkflowStep(stage=CBRWorkflowStage.VERIFY, skill="cbr-formal-verification-gate"),
        WorkflowStep(stage=CBRWorkflowStage.REVIEW, skill="governance-human-review-gate"),
    ]
    if request.retain_observation:
        steps.append(
            WorkflowStep(
                stage=CBRWorkflowStage.RETAIN,
                skill="cbr-outcome-retention-curator",
                mutates_case_library=True,
                confirmation_required=True,
            )
        )
    return CBRWorkflowPlan(request=request, steps=tuple(steps))


class WorkflowService(Protocol):
    """Narrow service boundary used by the orchestrator and easy to fake in tests."""

    def intake(self, payload: Any) -> Any: ...
    def retrieve(self, payload: Any) -> Any: ...
    def audit(self, payload: Any) -> Any: ...
    def adapt(self, payload: Any) -> Any: ...
    def verify(self, payload: Any) -> Any: ...
    def review(self, payload: Any) -> Any: ...
    def retain(self, payload: Any) -> Any: ...


@dataclass
class CBRExecutionState:
    """Native cursor and references; artifacts deliberately retain result identity."""

    steps: tuple[WorkflowStep, ...]
    payload: Any
    artifacts: list[tuple[CBRWorkflowStage, Any]] = field(default_factory=list)
    position: int = 0

    @property
    def done(self) -> bool:
        return self.position == len(self.steps)


def initialize_cbr_execution(plan: CBRWorkflowPlan, initial_payload: Any) -> CBRExecutionState:
    return CBRExecutionState(steps=plan.steps, payload=initial_payload)


def invoke_cbr_stage(state: CBRExecutionState, service: WorkflowService) -> Any:
    operation = getattr(service, state.steps[state.position].stage.value)
    return operation(state.payload)


def advance_cbr_execution(state: CBRExecutionState, result: Any) -> bool:
    state.payload = result
    state.artifacts.append((state.steps[state.position].stage, state.payload))
    state.position += 1
    return state.done


def finish_cbr_execution(state: CBRExecutionState) -> tuple[tuple[CBRWorkflowStage, Any], ...]:
    return tuple(state.artifacts)


def execute_cbr_workflow(
    plan: CBRWorkflowPlan,
    service: WorkflowService,
    initial_payload: Any,
) -> tuple[tuple[CBRWorkflowStage, Any], ...]:
    """Execute a prevalidated plan through a controlled service boundary."""
    state = initialize_cbr_execution(plan, initial_payload)
    for _step in plan.steps:
        result = invoke_cbr_stage(state, service)
        advance_cbr_execution(state, result)
    return finish_cbr_execution(state)


class LibraryAction(StrEnum):
    IMPORT = "import"
    DEIDENTIFY = "deidentify"
    REVIEW = "review"
    PUBLISH = "publish"
    RETIRE = "retire"
    REEVALUATE = "reevaluate"


class CaseLibraryCurationRequest(StrictContract):
    library_id: str
    actions: tuple[LibraryAction, ...]
    source_authorized: bool
    independent_reviewer_ref: str | None = None
    publication_confirmed: bool = False
    retirement_confirmed: bool = False

    @model_validator(mode="after")
    def safe_lifecycle(self) -> "CaseLibraryCurationRequest":
        actions = self.actions
        if len(actions) != len(set(actions)):
            raise ValueError("case-library actions cannot repeat")
        if LibraryAction.IMPORT in actions and not self.source_authorized:
            raise ValueError("case import requires source authorization")
        if LibraryAction.PUBLISH in actions:
            required = (LibraryAction.IMPORT, LibraryAction.DEIDENTIFY, LibraryAction.REVIEW)
            if not all(action in actions for action in required):
                raise ValueError("publication requires import, de-identification, and review")
            if not self.independent_reviewer_ref or not self.publication_confirmed:
                raise ValueError("publication requires independent review and confirmation")
            indices = [actions.index(action) for action in (*required, LibraryAction.PUBLISH)]
            if indices != sorted(indices):
                raise ValueError("case-library publication actions are out of order")
        if LibraryAction.RETIRE in actions and not self.retirement_confirmed:
            raise ValueError("retirement requires separate confirmation")
        return self
