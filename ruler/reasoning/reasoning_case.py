# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Registry-driven domain reasoning cases."""

from __future__ import annotations
from collections.abc import Mapping
from typing import Any
from pydantic import BaseModel, ConfigDict, model_validator
from ruler.contracts.cases import CaseContext
from ruler.domains.registry import DomainRegistry


class DomainReasoningCase(BaseModel):
    """Neutral domain/corpus case that does not require application-specific decision objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    domain_id: str
    corpus_id: str
    context: CaseContext
    requested_outputs: tuple[str, ...] = (
        "fact_activation",
        "rule_evaluation",
        "consequences",
        "evidence_trace",
    )

    @model_validator(mode="after")
    def context_matches_domain(self) -> "DomainReasoningCase":
        if self.context.domain_id != self.domain_id:
            raise ValueError("case and context domain_id must match")
        if not self.corpus_id.strip():
            raise ValueError("corpus_id must not be blank")
        return self


def load_domain_reasoning_case(
    *,
    domain_id: str,
    corpus_id: str,
    case_payload: Mapping[str, Any],
    domain_registry: DomainRegistry,
) -> DomainReasoningCase:
    """Load a neutral case through its registered domain pack."""
    pack = domain_registry.get(domain_id)
    context = pack.load_case(case_payload)
    return DomainReasoningCase(
        case_id=f"reasoning_case_{domain_id}_{corpus_id}_{context.context_id}",
        domain_id=domain_id,
        corpus_id=corpus_id,
        context=context,
    )


def load_reasoning_case(
    source_mode: str | None = None,
    profile_id: str | None = None,
    *,
    domain_id: str | None = None,
    corpus_id: str | None = None,
    case_payload: Mapping[str, Any] | None = None,
    domain_registry: DomainRegistry | None = None,
) -> DomainReasoningCase:
    """Resolve a case through its domain pack, rejecting retired fixture dispatch."""
    if source_mode is not None or profile_id is not None:
        raise ValueError("source_mode/profile_id cannot be combined with domain case inputs")
    if domain_id is None or corpus_id is None or case_payload is None or domain_registry is None:
        raise ValueError(
            "domain_id, corpus_id, case_payload, and domain_registry are required together"
        )
    return load_domain_reasoning_case(
        domain_id=domain_id,
        corpus_id=corpus_id,
        case_payload=case_payload,
        domain_registry=domain_registry,
    )
