# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Neutral contracts that keep execution, evidence, and review orthogonal."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract, validate_sha256


class BackendCapability(StrEnum):
    HORN = "horn"
    STABLE_MODELS = "stable_models"
    DEFAULT_NEGATION = "default_negation"
    CLASSICAL_NEGATION = "classical_negation"
    FIRST_ORDER_QUANTIFICATION = "first_order_quantification"
    COUNTERMODEL = "countermodel"
    PROOF_OBJECT = "proof_object"
    TYPE_ELABORATION = "type_elaboration"
    OPTIMIZATION = "optimization"


class BackendProfile(StrictContract):
    backend_id: str
    engine: str
    capabilities: frozenset[BackendCapability]
    native_execution: Literal["built_in", "optional", "unavailable"]
    evidence_boundary: str = Field(min_length=1)


class ProjectionLoss(StrictContract):
    construct_id: str
    disposition: Literal["preserved", "approximated", "omitted", "unsupported"]
    explanation: str = Field(min_length=1)
    blocks_execution: bool


class ProjectionPolicy(StrictContract):
    policy_id: str
    source_semantics: str
    target_backend_id: str
    losses: tuple[ProjectionLoss, ...]

    @model_validator(mode="after")
    def lossy_projection_blocks_unless_explicitly_safe(self) -> "ProjectionPolicy":
        unsafe = [
            item.construct_id
            for item in self.losses
            if item.disposition in {"omitted", "unsupported"} and not item.blocks_execution
        ]
        if unsafe:
            raise ValueError(
                "omitted or unsupported constructs must block execution: " + ", ".join(unsafe)
            )
        return self

    @property
    def executable(self) -> bool:
        return not any(item.blocks_execution for item in self.losses)


class ReasoningQuery(StrictContract):
    query_id: str
    target: str
    contrary: str
    world_policy: Literal["open", "closed", "bounded"]
    required_capabilities: frozenset[BackendCapability]
    dependency_ids: tuple[str, ...] = ()
    interpretation_blocker_ids: tuple[str, ...] = ()
    factual_blocker_ids: tuple[str, ...] = ()


class ReasoningResultAxes(StrictContract):
    query_id: str
    backend_id: str
    execution: Literal["not_requested", "unavailable", "timeout", "error", "completed"]
    consistency: Literal["consistent", "inconsistent", "unknown"]
    target_support: Literal["proved", "countermodel", "not_proved", "unknown"]
    contrary_support: Literal["proved", "countermodel", "not_proved", "unknown"]
    dependency_closure: Literal["closed", "blocked", "outside_certified_scope"]
    proof_object: Literal["absent", "unverified", "verified", "invalid"]
    input_digest: str | None = None
    output_digest: str | None = None
    blockers: tuple[str, ...] = ()

    @model_validator(mode="after")
    def non_execution_has_no_output(self) -> "ReasoningResultAxes":
        if self.input_digest is not None:
            validate_sha256(self.input_digest)
        if self.output_digest is not None:
            validate_sha256(self.output_digest)
        if self.execution != "completed":
            if self.output_digest is not None:
                raise ValueError("non-completed execution cannot have an output digest")
            if self.target_support != "unknown" or self.contrary_support != "unknown":
                raise ValueError("non-completed execution cannot establish support")
        if self.proof_object == "verified" and self.execution != "completed":
            raise ValueError("verified proof object requires completed execution")
        return self

    @property
    def bounded_result(self) -> Literal["supported", "refuted", "conflict", "underdetermined"]:
        target = self.target_support == "proved"
        contrary = self.contrary_support == "proved"
        if target and contrary:
            return "conflict"
        if target:
            return "supported"
        if contrary:
            return "refuted"
        return "underdetermined"
