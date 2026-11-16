# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Neutral formal-rule and provenance contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from ruler.contracts.common import NormativeModality, ReviewStatus, StrictContract


class EvidenceGrounding(StrictContract):
    grounding_id: str
    normative_unit_ids: tuple[str, ...] = Field(min_length=1)
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    entailment_reviewed: bool = False
    reviewed_by: str | None = None
    notes: str = ""

    @model_validator(mode="after")
    def review_has_reviewer(self) -> "EvidenceGrounding":
        if self.entailment_reviewed and not self.reviewed_by:
            raise ValueError("reviewed grounding requires reviewed_by")
        if len(set(self.evidence_span_ids)) != len(self.evidence_span_ids):
            raise ValueError("grounding evidence spans must be unique")
        return self


class RuleValidation(StrictContract):
    schema_valid: bool = False
    compiles: bool = False
    symbolic_consistent: bool = False
    source_entails_rule: bool = False
    rule_entails_source: bool = False
    reviewed_by: str | None = None
    review_status: ReviewStatus = ReviewStatus.DRAFT

    @model_validator(mode="after")
    def approval_is_complete(self) -> "RuleValidation":
        if self.review_status == ReviewStatus.APPROVED:
            if not self.reviewed_by:
                raise ValueError("approved validation requires reviewed_by")
            gates = (
                self.schema_valid,
                self.compiles,
                self.symbolic_consistent,
                self.source_entails_rule,
                self.rule_entails_source,
            )
            if not all(gates):
                raise ValueError("approved validation requires every formal and fidelity gate")
        return self


class FormalRule(StrictContract):
    rule_id: str
    rule_version: str
    modality: NormativeModality
    scope: dict[str, str] = Field(default_factory=dict)
    applies_if: tuple[str, ...] = ()
    consequence: str
    exceptions: tuple[str, ...] = ()
    limits: tuple[dict[str, object], ...] = ()
    temporal_scope: tuple[str, ...] = ()
    grounding: EvidenceGrounding
    compiled_targets: dict[Literal["asp", "prolog"], str] = Field(default_factory=dict)
    validation: RuleValidation

    @model_validator(mode="after")
    def executable_rule_is_grounded(self) -> "FormalRule":
        if self.validation.review_status == ReviewStatus.APPROVED:
            if self.modality in {NormativeModality.UNKNOWN, NormativeModality.NON_FORMALIZABLE}:
                raise ValueError("unknown or non-formalizable rules cannot be approved")
            if not self.grounding.entailment_reviewed:
                raise ValueError("approved rules require reviewed evidence grounding")
            if not self.compiled_targets:
                raise ValueError("approved rules require an executable compiled target")
        return self
