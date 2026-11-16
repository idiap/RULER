# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic fetch, retry, checkpoint, freshness, and invalidation controls."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.error import HTTPError, URLError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.ingestion.contracts import canonical_sha256, stable_id


class FailureCategory(StrEnum):
    TRANSIENT_NETWORK = "transient_network"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"
    ROBOTS_OR_TERMS = "robots_or_terms"
    TOO_LARGE = "too_large"
    UNSUPPORTED_CONTENT = "unsupported_content"
    MALFORMED_CONTENT = "malformed_content"
    ENCRYPTED = "encrypted"
    PASSWORD_PROTECTED = "password_protected"
    INTERNAL = "internal"


class FetchFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category: FailureCategory
    code: str
    message: str
    transient: bool
    retry_after_seconds: float | None = Field(default=None, ge=0)


class ConditionalRequestMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    etag: str | None = None
    last_modified: str | None = None
    prior_raw_sha256: str | None = None

    def headers(self) -> dict[str, str]:
        """Build conditional HTTP headers for a freshness-aware refetch."""
        headers: dict[str, str] = {}
        if self.etag:
            headers["If-None-Match"] = self.etag
        if self.last_modified:
            headers["If-Modified-Since"] = self.last_modified
        return headers


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    maximum_attempts: int = Field(default=3, ge=1, le=10)
    initial_backoff_seconds: float = Field(default=1.0, ge=0)
    maximum_backoff_seconds: float = Field(default=30.0, ge=0)
    jitter_fraction: float = Field(default=0.2, ge=0, le=1)

    def delay(self, attempt: int, seed: str) -> float:
        """Return deterministic exponential backoff with bounded seeded jitter."""
        base = min(
            self.maximum_backoff_seconds,
            self.initial_backoff_seconds * (2 ** max(0, attempt - 1)),
        )
        digest = int(canonical_sha256({"seed": seed, "attempt": attempt})[-8:], 16)
        centered = (digest / 0xFFFFFFFF) * 2 - 1
        return max(0.0, base * (1 + centered * self.jitter_fraction))


class FetchCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    checkpoint_id: str
    source_task_id: str
    attempt: int = Field(ge=1)
    state: Literal["pending", "fetched", "not_modified", "failed", "quarantined"]
    updated_at: datetime
    source_version_id: str | None = None
    raw_sha256: str | None = None
    failure: FetchFailure | None = None

    @model_validator(mode="after")
    def state_evidence(self) -> "FetchCheckpoint":
        """Require hashes for fetched states and typed failures for blocked states."""
        if self.state == "fetched" and not all((self.source_version_id, self.raw_sha256)):
            raise ValueError("fetched checkpoints require source version and content hash")
        if self.state in {"failed", "quarantined"} and self.failure is None:
            raise ValueError("failed checkpoints require classified failure evidence")
        return self


class DependencyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_artifact_id: str
    dependent_artifact_id: str
    dependency_kind: Literal[
        "extraction",
        "span",
        "translation",
        "formalization",
        "approval",
        "release",
        "recommendation",
    ]


class InvalidationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invalidation_id: str
    changed_source_version_id: str
    replacement_source_version_id: str | None = None
    invalidated_artifact_ids: tuple[str, ...]
    reason: Literal["content_changed", "withdrawn", "superseded", "stale"]
    created_at: datetime


def classify_fetch_failure(error: Exception) -> FetchFailure:
    """Map transport errors to stable retry semantics."""
    if isinstance(error, HTTPError):
        if error.code == 429:
            return FetchFailure(
                category=FailureCategory.RATE_LIMITED,
                code="http_429",
                message=str(error),
                transient=True,
                retry_after_seconds=_retry_after(error.headers.get("Retry-After")),
            )
        if 500 <= error.code <= 599:
            return FetchFailure(
                category=FailureCategory.SERVER_ERROR,
                code=f"http_{error.code}",
                message=str(error),
                transient=True,
            )
        category = (
            FailureCategory.NOT_FOUND if error.code in {404, 410} else FailureCategory.ACCESS_DENIED
        )
        return FetchFailure(
            category=category, code=f"http_{error.code}", message=str(error), transient=False
        )
    if isinstance(error, (URLError, TimeoutError, ConnectionError)):
        return FetchFailure(
            category=FailureCategory.TRANSIENT_NETWORK,
            code=type(error).__name__.lower(),
            message=str(error),
            transient=True,
        )
    return FetchFailure(
        category=FailureCategory.INTERNAL,
        code=type(error).__name__,
        message=str(error),
        transient=False,
    )


def retry_call(
    operation: Callable[[], Any],
    policy: RetryPolicy,
    *,
    seed: str,
    sleep: Callable[[float], None],
) -> tuple[Any, int]:
    """Retry only classified transient failures and return value plus attempt count."""
    for attempt in range(1, policy.maximum_attempts + 1):
        try:
            return operation(), attempt
        except Exception as error:
            failure = classify_fetch_failure(error)
            if not failure.transient or attempt == policy.maximum_attempts:
                raise
            sleep(failure.retry_after_seconds or policy.delay(attempt, seed))
    raise AssertionError("unreachable")


def write_fetch_checkpoint(path: Path, checkpoint: FetchCheckpoint) -> bool:
    """Append a state record; an identical latest checkpoint is a no-op."""
    path.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if path.exists():
        history = json.loads(path.read_text(encoding="utf-8"))
        if history and history[-1] == checkpoint.model_dump(mode="json"):
            return False
    history.append(checkpoint.model_dump(mode="json"))
    path.write_text(json.dumps(history, sort_keys=True) + "\n", encoding="utf-8")
    return True


def invalidation_closure(
    changed_source_version_id: str,
    edges: tuple[DependencyEdge, ...],
    *,
    replacement_source_version_id: str | None = None,
    reason: Literal["content_changed", "withdrawn", "superseded", "stale"] = "content_changed",
    created_at: datetime | None = None,
) -> InvalidationRecord:
    """Invalidate exactly the transitive downstream dependency closure."""
    invalidated: set[str] = set()
    frontier = [changed_source_version_id]
    while frontier:
        source = frontier.pop()
        for edge in edges:
            if edge.source_artifact_id == source and edge.dependent_artifact_id not in invalidated:
                invalidated.add(edge.dependent_artifact_id)
                frontier.append(edge.dependent_artifact_id)
    payload = {
        "changed_source_version_id": changed_source_version_id,
        "replacement_source_version_id": replacement_source_version_id,
        "invalidated_artifact_ids": tuple(sorted(invalidated)),
        "reason": reason,
    }
    return InvalidationRecord(
        invalidation_id=stable_id("invalidation", payload),
        **payload,
        created_at=created_at or datetime.now(UTC),
    )


def is_stale(retrieved_at: datetime, maximum_age: timedelta, now: datetime) -> bool:
    """Return whether a source version has exceeded its configured freshness window."""
    return now - retrieved_at > maximum_age


def _retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
