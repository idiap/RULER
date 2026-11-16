# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Shared primitives for neutral v2 contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class StrictContract(BaseModel):
    """Immutable base that makes schema evolution explicit."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_REVIEW = "needs_review"


class NormativeModality(StrEnum):
    DEFINITION = "definition"
    APPLICABILITY = "applicability"
    OBLIGATION = "obligation"
    PERMISSION = "permission"
    PROHIBITION = "prohibition"
    EXCEPTION = "exception"
    PRECEDENCE = "precedence"
    CONSTRAINT = "constraint"
    LIMIT = "limit"
    TEMPORAL_RULE = "temporal_rule"
    PROCEDURAL_REQUIREMENT = "procedural_requirement"
    UNKNOWN = "unknown"
    NON_FORMALIZABLE = "non_formalizable"


class EvaluationStatus(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    SATISFIED = "satisfied"
    VIOLATED = "violated"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


def validate_sha256(value: str) -> str:
    digest = value.removeprefix("sha256:")
    if not value.startswith("sha256:") or len(digest) != 64:
        raise ValueError("hash must use sha256:<64 lowercase hex> form")
    if any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("hash must use lowercase hexadecimal")
    return value


class TypedValue(StrictContract):
    """Portable typed value; domain packs own additional type identifiers."""

    value_type: str
    value: Any
    unit: str | None = None

    @field_validator("value_type")
    @classmethod
    def type_is_named(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value_type must not be blank")
        return value
