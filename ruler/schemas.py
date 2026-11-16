# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Typed domain schema library. It defines clauses, features, rules, contexts, workflow
hooks, and provenance records so every artifact has a validated representation.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ClauseType(StrEnum):
    """Typed clause type artifact used by the schemas workflow."""

    DEFINITION = "definition"
    COVERAGE_GRANT = "coverage_grant"
    EXCLUSION = "exclusion"
    EXCEPTION_TO_EXCLUSION = "exception_to_exclusion"
    LIMIT = "limit"
    SERVICE_FEE = "service_fee"
    DUTY = "duty"
    TEMPORAL_RULE = "temporal_rule"
    OPTION_DEPENDENCY = "option_dependency"
    PRECEDENCE = "precedence"


class ReviewStatus(StrEnum):
    """Typed review status artifact used by the schemas workflow."""

    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class GroundingStatus(StrEnum):
    """Typed grounding status artifact used by the schemas workflow."""

    VERIFIED = "verified"
    VERIFIED_PARTIAL = "verified_partial"
    MARKETING_ONLY = "marketing_only"
    CONTRADICTED = "contradicted"
    STALE_SOURCE = "stale_source"
    UNKNOWN = "unknown"


class SourceRecord(BaseModel):
    """Typed source record artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    uri: str
    document_category: str
    provider: str | None = None
    product_family: str | None = None
    version: str | None = None
    retrieved_at: datetime | None = None
    raw_sha256: str
    extraction_quality: float = Field(ge=0.0, le=1.0)
    local_path: str | None = None

    @field_validator("raw_sha256")
    @classmethod
    def sha256_prefix(cls, value: str) -> str:
        """Require source hashes to use the explicit sha256 prefix."""
        if not value.startswith("sha256:") or len(value) < 20:
            raise ValueError("raw_sha256 must use sha256:<hex> form")
        return value


class SourceAnchor(BaseModel):
    """Typed source anchor artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    page: int | None = Field(default=None, ge=1)
    section: str | None = None
    span: str | None = None


class ExtractedClauseSpan(BaseModel):
    """Typed extracted clause span artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    span_id: str
    clause_id: str
    source_id: str
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    section: str
    title: str
    text: str
    text_sha256: str
    extraction_method: str
    selector: dict[str, Any]

    @field_validator("text_sha256")
    @classmethod
    def span_hash_prefix(cls, value: str) -> str:
        """Require extracted span hashes to use the explicit sha256 prefix."""
        if not value.startswith("sha256:"):
            raise ValueError("text_sha256 must use sha256:<hex> form")
        return value

    @model_validator(mode="after")
    def page_range_is_ordered(self) -> "ExtractedClauseSpan":
        """Reject empty spans and impossible page intervals before promotion."""
        if self.page_end < self.page_start:
            raise ValueError("page_end must be >= page_start")
        if not self.text.strip():
            raise ValueError("span text must not be blank")
        return self


class PolicyClause(BaseModel):
    """Typed policy clause artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    clause_id: str
    provider: str
    product_family: str
    document_type: str
    edition: str
    title: str
    raw_text_hash: str
    language: str
    clause_type: ClauseType
    modality: str
    subject: str
    source_anchor: SourceAnchor
    formalization_status: ReviewStatus
    conditions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    limits: dict[str, Any] = Field(default_factory=dict)
    source_candidate_ids: list[str] = Field(default_factory=list)
    promotion_ledger_ids: list[str] = Field(default_factory=list)
    extraction_quality_flags: list[str] = Field(default_factory=list)

    @field_validator("raw_text_hash")
    @classmethod
    def hash_prefix(cls, value: str) -> str:
        """hash prefix for this typed schemas model."""
        if not value.startswith("sha256:"):
            raise ValueError("raw_text_hash must use sha256:<hex> form")
        return value


class ValidationBlock(BaseModel):
    """Typed validation block artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    schema_valid: bool
    compiles: bool
    nli_entails_rule: bool
    nli_rule_entails_clause: bool
    symbolic_consistent: bool
    reviewed_by: str | None = None
    review_status: ReviewStatus


class PolicyRule(BaseModel):
    """Typed policy rule artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    rule_version: str
    source_clauses: list[str]
    product_scope: str
    coverage_scope: str
    applies_if: list[str]
    benefit_or_consequence: str
    exclusions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    limits: list[dict[str, Any]] = Field(default_factory=list)
    temporal_scope: list[str] = Field(default_factory=list)
    required_policy_options: list[str] = Field(default_factory=list)
    compiled_targets: dict[str, str] = Field(default_factory=dict)
    validation: ValidationBlock

    @model_validator(mode="after")
    def approved_rules_must_be_validated(self) -> "PolicyRule":
        """approved rules must be validated for this typed schemas model."""
        if self.validation.review_status == ReviewStatus.APPROVED:
            required = [
                self.validation.schema_valid,
                self.validation.compiles,
                self.validation.symbolic_consistent,
            ]
            if not all(required):
                raise ValueError("approved policy rules must be valid, compilable, and consistent")
        return self


class PolicyGrounding(BaseModel):
    """Typed policy grounding artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    status: GroundingStatus
    clauses: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def verified_requires_clause(self) -> "PolicyGrounding":
        """verified requires clause for this typed schemas model."""
        if (
            self.status in {GroundingStatus.VERIFIED, GroundingStatus.VERIFIED_PARTIAL}
            and not self.clauses
        ):
            raise ValueError("verified feature grounding requires at least one clause")
        return self


class ProductFeature(BaseModel):
    """Typed product feature artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    provider: str
    product_family: str
    product: str
    coverage_family: str
    parent_feature_id: str | None = None
    display_order: float
    labels: dict[str, str]
    is_selectable: bool
    requires: list[str] = Field(default_factory=list)
    excludes: list[str] = Field(default_factory=list)
    implies: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    pricing_refs: list[str] = Field(default_factory=list)
    policy_grounding: PolicyGrounding
    comparison_dimensions: dict[str, float | None] = Field(default_factory=dict)
    source_candidate_ids: list[str] = Field(default_factory=list)
    promotion_ledger_ids: list[str] = Field(default_factory=list)
    commercial_evidence_refs: list[str] = Field(default_factory=list)
    policy_evidence_refs: list[str] = Field(default_factory=list)


class HookCommand(BaseModel):
    """Typed hook command artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    name: str
    command: str
    required: bool = True
    local_read: bool = True
    local_write: bool = False
    external_read: bool = False
    external_write: bool = False
    network: bool = False
    deterministic: bool = True
    expected_duration: str = "short"
    cache_policy: str = "none"
    confirmation_required: bool = False
    resumable: bool = False


class WorkflowHook(BaseModel):
    """Typed workflow hook artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    hook: str
    description: str
    commands: list[HookCommand]


class SkillHookBinding(BaseModel):
    """Typed skill hook binding artifact used by the schemas workflow."""

    model_config = ConfigDict(extra="forbid")

    skill: str
    stages: list[str]
    required_inputs: list[str] = Field(default_factory=list)
    required_outputs: list[str] = Field(default_factory=list)
    validation_commands: list[str] = Field(default_factory=list)
    execution_mode: Literal["deterministic", "generative", "hybrid"] | None = None
    execution_commands: list[str] = Field(default_factory=list)
    implementation_refs: list[str] = Field(default_factory=list)
    backend_ids: list[str] = Field(default_factory=list)
    fixture_paths: list[str] = Field(default_factory=list)
    evidence_outputs: list[str] = Field(default_factory=list)
