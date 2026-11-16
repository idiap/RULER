# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Strict contracts for evaluation independent of recommendation and ranking."""

from __future__ import annotations

import hashlib
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.kb.formalization import SourceSpanRef
from ruler.kb.logical_ir import Atom


class EvaluationStatus(StrEnum):
    APPLICABLE = "applicable"
    INAPPLICABLE = "inapplicable"
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    EXCEPTION = "exception"
    UNKNOWN = "unknown"


class ExpectedRule(BaseModel):
    """A release-pinned rule whose absence is reported as open-world unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    modality: str
    evidence: tuple[SourceSpanRef, ...]

    @model_validator(mode="after")
    def evidence_is_required(self) -> "ExpectedRule":
        if not self.evidence:
            raise ValueError("expected rules require exact-span evidence")
        return self


class EvaluationRequest(BaseModel):
    """Facts and release identity needed for one non-ranking evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    case_id: str
    release_id: str
    facts: tuple[Atom, ...] = ()
    expected_rules: tuple[ExpectedRule, ...]

    @model_validator(mode="after")
    def rule_ids_are_unique(self) -> "EvaluationRequest":
        ids = [item.rule_id for item in self.expected_rules]
        if len(ids) != len(set(ids)):
            raise ValueError("expected rule IDs must be unique")
        if not self.release_id.strip():
            raise ValueError("evaluation requires an immutable release identity")
        return self


class RuleConsequence(BaseModel):
    """One explicit or open-world result with evidence and release provenance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    modality: str
    status: EvaluationStatus
    subject: str | None = None
    evidence: tuple[SourceSpanRef, ...]
    release_id: str
    derived_atom: str | None = None


class EvaluationTraceEvent(BaseModel):
    """Artifact-level trace event; no hidden reasoning or free-form chain of thought."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=0)
    event_type: str
    artifact_ids: tuple[str, ...]


class EvaluationPacket(BaseModel):
    """Deterministically replayable result packet."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    case_id: str
    release_id: str
    program_id: str
    program_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    consequences: tuple[RuleConsequence, ...]
    trace: tuple[EvaluationTraceEvent, ...]

    def sha256(self) -> str:
        payload = self.model_dump_json(exclude_none=True)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CounterfactualChange(BaseModel):
    """Status change caused by an explicitly identified fact intervention."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str
    baseline_status: EvaluationStatus
    counterfactual_status: EvaluationStatus


class CounterfactualResult(BaseModel):
    """Replayable before/after packets plus their material status changes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    probe_id: str
    baseline: EvaluationPacket
    counterfactual: EvaluationPacket
    changes: tuple[CounterfactualChange, ...]
