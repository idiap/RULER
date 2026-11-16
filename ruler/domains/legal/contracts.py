# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Source-bound contracts for reviewable legal interpretation.

These contracts deliberately separate legal interpretation from executable rule
evaluation.  A proof can establish a property of an encoding; it cannot by itself
establish the governing law or resolve an open-textured legal concept.
"""

from __future__ import annotations

import hashlib
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract, validate_sha256


class AuthorityKind(StrEnum):
    CONSTITUTION = "constitution"
    STATUTE = "statute"
    REGULATION = "regulation"
    CASE_LAW = "case_law"
    ADMINISTRATIVE_GUIDANCE = "administrative_guidance"
    CONTRACT = "contract"
    DOCTRINE = "doctrine"


class BindingForce(StrEnum):
    BINDING = "binding"
    PERSUASIVE = "persuasive"
    FACT_SPECIFIC = "fact_specific"
    UNKNOWN_REQUIRES_REVIEW = "unknown_requires_review"


class ClaimType(StrEnum):
    MATERIAL_FACT = "material_fact"
    PARTY_POSITION = "party_position"
    NORM = "norm"
    HOLDING = "holding"
    INTERPRETATION = "interpretation"
    INFERENCE = "inference"
    WARRANT = "warrant"
    DEFEATER = "defeater"
    CONCEPT_READING = "concept_reading"
    OUTCOME = "outcome"
    REMEDY = "remedy"
    FORMAL_PROPOSITION = "formal_proposition"


class InterpretationMethod(StrEnum):
    TEXTUAL = "textual"
    SYSTEMATIC = "systematic"
    HISTORICAL = "historical"
    TELEOLOGICAL = "teleological"
    PRECEDENT = "precedent"
    ANALOGY = "analogy"
    DISTINCTION = "distinction"
    CONSTITUTION_CONFORMING = "constitution_conforming"


class BurdenKind(StrEnum):
    PRODUCTION = "production"
    PERSUASION = "persuasion"
    REVIEW = "review"


class ProofClassification(StrEnum):
    TYPE_WELL_FORMEDNESS = "type_well_formedness"
    SOURCE_IDENTITY = "source_identity_carried"
    SEMANTIC_PRESERVATION = "semantic_preservation"
    LOGICAL_CONSISTENCY = "logical_consistency"
    BOUNDED_ENTAILMENT = "bounded_entailment"
    COUNTEREXAMPLE = "counterexample"
    CASE_APPLICATION = "case_application"
    LEGAL_REVIEW = "legal_review_obligation"


class EpistemicStrength(StrEnum):
    SYNTACTIC_ONLY = "syntactic_only"
    PROVENANCE_ONLY = "provenance_only"
    MODEL_ADEQUACY = "model_adequacy"
    BOUNDED_LOGICAL_CONSEQUENCE = "bounded_logical_consequence"
    CASE_SPECIFIC_APPLICATION = "case_specific_application"
    HUMAN_LEGAL_JUDGMENT_REQUIRED = "human_legal_judgment_required"


class ProofStatus(StrEnum):
    NOT_ATTEMPTED = "not_attempted"
    TYPECHECKED = "typechecked"
    PROVED = "proved"
    COUNTEREXAMPLE_FOUND = "counterexample_found"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNDERDETERMINED = "underdetermined"


class ProofEvidenceIdentity(StrictContract):
    """Immutable identities needed to authenticate a successful proof claim.

    The fields deliberately describe evidence rather than asserting that it is valid.
    Filesystem identity and independent replay are checked by ``legal.evidence``.
    """

    input_artifact_id: str = Field(min_length=1)
    input_digest: str
    output_artifact_id: str = Field(min_length=1)
    output_digest: str
    certificate_artifact_id: str = Field(min_length=1)
    certificate_digest: str
    engine_id: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    engine_artifact_id: str = Field(min_length=1)
    engine_digest: str
    configuration_artifact_id: str = Field(min_length=1)
    configuration_digest: str
    verifier_id: str = Field(min_length=1)
    verifier_version: str = Field(min_length=1)
    replay_artifact_id: str = Field(min_length=1)
    replay_digest: str
    verification_status: Literal["verified", "invalid", "unverified"]

    @model_validator(mode="after")
    def digests_are_canonical(self) -> "ProofEvidenceIdentity":
        for value in (
            self.input_digest,
            self.output_digest,
            self.certificate_digest,
            self.engine_digest,
            self.configuration_digest,
            self.replay_digest,
        ):
            validate_sha256(value)
        artifact_ids = {
            self.input_artifact_id,
            self.output_artifact_id,
            self.certificate_artifact_id,
            self.engine_artifact_id,
            self.configuration_artifact_id,
            self.replay_artifact_id,
        }
        if len(artifact_ids) != 6:
            raise ValueError("proof evidence roles require distinct artifact identities")
        return self


class TemporalScope(StrictContract):
    status: Literal["bounded", "unknown_requires_review", "not_applicable"]
    valid_from: date | None = None
    valid_to: date | None = None
    cutoff: date | None = None
    source_version_id: str | None = None

    @model_validator(mode="after")
    def interval_is_ordered(self) -> "TemporalScope":
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("valid_from must not be after valid_to")
        if self.status == "bounded" and not self.source_version_id:
            raise ValueError("bounded temporal scope requires source_version_id")
        return self


class ExactSourceSpan(StrictContract):
    span_id: str
    source_artifact_id: str
    stable_anchor: str
    language: str
    exact_text: str = Field(min_length=1)
    text_sha256: str
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def span_is_digest_bound(self) -> "ExactSourceSpan":
        validate_sha256(self.text_sha256)
        expected = "sha256:" + hashlib.sha256(self.exact_text.encode()).hexdigest()
        if self.text_sha256 != expected:
            raise ValueError("exact source text digest mismatch")
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be after start_char")
        if self.end_char - self.start_char != len(self.exact_text):
            raise ValueError("source offsets must describe the exact text length")
        return self


class LegalAuthority(StrictContract):
    authority_id: str
    kind: AuthorityKind
    jurisdiction: str
    issuing_body: str
    citation: str
    rank: int = Field(ge=0)
    binding_force: BindingForce
    temporal_scope: TemporalScope
    source_span_ids: tuple[str, ...] = Field(min_length=1)


class LegalClaim(StrictContract):
    claim_id: str
    claim_type: ClaimType
    statement: str = Field(min_length=1)
    jurisdiction: str
    temporal_scope: TemporalScope
    source_span_ids: tuple[str, ...] = ()
    commitment_status: Literal["candidate_uncommitted"] = "candidate_uncommitted"


class InterpretiveArgument(StrictContract):
    argument_id: str
    method: InterpretationMethod
    conclusion_claim_id: str
    premise_claim_ids: tuple[str, ...] = Field(min_length=1)
    authority_ids: tuple[str, ...] = Field(min_length=1)
    warrant: str = Field(min_length=1)
    defeater_claim_ids: tuple[str, ...] = ()
    boundary_tests: tuple[str, ...] = ()
    status: Literal["proposed", "supported", "defeated", "needs_review"] = "proposed"


class BurdenAllocation(StrictContract):
    burden_id: str
    issue_id: str
    bearer: str
    kind: BurdenKind
    standard: str = Field(min_length=1)
    discharged_by_claim_ids: tuple[str, ...] = ()
    status: Literal["open", "discharged", "failed", "needs_review"] = "open"


class LegalIssueFrame(StrictContract):
    issue_id: str
    question_presented: str = Field(min_length=1)
    governing_authority_ids: tuple[str, ...] = Field(min_length=1)
    fact_claim_ids: tuple[str, ...]
    interpretation_argument_ids: tuple[str, ...]
    burden_ids: tuple[str, ...] = ()
    requested_remedy_claim_ids: tuple[str, ...] = ()


class FormalProofObligation(StrictContract):
    obligation_id: str
    classification: ProofClassification
    epistemic_strength: EpistemicStrength
    target_claim_id: str
    premise_claim_ids: tuple[str, ...]
    trusted_assumption_ids: tuple[str, ...] = ()
    backend: Literal["lean4", "tptp_vampire", "asp", "prolog", "reference"]
    proof_status: ProofStatus = ProofStatus.NOT_ATTEMPTED
    proof_digest: str | None = None
    evidence: ProofEvidenceIdentity | None = None
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def proof_evidence_is_honest(self) -> "FormalProofObligation":
        if self.proof_digest is not None:
            validate_sha256(self.proof_digest)
        successful = self.proof_status in {ProofStatus.PROVED, ProofStatus.TYPECHECKED}
        if successful and self.evidence is None:
            raise ValueError("successful proof status requires structured proof evidence")
        if self.evidence is not None:
            if self.proof_digest != self.evidence.certificate_digest:
                raise ValueError("proof_digest must identify the declared certificate artifact")
            if successful and self.evidence.verification_status != "verified":
                raise ValueError("successful proof status requires independently verified evidence")
        return self


class ReviewGate(StrictContract):
    gate_id: str
    kind: Literal["source", "semantic", "formal", "legal", "independent"]
    status: Literal["pending", "passed", "failed", "blocked"]
    reviewer: str | None = None
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def passed_gate_is_attested(self) -> "ReviewGate":
        if self.status == "passed" and not self.reviewer:
            raise ValueError("passed review gate requires reviewer")
        return self


class LegalReasoningPacket(StrictContract):
    packet_id: str
    schema_version: Literal["1.0"] = "1.0"
    jurisdiction: str
    source_spans: tuple[ExactSourceSpan, ...] = Field(min_length=1)
    authorities: tuple[LegalAuthority, ...] = Field(min_length=1)
    claims: tuple[LegalClaim, ...] = Field(min_length=1)
    arguments: tuple[InterpretiveArgument, ...] = ()
    burdens: tuple[BurdenAllocation, ...] = ()
    issues: tuple[LegalIssueFrame, ...] = Field(min_length=1)
    proof_obligations: tuple[FormalProofObligation, ...] = ()
    review_gates: tuple[ReviewGate, ...] = ()
    reasoning_log: tuple[str, ...] = Field(min_length=1)
    commitment_status: Literal["candidate_uncommitted"] = "candidate_uncommitted"

    @model_validator(mode="after")
    def references_are_closed(self) -> "LegalReasoningPacket":  # noqa: C901
        identity_lists = (
            [item.span_id for item in self.source_spans],
            [item.authority_id for item in self.authorities],
            [item.claim_id for item in self.claims],
            [item.argument_id for item in self.arguments],
            [item.burden_id for item in self.burdens],
            [item.issue_id for item in self.issues],
        )
        if any(len(ids) != len(set(ids)) for ids in identity_lists):
            raise ValueError("legal packet identifiers must be unique")
        spans, authorities, claims, arguments, burdens, issues = map(set, identity_lists)
        if any(item.jurisdiction != self.jurisdiction for item in self.authorities):
            raise ValueError("authority jurisdiction must match packet")
        if any(item.jurisdiction != self.jurisdiction for item in self.claims):
            raise ValueError("claim jurisdiction must match packet")
        for item in self.authorities:
            _require_subset(item.source_span_ids, spans, item.authority_id, "source spans")
        for item in self.claims:
            _require_subset(item.source_span_ids, spans, item.claim_id, "source spans")
        for item in self.arguments:
            _require_subset(
                (item.conclusion_claim_id, *item.premise_claim_ids, *item.defeater_claim_ids),
                claims,
                item.argument_id,
                "claims",
            )
            _require_subset(item.authority_ids, authorities, item.argument_id, "authorities")
        for item in self.issues:
            _require_subset(item.governing_authority_ids, authorities, item.issue_id, "authorities")
            _require_subset(
                (*item.fact_claim_ids, *item.requested_remedy_claim_ids),
                claims,
                item.issue_id,
                "claims",
            )
            _require_subset(item.interpretation_argument_ids, arguments, item.issue_id, "arguments")
            _require_subset(item.burden_ids, burdens, item.issue_id, "burdens")
        for item in self.burdens:
            _require_subset((item.issue_id,), issues, item.burden_id, "issues")
            _require_subset(item.discharged_by_claim_ids, claims, item.burden_id, "claims")
        for item in self.proof_obligations:
            _require_subset(
                (item.target_claim_id, *item.premise_claim_ids),
                claims,
                item.obligation_id,
                "claims",
            )
        return self


def _require_subset(values: tuple[str, ...], allowed: set[str], owner: str, kind: str) -> None:
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"{owner}: unknown {kind}: {', '.join(unknown)}")
