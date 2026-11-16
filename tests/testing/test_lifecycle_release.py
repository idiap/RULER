# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Lifecycle revocation and stale-source publication controls."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ruler.ingestion import (
    ApprovalDecision,
    ArtifactRecord,
    IngestionBundle,
    canonical_sha256,
    stable_id,
    validate_ingestion_bundle,
)
from ruler.ingestion.contracts import ACTIVE_STAGES, STAGE_OWNERS
from tests.ingestion.test_contracts import _annotation, _approval, _candidate, _registry, _version


def test_optional_review_never_makes_ungated_candidate_compilable() -> None:
    from ruler.ingestion import CompiledArtifact, canonical_sha256

    version = _version()
    candidate = _candidate(version)
    approval = _approval(candidate, version)
    annotation = _annotation(candidate, approval)
    revoke_payload = {
        "reviewer_id": "reviewer:1",
        "decided_at": approval.decided_at.replace(microsecond=1),
        "decision": ApprovalDecision.REVOKE,
        "source_version_id": version.source_version_id,
        "source_version_sha256": version.raw_sha256,
        "candidate_id": candidate.candidate_id,
        "candidate_sha256": approval.candidate_sha256,
        "reviewed_fields": ("semantic_payload",),
        "edits": (),
        "bilingual_check_passed": True,
        "fidelity_check_passed": True,
        "rationale": "Source was withdrawn.",
        "restrictions": (),
        "supersedes_approval_id": approval.approval_id,
    }
    revoke = approval.__class__(
        approval_id=stable_id("approval", revoke_payload),
        reviewer_role="policy_specialist",
        **revoke_payload,
    )
    compiled = CompiledArtifact(
        compiled_artifact_id="compiled:revoked",
        formal_element_ids=(candidate.formal_element_id,),
        annotation_ids=(annotation.annotation_id,),
        target="asp",
        payload_sha256=canonical_sha256("revoked_rule."),
        compiler_version="fixture-1",
    )
    errors = validate_ingestion_bundle(
        IngestionBundle(
            source_registry=(_registry(),),
            source_versions=(version,),
            candidates=(candidate,),
            approvals=(approval, revoke),
            annotations=(annotation,),
            compiled_artifacts=(compiled,),
        )
    )
    assert "compiled:revoked: ungated element rule:coverage" in errors
    assert any("annotation targets ungated element" in error for error in errors)


def test_source_drift_does_not_validate_against_stale_approval() -> None:
    original = _version(b"policy-v1")
    changed = _version(b"policy-v2")
    candidate = _candidate(original)
    approval = _approval(candidate, original)
    stale = approval.model_copy(
        update={
            "source_version_id": changed.source_version_id,
            "approval_id": approval.approval_id,
        }
    )
    with pytest.raises(ValidationError, match="approval_id does not match"):
        IngestionBundle(
            source_registry=(_registry(),),
            source_versions=(original, changed),
            candidates=(candidate,),
            approvals=(stale,),
        )


def test_every_lifecycle_stage_requires_its_immediate_predecessor() -> None:
    records: list[ArtifactRecord] = []
    for index, stage in enumerate(ACTIVE_STAGES):
        records.append(
            ArtifactRecord(
                artifact_id=f"artifact:{stage}",
                artifact_type=f"fixture:{stage}",
                stage=stage,
                owner=STAGE_OWNERS[stage],
                payload_sha256=canonical_sha256({"stage": stage}),
                prerequisite_artifact_ids=(() if index == 0 else (records[-1].artifact_id,)),
            )
        )
    assert validate_ingestion_bundle(IngestionBundle(artifact_records=tuple(records))) == []

    for missing_index in range(len(records) - 1):
        damaged = tuple(record for index, record in enumerate(records) if index != missing_index)
        errors = validate_ingestion_bundle(IngestionBundle(artifact_records=damaged))
        follower = records[missing_index + 1]
        assert any(error.startswith(f"{follower.artifact_id}:") for error in errors)
