# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import pytest

from ruler.applications.resource_portfolio.explanations import (
    ExplanationCounterfactual,
    ExplanationDraft,
    ExplanationDriver,
    PortfolioExplanationEvidence,
    build_deterministic_explanation,
    explanation_evidence_digest,
    validate_explanation_draft,
    _schema,
)


def _evidence(status: str = "FEASIBLE") -> PortfolioExplanationEvidence:
    payload = {
        "run_id": "run-1",
        "recommendation_id": "rec-1",
        "solver_status": status,
        "action": "RETAIN",
        "target_id": "resource-1",
        "drivers": (
            ExplanationDriver(
                driver_id="driver-capacity",
                kind="constraint",
                statement="The resource supplies required reserve capacity",
                trace_refs=("constraint:reserve",),
            ),
        ),
        "counterfactuals": (
            ExplanationCounterfactual(
                counterfactual_id="cf-demand",
                condition="demand falls below the verified threshold",
                changed_action="RELEASE",
                variant_run_id="run-2",
            ),
        ),
        "caveats": ("The plan remains subject to human approval",),
        "numeric_values": {"relative_gap": 0.01},
    }
    return PortfolioExplanationEvidence(
        **payload, evidence_digest=explanation_evidence_digest(payload)
    )


def test_deterministic_explanation_is_trace_closed_and_pending_review() -> None:
    result = build_deterministic_explanation(_evidence())
    assert result.candidate_only is False
    assert result.receipt.mode == "deterministic"
    assert result.draft.cited_driver_ids == ("driver-capacity",)
    assert result.draft.cited_numeric_keys == ("relative_gap",)
    assert "relative gap=0.01" in result.draft.explanation
    assert "Human approval" in result.draft.review_gate
    assert "provisional feasible" in result.draft.explanation


def test_explanation_rejects_invented_driver_and_optimality() -> None:
    evidence = _evidence()
    with pytest.raises(ValueError, match="unknown drivers"):
        validate_explanation_draft(
            evidence,
            ExplanationDraft(
                recommendation_id="rec-1",
                headline="Retain resource",
                explanation="An invented reason applies",
                cited_driver_ids=("invented",),
                review_gate="Human review required",
            ),
        )
    with pytest.raises(ValueError, match="cannot be described as optimal"):
        validate_explanation_draft(
            evidence,
            ExplanationDraft(
                recommendation_id="rec-1",
                headline="Optimal plan",
                explanation="The resource is retained",
                cited_driver_ids=("driver-capacity",),
                review_gate="Human review required",
            ),
        )


def test_explanation_rejects_unverified_numbers() -> None:
    with pytest.raises(ValueError, match="unsupported numbers"):
        validate_explanation_draft(
            _evidence(),
            ExplanationDraft(
                recommendation_id="rec-1",
                headline="Retain resource",
                explanation="The gap is 7 percent",
                cited_driver_ids=("driver-capacity",),
                review_gate="Human review required",
            ),
        )


def test_explanation_accepts_json_float_rendering_of_verified_integers() -> None:
    evidence = _evidence().model_copy(update={"numeric_values": {"relative_gap": 1.0}})
    validate_explanation_draft(
        evidence,
        ExplanationDraft(
            recommendation_id="rec-1",
            headline="Retain resource",
            explanation="The verified relative gap is 1.0",
            cited_driver_ids=("driver-capacity",),
            cited_numeric_keys=("relative_gap",),
            review_gate="Human review required",
        ),
    )


def test_explanation_schema_is_strict_provider_compatible() -> None:
    schema = _schema(_evidence())

    def assert_strict(value: object) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("properties"), dict):
                assert set(value["required"]) == set(value["properties"])
            for child in value.values():
                assert_strict(child)
        elif isinstance(value, list):
            for child in value:
                assert_strict(child)

    assert_strict(schema)
