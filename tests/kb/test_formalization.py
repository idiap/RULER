# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Formalization state, inventory, coverage, vocabulary, and contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ruler.kb.formalization import (
    CANONICAL_PREDICATES,
    CLAUSE_CONTRACT_FIXTURES,
    CLAUSE_TRANSLATION_CONTRACTS,
    FormalizationInventory,
    FormalizationState,
    InventoryItem,
    PredicateRegistry,
    SourceSpanRef,
    Uncertainty,
    UncertaintyKind,
    build_coverage_report,
    load_active_onboarding_inventory,
    may_transition,
    require_translation_contract,
)


def _span(assertion_id: str) -> SourceSpanRef:
    return SourceSpanRef(
        document_id="document:policy-2026",
        source_version="edition:2026-01",
        section_id="section:B1",
        span_id=f"span:{assertion_id}",
        span_sha256="sha256:" + "a" * 64,
    )


def _item(assertion_id: str, state: FormalizationState, **updates: object) -> InventoryItem:
    data: dict[str, object] = {
        "assertion_id": assertion_id,
        "assertion_kind": "clause",
        "provider": "provider-a",
        "product_family": "motor",
        "clause_type": "inclusion",
        "modality": "implication",
        "source_span": _span(assertion_id),
        "state": state,
        "target_formalism": "asp",
        "predicate_family": "coverage",
        "owner": "formalization-wave:test",
        "source_record_review": "approved",
        "logical_unit_ids": (
            [f"statement:{assertion_id}"]
            if state.value
            in {
                "candidate_logic",
                "review_required",
                "approved_logic",
                "compiled",
                "validated",
            }
            else []
        ),
    }
    data.update(updates)
    return InventoryItem.model_validate(data)


def test_empty_workspace_has_no_published_assertions(tmp_path) -> None:
    inventory = load_active_onboarding_inventory(repository_root=tmp_path)
    assert inventory.expected_assertion_count == 0
    assert inventory.items == []


def test_inventory_requires_unique_complete_assertions_and_exact_reconciliation() -> None:
    items = [
        _item("a", FormalizationState.VALIDATED),
        _item(
            "b",
            FormalizationState.NON_FORMALIZABLE,
            target_formalism="none",
            predicate_family=None,
            terminal_reason="pure marketing heading",
        ),
        _item("c", FormalizationState.REJECTED, terminal_reason="source is incomplete"),
    ]
    inventory = FormalizationInventory(
        inventory_id="inventory:test",
        release_id="release:test",
        expected_assertion_count=3,
        items=items,
    )
    counts = build_coverage_report(inventory).totals

    assert counts.source_assertions == 3
    assert counts.formalizable_assertions == 2
    assert counts.validated_units == 1
    assert counts.rejected_units == 1
    assert counts.non_formalizable_units == 1
    assert counts.unresolved_units == 0
    with pytest.raises(ValidationError, match="expected 4"):
        FormalizationInventory(
            inventory_id="inventory:bad",
            release_id="release:test",
            expected_assertion_count=4,
            items=items,
        )
    with pytest.raises(ValidationError, match="duplicate inventory assertions"):
        FormalizationInventory(
            inventory_id="inventory:duplicate",
            release_id="release:test",
            expected_assertion_count=2,
            items=[items[0], items[0]],
        )


def test_record_approval_does_not_imply_logic_and_uncertainty_blocks_promotion() -> None:
    source = _item("approved-record", FormalizationState.SOURCE_ONLY)
    assert source.source_record_review == "approved"
    assert source.state == FormalizationState.SOURCE_ONLY
    assert may_transition(source.state, FormalizationState.NORMALIZED)
    assert not may_transition(source.state, FormalizationState.COMPILED)

    unresolved = Uncertainty(
        kind=UncertaintyKind.AMBIGUOUS,
        material=True,
        resolved=False,
        rationale="two materially different interpretations",
    )
    with pytest.raises(ValidationError, match="uncertainty blocks"):
        _item("ambiguous", FormalizationState.APPROVED_LOGIC, uncertainty=unresolved)
    review = _item("ambiguous", FormalizationState.REVIEW_REQUIRED, uncertainty=unresolved)
    assert review.uncertainty.blocks_promotion


def test_metadata_projection_cannot_be_counted_as_logic() -> None:
    with pytest.raises(ValidationError, match="metadata projections"):
        _item("attribute-fact", FormalizationState.CANDIDATE_LOGIC, metadata_projection=True)


def test_canonical_vocabulary_covers_required_policy_families_and_fails_closed() -> None:
    registry = PredicateRegistry(signatures=CANONICAL_PREDICATES)
    assert {
        "benefit",
        "limit",
        "service_fee",
        "exclusion",
        "exception",
        "eligibility",
        "contract_subject",
        "covered_object",
        "geography",
        "time",
        "duty",
        "precedence",
        "document_applicability",
    } <= {signature.family for signature in registry.signatures}
    assert registry.require("coverage_limit").arity == 4
    with pytest.raises(ValueError, match="undeclared or unapproved"):
        registry.require("ad_hoc_policy_truth")


def test_every_clause_contract_has_all_fixture_classes_and_deterministic_lookup() -> None:
    required_types = {
        "definition",
        "inclusion",
        "exclusion",
        "obligation",
        "permission",
        "limit",
        "service_fee",
        "temporal",
        "precedence",
        "cross_reference",
        "exception",
    }
    assert {contract.clause_type for contract in CLAUSE_TRANSLATION_CONTRACTS} == required_types
    for clause_type in required_types:
        contract = require_translation_contract(clause_type)
        assert set(contract.required_fixture_kinds) == {
            "positive",
            "negative",
            "boundary",
            "counterexample",
        }
        fixtures = [
            fixture for fixture in CLAUSE_CONTRACT_FIXTURES if fixture.clause_type == clause_type
        ]
        assert {fixture.fixture_kind for fixture in fixtures} == {
            "positive",
            "negative",
            "boundary",
            "counterexample",
        }
        assert {fixture.expected_decision for fixture in fixtures} == {
            "compile",
            "reject",
            "hold_for_review",
        }
    with pytest.raises(ValueError, match="unsupported clause type"):
        require_translation_contract("marketing_slogan")
