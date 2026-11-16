# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Contract and portability tests for progressive batch KB construction."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from ruler.ingestion.batch_pipeline import (
    BatchPaths,
    BatchPipelineSpec,
    CATALOGUE_FILE,
    CompletenessLedger,
    PipelineStage,
    SpanSpec,
    batch_status,
    build_pipeline_catalogue,
    run_batch_stage,
    validate_batch_pipeline,
)
from ruler.ingestion.contracts import (
    FormalElementAnnotation,
    KBReleaseManifest,
    canonical_sha256,
    stable_id,
)
from ruler.ingestion.progressive_onboarding import (
    LEGACY_BATCH_IDS,
    OnboardingStage,
    load_progress_events,
)
from ruler.io import read_yaml, write_yaml
from ruler.kb.repository import (
    KnowledgeRepository,
    ReleasedAssertion,
)


def _published_repository(
    assertions: list[ReleasedAssertion], annotations: list[FormalElementAnnotation]
) -> KnowledgeRepository:
    """Build a hash-complete in-memory release around prepared batch artifacts."""

    one = {"fixture:one": canonical_sha256("fixture")}
    payload = {
        "corpus_snapshot_id": "snapshot:prepared-batch-fixture",
        "source_version_hashes": {
            source_id: canonical_sha256(source_id)
            for assertion in assertions
            for source_id in assertion.source_version_ids
        },
        "span_hashes": one,
        "translation_hashes": one,
        "formal_record_hashes": {
            item.assertion_id: canonical_sha256(item.model_dump(mode="json")) for item in assertions
        },
        "automated_gate_hashes": one,
        "optional_review_hashes": {},
        "annotation_hashes": {
            item.annotation_id: canonical_sha256(item.model_dump(mode="json"))
            for item in annotations
        },
        "executable_rule_hashes": one,
        "validator_hashes": one,
    }
    release = KBReleaseManifest(
        kb_release_id=stable_id("kb_release", payload),
        **payload,
        created_at=datetime(2026, 8, 14, tzinfo=UTC),
        release_status="published",
    )
    return KnowledgeRepository(release, assertions, annotations)


def test_publication_request_preserves_provider_neutral_multi_carrier_scope() -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    def assertion(
        assertion_id: str,
        *,
        provider: str,
        option_ids: tuple[str, ...] = (),
    ) -> tuple[ReleasedAssertion, FormalElementAnnotation]:
        payload = {"predicate": "covers", "object": assertion_id}
        semantic_sha256 = canonical_sha256(payload)
        annotation_identity = {
            "formal_element_id": assertion_id,
            "semantic_sha256": semantic_sha256,
            "source_span_ids": (f"span:{assertion_id}",),
            "source_text_sha256s": (canonical_sha256(f"source:{assertion_id}"),),
            "source_language": "fr",
            "source_language_gloss": f"Portee controlee {assertion_id}.",
            "controlled_english": f"Controlled scope {assertion_id}.",
            "terminology_decision_ids": (),
        }
        annotation = FormalElementAnnotation(
            annotation_id=stable_id("formal_annotation", annotation_identity),
            **annotation_identity,
            review_state="validated",
        )
        released = ReleasedAssertion(
            assertion_id=assertion_id,
            semantic_key=f"semantic:{assertion_id}",
            assertion_kind="clause",
            provider=provider,
            product_family="household_liability",
            product_id="RC/menage",
            jurisdiction="CH",
            option_ids=option_ids,
            source_version_ids=("source-version:multi-carrier",),
            annotation_id=annotation.annotation_id,
            payload=payload,
            payload_sha256=semantic_sha256,
        )
        return released, annotation

    fixtures = [
        assertion("clause:service-provider-maintenance", provider="service-provider"),
        assertion("feature:coop-legal-protection", provider="coop"),
        assertion(
            "clause:coop-r-option",
            provider="coop",
            option_ids=("private-legal-protection",),
        ),
    ]
    assertions = [item[0] for item in fixtures]
    annotations = [item[1] for item in fixtures]
    repository = _published_repository(assertions, annotations)
    paths = BatchPaths(
        source_selection="selection.yaml",
        extraction_manifest="extraction.yaml",
        link_manifest="links.yaml",
        span_specs="spans.yaml",
        completeness_ledger="completeness.yaml",
        formal_elements="elements.yaml",
        output_root="output",
    )
    neutral_spec = BatchPipelineSpec(
        batch_id="multi-carrier-neutral",
        sequence=1,
        phase=7,
        product_labels=("RC/menage",),
        provider=None,
        product_family="household_liability",
        quality_case_id="multi_carrier_neutral_fidelity",
        paths=paths,
    )

    request = pipeline._publication_request(neutral_spec, assertions)
    assert request.provider is None
    projections, required_groups = pipeline._publication_projections(
        repository, assertions, request
    )
    assert required_groups == {}
    assert projections[0].assertion_ids == (
        "clause:service-provider-maintenance",
        "feature:coop-legal-protection",
    )

    with_r_option = repository.project(
        request.model_copy(update={"option_ids": ("private-legal-protection",)})
    )
    assert with_r_option.assertion_ids == (
        "clause:coop-r-option",
        "clause:service-provider-maintenance",
        "feature:coop-legal-protection",
    )

    provider_spec = neutral_spec.model_copy(update={"provider": "Service-Provider"})
    provider_request = pipeline._publication_request(provider_spec, assertions)
    assert provider_request.provider == "service-provider"
    assert repository.project(provider_request).assertion_ids == (
        "clause:service-provider-maintenance",
    )
    assert repository.project(
        provider_request.model_copy(update={"option_ids": ("private-legal-protection",)})
    ).assertion_ids == ("clause:service-provider-maintenance",)


@pytest.mark.parametrize(
    ("evidence_bytes", "expected_cap"),
    [
        (0, 300_000),
        (300_000, 300_000),
        (300_001, 600_000),
        (600_000, 600_000),
        (600_001, 1_200_000),
        (1_200_000, 1_200_000),
    ],
)
def test_quality_input_cap_uses_smallest_governed_tier(
    evidence_bytes: int, expected_cap: int
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    assert pipeline._select_quality_input_cap(evidence_bytes) == expected_cap


def test_quality_input_cap_rejects_bundles_above_governed_ceiling() -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    with pytest.raises(ValueError, match="exceeds the governed ceiling of 1200000 bytes"):
        pipeline._select_quality_input_cap(1_200_001)


def test_catalogue_covers_every_bounded_batch_with_copy_ready_commands() -> None:
    """Keep batch order and execution instructions derivable from the workbook plan."""
    catalogue = build_pipeline_catalogue()

    assert len(catalogue["batches"]) >= 12
    assert tuple(item["batch_id"] for item in catalogue["batches"][:12]) == LEGACY_BATCH_IDS
    assert catalogue["entrypoint"].startswith("uv run ruler workflow product-batch-pipeline")
    assert catalogue["constraints"]["maximum_concurrent_batches"] == 1
    assert all(len(item["product_labels"]) <= 3 for item in catalogue["batches"])
    assert all(item["maximum_documents"] <= 3 for item in catalogue["batches"])
    assert len({item["quality_case_id"] for item in catalogue["batches"]}) == len(
        catalogue["batches"]
    )
    assert "source-revision" not in catalogue["stage_order"]
    assert "scope-revision" not in catalogue["stage_order"]
    validation = validate_batch_pipeline()
    assert any(item.startswith("unpublished_batches=") for item in validation)
    assert f"ledger_managed_batches={len(catalogue['batches'])}" in validation
    assert read_yaml(CATALOGUE_FILE) == catalogue


def test_status_is_self_describing_and_blocks_later_batches() -> None:
    """Tell a fresh operator exactly what is missing without allowing phase skipping."""
    first = batch_status("phase-01-batch-01")
    second = batch_status("phase-02-batch-01")
    reference = batch_status("phase-03-batch-02")

    assert first["current_stage"]
    if first["next_stage"]:
        assert first["next_command"].endswith(f"--stage {first['next_stage']}")
    assert all(not Path(item).is_absolute() for item in first["missing_inputs"])
    assert first["runbook"] == "docs/operations/progressive_product_onboarding_runbook.md"
    assert second["sequence"] == 2
    assert reference["current_stage"] is None
    assert reference["reference_release"] is None
    assert reference["batch_kind"] == "product_family"
    assert reference["planned_document_ids"] == []


def test_expansion_source_selection_must_match_planned_documents(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    write_yaml(
        tmp_path / "selection.yaml",
        {
            "batch_id": "phase-07-batch-01",
            "product_labels": ["Protection juridique"],
            "document_ids": ["unplanned-document"],
        },
    )
    spec = BatchPipelineSpec(
        batch_id="phase-07-batch-01",
        sequence=13,
        phase=7,
        product_labels=("Protection juridique",),
        batch_kind="provider_document_expansion",
        planned_document_ids=("planned-document",),
        quality_case_id="phase_07_batch_01_fidelity",
        paths=BatchPaths(
            source_selection="selection.yaml",
            extraction_manifest="extraction.yaml",
            link_manifest="links.yaml",
            span_specs="spans.yaml",
            completeness_ledger="completeness.yaml",
            formal_elements="elements.yaml",
            output_root="output",
        ),
    )
    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError, match="expansion plan documents"):
        pipeline._validate_source_selection(spec)


def test_source_and_extraction_boundaries_reject_explicit_jurisdiction_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    spec = BatchPipelineSpec(
        batch_id="jurisdiction-test",
        sequence=1,
        phase=7,
        product_labels=("Product",),
        planned_document_ids=("document-1",),
        jurisdiction="CH",
        quality_case_id="jurisdiction_test_fidelity",
        paths=BatchPaths(
            source_selection="selection.yaml",
            extraction_manifest="extraction.yaml",
            link_manifest="links.yaml",
            span_specs="spans.yaml",
            completeness_ledger="completeness.yaml",
            formal_elements="elements.yaml",
            output_root="output",
        ),
    )
    selection = {
        "batch_id": spec.batch_id,
        "jurisdiction": "FR",
        "product_labels": ["Product"],
        "document_ids": ["document-1"],
    }
    write_yaml(tmp_path / "selection.yaml", selection)
    write_yaml(
        tmp_path / "links.yaml",
        {"selected_documents": [{"document_id": "document-1", "row_refs": ["workbook#row-1"]}]},
    )
    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path)

    with pytest.raises(
        ValueError,
        match="source selection jurisdiction 'FR' does not match batch jurisdiction 'CH'",
    ):
        pipeline._validate_source_selection(spec)

    write_yaml(tmp_path / "selection.yaml", {**selection, "jurisdiction": "CH"})
    write_yaml(
        tmp_path / "extraction.yaml",
        {
            "documents": [
                {
                    "document_id": "document-1",
                    "jurisdiction": "FR",
                    "status": "extracted",
                    "raw_sha256": "sha256:fixture",
                    "row_refs": ["workbook#row-1"],
                }
            ]
        },
    )
    with pytest.raises(
        ValueError,
        match="extracted document document-1 jurisdiction 'FR' does not match batch jurisdiction 'CH'",
    ):
        pipeline._validate_extraction(spec)


def test_dry_run_never_mutates_the_progress_ledger() -> None:
    """Make readiness inspection safe in CI and newly provisioned environments."""
    before = load_progress_events()
    result = run_batch_stage("phase-02-batch-01", PipelineStage.PLANNED, dry_run=True)
    after = load_progress_events()

    assert result["dry_run"] is True
    assert before == after


def test_unknown_batch_and_illegal_stage_are_rejected() -> None:
    """Fail closed instead of inventing paths or skipping the append-only lifecycle."""
    with pytest.raises(ValueError, match="unknown progressive onboarding batch"):
        batch_status("phase-99-batch-99")
    with pytest.raises(ValueError, match="next legal stage"):
        run_batch_stage("phase-01-batch-01", PipelineStage.FORMALIZED)


def test_input_contracts_reject_bad_coordinates_and_unexplained_omissions() -> None:
    """Catch incomplete source inventories before semantic construction starts."""
    with pytest.raises(ValueError, match="line_end"):
        SpanSpec(
            span_id="span",
            document_id="document",
            artifact="source.md",
            line_start=2,
            line_end=1,
            section="section",
        )
    with pytest.raises(ValueError, match="recommendation-impact"):
        CompletenessLedger.model_validate(
            {
                "batch_id": "batch",
                "document_ids": ["document"],
                "dispositions": [
                    {
                        "structural_element_id": "section",
                        "disposition": "omit",
                        "recommendation_impact": "",
                        "rationale": "Not relevant.",
                        "source_span_ids": [],
                    }
                ],
                "unresolved_cross_references": [],
                "verified": True,
            }
        )


def _write_completeness_fixture(
    tmp_path: Path, *, disposition: str, unresolved_reference: str
) -> BatchPipelineSpec:
    write_yaml(
        tmp_path / "selection.yaml",
        {"batch_id": "completeness-test", "document_ids": ["document-1"]},
    )
    write_yaml(
        tmp_path / "spans.yaml",
        [
            {
                "span_id": "span-1",
                "document_id": "document-1",
                "artifact": "source.md",
                "line_start": 1,
                "line_end": 1,
                "section": "Section 1",
            }
        ],
    )
    write_yaml(
        tmp_path / "completeness.yaml",
        {
            "batch_id": "completeness-test",
            "document_ids": ["document-1"],
            "dispositions": [
                {
                    "structural_element_id": "section-1",
                    "disposition": disposition,
                    "recommendation_impact": "Explicitly assessed.",
                    "rationale": "Fixture disposition.",
                    "source_span_ids": ["span-1"],
                }
            ],
            "unresolved_cross_references": [unresolved_reference],
            "verified": True,
        },
    )
    return BatchPipelineSpec(
        batch_id="completeness-test",
        sequence=1,
        phase=1,
        product_labels=("Product",),
        quality_case_id="completeness_test_fidelity",
        paths=BatchPaths(
            source_selection="selection.yaml",
            extraction_manifest="extraction.yaml",
            link_manifest="links.yaml",
            span_specs="spans.yaml",
            completeness_ledger="completeness.yaml",
            formal_elements="elements.yaml",
            output_root="output",
        ),
    )


def test_completeness_accepts_cross_references_to_deferred_elements(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    spec = _write_completeness_fixture(
        tmp_path, disposition="defer", unresolved_reference="section-1"
    )
    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path)

    assert pipeline._validate_completeness(spec)["evidence_ids"]


@pytest.mark.parametrize(
    ("disposition", "unresolved_reference"),
    [("keep", "section-1"), ("omit", "section-1"), ("defer", "unknown-section")],
)
def test_completeness_rejects_cross_references_not_bound_to_deferred_elements(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    disposition: str,
    unresolved_reference: str,
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    spec = _write_completeness_fixture(
        tmp_path,
        disposition=disposition,
        unresolved_reference=unresolved_reference,
    )
    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path)

    with pytest.raises(ValueError, match="unresolved cross-references"):
        pipeline._validate_completeness(spec)


def test_catalogue_uses_only_repository_relative_paths() -> None:
    """Avoid carrying machine-specific paths into a transferred execution package."""
    for batch in build_pipeline_catalogue()["batches"]:
        for value in batch["paths"].values():
            path = Path(value)
            assert not path.is_absolute()
            assert ".." not in path.parts


def test_revision_rebuilds_all_gates_and_preserves_failed_result_ids(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A correction is an append-only audit artifact, not a rewritten stage claim."""
    import ruler.ingestion.batch_pipeline as pipeline

    spec = BatchPipelineSpec(
        batch_id="revision-test",
        sequence=1,
        phase=1,
        product_labels=("Product",),
        quality_case_id="revision_test_fidelity",
        paths=BatchPaths(
            source_selection="input/selection.yaml",
            extraction_manifest="input/extraction.yaml",
            link_manifest="input/links.yaml",
            span_specs="input/spans.yaml",
            completeness_ledger="input/completeness.yaml",
            formal_elements="input/elements.yaml",
            output_root="output",
        ),
    )
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        pipeline, "_current_failed_quality_result_ids", lambda _spec: ["failed-run-1"]
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_completeness",
        lambda _spec: calls.append("completeness") or {"evidence_ids": ["complete:1"]},
    )
    monkeypatch.setattr(
        pipeline,
        "_prepare_formalization",
        lambda _spec: calls.append("formalization") or {"evidence_ids": ["formal:2"]},
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_prepared_bundle",
        lambda _spec: calls.append("deterministic") or {"evidence_ids": ["deterministic:3"]},
    )

    result = pipeline._revise_after_failed_quality(
        spec,
        status={"current_stage": "deterministic_verified"},
    )

    assert calls == ["completeness", "formalization", "deterministic"]
    assert result["failed_result_ids"] == ["failed-run-1"]
    revision_path = next((tmp_path / "output/revisions").glob("*.yaml"))
    revision = read_yaml(revision_path)
    assert revision["failed_result_ids"] == ["failed-run-1"]
    assert revision["formalization_evidence_ids"] == ["formal:2"]


def test_revision_rejects_missing_current_hash_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    spec = BatchPipelineSpec(
        batch_id="revision-test",
        sequence=1,
        phase=1,
        product_labels=("Product",),
        quality_case_id="revision_test_fidelity",
        paths=BatchPaths(
            source_selection="input/selection.yaml",
            extraction_manifest="input/extraction.yaml",
            link_manifest="input/links.yaml",
            span_specs="input/spans.yaml",
            completeness_ledger="input/completeness.yaml",
            formal_elements="input/elements.yaml",
            output_root="output",
        ),
    )
    monkeypatch.setattr(pipeline, "_current_failed_quality_result_ids", lambda _spec: [])
    monkeypatch.setattr(pipeline, "_deterministic_artifacts_are_current", lambda _spec: True)

    with pytest.raises(ValueError, match="current-hash failed or invalid"):
        pipeline._revise_after_failed_quality(
            spec,
            status={"current_stage": "deterministic_verified"},
        )


def test_revision_rebuilds_drifted_deterministic_inputs_without_failed_judge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Input drift routed to revision must be recoverable before a judge runs."""
    import ruler.ingestion.batch_pipeline as pipeline

    spec = BatchPipelineSpec(
        batch_id="drift-revision-test",
        sequence=1,
        phase=1,
        product_labels=("Product",),
        quality_case_id="drift_revision_test_fidelity",
        paths=BatchPaths(
            source_selection="input/selection.yaml",
            extraction_manifest="input/extraction.yaml",
            link_manifest="input/links.yaml",
            span_specs="input/spans.yaml",
            completeness_ledger="input/completeness.yaml",
            formal_elements="input/elements.yaml",
            output_root="output",
        ),
    )
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "_deterministic_artifacts_are_current", lambda _spec: False)
    monkeypatch.setattr(pipeline, "_current_failed_quality_result_ids", lambda _spec: [])
    monkeypatch.setattr(pipeline, "_preserved_semantic_failure_ids", lambda _spec: [])
    monkeypatch.setattr(
        pipeline,
        "_validate_completeness",
        lambda _spec: calls.append("completeness") or {"evidence_ids": ["complete:1"]},
    )
    monkeypatch.setattr(
        pipeline,
        "_prepare_formalization",
        lambda _spec: calls.append("formalization") or {"evidence_ids": ["formal:2"]},
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_prepared_bundle",
        lambda _spec: calls.append("deterministic") or {"evidence_ids": ["deterministic:3"]},
    )

    result = pipeline._revise_after_failed_quality(
        spec,
        status={"current_stage": "deterministic_verified"},
    )

    assert calls == ["completeness", "formalization", "deterministic"]
    assert result["failed_result_ids"] == []
    assert (
        result["note"]
        == "Drifted formalization inputs were rebuilt and deterministically reverified."
    )


@pytest.mark.parametrize(
    "current_stage",
    ["generative_verified", "coherence_verified"],
)
def test_revision_reopens_post_consensus_and_records_superseded_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, current_stage: str
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    spec = BatchPipelineSpec(
        batch_id="post-consensus-revision-test",
        sequence=1,
        phase=1,
        product_labels=("Product",),
        quality_case_id="post_consensus_revision_fidelity",
        paths=BatchPaths(
            source_selection="input/selection.yaml",
            extraction_manifest="input/extraction.yaml",
            link_manifest="input/links.yaml",
            span_specs="input/spans.yaml",
            completeness_ledger="input/completeness.yaml",
            formal_elements="input/elements.yaml",
            output_root="output",
        ),
    )
    output = tmp_path / "output"
    consensus = {
        "status": "pass",
        "automated_promotion_allowed": True,
        "result_ids": ["passed-run-1", "passed-run-2"],
    }
    write_yaml(output / "quality_consensus.yaml", consensus)
    coherence = {"batch_id": spec.batch_id, "coherent": True}
    if current_stage == "coherence_verified":
        write_yaml(output / "coherence.yaml", coherence)

    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "_deterministic_artifacts_are_current", lambda _spec: False)
    monkeypatch.setattr(pipeline, "_current_failed_quality_result_ids", lambda _spec: [])
    monkeypatch.setattr(pipeline, "_preserved_semantic_failure_ids", lambda _spec: [])
    monkeypatch.setattr(
        pipeline, "_validate_completeness", lambda _spec: {"evidence_ids": ["complete:1"]}
    )
    monkeypatch.setattr(
        pipeline, "_prepare_formalization", lambda _spec: {"evidence_ids": ["formal:2"]}
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_prepared_bundle",
        lambda _spec: {"evidence_ids": ["deterministic:3"]},
    )

    result = pipeline._revise_after_failed_quality(spec, status={"current_stage": current_stage})

    revision = result["revision"]
    assert revision["reopened_from_stage"] == current_stage
    assert revision["superseded_consensus_result_ids"] == ["passed-run-1", "passed-run-2"]
    assert revision["superseded_consensus_sha256"] == canonical_sha256(consensus)
    if current_stage == "coherence_verified":
        assert revision["superseded_coherence_sha256"] == canonical_sha256(coherence)
    else:
        assert "superseded_coherence_sha256" not in revision
    assert (output / "quality_consensus.yaml").is_file()


def test_status_routes_post_consensus_artifact_drift_to_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    spec = BatchPipelineSpec(
        batch_id="post-consensus-status-test",
        sequence=1,
        phase=1,
        product_labels=("Product",),
        quality_case_id="post_consensus_status_fidelity",
        paths=BatchPaths(
            source_selection="input/selection.yaml",
            extraction_manifest="input/extraction.yaml",
            link_manifest="input/links.yaml",
            span_specs="input/spans.yaml",
            completeness_ledger="input/completeness.yaml",
            formal_elements="input/elements.yaml",
            output_root="output",
        ),
    )
    monkeypatch.setattr(pipeline, "load_batch_spec", lambda _batch_id: spec)
    monkeypatch.setattr(
        pipeline,
        "load_progress_events",
        lambda: [
            SimpleNamespace(batch_id=spec.batch_id, stage=OnboardingStage.GENERATIVE_VERIFIED)
        ],
    )
    monkeypatch.setattr(pipeline, "reference_release_is_published", lambda *args, **kwargs: False)
    monkeypatch.setattr(pipeline, "_prior_batch_blocker", lambda _spec: None)
    monkeypatch.setattr(pipeline, "_deterministic_artifacts_are_current", lambda _spec: False)
    monkeypatch.setattr(pipeline, "_required_paths", lambda _spec, _stage: [])

    status = pipeline.batch_status(spec.batch_id)

    assert status["current_stage"] == "generative_verified"
    assert status["next_stage"] == "revision"
    assert status["ready"] is True


def test_source_revision_binds_revalidated_provenance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    spec = BatchPipelineSpec(
        batch_id="source-revision-test",
        sequence=1,
        phase=1,
        product_labels=("Product",),
        quality_case_id="source_revision_fidelity",
        paths=BatchPaths(
            source_selection="input/selection.yaml",
            extraction_manifest="input/extraction.yaml",
            link_manifest="input/links.yaml",
            span_specs="input/spans.yaml",
            completeness_ledger="input/completeness.yaml",
            formal_elements="input/elements.yaml",
            output_root="output",
        ),
    )
    for path, payload in {
        "input/selection.yaml": {"batch_id": spec.batch_id},
        "input/extraction.yaml": {"documents": []},
        "input/links.yaml": {"selected_documents": []},
        "input/spans.yaml": [],
        "input/completeness.yaml": {"batch_id": spec.batch_id},
    }.items():
        write_yaml(tmp_path / path, payload)
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        pipeline,
        "load_progress_events",
        lambda: [
            SimpleNamespace(
                batch_id=spec.batch_id,
                stage=stage,
                event_id=f"event:{stage.value}",
                evidence_ids=(f"old:{stage.value}",),
            )
            for stage in (
                OnboardingStage.SOURCES_READY,
                OnboardingStage.EXTRACTED,
                OnboardingStage.COMPLETENESS_VERIFIED,
            )
        ],
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_source_selection",
        lambda _spec: calls.append("source") or {"evidence_ids": ["source:1"]},
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_extraction",
        lambda _spec: calls.append("extraction") or {"evidence_ids": ["extract:2"]},
    )
    monkeypatch.setattr(
        pipeline,
        "_validate_completeness",
        lambda _spec: calls.append("completeness") or {"evidence_ids": ["complete:3"]},
    )
    monkeypatch.setattr(pipeline, "_materialize_spans", lambda _spec: [])
    monkeypatch.setattr(pipeline, "_source_contracts", lambda _spec, _spans: ((), ()))

    result = pipeline._revise_source_provenance(
        spec, status={"current_stage": "completeness_verified"}
    )

    assert calls == ["source", "extraction", "completeness"]
    assert result["evidence_ids"][0].startswith("batch_source_revision:")
    amendment = read_yaml(next((tmp_path / "output/source_revisions").glob("*.yaml")))
    assert amendment["prior_checkpoint_evidence_ids"]["sources_ready"] == ["old:sources_ready"]


def test_scope_revision_binds_plan_specs_and_document_relocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    def make_spec(batch_id: str, sequence: int, documents: tuple[str, ...], jurisdiction: str):
        return BatchPipelineSpec(
            batch_id=batch_id,
            sequence=sequence,
            phase=7,
            product_labels=("Product",),
            batch_kind="provider_document_expansion",
            planned_document_ids=documents,
            jurisdiction=jurisdiction,
            quality_case_id=f"{batch_id}_fidelity",
            paths=BatchPaths(
                source_selection=f"{batch_id}/selection.yaml",
                extraction_manifest=f"{batch_id}/extraction.yaml",
                link_manifest=f"{batch_id}/links.yaml",
                span_specs=f"{batch_id}/spans.yaml",
                completeness_ledger=f"{batch_id}/completeness.yaml",
                formal_elements=f"{batch_id}/elements.yaml",
                output_root=f"{batch_id}/output",
            ),
        )

    old_active = make_spec("active", 1, ("document-1", "document-2"), "CH")
    new_active = make_spec("active", 1, ("document-1",), "CH")
    old_later = make_spec("later", 2, ("document-3",), "FR")
    new_later = make_spec("later", 2, ("document-2", "document-3"), "FR")
    old_plan = {"plan_id": "progressive_onboarding_plan:old", "batches": []}
    new_plan = {"plan_id": "progressive_onboarding_plan:new", "batches": []}
    old_catalogue = {
        "batches": [
            old_active.model_dump(mode="json"),
            old_later.model_dump(mode="json"),
        ]
    }
    new_catalogue = {
        "batches": [
            new_active.model_dump(mode="json"),
            new_later.model_dump(mode="json"),
        ]
    }
    plan_path = tmp_path / "plan.yaml"
    catalogue_path = tmp_path / "catalogue.yaml"
    write_yaml(plan_path, old_plan)
    write_yaml(catalogue_path, old_catalogue)
    write_yaml(
        tmp_path / "active/selection.yaml",
        {
            "batch_id": "active",
            "jurisdiction": "CH",
            "product_labels": ["Product"],
            "document_ids": ["document-1"],
        },
    )
    write_yaml(
        tmp_path / "active/links.yaml",
        {"selected_documents": [{"document_id": "document-1", "row_refs": ["workbook#row-1"]}]},
    )
    generated_plan = SimpleNamespace(model_dump=lambda **_kwargs: new_plan)
    monkeypatch.setattr(pipeline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pipeline, "ONBOARDING_PLAN_FILE", plan_path)
    monkeypatch.setattr(pipeline, "CATALOGUE_FILE", catalogue_path)
    monkeypatch.setattr(pipeline, "build_progressive_plan", lambda: generated_plan)
    monkeypatch.setattr(pipeline, "build_pipeline_catalogue", lambda: new_catalogue)

    def write_generated_catalogue() -> dict[str, Path]:
        write_yaml(catalogue_path, new_catalogue)
        return {"catalogue": catalogue_path}

    monkeypatch.setattr(pipeline, "write_pipeline_catalogue", write_generated_catalogue)

    result = pipeline._revise_batch_scope(old_active, status={"current_stage": "sources_ready"})

    revision = result["scope_revision"]
    assert revision["old_plan_id"] == "progressive_onboarding_plan:old"
    assert revision["new_plan_id"] == "progressive_onboarding_plan:new"
    assert revision["old_spec"]["planned_document_ids"] == [
        "document-1",
        "document-2",
    ]
    assert revision["new_spec"]["planned_document_ids"] == ["document-1"]
    assert revision["document_relocations"] == [
        {
            "document_id": "document-2",
            "old_batch_id": "active",
            "new_batch_id": "later",
        }
    ]
    assert revision["spec_hashes"]["old"] != revision["spec_hashes"]["new"]
    assert read_yaml(plan_path) == new_plan
    assert read_yaml(catalogue_path) == new_catalogue
    assert next((tmp_path / "active/output/scope_revisions").glob("*.yaml"))


def test_scope_revision_stage_appends_non_advancing_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ruler.ingestion.batch_pipeline as pipeline

    spec = BatchPipelineSpec(
        batch_id="scope-test",
        sequence=1,
        phase=7,
        product_labels=("Product",),
        quality_case_id="scope_test_fidelity",
        paths=BatchPaths(
            source_selection="selection.yaml",
            extraction_manifest="extraction.yaml",
            link_manifest="links.yaml",
            span_specs="spans.yaml",
            completeness_ledger="completeness.yaml",
            formal_elements="elements.yaml",
            output_root="output",
        ),
    )
    status = {
        "current_stage": "sources_ready",
        "next_stage": "scope-revision",
        "blocked_by_batch": None,
        "missing_inputs": [],
    }
    next_status = {**status, "next_stage": "extracted"}
    statuses = iter((status, next_status))
    observed: dict[str, object] = {}
    monkeypatch.setattr(pipeline, "load_batch_spec", lambda _batch_id: spec)
    monkeypatch.setattr(pipeline, "batch_status", lambda _batch_id: next(statuses))
    monkeypatch.setattr(
        pipeline,
        "_revise_batch_scope",
        lambda _spec, status: {
            "evidence_ids": ["batch_scope_revision:fixture"],
            "note": "fixture",
        },
    )

    def append_checkpoint(batch_id, stage, *, evidence_ids, note):
        observed.update(
            batch_id=batch_id,
            stage=stage,
            evidence_ids=evidence_ids,
            note=note,
        )
        return SimpleNamespace(model_dump=lambda **_kwargs: {"stage": stage.value})

    monkeypatch.setattr(pipeline, "append_progress_checkpoint", append_checkpoint)

    result = pipeline.run_batch_stage("scope-test", PipelineStage.SCOPE_REVISION)

    assert observed["stage"] == OnboardingStage.SCOPE_REVISION
    assert observed["evidence_ids"] == ("batch_scope_revision:fixture",)
    assert result["checkpoint"] == {"stage": "scope_revision"}
    assert result["next"] == next_status
