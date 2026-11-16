# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Digest-locked realistic cases for generative autoformalization tests.

The producer-facing payload is constructed here rather than by test code so hidden
oracles cannot accidentally become prompt material.  The corpus is provider-neutral;
live model runners may consume :func:`build_producer_input`, while deterministic
tests can validate the same immutable sources and independent expectations.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ruler.io import read_yaml
from ruler.paths import REPO_ROOT

AUTOFORMALIZATION_CASES_FILE = REPO_ROOT / "tests" / "fixtures" / "autoformalization" / "cases.yaml"
SHA256_PREFIX = "sha256:"


def _sha256(path: Path) -> str:
    return SHA256_PREFIX + hashlib.sha256(path.read_bytes()).hexdigest()


class SourceFixture(BaseModel):
    """One immutable source visible to a generative producer."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    document_kind: str = Field(min_length=1)
    authority_status: str = Field(min_length=1)
    anchors: tuple[str, ...] = Field(min_length=1)


class OracleFixture(BaseModel):
    """Evaluator-only expectations that must never enter the producer prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class AutoformalizationCase(BaseModel):
    """One source style and the deterministic capabilities it must exercise."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    domain_id: str = Field(min_length=1)
    source_language: str = Field(min_length=2)
    target_language: str = Field(min_length=2)
    source_style: str = Field(min_length=1)
    task: str = Field(min_length=1)
    allowed_predicates: tuple[str, ...] = Field(min_length=1)
    sources: tuple[SourceFixture, ...] = Field(min_length=1)
    oracle: OracleFixture
    required_backends: tuple[Literal["asp", "prolog", "tptp", "lean4", "exhaustive_reference"], ...]
    required_behavioral_perspectives: tuple[
        Literal["positive", "negative", "counterfactual", "exception", "boundary", "conflict"],
        ...,
    ]

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> "AutoformalizationCase":
        source_ids = [item.source_id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source identifiers must be unique within a case")
        if len(self.allowed_predicates) != len(set(self.allowed_predicates)):
            raise ValueError("allowed predicates must be unique")
        if len(self.required_backends) != len(set(self.required_backends)):
            raise ValueError("required backends must be unique")
        return self


class ProducerInputPolicy(BaseModel):
    """Explicit allowlist preventing hidden-label leakage into model input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    include_fields: tuple[str, ...] = Field(min_length=1)
    exclude_fields: tuple[str, ...] = Field(min_length=1)
    oracle_visibility: Literal["evaluator_only"]


class AutoformalizationCaseCatalogue(BaseModel):
    """Versioned collection of realistic autoformalization cases."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str
    version: int = Field(ge=1)
    producer_input_policy: ProducerInputPolicy
    cases: tuple[AutoformalizationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> "AutoformalizationCaseCatalogue":
        identifiers = [item.case_id for item in self.cases]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("autoformalization case identifiers must be unique")
        required_public_fields = {
            "case_id",
            "domain_id",
            "source_language",
            "target_language",
            "source_style",
            "task",
            "allowed_predicates",
            "sources",
        }
        if set(self.producer_input_policy.include_fields) != required_public_fields:
            raise ValueError("producer input allowlist does not match the safe public fields")
        if "oracle" not in self.producer_input_policy.exclude_fields:
            raise ValueError("producer input policy must explicitly exclude the oracle")
        return self


class AutoformalizationOracle(BaseModel):
    """Independent semantic and behavioral evaluator contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    expected_disposition: Literal[
        "candidate_review_required", "blocked_ambiguity", "non_formalizable"
    ]
    semantic_invariants: tuple[str, ...] = Field(min_length=1)
    required_mutations: tuple[
        Literal[
            "actor",
            "modality",
            "polarity",
            "connective",
            "exception",
            "quantity",
            "temporal",
            "coreference",
            "precedence",
            "source_link",
        ],
        ...,
    ] = Field(min_length=1)
    behavioral_cases: tuple[dict[str, str], ...] = Field(min_length=1)
    forbidden_claims: tuple[str, ...] = Field(min_length=1)

    @field_validator("behavioral_cases")
    @classmethod
    def behavioral_cases_are_named(cls, values: tuple[dict[str, str], ...]):
        if any(set(item) != {"id", "expected"} or not all(item.values()) for item in values):
            raise ValueError("behavioral cases require only non-empty id and expected fields")
        identifiers = [item["id"] for item in values]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("behavioral case identifiers must be unique")
        return values


def _resolve_fixture(path: str, root: Path) -> Path:
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"fixture path escapes repository root: {path}") from exc
    if not resolved.is_file():
        raise ValueError(f"fixture is missing: {path}")
    return resolved


def load_autoformalization_case_catalogue(
    path: Path = AUTOFORMALIZATION_CASES_FILE,
    *,
    root: Path = REPO_ROOT,
) -> AutoformalizationCaseCatalogue:
    """Load the catalogue and authenticate every public source and hidden oracle."""

    catalogue = AutoformalizationCaseCatalogue.model_validate(read_yaml(path))
    source_paths: set[Path] = set()
    oracle_paths: set[Path] = set()
    for case in catalogue.cases:
        for source in case.sources:
            source_path = _resolve_fixture(source.path, root)
            if _sha256(source_path) != source.sha256:
                raise ValueError(f"{case.case_id}: source digest mismatch: {source.path}")
            source_paths.add(source_path)
        oracle_path = _resolve_fixture(case.oracle.path, root)
        if _sha256(oracle_path) != case.oracle.sha256:
            raise ValueError(f"{case.case_id}: oracle digest mismatch: {case.oracle.path}")
        oracle = AutoformalizationOracle.model_validate(read_yaml(oracle_path))
        if oracle.case_id != case.case_id:
            raise ValueError(f"{case.case_id}: oracle case identifier mismatch")
        oracle_paths.add(oracle_path)
    if overlap := source_paths & oracle_paths:
        raise ValueError(f"producer sources and evaluator oracles overlap: {sorted(overlap)}")
    return catalogue


def load_autoformalization_oracle(
    case: AutoformalizationCase,
    *,
    root: Path = REPO_ROOT,
) -> AutoformalizationOracle:
    """Load one evaluator-only oracle after authenticating its bytes."""

    path = _resolve_fixture(case.oracle.path, root)
    if _sha256(path) != case.oracle.sha256:
        raise ValueError(f"{case.case_id}: oracle digest mismatch: {case.oracle.path}")
    oracle = AutoformalizationOracle.model_validate(read_yaml(path))
    if oracle.case_id != case.case_id:
        raise ValueError(f"{case.case_id}: oracle case identifier mismatch")
    return oracle


def build_producer_input(
    case: AutoformalizationCase,
    *,
    root: Path = REPO_ROOT,
) -> dict[str, object]:
    """Build an exact-source producer payload containing no oracle material."""

    sources: list[dict[str, object]] = []
    for source in case.sources:
        path = _resolve_fixture(source.path, root)
        if _sha256(path) != source.sha256:
            raise ValueError(f"{case.case_id}: source digest mismatch: {source.path}")
        sources.append(
            {
                "source_id": source.source_id,
                "sha256": source.sha256,
                "document_kind": source.document_kind,
                "authority_status": source.authority_status,
                "anchors": list(source.anchors),
                "content": path.read_text(encoding="utf-8"),
            }
        )
    return {
        "case_id": case.case_id,
        "domain_id": case.domain_id,
        "source_language": case.source_language,
        "target_language": case.target_language,
        "source_style": case.source_style,
        "task": case.task,
        "allowed_predicates": list(case.allowed_predicates),
        "sources": sources,
    }


@dataclass(frozen=True)
class StagedProducerInput:
    """A producer-visible directory containing only authenticated public material."""

    root: Path
    payload_path: Path


@contextmanager
def stage_producer_input(
    case: AutoformalizationCase,
    *,
    root: Path = REPO_ROOT,
    parent: Path | None = None,
) -> Iterator[StagedProducerInput]:
    """Materialize the allowlisted payload behind an OS-enforced read-only boundary.

    The stage deliberately does not accept or load an oracle.  Callers give a model
    this directory as its complete filesystem view; cleanup restores owner write bits
    only after the producer has exited.
    """

    payload = build_producer_input(case, root=root)
    with tempfile.TemporaryDirectory(
        prefix=f"ruler-producer-{case.case_id}-", dir=parent
    ) as directory:
        stage_root = Path(directory)
        payload_path = stage_root / "producer_input.json"
        payload_path.write_text(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.chmod(payload_path, 0o444)
        os.chmod(stage_root, 0o555)
        try:
            yield StagedProducerInput(root=stage_root, payload_path=payload_path)
        finally:
            os.chmod(stage_root, 0o755)
            os.chmod(payload_path, 0o644)


__all__ = [
    "AUTOFORMALIZATION_CASES_FILE",
    "AutoformalizationCase",
    "AutoformalizationCaseCatalogue",
    "AutoformalizationOracle",
    "StagedProducerInput",
    "build_producer_input",
    "load_autoformalization_case_catalogue",
    "load_autoformalization_oracle",
    "stage_producer_input",
]
