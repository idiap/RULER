# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ruler.ingestion import (
    AutomatedGateEvidence,
    CompiledArtifact,
    FormalElementAnnotation,
    FormalizationCandidate,
    IngestionBundle,
    SourceRegistryEntry,
    SourceVersion,
    build_corpus_snapshot,
    build_kb_release,
    canonical_sha256,
    publish_kb_release,
    stable_id,
    validate_published_release,
    write_contract_schemas,
)

NOW = datetime(2026, 8, 13, tzinfo=UTC)


def _gated_bundle() -> IngestionBundle:
    url = "https://example.test/policy.pdf"
    task_id = stable_id("source_task", {"provider_id": "provider", "canonical_url": url})
    raw_hash = canonical_sha256(b"policy")
    version_id = stable_id("source_version", {"source_task_id": task_id, "raw_sha256": raw_hash})
    version = SourceVersion(
        source_version_id=version_id,
        source_task_id=task_id,
        raw_sha256=raw_hash,
        byte_length=6,
        retrieved_at=NOW,
        submitted_url=url,
        final_url=url,
        http_status=200,
        content_type="application/pdf",
    )
    registry = SourceRegistryEntry(
        source_task_id=task_id,
        provider_id="provider",
        catalogue_row_ids=("row:1",),
        product_ids=("product:1",),
        submitted_urls=(url,),
        canonical_url=url,
        source_version_ids=(version_id,),
    )
    semantic = {"predicate": "covers", "object": "loss"}
    semantic_hash = canonical_sha256(semantic)
    binding = {
        "source_version_id": version_id,
        "source_span_ids": ("span:1",),
        "source_text_sha256s": (canonical_sha256("source"),),
        "formal_element_id": "rule:1",
        "semantic_sha256": semantic_hash,
    }
    candidate = FormalizationCandidate(
        candidate_id=stable_id("formalization_candidate", binding),
        **binding,
        semantic_payload=semantic,
    )
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
    evidence = {name: canonical_sha256(name) for name in checks}
    gate_payload = {
        "candidate_id": candidate.candidate_id,
        "candidate_sha256": canonical_sha256(candidate.model_dump(mode="json")),
        "formal_element_id": candidate.formal_element_id,
        "semantic_sha256": candidate.semantic_sha256,
        "deterministic_checks": checks,
        "deterministic_evidence_hashes": evidence,
        "generative_gate_config_sha256": canonical_sha256("codex-quality-config-v1"),
        "generative_evidence_sha256": canonical_sha256("quality verdict fixture"),
        "generative_verdict": "pass",
    }
    gate = AutomatedGateEvidence(
        gate_evidence_id=stable_id("automated_gate", gate_payload),
        **gate_payload,
    )
    annotation_identity = {
        "formal_element_id": "rule:1",
        "semantic_sha256": semantic_hash,
        "source_span_ids": ("span:1",),
        "source_text_sha256s": (canonical_sha256("source"),),
        "source_language": "fr",
        "source_language_gloss": "La police couvre la perte.",
        "controlled_english": "The policy covers the loss.",
        "terminology_decision_ids": (),
    }
    annotation = FormalElementAnnotation(
        annotation_id=stable_id("formal_annotation", annotation_identity),
        **annotation_identity,
        review_state="validated",
    )
    compiled = CompiledArtifact(
        compiled_artifact_id="compiled:1",
        formal_element_ids=("rule:1",),
        annotation_ids=(annotation.annotation_id,),
        target="prolog",
        payload_sha256=canonical_sha256("covers(loss)."),
        compiler_version="1",
    )
    return IngestionBundle(
        source_registry=(registry,),
        source_versions=(version,),
        candidates=(candidate,),
        automated_gates=(gate,),
        annotations=(annotation,),
        compiled_artifacts=(compiled,),
    )


def _validator_payloads() -> dict[str, object]:
    return {
        **{
            f"deterministic:{name}": name
            for name in (
                "schema",
                "provenance",
                "fidelity",
                "coherence",
                "compilation",
                "interpretability",
            )
        },
        "generative:config": "codex-quality-config-v1",
        "generative:verdict": "quality verdict fixture",
    }


def test_contract_schema_catalogue_is_persisted_and_hash_bound(tmp_path) -> None:
    paths = write_contract_schemas(tmp_path)
    assert "KBReleaseManifest" in paths
    assert paths["catalogue"].exists()
    assert (
        write_contract_schemas(tmp_path)["catalogue"].read_bytes()
        == paths["catalogue"].read_bytes()
    )


def test_release_builder_publishes_idempotent_immutable_manifest(tmp_path) -> None:
    bundle = _gated_bundle()
    snapshot = build_corpus_snapshot(bundle, created_at=NOW)
    release = build_kb_release(
        bundle,
        snapshot,
        span_payloads={"span:1": "source"},
        translation_payloads={"translation:1": "The policy covers the loss."},
        formal_record_payloads={"rule:1": {"predicate": "covers"}},
        validator_payloads=_validator_payloads(),
    )
    first_path = publish_kb_release(release, tmp_path)
    regenerated = release.model_copy(update={"created_at": NOW + timedelta(minutes=1)})
    second_path = publish_kb_release(regenerated, tmp_path)

    assert first_path == second_path
    assert validate_published_release(first_path) == release
    assert release.corpus_snapshot_id == snapshot.corpus_snapshot_id


def test_release_builder_blocks_candidate_without_automated_gate(tmp_path) -> None:
    bundle = _gated_bundle().model_copy(update={"automated_gates": ()})
    snapshot = build_corpus_snapshot(bundle, created_at=NOW)
    with pytest.raises(ValueError, match="ungated element"):
        build_kb_release(
            bundle,
            snapshot,
            span_payloads={"span:1": "source"},
            translation_payloads={"translation:1": "translation"},
            formal_record_payloads={"rule:1": {}},
            validator_payloads=_validator_payloads(),
        )


def test_release_builder_recomputes_and_requires_automated_evidence_payloads() -> None:
    bundle = _gated_bundle()
    snapshot = build_corpus_snapshot(bundle, created_at=NOW)
    with pytest.raises(ValueError, match="automated evidence payloads are not release-pinned"):
        build_kb_release(
            bundle,
            snapshot,
            span_payloads={"span:1": "source"},
            translation_payloads={"translation:1": "translation"},
            formal_record_payloads={"rule:1": {}},
            validator_payloads={"unrelated": {"passed": True}},
        )
