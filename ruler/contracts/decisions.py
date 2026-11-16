# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Neutral evaluation input and output envelopes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, model_validator

from ruler.contracts.common import EvaluationStatus, StrictContract
from ruler.contracts.cases import CaseContext


class EvaluationRequest(StrictContract):
    request_id: str
    requested_at: datetime
    requested_by: str
    domain_id: str
    corpus_id: str
    release_id: str
    context: CaseContext
    rule_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def context_matches_domain(self) -> "EvaluationRequest":
        if self.context.domain_id != self.domain_id:
            raise ValueError("request and context domain_id must match")
        return self


class RuleConsequence(StrictContract):
    consequence_id: str
    rule_id: str
    status: EvaluationStatus
    effect: str
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)
    facts_used: tuple[str, ...] = ()
    uncertainty_flags: tuple[str, ...] = ()


class EvaluationPacket(StrictContract):
    packet_id: str
    request_id: str
    domain_id: str
    corpus_id: str
    release_id: str
    consequences: tuple[RuleConsequence, ...]
    rules_fired: tuple[str, ...] = ()
    trace_refs: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consequences_are_unique(self) -> "EvaluationPacket":
        ids = [item.consequence_id for item in self.consequences]
        if len(ids) != len(set(ids)):
            raise ValueError("consequence identifiers must be unique")
        return self
