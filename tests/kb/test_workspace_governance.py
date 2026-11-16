# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ruler.kb.workspace_contracts import (
    KBArtifactRef,
    KBArtifactRole,
    KBFormalism,
    KBPurpose,
    KBVersion,
    KnowledgeBase,
)
from ruler.kb.workspace_governance import (
    AccessGrant,
    AccessPolicy,
    EvidenceKind,
    KBDependency,
    KBPermission,
    KBRole,
    MutationCoordinator,
    QuotaLimits,
    QuotaPolicy,
    QuotaUsage,
    ReleaseEvidence,
    ReleaseLifecycle,
    ReleaseStage,
    execution_boundary,
    kb_etag,
    validate_dependency,
)
from ruler.kb.workspace_packages import export_package, import_package, inspect_package


def _artifact(payload: bytes = b"eligible(x).\n") -> KBArtifactRef:
    return KBArtifactRef(
        artifact_id="rules",
        name="Rules",
        role=KBArtifactRole.RULES,
        formalism=KBFormalism.ASP,
        media_type="text/x-asp",
        path="kb/rules.lp",
        sha256="sha256:" + hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
    )


def _kb(payload: bytes = b"eligible(x).\n") -> KnowledgeBase:
    artifact = _artifact(payload)
    version = KBVersion(
        version_id="demo-v0001",
        revision=1,
        status="draft",
        artifacts=(artifact,),
        created_at=datetime.now(UTC),
        content_sha256="sha256:" + "1" * 64,
        change_summary="Initial version.",
    )
    return KnowledgeBase(
        kb_id="demo-kb",
        name="Demo",
        description="A governance test KB.",
        domain_id="test",
        purposes=frozenset({KBPurpose.VERIFICATION}),
        access_mode="local_owner",
        lifecycle="draft",
        current_version_id=version.version_id,
        versions=(version,),
        source_kind="managed",
    )


def _evidence(kind: EvidenceKind, digest: str, actor: str) -> ReleaseEvidence:
    return ReleaseEvidence(
        evidence_id=f"{kind}-{actor}",
        kind=kind,
        subject_sha256=digest,
        actor_id=actor,
        successful=True,
        recorded_at=datetime.now(UTC),
        details="Recorded by the test gate.",
    )


def test_release_lifecycle_requires_evidence_and_published_default() -> None:
    draft = ReleaseLifecycle.draft(_kb())
    assert execution_boundary(draft).fit_for_reliance is False
    with pytest.raises(ValueError, match="lacks successful evidence"):
        ReleaseLifecycle.transition(draft, ReleaseStage.CANDIDATE, evidence=())
    candidate = ReleaseLifecycle.transition(
        draft,
        ReleaseStage.CANDIDATE,
        evidence=(_evidence(EvidenceKind.VALIDATION, draft.content_sha256, "validator"),),
    )
    reviewed = ReleaseLifecycle.transition(
        candidate,
        ReleaseStage.REVIEWED,
        evidence=(_evidence(EvidenceKind.REVIEW, draft.content_sha256, "reviewer"),),
    )
    published = ReleaseLifecycle.transition(
        reviewed,
        ReleaseStage.PUBLISHED,
        evidence=(_evidence(EvidenceKind.PUBLICATION_APPROVAL, draft.content_sha256, "publisher"),),
    )
    assert ReleaseLifecycle.execution_release((draft, candidate, published)) == published
    assert execution_boundary(published).fit_for_reliance is True
    with pytest.raises(LookupError, match="no published"):
        ReleaseLifecycle.execution_release((draft, candidate))


def test_access_policy_redacts_source_and_does_not_leak_absence() -> None:
    policy = AccessPolicy(
        (
            AccessGrant(principal_id="reader", kb_id="demo-kb", roles=frozenset({KBRole.READER})),
            AccessGrant(principal_id="editor", kb_id="demo-kb", roles=frozenset({KBRole.EDITOR})),
        )
    )
    redacted = policy.artifact_view("reader", "demo-kb", _artifact())
    assert redacted["path"] is None
    assert redacted["sha256"] is None
    assert redacted["source_redacted"] is True
    assert policy.artifact_view("editor", "demo-kb", _artifact())["path"] == "kb/rules.lp"
    with pytest.raises(LookupError, match="unavailable") as denied:
        policy.require("reader", "demo-kb", KBPermission.EXECUTE)
    with pytest.raises(LookupError, match="unavailable") as absent:
        policy.require("reader", "absent-kb", KBPermission.READ_METADATA)
    assert str(denied.value) == str(absent.value)


def test_dependency_is_digest_pinned_and_retirement_invalidates() -> None:
    draft = ReleaseLifecycle.draft(_kb())
    candidate = ReleaseLifecycle.transition(
        draft,
        ReleaseStage.CANDIDATE,
        evidence=(_evidence(EvidenceKind.VALIDATION, draft.content_sha256, "validator"),),
    )
    dependency = KBDependency(
        dependency_id="shared-rules",
        source_kb_id="demo-kb",
        source_release_id=candidate.release_id,
        source_release_sha256=candidate.content_sha256,
        artifact_id="rules",
        artifact_sha256=_artifact().sha256,
    )
    status = validate_dependency(
        dependency,
        releases={candidate.release_id: candidate},
        artifacts={(candidate.release_id, "rules"): _artifact()},
    )
    assert status.valid
    changed = dependency.model_copy(update={"artifact_sha256": "sha256:" + "0" * 64})
    assert not validate_dependency(
        changed,
        releases={candidate.release_id: candidate},
        artifacts={(candidate.release_id, "rules"): _artifact()},
    ).valid


def test_etag_lock_idempotency_and_append_only_audit(tmp_path: Path) -> None:
    current = _kb()
    coordinator = MutationCoordinator(tmp_path / "audit.jsonl")

    def load() -> KnowledgeBase:
        return current

    def rename(kb: KnowledgeBase) -> KnowledgeBase:
        return kb.model_copy(update={"name": "Renamed"})

    result = coordinator.execute(
        kb_id=current.kb_id,
        actor_id="editor",
        action="rename",
        idempotency_key="rename-1",
        request={"name": "Renamed"},
        if_match=kb_etag(current),
        load=load,
        mutate=rename,
    )
    replay = coordinator.execute(
        kb_id=current.kb_id,
        actor_id="editor",
        action="rename",
        idempotency_key="rename-1",
        request={"name": "Renamed"},
        if_match=kb_etag(current),
        load=load,
        mutate=rename,
    )
    assert result.replayed is False and replay.replayed is True
    assert len((tmp_path / "audit.jsonl").read_text().splitlines()) == 1
    assert json.loads((tmp_path / "audit.jsonl").read_text())["action"] == "rename"
    with pytest.raises(RuntimeError, match="stale"):
        coordinator.execute(
            kb_id=current.kb_id,
            actor_id="editor",
            action="rename",
            idempotency_key="rename-2",
            request={"name": "Again"},
            if_match='"stale"',
            load=load,
            mutate=rename,
        )


def test_quota_policy_reports_every_exceeded_boundary() -> None:
    usage = QuotaUsage(
        kbs=2,
        revisions=1,
        artifacts=1,
        search_indexes=0,
        concurrent_inference=3,
        solver_seconds=1,
        ground_atoms=1,
        retained_runs=0,
    )
    policy = QuotaPolicy(QuotaLimits(max_kbs=1, max_concurrent_inference=2))
    decision = policy.check(usage)
    assert not decision.allowed
    assert len(decision.blockers) == 2
    with pytest.raises(RuntimeError, match="knowledge bases"):
        policy.require(usage)


def test_package_round_trip_is_digest_bound_and_dry_run_first(tmp_path: Path) -> None:
    payload = b"eligible(x).\n"
    package = tmp_path / "demo.ruler-kb"
    manifest = export_package(_kb(payload), package, read_artifact=lambda _: payload)
    inspected, plan = inspect_package(package)
    assert plan.safe_to_import and inspected == manifest
    imported, applied = import_package(package, tmp_path / "imports")
    assert imported == manifest and applied.safe_to_import
    digest = manifest.objects[0].artifact.sha256.removeprefix("sha256:")
    assert (
        tmp_path / "imports" / "demo-kb" / "objects" / "sha256" / digest
    ).read_bytes() == payload
    assert not inspect_package(package, existing_kb_ids=("demo-kb",))[1].safe_to_import


def test_package_rejects_traversal_and_tampering(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../outside", b"bad")
        archive.writestr("manifest.json", b"{}")
    assert not inspect_package(traversal)[1].safe_to_import

    payload = b"eligible(x).\n"
    original = tmp_path / "original.zip"
    export_package(_kb(payload), original, read_artifact=lambda _: payload)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            target.writestr(
                info.filename, b"tampered" if info.filename.startswith("objects/") else data
            )
    plan = inspect_package(tampered)[1]
    assert not plan.safe_to_import
    assert any(issue.code == "digest_mismatch" for issue in plan.issues)
