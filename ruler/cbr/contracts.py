# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Strict, immutable contracts for transparent case-based reasoning."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ruler.contracts.common import StrictContract, TypedValue, validate_sha256
from ruler.evaluation.contracts import CounterfactualResult, EvaluationPacket


def content_digest(value: StrictContract) -> str:
    """Return a stable digest for a frozen contract."""
    payload = json.dumps(
        value.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


class Missingness(StrEnum):
    OBSERVED = "observed"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    REDACTED = "redacted"


class ComparisonPolicy(StrEnum):
    CATEGORICAL = "categorical"
    ORDINAL = "ordinal"
    NUMERIC_RANGE = "numeric_range"
    SET = "set"
    TEMPORAL = "temporal"
    TAXONOMY = "taxonomy"
    VERSION = "version"
    NON_COMPARABLE = "non_comparable"


class ReviewState(StrEnum):
    DRAFT = "draft"
    REVIEWED = "reviewed"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class CaseFeature(StrictContract):
    feature_id: str
    value: TypedValue | None = None
    observed_at: datetime | None = None
    source_ref: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    missingness: Missingness = Missingness.OBSERVED
    comparison_policy: ComparisonPolicy

    @model_validator(mode="after")
    def value_matches_missingness(self) -> "CaseFeature":
        if self.missingness == Missingness.OBSERVED and self.value is None:
            raise ValueError("observed features require a typed value")
        if self.missingness != Missingness.OBSERVED and self.value is not None:
            raise ValueError("unknown, redacted, and not-applicable features cannot carry values")
        if self.missingness == Missingness.OBSERVED and (
            self.observed_at is None or self.source_ref is None or self.confidence is None
        ):
            raise ValueError("observed features require timestamp, source, and confidence")
        if self.observed_at is not None and self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        return self


class CaseDisposition(StrictContract):
    disposition_id: str
    decision: str
    actor_role: str
    decided_at: datetime
    approval_refs: tuple[str, ...] = ()
    rule_release_id: str
    rule_release_sha256: str

    @model_validator(mode="after")
    def valid(self) -> "CaseDisposition":
        validate_sha256(self.rule_release_sha256)
        if self.decided_at.tzinfo is None:
            raise ValueError("decided_at must be timezone-aware")
        return self


class CBRCaseRecord(StrictContract):
    case_id: str
    case_kind: str
    domain_id: str
    schema_version: str
    opened_at: datetime
    closed_at: datetime | None = None
    as_of_date: date
    jurisdictions: tuple[str, ...]
    rule_release_id: str
    rule_release_sha256: str
    case_library_release_id: str
    case_library_release_sha256: str
    subject_ref: str
    party_refs: tuple[str, ...] = ()
    features: tuple[CaseFeature, ...]
    goals: tuple[str, ...] = ()
    hard_constraints: tuple[str, ...] = ()
    requested_action: str
    source_refs: tuple[str, ...] = ()
    evidence_digests: tuple[str, ...] = ()
    sensitivity_labels: frozenset[str] = frozenset()
    disposition: CaseDisposition | None = None
    observed_outcome_id: str | None = None
    review_state: ReviewState = ReviewState.DRAFT
    retention_policy_id: str
    supersedes_case_id: str | None = None

    @model_validator(mode="after")
    def valid_record(self) -> "CBRCaseRecord":
        validate_sha256(self.rule_release_sha256)
        validate_sha256(self.case_library_release_sha256)
        for digest in self.evidence_digests:
            validate_sha256(digest)
        if self.opened_at.tzinfo is None or (self.closed_at and self.closed_at.tzinfo is None):
            raise ValueError("case timestamps must be timezone-aware")
        if self.closed_at and self.closed_at < self.opened_at:
            raise ValueError("closed_at cannot precede opened_at")
        ids = [feature.feature_id for feature in self.features]
        if len(ids) != len(set(ids)):
            raise ValueError("case feature IDs must be unique")
        if not self.jurisdictions:
            raise ValueError("a case requires at least one jurisdiction")
        if self.review_state == ReviewState.REVIEWED and self.disposition is None:
            raise ValueError("reviewed cases require a separately recorded disposition")
        return self

    def feature_map(self) -> dict[str, CaseFeature]:
        return {feature.feature_id: feature for feature in self.features}


class FeatureDefinition(StrictContract):
    feature_id: str
    value_type: str
    comparison_policy: ComparisonPolicy
    sensitivity: Literal["public", "internal", "confidential", "restricted"] = "internal"
    missing_behavior: Literal["exclude", "ignore", "penalize"] = "ignore"
    ordinal_values: tuple[str, ...] = ()
    numeric_range: tuple[float, float] | None = None
    taxonomy_parents: dict[str, str | None] = Field(default_factory=dict)
    diversity_key: bool = False

    @model_validator(mode="after")
    def comparator_config_is_valid(self) -> "FeatureDefinition":
        if self.comparison_policy == ComparisonPolicy.ORDINAL and not self.ordinal_values:
            raise ValueError("ordinal features require an ordered vocabulary")
        if self.comparison_policy == ComparisonPolicy.NUMERIC_RANGE:
            if self.numeric_range is None or self.numeric_range[0] >= self.numeric_range[1]:
                raise ValueError("numeric comparators require an increasing range")
        return self


class FeatureWeight(StrictContract):
    feature_id: str
    weight: float = Field(gt=0, le=1)


class HardFilter(StrictContract):
    filter_id: str
    kind: Literal[
        "case_kind",
        "domain",
        "jurisdiction",
        "rule_release",
        "temporal",
        "access",
        "feature",
    ]
    feature_id: str | None = None
    required: bool = True
    max_age_days: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def feature_filter_is_named(self) -> "HardFilter":
        if (self.kind == "feature") != (self.feature_id is not None):
            raise ValueError("feature hard filters require exactly one feature_id")
        return self


class DiversityPolicy(StrictContract):
    feature_id: str | None = None
    max_per_value: int = Field(default=1, ge=1)


class SimilarityProfile(StrictContract):
    profile_id: str
    version: str
    domain_id: str
    case_kind: str
    feature_weights: tuple[FeatureWeight, ...]
    hard_filters: tuple[HardFilter, ...]
    maximum_candidate_pool: int = Field(default=100, ge=1, le=10_000)
    maximum_top_k: int = Field(default=10, ge=1, le=100)
    minimum_evidence_completeness: float = Field(default=0, ge=0, le=1)
    missing_penalty: float = Field(default=0, ge=0, le=1)
    diversity: DiversityPolicy = DiversityPolicy()
    require_contrast: bool = True

    @model_validator(mode="after")
    def weights_are_normalized(self) -> "SimilarityProfile":
        ids = [item.feature_id for item in self.feature_weights]
        if len(ids) != len(set(ids)):
            raise ValueError("profile feature weights must be unique")
        if abs(sum(item.weight for item in self.feature_weights) - 1.0) > 1e-9:
            raise ValueError("similarity weights must sum to 1")
        return self

    def sha256(self) -> str:
        return content_digest(self)


class CaseLibraryDependency(StrictContract):
    rule_release_id: str
    rule_release_sha256: str

    @field_validator("rule_release_sha256")
    @classmethod
    def digest(cls, value: str) -> str:
        return validate_sha256(value)


class CaseLibraryManifest(StrictContract):
    library_id: str
    release_id: str
    cases: tuple[CBRCaseRecord, ...]
    dependencies: tuple[CaseLibraryDependency, ...]
    profile_sha256: str
    created_at: datetime

    @model_validator(mode="after")
    def coherent(self) -> "CaseLibraryManifest":
        validate_sha256(self.profile_sha256)
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case IDs must be unique")
        dependency_keys = [
            (item.rule_release_id, item.rule_release_sha256) for item in self.dependencies
        ]
        if len(dependency_keys) != len(set(dependency_keys)):
            raise ValueError("case-library dependencies must be unique")
        dependencies = {
            (item.rule_release_id, item.rule_release_sha256) for item in self.dependencies
        }
        library_digests = {case.case_library_release_sha256 for case in self.cases}
        if len(library_digests) > 1:
            raise ValueError("all cases must pin one case-library release digest")
        for case in self.cases:
            if case.case_library_release_id != self.release_id:
                raise ValueError(f"{case.case_id} pins another case-library release")
            if case.review_state == ReviewState.DRAFT:
                raise ValueError(f"{case.case_id} is draft and cannot enter a release manifest")
            if (case.rule_release_id, case.rule_release_sha256) not in dependencies:
                raise ValueError(f"{case.case_id} has no pinned rule dependency")
        return self

    def sha256(self) -> str:
        return content_digest(self)


class ExclusionReason(StrictContract):
    filter_id: str
    code: str
    explanation: str


class FeatureContribution(StrictContract):
    feature_id: str
    similarity: float | None = Field(default=None, ge=0, le=1)
    weighted_contribution: float = Field(ge=0, le=1)
    query_missingness: Missingness
    candidate_missingness: Missingness
    explanation: str


class RetrievedCase(StrictContract):
    case_id: str
    rank: int | None = Field(default=None, ge=1)
    score: float = Field(ge=0, le=1)
    contributions: tuple[FeatureContribution, ...]
    matched_hard_filters: tuple[str, ...] = ()
    mismatched_hard_filters: tuple[ExclusionReason, ...] = ()
    material_differences: tuple[str, ...] = ()
    redacted_fields: tuple[str, ...] = ()
    eligibility: Literal["usable", "contrast_only", "excluded"]


class RetrievalRequest(StrictContract):
    request_id: str
    query_case: CBRCaseRecord
    case_library_release_id: str
    case_library_release_sha256: str
    similarity_profile_sha256: str
    rule_release_id: str
    rule_release_sha256: str
    top_k: int = Field(default=3, ge=1, le=100)
    authorized_fields: frozenset[str] = frozenset()
    maximum_candidates: int = Field(default=100, ge=1, le=10_000)

    @model_validator(mode="after")
    def digests(self) -> "RetrievalRequest":
        for value in (
            self.case_library_release_sha256,
            self.similarity_profile_sha256,
            self.rule_release_sha256,
        ):
            validate_sha256(value)
        return self


class RetrievalResult(StrictContract):
    request_id: str
    profile_sha256: str
    retrieved: tuple[RetrievedCase, ...]
    excluded_contrast: RetrievedCase | None = None
    candidate_count: int = Field(ge=0)
    trace: tuple[str, ...]

    @field_validator("profile_sha256")
    @classmethod
    def digest(cls, value: str) -> str:
        return validate_sha256(value)

    def sha256(self) -> str:
        return content_digest(self)


class AdaptationOperation(StrictContract):
    operation: Literal["add", "remove", "replace", "retain"]
    source_case_id: str
    target_field: str
    value: CaseFeature | str | None = None
    justification_code: str
    requires_formal_verification: bool = True

    @model_validator(mode="after")
    def valid_shape(self) -> "AdaptationOperation":
        if self.operation in {"add", "replace"} and self.value is None:
            raise ValueError(f"{self.operation} requires a value")
        if self.operation == "remove" and self.value is not None:
            raise ValueError("remove cannot carry a value")
        return self


class AdaptationPlan(StrictContract):
    plan_id: str
    query_case_id: str
    source_case_id: str
    rule_release_id: str
    rule_release_sha256: str
    operations: tuple[AdaptationOperation, ...]
    evidence_requirements: tuple[str, ...] = ()
    proposed_action: str | None = None

    @field_validator("rule_release_sha256")
    @classmethod
    def digest(cls, value: str) -> str:
        return validate_sha256(value)


class CBRDecisionPacket(StrictContract):
    packet_id: str
    query_case_id: str
    case_library_release_id: str
    case_library_release_sha256: str
    rule_release_id: str
    rule_release_sha256: str
    retrieval: RetrievalResult
    adaptation: AdaptationPlan
    evaluation: EvaluationPacket
    counterfactuals: tuple[CounterfactualResult, ...] = ()
    blockers: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    escalation_route: str | None = None
    proposed_disposition: str | None = None
    human_review_required: bool = True
    verification_passed: bool = False
    trace: tuple[str, ...] = ()

    @model_validator(mode="after")
    def releases_align(self) -> "CBRDecisionPacket":
        for digest in (self.case_library_release_sha256, self.rule_release_sha256):
            validate_sha256(digest)
        if self.evaluation.release_id != self.rule_release_id:
            raise ValueError("evaluation must use the decision packet's current rule release")
        if self.adaptation.rule_release_id != self.rule_release_id:
            raise ValueError("adaptation and decision packet must use the same rule release")
        if self.adaptation.query_case_id != self.query_case_id:
            raise ValueError("adaptation and decision packet must identify the same query case")
        if self.verification_passed:
            unsafe = {"unknown", "violated"}
            if (
                self.blockers
                or self.unknowns
                or any(item.status.value in unsafe for item in self.evaluation.consequences)
            ):
                raise ValueError("verification cannot pass with violated/unknown rules or blockers")
        if not self.human_review_required and not self.verification_passed:
            raise ValueError("unverified proposals cannot be marked review-free")
        return self

    def sha256(self) -> str:
        return content_digest(self)


class OutcomeObservation(StrictContract):
    outcome_id: str
    case_id: str
    observed_at: datetime
    source_ref: str
    reviewer_id: str
    original_proposer_id: str
    status: Literal["success", "failure", "partial_success", "recurrence", "unresolved"]
    loss_or_cost: TypedValue | None = None
    elapsed_seconds: int | None = Field(default=None, ge=0)
    customer_confirmed: bool | None = None
    causal_claim_boundary: str
    visibility: Literal["public", "internal", "confidential", "restricted"]
    retention_policy_id: str
    review_state: Literal["reviewed", "retired", "superseded"] = "reviewed"
    supersedes_outcome_id: str | None = None

    @model_validator(mode="after")
    def reviewed_and_independent(self) -> "OutcomeObservation":
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.reviewer_id == self.original_proposer_id:
            raise ValueError("outcome reviewer must be independent of the automated proposer")
        if self.supersedes_outcome_id == self.outcome_id:
            raise ValueError("an outcome cannot supersede itself")
        return self


class ReleaseDrift(StrictContract):
    case_id: str
    recorded_release_id: str
    current_release_id: str
    status: Literal["current", "requires_reevaluation"]
    reason: str
