# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Portable, stage-gated construction pipeline for progressive KB batches.

The pipeline deliberately separates source selection, extraction, completeness,
formalization, deterministic checks, generative checks, coherence, and publication.
Every batch uses the same repository-relative input contract, so no knowledge of an
interactive development session is required to run it in another environment.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from itertools import product
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.ingestion.adapters import adapt_legacy_source_manifests
from ruler.ingestion.contracts import (
    AutomatedGateEvidence,
    CompiledArtifact,
    FormalElementAnnotation,
    FormalizationCandidate,
    IngestionBundle,
    SourceRegistryEntry,
    SourceVersion,
    canonical_sha256,
    stable_id,
)
from ruler.ingestion.progressive_onboarding import (
    ONBOARDING_PLAN_FILE,
    OnboardingStage,
    append_progress_checkpoint,
    build_progressive_plan,
    effective_onboarding_stage,
    load_progress_events,
    reference_release_is_published,
)
from ruler.ingestion.release import build_corpus_snapshot, build_kb_release, publish_kb_release
from ruler.io import read_yaml, repo_relative_posix, write_text, write_yaml
from ruler.io import stable_hash
from ruler.kb.repository import KnowledgeRepository, ProjectionRequest, ReleasedAssertion
from ruler.paths import BUILD_DIR, DATA_DIR, KB_DIR, REPO_ROOT
from ruler.runtime.generative_quality import (
    EvaluationResult,
    load_quality_catalogue,
    quality_case_cache_key,
    resolve_quality_consensus,
    run_quality_case,
    write_consensus_bundle,
)
from ruler.schemas import PolicyClause, PolicyRule, ProductFeature

PIPELINE_ROOT = DATA_DIR / "operations" / "progressive_onboarding"
CATALOGUE_FILE = PIPELINE_ROOT / "pipeline_catalogue.yaml"
CATALOGUE_MARKDOWN = PIPELINE_ROOT / "pipeline_catalogue.md"
BATCH_ROOT = PIPELINE_ROOT / "batches"
RELEASE_ROOT = KB_DIR / "releases" / "product_onboarding"
QUALITY_ROOT = BUILD_DIR / "progressive_onboarding_quality"
QUALITY_INPUT_BYTE_TIERS = (300_000, 600_000, 1_200_000)


class PipelineStage(StrEnum):
    """Legal, individually checkpointed stages exposed by the portable CLI."""

    STATUS = "status"
    PLANNED = "planned"
    SOURCES_READY = "sources-ready"
    EXTRACTED = "extracted"
    COMPLETENESS_VERIFIED = "completeness-verified"
    FORMALIZED = "formalized"
    DETERMINISTIC_VERIFIED = "deterministic-verified"
    GENERATIVE_VERIFIED = "generative-verified"
    COHERENCE_VERIFIED = "coherence-verified"
    PUBLISHED = "published"
    REVISION = "revision"
    SOURCE_REVISION = "source-revision"
    SCOPE_REVISION = "scope-revision"


STAGE_TO_CHECKPOINT = {
    PipelineStage.PLANNED: OnboardingStage.PLANNED,
    PipelineStage.SOURCES_READY: OnboardingStage.SOURCES_READY,
    PipelineStage.EXTRACTED: OnboardingStage.EXTRACTED,
    PipelineStage.COMPLETENESS_VERIFIED: OnboardingStage.COMPLETENESS_VERIFIED,
    PipelineStage.FORMALIZED: OnboardingStage.FORMALIZED,
    PipelineStage.DETERMINISTIC_VERIFIED: OnboardingStage.DETERMINISTIC_VERIFIED,
    PipelineStage.GENERATIVE_VERIFIED: OnboardingStage.GENERATIVE_VERIFIED,
    PipelineStage.COHERENCE_VERIFIED: OnboardingStage.COHERENCE_VERIFIED,
    PipelineStage.PUBLISHED: OnboardingStage.PUBLISHED,
}


class BatchPaths(BaseModel):
    """Repository-relative inputs and outputs shared by every batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_selection: str
    extraction_manifest: str
    link_manifest: str
    span_specs: str
    completeness_ledger: str
    formal_elements: str
    output_root: str


class BatchPipelineSpec(BaseModel):
    """One portable batch definition with no machine-specific paths."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    batch_id: str
    sequence: int = Field(ge=1)
    phase: int = Field(ge=1)
    product_labels: tuple[str, ...] = Field(min_length=1, max_length=3)
    maximum_documents: int = Field(default=3, ge=1, le=3)
    batch_kind: Literal["product_family", "provider_document_expansion"] = Field(
        default="product_family", exclude_if=lambda value: value == "product_family"
    )
    planned_document_ids: tuple[str, ...] = Field(
        default=(), max_length=3, exclude_if=lambda value: not value
    )
    provider: str | None = None
    jurisdiction: str = "CH"
    product_family: str | None = None
    quality_case_id: str
    paths: BatchPaths
    reference_release: str | None = None


class DocumentBatchPaths(BaseModel):
    """Repository-relative paths for a corpus with no commercial catalogue."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    source_manifest: str
    extraction_manifest: str
    span_specs: str
    formal_elements: str
    output_root: str


class DocumentBatchPipelineSpec(BaseModel):
    """Portable batch contract for document-only domain corpora."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[2] = 2
    batch_id: str
    sequence: int = Field(ge=1)
    domain_id: str
    corpus_id: str
    planned_document_ids: tuple[str, ...] = Field(min_length=1)
    maximum_documents: int = Field(default=3, ge=1)
    jurisdiction: str | None = None
    quality_case_id: str
    record_parser_types: tuple[str, ...] = ()
    paths: DocumentBatchPaths
    reference_release: str | None = None

    @model_validator(mode="after")
    def document_limit_is_respected(self) -> "DocumentBatchPipelineSpec":
        if len(self.planned_document_ids) > self.maximum_documents:
            raise ValueError("planned documents exceed maximum_documents")
        return self


class SpanSpec(BaseModel):
    """Stable source range used to reconstruct exact source text."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    span_id: str
    document_id: str
    artifact: str
    line_start: int = Field(ge=1)
    line_end: int = Field(ge=1)
    section: str

    @model_validator(mode="after")
    def ordered_lines(self) -> "SpanSpec":
        if self.line_end < self.line_start:
            raise ValueError("span line_end must be greater than or equal to line_start")
        return self


class FormalElementSpec(BaseModel):
    """Typed semantic record plus its exact spans and bilingual explanation."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    record_type: Literal["feature", "clause", "rule"]
    record: dict[str, Any]
    source_span_ids: tuple[str, ...] = Field(min_length=1)
    source_language: str
    source_language_gloss: str
    controlled_english: str
    terminology_decision_ids: tuple[str, ...] = ()
    option_ids: tuple[str, ...] = ()
    option_group_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    option_group_required: bool = Field(default=False, exclude_if=lambda value: not value)
    option_group_product_ids: tuple[str, ...] = Field(
        default=(), exclude_if=lambda value: not value
    )
    dependency_only: bool = Field(default=False, exclude_if=lambda value: not value)
    dependencies: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid_option_group(self) -> "FormalElementSpec":
        """Require one explicit member option for every declared option group."""
        if self.option_group_required and self.option_group_id is None:
            raise ValueError("option_group_required requires option_group_id")
        if self.option_group_id is not None and len(self.option_ids) != 1:
            raise ValueError("option-group elements require exactly one option_id")
        if self.option_group_product_ids and self.option_group_id is None:
            raise ValueError("option_group_product_ids requires option_group_id")
        return self


class CompletenessDisposition(BaseModel):
    """Explicit keep/defer/omit decision for one structural policy element."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    structural_element_id: str
    disposition: Literal["keep", "defer", "omit"]
    recommendation_impact: str
    rationale: str
    source_span_ids: tuple[str, ...] = ()


class CompletenessLedger(BaseModel):
    """Coverage proof required before formalization can begin."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    batch_id: str
    document_ids: tuple[str, ...] = Field(min_length=1, max_length=3)
    dispositions: tuple[CompletenessDisposition, ...] = Field(min_length=1)
    unresolved_cross_references: tuple[str, ...] = ()
    verified: Literal[True]

    @model_validator(mode="after")
    def material_omissions_are_explained(self) -> "CompletenessLedger":
        for item in self.dispositions:
            if item.disposition == "omit" and not item.recommendation_impact.strip():
                raise ValueError("omitted elements require recommendation-impact analysis")
        return self


def build_pipeline_catalogue() -> dict[str, Any]:
    """Derive all batch contracts and exact commands from the canonical rollout plan."""
    plan = build_progressive_plan()
    batches = []
    for sequence, batch in enumerate(plan.batches, start=1):
        root = f"data/operations/progressive_onboarding/batches/{batch.batch_id}"
        batches.append(
            BatchPipelineSpec(
                batch_id=batch.batch_id,
                sequence=sequence,
                phase=batch.phase,
                product_labels=batch.product_labels,
                maximum_documents=batch.maximum_documents,
                batch_kind=batch.batch_kind,
                planned_document_ids=batch.planned_document_ids,
                jurisdiction=batch.jurisdiction,
                quality_case_id=f"{batch.batch_id.replace('-', '_')}_fidelity",
                paths=BatchPaths(
                    source_selection=f"{root}/input/source_selection.yaml",
                    extraction_manifest=f"{root}/input/extraction_manifest.yaml",
                    link_manifest=f"{root}/input/link_manifest.yaml",
                    span_specs=f"{root}/input/span_specs.yaml",
                    completeness_ledger=f"{root}/input/completeness_ledger.yaml",
                    formal_elements=f"{root}/input/formal_elements.yaml",
                    output_root=f"{root}/output",
                ),
                reference_release=None,
            ).model_dump(mode="json")
        )
    return {
        "schema_version": 1,
        "purpose": "Portable stage-by-stage KB construction for every progressive onboarding batch.",
        "setup": ["uv sync --extra dev", "uv run ruler validate batch-pipeline"],
        "entrypoint": "uv run ruler workflow product-batch-pipeline --batch-id <batch-id> --stage <stage>",
        "stage_order": [
            stage.value
            for stage in PipelineStage
            if stage
            not in {
                PipelineStage.STATUS,
                PipelineStage.REVISION,
                PipelineStage.SOURCE_REVISION,
                PipelineStage.SCOPE_REVISION,
            }
        ],
        "constraints": {
            "maximum_concurrent_batches": 1,
            "maximum_products_per_batch": 3,
            "maximum_documents_per_batch": 3,
            "publication_requires_current_hash_generative_consensus": True,
            "candidate_or_ungated_content_enters_runtime_truth": False,
        },
        "batches": batches,
    }


def write_pipeline_catalogue() -> dict[str, Path]:
    """Write the machine catalogue, human run table, and copy-ready input templates."""
    payload = build_pipeline_catalogue()
    write_yaml(CATALOGUE_FILE, payload)
    rows = []
    for batch in payload["batches"]:
        labels = ", ".join(batch["product_labels"])
        rows.append(f"| `{batch['batch_id']}` | {batch['sequence']} | {labels} | `status` |")
    write_text(
        CATALOGUE_MARKDOWN,
        "# Portable progressive KB construction\n\n"
        "Start from a clean checkout; no prior conversation or local build output is required.\n\n"
        "```bash\nuv sync --extra dev\nuv run ruler validate batch-pipeline\n"
        "uv run ruler workflow product-batch-pipeline --batch-id phase-01-batch-01 --stage status\n```\n\n"
        "Run exactly one lifecycle stage at a time. The status output lists missing inputs and the next command.\n\n"
        "| Batch | Order | Product labels | First command |\n|---|---:|---|---|\n"
        + "\n".join(rows)
        + "\n",
    )
    template_root = PIPELINE_ROOT / "templates"
    write_yaml(
        template_root / "source_selection.example.yaml",
        {
            "batch_id": "phase-XX-batch-YY",
            "provider": "provider-id",
            "jurisdiction": "CH",
            "product_family": "controlled-family-id",
            "product_labels": ["workbook label"],
            "document_ids": ["stable-document-id"],
            "selection_rationale": "Why these documents cover this bounded batch.",
        },
    )
    write_yaml(
        template_root / "span_specs.example.yaml",
        [
            {
                "span_id": "stable-span-id",
                "document_id": "stable-document-id",
                "artifact": "data/sources/extracted/provider/document/docling.md",
                "line_start": 1,
                "line_end": 10,
                "section": "Exact heading",
            }
        ],
    )
    write_yaml(
        template_root / "formal_elements.example.yaml",
        {
            "batch_id": "phase-XX-batch-YY",
            "elements": [
                {
                    "record_type": "clause",
                    "record": {"replace": "with a complete PolicyClause payload"},
                    "source_span_ids": ["stable-span-id"],
                    "source_language": "fr",
                    "source_language_gloss": "Controlled source-language explanation.",
                    "controlled_english": "Controlled English explanation.",
                    "terminology_decision_ids": [],
                }
            ],
        },
    )
    write_yaml(
        template_root / "completeness_ledger.example.yaml",
        {
            "batch_id": "phase-XX-batch-YY",
            "document_ids": ["stable-document-id"],
            "dispositions": [
                {
                    "structural_element_id": "section-id",
                    "disposition": "keep",
                    "recommendation_impact": "Material scope definition.",
                    "rationale": "Preserve in formal truth.",
                    "source_span_ids": ["stable-span-id"],
                }
            ],
            "unresolved_cross_references": [],
            "verified": True,
        },
    )
    return {
        "catalogue": CATALOGUE_FILE,
        "markdown": CATALOGUE_MARKDOWN,
        "templates": template_root,
    }


def load_batch_spec(batch_id: str) -> BatchPipelineSpec:
    """Load one batch from the generated catalogue and reject unknown identifiers."""
    payload = read_yaml(CATALOGUE_FILE) if CATALOGUE_FILE.exists() else build_pipeline_catalogue()
    for item in payload["batches"]:
        if item["batch_id"] == batch_id:
            return BatchPipelineSpec.model_validate(item)
    raise ValueError(f"unknown progressive onboarding batch: {batch_id}")


def batch_status(batch_id: str) -> dict[str, Any]:
    """Report current stage, exact missing inputs, and the next copy-ready command."""
    spec = load_batch_spec(batch_id)
    events = [event for event in load_progress_events() if event.batch_id == batch_id]
    effective = effective_onboarding_stage(events)
    reference_published = reference_release_is_published(
        batch_id,
        catalogue_path=CATALOGUE_FILE,
        repository_root=REPO_ROOT,
    )
    if reference_published:
        effective = OnboardingStage.PUBLISHED
    expected = _next_pipeline_stage(effective)
    if effective == OnboardingStage.SOURCES_READY and _scope_revision_required(batch_id):
        expected = PipelineStage.SCOPE_REVISION
    if effective == OnboardingStage.COMPLETENESS_VERIFIED and _source_revision_required(
        spec, events
    ):
        expected = PipelineStage.SOURCE_REVISION
    revisable = {
        OnboardingStage.DETERMINISTIC_VERIFIED,
        OnboardingStage.GENERATIVE_VERIFIED,
        OnboardingStage.COHERENCE_VERIFIED,
    }
    artifacts_are_current = (
        _deterministic_artifacts_are_current(spec) if effective in revisable else True
    )
    if effective in revisable and not artifacts_are_current:
        expected = PipelineStage.REVISION
    elif effective == OnboardingStage.DETERMINISTIC_VERIFIED and _current_failed_quality_result_ids(
        spec
    ):
        expected = PipelineStage.REVISION
    required = _required_paths(spec, expected)
    missing = [repo_relative_posix(path) for path in required if not path.is_file()]
    blocker = None if reference_published else _prior_batch_blocker(spec)
    return {
        "batch_id": batch_id,
        "sequence": spec.sequence,
        "product_labels": list(spec.product_labels),
        "batch_kind": spec.batch_kind,
        "planned_document_ids": list(spec.planned_document_ids),
        "current_stage": effective.value if effective else None,
        "next_stage": expected.value if expected else None,
        "ready": not missing and blocker is None,
        "blocked_by_batch": blocker,
        "missing_inputs": missing,
        "next_command": (
            f"uv run ruler workflow product-batch-pipeline --batch-id {batch_id} --stage {expected.value}"
            if expected and blocker is None
            else None
        ),
        "input_templates": "data/operations/progressive_onboarding/templates",
        "runbook": "docs/operations/progressive_product_onboarding_runbook.md",
        "reference_release": spec.reference_release if reference_published else None,
    }


def _prior_batch_blocker(spec: BatchPipelineSpec) -> str | None:
    """Return the earliest unfinished predecessor, enforcing one active batch."""
    catalogue = read_yaml(CATALOGUE_FILE)
    events = load_progress_events()
    for prior in catalogue["batches"]:
        if prior["sequence"] >= spec.sequence:
            break
        if reference_release_is_published(
            prior["batch_id"],
            catalogue_path=CATALOGUE_FILE,
            repository_root=REPO_ROOT,
        ):
            continue
        prior_events = [event for event in events if event.batch_id == prior["batch_id"]]
        latest = effective_onboarding_stage(prior_events)
        explicitly_blocked = bool(
            prior_events and prior_events[-1].stage == OnboardingStage.BLOCKED
        )
        if latest != OnboardingStage.PUBLISHED and not explicitly_blocked:
            return prior["batch_id"]
    return None


def run_batch_stage(
    batch_id: str,
    stage: PipelineStage,
    *,
    model: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run exactly one legal stage and append one evidence-bound checkpoint."""
    if stage == PipelineStage.STATUS or dry_run:
        return {**batch_status(batch_id), "dry_run": dry_run}
    spec = load_batch_spec(batch_id)
    status = batch_status(batch_id)
    return dispatch_batch_stage(batch_id, stage, spec=spec, status=status, model=model)


def dispatch_batch_stage(
    batch_id: str,
    stage: PipelineStage,
    *,
    spec: BatchPipelineSpec,
    status: dict[str, Any],
    model: str | None = None,
) -> dict[str, Any]:
    """Shared dispatch after the ordered spec/readiness reads.

    Consume the observed readiness without another pre-dispatch read. Callers
    must serialize access to the workspace ledger, as for run_batch_stage.
    """
    if stage == PipelineStage.REVISION:
        if status["blocked_by_batch"]:
            raise ValueError(f"{batch_id} is blocked by unfinished {status['blocked_by_batch']}")
        evidence = _revise_after_failed_quality(spec, status=status)
        checkpoint = append_progress_checkpoint(
            batch_id,
            OnboardingStage.REVISION,
            evidence_ids=tuple(evidence["evidence_ids"]),
            note=evidence["note"],
        )
        return {
            **evidence,
            "checkpoint": checkpoint.model_dump(mode="json"),
            "next": batch_status(batch_id),
        }
    if stage == PipelineStage.SOURCE_REVISION:
        if status["blocked_by_batch"]:
            raise ValueError(f"{batch_id} is blocked by unfinished {status['blocked_by_batch']}")
        if status["next_stage"] != PipelineStage.SOURCE_REVISION.value:
            raise ValueError("source revision requires unamended source-input drift")
        if status["missing_inputs"]:
            raise ValueError(
                f"{batch_id}/{stage.value} missing inputs: " + ", ".join(status["missing_inputs"])
            )
        evidence = _revise_source_provenance(spec, status=status)
        checkpoint = append_progress_checkpoint(
            batch_id,
            OnboardingStage.SOURCE_REVISION,
            evidence_ids=tuple(evidence["evidence_ids"]),
            note=evidence["note"],
        )
        return {
            **evidence,
            "checkpoint": checkpoint.model_dump(mode="json"),
            "next": batch_status(batch_id),
        }
    if stage == PipelineStage.SCOPE_REVISION:
        if status["blocked_by_batch"]:
            raise ValueError(f"{batch_id} is blocked by unfinished {status['blocked_by_batch']}")
        if status["next_stage"] != PipelineStage.SCOPE_REVISION.value:
            raise ValueError("scope revision requires generated plan/spec drift at sources_ready")
        if status["missing_inputs"]:
            raise ValueError(
                f"{batch_id}/{stage.value} missing inputs: " + ", ".join(status["missing_inputs"])
            )
        evidence = _revise_batch_scope(spec, status=status)
        checkpoint = append_progress_checkpoint(
            batch_id,
            OnboardingStage.SCOPE_REVISION,
            evidence_ids=tuple(evidence["evidence_ids"]),
            note=evidence["note"],
        )
        return {
            **evidence,
            "checkpoint": checkpoint.model_dump(mode="json"),
            "next": batch_status(batch_id),
        }
    if status["next_stage"] != stage.value:
        raise ValueError(f"next legal stage for {batch_id} is {status['next_stage']}")
    if status["blocked_by_batch"]:
        raise ValueError(f"{batch_id} is blocked by unfinished {status['blocked_by_batch']}")
    missing = status["missing_inputs"]
    if missing:
        raise ValueError(f"{batch_id}/{stage.value} missing inputs: {', '.join(missing)}")

    if stage == PipelineStage.PLANNED:
        evidence = {
            "evidence_ids": [stable_id("batch_pipeline_plan", spec.model_dump(mode="json"))],
            "note": "Portable bounded batch contract registered; no source work started.",
        }
    elif stage == PipelineStage.SOURCES_READY:
        evidence = _validate_source_selection(spec)
    elif stage == PipelineStage.EXTRACTED:
        evidence = _validate_extraction(spec)
    elif stage == PipelineStage.COMPLETENESS_VERIFIED:
        evidence = _validate_completeness(spec)
    elif stage == PipelineStage.FORMALIZED:
        evidence = _prepare_formalization(spec)
    elif stage == PipelineStage.DETERMINISTIC_VERIFIED:
        evidence = _validate_prepared_bundle(spec)
    elif stage == PipelineStage.GENERATIVE_VERIFIED:
        evidence = _run_generative_gate(spec, model=model)
    elif stage == PipelineStage.COHERENCE_VERIFIED:
        evidence = _validate_release_coherence(spec)
    elif stage == PipelineStage.PUBLISHED:
        evidence = _publish_release(spec)
    else:  # pragma: no cover - enum exhaustiveness
        raise ValueError(f"unsupported pipeline stage: {stage}")
    checkpoint = append_progress_checkpoint(
        batch_id,
        STAGE_TO_CHECKPOINT[stage],
        evidence_ids=tuple(evidence["evidence_ids"]),
        note=evidence["note"],
    )
    return {
        **evidence,
        "checkpoint": checkpoint.model_dump(mode="json"),
        "next": batch_status(batch_id),
    }


def _next_pipeline_stage(previous: OnboardingStage | None) -> PipelineStage | None:
    mapping = {
        OnboardingStage.PLANNED: PipelineStage.SOURCES_READY,
        OnboardingStage.SOURCES_READY: PipelineStage.EXTRACTED,
        OnboardingStage.EXTRACTED: PipelineStage.COMPLETENESS_VERIFIED,
        OnboardingStage.COMPLETENESS_VERIFIED: PipelineStage.FORMALIZED,
        OnboardingStage.FORMALIZED: PipelineStage.DETERMINISTIC_VERIFIED,
        OnboardingStage.DETERMINISTIC_VERIFIED: PipelineStage.GENERATIVE_VERIFIED,
        OnboardingStage.GENERATIVE_VERIFIED: PipelineStage.COHERENCE_VERIFIED,
        OnboardingStage.COHERENCE_VERIFIED: PipelineStage.PUBLISHED,
        OnboardingStage.PUBLISHED: None,
    }
    return PipelineStage.PLANNED if previous is None else mapping.get(previous)


def _required_paths(spec: BatchPipelineSpec, stage: PipelineStage | None) -> list[Path]:
    if stage is None:
        return []
    paths = spec.paths
    mapping = {
        PipelineStage.SOURCES_READY: [paths.source_selection, paths.link_manifest],
        PipelineStage.EXTRACTED: [paths.extraction_manifest],
        PipelineStage.COMPLETENESS_VERIFIED: [paths.completeness_ledger, paths.span_specs],
        PipelineStage.FORMALIZED: [paths.formal_elements],
        PipelineStage.DETERMINISTIC_VERIFIED: [f"{paths.output_root}/preparation.yaml"],
        PipelineStage.GENERATIVE_VERIFIED: [f"{paths.output_root}/quality_cases.yaml"],
        PipelineStage.COHERENCE_VERIFIED: [f"{paths.output_root}/quality_consensus.yaml"],
        PipelineStage.PUBLISHED: [f"{paths.output_root}/coherence.yaml"],
        PipelineStage.REVISION: [
            paths.completeness_ledger,
            paths.span_specs,
            paths.formal_elements,
        ],
        PipelineStage.SOURCE_REVISION: [
            paths.source_selection,
            paths.link_manifest,
            paths.extraction_manifest,
            paths.completeness_ledger,
            paths.span_specs,
        ],
        PipelineStage.SCOPE_REVISION: [paths.source_selection, paths.link_manifest],
    }
    return [REPO_ROOT / path for path in mapping.get(stage, [])]


def _validate_source_selection(spec: BatchPipelineSpec) -> dict[str, Any]:
    selection = read_yaml(REPO_ROOT / spec.paths.source_selection)
    _validate_jurisdiction(
        expected=spec.jurisdiction,
        observed=selection.get("jurisdiction"),
        boundary="source selection",
    )
    document_ids = selection.get("document_ids", [])
    if selection.get("batch_id") != spec.batch_id or not document_ids:
        raise ValueError("source selection must identify this batch and at least one document")
    if len(document_ids) > spec.maximum_documents:
        raise ValueError("source selection exceeds the batch document cap")
    if spec.planned_document_ids and tuple(document_ids) != spec.planned_document_ids:
        raise ValueError("source selection differs from the expansion plan documents")
    if tuple(selection.get("product_labels", ())) != spec.product_labels:
        raise ValueError("source selection product labels differ from the batch contract")
    link_manifest = read_yaml(REPO_ROOT / spec.paths.link_manifest)
    _validate_jurisdiction(
        expected=spec.jurisdiction,
        observed=link_manifest.get("jurisdiction"),
        boundary="link manifest",
    )
    links = link_manifest.get("selected_documents", [])
    if {item.get("document_id") for item in links} != set(document_ids):
        raise ValueError("link manifest must contain exactly the selected documents")
    for item in links:
        _validate_jurisdiction(
            expected=spec.jurisdiction,
            observed=item.get("jurisdiction"),
            boundary=f"selected link {item.get('document_id', '<unknown>')}",
        )
        if not item.get("workbook_rows") and not item.get("row_refs"):
            raise ValueError(f"selected link lacks workbook rows: {item['document_id']}")
    evidence_id = _source_selection_evidence_id(spec)
    return {"evidence_ids": [evidence_id], "note": "Bounded source selection validated."}


def _validate_extraction(spec: BatchPipelineSpec) -> dict[str, Any]:
    selection = read_yaml(REPO_ROOT / spec.paths.source_selection)
    _validate_jurisdiction(
        expected=spec.jurisdiction,
        observed=selection.get("jurisdiction"),
        boundary="source selection",
    )
    manifest = read_yaml(REPO_ROOT / spec.paths.extraction_manifest)
    _validate_jurisdiction(
        expected=spec.jurisdiction,
        observed=manifest.get("jurisdiction"),
        boundary="extraction manifest",
    )
    documents = manifest.get("documents", [])
    selected = set(selection["document_ids"])
    if {item["document_id"] for item in documents} != selected:
        raise ValueError("extraction manifest must contain no documents outside the selection")
    extracted = {item["document_id"] for item in documents if item.get("status") == "extracted"}
    if selected != extracted:
        raise ValueError(
            "extraction manifest must contain exactly the selected extracted documents"
        )
    for item in documents:
        _validate_jurisdiction(
            expected=spec.jurisdiction,
            observed=item.get("jurisdiction"),
            boundary=f"extracted document {item.get('document_id', '<unknown>')}",
        )
        if item["document_id"] in selected and not item.get("raw_sha256"):
            raise ValueError(f"extracted document lacks raw hash: {item['document_id']}")
        if item["document_id"] in selected and not item.get("row_refs"):
            raise ValueError(f"extracted document lacks workbook row refs: {item['document_id']}")
    return {
        "evidence_ids": [_extraction_evidence_id(spec)],
        "note": "All selected documents are extracted and content-hash pinned.",
    }


def _validate_jurisdiction(*, expected: str, observed: Any, boundary: str) -> None:
    """Reject an explicit source jurisdiction that crosses the batch boundary."""
    if observed is None or not str(observed).strip():
        return
    if str(observed).strip().upper() != expected.strip().upper():
        raise ValueError(
            f"{boundary} jurisdiction {observed!r} does not match batch jurisdiction {expected!r}"
        )


def _catalogue_specs(payload: dict[str, Any]) -> dict[str, BatchPipelineSpec]:
    """Normalize generated catalogue entries before comparing governed scope."""
    return {
        item["batch_id"]: BatchPipelineSpec.model_validate(item)
        for item in payload.get("batches", ())
    }


def _planned_document_partition(
    specs: dict[str, BatchPipelineSpec],
) -> dict[str, str]:
    """Return the unique owning batch for every explicitly planned document."""
    owners: dict[str, str] = {}
    for batch_id, spec in specs.items():
        for document_id in spec.planned_document_ids:
            if previous := owners.get(document_id):
                raise ValueError(
                    f"planned document {document_id!r} occurs in both {previous!r} and {batch_id!r}"
                )
            owners[document_id] = batch_id
    return owners


def _scope_drift(batch_id: str) -> dict[str, Any] | None:
    """Describe active-batch scope drift between checked-in and generated contracts."""
    if not ONBOARDING_PLAN_FILE.is_file() or not CATALOGUE_FILE.is_file():
        return None
    old_plan = read_yaml(ONBOARDING_PLAN_FILE)
    old_catalogue = read_yaml(CATALOGUE_FILE)
    new_plan = build_progressive_plan().model_dump(mode="json")
    new_catalogue = build_pipeline_catalogue()
    old_specs = _catalogue_specs(old_catalogue)
    new_specs = _catalogue_specs(new_catalogue)
    if batch_id not in old_specs:
        raise ValueError(f"checked-in catalogue lacks active batch {batch_id!r}")
    if batch_id not in new_specs:
        raise ValueError(f"generated plan removes active batch {batch_id!r}")
    old_spec = old_specs[batch_id]
    new_spec = new_specs[batch_id]
    old_spec_payload = old_spec.model_dump(mode="json")
    new_spec_payload = new_spec.model_dump(mode="json")
    if canonical_sha256(old_spec_payload) == canonical_sha256(new_spec_payload):
        return None
    return {
        "old_plan": old_plan,
        "new_plan": new_plan,
        "old_catalogue": old_catalogue,
        "new_catalogue": new_catalogue,
        "old_specs": old_specs,
        "new_specs": new_specs,
        "old_spec": old_spec,
        "new_spec": new_spec,
    }


def _scope_revision_required(batch_id: str) -> bool:
    """Expose scope remediation only for generated drift affecting this batch."""
    return _scope_drift(batch_id) is not None


def _revise_batch_scope(spec: BatchPipelineSpec, *, status: dict[str, Any]) -> dict[str, Any]:
    """Accept a content-bound document repartition without advancing the batch."""
    if status["current_stage"] != OnboardingStage.SOURCES_READY.value:
        raise ValueError("scope revision requires current stage sources_ready")
    drift = _scope_drift(spec.batch_id)
    if drift is None:
        raise ValueError("scope revision requires generated plan/spec drift")

    old_owners = _planned_document_partition(drift["old_specs"])
    new_owners = _planned_document_partition(drift["new_specs"])
    if set(old_owners) != set(new_owners):
        missing = sorted(set(old_owners) - set(new_owners))
        added = sorted(set(new_owners) - set(old_owners))
        raise ValueError(
            "scope revision must preserve the planned-document partition; "
            f"orphaned={missing}, unreviewed={added}"
        )

    changed_batch_ids = sorted(
        batch_id
        for batch_id in set(drift["old_specs"]) & set(drift["new_specs"])
        if canonical_sha256(drift["old_specs"][batch_id].model_dump(mode="json"))
        != canonical_sha256(drift["new_specs"][batch_id].model_dump(mode="json"))
    )
    events = load_progress_events()
    for batch_id in changed_batch_ids:
        if batch_id == spec.batch_id:
            continue
        effective = effective_onboarding_stage(
            [event for event in events if event.batch_id == batch_id]
        )
        if effective is not None and effective != OnboardingStage.PLANNED:
            raise ValueError(
                f"scope revision cannot alter already-started batch {batch_id!r} "
                f"at stage {effective.value!r}"
            )

    new_spec: BatchPipelineSpec = drift["new_spec"]
    source_evidence = _validate_source_selection(new_spec)
    changed_documents = sorted(
        set(drift["old_spec"].planned_document_ids) | set(new_spec.planned_document_ids)
    )
    relocations = [
        {
            "document_id": document_id,
            "old_batch_id": old_owners[document_id],
            "new_batch_id": new_owners[document_id],
        }
        for document_id in changed_documents
        if old_owners[document_id] != new_owners[document_id]
    ]
    payload = {
        "batch_id": spec.batch_id,
        "old_plan_id": drift["old_plan"].get("plan_id"),
        "new_plan_id": drift["new_plan"].get("plan_id"),
        "old_expansion_plan_id": drift["old_plan"].get("expansion_plan_id"),
        "new_expansion_plan_id": drift["new_plan"].get("expansion_plan_id"),
        "plan_hashes": {
            "old": canonical_sha256(drift["old_plan"]),
            "new": canonical_sha256(drift["new_plan"]),
        },
        "catalogue_hashes": {
            "old": canonical_sha256(drift["old_catalogue"]),
            "new": canonical_sha256(drift["new_catalogue"]),
        },
        "spec_hashes": {
            "old": canonical_sha256(drift["old_spec"].model_dump(mode="json")),
            "new": canonical_sha256(new_spec.model_dump(mode="json")),
        },
        "old_spec": {
            "jurisdiction": drift["old_spec"].jurisdiction,
            "product_labels": list(drift["old_spec"].product_labels),
            "planned_document_ids": list(drift["old_spec"].planned_document_ids),
        },
        "new_spec": {
            "jurisdiction": new_spec.jurisdiction,
            "product_labels": list(new_spec.product_labels),
            "planned_document_ids": list(new_spec.planned_document_ids),
        },
        "document_partition_hashes": {
            "old": canonical_sha256(old_owners),
            "new": canonical_sha256(new_owners),
        },
        "active_document_set_hashes": {
            "old": canonical_sha256(sorted(drift["old_spec"].planned_document_ids)),
            "new": canonical_sha256(sorted(new_spec.planned_document_ids)),
        },
        "document_relocations": relocations,
        "changed_batch_ids": changed_batch_ids,
        "replacement_source_evidence_ids": source_evidence["evidence_ids"],
    }
    revision_id = stable_id("batch_scope_revision", payload)
    revision = {"revision_id": revision_id, **payload}
    output = REPO_ROOT / new_spec.paths.output_root
    write_yaml(
        output / "scope_revisions" / f"{revision_id.split(':', 1)[1]}.yaml",
        revision,
    )
    write_yaml(ONBOARDING_PLAN_FILE, drift["new_plan"])
    write_pipeline_catalogue()
    return {
        "evidence_ids": [revision_id],
        "scope_revision": revision,
        "note": "Generated batch scope and source selection were revalidated without advancing the batch.",
    }


def _validate_completeness(spec: BatchPipelineSpec) -> dict[str, Any]:
    ledger = CompletenessLedger.model_validate(
        read_yaml(REPO_ROOT / spec.paths.completeness_ledger)
    )
    if ledger.batch_id != spec.batch_id:
        raise ValueError("completeness ledger batch_id mismatch")
    selection = read_yaml(REPO_ROOT / spec.paths.source_selection)
    if set(ledger.document_ids) != set(selection["document_ids"]):
        raise ValueError("completeness ledger documents differ from the source selection")
    deferred_element_ids = {
        item.structural_element_id for item in ledger.dispositions if item.disposition == "defer"
    }
    invalid_cross_references = sorted(
        set(ledger.unresolved_cross_references) - deferred_element_ids
    )
    if invalid_cross_references:
        raise ValueError(
            "unresolved cross-references must name deferred structural elements: "
            f"{', '.join(invalid_cross_references)}"
        )
    spans = [SpanSpec.model_validate(item) for item in read_yaml(REPO_ROOT / spec.paths.span_specs)]
    known_spans = {item.span_id for item in spans}
    referenced = {span for item in ledger.dispositions for span in item.source_span_ids}
    if referenced != known_spans:
        raise ValueError(
            "every declared span must be accounted for exactly by completeness dispositions"
        )
    return {
        "evidence_ids": [_completeness_evidence_id(spec)],
        "note": "Every inventoried structural element has an explicit disposition.",
    }


def _source_selection_evidence_id(spec: BatchPipelineSpec) -> str:
    """Bind source readiness to both selection and link provenance."""
    payload = {
        "source_selection": read_yaml(REPO_ROOT / spec.paths.source_selection),
        "link_manifest": read_yaml(REPO_ROOT / spec.paths.link_manifest),
    }
    return stable_id("source_selection", payload)


def _extraction_evidence_id(spec: BatchPipelineSpec) -> str:
    return stable_id("batch_extraction", read_yaml(REPO_ROOT / spec.paths.extraction_manifest))


def _completeness_evidence_id(spec: BatchPipelineSpec) -> str:
    """Bind completeness to both dispositions and their exact span inventory."""
    payload = {
        "completeness_ledger": read_yaml(REPO_ROOT / spec.paths.completeness_ledger),
        "span_specs": read_yaml(REPO_ROOT / spec.paths.span_specs),
    }
    return stable_id("completeness_ledger", payload)


def _source_input_hashes(spec: BatchPipelineSpec) -> dict[str, str]:
    paths = {
        "source_selection": spec.paths.source_selection,
        "link_manifest": spec.paths.link_manifest,
        "extraction_manifest": spec.paths.extraction_manifest,
        "completeness_ledger": spec.paths.completeness_ledger,
        "span_specs": spec.paths.span_specs,
    }
    return {name: canonical_sha256(read_yaml(REPO_ROOT / path)) for name, path in paths.items()}


def _formalization_input_hashes(spec: BatchPipelineSpec) -> dict[str, str]:
    """Bind prepared artifacts to every source-owned formalization input."""
    paths = {
        "completeness_ledger": spec.paths.completeness_ledger,
        "span_specs": spec.paths.span_specs,
        "formal_elements": spec.paths.formal_elements,
    }
    return {name: canonical_sha256(read_yaml(REPO_ROOT / path)) for name, path in paths.items()}


def _source_revision_required(spec: BatchPipelineSpec, events: list[Any]) -> bool:
    """Detect source-input drift not covered by an append-only amendment."""
    source_revision = next(
        (event for event in reversed(events) if event.stage == OnboardingStage.SOURCE_REVISION),
        None,
    )
    if source_revision:
        output = REPO_ROOT / spec.paths.output_root
        for evidence_id in source_revision.evidence_ids:
            if not evidence_id.startswith("batch_source_revision:"):
                continue
            path = output / "source_revisions" / f"{evidence_id.split(':', 1)[1]}.yaml"
            if path.is_file():
                amendment = read_yaml(path)
                amendment_id = amendment.pop("revision_id", None)
                if (
                    amendment_id == stable_id("batch_source_revision", amendment)
                    and amendment_id == evidence_id
                    and amendment.get("input_hashes") == _source_input_hashes(spec)
                ):
                    return False

    expected = {
        OnboardingStage.SOURCES_READY: _source_selection_evidence_id(spec),
        OnboardingStage.EXTRACTED: _extraction_evidence_id(spec),
        OnboardingStage.COMPLETENESS_VERIFIED: _completeness_evidence_id(spec),
    }
    for stage, evidence_id in expected.items():
        checkpoint = next((event for event in reversed(events) if event.stage == stage), None)
        if checkpoint is None or evidence_id not in checkpoint.evidence_ids:
            return True
    return False


def _revise_source_provenance(spec: BatchPipelineSpec, *, status: dict[str, Any]) -> dict[str, Any]:
    """Revalidate corrected source provenance without advancing the lifecycle."""
    if status["current_stage"] != OnboardingStage.COMPLETENESS_VERIFIED.value:
        raise ValueError("source revision requires current stage completeness_verified")

    events = [event for event in load_progress_events() if event.batch_id == spec.batch_id]
    source = _validate_source_selection(spec)
    extraction = _validate_extraction(spec)
    completeness = _validate_completeness(spec)
    spans = _materialize_spans(spec)
    registry, versions = _source_contracts(spec, spans)
    prior_evidence_ids = {
        stage.value: list(checkpoint.evidence_ids)
        for stage in (
            OnboardingStage.SOURCES_READY,
            OnboardingStage.EXTRACTED,
            OnboardingStage.COMPLETENESS_VERIFIED,
        )
        if (checkpoint := next((event for event in reversed(events) if event.stage == stage), None))
    }
    payload = {
        "batch_id": spec.batch_id,
        "prior_checkpoint_evidence_ids": prior_evidence_ids,
        "replacement_evidence_ids": {
            "sources_ready": source["evidence_ids"],
            "extracted": extraction["evidence_ids"],
            "completeness_verified": completeness["evidence_ids"],
        },
        "input_hashes": _source_input_hashes(spec),
        "source_registry_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in registry]
        ),
        "source_versions_sha256": canonical_sha256(
            [item.model_dump(mode="json") for item in versions]
        ),
    }
    revision_id = stable_id("batch_source_revision", payload)
    revision = {"revision_id": revision_id, **payload}
    output = REPO_ROOT / spec.paths.output_root
    write_yaml(
        output / "source_revisions" / f"{revision_id.split(':', 1)[1]}.yaml",
        revision,
    )
    return {
        "evidence_ids": [revision_id],
        "source_revision": revision,
        "note": "Corrected source provenance was revalidated without advancing the batch.",
    }


def _prepare_formalization(spec: BatchPipelineSpec) -> dict[str, Any]:
    spans = _materialize_spans(spec)
    registry, versions = _source_contracts(spec, spans)
    version_by_document = {
        document_id: version
        for entry in registry
        for document_id in entry.document_ids
        for version in versions
        if version.source_version_id in entry.source_version_ids
    }
    provider_by_document = {
        document_id: entry.provider_id for entry in registry for document_id in entry.document_ids
    }
    formal_payload = read_yaml(REPO_ROOT / spec.paths.formal_elements)
    if formal_payload.get("batch_id") != spec.batch_id:
        raise ValueError("formal element batch_id mismatch")
    element_specs = [FormalElementSpec.model_validate(item) for item in formal_payload["elements"]]
    parsed_elements = [(element, _parse_record(element)) for element in element_specs]
    provider_by_formal_record = {
        _record_id(record): provider.lower()
        for _, record in parsed_elements
        if (provider := getattr(record, "provider", None))
    }
    span_by_id = {item["span_id"]: item for item in spans}
    completeness = CompletenessLedger.model_validate(
        read_yaml(REPO_ROOT / spec.paths.completeness_ledger)
    )
    kept_spans = {
        span_id
        for item in completeness.dispositions
        if item.disposition == "keep"
        for span_id in item.source_span_ids
    }
    # The semantic judge must be able to verify keep, omit, and defer decisions.
    # Publication bindings remain restricted to kept_spans below, while the
    # read-only quality bundle carries every span cited by the completeness ledger.
    disposition_spans = {
        span_id for item in completeness.dispositions for span_id in item.source_span_ids
    }
    quality_spans = [item for item in spans if item["span_id"] in disposition_spans]
    candidates: list[FormalizationCandidate] = []
    annotations: list[FormalElementAnnotation] = []
    assertions: list[ReleasedAssertion] = []
    rules: list[tuple[PolicyRule, FormalElementAnnotation]] = []
    labels_seen: set[str] = set()
    for element, record in parsed_elements:
        if not set(element.source_span_ids) <= kept_spans:
            raise ValueError("formal elements may bind only spans with a keep disposition")
        record_id = _record_id(record)
        bound_spans = [span_by_id[span_id] for span_id in element.source_span_ids]
        document_ids = {item["document_id"] for item in bound_spans}
        if len(document_ids) != 1:
            raise ValueError(f"{record_id}: one formal element must bind one source version")
        document_id = next(iter(document_ids))
        version = version_by_document[document_id]
        payload = {"record": record.model_dump(mode="json")}
        semantic_hash = canonical_sha256(payload)
        binding = {
            "source_version_id": version.source_version_id,
            "source_span_ids": tuple(item["span_id"] for item in bound_spans),
            "source_text_sha256s": tuple(item["text_sha256"] for item in bound_spans),
            "formal_element_id": record_id,
            "semantic_sha256": semantic_hash,
        }
        candidates.append(
            FormalizationCandidate(
                candidate_id=stable_id("formalization_candidate", binding),
                **binding,
                semantic_payload=payload,
                state="fidelity_reviewed",
            )
        )
        annotation_payload = {
            **binding,
            "source_language": element.source_language,
            "source_language_gloss": element.source_language_gloss,
            "controlled_english": element.controlled_english,
            "terminology_decision_ids": element.terminology_decision_ids,
        }
        annotation_payload.pop("source_version_id")
        annotation = FormalElementAnnotation(
            annotation_id=stable_id("formal_annotation", annotation_payload),
            **annotation_payload,
            review_state="validated",
        )
        annotations.append(annotation)
        family = getattr(record, "product_family", getattr(record, "product_scope", None))
        if not family:
            raise ValueError(f"{record_id}: product family is required")
        product_id = getattr(record, "product", family)
        rule_clause_providers = {
            provider_by_formal_record[source_clause]
            for source_clause in getattr(record, "source_clauses", ())
            if source_clause in provider_by_formal_record
        }
        rule_provider = (
            next(iter(rule_clause_providers)) if len(rule_clause_providers) == 1 else None
        )
        assertions.append(
            ReleasedAssertion(
                assertion_id=record_id,
                semantic_key=f"{element.record_type}:{record_id}",
                assertion_kind=element.record_type,
                provider=(
                    spec.provider
                    or getattr(record, "provider", None)
                    or rule_provider
                    or provider_by_document[document_id]
                ).lower(),
                product_family=family,
                product_id=product_id,
                jurisdiction=spec.jurisdiction,
                option_ids=element.option_ids,
                option_group_id=element.option_group_id,
                option_group_required=element.option_group_required,
                option_group_product_ids=element.option_group_product_ids,
                dependency_only=element.dependency_only,
                dependencies=element.dependencies,
                source_version_ids=(version.source_version_id,),
                annotation_id=annotation.annotation_id,
                payload=payload,
                payload_sha256=semantic_hash,
            )
        )
        if isinstance(record, ProductFeature):
            labels_seen.add(record.product)
            labels_seen.update(
                candidate.removeprefix("workbook_label:")
                for candidate in record.source_candidate_ids
                if candidate.startswith("workbook_label:")
            )
        if isinstance(record, PolicyRule):
            rules.append((record, annotation))
    if not set(spec.product_labels) <= labels_seen:
        raise ValueError("every batch product label requires an explicit ProductFeature record")
    output = REPO_ROOT / spec.paths.output_root
    write_yaml(output / "spans.yaml", spans)
    write_yaml(output / "quality_spans.yaml", quality_spans)
    write_yaml(output / "source_registry.yaml", [item.model_dump(mode="json") for item in registry])
    write_yaml(output / "source_versions.yaml", [item.model_dump(mode="json") for item in versions])
    write_yaml(output / "candidates.yaml", [item.model_dump(mode="json") for item in candidates])
    write_yaml(output / "annotations.yaml", [item.model_dump(mode="json") for item in annotations])
    assertion_payloads = [item.model_dump(mode="json") for item in assertions]
    write_yaml(output / "assertions.yaml", assertion_payloads)
    write_text(
        output / "quality_assertions.json",
        json.dumps(
            assertion_payloads,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    compiled = "\n".join(
        f"% Annotation-ID: {annotation.annotation_id}\n"
        f"% NL-{annotation.source_language.upper()}: {annotation.source_language_gloss}\n"
        f"% NL-EN: {annotation.controlled_english}\n{rule.compiled_targets['prolog']}\n"
        for rule, annotation in rules
    )
    write_text(output / "compiled.pl", compiled)
    artifact_hashes = {
        "candidates": canonical_sha256([item.model_dump(mode="json") for item in candidates]),
        "assertions": canonical_sha256([item.model_dump(mode="json") for item in assertions]),
        "annotations": canonical_sha256([item.model_dump(mode="json") for item in annotations]),
        "spans": canonical_sha256(spans),
    }
    prep = {
        "batch_id": spec.batch_id,
        "product_labels": list(spec.product_labels),
        "provider": spec.provider,
        "jurisdiction": spec.jurisdiction,
        "product_family": spec.product_family,
        "input_hashes": _formalization_input_hashes(spec),
        "counts": {
            "features": sum(
                isinstance(_parse_record(item), ProductFeature) for item in element_specs
            ),
            "clauses": sum(isinstance(_parse_record(item), PolicyClause) for item in element_specs),
            "rules": len(rules),
        },
        "artifact_hashes": artifact_hashes,
        "publication_status": "awaiting_deterministic_verification",
    }
    write_yaml(output / "preparation.yaml", prep)
    _write_batch_quality_catalogue(spec)
    return {
        "evidence_ids": [
            stable_id(
                "batch_formalization",
                {
                    "batch_id": spec.batch_id,
                    "artifact_hashes": artifact_hashes,
                },
            )
        ],
        "note": "Typed candidates, assertions, bilingual annotations, and Prolog were constructed.",
    }


def _current_failed_quality_result_ids(spec: BatchPipelineSpec) -> list[str]:
    """Return current-evidence semantic failures eligible for content revision.

    Runner errors and timeouts remain immutable audit results, but they are transport
    failures rather than evidence that the source-bound content needs revision.
    """
    output = REPO_ROOT / spec.paths.output_root
    catalogue_path = output / "quality_cases.yaml"
    if not catalogue_path.is_file() or not _deterministic_artifacts_are_current(spec):
        return []
    catalogue = load_quality_catalogue(catalogue_path)
    result_root = QUALITY_ROOT / spec.batch_id
    failed: list[str] = []
    for path in sorted(result_root.glob("*/result.yaml")):
        payload = read_yaml(path)
        result_hash = payload.pop("result_hash", None)
        if result_hash != stable_hash(payload):
            continue
        try:
            result = EvaluationResult.model_validate(payload)
            expected_key = quality_case_cache_key(
                spec.quality_case_id,
                profile_name="release",
                model=result.model,
                catalogue_path=catalogue_path,
            )
        except (OSError, TypeError, ValueError):
            continue
        if (
            result.case_id == spec.quality_case_id
            and result.model in catalogue.allowed_models
            and result.cache_key == expected_key
            and result.status not in {"pass", "runner_error", "timeout"}
        ):
            failed.append(result.run_id)
    return sorted(set(failed))


def _preserved_semantic_failure_ids(spec: BatchPipelineSpec) -> list[str]:
    """Return valid historical semantic failures when a partial rebuild is stale."""
    failed: list[str] = []
    for path in sorted((QUALITY_ROOT / spec.batch_id).glob("*/result.yaml")):
        payload = read_yaml(path)
        result_hash = payload.pop("result_hash", None)
        if result_hash != stable_hash(payload):
            continue
        try:
            result = EvaluationResult.model_validate(payload)
        except (TypeError, ValueError):
            continue
        if result.case_id == spec.quality_case_id and result.status not in {
            "pass",
            "runner_error",
            "timeout",
        }:
            failed.append(result.run_id)
    return sorted(set(failed))


def _deterministic_artifacts_are_current(spec: BatchPipelineSpec) -> bool:
    """Check that the prepared outputs still match their deterministic checkpoint."""
    output = REPO_ROOT / spec.paths.output_root
    try:
        evidence = read_yaml(output / "deterministic_evidence.yaml")
        preparation = read_yaml(output / "preparation.yaml")
        raw_candidates = read_yaml(output / "candidates.yaml")
        raw_assertions = read_yaml(output / "assertions.yaml")
        raw_annotations = read_yaml(output / "annotations.yaml")
        raw_spans = read_yaml(output / "spans.yaml")
        candidates = [FormalizationCandidate.model_validate(item) for item in raw_candidates]
        assertions = [ReleasedAssertion.model_validate(item) for item in raw_assertions]
    except (OSError, TypeError, ValueError):
        return False
    deterministic_matches = evidence.get("candidate_hashes") == [
        canonical_sha256(item.model_dump(mode="json")) for item in candidates
    ] and evidence.get("assertion_hashes") == [item.payload_sha256 for item in assertions]
    if preparation.get("input_hashes") != _formalization_input_hashes(spec):
        return False
    artifact_hashes = preparation.get("artifact_hashes")
    if not artifact_hashes:
        return deterministic_matches
    return deterministic_matches and artifact_hashes == {
        "candidates": canonical_sha256(raw_candidates),
        "assertions": canonical_sha256(raw_assertions),
        "annotations": canonical_sha256(raw_annotations),
        "spans": canonical_sha256(raw_spans),
    }


def _revise_after_failed_quality(
    spec: BatchPipelineSpec, *, status: dict[str, Any]
) -> dict[str, Any]:
    """Rebuild a deterministic revision after judge failure or input drift."""
    reopened_from_stage = OnboardingStage(status["current_stage"])
    if reopened_from_stage not in {
        OnboardingStage.DETERMINISTIC_VERIFIED,
        OnboardingStage.GENERATIVE_VERIFIED,
        OnboardingStage.COHERENCE_VERIFIED,
    }:
        raise ValueError(
            "revision requires current stage deterministic_verified, "
            "generative_verified, or coherence_verified"
        )
    artifacts_are_current = _deterministic_artifacts_are_current(spec)
    failed_result_ids = _current_failed_quality_result_ids(spec)
    if not failed_result_ids and not artifacts_are_current:
        failed_result_ids = _preserved_semantic_failure_ids(spec)
    if not failed_result_ids and artifacts_are_current:
        raise ValueError("revision requires current-hash failed or invalid generative results")

    output = REPO_ROOT / spec.paths.output_root
    superseded: dict[str, Any] = {}
    if reopened_from_stage in {
        OnboardingStage.GENERATIVE_VERIFIED,
        OnboardingStage.COHERENCE_VERIFIED,
    }:
        consensus_path = output / "quality_consensus.yaml"
        if consensus_path.is_file():
            consensus = read_yaml(consensus_path)
            superseded["superseded_consensus_result_ids"] = consensus.get("result_ids", [])
            superseded["superseded_consensus_sha256"] = canonical_sha256(consensus)
    if reopened_from_stage == OnboardingStage.COHERENCE_VERIFIED:
        coherence_path = output / "coherence.yaml"
        if coherence_path.is_file():
            superseded["superseded_coherence_sha256"] = canonical_sha256(read_yaml(coherence_path))

    completeness = _validate_completeness(spec)
    formalization = _prepare_formalization(spec)
    deterministic = _validate_prepared_bundle(spec)
    payload = {
        "batch_id": spec.batch_id,
        "reopened_from_stage": reopened_from_stage.value,
        "failed_result_ids": failed_result_ids,
        "completeness_evidence_ids": completeness["evidence_ids"],
        "formalization_evidence_ids": formalization["evidence_ids"],
        "deterministic_evidence_ids": deterministic["evidence_ids"],
        **superseded,
    }
    revision_id = stable_id("batch_revision", payload)
    revision = {"revision_id": revision_id, **payload}
    write_yaml(output / "revisions" / f"{revision_id.split(':', 1)[1]}.yaml", revision)
    reopened_after_consensus = reopened_from_stage in {
        OnboardingStage.GENERATIVE_VERIFIED,
        OnboardingStage.COHERENCE_VERIFIED,
    }
    return {
        "evidence_ids": [revision_id],
        "failed_result_ids": failed_result_ids,
        "revision": revision,
        "note": (
            "Prior generative or coherence evidence was superseded; corrected artifacts "
            "were deterministically reverified."
            if reopened_after_consensus
            else (
                "Failed generative evidence was retained and corrected artifacts were "
                "deterministically reverified."
                if failed_result_ids
                else "Drifted formalization inputs were rebuilt and deterministically reverified."
            )
        ),
    }


def _parse_record(element: FormalElementSpec) -> ProductFeature | PolicyClause | PolicyRule:
    model = {"feature": ProductFeature, "clause": PolicyClause, "rule": PolicyRule}[
        element.record_type
    ]
    return model.model_validate(element.record)


def _record_id(record: ProductFeature | PolicyClause | PolicyRule) -> str:
    if isinstance(record, ProductFeature):
        return record.feature_id
    if isinstance(record, PolicyClause):
        return record.clause_id
    return record.rule_id


def _materialize_spans(spec: BatchPipelineSpec) -> list[dict[str, Any]]:
    spans = []
    for item in read_yaml(REPO_ROOT / spec.paths.span_specs):
        span = SpanSpec.model_validate(item)
        artifact = (REPO_ROOT / span.artifact).resolve()
        artifact.relative_to(REPO_ROOT.resolve())
        lines = artifact.read_text(encoding="utf-8").splitlines()
        if span.line_end > len(lines):
            raise ValueError(f"{span.span_id}: line range exceeds source artifact")
        text = "\n".join(lines[span.line_start - 1 : span.line_end]).strip()
        spans.append(
            {**span.model_dump(mode="json"), "text": text, "text_sha256": canonical_sha256(text)}
        )
    return spans


def _source_contracts(
    spec: BatchPipelineSpec, spans: list[dict[str, Any]]
) -> tuple[tuple[SourceRegistryEntry, ...], tuple[SourceVersion, ...]]:
    selected = {item["document_id"] for item in spans}
    extraction = read_yaml(REPO_ROOT / spec.paths.extraction_manifest)
    documents = [item for item in extraction["documents"] if item["document_id"] in selected]
    if {item["document_id"] for item in documents} != selected:
        raise ValueError("span documents are not closed by the extraction manifest")
    return adapt_legacy_source_manifests(
        read_yaml(REPO_ROOT / spec.paths.link_manifest), {**extraction, "documents": documents}
    )


def _validate_prepared_bundle(spec: BatchPipelineSpec) -> dict[str, Any]:
    bundle, assertions = _load_prepared(spec, gates=())
    if not bundle.candidates or not assertions or not bundle.annotations:
        raise ValueError("prepared batch must contain candidates, assertions, and annotations")
    if len({item.assertion_id for item in assertions}) != len(assertions):
        raise ValueError("duplicate assertion IDs")
    evidence = {
        "batch": spec.batch_id,
        "candidate_hashes": [
            canonical_sha256(item.model_dump(mode="json")) for item in bundle.candidates
        ],
        "assertion_hashes": [item.payload_sha256 for item in assertions],
    }
    output = REPO_ROOT / spec.paths.output_root
    write_yaml(output / "deterministic_evidence.yaml", evidence)
    prep = read_yaml(output / "preparation.yaml")
    write_yaml(
        output / "preparation.yaml",
        {**prep, "publication_status": "awaiting_generative_verification"},
    )
    return {
        "evidence_ids": [stable_id("deterministic_batch_evidence", evidence)],
        "note": "Schema, provenance, annotation, referential, and compilation contracts passed.",
    }


def _write_batch_quality_catalogue(spec: BatchPipelineSpec) -> Path:
    output = REPO_ROOT / spec.paths.output_root
    base = load_quality_catalogue()
    # Rule assertions already carry their compiled targets. The standalone Prolog file is
    # deterministically verified, so staging it again would duplicate model evidence.
    evidence = [
        {"evidence_id": name, "path": f"{spec.paths.output_root}/{filename}"}
        for name, filename in (
            ("batch_source_spans", "quality_spans.yaml"),
            ("batch_assertions", "quality_assertions.json"),
            ("batch_annotations", "annotations.yaml"),
        )
    ]
    evidence.append({"evidence_id": "batch_source_selection", "path": spec.paths.source_selection})
    evidence.append({"evidence_id": "batch_completeness", "path": spec.paths.completeness_ledger})
    evidence_bytes = sum((REPO_ROOT / item["path"]).stat().st_size for item in evidence)
    max_input_bytes = _select_quality_input_cap(evidence_bytes)
    payload = {
        "catalogue_id": f"{spec.quality_case_id}-catalogue-v1",
        "version": 1,
        "rubric": repo_relative_posix(REPO_ROOT / base.rubric),
        "output_schema": repo_relative_posix(REPO_ROOT / base.output_schema),
        "allowed_models": base.allowed_models,
        "profiles": {
            "release": {
                "case_ids": [spec.quality_case_id],
                "max_calls": 2,
                "max_input_bytes": max_input_bytes,
                "timeout_seconds": 600,
                "blocking": True,
            }
        },
        "cases": [
            {
                "case_id": spec.quality_case_id,
                "owner": "kb-governance",
                "risk_class": "high",
                "lifecycle_stage": "formalization",
                "requirement_ids": ["FOR-003", "FOR-004", "FOR-006", "KB-005", "KB-007"],
                "evidence": evidence,
                "focus": "Check source-to-feature/clause/rule fidelity, completeness, bilingual commentary, and semantic minimality for this exact batch. Workbook labels may be grouped into one non-selectable feature when the policy evidence defines one combined scope; source selection supplies label provenance and does not authorize separate module semantics. Deferred inventory is outside released truth and recommendation use. Evidence fields ending in sha256 use canonical_sha256 over canonical JSON serialization; for a text value this includes the JSON string quotes and is not the SHA-256 of the unquoted UTF-8 bytes.",
                "expected_criteria": [
                    "provenance_closure",
                    "unsupported_addition",
                    "semantic_omission",
                    "polarity_and_modality",
                    "numeric_temporal_scope",
                    "cross_reference_preservation",
                    "controlled_language_quality",
                    "semantic_minimality",
                ],
            }
        ],
    }
    path = output / "quality_cases.yaml"
    write_yaml(path, payload)
    return path


def _select_quality_input_cap(evidence_bytes: int) -> int:
    """Return the smallest governed tier that contains the complete evidence bundle."""

    if evidence_bytes < 0:
        raise ValueError("quality evidence byte count cannot be negative")
    for tier in QUALITY_INPUT_BYTE_TIERS:
        if evidence_bytes <= tier:
            return tier
    raise ValueError(
        f"quality evidence totals {evidence_bytes} bytes and exceeds the governed "
        f"ceiling of {QUALITY_INPUT_BYTE_TIERS[-1]} bytes"
    )


def _run_generative_gate(spec: BatchPipelineSpec, *, model: str | None) -> dict[str, Any]:
    output = REPO_ROOT / spec.paths.output_root
    catalogue_path = output / "quality_cases.yaml"
    catalogue = load_quality_catalogue(catalogue_path)
    selected_model = model or catalogue.allowed_models[0]
    result_root = QUALITY_ROOT / spec.batch_id
    results = [
        run_quality_case(
            spec.quality_case_id,
            profile_name="release",
            model=selected_model,
            output_dir=result_root,
            attempt=index + 1,
            catalogue_path=catalogue_path,
        )
        for index in range(catalogue.profiles["release"].max_calls)
    ]
    consensus = resolve_quality_consensus(results)
    if not consensus.automated_promotion_allowed:
        raise ValueError(f"generative verification blocked: {consensus.reason}")
    write_consensus_bundle(results, output_dir=result_root)
    consensus_payload = consensus.model_dump(mode="json")
    write_yaml(output / "quality_consensus.yaml", consensus_payload)
    return {
        "evidence_ids": [stable_id("batch_quality_consensus", consensus_payload)],
        "note": "All current-hash independent generative judgments passed.",
    }


def _validate_release_coherence(spec: BatchPipelineSpec) -> dict[str, Any]:
    output = REPO_ROOT / spec.paths.output_root
    consensus = read_yaml(output / "quality_consensus.yaml")
    if consensus.get("status") != "pass" or not consensus.get("automated_promotion_allowed"):
        raise ValueError("passing generative consensus is required")
    _, assertions = _load_prepared(spec, gates=())
    semantic_keys = [item.semantic_key for item in assertions]
    if len(semantic_keys) != len(set(semantic_keys)):
        raise ValueError("duplicate semantic keys block release")
    evidence = {
        "batch_id": spec.batch_id,
        "assertion_ids": [item.assertion_id for item in assertions],
        "semantic_keys": semantic_keys,
        "quality_consensus_hash": canonical_sha256(consensus),
        "coherent": True,
    }
    write_yaml(output / "coherence.yaml", evidence)
    return {
        "evidence_ids": [stable_id("batch_coherence", evidence)],
        "note": "The prospective release is source-closed, dependency-closed, and duplicate-free.",
    }


def _publish_release(spec: BatchPipelineSpec) -> dict[str, Any]:
    output = REPO_ROOT / spec.paths.output_root
    consensus = read_yaml(output / "quality_consensus.yaml")
    quality_results = []
    for result_id in consensus["result_ids"]:
        result_path = QUALITY_ROOT / spec.batch_id / result_id / "result.yaml"
        if not result_path.is_file():
            raise ValueError(f"missing generative result: {result_id}")
        payload = read_yaml(result_path)
        result = EvaluationResult.model_validate(
            {key: value for key, value in payload.items() if key != "result_hash"}
        )
        expected_key = quality_case_cache_key(
            spec.quality_case_id,
            profile_name="release",
            model=result.model,
            catalogue_path=output / "quality_cases.yaml",
        )
        if result.cache_key != expected_key:
            raise ValueError("generative evidence is stale for the current batch artifacts")
        quality_results.append(result)
    current_consensus = resolve_quality_consensus(quality_results)
    if current_consensus.model_dump(mode="json") != consensus:
        raise ValueError("stored generative consensus does not match its result records")
    deterministic = read_yaml(output / "deterministic_evidence.yaml")
    gate_payloads = {
        name: {"batch": spec.batch_id, "check": name, "passed": True}
        for name in (
            "schema",
            "provenance",
            "fidelity",
            "coherence",
            "compilation",
            "interpretability",
        )
    }
    generative_config = {
        "case": spec.quality_case_id,
        "profile": "release",
        "result_ids": consensus["result_ids"],
    }
    candidates = tuple(
        FormalizationCandidate.model_validate(item)
        for item in read_yaml(output / "candidates.yaml")
    )
    gates = []
    for candidate in candidates:
        body = {
            "candidate_id": candidate.candidate_id,
            "formal_element_id": candidate.formal_element_id,
            "candidate_sha256": canonical_sha256(candidate.model_dump(mode="json")),
            "semantic_sha256": candidate.semantic_sha256,
            "deterministic_checks": {key: True for key in gate_payloads},
            "deterministic_evidence_hashes": {
                key: canonical_sha256(value) for key, value in gate_payloads.items()
            },
            "generative_gate_config_sha256": canonical_sha256(generative_config),
            "generative_evidence_sha256": canonical_sha256(consensus),
            "generative_verdict": "pass",
        }
        gates.append(
            AutomatedGateEvidence(gate_evidence_id=stable_id("automated_gate", body), **body)
        )
    bundle, assertions = _load_prepared(spec, gates=tuple(gates))
    snapshot = build_corpus_snapshot(bundle)
    annotations = bundle.annotations
    validator_payloads = {
        **gate_payloads,
        "deterministic_evidence": deterministic,
        "generative_config": generative_config,
        "generative_evidence": consensus,
    }
    release = build_kb_release(
        bundle,
        snapshot,
        span_payloads={item["span_id"]: item for item in read_yaml(output / "spans.yaml")},
        translation_payloads={
            item.annotation_id: {
                "source": item.source_language_gloss,
                "en": item.controlled_english,
            }
            for item in annotations
        },
        formal_record_payloads={
            item.assertion_id: item.model_dump(mode="json") for item in assertions
        },
        validator_payloads=validator_payloads,
    ).model_copy(update={"release_status": "published"})
    repository = KnowledgeRepository(release, assertions, list(annotations), automated_gates=gates)
    repository.require_coherent()
    projection_request = _publication_request(spec, assertions)
    projections, required_option_groups = _publication_projections(
        repository, assertions, projection_request
    )
    manifest = publish_kb_release(release, RELEASE_ROOT)
    pointer = {
        "batch_id": spec.batch_id,
        "kb_release_id": release.kb_release_id,
        "manifest": repo_relative_posix(manifest),
        "assertions": repo_relative_posix(output / "assertions.yaml"),
        "annotations": repo_relative_posix(output / "annotations.yaml"),
        "compiled": repo_relative_posix(output / "compiled.pl"),
        "counts": read_yaml(output / "preparation.yaml")["counts"],
    }
    if required_option_groups:
        pointer["required_option_groups"] = required_option_groups
        pointer["projection_branches"] = [
            {
                "option_ids": list(projection.request.option_ids),
                "projection_id": projection.projection_id,
            }
            for projection in projections
        ]
        pointer["projection_ids"] = [projection.projection_id for projection in projections]
    else:
        pointer["projection_id"] = projections[0].projection_id
    pointer_path = RELEASE_ROOT / "active_batches" / f"{spec.batch_id}.yaml"
    write_yaml(pointer_path, pointer)
    prep = read_yaml(output / "preparation.yaml")
    write_yaml(output / "preparation.yaml", {**prep, "publication_status": "published", **pointer})
    return {
        "evidence_ids": [
            release.kb_release_id,
            *(projection.projection_id for projection in projections),
        ],
        "note": "Immutable gated KB release and dependency-closed runtime projection published.",
        "release": pointer,
    }


def _publication_projections(
    repository: KnowledgeRepository,
    assertions: list[ReleasedAssertion],
    request: ProjectionRequest,
) -> tuple[tuple[Any, ...], dict[str, list[str]]]:
    """Build every valid branch needed to witness required option-group publication."""

    groups: dict[str, dict[str, Any]] = {}
    for assertion in assertions:
        if assertion.option_group_id is None or not _assertion_matches_publication_scope(
            assertion, request
        ):
            continue
        group = groups.setdefault(
            assertion.option_group_id,
            {"required": False, "option_ids": set()},
        )
        group["required"] = group["required"] or assertion.option_group_required
        group["option_ids"].update(assertion.option_ids)

    required = {
        group_id: sorted(group["option_ids"])
        for group_id, group in sorted(groups.items())
        if group["required"]
    }
    if not required:
        return (repository.project(request),), {}

    group_ids = tuple(required)
    selections = product(*(required[group_id] for group_id in group_ids))
    projections = tuple(
        repository.project(request.model_copy(update={"option_ids": tuple(selection)}))
        for selection in selections
    )
    return projections, required


def _publication_request(
    spec: BatchPipelineSpec,
    assertions: list[ReleasedAssertion],
) -> ProjectionRequest:
    """Keep provider-neutral batches neutral in their published runtime scope."""

    family = spec.product_family or assertions[0].product_family
    provider = spec.provider.lower() if spec.provider is not None else None
    return ProjectionRequest(
        product_family=family,
        provider=provider,
        jurisdiction=spec.jurisdiction,
        effective_on=date.today(),
    )


def _assertion_matches_publication_scope(
    assertion: ReleasedAssertion, request: ProjectionRequest
) -> bool:
    """Apply the non-option part of repository scope matching for publication."""

    if assertion.product_family != request.product_family:
        return False
    if assertion.jurisdiction != request.jurisdiction:
        return False
    if request.provider and assertion.provider != request.provider:
        return False
    if request.product_ids:
        product_ids = assertion.option_group_product_ids or (assertion.product_id,)
        if not set(product_ids) & set(request.product_ids):
            return False
    if assertion.effective_from and request.effective_on < assertion.effective_from:
        return False
    if assertion.effective_to and request.effective_on > assertion.effective_to:
        return False
    return True


def _load_prepared(
    spec: BatchPipelineSpec, *, gates: tuple[AutomatedGateEvidence, ...]
) -> tuple[IngestionBundle, list[ReleasedAssertion]]:
    output = REPO_ROOT / spec.paths.output_root
    candidates = tuple(
        FormalizationCandidate.model_validate(item)
        for item in read_yaml(output / "candidates.yaml")
    )
    annotations = tuple(
        FormalElementAnnotation.model_validate(item)
        for item in read_yaml(output / "annotations.yaml")
    )
    assertions = [
        ReleasedAssertion.model_validate(item) for item in read_yaml(output / "assertions.yaml")
    ]
    compiled_path = output / "compiled.pl"
    compiled = CompiledArtifact(
        compiled_artifact_id=stable_id("compiled", {"batch": spec.batch_id, "target": "prolog"}),
        formal_element_ids=tuple(item.formal_element_id for item in candidates),
        annotation_ids=tuple(item.annotation_id for item in annotations),
        target="prolog",
        payload_sha256=canonical_sha256(compiled_path.read_bytes()),
        compiler_version="portable-product-batch-v1",
    )
    bundle = IngestionBundle(
        source_registry=tuple(
            SourceRegistryEntry.model_validate(item)
            for item in read_yaml(output / "source_registry.yaml")
        ),
        source_versions=tuple(
            SourceVersion.model_validate(item)
            for item in read_yaml(output / "source_versions.yaml")
        ),
        candidates=candidates,
        automated_gates=gates,
        annotations=annotations,
        compiled_artifacts=(compiled,),
    )
    return bundle, assertions


def validate_batch_pipeline() -> list[str]:
    """Validate catalogue closure, paths, commands, ordering, and boundedness."""
    expected = build_pipeline_catalogue()
    actual = read_yaml(CATALOGUE_FILE)
    if actual != expected:
        raise ValueError("batch pipeline catalogue is stale; regenerate it explicitly")
    specs = [BatchPipelineSpec.model_validate(item) for item in actual["batches"]]
    plan_ids = [item.batch_id for item in build_progressive_plan().batches]
    if [item.batch_id for item in specs] != plan_ids:
        raise ValueError("batch pipeline order differs from the progressive plan")
    if len({item.quality_case_id for item in specs}) != len(specs):
        raise ValueError("batch quality case IDs must be unique")
    for spec in specs:
        if Path(spec.paths.output_root).is_absolute() or ".." in Path(spec.paths.output_root).parts:
            raise ValueError(f"{spec.batch_id}: output root must stay repository-relative")
        if spec.reference_release and not (REPO_ROOT / spec.reference_release).is_file():
            raise ValueError(f"{spec.batch_id}: reference release does not exist")
    events = load_progress_events()
    unpublished = 0
    for spec in specs:
        if reference_release_is_published(
            spec.batch_id,
            catalogue_path=CATALOGUE_FILE,
            repository_root=REPO_ROOT,
        ):
            continue
        effective = effective_onboarding_stage(
            [event for event in events if event.batch_id == spec.batch_id]
        )
        unpublished += effective != OnboardingStage.PUBLISHED
    return [
        f"batches={len(specs)}",
        f"unpublished_batches={unpublished}",
        f"ledger_managed_batches={sum(item.reference_release is None for item in specs)}",
        "portable_entrypoint=product-batch-pipeline",
        "bulk_execution=disabled",
    ]
