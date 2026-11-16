# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ruler.ingestion import (
    CompletenessEntry,
    ExtractionArtifact,
    FidelityCheck,
    FidelityGate,
    KnowledgeState,
    KnowledgeStatusFact,
    MaterialCategory,
    PageExtractionQuality,
    PolicyCompletenessLedger,
    SemanticAtom,
    VocabularySenseDecision,
    build_structural_inventory,
    canonical_sha256,
    extraction_quality_gate,
    stable_id,
)


def _extraction(*, quality: float = 0.99, status: str = "complete") -> ExtractionArtifact:
    return ExtractionArtifact(
        extraction_artifact_id="extraction:1",
        source_version_id="source:1",
        extractor="fixture",
        extractor_version="1",
        configuration_sha256=canonical_sha256({}),
        raw_output_sha256=canonical_sha256("raw"),
        cleaned_view_sha256=canonical_sha256("clean"),
        quality=quality,
        status=status,
    )


def test_complete_inventory_has_no_top_n_loss_and_defaults_to_deferred() -> None:
    blocks = [f"## Section {index}\n\nParagraph {index}." for index in range(40)]
    text = "\n\n".join(blocks)
    inventory, elements, decisions = build_structural_inventory(
        source_version_id="source:1", extraction=_extraction(), raw_text=text, cleaned_text=text
    )
    assert len(elements) == 80
    assert len(inventory.element_ids) == len(decisions) == 80
    assert {item.disposition for item in decisions} == {"defer"}
    assert {item.recommendation_materiality for item in decisions} == {"unresolved"}
    assert len({item.element_id for item in elements}) == 80


def test_low_quality_or_partial_extraction_is_not_formalization_ready() -> None:
    page = PageExtractionQuality(
        page=1,
        native_text_characters=0,
        extracted_text_sha256=canonical_sha256(""),
        quality=0.2,
        rotation_degrees=90,
        detected_languages=("fr",),
        ocr_state="partial",
    )
    ready, reasons = extraction_quality_gate(_extraction(quality=0.4, status="partial"), (page,))
    assert ready is False
    assert "extraction_partial" in reasons
    assert "page_1_ocr_partial" in reasons


def test_reviewed_completeness_ledger_rejects_unresolved_category() -> None:
    entries = tuple(
        CompletenessEntry(
            category=category,
            status="unresolved",
            rationale="Review pending.",
        )
        for category in MaterialCategory
    )
    payload = {
        "source_version_id": "source:1",
        "recommendation_scope": "motor",
        "entries": [item.model_dump(mode="json") for item in entries],
    }
    with pytest.raises(ValidationError, match="unresolved"):
        PolicyCompletenessLedger(
            ledger_id=stable_id("completeness_ledger", payload),
            **payload,
            review_state="reviewed",
        )


def test_unresolved_vocabulary_cannot_silently_choose_first_sense() -> None:
    with pytest.raises(ValidationError, match="cannot silently select"):
        VocabularySenseDecision(
            decision_id="decision:franchise",
            provider_term="franchise",
            source_language="fr",
            sense_id="vehicle_service_fee",
            status="unresolved",
            rationale="Multiple corpus senses.",
            source_artifact_refs=("span:1",),
        )


def test_semantic_atom_identity_includes_numeric_unit_currency_and_source_version() -> None:
    payload = {
        "subject": "replacement_vehicle",
        "predicate": "benefit_limit",
        "object_or_value": 500,
        "unit": None,
        "currency": "CHF",
        "modality": "maximum",
        "negated": False,
        "quantifier": None,
        "source_version_id": "source:v1",
    }
    atom = SemanticAtom(
        atom_id=stable_id("semantic_atom", payload),
        role="limit",
        source_span_ids=("span:1",),
        vocabulary_decision_ids=("decision:benefit_limit",),
        **payload,
    )
    changed = {**payload, "object_or_value": 750}
    assert atom.atom_id != stable_id("semantic_atom", changed)


def test_fidelity_gate_requires_both_directions_and_deterministic_generative_authorization() -> (
    None
):
    checks = tuple(
        FidelityCheck(
            check_kind=kind,
            status="pass",
            evidence_refs=("evidence:1",),
            details="Checked independently.",
        )
        for kind in (
            "source_entails_formal",
            "formal_entails_source",
            "contradiction",
            "numeric_unit_date",
            "exception_preservation",
            "cross_reference_preservation",
            "bilingual",
        )
    )
    assert not FidelityGate(
        formal_element_id="rule:1", semantic_sha256=canonical_sha256({}), checks=checks
    ).compilation_allowed
    assert FidelityGate(
        formal_element_id="rule:1",
        semantic_sha256=canonical_sha256({}),
        checks=checks,
        deterministic_gate_ids=("gate:schema-and-solver",),
        generative_gate_ids=("judge:semantic-fidelity",),
    ).compilation_allowed
    assert (
        FidelityGate(
            formal_element_id="rule:1",
            semantic_sha256=canonical_sha256({}),
            checks=checks,
            optional_reviewer_metadata={"reviewer": "optional-review:1"},
        ).compilation_allowed
        is False
    )


def test_unknown_is_distinct_from_excluded_and_negative_requires_evidence() -> None:
    payload = {
        "subject_id": "product:1",
        "predicate": "covers_theft",
        "state": KnowledgeState.UNKNOWN,
        "evidence_refs": (),
        "rationale": "No material clause has been reviewed yet.",
    }
    fact = KnowledgeStatusFact(fact_id=stable_id("knowledge_status", payload), **payload)
    assert fact.state is KnowledgeState.UNKNOWN
    excluded = {**payload, "state": KnowledgeState.EXCLUDED}
    with pytest.raises(ValidationError, match="require evidence"):
        KnowledgeStatusFact(fact_id=stable_id("knowledge_status", excluded), **excluded)
