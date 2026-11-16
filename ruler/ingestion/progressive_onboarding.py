# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Progressive product onboarding plans and append-only checkpoints.

This module prepares small batches from the reference workbook rollout inventory.
It never crawls, extracts, formalizes, or publishes policy content itself.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.ingestion.contracts import stable_id
from ruler.io import read_yaml, write_yaml
from ruler.paths import DATA_DIR, REPO_ROOT

ONBOARDING_ROOT = DATA_DIR / "operations" / "progressive_onboarding"
ONBOARDING_PLAN_FILE = ONBOARDING_ROOT / "plan.yaml"
ONBOARDING_LEDGER_FILE = ONBOARDING_ROOT / "progress_ledger.jsonl"
ROLLOUT_PLAN_FILE = DATA_DIR / "operations" / "ingestion_rollout" / "family_rollout_plan.yaml"
PIPELINE_CATALOGUE_FILE = ONBOARDING_ROOT / "pipeline_catalogue.yaml"
PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE = ONBOARDING_ROOT / "provider_document_expansion_plan.yaml"
LEGACY_BATCH_IDS: tuple[str, ...] = ()
LEGACY_REFERENCE_DOCUMENT_IDS: frozenset[str] = frozenset()


class OnboardingStage(StrEnum):
    PLANNED = "planned"
    SOURCES_READY = "sources_ready"
    EXTRACTED = "extracted"
    COMPLETENESS_VERIFIED = "completeness_verified"
    FORMALIZED = "formalized"
    DETERMINISTIC_VERIFIED = "deterministic_verified"
    GENERATIVE_VERIFIED = "generative_verified"
    COHERENCE_VERIFIED = "coherence_verified"
    PUBLISHED = "published"
    BLOCKED = "blocked"
    REVISION = "revision"
    SOURCE_REVISION = "source_revision"
    SCOPE_REVISION = "scope_revision"


NON_ADVANCING_STAGES = frozenset(
    {
        OnboardingStage.BLOCKED,
        OnboardingStage.REVISION,
        OnboardingStage.SOURCE_REVISION,
        OnboardingStage.SCOPE_REVISION,
    }
)
ORDERED_STAGES = tuple(stage for stage in OnboardingStage if stage not in NON_ADVANCING_STAGES)
REVISION_ELIGIBLE_STAGES = frozenset(
    {
        OnboardingStage.DETERMINISTIC_VERIFIED,
        OnboardingStage.GENERATIVE_VERIFIED,
        OnboardingStage.COHERENCE_VERIFIED,
    }
)


class BatchPlan(BaseModel):
    """One deliberately bounded product-family onboarding batch."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    batch_id: str
    phase: int = Field(ge=1)
    product_labels: tuple[str, ...] = Field(min_length=1)
    phase_workbook_rows: int = Field(ge=0)
    phase_source_ready_rows: int = Field(ge=0)
    phase_discovery_rows: int = Field(ge=0)
    phase_quarantined_rows: int = Field(ge=0)
    maximum_products: int = Field(default=3, ge=1, le=3)
    maximum_documents: int = Field(default=3, ge=1, le=3)
    batch_kind: Literal["product_family", "provider_document_expansion"] = Field(
        default="product_family", exclude_if=lambda value: value == "product_family"
    )
    planned_document_ids: tuple[str, ...] = Field(
        default=(), max_length=3, exclude_if=lambda value: not value
    )
    jurisdiction: str = Field(default="CH", min_length=2, exclude_if=lambda value: value == "CH")
    initial_stage: Literal["planned"] = "planned"


class ProviderDocumentExpansionBatch(BaseModel):
    """One explicit provider/document slice appended after the legacy product plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    batch_id: str = Field(pattern=r"^phase-[0-9]{2}-batch-[0-9]{2}$")
    phase: int = Field(ge=1)
    product_labels: tuple[str, ...] = Field(min_length=1, max_length=3)
    planned_document_ids: tuple[str, ...] = Field(min_length=1, max_length=3)
    jurisdiction: str = Field(default="CH", min_length=2, exclude_if=lambda value: value == "CH")
    batch_kind: Literal["provider_document_expansion"] = Field(
        default="provider_document_expansion",
        exclude_if=lambda value: value == "provider_document_expansion",
    )


class ProviderDocumentExpansionPlan(BaseModel):
    """Content-bound opt-in plan for repeated-label provider expansion batches."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    expansion_plan_id: str
    base_plan_id: str
    source_reference_manifest: str
    batches: tuple[ProviderDocumentExpansionBatch, ...] = ()

    @model_validator(mode="after")
    def content_bound_and_unique(self) -> "ProviderDocumentExpansionPlan":
        payload = self.model_dump(mode="json", exclude={"expansion_plan_id"})
        expected = stable_id("provider_document_expansion_plan", payload)
        if self.expansion_plan_id != expected:
            raise ValueError("expansion_plan_id does not match provider expansion content")
        batch_ids = [batch.batch_id for batch in self.batches]
        if len(batch_ids) != len(set(batch_ids)):
            raise ValueError("provider expansion batch IDs must be unique")
        document_ids = [
            document_id for batch in self.batches for document_id in batch.planned_document_ids
        ]
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("provider expansion documents must occur in exactly one batch")
        return self


class ProgressiveOnboardingPlan(BaseModel):
    """Ordered batches and verification gates derived from the workbook inventory."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    plan_id: str
    schema_version: int = 1
    source_rollout_plan: str
    source_expansion_plan: str | None = Field(default=None, exclude_if=lambda value: value is None)
    expansion_plan_id: str | None = Field(default=None, exclude_if=lambda value: value is None)
    policy: str
    maximum_concurrent_batches: Literal[1] = 1
    stage_order: tuple[str, ...]
    verification_skills: tuple[str, ...]
    continuous_verifications: dict[str, tuple[str, ...]]
    batches: tuple[BatchPlan, ...]

    @model_validator(mode="after")
    def content_bound_plan(self) -> "ProgressiveOnboardingPlan":
        """Bind the plan ID to its ordering, scopes, and verification contract."""
        payload = self.model_dump(mode="json", exclude={"plan_id"})
        if self.plan_id != stable_id("progressive_onboarding_plan", payload):
            raise ValueError("plan_id does not match progressive onboarding content")
        return self


class ProgressEvent(BaseModel):
    """One immutable batch checkpoint with evidence for the claimed stage."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    event_id: str
    batch_id: str
    previous_stage: OnboardingStage | None
    stage: OnboardingStage
    recorded_at: datetime
    evidence_ids: tuple[str, ...] = ()
    note: str

    @model_validator(mode="after")
    def valid_checkpoint(self) -> "ProgressEvent":
        """Require evidence for progress and bind identity to the full event payload."""
        if (
            self.stage not in {OnboardingStage.PLANNED, OnboardingStage.BLOCKED}
            and not self.evidence_ids
        ):
            raise ValueError("advancing an onboarding batch requires evidence IDs")
        expected = stable_id(
            "onboarding_progress", self.model_dump(mode="json", exclude={"event_id"})
        )
        if self.event_id != expected:
            raise ValueError("event_id does not match onboarding checkpoint content")
        return self


def effective_onboarding_stage(events: list[ProgressEvent]) -> OnboardingStage | None:
    """Resolve append-only checkpoints into the batch's current executable stage."""
    effective: OnboardingStage | None = None
    for event in events:
        if event.stage == OnboardingStage.REVISION:
            if effective in REVISION_ELIGIBLE_STAGES:
                effective = OnboardingStage.DETERMINISTIC_VERIFIED
            continue
        if event.stage in NON_ADVANCING_STAGES:
            continue
        effective = event.stage
    return effective


def build_progressive_plan() -> ProgressiveOnboardingPlan:
    """Convert the existing family rollout into small, ordered non-executing batches."""
    rollout = read_yaml(ROLLOUT_PLAN_FILE)
    batches: list[BatchPlan] = []
    for phase in rollout["phases"]:
        products = phase["products"]
        for offset in range(0, len(products), 3):
            labels = tuple(products[offset : offset + 3])
            suffix = offset // 3 + 1
            dispositions = phase.get("source_dispositions", {})
            batches.append(
                BatchPlan(
                    batch_id=f"phase-{phase['phase']:02d}-batch-{suffix:02d}",
                    phase=phase["phase"],
                    product_labels=labels,
                    phase_workbook_rows=phase["workbook_rows"],
                    phase_source_ready_rows=dispositions.get("source_ready", 0),
                    phase_discovery_rows=dispositions.get("discovery_needed", 0),
                    phase_quarantined_rows=dispositions.get("quarantined", 0),
                )
            )
    payload = {
        "schema_version": 1,
        "source_rollout_plan": "data/operations/ingestion_rollout/family_rollout_plan.yaml",
        "policy": "prepare and verify one batch at a time; never start the next phase before the current phase is published or explicitly blocked",
        "maximum_concurrent_batches": 1,
        "stage_order": tuple(stage.value for stage in ORDERED_STAGES),
        "verification_skills": (
            "progressive-product-onboarding",
            "execute-progressive-product-batch",
            "verify-kb-consistency",
            "summarize-kb-statistics",
        ),
        "continuous_verifications": {
            "every_checkpoint": (
                "uv run ruler validate progressive-onboarding",
                "uv run ruler validate batch-pipeline",
                "uv run ruler workflow verify-kb-consistency",
                "uv run ruler workflow kb-statistics",
            ),
            "before_formalization": (
                "uv run ruler validate source-corpus",
                "uv run ruler validate translation-control",
            ),
            "before_publication": (
                "uv run ruler validate formalized-kb",
                "uv run ruler validate semantic-preservation",
                "uv run ruler validate prolog-nl-comments",
                "uv run ruler validate reasoning-core",
            ),
        },
        "batches": tuple(batches),
    }
    identity_payload = {
        **payload,
        "batches": [batch.model_dump(mode="json") for batch in batches],
    }
    base_plan = ProgressiveOnboardingPlan(
        plan_id=stable_id("progressive_onboarding_plan", identity_payload), **payload
    )
    if not PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE.is_file():
        return base_plan

    expansion = ProviderDocumentExpansionPlan.model_validate(
        read_yaml(PROVIDER_DOCUMENT_EXPANSION_PLAN_FILE)
    )
    if not expansion.batches:
        return base_plan
    if expansion.base_plan_id != base_plan.plan_id:
        raise ValueError("provider expansion plan targets a different base plan")
    last_legacy_phase = max((item.phase for item in base_plan.batches), default=0)
    if any(batch.phase <= last_legacy_phase for batch in expansion.batches):
        raise ValueError("provider expansion batches must follow the legacy phases")
    if {batch.batch_id for batch in expansion.batches} & {
        batch.batch_id for batch in base_plan.batches
    }:
        raise ValueError("provider expansion batch IDs collide with the legacy prefix")
    known_labels = {label for batch in base_plan.batches for label in batch.product_labels}
    if any(not set(batch.product_labels) <= known_labels for batch in expansion.batches):
        raise ValueError("provider expansion labels must come from the workbook rollout")

    reference_path = Path(expansion.source_reference_manifest)
    if reference_path.is_absolute() or ".." in reference_path.parts:
        raise ValueError("provider expansion source manifest must stay repository-relative")
    reference = read_yaml(REPO_ROOT / reference_path)
    selected_records = [
        item
        for item in reference.get("selected_documents", ())
        if isinstance(item, dict) and item.get("document_id")
    ]
    reference_ids = [item["document_id"] for item in selected_records]
    if len(reference_ids) != len(set(reference_ids)):
        raise ValueError("provider expansion reference documents must be unique")
    records = {item["document_id"]: item for item in selected_records}
    planned_ids = {
        document_id for batch in expansion.batches for document_id in batch.planned_document_ids
    }
    already_governed_ids = _legacy_selected_document_ids(REPO_ROOT) | (
        LEGACY_REFERENCE_DOCUMENT_IDS & records.keys()
    )
    expected_planned_ids = records.keys() - already_governed_ids
    if planned_ids != expected_planned_ids:
        missing_ids = sorted(expected_planned_ids - planned_ids)
        unexpected_ids = sorted(planned_ids - expected_planned_ids)
        raise ValueError(
            "provider expansion must exactly cover reference documents not already "
            f"governed by legacy batches; missing={missing_ids}, unexpected={unexpected_ids}"
        )

    expanded_batches = list(base_plan.batches)
    for batch in expansion.batches:
        row_count = sum(
            int(records[document_id].get("row_count", 0))
            for document_id in batch.planned_document_ids
        )
        expanded_batches.append(
            BatchPlan(
                batch_id=batch.batch_id,
                phase=batch.phase,
                product_labels=batch.product_labels,
                phase_workbook_rows=row_count,
                phase_source_ready_rows=row_count,
                phase_discovery_rows=0,
                phase_quarantined_rows=0,
                batch_kind=batch.batch_kind,
                planned_document_ids=batch.planned_document_ids,
                jurisdiction=batch.jurisdiction,
            )
        )
    expanded_payload = {
        **payload,
        "source_expansion_plan": "data/operations/progressive_onboarding/provider_document_expansion_plan.yaml",
        "expansion_plan_id": expansion.expansion_plan_id,
        "batches": tuple(expanded_batches),
    }
    expanded_identity = {
        **expanded_payload,
        "batches": [batch.model_dump(mode="json") for batch in expanded_batches],
    }
    return ProgressiveOnboardingPlan(
        plan_id=stable_id("progressive_onboarding_plan", expanded_identity),
        **expanded_payload,
    )


def _legacy_selected_document_ids(repository_root: Path) -> set[str]:
    """Collect reference documents already governed by legacy lifecycle batches."""
    document_ids: set[str] = set()
    batch_root = repository_root / "data" / "operations" / "progressive_onboarding" / "batches"
    for batch_id in LEGACY_BATCH_IDS:
        selection_path = batch_root / batch_id / "input" / "source_selection.yaml"
        if not selection_path.is_file():
            continue
        selection = read_yaml(selection_path)
        document_ids.update(
            document_id
            for document_id in selection.get("document_ids", ())
            if isinstance(document_id, str) and document_id
        )
    return document_ids


def initialize_progressive_onboarding(root: Path = ONBOARDING_ROOT) -> dict[str, Path]:
    """Write the plan and seed only the first batch as planned; perform no ingestion."""
    plan = build_progressive_plan()
    plan_path = root / "plan.yaml"
    ledger_path = root / "progress_ledger.jsonl"
    write_yaml(plan_path, plan.model_dump(mode="json"))
    if not ledger_path.exists() and not plan.batches:
        ledger_path.touch()
    if not ledger_path.exists():
        first = plan.batches[0]
        payload = {
            "batch_id": first.batch_id,
            "previous_stage": None,
            "stage": OnboardingStage.PLANNED,
            "recorded_at": datetime.now(UTC),
            "evidence_ids": (plan.plan_id,),
            "note": "Initial bounded batch prepared; no crawl or extraction started.",
        }
        event = _progress_event(payload)
        _append_jsonl(ledger_path, event)
    return {"plan": plan_path, "ledger": ledger_path}


def load_progress_events(path: Path = ONBOARDING_LEDGER_FILE) -> tuple[ProgressEvent, ...]:
    """Load and validate every append-only onboarding checkpoint."""
    if not path.exists():
        return ()
    return tuple(
        ProgressEvent.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


def reference_release_is_published(
    batch_id: str,
    *,
    catalogue_path: Path = PIPELINE_CATALOGUE_FILE,
    repository_root: Path = REPO_ROOT,
) -> bool:
    """Resolve a configured immutable reference release as predecessor-final evidence."""
    if not catalogue_path.is_file():
        return False
    catalogue = read_yaml(catalogue_path)
    batches = catalogue.get("batches", ()) if isinstance(catalogue, dict) else ()
    batch = next(
        (item for item in batches if isinstance(item, dict) and item.get("batch_id") == batch_id),
        None,
    )
    if not batch or not batch.get("reference_release"):
        return False
    release_path = Path(batch["reference_release"])
    if release_path.is_absolute() or ".." in release_path.parts:
        raise ValueError(f"{batch_id}: reference release must stay repository-relative")
    return (repository_root / release_path).is_file()


def append_progress_checkpoint(
    batch_id: str,
    stage: OnboardingStage,
    *,
    evidence_ids: tuple[str, ...],
    note: str,
    path: Path = ONBOARDING_LEDGER_FILE,
) -> ProgressEvent:
    """Advance one batch by one stage, or record a non-advancing blocked event."""
    plan = prepare_progress_checkpoint(batch_id)
    all_events = load_progress_events(path)
    check_checkpoint_predecessors(batch_id, stage, plan, all_events)
    previous, effective_previous = resolve_checkpoint_stages(batch_id, all_events)
    check_checkpoint_transition(batch_id, stage, effective_previous)
    event = create_checkpoint_event(batch_id, stage, previous, evidence_ids, note)
    _append_jsonl(path, event)
    return event


def prepare_progress_checkpoint(batch_id: str) -> ProgressiveOnboardingPlan:
    """Rebuild the native plan and reject an unknown target before reading the ledger."""
    plan = build_progressive_plan()
    if batch_id not in {batch.batch_id for batch in plan.batches}:
        raise ValueError(f"unknown onboarding batch: {batch_id}")
    return plan


def check_checkpoint_predecessors(
    batch_id: str,
    stage: OnboardingStage,
    plan: ProgressiveOnboardingPlan,
    all_events: tuple[ProgressEvent, ...],
) -> None:
    """Check earlier batches in source order, stopping at the first unmet predecessor."""
    target = next(batch for batch in plan.batches if batch.batch_id == batch_id)
    target_sequence = plan.batches.index(target)
    if target_sequence and stage not in {OnboardingStage.PLANNED, OnboardingStage.BLOCKED}:
        for prior in plan.batches[:target_sequence]:
            prior_events = [event for event in all_events if event.batch_id == prior.batch_id]
            latest = prior_events[-1].stage if prior_events else None
            if latest not in {
                OnboardingStage.PUBLISHED,
                OnboardingStage.BLOCKED,
            } and not reference_release_is_published(prior.batch_id):
                raise ValueError(f"prior phase batch is not final: {prior.batch_id}")


def resolve_checkpoint_stages(
    batch_id: str,
    all_events: tuple[ProgressEvent, ...],
) -> tuple[OnboardingStage | None, OnboardingStage | None]:
    """Keep latest recorded and folded effective progress distinct."""
    events = [event for event in all_events if event.batch_id == batch_id]
    previous = events[-1].stage if events else None
    effective_previous = effective_onboarding_stage(events)
    return previous, effective_previous


def check_checkpoint_transition(
    batch_id: str,
    stage: OnboardingStage,
    effective_previous: OnboardingStage | None,
) -> None:
    """Validate exactly one native transition, including non-advancing revisions."""
    if stage == OnboardingStage.REVISION:
        if effective_previous not in REVISION_ELIGIBLE_STAGES:
            raise ValueError(
                "revision requires a deterministic, generative, or coherence checkpoint"
            )
    elif stage == OnboardingStage.SOURCE_REVISION:
        if effective_previous != OnboardingStage.COMPLETENESS_VERIFIED:
            raise ValueError("source revision requires a completeness-verified batch")
    elif stage == OnboardingStage.SCOPE_REVISION:
        if effective_previous != OnboardingStage.SOURCES_READY:
            raise ValueError("scope revision requires a sources-ready batch")
    elif stage != OnboardingStage.BLOCKED:
        if effective_previous == OnboardingStage.PUBLISHED:
            raise ValueError(f"{batch_id} is already published")
        expected = (
            ORDERED_STAGES[0]
            if effective_previous is None
            else ORDERED_STAGES[ORDERED_STAGES.index(effective_previous) + 1]
        )
        if stage != expected:
            raise ValueError(f"next legal stage for {batch_id} is {expected}")


def create_checkpoint_event(
    batch_id: str,
    stage: OnboardingStage,
    previous: OnboardingStage | None,
    evidence_ids: tuple[str, ...],
    note: str,
) -> ProgressEvent:
    """Create and validate a timestamped content-derived event without writing."""
    payload = {
        "batch_id": batch_id,
        "previous_stage": previous,
        "stage": stage,
        "recorded_at": datetime.now(UTC),
        "evidence_ids": evidence_ids,
        "note": note,
    }
    event = _progress_event(payload)
    return event


def validate_progressive_onboarding(root: Path = ONBOARDING_ROOT) -> list[str]:
    """Validate batch size, stage ordering, evidence closure, and phase sequencing."""
    plan = ProgressiveOnboardingPlan.model_validate(read_yaml(root / "plan.yaml"))
    events = load_progress_events(root / "progress_ledger.jsonl")
    errors: list[str] = []
    known = {batch.batch_id: batch for batch in plan.batches}
    last_effective: dict[str, OnboardingStage] = {}
    for event in events:
        if event.batch_id not in known:
            errors.append(f"unknown batch event: {event.batch_id}")
            continue
        if event.stage == OnboardingStage.REVISION:
            previous = last_effective.get(event.batch_id)
            if previous not in REVISION_ELIGIBLE_STAGES:
                errors.append(f"{event.batch_id}: revision cannot reopen stage {previous}")
            else:
                last_effective[event.batch_id] = OnboardingStage.DETERMINISTIC_VERIFIED
            continue
        if event.stage in NON_ADVANCING_STAGES:
            continue
        previous = last_effective.get(event.batch_id)
        if previous == OnboardingStage.PUBLISHED:
            errors.append(f"{event.batch_id}: stage recorded after publication")
            continue
        expected = (
            ORDERED_STAGES[0]
            if previous is None
            else ORDERED_STAGES[ORDERED_STAGES.index(previous) + 1]
        )
        if event.stage != expected:
            errors.append(f"{event.batch_id}: expected {expected}, found {event.stage}")
        last_effective[event.batch_id] = event.stage
    if plan.maximum_concurrent_batches != 1:
        errors.append("only one onboarding batch may be active")
    if any(len(batch.product_labels) > 3 or batch.maximum_documents > 3 for batch in plan.batches):
        errors.append("progressive batches exceed the preparation cap")
    if errors:
        raise ValueError("; ".join(errors))
    return [f"batches={len(plan.batches)}", f"events={len(events)}", "scale_execution=disabled"]


def _append_jsonl(path: Path, event: ProgressEvent) -> None:
    """Atomically replace the ledger with its prior bytes plus one immutable event."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_bytes() if path.exists() else b""
    payload = existing + json.dumps(event.model_dump(mode="json"), sort_keys=True).encode() + b"\n"
    with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _progress_event(payload: dict[str, Any]) -> ProgressEvent:
    """Normalize Pydantic JSON types before deriving a checkpoint identity."""
    provisional = ProgressEvent.model_construct(event_id="", **payload)
    identity = provisional.model_dump(mode="json", exclude={"event_id"})
    return ProgressEvent.model_validate(
        dict(event_id=stable_id("onboarding_progress", identity), **payload)
    )
