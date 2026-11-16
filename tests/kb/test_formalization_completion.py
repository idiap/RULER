# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from ruler.ingestion.contracts import stable_id
from ruler.kb.formalization_completion import (
    MIGRATION_REQUIREMENTS,
    AssertionInventoryItem,
    FormalizationState,
    MigrationFamily,
    ReviewedClassification,
    ReviewedOverlayStream,
    TraceClosure,
    build_current_completion_report,
    build_effective_classifications,
    evaluate_completion,
    validate_overlay_stream,
)


def _decision(
    assertion_id: str,
    *,
    state: FormalizationState,
    formalizable: bool,
    revision: int = 1,
    previous_overlay_id: str | None = None,
    reviewed_at: datetime | None = None,
) -> ReviewedClassification:
    migration_family = MigrationFamily.DEFINITION_SCOPE
    evidence = (
        {
            requirement: (f"evidence:{requirement}",)
            for requirement in MIGRATION_REQUIREMENTS[migration_family]
        }
        if state == FormalizationState.VALIDATED
        else {}
    )
    trace = (
        TraceClosure(
            source_version_ids=("source:1",),
            source_span_ids=("span:1",),
            logical_unit_ids=("rule:1",),
            atom_ids=("rule:1:head",),
        )
        if state == FormalizationState.VALIDATED
        else TraceClosure(
            source_version_ids=("source:1",),
            source_span_ids=("span:1",),
            logical_unit_ids=(),
            atom_ids=(),
            explicit_gap_reason="reviewed as not executable domain knowledge",
        )
    )
    payload = {
        "assertion_id": assertion_id,
        "revision": revision,
        "previous_overlay_id": previous_overlay_id,
        "reviewed_at": reviewed_at or datetime(2026, 8, 17, tzinfo=timezone.utc),
        "reviewer_id": "fixture-reviewer",
        "review_kind": "fixture",
        "state": state,
        "formalizable": formalizable,
        "modality": "definition",
        "migration_family": migration_family,
        "requirement_evidence": evidence,
        "trace": trace.model_dump(mode="python"),
        "blockers": () if state == FormalizationState.VALIDATED else ("not formalizable",),
        "rationale": "Fixture review decision.",
        "human_approval_ref": None,
    }
    return ReviewedClassification(
        overlay_id=stable_id("formalization_overlay", payload),
        **payload,
    )


def _inventory(assertion_id: str) -> AssertionInventoryItem:
    return AssertionInventoryItem(
        assertion_id=assertion_id,
        origin="published_onboarding:fixture",
        assertion_kind="clause",
        provider="provider",
        product_family="family",
        source_version_ids=("source:1",),
    )


def test_modality_requirements_block_compiled_or_validated_shortcuts() -> None:
    valid = _decision(
        "assertion:1",
        state=FormalizationState.VALIDATED,
        formalizable=True,
    )
    payload = valid.model_dump(mode="python")
    payload["requirement_evidence"].pop("boundary_counterexample")
    identity = {key: value for key, value in payload.items() if key != "overlay_id"}
    payload["overlay_id"] = stable_id("formalization_overlay", identity)
    with pytest.raises(ValidationError, match="lacks requirements"):
        ReviewedClassification.model_validate(payload)


def test_append_only_overlay_chain_rejects_broken_predecessor() -> None:
    first = _decision(
        "assertion:1",
        state=FormalizationState.NON_FORMALIZABLE,
        formalizable=False,
    )
    second = _decision(
        "assertion:1",
        state=FormalizationState.NON_FORMALIZABLE,
        formalizable=False,
        revision=2,
        previous_overlay_id="formalization_overlay:wrong",
        reviewed_at=first.reviewed_at + timedelta(days=1),
    )
    stream = ReviewedOverlayStream(stream_id="fixture", decisions=(first, second))
    errors = validate_overlay_stream(stream, [_inventory("assertion:1")])
    assert errors == ["assertion:1: broken previous_overlay_id chain"]


def test_completion_requires_terminal_validated_and_trace_closed_reconciliation() -> None:
    validated = _decision(
        "assertion:validated",
        state=FormalizationState.VALIDATED,
        formalizable=True,
    )
    non_formalizable = _decision(
        "assertion:non-formalizable",
        state=FormalizationState.NON_FORMALIZABLE,
        formalizable=False,
    )
    inventory = [
        _inventory("assertion:validated"),
        _inventory("assertion:non-formalizable"),
    ]
    stream = ReviewedOverlayStream(
        stream_id="fixture",
        decisions=(validated, non_formalizable),
    )
    report = evaluate_completion(build_effective_classifications(inventory, stream))
    assert report.total_inventory == sum(report.state_counts.values()) == 2
    assert report.terminal_items == 2
    assert report.validated_formalizable_items == report.formalizable_items == 1
    assert report.trace_closed_items == 2
    assert report.inventory_closed
    assert report.formalizable_coverage_complete
    assert report.document_trace_closed
    assert report.closed_provider_product_scopes == report.provider_product_scopes == 1
    assert report.complete
    assert report.blockers == ()


def test_hash_bound_overlay_rejects_in_place_review_mutation() -> None:
    decision = _decision(
        "assertion:1",
        state=FormalizationState.NON_FORMALIZABLE,
        formalizable=False,
    )
    payload = decision.model_dump(mode="python")
    payload["rationale"] = "Mutated without appending a revision."
    with pytest.raises(ValidationError, match="overlay_id does not match"):
        ReviewedClassification.model_validate(payload)


def test_current_report_helper_never_claims_completion() -> None:
    report = build_current_completion_report()
    assert report.total_inventory == (report.published_assertions + report.canonical_policy_records)
    assert report.complete is False
    assert report.blockers == ("no published assertions configured",)
