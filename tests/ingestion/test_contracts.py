# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from ruler.ingestion.contracts import (
    ACTIVE_STAGES,
    STAGE_OWNERS,
    ApprovalDecision,
    AutomatedGateEvidence,
    ArtifactRecord,
    CorpusSnapshot,
    FormalElementAnnotation,
    FormalizationCandidate,
    HumanApproval,
    IngestionBundle,
    IngestionStage,
    KBReleaseManifest,
    NullMeaning,
    SourceRegistryEntry,
    SourceVersion,
    StageTransition,
    TranslationUnit,
    WorkbookCell,
    canonical_sha256,
    ingestion_json_schemas,
    stable_id,
    validate_ingestion_bundle,
)

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _registry() -> SourceRegistryEntry:
    canonical_url = "https://example.test/policy.pdf"
    return SourceRegistryEntry(
        source_task_id=stable_id(
            "source_task", {"provider_id": "provider", "canonical_url": canonical_url}
        ),
        provider_id="provider",
        catalogue_row_ids=("catalogue_row:1",),
        product_ids=("product:1",),
        submitted_urls=("https://example.test/policy.pdf?utm_source=test",),
        canonical_url=canonical_url,
    )


def _version(payload: bytes = b"policy-v1") -> SourceVersion:
    registry = _registry()
    raw_hash = canonical_sha256(payload)
    version_id = stable_id(
        "source_version", {"source_task_id": registry.source_task_id, "raw_sha256": raw_hash}
    )
    return SourceVersion(
        source_version_id=version_id,
        source_task_id=registry.source_task_id,
        raw_sha256=raw_hash,
        byte_length=len(payload),
        retrieved_at=NOW,
        submitted_url=registry.submitted_urls[0],
        final_url=registry.canonical_url,
        http_status=200,
        content_type="application/pdf",
        detected_language="fr",
    )


def _candidate(version: SourceVersion) -> FormalizationCandidate:
    semantic_payload = {"predicate": "covers", "subject": "policy", "object": "loss"}
    semantic_hash = canonical_sha256(semantic_payload)
    binding = {
        "source_version_id": version.source_version_id,
        "source_span_ids": ("span:1",),
        "source_text_sha256s": (canonical_sha256("source text"),),
        "formal_element_id": "rule:coverage",
        "semantic_sha256": semantic_hash,
    }
    return FormalizationCandidate(
        candidate_id=stable_id("formalization_candidate", binding),
        **binding,
        semantic_payload=semantic_payload,
    )


def _approval(candidate: FormalizationCandidate, version: SourceVersion) -> HumanApproval:
    payload = {
        "reviewer_id": "reviewer:1",
        "decided_at": NOW,
        "decision": ApprovalDecision.APPROVE,
        "source_version_id": version.source_version_id,
        "source_version_sha256": version.raw_sha256,
        "candidate_id": candidate.candidate_id,
        "candidate_sha256": canonical_sha256(candidate.model_dump(mode="json")),
        "reviewed_fields": ("semantic_payload", "source_span_ids"),
        "edits": (),
        "bilingual_check_passed": True,
        "fidelity_check_passed": True,
        "rationale": "Source and formal rule agree.",
        "restrictions": (),
        "supersedes_approval_id": None,
    }
    return HumanApproval(
        approval_id=stable_id("approval", payload),
        reviewer_role="policy_specialist",
        **payload,
    )


def _automated_gate(candidate: FormalizationCandidate) -> AutomatedGateEvidence:
    checks = {
        name: True
        for name in (
            "schema",
            "provenance",
            "fidelity",
            "coherence",
            "compilation",
            "interpretability",
        )
    }
    payload = {
        "candidate_id": candidate.candidate_id,
        "formal_element_id": candidate.formal_element_id,
        "candidate_sha256": canonical_sha256(candidate.model_dump(mode="json")),
        "semantic_sha256": candidate.semantic_sha256,
        "deterministic_checks": checks,
        "deterministic_evidence_hashes": {name: canonical_sha256(name) for name in checks},
        "generative_gate_config_sha256": canonical_sha256("configured codex gate"),
        "generative_evidence_sha256": canonical_sha256("quality verdict"),
        "generative_verdict": "pass",
    }
    return AutomatedGateEvidence(gate_evidence_id=stable_id("automated_gate", payload), **payload)


def _annotation(
    candidate: FormalizationCandidate, approval: HumanApproval
) -> FormalElementAnnotation:
    identity = {
        "formal_element_id": candidate.formal_element_id,
        "semantic_sha256": candidate.semantic_sha256,
        "source_span_ids": candidate.source_span_ids,
        "source_text_sha256s": candidate.source_text_sha256s,
        "source_language": "fr",
        "source_language_gloss": "La police couvre la perte.",
        "controlled_english": "The policy covers the loss.",
        "terminology_decision_ids": ("term:covers",),
    }
    return FormalElementAnnotation(
        annotation_id=stable_id("formal_annotation", identity),
        **identity,
        review_state="approved",
        reviewer_id=approval.reviewer_id,
        approved_at=approval.decided_at,
        approval_id=approval.approval_id,
    )


def test_stage_machine_accepts_only_adjacent_progression_or_terminal_exit() -> None:
    for previous, following in zip(ACTIVE_STAGES, ACTIVE_STAGES[1:]):
        payload = {
            "artifact_id": "artifact:1",
            "previous_stage": previous,
            "following_stage": following,
            "occurred_at": NOW,
            "actor": "worker:1",
            "reason": "stage completed",
            "input_artifact_ids": (),
        }
        StageTransition(transition_id=stable_id("transition", payload), **payload)

    with pytest.raises(ValidationError, match="illegal ingestion transition"):
        StageTransition(
            transition_id="transition:invalid",
            artifact_id="artifact:1",
            previous_stage=IngestionStage.CATALOGUED,
            following_stage=IngestionStage.FETCHED,
            occurred_at=NOW,
            actor="worker:1",
            reason="skipped discovery",
        )


def test_artifact_owner_is_stage_bound() -> None:
    with pytest.raises(ValidationError, match="must be owned"):
        ArtifactRecord(
            artifact_id="artifact:1",
            artifact_type="source",
            stage=IngestionStage.FETCHED,
            owner="kb_release",
            payload_sha256=canonical_sha256({}),
        )


def test_later_stage_requires_immediately_preceding_artifact() -> None:
    catalogued = ArtifactRecord(
        artifact_id="catalogue:1",
        artifact_type="row",
        stage=IngestionStage.CATALOGUED,
        owner=STAGE_OWNERS[IngestionStage.CATALOGUED],
        payload_sha256=canonical_sha256("row"),
    )
    fetched = ArtifactRecord(
        artifact_id="fetch:1",
        artifact_type="fetch",
        stage=IngestionStage.FETCHED,
        owner=STAGE_OWNERS[IngestionStage.FETCHED],
        payload_sha256=canonical_sha256("fetch"),
        prerequisite_artifact_ids=(catalogued.artifact_id,),
    )
    errors = validate_ingestion_bundle(IngestionBundle(artifact_records=(catalogued, fetched)))
    assert errors == ["fetch:1: missing prerequisite from stage source_discovered"]


def test_workbook_null_meanings_are_not_collapsed() -> None:
    placeholder = WorkbookCell(
        coordinate="Produits!R4",
        original_value="-",
        normalized_value=None,
        null_meaning=NullMeaning.PLACEHOLDER,
    )
    assert placeholder.original_value == "-"
    assert placeholder.null_meaning != NullMeaning.GENUINELY_EMPTY
    with pytest.raises(ValidationError, match="explicit null meaning"):
        WorkbookCell(coordinate="Produits!A4", original_value=None)


def test_translation_hash_is_recomputed() -> None:
    with pytest.raises(ValidationError, match="hash does not match"):
        TranslationUnit(
            translation_unit_id="translation:1",
            structural_element_ids=("element:1",),
            source_language="fr",
            source_text_sha256=canonical_sha256("texte"),
            controlled_english="text",
            controlled_english_sha256=canonical_sha256("different"),
        )


def test_candidate_rejects_self_reported_semantic_hash() -> None:
    version = _version()
    candidate = _candidate(version)
    payload = candidate.model_dump(mode="python")
    payload["semantic_payload"] = {"predicate": "excludes"}
    with pytest.raises(ValidationError, match="does not match semantic_payload"):
        FormalizationCandidate.model_validate(payload)


def test_approval_is_invalidated_when_candidate_payload_changes() -> None:
    version = _version()
    candidate = _candidate(version)
    approval = _approval(candidate, version)
    changed_payload = {"predicate": "covers", "subject": "other", "object": "loss"}
    changed_hash = canonical_sha256(changed_payload)
    changed_binding = {
        "source_version_id": candidate.source_version_id,
        "source_span_ids": candidate.source_span_ids,
        "source_text_sha256s": candidate.source_text_sha256s,
        "formal_element_id": candidate.formal_element_id,
        "semantic_sha256": changed_hash,
    }
    changed = FormalizationCandidate(
        candidate_id=stable_id("formalization_candidate", changed_binding),
        **changed_binding,
        semantic_payload=changed_payload,
    )
    stale_approval = approval.model_copy(
        update={"candidate_id": changed.candidate_id, "approval_id": approval.approval_id}
    )
    with pytest.raises(ValidationError, match="approval_id does not match"):
        IngestionBundle(
            source_registry=(_registry(),),
            source_versions=(version,),
            candidates=(changed,),
            approvals=(stale_approval,),
        )


def test_approved_annotation_is_bound_to_semantics_and_bilingual_gloss() -> None:
    version = _version()
    candidate = _candidate(version)
    approval = _approval(candidate, version)
    annotation = _annotation(candidate, approval)
    assert annotation.review_state == "approved"
    with pytest.raises(ValidationError, match="controlled-English glosses"):
        FormalElementAnnotation.model_validate(
            {**annotation.model_dump(mode="python"), "controlled_english": ""}
        )


def test_bundle_allows_only_automatically_gated_annotated_elements_to_compile() -> None:
    version = _version()
    candidate = _candidate(version)
    approval = _approval(candidate, version)
    annotation = _annotation(candidate, approval)
    from ruler.ingestion.contracts import CompiledArtifact

    compiled = CompiledArtifact(
        compiled_artifact_id="compiled:1",
        formal_element_ids=(candidate.formal_element_id,),
        annotation_ids=(annotation.annotation_id,),
        target="prolog",
        payload_sha256=canonical_sha256("rule."),
        compiler_version="1",
    )
    bundle = IngestionBundle(
        source_registry=(_registry(),),
        source_versions=(version,),
        candidates=(candidate,),
        automated_gates=(_automated_gate(candidate),),
        approvals=(approval,),
        annotations=(annotation,),
        compiled_artifacts=(compiled,),
    )
    assert validate_ingestion_bundle(bundle) == []

    assert any(
        "ungated element" in error
        for error in validate_ingestion_bundle(bundle.model_copy(update={"automated_gates": ()}))
    )


def test_snapshot_and_release_ids_are_content_derived() -> None:
    version = _version()
    snapshot_pairs = [(version.source_version_id, version.raw_sha256)]
    snapshot = CorpusSnapshot(
        corpus_snapshot_id=stable_id("corpus_snapshot", snapshot_pairs),
        source_version_ids=(version.source_version_id,),
        source_version_sha256s=(version.raw_sha256,),
        created_at=NOW,
    )
    hashes = {"item:1": canonical_sha256("one")}
    release_payload = {
        "corpus_snapshot_id": snapshot.corpus_snapshot_id,
        "source_version_hashes": {version.source_version_id: version.raw_sha256},
        "span_hashes": hashes,
        "translation_hashes": hashes,
        "formal_record_hashes": hashes,
        "automated_gate_hashes": hashes,
        "optional_review_hashes": hashes,
        "annotation_hashes": hashes,
        "executable_rule_hashes": hashes,
        "validator_hashes": hashes,
    }
    release = KBReleaseManifest(
        kb_release_id=stable_id("kb_release", release_payload),
        **release_payload,
        created_at=NOW,
    )
    assert release.kb_release_id.startswith("kb_release:")
    with pytest.raises(ValidationError, match="does not match immutable release"):
        KBReleaseManifest.model_validate(
            {
                **release.model_dump(mode="python"),
                "formal_record_hashes": {"item:1": canonical_sha256("two")},
            }
        )


def test_every_intermediate_contract_exports_json_schema() -> None:
    schemas = ingestion_json_schemas()
    required = {
        "CatalogueRow",
        "SourceRegistryEntry",
        "SourceVersion",
        "FetchResult",
        "ExtractionArtifact",
        "StructuralElement",
        "TriageDecision",
        "TranslationUnit",
        "FormalizationCandidate",
        "HumanApproval",
        "CompiledArtifact",
        "CorpusSnapshot",
        "KBReleaseManifest",
        "FormalElementAnnotation",
    }
    assert required <= schemas.keys()
    assert all(schema.get("additionalProperties") is False for schema in schemas.values())
