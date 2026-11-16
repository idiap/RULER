# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Immutable evidence binding for formally validated logical releases."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_core import to_jsonable_python

from ruler.ingestion.contracts import canonical_sha256, stable_id
from ruler.kb.asp_compiler import CompiledASP
from ruler.kb.logical_ir import LogicalProgram
from ruler.kb.prolog_compiler import CompiledProlog


def _validate_sha256(value: str) -> str:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError("hashes must use sha256:<64 lowercase hex> form")
    try:
        int(value.removeprefix("sha256:"), 16)
    except ValueError as exc:
        raise ValueError("hashes must use sha256:<64 lowercase hex> form") from exc
    if value != value.lower():
        raise ValueError("hashes must use lowercase hexadecimal")
    return value


class ValidatorEvidence(BaseModel):
    """Hash-bound result of one validator over an exact IR revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    validator_id: str
    validator_version: str
    evaluated_ir_sha256: str
    passed: bool
    issue_codes: tuple[str, ...] = ()
    evidence_sha256: str

    _ir_hash = field_validator("evaluated_ir_sha256")(_validate_sha256)
    _evidence_hash = field_validator("evidence_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def evidence_hash_matches(self) -> "ValidatorEvidence":
        payload = self.model_dump(mode="json", exclude={"evidence_sha256"})
        if self.evidence_sha256 != canonical_sha256(payload):
            raise ValueError("validator evidence hash does not match its payload")
        if self.passed and self.issue_codes:
            raise ValueError("passing validator evidence cannot retain issue codes")
        return self

    @classmethod
    def create(
        cls,
        *,
        validator_id: str,
        validator_version: str,
        evaluated_ir_sha256: str,
        passed: bool,
        issue_codes: tuple[str, ...] = (),
    ) -> "ValidatorEvidence":
        payload = {
            "validator_id": validator_id,
            "validator_version": validator_version,
            "evaluated_ir_sha256": evaluated_ir_sha256,
            "passed": passed,
            "issue_codes": issue_codes,
        }
        return cls(**payload, evidence_sha256=canonical_sha256(payload))


class FormalReviewDecision(BaseModel):
    """Immutable human or accountable-agent promotion decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_id: str
    reviewer_id: str
    decision: Literal["approved", "rejected", "hold_for_review"]
    logical_unit_ids: tuple[str, ...] = Field(min_length=1)
    rationale: str
    decided_at: datetime
    decision_sha256: str

    _decision_hash = field_validator("decision_sha256")(_validate_sha256)

    @model_validator(mode="after")
    def decision_hash_matches(self) -> "FormalReviewDecision":
        payload = self.model_dump(mode="json", exclude={"decision_sha256"})
        if self.decision_sha256 != canonical_sha256(payload):
            raise ValueError("review decision hash does not match its payload")
        if not self.rationale.strip():
            raise ValueError("review decisions require a rationale")
        return self

    @classmethod
    def create(
        cls,
        *,
        decision_id: str,
        reviewer_id: str,
        decision: Literal["approved", "rejected", "hold_for_review"],
        logical_unit_ids: tuple[str, ...],
        rationale: str,
        decided_at: datetime,
    ) -> "FormalReviewDecision":
        payload = {
            "decision_id": decision_id,
            "reviewer_id": reviewer_id,
            "decision": decision,
            "logical_unit_ids": logical_unit_ids,
            "rationale": rationale,
            "decided_at": decided_at,
        }
        json_payload = to_jsonable_python(payload)
        return cls(**payload, decision_sha256=canonical_sha256(json_payload))


class FormalLogicRelease(BaseModel):
    """Content-derived binding of every dependency needed to replay formal truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    release_id: str
    program_id: str
    source_version_hashes: dict[str, str]
    span_hashes: dict[str, str]
    ir_sha256: str
    compiler_hashes: dict[str, str]
    generated_program_hashes: dict[str, str]
    validator_hashes: dict[str, str]
    review_decision_hashes: dict[str, str]

    _ir_hash = field_validator("ir_sha256")(_validate_sha256)

    @field_validator(
        "source_version_hashes",
        "span_hashes",
        "compiler_hashes",
        "generated_program_hashes",
        "validator_hashes",
        "review_decision_hashes",
    )
    @classmethod
    def hash_maps_are_nonempty_and_valid(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("formal releases require every hash class")
        for digest in value.values():
            _validate_sha256(digest)
        return value

    @model_validator(mode="after")
    def release_identity_matches(self) -> "FormalLogicRelease":
        payload = self.model_dump(mode="json", exclude={"release_id"})
        if self.release_id != stable_id("formal_logic_release", payload):
            raise ValueError("formal logic release ID does not match immutable evidence")
        return self


def build_formal_logic_release(
    program: LogicalProgram,
    asp: CompiledASP,
    prolog: CompiledProlog,
    *,
    source_version_hashes: dict[str, str],
    validators: tuple[ValidatorEvidence, ...],
    review_decisions: tuple[FormalReviewDecision, ...],
) -> FormalLogicRelease:
    """Build a release only when source, validation, review, and output closure holds."""
    if asp.program_id != program.program_id or prolog.program_id != program.program_id:
        raise ValueError("compiled programs must match the IR program identity")
    expected_asp_hash = "sha256:" + hashlib.sha256(asp.text.encode("utf-8")).hexdigest()
    expected_prolog_hash = "sha256:" + hashlib.sha256(prolog.text.encode("utf-8")).hexdigest()
    if asp.sha256 != expected_asp_hash or prolog.sha256 != expected_prolog_hash:
        raise ValueError("compiled program hash does not match generated text")
    required_sources = {
        reference.source_version
        for statement in program.statements
        for reference in statement.provenance
    }
    if set(source_version_hashes) != required_sources:
        raise ValueError("source version hashes do not exactly cover IR provenance")
    span_hashes: dict[str, str] = {}
    for statement in program.statements:
        for reference in statement.provenance:
            previous = span_hashes.setdefault(reference.span_id, reference.span_sha256)
            if previous != reference.span_sha256:
                raise ValueError(f"conflicting hashes for source span {reference.span_id}")
    ir_hash = program.sha256()
    if not validators or any(not evidence.passed for evidence in validators):
        raise ValueError("formal releases require passing validator evidence")
    if len({evidence.validator_id for evidence in validators}) != len(validators):
        raise ValueError("validator evidence IDs must be unique")
    if any(evidence.evaluated_ir_sha256 != ir_hash for evidence in validators):
        raise ValueError("validator evidence is stale for the current IR")
    approved_units = {
        unit_id
        for decision in review_decisions
        if decision.decision == "approved"
        for unit_id in decision.logical_unit_ids
    }
    statement_ids = {statement.statement_id for statement in program.statements}
    if approved_units != statement_ids:
        raise ValueError("approved reviews must exactly cover every logical unit")
    if len({decision.decision_id for decision in review_decisions}) != len(review_decisions):
        raise ValueError("review decision IDs must be unique")
    blocked_units = {
        unit_id
        for decision in review_decisions
        if decision.decision != "approved"
        for unit_id in decision.logical_unit_ids
    }
    if blocked_units & statement_ids:
        raise ValueError("rejected or held logical units cannot enter a formal release")
    payload = {
        "program_id": program.program_id,
        "source_version_hashes": dict(sorted(source_version_hashes.items())),
        "span_hashes": dict(sorted(span_hashes.items())),
        "ir_sha256": ir_hash,
        "compiler_hashes": {
            "asp": canonical_sha256(asp.compiler_version),
            "prolog": canonical_sha256(prolog.compiler_version),
        },
        "generated_program_hashes": {"asp": asp.sha256, "prolog": prolog.sha256},
        "validator_hashes": {
            evidence.validator_id: evidence.evidence_sha256 for evidence in validators
        },
        "review_decision_hashes": {
            decision.decision_id: decision.decision_sha256 for decision in review_decisions
        },
    }
    return FormalLogicRelease(
        release_id=stable_id("formal_logic_release", payload),
        **payload,
    )
