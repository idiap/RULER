# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Versioned contracts for controlled policy and product ingestion.

The models in this module deliberately describe artifacts rather than executing a
crawl.  Every identity that protects a lifecycle boundary is derived from canonical
content, and :func:`validate_ingestion_bundle` checks cross-artifact references before
approval, compilation, or publication.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONTRACT_VERSION = "1.0"
SHA256_PREFIX = "sha256:"


def canonical_sha256(value: Any) -> str:
    """Hash bytes directly and structured values as stable canonical JSON."""
    if isinstance(value, bytes):
        encoded = value
    else:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    return SHA256_PREFIX + hashlib.sha256(encoded).hexdigest()


def stable_id(kind: str, value: Any) -> str:
    """Return a readable deterministic identity derived from canonical content."""
    if not kind or not kind.replace("_", "").isalnum():
        raise ValueError("stable ID kind must contain only letters, digits, and underscores")
    return f"{kind}:{canonical_sha256(value).removeprefix(SHA256_PREFIX)}"


def _validate_sha256(value: str) -> str:
    digest = value.removeprefix(SHA256_PREFIX)
    if not value.startswith(SHA256_PREFIX) or len(digest) != 64:
        raise ValueError("value must use sha256:<64 lowercase hex characters>")
    if any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("sha256 digest must be lowercase hexadecimal")
    return value


class FrozenContract(BaseModel):
    """Strict immutable base for artifacts crossing ingestion boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["1.0"] = CONTRACT_VERSION


class IngestionStage(StrEnum):
    CATALOGUED = "catalogued"
    SOURCE_DISCOVERED = "source_discovered"
    FETCHED = "fetched"
    EXTRACTED = "extracted"
    SEGMENTED = "segmented"
    NORMALIZED = "normalized"
    FORMALIZATION_CANDIDATE = "formalization_candidate"
    FIDELITY_REVIEWED = "fidelity_reviewed"
    APPROVED = "approved"
    COMPILED = "compiled"
    PUBLISHED = "published"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


ACTIVE_STAGES: tuple[IngestionStage, ...] = (
    IngestionStage.CATALOGUED,
    IngestionStage.SOURCE_DISCOVERED,
    IngestionStage.FETCHED,
    IngestionStage.EXTRACTED,
    IngestionStage.SEGMENTED,
    IngestionStage.NORMALIZED,
    IngestionStage.FORMALIZATION_CANDIDATE,
    IngestionStage.FIDELITY_REVIEWED,
    IngestionStage.APPROVED,
    IngestionStage.COMPILED,
    IngestionStage.PUBLISHED,
)
TERMINAL_STAGES = frozenset(
    {IngestionStage.QUARANTINED, IngestionStage.REJECTED, IngestionStage.WITHDRAWN}
)
STAGE_OWNERS: dict[IngestionStage, str] = {
    IngestionStage.CATALOGUED: "catalogue_intake",
    IngestionStage.SOURCE_DISCOVERED: "source_registry",
    IngestionStage.FETCHED: "source_fetch",
    IngestionStage.EXTRACTED: "document_extraction",
    IngestionStage.SEGMENTED: "structural_segmentation",
    IngestionStage.NORMALIZED: "controlled_normalization",
    IngestionStage.FORMALIZATION_CANDIDATE: "autoformalization",
    IngestionStage.FIDELITY_REVIEWED: "fidelity_review",
    IngestionStage.APPROVED: "automated_release_gate",
    IngestionStage.COMPILED: "kb_compilation",
    IngestionStage.PUBLISHED: "kb_release",
    IngestionStage.QUARANTINED: "ingestion_control",
    IngestionStage.REJECTED: "human_review",
    IngestionStage.WITHDRAWN: "source_governance",
}


def allowed_stage_transition(previous: IngestionStage, following: IngestionStage) -> bool:
    """Return whether a transition is legal; active stages cannot be skipped."""
    if previous in TERMINAL_STAGES or previous == IngestionStage.PUBLISHED:
        return False
    if following in TERMINAL_STAGES:
        return True
    return ACTIVE_STAGES.index(following) == ACTIVE_STAGES.index(previous) + 1


class StageTransition(FrozenContract):
    transition_id: str
    artifact_id: str
    previous_stage: IngestionStage
    following_stage: IngestionStage
    occurred_at: datetime
    actor: str
    reason: str
    input_artifact_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def legal_transition(self) -> "StageTransition":
        """Reject skipped stages and bind the transition ID to its audit payload."""
        if not allowed_stage_transition(self.previous_stage, self.following_stage):
            raise ValueError(
                f"illegal ingestion transition {self.previous_stage} -> {self.following_stage}"
            )
        expected = stable_id(
            "transition",
            {
                "artifact_id": self.artifact_id,
                "previous_stage": self.previous_stage,
                "following_stage": self.following_stage,
                "occurred_at": self.occurred_at,
                "actor": self.actor,
                "reason": self.reason,
                "input_artifact_ids": self.input_artifact_ids,
            },
        )
        if self.transition_id != expected:
            raise ValueError("transition_id does not match transition content")
        return self


class ArtifactRecord(FrozenContract):
    artifact_id: str
    artifact_type: str
    stage: IngestionStage
    owner: str
    payload_sha256: str
    prerequisite_artifact_ids: tuple[str, ...] = ()

    _hash = field_validator("payload_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def owner_matches_stage(self) -> "ArtifactRecord":
        """Ensure only the component assigned to a lifecycle stage owns its output."""
        if self.owner != STAGE_OWNERS[self.stage]:
            raise ValueError(f"{self.stage} artifacts must be owned by {STAGE_OWNERS[self.stage]}")
        return self


class NullMeaning(StrEnum):
    VALUE = "value"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    NOT_OFFERED = "not_offered"
    INACCESSIBLE = "inaccessible"
    PLACEHOLDER = "placeholder"
    GENUINELY_EMPTY = "genuinely_empty"


class AliasDecision(FrozenContract):
    alias_id: str
    entity_kind: Literal["client_segment", "provider", "branch", "product", "feature", "term"]
    original_value: str
    canonical_value: str
    rationale: str
    decision_state: Literal["proposed", "approved", "rejected"] = "proposed"
    reviewer_id: str | None = None

    @model_validator(mode="after")
    def stable_alias_identity(self) -> "AliasDecision":
        """Keep alias decisions reversible and content-addressed across reruns."""
        expected = stable_id(
            "alias",
            {
                "entity_kind": self.entity_kind,
                "original_value": self.original_value,
                "canonical_value": self.canonical_value,
            },
        )
        if self.alias_id != expected:
            raise ValueError("alias_id must preserve the original-to-canonical mapping")
        if self.decision_state == "approved" and not self.reviewer_id:
            raise ValueError("approved aliases require a reviewer")
        return self


class EntityAssociation(FrozenContract):
    """Domain-supplied association between a corpus record and an external entity.

    Core treats both the entity kind and its role as governed identifiers.  Commercial
    products are therefore one possible association, not a prerequisite for ingestion.
    """

    association_id: str
    domain_id: str
    entity_kind: str
    entity_id: str
    role: str
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def stable_association_identity(self) -> "EntityAssociation":
        identity = {
            "domain_id": self.domain_id,
            "entity_kind": self.entity_kind,
            "entity_id": self.entity_id,
            "role": self.role,
        }
        if self.association_id != stable_id("entity_association", identity):
            raise ValueError("association_id must derive from its governed entity coordinates")
        return self


class EntityAliasDecision(FrozenContract):
    """Open, domain-scoped counterpart of the closed v1 catalogue alias contract."""

    alias_id: str
    domain_id: str
    entity_kind: str
    original_value: str
    canonical_value: str
    rationale: str
    decision_state: Literal["proposed", "approved", "rejected"] = "proposed"
    reviewer_id: str | None = None

    @model_validator(mode="after")
    def stable_alias_identity(self) -> "EntityAliasDecision":
        identity = {
            "domain_id": self.domain_id,
            "entity_kind": self.entity_kind,
            "original_value": self.original_value,
            "canonical_value": self.canonical_value,
        }
        if self.alias_id != stable_id("entity_alias", identity):
            raise ValueError("alias_id must preserve the domain-scoped alias mapping")
        if self.decision_state == "approved" and not self.reviewer_id:
            raise ValueError("approved aliases require a reviewer")
        return self


class DomainParameterRule(FrozenContract):
    """Domain-owned typed parameter payload linked to neutral corpus records."""

    parameter_rule_id: str
    domain_id: str
    rule_kind: str
    corpus_record_ids: tuple[str, ...]
    parameters: dict[str, Any]
    candidate_only: Literal[True] = True

    @model_validator(mode="after")
    def stable_parameter_identity(self) -> "DomainParameterRule":
        identity = {
            "domain_id": self.domain_id,
            "rule_kind": self.rule_kind,
            "corpus_record_ids": self.corpus_record_ids,
            "parameters": self.parameters,
        }
        if self.parameter_rule_id != stable_id("domain_parameter_rule", identity):
            raise ValueError("parameter_rule_id must derive from its complete neutral payload")
        return self


class CorpusRecord(FrozenContract):
    """Neutral catalogue record; entity associations are optional by design."""

    record_id: str
    domain_id: str
    corpus_id: str
    record_type: str
    external_id: str
    source_reference_ids: tuple[str, ...] = ()
    entity_association_ids: tuple[str, ...] = ()
    parameter_rule_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def stable_record_identity(self) -> "CorpusRecord":
        identity = {
            "domain_id": self.domain_id,
            "corpus_id": self.corpus_id,
            "record_type": self.record_type,
            "external_id": self.external_id,
        }
        if self.record_id != stable_id("corpus_record", identity):
            raise ValueError("record_id must derive from its domain, corpus, type, and external ID")
        if len(set(self.entity_association_ids)) != len(self.entity_association_ids):
            raise ValueError("entity association references must be unique")
        return self


class WorkbookCell(FrozenContract):
    coordinate: str
    original_value: Any = None
    normalized_value: Any = None
    null_meaning: NullMeaning = NullMeaning.VALUE
    alias_id: str | None = None
    warning_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def preserve_null_semantics(self) -> "WorkbookCell":
        """Distinguish genuine values from every explicit missing-value meaning."""
        if self.null_meaning == NullMeaning.VALUE and self.original_value is None:
            raise ValueError("a missing original value requires an explicit null meaning")
        if self.null_meaning != NullMeaning.VALUE and self.normalized_value is not None:
            raise ValueError("null-valued cells cannot also have a normalized value")
        return self


class WorkbookSheetSignature(FrozenContract):
    name: str
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0)
    header_sha256: str

    _hash = field_validator("header_sha256")(_validate_sha256)


class WorkbookIntake(FrozenContract):
    intake_run_id: str
    workbook_sha256: str
    sheet_signatures: tuple[WorkbookSheetSignature, ...]
    accepted_rows: int = Field(ge=0)
    warning_rows: int = Field(ge=0)
    quarantined_rows: int = Field(ge=0)
    schema_decision: Literal["accepted", "migration_required", "quarantined"]
    ingested_at: datetime

    _hash = field_validator("workbook_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def content_derived_intake_id(self) -> "WorkbookIntake":
        """Bind an intake identity to workbook bytes and its observed sheet schema."""
        expected = stable_id(
            "workbook_intake",
            {
                "workbook_sha256": self.workbook_sha256,
                "sheet_signatures": [
                    item.model_dump(mode="json") for item in self.sheet_signatures
                ],
            },
        )
        if self.intake_run_id != expected:
            raise ValueError("intake_run_id must be derived from workbook and schema signatures")
        if self.schema_decision == "accepted" and self.quarantined_rows:
            raise ValueError("an accepted intake cannot contain quarantined rows")
        return self


class CatalogueRow(FrozenContract):
    row_id: str
    intake_run_id: str
    sheet_name: str
    row_number: int = Field(ge=1)
    client_segment_id: str
    provider_id: str
    branch_id: str
    product_id: str
    feature_id: str
    source_reference_ids: tuple[str, ...] = ()
    parameter_rule_ids: tuple[str, ...] = ()
    cells: tuple[WorkbookCell, ...]
    authority: Literal["catalogue_claim"] = "catalogue_claim"

    @model_validator(mode="after")
    def stable_row_identity(self) -> "CatalogueRow":
        """Derive a row identity from immutable workbook coordinates, not display data."""
        expected = stable_id(
            "catalogue_row",
            {
                "intake_run_id": self.intake_run_id,
                "sheet_name": self.sheet_name,
                "row_number": self.row_number,
            },
        )
        if self.row_id != expected:
            raise ValueError("row_id must be derived from intake, sheet, and row coordinate")
        coordinates = [cell.coordinate for cell in self.cells]
        if len(coordinates) != len(set(coordinates)):
            raise ValueError("catalogue row cell coordinates must be unique")
        return self


class CatalogueParameterRule(FrozenContract):
    parameter_rule_id: str
    kind: Literal["service_fee", "tax", "provider_contribution", "payment_fee", "ui_sync"]
    workbook_row_ids: tuple[str, ...]
    year: int | None = None
    vehicle_type: str | None = None
    provider_id: str | None = None
    branch_id: str | None = None
    coverage_selection: tuple[str, ...] = ()
    calculation_base: str | None = None
    cadence: str | None = None
    fixed_amount: str | None = None
    percentage: str | None = None
    currency: str | None = None
    exception_conditions: tuple[str, ...] = ()
    candidate_only: Literal[True] = True


class SourceRegistryEntry(FrozenContract):
    source_task_id: str
    provider_id: str
    catalogue_row_ids: tuple[str, ...]
    product_ids: tuple[str, ...]
    submitted_urls: tuple[str, ...]
    canonical_url: str
    retrieval_url: str | None = Field(default=None, exclude_if=lambda value: value is None)
    document_ids: tuple[str, ...] = ()
    source_version_ids: tuple[str, ...] = ()
    extraction_artifact_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def stable_task_identity(self) -> "SourceRegistryEntry":
        """Give each governed identity and optional retrieval route one acquisition task."""
        if not self.catalogue_row_ids:
            raise ValueError("source tasks must resolve back to at least one catalogue row")
        identity = {
            "provider_id": self.provider_id,
            "canonical_url": self.canonical_url,
        }
        if self.retrieval_url is not None:
            identity["retrieval_url"] = self.retrieval_url
        expected = stable_id("source_task", identity)
        if self.source_task_id != expected:
            raise ValueError("source_task_id must be governed-source-route derived")
        return self


class DocumentSourceRegistryEntry(FrozenContract):
    """Acquisition task for a document-only or entity-associated corpus."""

    source_task_id: str
    domain_id: str
    corpus_id: str
    canonical_url: str
    submitted_urls: tuple[str, ...]
    publisher_id: str | None = None
    retrieval_url: str | None = None
    corpus_record_ids: tuple[str, ...] = ()
    entity_association_ids: tuple[str, ...] = ()
    document_ids: tuple[str, ...] = ()
    source_version_ids: tuple[str, ...] = ()
    extraction_artifact_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def stable_document_task_identity(self) -> "DocumentSourceRegistryEntry":
        identity = {
            "domain_id": self.domain_id,
            "corpus_id": self.corpus_id,
            "canonical_url": self.canonical_url,
            "publisher_id": self.publisher_id,
        }
        if self.retrieval_url is not None:
            identity["retrieval_url"] = self.retrieval_url
        if self.source_task_id != stable_id("source_task", identity):
            raise ValueError("source_task_id must derive from domain, corpus, and source route")
        if not self.submitted_urls:
            raise ValueError("document source tasks require at least one submitted URL")
        return self


class SourceVersion(FrozenContract):
    source_version_id: str
    source_task_id: str
    raw_sha256: str
    byte_length: int = Field(ge=0)
    retrieved_at: datetime
    submitted_url: str
    final_url: str
    http_status: int = Field(ge=100, le=599)
    redirect_chain: tuple[str, ...] = ()
    content_type: str
    etag: str | None = None
    last_modified: str | None = None
    detected_language: str | None = None
    document_edition: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    predecessor_version_id: str | None = None
    supersedes_version_id: str | None = None
    withdrawn_at: datetime | None = None

    _hash = field_validator("raw_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def content_derived_version(self) -> "SourceVersion":
        """Make a document edition immutable by deriving its ID from the raw hash."""
        expected = stable_id(
            "source_version",
            {"source_task_id": self.source_task_id, "raw_sha256": self.raw_sha256},
        )
        if self.source_version_id != expected:
            raise ValueError("source_version_id must be derived from task and raw content hash")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must not precede effective_from")
        return self


class FetchResult(FrozenContract):
    fetch_result_id: str
    source_task_id: str
    fetched_at: datetime
    outcome: Literal["fetched", "not_modified", "transient_error", "terminal_error", "quarantined"]
    source_version_id: str | None = None
    response_sha256: str | None = None
    error_code: str | None = None
    attempt: int = Field(ge=1)

    @model_validator(mode="after")
    def outcome_has_matching_evidence(self) -> "FetchResult":
        """Require version evidence for success and a typed code for fetch failures."""
        if self.outcome == "fetched" and not self.source_version_id:
            raise ValueError("a fetched result requires a source version")
        if self.outcome.endswith("error") and not self.error_code:
            raise ValueError("an error result requires an error code")
        if self.response_sha256:
            _validate_sha256(self.response_sha256)
        return self


class ExtractionArtifact(FrozenContract):
    extraction_artifact_id: str
    source_version_id: str
    extractor: str
    extractor_version: str
    configuration_sha256: str
    raw_output_sha256: str
    cleaned_view_sha256: str
    quality: float = Field(ge=0.0, le=1.0)
    status: Literal["complete", "partial", "quarantined"]
    warnings: tuple[str, ...] = ()

    _hashes = field_validator("configuration_sha256", "raw_output_sha256", "cleaned_view_sha256")(
        _validate_sha256
    )


class OCRQualityState(StrEnum):
    NOT_REQUIRED = "not_required"
    REQUIRED = "required"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    BLOCKED_ENCRYPTED = "blocked_encrypted"
    BLOCKED_PASSWORD = "blocked_password"


class PageExtractionQuality(FrozenContract):
    page: int = Field(ge=1)
    native_text_characters: int = Field(ge=0)
    extracted_text_sha256: str
    quality: float = Field(ge=0.0, le=1.0)
    rotation_degrees: Literal[0, 90, 180, 270] = 0
    detected_languages: tuple[str, ...] = ()
    table_count: int = Field(default=0, ge=0)
    ocr_state: OCRQualityState = OCRQualityState.NOT_REQUIRED
    warnings: tuple[str, ...] = ()

    _hash = field_validator("extracted_text_sha256")(_validate_sha256)


class StructuralElement(FrozenContract):
    element_id: str
    extraction_artifact_id: str
    source_version_id: str
    kind: Literal["heading", "paragraph", "list", "table", "footnote", "annex", "cross_reference"]
    page: int | None = Field(default=None, ge=1)
    bounding_box: tuple[float, float, float, float] | None = None
    character_offsets: tuple[int, int] | None = None
    heading_ancestry: tuple[str, ...] = ()
    table_lineage: tuple[str, ...] = ()
    neighboring_element_ids: tuple[str, ...] = ()
    cross_reference_targets: tuple[str, ...] = ()
    text_sha256: str

    _hash = field_validator("text_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> "StructuralElement":
        """Protect stable source anchors from inverted character coordinates."""
        if self.character_offsets and self.character_offsets[1] < self.character_offsets[0]:
            raise ValueError("character offsets must be ordered")
        return self


class LayoutAwareChunk(FrozenContract):
    chunk_id: str
    source_version_id: str
    structural_element_ids: tuple[str, ...]
    page_start: int = Field(ge=1)
    page_end: int = Field(ge=1)
    bounding_boxes: tuple[tuple[float, float, float, float], ...] = ()
    character_offsets: tuple[int, int] | None = None
    heading_ancestry: tuple[str, ...] = ()
    table_lineage: tuple[str, ...] = ()
    neighboring_context_ids: tuple[str, ...] = ()
    cross_reference_targets: tuple[str, ...] = ()
    raw_text_sha256: str
    cleaned_text_sha256: str

    _hashes = field_validator("raw_text_sha256", "cleaned_text_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def stable_layout_identity(self) -> "LayoutAwareChunk":
        """Bind chunk identity to source version and layout rather than processing rank."""
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        coordinates = {
            "source_version_id": self.source_version_id,
            "structural_element_ids": self.structural_element_ids,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "bounding_boxes": self.bounding_boxes,
            "character_offsets": self.character_offsets,
            "heading_ancestry": self.heading_ancestry,
            "table_lineage": self.table_lineage,
        }
        if self.chunk_id != stable_id("layout_chunk", coordinates):
            raise ValueError("chunk_id must derive from source version and structural coordinates")
        return self


class TriageDecision(FrozenContract):
    triage_decision_id: str
    structural_element_id: str
    disposition: Literal["keep", "defer", "omit", "duplicate", "quarantine"]
    recommendation_materiality: Literal["material", "not_material", "unresolved"]
    rationale: str
    reviewer_id: str | None = None
    review_state: Literal["draft", "reviewed"] = "draft"

    @model_validator(mode="after")
    def omission_requires_review(self) -> "TriageDecision":
        """Prevent recommendation-material content from being silently omitted."""
        if self.disposition == "omit" and (
            self.recommendation_materiality != "not_material" or self.review_state != "reviewed"
        ):
            raise ValueError("omission requires a reviewed not-material decision")
        return self


class TranslationUnit(FrozenContract):
    translation_unit_id: str
    structural_element_ids: tuple[str, ...]
    source_language: str
    source_text_sha256: str
    controlled_english: str
    controlled_english_sha256: str
    terminology_decision_ids: tuple[str, ...] = ()
    review_state: Literal["draft", "reviewed", "approved"] = "draft"

    _hashes = field_validator("source_text_sha256", "controlled_english_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def recompute_translation_hash(self) -> "TranslationUnit":
        """Detect any drift between controlled English and its declared content hash."""
        if self.controlled_english_sha256 != canonical_sha256(self.controlled_english):
            raise ValueError("controlled English hash does not match its text")
        return self


class FormalizationCandidate(FrozenContract):
    candidate_id: str
    source_version_id: str
    source_span_ids: tuple[str, ...]
    source_text_sha256s: tuple[str, ...]
    translation_unit_ids: tuple[str, ...] = ()
    formal_element_id: str
    semantic_payload: dict[str, Any]
    semantic_sha256: str
    state: Literal["formalization_candidate", "fidelity_reviewed"] = "formalization_candidate"

    _hash = field_validator("semantic_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def recompute_candidate_hashes(self) -> "FormalizationCandidate":
        """Bind candidate identity to exact source spans and normalized semantics."""
        if not self.source_span_ids or len(self.source_span_ids) != len(self.source_text_sha256s):
            raise ValueError(
                "candidate source span IDs and text hashes must be non-empty and aligned"
            )
        expected_semantic = canonical_sha256(self.semantic_payload)
        if self.semantic_sha256 != expected_semantic:
            raise ValueError("semantic_sha256 does not match semantic_payload")
        expected_id = stable_id(
            "formalization_candidate",
            {
                "source_version_id": self.source_version_id,
                "source_span_ids": self.source_span_ids,
                "source_text_sha256s": self.source_text_sha256s,
                "formal_element_id": self.formal_element_id,
                "semantic_sha256": self.semantic_sha256,
            },
        )
        if self.candidate_id != expected_id:
            raise ValueError("candidate_id does not match bound source and semantics")
        return self


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"
    SUPERSEDE = "supersede"
    REVOKE = "revoke"


class HumanApproval(FrozenContract):
    """Optional human review metadata; never a publication prerequisite."""

    approval_id: str
    reviewer_id: str
    reviewer_role: str
    decided_at: datetime
    decision: ApprovalDecision
    source_version_id: str
    source_version_sha256: str
    candidate_id: str
    candidate_sha256: str
    reviewed_fields: tuple[str, ...]
    edits: tuple[dict[str, Any], ...] = ()
    bilingual_check_passed: bool
    fidelity_check_passed: bool
    rationale: str
    restrictions: tuple[str, ...] = ()
    supersedes_approval_id: str | None = None

    _hashes = field_validator("source_version_sha256", "candidate_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def validate_decision(self) -> "HumanApproval":
        """Validate optional review metadata without granting publication authority."""
        if self.decision == ApprovalDecision.APPROVE:
            if not self.bilingual_check_passed or not self.fidelity_check_passed:
                raise ValueError("approval requires passing bilingual and fidelity checks")
            if not self.reviewed_fields:
                raise ValueError("approval requires explicit reviewed fields")
        expected = stable_id(
            "approval",
            {
                "reviewer_id": self.reviewer_id,
                "decided_at": self.decided_at,
                "decision": self.decision,
                "source_version_id": self.source_version_id,
                "source_version_sha256": self.source_version_sha256,
                "candidate_id": self.candidate_id,
                "candidate_sha256": self.candidate_sha256,
                "reviewed_fields": self.reviewed_fields,
                "edits": self.edits,
                "bilingual_check_passed": self.bilingual_check_passed,
                "fidelity_check_passed": self.fidelity_check_passed,
                "rationale": self.rationale,
                "restrictions": self.restrictions,
                "supersedes_approval_id": self.supersedes_approval_id,
            },
        )
        if self.approval_id != expected:
            raise ValueError("approval_id does not match the immutable decision payload")
        return self


REQUIRED_AUTOMATED_CHECKS = frozenset(
    {"schema", "provenance", "fidelity", "coherence", "compilation", "interpretability"}
)


class AutomatedGateEvidence(FrozenContract):
    """Hash-bound deterministic and generative evidence authorizing one formal element."""

    gate_evidence_id: str
    candidate_id: str
    formal_element_id: str
    candidate_sha256: str
    semantic_sha256: str
    deterministic_checks: dict[str, bool]
    deterministic_evidence_hashes: dict[str, str]
    generative_gate_config_sha256: str
    generative_evidence_sha256: str
    generative_verdict: Literal["pass", "fail", "uncertain"]
    optional_reviewer_metadata: dict[str, str] = Field(default_factory=dict)

    _hashes = field_validator(
        "candidate_sha256",
        "semantic_sha256",
        "generative_gate_config_sha256",
        "generative_evidence_sha256",
    )(_validate_sha256)

    @model_validator(mode="after")
    def deterministic_identity(self) -> "AutomatedGateEvidence":
        """Bind automated authorization to exact deterministic and generative evidence."""
        for value in self.deterministic_evidence_hashes.values():
            _validate_sha256(value)
        expected = stable_id(
            "automated_gate",
            {
                "candidate_id": self.candidate_id,
                "formal_element_id": self.formal_element_id,
                "candidate_sha256": self.candidate_sha256,
                "semantic_sha256": self.semantic_sha256,
                "deterministic_checks": self.deterministic_checks,
                "deterministic_evidence_hashes": self.deterministic_evidence_hashes,
                "generative_gate_config_sha256": self.generative_gate_config_sha256,
                "generative_evidence_sha256": self.generative_evidence_sha256,
                "generative_verdict": self.generative_verdict,
            },
        )
        if self.gate_evidence_id != expected:
            raise ValueError("automated gate ID does not match its evidence")
        return self

    @property
    def passed(self) -> bool:
        """Return true only when every mandatory check and the model gate passed."""
        return (
            REQUIRED_AUTOMATED_CHECKS.issubset(self.deterministic_checks)
            and all(self.deterministic_checks[name] for name in REQUIRED_AUTOMATED_CHECKS)
            and REQUIRED_AUTOMATED_CHECKS.issubset(self.deterministic_evidence_hashes)
            and self.generative_verdict == "pass"
        )


class FormalElementAnnotation(FrozenContract):
    annotation_id: str
    formal_element_id: str
    semantic_sha256: str
    source_span_ids: tuple[str, ...]
    source_text_sha256s: tuple[str, ...]
    source_language: str
    source_language_gloss: str
    controlled_english: str
    terminology_decision_ids: tuple[str, ...] = ()
    review_state: Literal["draft", "needs_review", "validated", "approved", "rejected"]
    reviewer_id: str | None = None
    approved_at: datetime | None = None
    approval_id: str | None = None

    _hash = field_validator("semantic_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def validate_annotation(self) -> "FormalElementAnnotation":
        """Keep bilingual commentary traceable to the same semantics and source spans."""
        if not self.source_span_ids or len(self.source_span_ids) != len(self.source_text_sha256s):
            raise ValueError("annotation source span IDs and hashes must be non-empty and aligned")
        for value in self.source_text_sha256s:
            _validate_sha256(value)
        if not self.source_language_gloss.strip() or not self.controlled_english.strip():
            raise ValueError("both source-language and controlled-English glosses are required")
        expected = stable_id(
            "formal_annotation",
            {
                "formal_element_id": self.formal_element_id,
                "semantic_sha256": self.semantic_sha256,
                "source_span_ids": self.source_span_ids,
                "source_text_sha256s": self.source_text_sha256s,
                "source_language": self.source_language,
                "source_language_gloss": self.source_language_gloss,
                "controlled_english": self.controlled_english,
                "terminology_decision_ids": self.terminology_decision_ids,
            },
        )
        if self.annotation_id != expected:
            raise ValueError("annotation_id does not match semantics, evidence, and glosses")
        return self


class CompiledArtifact(FrozenContract):
    compiled_artifact_id: str
    formal_element_ids: tuple[str, ...]
    annotation_ids: tuple[str, ...]
    target: Literal["prolog", "asp", "json", "rdf"]
    payload_sha256: str
    compiler_version: str

    _hash = field_validator("payload_sha256")(_validate_sha256)


class CorpusSnapshot(FrozenContract):
    corpus_snapshot_id: str
    source_version_ids: tuple[str, ...]
    source_version_sha256s: tuple[str, ...]
    created_at: datetime

    @model_validator(mode="after")
    def deterministic_snapshot(self) -> "CorpusSnapshot":
        """Make a corpus snapshot a stable, sorted set of exact source versions."""
        if len(self.source_version_ids) != len(self.source_version_sha256s):
            raise ValueError("snapshot source version IDs and hashes must align")
        if tuple(sorted(self.source_version_ids)) != self.source_version_ids:
            raise ValueError("snapshot source versions must be sorted")
        for value in self.source_version_sha256s:
            _validate_sha256(value)
        expected = stable_id(
            "corpus_snapshot",
            list(zip(self.source_version_ids, self.source_version_sha256s, strict=True)),
        )
        if self.corpus_snapshot_id != expected:
            raise ValueError("corpus_snapshot_id does not match pinned source versions")
        return self


class KBReleaseManifest(FrozenContract):
    kb_release_id: str
    corpus_snapshot_id: str
    source_version_hashes: dict[str, str]
    span_hashes: dict[str, str]
    translation_hashes: dict[str, str]
    formal_record_hashes: dict[str, str]
    automated_gate_hashes: dict[str, str]
    optional_review_hashes: dict[str, str]
    annotation_hashes: dict[str, str]
    executable_rule_hashes: dict[str, str]
    validator_hashes: dict[str, str]
    created_at: datetime
    release_status: Literal["built", "published"] = "built"

    @model_validator(mode="after")
    def deterministic_release(self) -> "KBReleaseManifest":
        """Derive the release ID from every evidence, gate, annotation, and rule hash."""
        collections = (
            self.source_version_hashes,
            self.span_hashes,
            self.translation_hashes,
            self.formal_record_hashes,
            self.automated_gate_hashes,
            self.annotation_hashes,
            self.executable_rule_hashes,
            self.validator_hashes,
        )
        if any(not collection for collection in collections):
            raise ValueError("release manifests require every artifact and validator hash class")
        for collection in collections:
            for value in collection.values():
                _validate_sha256(value)
        for value in self.optional_review_hashes.values():
            _validate_sha256(value)
        expected = stable_id(
            "kb_release",
            {
                "corpus_snapshot_id": self.corpus_snapshot_id,
                "source_version_hashes": self.source_version_hashes,
                "span_hashes": self.span_hashes,
                "translation_hashes": self.translation_hashes,
                "formal_record_hashes": self.formal_record_hashes,
                "automated_gate_hashes": self.automated_gate_hashes,
                "optional_review_hashes": self.optional_review_hashes,
                "annotation_hashes": self.annotation_hashes,
                "executable_rule_hashes": self.executable_rule_hashes,
                "validator_hashes": self.validator_hashes,
            },
        )
        if self.kb_release_id != expected:
            raise ValueError("kb_release_id does not match immutable release contents")
        return self


class IngestionBundle(FrozenContract):
    workbook_intakes: tuple[WorkbookIntake, ...] = ()
    catalogue_rows: tuple[CatalogueRow, ...] = ()
    parameter_rules: tuple[CatalogueParameterRule, ...] = ()
    source_registry: tuple[SourceRegistryEntry, ...] = ()
    entity_associations: tuple[EntityAssociation, ...] = ()
    entity_alias_decisions: tuple[EntityAliasDecision, ...] = ()
    domain_parameter_rules: tuple[DomainParameterRule, ...] = ()
    corpus_records: tuple[CorpusRecord, ...] = ()
    document_source_registry: tuple[DocumentSourceRegistryEntry, ...] = ()
    source_versions: tuple[SourceVersion, ...] = ()
    fetch_results: tuple[FetchResult, ...] = ()
    extraction_artifacts: tuple[ExtractionArtifact, ...] = ()
    structural_elements: tuple[StructuralElement, ...] = ()
    triage_decisions: tuple[TriageDecision, ...] = ()
    translation_units: tuple[TranslationUnit, ...] = ()
    candidates: tuple[FormalizationCandidate, ...] = ()
    automated_gates: tuple[AutomatedGateEvidence, ...] = ()
    approvals: tuple[HumanApproval, ...] = ()
    annotations: tuple[FormalElementAnnotation, ...] = ()
    compiled_artifacts: tuple[CompiledArtifact, ...] = ()
    snapshots: tuple[CorpusSnapshot, ...] = ()
    releases: tuple[KBReleaseManifest, ...] = ()
    artifact_records: tuple[ArtifactRecord, ...] = ()


def validate_ingestion_bundle(bundle: IngestionBundle) -> list[str]:
    """Return deterministic referential/hash errors for a complete artifact bundle."""
    errors: list[str] = []
    intakes = {item.intake_run_id: item for item in bundle.workbook_intakes}
    rows = {item.row_id: item for item in bundle.catalogue_rows}
    associations = {item.association_id: item for item in bundle.entity_associations}
    domain_parameter_rules = {
        item.parameter_rule_id: item for item in bundle.domain_parameter_rules
    }
    corpus_records = {item.record_id: item for item in bundle.corpus_records}
    parameter_rules = {item.parameter_rule_id: item for item in bundle.parameter_rules}
    registry: dict[str, SourceRegistryEntry | DocumentSourceRegistryEntry] = {
        item.source_task_id: item for item in bundle.source_registry
    }
    for task in bundle.document_source_registry:
        if task.source_task_id in registry:
            errors.append(f"{task.source_task_id}: duplicate source task identity")
        registry[task.source_task_id] = task
    versions = {item.source_version_id: item for item in bundle.source_versions}
    extractions = {item.extraction_artifact_id: item for item in bundle.extraction_artifacts}
    structural_elements = {item.element_id: item for item in bundle.structural_elements}
    translations = {item.translation_unit_id: item for item in bundle.translation_units}
    candidates = {item.candidate_id: item for item in bundle.candidates}
    approvals = {item.approval_id: item for item in bundle.approvals}
    annotations = {item.annotation_id: item for item in bundle.annotations}
    snapshots = {item.corpus_snapshot_id: item for item in bundle.snapshots}
    records = {item.artifact_id: item for item in bundle.artifact_records}

    for row in bundle.catalogue_rows:
        if row.intake_run_id not in intakes:
            errors.append(f"{row.row_id}: unknown workbook intake {row.intake_run_id}")
        for rule_id in row.parameter_rule_ids:
            if rule_id not in parameter_rules:
                errors.append(f"{row.row_id}: unknown parameter rule {rule_id}")

    for rule in bundle.parameter_rules:
        for row_id in rule.workbook_row_ids:
            if row_id not in rows:
                errors.append(f"{rule.parameter_rule_id}: unknown workbook row {row_id}")

    for task in bundle.source_registry:
        for row_id in task.catalogue_row_ids:
            if rows and row_id not in rows:
                errors.append(f"{task.source_task_id}: unknown catalogue row {row_id}")
        for version_id in task.source_version_ids:
            if version_id not in versions:
                errors.append(f"{task.source_task_id}: unknown source version {version_id}")

    for record in bundle.corpus_records:
        for association_id in record.entity_association_ids:
            association = associations.get(association_id)
            if association is None:
                errors.append(f"{record.record_id}: unknown entity association {association_id}")
            elif association.domain_id != record.domain_id:
                errors.append(
                    f"{record.record_id}: cross-domain entity association {association_id}"
                )
        for rule_id in record.parameter_rule_ids:
            rule = domain_parameter_rules.get(rule_id)
            if rule is None:
                errors.append(f"{record.record_id}: unknown domain parameter rule {rule_id}")
            elif rule.domain_id != record.domain_id:
                errors.append(f"{record.record_id}: cross-domain parameter rule {rule_id}")

    for rule in bundle.domain_parameter_rules:
        for record_id in rule.corpus_record_ids:
            if record_id not in corpus_records:
                errors.append(f"{rule.parameter_rule_id}: unknown corpus record {record_id}")

    for task in bundle.document_source_registry:
        for record_id in task.corpus_record_ids:
            record = corpus_records.get(record_id)
            if record is None:
                errors.append(f"{task.source_task_id}: unknown corpus record {record_id}")
            elif (record.domain_id, record.corpus_id) != (task.domain_id, task.corpus_id):
                errors.append(
                    f"{task.source_task_id}: corpus record {record_id} is outside its corpus"
                )
        for association_id in task.entity_association_ids:
            association = associations.get(association_id)
            if association is None:
                errors.append(f"{task.source_task_id}: unknown entity association {association_id}")
            elif association.domain_id != task.domain_id:
                errors.append(
                    f"{task.source_task_id}: cross-domain entity association {association_id}"
                )
        for version_id in task.source_version_ids:
            if version_id not in versions:
                errors.append(f"{task.source_task_id}: unknown source version {version_id}")

    for version in bundle.source_versions:
        if version.source_task_id not in registry:
            errors.append(
                f"{version.source_version_id}: unknown source task {version.source_task_id}"
            )
        for link_name, linked_id in (
            ("predecessor", version.predecessor_version_id),
            ("supersedes", version.supersedes_version_id),
        ):
            if linked_id and linked_id not in versions:
                errors.append(
                    f"{version.source_version_id}: unknown {link_name} version {linked_id}"
                )

    for fetch in bundle.fetch_results:
        if fetch.source_task_id not in registry:
            errors.append(f"{fetch.fetch_result_id}: unknown source task {fetch.source_task_id}")
        if fetch.source_version_id and fetch.source_version_id not in versions:
            errors.append(
                f"{fetch.fetch_result_id}: unknown source version {fetch.source_version_id}"
            )

    for extraction in bundle.extraction_artifacts:
        if extraction.source_version_id not in versions:
            errors.append(f"{extraction.extraction_artifact_id}: unknown source version")

    for element in bundle.structural_elements:
        if element.extraction_artifact_id not in extractions:
            errors.append(f"{element.element_id}: unknown extraction artifact")
        if element.source_version_id not in versions:
            errors.append(f"{element.element_id}: unknown source version")

    for decision in bundle.triage_decisions:
        if decision.structural_element_id not in structural_elements:
            errors.append(f"{decision.triage_decision_id}: unknown structural element")

    for translation in bundle.translation_units:
        for element_id in translation.structural_element_ids:
            if element_id not in structural_elements:
                errors.append(
                    f"{translation.translation_unit_id}: unknown structural element {element_id}"
                )

    for candidate in bundle.candidates:
        if candidate.source_version_id not in versions:
            errors.append(f"{candidate.candidate_id}: unknown source version")
        if structural_elements:
            for span_id in candidate.source_span_ids:
                if span_id not in structural_elements:
                    errors.append(f"{candidate.candidate_id}: unknown source span {span_id}")
        for translation_id in candidate.translation_unit_ids:
            if translation_id not in translations:
                errors.append(f"{candidate.candidate_id}: unknown translation {translation_id}")

    effective_approvals: dict[str, HumanApproval] = {}
    for approval in sorted(bundle.approvals, key=lambda item: item.decided_at):
        candidate = candidates.get(approval.candidate_id)
        version = versions.get(approval.source_version_id)
        if candidate is None:
            errors.append(f"{approval.approval_id}: unknown candidate {approval.candidate_id}")
            continue
        if version is None:
            errors.append(
                f"{approval.approval_id}: unknown source version {approval.source_version_id}"
            )
            continue
        actual_candidate_hash = canonical_sha256(candidate.model_dump(mode="json"))
        if approval.candidate_sha256 != actual_candidate_hash:
            errors.append(f"{approval.approval_id}: candidate payload changed after review")
        if approval.source_version_sha256 != version.raw_sha256:
            errors.append(f"{approval.approval_id}: source version changed after review")
        if approval.decision == ApprovalDecision.APPROVE:
            effective_approvals[candidate.candidate_id] = approval
        elif approval.decision in {ApprovalDecision.REVOKE, ApprovalDecision.SUPERSEDE}:
            effective_approvals.pop(candidate.candidate_id, None)

    gated_candidates: set[str] = set()
    for gate in bundle.automated_gates:
        candidate = candidates.get(gate.candidate_id)
        if candidate is None:
            errors.append(f"{gate.gate_evidence_id}: unknown candidate {gate.candidate_id}")
            continue
        if gate.formal_element_id != candidate.formal_element_id:
            errors.append(f"{gate.gate_evidence_id}: formal element differs from candidate")
        if gate.candidate_sha256 != canonical_sha256(candidate.model_dump(mode="json")):
            errors.append(
                f"{gate.gate_evidence_id}: candidate payload changed after automated gate"
            )
        if gate.semantic_sha256 != candidate.semantic_sha256:
            errors.append(f"{gate.gate_evidence_id}: semantic hash differs from candidate")
        if not gate.passed:
            errors.append(f"{gate.gate_evidence_id}: automated gate did not pass")
        else:
            gated_candidates.add(candidate.candidate_id)

    approved_elements: dict[str, FormalizationCandidate] = {
        candidate.formal_element_id: candidate
        for candidate in bundle.candidates
        if candidate.candidate_id in gated_candidates
    }
    for annotation in bundle.annotations:
        candidate = approved_elements.get(annotation.formal_element_id)
        if annotation.review_state in {"validated", "approved"}:
            if candidate is None:
                errors.append(f"{annotation.annotation_id}: annotation targets ungated element")
            elif annotation.semantic_sha256 != candidate.semantic_sha256:
                errors.append(f"{annotation.annotation_id}: semantic hash differs from candidate")
            if annotation.approval_id is not None and annotation.approval_id not in approvals:
                errors.append(f"{annotation.annotation_id}: unknown optional annotation review")

    for compiled in bundle.compiled_artifacts:
        for element_id in compiled.formal_element_ids:
            if element_id not in approved_elements:
                errors.append(f"{compiled.compiled_artifact_id}: ungated element {element_id}")
        for annotation_id in compiled.annotation_ids:
            annotation = annotations.get(annotation_id)
            if annotation is None or annotation.review_state not in {"validated", "approved"}:
                errors.append(
                    f"{compiled.compiled_artifact_id}: missing validated annotation {annotation_id}"
                )

    for snapshot in bundle.snapshots:
        for version_id, expected_hash in zip(
            snapshot.source_version_ids, snapshot.source_version_sha256s, strict=True
        ):
            version = versions.get(version_id)
            if version is None:
                errors.append(f"{snapshot.corpus_snapshot_id}: unknown source version {version_id}")
            elif version.raw_sha256 != expected_hash:
                errors.append(f"{snapshot.corpus_snapshot_id}: source version hash mismatch")

    for release in bundle.releases:
        snapshot = snapshots.get(release.corpus_snapshot_id)
        if snapshot is None:
            errors.append(f"{release.kb_release_id}: unknown corpus snapshot")
        elif release.source_version_hashes != dict(
            zip(snapshot.source_version_ids, snapshot.source_version_sha256s, strict=True)
        ):
            errors.append(f"{release.kb_release_id}: release sources differ from snapshot")
        passed_gate_ids = {item.gate_evidence_id for item in bundle.automated_gates if item.passed}
        if not set(release.automated_gate_hashes).issubset(passed_gate_ids):
            errors.append(
                f"{release.kb_release_id}: release includes failed or absent automated gate"
            )
        approved_annotation_ids = {
            item.annotation_id
            for item in bundle.annotations
            if item.review_state in {"validated", "approved"}
        }
        if not set(release.annotation_hashes).issubset(approved_annotation_ids):
            errors.append(f"{release.kb_release_id}: release includes unapproved annotation")

    for record in bundle.artifact_records:
        for prerequisite in record.prerequisite_artifact_ids:
            required = records.get(prerequisite)
            if required is None:
                errors.append(f"{record.artifact_id}: unknown prerequisite {prerequisite}")
                continue
            if required.stage in TERMINAL_STAGES:
                errors.append(f"{record.artifact_id}: prerequisite {prerequisite} is terminal")
            if record.stage in ACTIVE_STAGES and required.stage in ACTIVE_STAGES:
                if ACTIVE_STAGES.index(required.stage) >= ACTIVE_STAGES.index(record.stage):
                    errors.append(
                        f"{record.artifact_id}: prerequisite is not from an earlier stage"
                    )
        if record.stage in ACTIVE_STAGES and record.stage != IngestionStage.CATALOGUED:
            previous_stage = ACTIVE_STAGES[ACTIVE_STAGES.index(record.stage) - 1]
            prerequisite_stages = {
                records[item].stage for item in record.prerequisite_artifact_ids if item in records
            }
            if previous_stage not in prerequisite_stages:
                errors.append(
                    f"{record.artifact_id}: missing prerequisite from stage {previous_stage}"
                )
    return sorted(set(errors))


CONTRACT_MODELS: dict[str, type[BaseModel]] = {
    model.__name__: model
    for model in (
        AliasDecision,
        ArtifactRecord,
        CatalogueParameterRule,
        CatalogueRow,
        CorpusRecord,
        DomainParameterRule,
        CompiledArtifact,
        CorpusSnapshot,
        ExtractionArtifact,
        FetchResult,
        FormalElementAnnotation,
        FormalizationCandidate,
        HumanApproval,
        AutomatedGateEvidence,
        IngestionBundle,
        KBReleaseManifest,
        LayoutAwareChunk,
        DocumentSourceRegistryEntry,
        EntityAssociation,
        EntityAliasDecision,
        PageExtractionQuality,
        SourceRegistryEntry,
        SourceVersion,
        StageTransition,
        StructuralElement,
        TranslationUnit,
        TriageDecision,
        WorkbookCell,
        WorkbookIntake,
        WorkbookSheetSignature,
    )
}


def ingestion_json_schemas() -> dict[str, dict[str, Any]]:
    """Return the complete, deterministic JSON Schema catalogue for interchange."""
    return {name: model.model_json_schema() for name, model in sorted(CONTRACT_MODELS.items())}
