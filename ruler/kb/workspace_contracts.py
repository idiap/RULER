# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Contracts for named, versioned, multi-formalism knowledge bases."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from ruler.contracts.common import StrictContract, validate_sha256


class KBFormalism(StrEnum):
    ASP = "asp"
    PROLOG = "prolog"
    LOGICAL_IR = "logical_ir"
    TPTP = "tptp"
    LEAN4 = "lean4"
    SEMANTIC_IR = "semantic_ir"
    LEGAL_ARGUMENT = "legal_argument"
    TABULAR_FACTS = "tabular_facts"
    OPTIMIZATION_MODEL = "optimization_model"
    SOURCE_DOCUMENT = "source_document"
    STRUCTURED_DATA = "structured_data"


class KBPurpose(StrEnum):
    VERIFICATION = "verification"
    COMPLIANCE = "compliance"
    INFERENCE = "inference"
    OPTIMIZATION = "optimization"
    RECOMMENDATION = "recommendation"
    INTERPRETATION = "interpretation"
    EXPLORATION = "exploration"


class KBArtifactRole(StrEnum):
    SOURCE = "source"
    FACTS = "facts"
    RULES = "rules"
    AXIOMS = "axioms"
    CONSTRAINTS = "constraints"
    VOCABULARY = "vocabulary"
    QUERY = "query"
    MODEL = "model"
    EVIDENCE = "evidence"
    INTERPRETATION = "interpretation"
    TESTS = "tests"


class KBArtifactRef(StrictContract):
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    name: str = Field(min_length=1, max_length=160)
    role: KBArtifactRole
    formalism: KBFormalism
    media_type: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str
    language: str = "und"
    status: Literal["candidate", "reviewed", "approved", "active", "retired"] = "candidate"
    references: tuple[str, ...] = ()
    size_bytes: int = Field(ge=0)

    @model_validator(mode="after")
    def digest_and_path_are_safe(self) -> "KBArtifactRef":
        validate_sha256(self.sha256)
        if self.path.startswith(("/", "\\")) or "\\" in self.path or ".." in self.path.split("/"):
            raise ValueError("artifact path must be a contained repository-relative POSIX path")
        return self


class KBVersion(StrictContract):
    version_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    revision: int = Field(ge=1)
    status: Literal["draft", "candidate", "published", "retired"]
    parent_version_id: str | None = None
    artifacts: tuple[KBArtifactRef, ...]
    created_at: datetime
    content_sha256: str
    change_summary: str = Field(min_length=1)

    @model_validator(mode="after")
    def version_is_closed(self) -> "KBVersion":
        validate_sha256(self.content_sha256)
        ids = [item.artifact_id for item in self.artifacts]
        if len(ids) != len(set(ids)):
            raise ValueError("artifact IDs must be unique within a KB version")
        known = set(ids)
        for artifact in self.artifacts:
            unknown = set(artifact.references) - known
            if unknown:
                raise ValueError(
                    f"{artifact.artifact_id}: unknown artifact references: {sorted(unknown)}"
                )
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return self


class KnowledgeBase(StrictContract):
    kb_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    domain_id: str = Field(min_length=1)
    purposes: frozenset[KBPurpose] = Field(min_length=1)
    tags: frozenset[str] = frozenset()
    owner: str = "local"
    access_mode: Literal["read_only", "local_owner"]
    lifecycle: Literal["draft", "active", "archived"]
    current_version_id: str
    versions: tuple[KBVersion, ...] = Field(min_length=1)
    source_kind: Literal["managed", "corpus_adapter", "release_adapter"]

    @model_validator(mode="after")
    def versions_are_consistent(self) -> "KnowledgeBase":
        version_ids = [item.version_id for item in self.versions]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError("KB version IDs must be unique")
        if self.current_version_id not in version_ids:
            raise ValueError("current_version_id must refer to a declared version")
        revisions = sorted(item.revision for item in self.versions)
        if revisions != list(range(1, len(revisions) + 1)):
            raise ValueError("KB revisions must be contiguous starting at 1")
        if self.source_kind != "managed" and self.access_mode != "read_only":
            raise ValueError("adapted knowledge bases must be read-only")
        return self

    @property
    def current_version(self) -> KBVersion:
        return next(item for item in self.versions if item.version_id == self.current_version_id)

    @property
    def formalisms(self) -> frozenset[KBFormalism]:
        return frozenset(item.formalism for item in self.current_version.artifacts)


class KBSearchHit(StrictContract):
    kb_id: str
    kb_name: str
    artifact_id: str | None
    artifact_name: str | None
    role: KBArtifactRole | None
    formalism: KBFormalism | None
    score: int = Field(ge=1)
    snippet: str = Field(max_length=500)
    version_id: str


class KBInferenceRequest(StrictContract):
    request_id: str
    operation: Literal[
        "query",
        "verify",
        "evaluate",
        "counterfactual",
        "crosscheck",
        "consistency",
        "elaborate",
        "optimize",
        "recommend",
        "assess",
    ]
    version_id: str | None = None
    artifact_id: str | None = None
    query: str | None = None
    contrary: str | None = None
    asserted_facts: tuple[str, ...] = ()
    parameters: dict[str, Any] = Field(default_factory=dict)
    backend_id: str | None = None
    max_models: int = Field(default=100, ge=1, le=1000)


class KBInferenceResult(StrictContract):
    request_id: str
    kb_id: str
    version_id: str
    operation: str
    backend_id: str
    status: Literal["completed", "blocked", "unsupported", "error"]
    conclusion: Literal["supported", "refuted", "conflict", "underdetermined", "not_applicable"]
    summary: str
    target_support: Literal["proved", "not_proved", "unknown"] = "unknown"
    contrary_support: Literal["proved", "not_proved", "unknown"] = "unknown"
    complete: bool = False
    model_count: int | None = Field(default=None, ge=0)
    evidence: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    result: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    claim_boundary: str = Field(min_length=1)


class CreateKnowledgeBaseRequest(StrictContract):
    kb_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=1000)
    domain_id: str
    purposes: frozenset[KBPurpose]
    tags: frozenset[str] = frozenset()


class AddKBArtifactRequest(StrictContract):
    artifact_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    name: str = Field(min_length=1, max_length=160)
    role: KBArtifactRole
    formalism: KBFormalism
    media_type: str
    filename: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
    content: str = Field(max_length=1_000_000)
    language: str = "und"
    references: tuple[str, ...] = ()
    change_summary: str = Field(min_length=1, max_length=500)


def utc_now() -> datetime:
    return datetime.now(UTC)
