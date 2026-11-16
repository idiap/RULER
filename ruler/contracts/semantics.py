# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Renderer-neutral semantic basis for source-grounded formalization."""

from __future__ import annotations

import hashlib
import re
from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract, validate_sha256


class SemanticElementKind(StrEnum):
    ENTITY = "entity"
    RELATION = "relation"
    PROPOSITION = "proposition"
    CONNECTIVE = "connective"
    QUANTITY = "quantity"
    TEMPORAL_RELATION = "temporal_relation"
    COREFERENCE = "coreference"
    EXCEPTION = "exception"
    COUNTER_EXCEPTION = "counter_exception"


class SemanticModality(StrEnum):
    ASSERTED = "asserted"
    OBLIGATORY = "obligatory"
    PERMITTED = "permitted"
    PROHIBITED = "prohibited"
    DEFINED = "defined"
    OPEN = "open"


class SemanticSourceSpan(StrictContract):
    span_id: str
    artifact_id: str
    artifact_sha256: str
    exact_text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)

    @model_validator(mode="after")
    def offsets_and_digest_are_well_formed(self) -> "SemanticSourceSpan":
        validate_sha256(self.artifact_sha256)
        if self.end_char - self.start_char != len(self.exact_text):
            raise ValueError("source offsets must equal exact text length")
        return self

    def verify_against(self, artifact: bytes) -> None:
        digest = "sha256:" + hashlib.sha256(artifact).hexdigest()
        if digest != self.artifact_sha256:
            raise ValueError(f"{self.span_id}: source artifact digest mismatch")
        try:
            text = artifact.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{self.span_id}: source artifact is not UTF-8") from exc
        if text[self.start_char : self.end_char] != self.exact_text:
            raise ValueError(f"{self.span_id}: exact text does not match source artifact offsets")


class SemanticRole(StrictContract):
    role: Literal[
        "actor", "action", "object", "condition", "exception", "quantity", "time", "antecedent"
    ]
    element_id: str


class SemanticTemporalConstraint(StrictContract):
    """Typed temporal meaning retained before engine-specific compilation."""

    kind: Literal["relative_deadline", "rolling_window", "effective_version"]
    anchor_event: str | None = None
    amount: int | None = Field(default=None, gt=0)
    unit: Literal["hours", "calendar_days", "business_days"] | None = None
    comparison: Literal["before", "before_or_on", "after", "after_or_on"] | None = None
    effective_from: date | None = None
    effective_until: date | None = None
    start_inclusive: bool | None = None
    end_inclusive: bool | None = None
    version_id: str | None = None
    precedence_rank: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def temporal_shape_is_typed(self) -> "SemanticTemporalConstraint":
        duration_fields = (self.anchor_event, self.amount, self.unit, self.comparison)
        if self.kind in {"relative_deadline", "rolling_window"}:
            if any(value is None for value in duration_fields):
                raise ValueError(f"{self.kind} requires anchor, amount, unit, and comparison")
            if self.kind == "rolling_window" and (
                self.start_inclusive is None or self.end_inclusive is None
            ):
                raise ValueError("rolling_window requires explicit boundary inclusivity")
            if any(
                value is not None
                for value in (
                    self.effective_from,
                    self.effective_until,
                    self.version_id,
                    self.precedence_rank,
                )
            ):
                raise ValueError(f"{self.kind} cannot carry effective-version fields")
        else:
            if (
                self.effective_from is None
                or self.version_id is None
                or self.precedence_rank is None
            ):
                raise ValueError(
                    "effective_version requires effective_from, version_id, and precedence_rank"
                )
            if self.effective_until is not None and self.effective_from > self.effective_until:
                raise ValueError("effective version start must not follow its end")
            if any(value is not None for value in duration_fields):
                raise ValueError("effective_version cannot carry relative-duration fields")
            if self.start_inclusive is None or self.end_inclusive is None:
                raise ValueError("effective_version requires explicit boundary inclusivity")
        return self


class SemanticElement(StrictContract):
    element_id: str
    kind: SemanticElementKind
    predicate: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    roles: tuple[SemanticRole, ...] = ()
    modality: SemanticModality = SemanticModality.ASSERTED
    polarity: Literal["positive", "negative"] = "positive"
    connective: Literal["and", "or", "unless", "if", "iff", "none"] = "none"
    value: str | int | float | None = None
    unit: str | None = None
    source_span_ids: tuple[str, ...] = Field(min_length=1)
    candidate_assumption_ids: tuple[str, ...] = ()
    formalization_unit_ids: tuple[str, ...] = ()
    temporal: SemanticTemporalConstraint | None = None

    @model_validator(mode="after")
    def remains_atomic_and_typed(self) -> "SemanticElement":
        if len(self.predicate.split("_")) > 8 or re.search(
            r"\b(that|which|because|therefore)\b", self.predicate
        ):
            raise ValueError("sentence-shaped predicates are prohibited")
        if self.kind == SemanticElementKind.QUANTITY and (self.value is None or not self.unit):
            raise ValueError("quantity elements require value and unit")
        if self.kind == SemanticElementKind.TEMPORAL_RELATION and self.temporal is None:
            raise ValueError("temporal_relation elements require a typed temporal constraint")
        if self.temporal is not None and self.kind != SemanticElementKind.TEMPORAL_RELATION:
            raise ValueError("typed temporal constraints belong only to temporal_relation elements")
        if len(self.formalization_unit_ids) != len(set(self.formalization_unit_ids)):
            raise ValueError("formalization unit links must be unique")
        return self


class SemanticBasis(StrictContract):
    basis_id: str
    context_id: str
    spans: tuple[SemanticSourceSpan, ...] = Field(min_length=1)
    elements: tuple[SemanticElement, ...] = Field(min_length=1)
    assumption_ids: tuple[str, ...] = ()
    commitment_status: Literal["candidate_uncommitted"] = "candidate_uncommitted"

    @model_validator(mode="after")
    def graph_is_closed_and_grounded(self) -> "SemanticBasis":
        span_ids = [item.span_id for item in self.spans]
        element_ids = [item.element_id for item in self.elements]
        if len(span_ids) != len(set(span_ids)) or len(element_ids) != len(set(element_ids)):
            raise ValueError("semantic basis identifiers must be unique")
        known_spans, known_elements = set(span_ids), set(element_ids)
        assumptions = set(self.assumption_ids)
        for item in self.elements:
            if unknown := set(item.source_span_ids) - known_spans:
                raise ValueError(f"{item.element_id}: unknown source spans: {sorted(unknown)}")
            if unknown := set(item.candidate_assumption_ids) - assumptions:
                raise ValueError(
                    f"{item.element_id}: unknown candidate assumptions: {sorted(unknown)}"
                )
            for role in item.roles:
                if role.element_id not in known_elements:
                    raise ValueError(f"{item.element_id}: dangling semantic role {role.element_id}")
        return self

    def verify_source_artifacts(self, artifacts: dict[str, bytes]) -> None:
        for span in self.spans:
            if span.artifact_id not in artifacts:
                raise ValueError(f"{span.span_id}: source artifact is unavailable")
            span.verify_against(artifacts[span.artifact_id])

    def verify_logical_units(
        self,
        unit_to_element_ids: dict[str, tuple[str, ...]],
        unit_deontic_operators: dict[str, str] | None = None,
    ) -> None:
        """Require a total, bidirectional basis→unit→element relation."""

        elements = {item.element_id: item for item in self.elements}
        known_units = set(unit_to_element_ids)
        for element in self.elements:
            if not element.formalization_unit_ids:
                raise ValueError(
                    f"{element.element_id}: semantic element has no formalization unit"
                )
            if unknown := set(element.formalization_unit_ids) - known_units:
                raise ValueError(
                    f"{element.element_id}: unknown formalization units: {sorted(unknown)}"
                )
        for unit_id, element_ids in unit_to_element_ids.items():
            if unknown := set(element_ids) - set(elements):
                raise ValueError(f"{unit_id}: unknown semantic elements: {sorted(unknown)}")
            for element_id in element_ids:
                if unit_id not in elements[element_id].formalization_unit_ids:
                    raise ValueError(f"{unit_id}: semantic unit link is not bidirectional")
        if unit_deontic_operators is not None:
            expected_by_element = {
                "obligatory": "obligation",
                "prohibited": "prohibition",
                "permitted": "permission",
                "defined": "definition",
            }
            for element in self.elements:
                expected = expected_by_element.get(element.modality.value)
                if element.kind == SemanticElementKind.EXCEPTION:
                    expected = "exception"
                elif element.kind == SemanticElementKind.COUNTER_EXCEPTION:
                    expected = "counter_exception"
                if expected is None:
                    continue
                for unit_id in element.formalization_unit_ids:
                    if unit_deontic_operators.get(unit_id) != expected:
                        raise ValueError(
                            f"{unit_id}: deontic operator does not preserve {element.element_id} "
                            f"as {expected}"
                        )
