# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ruler.ingestion.contracts import canonical_sha256, stable_id
from ruler.kb.formalization_wave import (
    FORMALIZATION_WAVE_TEMPLATE,
    REQUIRED_SKILL_SEQUENCE,
    DocumentIdentity,
    EntailmentAssessment,
    FormalizationWaveManifest,
    load_formalization_wave_manifest,
    validate_formalization_wave_configuration,
    validate_formalization_wave_manifest,
)


def _replace(manifest: FormalizationWaveManifest, **updates: object) -> FormalizationWaveManifest:
    payload = manifest.model_dump(mode="python")
    payload.update(updates)
    return FormalizationWaveManifest.model_validate(payload)


def test_reusable_template_has_closed_grounding() -> None:
    summary = validate_formalization_wave_configuration()
    assert "manifests=1" in summary
    assert "grounding=closed" in summary
    template = load_formalization_wave_manifest(FORMALIZATION_WAVE_TEMPLATE)
    assert tuple(gate.skill for gate in template.skill_gates) == REQUIRED_SKILL_SEQUENCE


def test_document_and_source_version_identities_are_content_bound() -> None:
    coordinates = {
        "provider": "provider",
        "document_name": "policy",
        "product_family": "motor",
    }
    document_id = stable_id("document", coordinates)
    source_hash = canonical_sha256(b"immutable policy")
    version_coordinates = {
        "document_id": document_id,
        "edition": "2026-01",
        "language": "fr",
        "public_url": "https://example.invalid/policy.pdf",
        "source_sha256": source_hash,
    }
    identity = DocumentIdentity(
        document_id=document_id,
        source_version_id=stable_id("document_version", version_coordinates),
        provider="provider",
        document_name="policy",
        product_family="motor",
        edition="2026-01",
        language="fr",
        public_url="https://example.invalid/policy.pdf",
        source_sha256=source_hash,
    )
    payload = identity.model_dump(mode="python")
    payload["edition"] = "2026-02"
    with pytest.raises(ValidationError, match="immutable version coordinates"):
        DocumentIdentity.model_validate(payload)


def test_missing_skill_or_validator_cannot_be_silently_skipped() -> None:
    manifest = load_formalization_wave_manifest(FORMALIZATION_WAVE_TEMPLATE)
    without_skill = _replace(manifest, skill_gates=manifest.skill_gates[:-1])
    assert any(
        "complete canonical sequence" in error
        for error in validate_formalization_wave_manifest(without_skill)
    )
    without_validator = _replace(
        manifest,
        wave_validators=tuple(
            command
            for command in manifest.wave_validators
            if command != "uv run ruler validate formalization-governance"
        ),
    )
    assert any(
        "missing mandatory wave validators" in error
        for error in validate_formalization_wave_manifest(without_validator)
    )


def test_unresolved_reference_and_lossy_entailment_block_compilation() -> None:
    manifest = load_formalization_wave_manifest(FORMALIZATION_WAVE_TEMPLATE)
    from ruler.kb.formalization_wave import CrossReferenceResolution

    ref = CrossReferenceResolution(
        reference_id="missing-reference",
        source_part_id=manifest.document_parts[-1].part_id,
        printed_target="missing-section",
        status="unresolved",
        blocker="target not supplied",
    )
    assessment = manifest.entailment_assessments[0].model_copy(
        update={
            "source_entails_logic": "fail",
            "reviewer_id": "fixture-reviewer",
            "review_decision": "changes_requested",
        }
    )
    manifest = _replace(manifest, cross_references=(ref,), entailment_assessments=(assessment,))
    first = manifest.logical_units[0].model_copy(
        update={"compiled": True, "cross_reference_ids": (ref.reference_id,)}
    )
    changed = _replace(manifest, logical_units=(first, *manifest.logical_units[1:]))
    errors = validate_formalization_wave_manifest(changed)
    assert any("compiled with unresolved cross-reference" in error for error in errors)
    assert any("blocked by entailment" in error for error in errors)


def test_material_or_failed_entailment_requires_human_review() -> None:
    with pytest.raises(ValidationError, match="requires human review"):
        EntailmentAssessment(
            formal_element_id="rule:1",
            source_entails_logic="fail",
            logic_entails_source="pass",
            evidence_refs=("evidence:1",),
            material_failure=True,
        )


def test_active_promotion_requires_all_skill_and_release_evidence() -> None:
    manifest = load_formalization_wave_manifest(FORMALIZATION_WAVE_TEMPLATE)
    active = _replace(manifest, promotion_target="active_reasoner", template_only=False)
    errors = validate_formalization_wave_manifest(active)
    assert any("non-passing skill gates" in error for error in errors)
    assert any("approved wave review_state" in error for error in errors)
    assert any("explicit human approvals" in error for error in errors)
