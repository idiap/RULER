# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Progressive onboarding remains bounded, ordered, and evidence-driven."""

from pathlib import Path

import pytest

from ruler.ingestion.progressive_onboarding import (
    LEGACY_BATCH_IDS,
    OnboardingStage,
    ProviderDocumentExpansionPlan,
    append_progress_checkpoint,
    build_progressive_plan,
    effective_onboarding_stage,
    initialize_progressive_onboarding,
    load_progress_events,
    validate_progressive_onboarding,
)
from ruler.ingestion.contracts import stable_id
from ruler.io import write_yaml


def test_plan_splits_reference_products_into_small_nonexecuting_batches() -> None:
    plan = build_progressive_plan()

    assert plan.batches
    assert all(len(batch.product_labels) <= 3 for batch in plan.batches)
    assert all(batch.maximum_documents <= 3 for batch in plan.batches)
    assert plan.batches[0].product_labels == ("Equipment maintenance",)
    assert tuple(batch.batch_id for batch in plan.batches[:12]) == LEGACY_BATCH_IDS
    assert all(batch.batch_kind == "product_family" for batch in plan.batches[:12])
    assert all(not batch.planned_document_ids for batch in plan.batches[:12])
    assert all(batch.jurisdiction == "CH" for batch in plan.batches)
    assert "verify-kb-consistency" in " ".join(plan.continuous_verifications["every_checkpoint"])


def test_provider_expansion_contract_is_content_bound_and_document_unique() -> None:
    batches = [
        {
            "batch_id": "phase-07-batch-01",
            "phase": 7,
            "product_labels": ["Support contract"],
            "planned_document_ids": ["provider-a-legal"],
        },
        {
            "batch_id": "phase-07-batch-02",
            "phase": 7,
            "product_labels": ["Support contract"],
            "planned_document_ids": ["provider-b-legal"],
        },
    ]
    payload = {
        "schema_version": 1,
        "base_plan_id": "progressive_onboarding_plan:fixture",
        "source_reference_manifest": "data/sources/manifests/priority_policy_link_manifest.yaml",
        "batches": batches,
    }
    plan = ProviderDocumentExpansionPlan.model_validate(
        {
            **payload,
            "expansion_plan_id": stable_id("provider_document_expansion_plan", payload),
        }
    )

    assert plan.batches[0].product_labels == plan.batches[1].product_labels
    assert all(batch.jurisdiction == "CH" for batch in plan.batches)
    duplicate_payload = {
        **payload,
        "batches": [
            batches[0],
            {**batches[1], "planned_document_ids": ["provider-a-legal"]},
        ],
    }
    with pytest.raises(ValueError, match="exactly one batch"):
        ProviderDocumentExpansionPlan.model_validate(
            {
                **duplicate_payload,
                "expansion_plan_id": stable_id(
                    "provider_document_expansion_plan", duplicate_payload
                ),
            }
        )


def test_build_plan_appends_document_bound_expansion_without_changing_legacy_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ruler.ingestion.progressive_onboarding as onboarding

    reference = tmp_path / "reference.yaml"
    expansion_path = tmp_path / "provider_document_expansion_plan.yaml"
    monkeypatch.setattr(
        onboarding,
        "PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE",
        tmp_path / "not-yet-created-expansion.yaml",
    )
    base = onboarding.build_progressive_plan()
    write_yaml(
        reference,
        {"selected_documents": [{"document_id": "provider-a-legal", "row_count": 4}]},
    )
    expansion_payload = {
        "schema_version": 1,
        "base_plan_id": base.plan_id,
        "source_reference_manifest": "reference.yaml",
        "batches": [
            {
                "batch_id": "phase-07-batch-01",
                "phase": 7,
                "product_labels": ["Support contract"],
                "planned_document_ids": ["provider-a-legal"],
                "jurisdiction": "LI",
            }
        ],
    }
    write_yaml(
        expansion_path,
        {
            **expansion_payload,
            "expansion_plan_id": stable_id("provider_document_expansion_plan", expansion_payload),
        },
    )
    monkeypatch.setattr(onboarding, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(onboarding, "PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE", expansion_path)

    expanded = onboarding.build_progressive_plan()

    assert tuple(batch.batch_id for batch in expanded.batches[:12]) == LEGACY_BATCH_IDS
    assert expanded.batches[-1].batch_kind == "provider_document_expansion"
    assert expanded.batches[-1].planned_document_ids == ("provider-a-legal",)
    assert expanded.batches[-1].jurisdiction == "LI"
    assert expanded.batches[-1].phase_workbook_rows == 4
    assert expanded.plan_id != base.plan_id


def test_build_plan_rejects_incomplete_reference_document_coverage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ruler.ingestion.progressive_onboarding as onboarding

    reference = tmp_path / "reference.yaml"
    expansion_path = tmp_path / "provider_document_expansion_plan.yaml"
    monkeypatch.setattr(
        onboarding,
        "PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE",
        tmp_path / "not-yet-created-expansion.yaml",
    )
    base = onboarding.build_progressive_plan()
    write_yaml(
        reference,
        {
            "selected_documents": [
                {"document_id": "provider-a-legal", "row_count": 4},
                {"document_id": "provider-b-legal", "row_count": 2},
            ]
        },
    )
    expansion_payload = {
        "schema_version": 1,
        "base_plan_id": base.plan_id,
        "source_reference_manifest": "reference.yaml",
        "batches": [
            {
                "batch_id": "phase-07-batch-01",
                "phase": 7,
                "product_labels": ["Support contract"],
                "planned_document_ids": ["provider-a-legal"],
            }
        ],
    }
    write_yaml(
        expansion_path,
        {
            **expansion_payload,
            "expansion_plan_id": stable_id("provider_document_expansion_plan", expansion_payload),
        },
    )
    monkeypatch.setattr(onboarding, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(onboarding, "PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE", expansion_path)

    with pytest.raises(ValueError, match="must exactly cover reference documents"):
        onboarding.build_progressive_plan()


def test_exact_coverage_exempts_legacy_batch_and_reference_release_documents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ruler.ingestion.progressive_onboarding as onboarding

    expansion_path = tmp_path / "provider_document_expansion_plan.yaml"
    monkeypatch.setattr(
        onboarding,
        "PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE",
        tmp_path / "not-yet-created-expansion.yaml",
    )
    base = onboarding.build_progressive_plan()
    write_yaml(
        tmp_path / "reference.yaml",
        {
            "selected_documents": [
                {"document_id": "legacy-lifecycle-document", "row_count": 3},
                {
                    "document_id": next(iter(onboarding.LEGACY_REFERENCE_DOCUMENT_IDS)),
                    "row_count": 1,
                },
                {"document_id": "provider-a-legal", "row_count": 4},
            ]
        },
    )
    write_yaml(
        tmp_path
        / "data/operations/progressive_onboarding/batches/phase-01-batch-01/input/source_selection.yaml",
        {"document_ids": ["legacy-lifecycle-document"]},
    )
    expansion_payload = {
        "schema_version": 1,
        "base_plan_id": base.plan_id,
        "source_reference_manifest": "reference.yaml",
        "batches": [
            {
                "batch_id": "phase-07-batch-01",
                "phase": 7,
                "product_labels": ["Support contract"],
                "planned_document_ids": ["provider-a-legal"],
            }
        ],
    }
    write_yaml(
        expansion_path,
        {
            **expansion_payload,
            "expansion_plan_id": stable_id("provider_document_expansion_plan", expansion_payload),
        },
    )
    monkeypatch.setattr(onboarding, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(onboarding, "PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE", expansion_path)

    expanded = onboarding.build_progressive_plan()

    assert expanded.batches[-1].planned_document_ids == ("provider-a-legal",)


def test_initialization_seeds_only_a_planned_event(tmp_path: Path) -> None:
    artifacts = initialize_progressive_onboarding(tmp_path)
    events = load_progress_events(artifacts["ledger"])

    assert len(events) == 1
    assert events[0].stage == OnboardingStage.PLANNED
    assert validate_progressive_onboarding(tmp_path)[-1] == "scale_execution=disabled"


def test_checkpoint_requires_adjacent_stage_and_evidence(tmp_path: Path) -> None:
    artifacts = initialize_progressive_onboarding(tmp_path)
    batch_id = build_progressive_plan().batches[0].batch_id

    with pytest.raises(ValueError, match="next legal stage"):
        append_progress_checkpoint(
            batch_id,
            OnboardingStage.EXTRACTED,
            evidence_ids=("artifact:extract",),
            note="Skipping fetch is forbidden.",
            path=artifacts["ledger"],
        )
    with pytest.raises(ValueError, match="requires evidence"):
        append_progress_checkpoint(
            batch_id,
            OnboardingStage.SOURCES_READY,
            evidence_ids=(),
            note="Missing evidence.",
            path=artifacts["ledger"],
        )
    event = append_progress_checkpoint(
        batch_id,
        OnboardingStage.SOURCES_READY,
        evidence_ids=("source_snapshot:fixture",),
        note="Bounded sources verified.",
        path=artifacts["ledger"],
    )
    assert event.previous_stage == OnboardingStage.PLANNED
    assert validate_progressive_onboarding(tmp_path)[1] == "events=2"


def test_reference_backed_publication_is_final_for_later_phase_checkpoint(
    tmp_path: Path,
) -> None:
    """Status and checkpoint writes must recognize the same immutable reference release."""
    artifacts = initialize_progressive_onboarding(tmp_path)
    plan = build_progressive_plan()
    target = next(batch for batch in plan.batches if batch.batch_id == "phase-04-batch-01")
    reference_batch_id = "phase-03-batch-02"

    for prior in (
        batch
        for batch in plan.batches
        if batch.phase < target.phase and batch.batch_id != reference_batch_id
    ):
        append_progress_checkpoint(
            prior.batch_id,
            OnboardingStage.BLOCKED,
            evidence_ids=(),
            note="Fixture final state for an unrelated predecessor.",
            path=artifacts["ledger"],
        )
    append_progress_checkpoint(
        target.batch_id,
        OnboardingStage.PLANNED,
        evidence_ids=("fixture:phase-04-plan",),
        note="Fixture target plan.",
        path=artifacts["ledger"],
    )

    event = append_progress_checkpoint(
        target.batch_id,
        OnboardingStage.SOURCES_READY,
        evidence_ids=("fixture:phase-04-sources",),
        note="Reference-backed predecessor accepted as published.",
        path=artifacts["ledger"],
    )

    assert event.previous_stage == OnboardingStage.PLANNED


def test_unfinished_predecessor_without_reference_still_blocks_checkpoint(
    tmp_path: Path,
) -> None:
    """Reference support must not weaken the normal ordered-predecessor invariant."""
    artifacts = initialize_progressive_onboarding(tmp_path)
    target = "phase-02-batch-01"
    append_progress_checkpoint(
        target,
        OnboardingStage.PLANNED,
        evidence_ids=("fixture:phase-02-plan",),
        note="Fixture target plan.",
        path=artifacts["ledger"],
    )

    with pytest.raises(ValueError, match="prior phase batch is not final: phase-01-batch-01"):
        append_progress_checkpoint(
            target,
            OnboardingStage.SOURCES_READY,
            evidence_ids=("fixture:must-not-advance",),
            note="Unfinished predecessor must block.",
            path=artifacts["ledger"],
        )


def test_same_phase_predecessor_blocks_a_later_batch(tmp_path: Path) -> None:
    artifacts = initialize_progressive_onboarding(tmp_path)
    plan = build_progressive_plan()
    predecessor = next(batch for batch in plan.batches if batch.batch_id == "phase-06-batch-01")
    target = next(batch for batch in plan.batches if batch.batch_id == "phase-06-batch-02")
    for prior in plan.batches[: plan.batches.index(predecessor)]:
        append_progress_checkpoint(
            prior.batch_id,
            OnboardingStage.BLOCKED,
            evidence_ids=(),
            note="Fixture predecessor final state.",
            path=artifacts["ledger"],
        )
    append_progress_checkpoint(
        target.batch_id,
        OnboardingStage.PLANNED,
        evidence_ids=("fixture:planned",),
        note="Fixture later same-phase batch.",
        path=artifacts["ledger"],
    )

    with pytest.raises(ValueError, match=predecessor.batch_id):
        append_progress_checkpoint(
            target.batch_id,
            OnboardingStage.SOURCES_READY,
            evidence_ids=("fixture:sources",),
            note="Must not skip the same-phase predecessor.",
            path=artifacts["ledger"],
        )


def test_revision_is_non_advancing_and_requires_deterministic_verification(
    tmp_path: Path,
) -> None:
    artifacts = initialize_progressive_onboarding(tmp_path)
    batch_id = build_progressive_plan().batches[0].batch_id

    with pytest.raises(ValueError, match="revision requires"):
        append_progress_checkpoint(
            batch_id,
            OnboardingStage.REVISION,
            evidence_ids=("batch_revision:too-early",),
            note="A premature revision must fail closed.",
            path=artifacts["ledger"],
        )

    for stage in (
        OnboardingStage.SOURCES_READY,
        OnboardingStage.EXTRACTED,
        OnboardingStage.COMPLETENESS_VERIFIED,
        OnboardingStage.FORMALIZED,
        OnboardingStage.DETERMINISTIC_VERIFIED,
    ):
        append_progress_checkpoint(
            batch_id,
            stage,
            evidence_ids=(f"fixture:{stage.value}",),
            note=f"Fixture checkpoint for {stage.value}.",
            path=artifacts["ledger"],
        )
    revision = append_progress_checkpoint(
        batch_id,
        OnboardingStage.REVISION,
        evidence_ids=("batch_revision:fixture",),
        note="Corrected artifacts were rebuilt and reverified.",
        path=artifacts["ledger"],
    )
    assert revision.previous_stage == OnboardingStage.DETERMINISTIC_VERIFIED
    assert validate_progressive_onboarding(tmp_path)[1] == "events=7"

    generative = append_progress_checkpoint(
        batch_id,
        OnboardingStage.GENERATIVE_VERIFIED,
        evidence_ids=("quality_consensus:fixture",),
        note="Two current-hash judgments passed.",
        path=artifacts["ledger"],
    )
    assert generative.previous_stage == OnboardingStage.REVISION
    assert validate_progressive_onboarding(tmp_path)[1] == "events=8"


@pytest.mark.parametrize(
    "reopened_stage",
    [OnboardingStage.GENERATIVE_VERIFIED, OnboardingStage.COHERENCE_VERIFIED],
)
def test_revision_reopens_post_consensus_batch_at_deterministic_stage(
    tmp_path: Path, reopened_stage: OnboardingStage
) -> None:
    artifacts = initialize_progressive_onboarding(tmp_path)
    batch_id = build_progressive_plan().batches[0].batch_id
    for stage in (
        OnboardingStage.SOURCES_READY,
        OnboardingStage.EXTRACTED,
        OnboardingStage.COMPLETENESS_VERIFIED,
        OnboardingStage.FORMALIZED,
        OnboardingStage.DETERMINISTIC_VERIFIED,
        OnboardingStage.GENERATIVE_VERIFIED,
    ):
        append_progress_checkpoint(
            batch_id,
            stage,
            evidence_ids=(f"fixture:{stage.value}",),
            note=f"Fixture checkpoint for {stage.value}.",
            path=artifacts["ledger"],
        )
    if reopened_stage == OnboardingStage.COHERENCE_VERIFIED:
        append_progress_checkpoint(
            batch_id,
            reopened_stage,
            evidence_ids=("fixture:coherence",),
            note="Fixture coherence checkpoint.",
            path=artifacts["ledger"],
        )

    revision = append_progress_checkpoint(
        batch_id,
        OnboardingStage.REVISION,
        evidence_ids=("batch_revision:post-consensus",),
        note="Post-consensus correction rebuilt deterministic artifacts.",
        path=artifacts["ledger"],
    )
    events = [
        event for event in load_progress_events(artifacts["ledger"]) if event.batch_id == batch_id
    ]
    assert revision.previous_stage == reopened_stage
    assert effective_onboarding_stage(events) == OnboardingStage.DETERMINISTIC_VERIFIED

    append_progress_checkpoint(
        batch_id,
        OnboardingStage.GENERATIVE_VERIFIED,
        evidence_ids=("quality_consensus:replacement",),
        note="Replacement current-hash consensus passed.",
        path=artifacts["ledger"],
    )
    append_progress_checkpoint(
        batch_id,
        OnboardingStage.COHERENCE_VERIFIED,
        evidence_ids=("coherence:replacement",),
        note="Replacement coherence passed.",
        path=artifacts["ledger"],
    )
    append_progress_checkpoint(
        batch_id,
        OnboardingStage.PUBLISHED,
        evidence_ids=("release:replacement",),
        note="Replacement release published.",
        path=artifacts["ledger"],
    )
    with pytest.raises(ValueError, match="revision requires"):
        append_progress_checkpoint(
            batch_id,
            OnboardingStage.REVISION,
            evidence_ids=("batch_revision:after-publication",),
            note="Published releases remain immutable.",
            path=artifacts["ledger"],
        )
    assert validate_progressive_onboarding(tmp_path)[0].startswith("batches=")


def test_source_revision_is_non_advancing_after_completeness(tmp_path: Path) -> None:
    artifacts = initialize_progressive_onboarding(tmp_path)
    batch_id = build_progressive_plan().batches[0].batch_id

    with pytest.raises(ValueError, match="completeness-verified"):
        append_progress_checkpoint(
            batch_id,
            OnboardingStage.SOURCE_REVISION,
            evidence_ids=("batch_source_revision:too-early",),
            note="Premature source remediation.",
            path=artifacts["ledger"],
        )

    for stage in (
        OnboardingStage.SOURCES_READY,
        OnboardingStage.EXTRACTED,
        OnboardingStage.COMPLETENESS_VERIFIED,
    ):
        append_progress_checkpoint(
            batch_id,
            stage,
            evidence_ids=(f"fixture:{stage.value}",),
            note=f"Fixture checkpoint for {stage.value}.",
            path=artifacts["ledger"],
        )
    amendment = append_progress_checkpoint(
        batch_id,
        OnboardingStage.SOURCE_REVISION,
        evidence_ids=("batch_source_revision:fixture",),
        note="Corrected source provenance was revalidated.",
        path=artifacts["ledger"],
    )
    assert amendment.previous_stage == OnboardingStage.COMPLETENESS_VERIFIED
    assert validate_progressive_onboarding(tmp_path)[1] == "events=5"


def test_scope_revision_is_non_advancing_after_sources_ready(tmp_path: Path) -> None:
    artifacts = initialize_progressive_onboarding(tmp_path)
    batch_id = build_progressive_plan().batches[0].batch_id

    with pytest.raises(ValueError, match="sources-ready"):
        append_progress_checkpoint(
            batch_id,
            OnboardingStage.SCOPE_REVISION,
            evidence_ids=("batch_scope_revision:too-early",),
            note="Premature scope remediation.",
            path=artifacts["ledger"],
        )

    append_progress_checkpoint(
        batch_id,
        OnboardingStage.SOURCES_READY,
        evidence_ids=("fixture:sources_ready",),
        note="Fixture source checkpoint.",
        path=artifacts["ledger"],
    )
    amendment = append_progress_checkpoint(
        batch_id,
        OnboardingStage.SCOPE_REVISION,
        evidence_ids=("batch_scope_revision:fixture",),
        note="Corrected source scope was revalidated.",
        path=artifacts["ledger"],
    )

    assert amendment.previous_stage == OnboardingStage.SOURCES_READY
    assert validate_progressive_onboarding(tmp_path)[1] == "events=3"
