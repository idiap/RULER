# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Neutral source, evidence, and normative-unit contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from ruler.contracts.common import (
    NormativeModality,
    ReviewStatus,
    StrictContract,
    validate_sha256,
)


class AuthoritativeSource(StrictContract):
    source_id: str
    uri: str
    document_kind: str
    issuing_authority: str | None = None
    publisher: str | None = None
    version: str | None = None
    language: str
    retrieved_at: datetime | None = None
    content_sha256: str
    extraction_quality: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _hash_is_canonical = field_validator("content_sha256")(validate_sha256)


class EvidenceSpan(StrictContract):
    span_id: str
    source_id: str
    source_version: str
    text_sha256: str
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    character_start: int | None = Field(default=None, ge=0)
    character_end: int | None = Field(default=None, ge=1)
    section: str | None = None
    selector: dict[str, Any] = Field(default_factory=dict)

    _hash_is_canonical = field_validator("text_sha256")(validate_sha256)

    @model_validator(mode="after")
    def coordinates_are_complete_and_ordered(self) -> "EvidenceSpan":
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("page coordinates must be supplied together")
        if (
            self.page_start is not None
            and self.page_end is not None
            and self.page_end < self.page_start
        ):
            raise ValueError("page_end must be >= page_start")
        if (self.character_start is None) != (self.character_end is None):
            raise ValueError("character coordinates must be supplied together")
        if (
            self.character_start is not None
            and self.character_end is not None
            and self.character_end <= self.character_start
        ):
            raise ValueError("character_end must be > character_start")
        if self.page_start is None and self.character_start is None and not self.selector:
            raise ValueError(
                "an evidence span requires exact page, character, or selector coordinates"
            )
        return self


class NormativeUnit(StrictContract):
    unit_id: str
    source_id: str
    title: str | None = None
    modality: NormativeModality
    subject: str
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    review_status: ReviewStatus = ReviewStatus.DRAFT
    language: str
    conditions: tuple[str, ...] = ()
    exceptions: tuple[str, ...] = ()
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def evidence_is_unique(self) -> "NormativeUnit":
        if len(set(self.evidence_span_ids)) != len(self.evidence_span_ids):
            raise ValueError("evidence_span_ids must be unique")
        if self.review_status == ReviewStatus.APPROVED and self.modality in {
            NormativeModality.UNKNOWN,
            NormativeModality.NON_FORMALIZABLE,
        }:
            raise ValueError("unknown or non-formalizable units cannot be approved")
        return self
