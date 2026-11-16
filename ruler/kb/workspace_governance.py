# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Governance primitives for multi-user, release-oriented knowledge bases.

This module is deliberately independent of the filesystem catalogue.  Callers can
put these checks around CLI, HTTP, or batch mutations without weakening the existing
content/digest validation boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Iterator, TypeVar

from pydantic import Field, field_validator, model_validator

from ruler.contracts.common import StrictContract, validate_sha256
from ruler.kb.workspace_contracts import (
    KBArtifactRef,
    KBArtifactRole,
    KBSearchHit,
    KBVersion,
    KnowledgeBase,
)


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ReleaseStage(StrEnum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    PUBLISHED = "published"
    RETIRED = "retired"


class EvidenceKind(StrEnum):
    VALIDATION = "validation"
    REVIEW = "review"
    PUBLICATION_APPROVAL = "publication_approval"
    RETIREMENT_APPROVAL = "retirement_approval"


class ReleaseEvidence(StrictContract):
    evidence_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    kind: EvidenceKind
    subject_sha256: str
    actor_id: str = Field(min_length=1, max_length=200)
    successful: bool
    recorded_at: datetime
    details: str = Field(min_length=1, max_length=2000)

    @field_validator("subject_sha256")
    @classmethod
    def valid_digest(cls, value: str) -> str:
        return validate_sha256(value)

    @field_validator("recorded_at")
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")
        return value


class ReleaseEnvelope(StrictContract):
    """Immutable release state for one content-addressed KB version."""

    release_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    kb_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    version_id: str
    content_sha256: str
    stage: ReleaseStage
    evidence: tuple[ReleaseEvidence, ...] = ()
    created_at: datetime
    supersedes_release_id: str | None = None

    @model_validator(mode="after")
    def validate_envelope(self) -> "ReleaseEnvelope":
        validate_sha256(self.content_sha256)
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        ids = [item.evidence_id for item in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("release evidence IDs must be unique")
        if any(item.subject_sha256 != self.content_sha256 for item in self.evidence):
            raise ValueError("release evidence must be bound to the release content digest")
        required = {
            ReleaseStage.CANDIDATE: {EvidenceKind.VALIDATION},
            ReleaseStage.REVIEWED: {EvidenceKind.VALIDATION, EvidenceKind.REVIEW},
            ReleaseStage.PUBLISHED: {
                EvidenceKind.VALIDATION,
                EvidenceKind.REVIEW,
                EvidenceKind.PUBLICATION_APPROVAL,
            },
            ReleaseStage.RETIRED: {
                EvidenceKind.VALIDATION,
                EvidenceKind.REVIEW,
                EvidenceKind.PUBLICATION_APPROVAL,
                EvidenceKind.RETIREMENT_APPROVAL,
            },
        }.get(self.stage, set())
        successful = {item.kind for item in self.evidence if item.successful}
        if missing := required - successful:
            raise ValueError(
                f"release stage {self.stage} lacks successful evidence: {sorted(missing)}"
            )
        return self

    @property
    def etag(self) -> str:
        return '"' + _canonical_digest(self.model_dump(mode="json")).removeprefix("sha256:") + '"'


class ReleaseLifecycle:
    """Pure lifecycle transitions; persistence is owned by the application."""

    _next = {
        ReleaseStage.DRAFT: ReleaseStage.CANDIDATE,
        ReleaseStage.CANDIDATE: ReleaseStage.REVIEWED,
        ReleaseStage.REVIEWED: ReleaseStage.PUBLISHED,
        ReleaseStage.PUBLISHED: ReleaseStage.RETIRED,
    }

    @staticmethod
    def draft(kb: KnowledgeBase, version: KBVersion | None = None) -> ReleaseEnvelope:
        selected = version or kb.current_version
        if selected not in kb.versions:
            raise ValueError("version does not belong to knowledge base")
        return ReleaseEnvelope(
            release_id=f"{selected.version_id}.draft",
            kb_id=kb.kb_id,
            version_id=selected.version_id,
            content_sha256=selected.content_sha256,
            stage=ReleaseStage.DRAFT,
            created_at=datetime.now(UTC),
        )

    @classmethod
    def transition(
        cls,
        envelope: ReleaseEnvelope,
        target: ReleaseStage,
        *,
        evidence: Sequence[ReleaseEvidence],
        release_id: str | None = None,
    ) -> ReleaseEnvelope:
        if cls._next.get(envelope.stage) != target:
            raise ValueError(f"invalid release transition: {envelope.stage} -> {target}")
        combined = (*envelope.evidence, *evidence)
        return ReleaseEnvelope(
            release_id=release_id or f"{envelope.version_id}.{target}",
            kb_id=envelope.kb_id,
            version_id=envelope.version_id,
            content_sha256=envelope.content_sha256,
            stage=target,
            evidence=combined,
            created_at=datetime.now(UTC),
            supersedes_release_id=envelope.release_id,
        )

    @staticmethod
    def execution_release(
        releases: Sequence[ReleaseEnvelope], *, allow_preview: bool = False
    ) -> ReleaseEnvelope:
        eligible = [item for item in releases if item.stage == ReleaseStage.PUBLISHED]
        if eligible:
            return eligible[-1]
        if allow_preview:
            previews = [item for item in releases if item.stage != ReleaseStage.RETIRED]
            if previews:
                return previews[-1]
        raise LookupError("no published release is available for ordinary execution")


class ReleaseRepository:
    """Immutable filesystem repository for content-bound release envelopes."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def put(self, envelope: ReleaseEnvelope) -> Path:
        target = (self.root / envelope.kb_id / f"{envelope.release_id}.json").resolve()
        _require_within(target, self.root)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(envelope.model_dump(mode="json"), indent=2, sort_keys=True).encode("utf-8")
            + b"\n"
        )
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            existing = ReleaseEnvelope.model_validate(
                json.loads(target.read_text(encoding="utf-8"))
            )
            if existing != envelope:
                raise ValueError(f"release envelope is immutable: {envelope.release_id}") from None
            return target
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return target

    def list(self, kb_id: str) -> tuple[ReleaseEnvelope, ...]:
        directory = (self.root / kb_id).resolve()
        _require_within(directory, self.root)
        if not directory.exists():
            return ()
        values = [
            ReleaseEnvelope.model_validate(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(directory.glob("*.json"))
        ]
        return tuple(sorted(values, key=lambda item: item.created_at))

    def execution_release(self, kb_id: str, *, allow_preview: bool = False) -> ReleaseEnvelope:
        return ReleaseLifecycle.execution_release(self.list(kb_id), allow_preview=allow_preview)


class ExecutionBoundary(StrictContract):
    release_id: str
    preview: bool
    fit_for_reliance: bool
    warning: str | None = None


def execution_boundary(release: ReleaseEnvelope) -> ExecutionBoundary:
    if release.stage == ReleaseStage.PUBLISHED:
        return ExecutionBoundary(
            release_id=release.release_id, preview=False, fit_for_reliance=True
        )
    return ExecutionBoundary(
        release_id=release.release_id,
        preview=True,
        fit_for_reliance=False,
        warning=f"NON-RELIANCE PREVIEW: release is {release.stage}, not published",
    )


class KBRole(StrEnum):
    READER = "reader"
    REASONER = "reasoner"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    PUBLISHER = "publisher"
    ADMINISTRATOR = "administrator"


class KBPermission(StrEnum):
    READ_METADATA = "read_metadata"
    READ_SOURCE = "read_source"
    SEARCH = "search"
    QUERY = "query"
    EXECUTE = "execute"
    EDIT = "edit"
    REVIEW = "review"
    PUBLISH = "publish"
    ADMINISTER = "administer"


_ROLE_PERMISSIONS: dict[KBRole, frozenset[KBPermission]] = {
    KBRole.READER: frozenset({KBPermission.READ_METADATA, KBPermission.SEARCH}),
    KBRole.REASONER: frozenset(
        {KBPermission.READ_METADATA, KBPermission.SEARCH, KBPermission.QUERY, KBPermission.EXECUTE}
    ),
    KBRole.EDITOR: frozenset(
        {
            KBPermission.READ_METADATA,
            KBPermission.READ_SOURCE,
            KBPermission.SEARCH,
            KBPermission.EDIT,
        }
    ),
    KBRole.REVIEWER: frozenset(
        {
            KBPermission.READ_METADATA,
            KBPermission.READ_SOURCE,
            KBPermission.SEARCH,
            KBPermission.QUERY,
            KBPermission.EXECUTE,
            KBPermission.REVIEW,
        }
    ),
    KBRole.PUBLISHER: frozenset(
        {
            KBPermission.READ_METADATA,
            KBPermission.READ_SOURCE,
            KBPermission.SEARCH,
            KBPermission.QUERY,
            KBPermission.EXECUTE,
            KBPermission.PUBLISH,
        }
    ),
    KBRole.ADMINISTRATOR: frozenset(KBPermission),
}


class AccessGrant(StrictContract):
    principal_id: str = Field(min_length=1)
    kb_id: str
    roles: frozenset[KBRole] = Field(min_length=1)


class AccessPolicy:
    """Deny-by-default, per-KB authorization with field-level source redaction."""

    def __init__(self, grants: Sequence[AccessGrant] = ()) -> None:
        self._grants = tuple(grants)

    def permissions(self, principal_id: str, kb_id: str) -> frozenset[KBPermission]:
        roles = {
            role
            for grant in self._grants
            if grant.principal_id == principal_id and grant.kb_id == kb_id
            for role in grant.roles
        }
        return frozenset(permission for role in roles for permission in _ROLE_PERMISSIONS[role])

    def allows(self, principal_id: str, kb_id: str, permission: KBPermission) -> bool:
        return permission in self.permissions(principal_id, kb_id)

    def require(self, principal_id: str, kb_id: str, permission: KBPermission) -> None:
        if not self.allows(principal_id, kb_id, permission):
            # Deliberately indistinguishable from an absent KB to prevent enumeration.
            raise LookupError("knowledge base is unavailable")

    def visible_kbs(
        self, principal_id: str, kbs: Sequence[KnowledgeBase]
    ) -> tuple[KnowledgeBase, ...]:
        return tuple(
            kb for kb in kbs if self.allows(principal_id, kb.kb_id, KBPermission.READ_METADATA)
        )

    def artifact_view(
        self, principal_id: str, kb_id: str, artifact: KBArtifactRef
    ) -> dict[str, Any]:
        self.require(principal_id, kb_id, KBPermission.READ_METADATA)
        value = artifact.model_dump(mode="json")
        if not self.allows(principal_id, kb_id, KBPermission.READ_SOURCE):
            value["path"] = None
            value["sha256"] = None
            value["size_bytes"] = None
            value["source_redacted"] = True
        else:
            value["source_redacted"] = False
        return value

    def search_hit_view(
        self,
        principal_id: str,
        hit: KBSearchHit,
        *,
        artifact: KBArtifactRef | None = None,
    ) -> dict[str, Any]:
        """Preserve searchable derived metadata while hiding exact source snippets."""

        self.require(principal_id, hit.kb_id, KBPermission.SEARCH)
        value = hit.model_dump(mode="json")
        if (
            artifact is not None
            and artifact.role == KBArtifactRole.SOURCE
            and not self.allows(principal_id, hit.kb_id, KBPermission.READ_SOURCE)
        ):
            value["snippet"] = "Source content is restricted."
            value["source_redacted"] = True
        else:
            value["source_redacted"] = False
        return value


class KBDependency(StrictContract):
    dependency_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    source_kb_id: str
    source_release_id: str
    source_release_sha256: str
    artifact_id: str
    artifact_sha256: str

    @field_validator("source_release_sha256", "artifact_sha256")
    @classmethod
    def digest_valid(cls, value: str) -> str:
        return validate_sha256(value)


class DependencyStatus(StrictContract):
    dependency_id: str
    valid: bool
    blockers: tuple[str, ...] = ()


def validate_dependency(
    dependency: KBDependency,
    *,
    releases: Mapping[str, ReleaseEnvelope],
    artifacts: Mapping[tuple[str, str], KBArtifactRef],
) -> DependencyStatus:
    blockers: list[str] = []
    release = releases.get(dependency.source_release_id)
    if release is None or release.kb_id != dependency.source_kb_id:
        blockers.append("source release is unavailable")
    else:
        if release.content_sha256 != dependency.source_release_sha256:
            blockers.append("source release digest mismatch")
        if release.stage == ReleaseStage.RETIRED:
            blockers.append("source release is retired")
    artifact = artifacts.get((dependency.source_release_id, dependency.artifact_id))
    if artifact is None:
        blockers.append("source artifact is unavailable")
    elif artifact.sha256 != dependency.artifact_sha256:
        blockers.append("source artifact digest mismatch")
    return DependencyStatus(
        dependency_id=dependency.dependency_id, valid=not blockers, blockers=tuple(blockers)
    )


def kb_etag(kb: KnowledgeBase) -> str:
    digest = _canonical_digest(kb.model_dump(mode="json")).removeprefix("sha256:")
    return f'"{digest}"'


class AuditEvent(StrictContract):
    event_id: str
    kb_id: str
    actor_id: str
    action: str
    idempotency_key: str
    request_sha256: str
    before_etag: str
    after_etag: str
    occurred_at: datetime


T = TypeVar("T")


class MutationResult(StrictContract):
    value: Any
    etag: str
    replayed: bool
    audit_event: AuditEvent


class MutationCoordinator:
    """Per-KB serialization, optimistic concurrency, replay, and append-only audit."""

    def __init__(self, audit_path: Path) -> None:
        self.audit_path = audit_path
        self._guard = threading.Lock()
        self._locks: dict[str, threading.RLock] = {}
        self._replays: dict[tuple[str, str], MutationResult] = {}

    @contextmanager
    def lock(self, kb_id: str) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(kb_id, threading.RLock())
        with lock:
            yield

    def execute(
        self,
        *,
        kb_id: str,
        actor_id: str,
        action: str,
        idempotency_key: str,
        request: Any,
        if_match: str,
        load: Callable[[], KnowledgeBase],
        mutate: Callable[[KnowledgeBase], KnowledgeBase],
    ) -> MutationResult:
        if not idempotency_key.strip() or len(idempotency_key) > 200:
            raise ValueError("a bounded non-empty idempotency key is required")
        request_digest = _canonical_digest(request)
        replay_key = (kb_id, idempotency_key)
        with self.lock(kb_id):
            if previous := self._replays.get(replay_key):
                if previous.audit_event.request_sha256 != request_digest:
                    raise ValueError("idempotency key was already used for a different request")
                return previous.model_copy(update={"replayed": True})
            current = load()
            before = kb_etag(current)
            if if_match != before:
                raise RuntimeError("precondition failed: stale If-Match ETag")
            updated = mutate(current)
            if updated.kb_id != kb_id:
                raise ValueError("mutation changed the knowledge-base identity")
            after = kb_etag(updated)
            now = datetime.now(UTC)
            event = AuditEvent(
                event_id=_canonical_digest(
                    {
                        "kb": kb_id,
                        "key": idempotency_key,
                        "request": request_digest,
                        "at": now.isoformat(),
                    }
                ),
                kb_id=kb_id,
                actor_id=actor_id,
                action=action,
                idempotency_key=idempotency_key,
                request_sha256=request_digest,
                before_etag=before,
                after_etag=after,
                occurred_at=now,
            )
            result = MutationResult(
                value=updated.model_dump(mode="json"), etag=after, replayed=False, audit_event=event
            )
            self._append_audit(event)
            self._replays[replay_key] = result
            return result

    def _append_audit(self, event: AuditEvent) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.audit_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())


class QuotaLimits(StrictContract):
    max_kbs: int = Field(default=100, ge=1)
    max_revisions_per_kb: int = Field(default=1000, ge=1)
    max_artifacts_per_release: int = Field(default=5000, ge=1)
    max_search_indexes: int = Field(default=100, ge=0)
    max_concurrent_inference: int = Field(default=4, ge=1)
    max_solver_seconds: int = Field(default=60, ge=1)
    max_ground_atoms: int = Field(default=1_000_000, ge=1)
    max_retained_runs: int = Field(default=10_000, ge=0)


class QuotaUsage(StrictContract):
    kbs: int = Field(ge=0)
    revisions: int = Field(ge=0)
    artifacts: int = Field(ge=0)
    search_indexes: int = Field(ge=0)
    concurrent_inference: int = Field(ge=0)
    solver_seconds: int = Field(ge=0)
    ground_atoms: int = Field(ge=0)
    retained_runs: int = Field(ge=0)


class QuotaDecision(StrictContract):
    allowed: bool
    blockers: tuple[str, ...] = ()


class QuotaPolicy:
    def __init__(self, limits: QuotaLimits) -> None:
        self.limits = limits

    def check(self, usage: QuotaUsage) -> QuotaDecision:
        pairs = {
            "knowledge bases": (usage.kbs, self.limits.max_kbs),
            "revisions per KB": (usage.revisions, self.limits.max_revisions_per_kb),
            "artifacts per release": (usage.artifacts, self.limits.max_artifacts_per_release),
            "search indexes": (usage.search_indexes, self.limits.max_search_indexes),
            "concurrent inference": (
                usage.concurrent_inference,
                self.limits.max_concurrent_inference,
            ),
            "solver seconds": (usage.solver_seconds, self.limits.max_solver_seconds),
            "ground atoms": (usage.ground_atoms, self.limits.max_ground_atoms),
            "retained runs": (usage.retained_runs, self.limits.max_retained_runs),
        }
        blockers = tuple(
            f"{name} quota exceeded ({actual}>{limit})"
            for name, (actual, limit) in pairs.items()
            if actual > limit
        )
        return QuotaDecision(allowed=not blockers, blockers=blockers)

    def require(self, usage: QuotaUsage) -> None:
        decision = self.check(usage)
        if not decision.allowed:
            raise RuntimeError("; ".join(decision.blockers))


class InferenceQuota:
    """Thread-safe concurrent-inference admission control for one quota scope."""

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("concurrent inference limit must be positive")
        self.limit = limit
        self._active = 0
        self._lock = threading.Lock()

    @property
    def active(self) -> int:
        with self._lock:
            return self._active

    @contextmanager
    def reserve(self) -> Iterator[None]:
        with self._lock:
            if self._active >= self.limit:
                raise RuntimeError("concurrent inference quota exceeded")
            self._active += 1
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1


def atomic_json_write(path: Path, value: Any) -> None:
    """Small persistence helper for envelopes and dependency registries."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _require_within(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("governance path escapes configured root") from exc
