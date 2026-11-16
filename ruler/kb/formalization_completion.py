# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Reviewed formalization overlays and exact completion gates.

Published onboarding records remain immutable.  Review decisions are appended in a
separate hash-bound stream, and absent decisions are conservatively interpreted as
``source_only`` rather than as approved logic.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.ingestion.contracts import stable_id
from ruler.io import read_yaml
from ruler.kb.formalization import FormalizationState, TERMINAL_STATES
from ruler.paths import REPO_ROOT

REVIEWED_OVERLAY_FILE = (
    REPO_ROOT
    / "data"
    / "operations"
    / "formalization_waves"
    / "reviewed_overlays"
    / "domain-overlays.yaml"
)
ACTIVE_BATCH_ROOT = REPO_ROOT / "kb" / "releases" / "product_onboarding"


class CompletionContract(BaseModel):
    """Strict immutable base for reviewed classification records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MigrationFamily(StrEnum):
    """MIGRATE-001..006 semantic families; MIGRATE-007 is portfolio closure."""

    DEFINITION_SCOPE = "definition_scope"
    INCLUSION_BENEFIT = "inclusion_benefit"
    EXCLUSION_EXCEPTION = "exclusion_exception"
    QUANTITY_LIMIT_SERVICE_FEE = "quantity_limit_service_fee"
    TEMPORAL = "temporal"
    FEATURE_PRODUCT_RELATION = "feature_product_relation"


BASE_REQUIREMENTS = frozenset(
    {
        "typed_predicate_signature",
        "operational_semantics",
        "source_grounding",
        "replay_test",
        "compilation",
        "semantic_validation",
    }
)
MIGRATION_REQUIREMENTS: dict[MigrationFamily, frozenset[str]] = {
    MigrationFamily.DEFINITION_SCOPE: BASE_REQUIREMENTS
    | {"applicability_scope", "typed_subject_or_object", "boundary_counterexample"},
    MigrationFamily.INCLUSION_BENEFIT: BASE_REQUIREMENTS
    | {"activation_conditions", "benefit_consequence", "option_dependencies"},
    MigrationFamily.EXCLUSION_EXCEPTION: BASE_REQUIREMENTS
    | {"preserved_negation", "exception_precedence", "negative_test"},
    MigrationFamily.QUANTITY_LIMIT_SERVICE_FEE: BASE_REQUIREMENTS
    | {"typed_unit", "quantity_scope", "exact_boundary_test"},
    MigrationFamily.TEMPORAL: BASE_REQUIREMENTS
    | {"temporal_interval", "before_on_after_tests", "edition_applicability"},
    MigrationFamily.FEATURE_PRODUCT_RELATION: BASE_REQUIREMENTS
    | {"relation_predicate", "policy_clause_dependency", "catalogue_policy_separation"},
}


class AssertionInventoryItem(CompletionContract):
    """One published assertion or canonical policy record awaiting classification."""

    assertion_id: str
    origin: str
    assertion_kind: str
    provider: str
    product_family: str
    source_version_ids: tuple[str, ...] = ()


class TraceClosure(CompletionContract):
    """Forward and reverse trace evidence for one reviewed assertion."""

    source_version_ids: tuple[str, ...]
    source_span_ids: tuple[str, ...]
    logical_unit_ids: tuple[str, ...]
    atom_ids: tuple[str, ...]
    explicit_gap_reason: str | None = None

    @model_validator(mode="after")
    def trace_or_gap_is_explicit(self) -> "TraceClosure":
        """A trace cannot disappear merely because formalization is incomplete."""
        has_complete_trace = all(
            (
                self.source_version_ids,
                self.source_span_ids,
                self.logical_unit_ids,
                self.atom_ids,
            )
        )
        if not has_complete_trace and not self.explicit_gap_reason:
            raise ValueError("incomplete traces require an explicit_gap_reason")
        return self


class ReviewedClassification(CompletionContract):
    """One append-only classification event for an assertion."""

    overlay_id: str
    assertion_id: str
    revision: int = Field(ge=1)
    previous_overlay_id: str | None = None
    reviewed_at: datetime
    reviewer_id: str
    review_kind: str
    state: FormalizationState
    formalizable: bool
    modality: str
    migration_family: MigrationFamily
    requirement_evidence: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    trace: TraceClosure
    blockers: tuple[str, ...] = ()
    rationale: str
    human_approval_ref: str | None = None

    @model_validator(mode="after")
    def classification_is_hash_bound_and_honest(self) -> "ReviewedClassification":
        """Bind revisions to evidence and reserve validated for complete proof."""
        expected = stable_id("formalization_overlay", self.identity_payload())
        if self.overlay_id != expected:
            raise ValueError("overlay_id does not match reviewed classification content")
        if self.revision == 1 and self.previous_overlay_id is not None:
            raise ValueError("the first revision cannot declare a predecessor")
        if self.revision > 1 and self.previous_overlay_id is None:
            raise ValueError("later revisions require previous_overlay_id")
        if self.formalizable and self.state in {
            FormalizationState.REJECTED,
            FormalizationState.NON_FORMALIZABLE,
        }:
            raise ValueError(
                "formalizable assertions cannot terminate as rejected/non-formalizable"
            )
        if not self.formalizable and self.state == FormalizationState.VALIDATED:
            raise ValueError("non-formalizable assertions cannot be validated logic")
        unknown_requirements = sorted(
            set(self.requirement_evidence) - MIGRATION_REQUIREMENTS[self.migration_family]
        )
        if unknown_requirements:
            raise ValueError(
                f"requirement evidence is not declared for this migration family: "
                f"{unknown_requirements}"
            )
        if self.state == FormalizationState.APPROVED_LOGIC and not self.human_approval_ref:
            raise ValueError("approved_logic requires an explicit human approval reference")
        if self.state in {FormalizationState.COMPILED, FormalizationState.VALIDATED}:
            missing = self.missing_requirements
            if missing:
                raise ValueError(f"compiled/validated classification lacks requirements: {missing}")
            if self.trace.explicit_gap_reason:
                raise ValueError("compiled/validated classification cannot retain a trace gap")
        if self.state != FormalizationState.VALIDATED and not self.blockers:
            raise ValueError("non-validated classifications require explicit blockers")
        return self

    @property
    def missing_requirements(self) -> tuple[str, ...]:
        """Return required semantic evidence absent from this revision."""
        required = MIGRATION_REQUIREMENTS[self.migration_family]
        return tuple(sorted(name for name in required if not self.requirement_evidence.get(name)))

    def identity_payload(self) -> dict[str, Any]:
        """Return canonical append-only identity content."""
        return {
            "assertion_id": self.assertion_id,
            "revision": self.revision,
            "previous_overlay_id": self.previous_overlay_id,
            "reviewed_at": self.reviewed_at,
            "reviewer_id": self.reviewer_id,
            "review_kind": self.review_kind,
            "state": self.state,
            "formalizable": self.formalizable,
            "modality": self.modality,
            "migration_family": self.migration_family,
            "requirement_evidence": self.requirement_evidence,
            "trace": self.trace.model_dump(mode="python"),
            "blockers": self.blockers,
            "rationale": self.rationale,
            "human_approval_ref": self.human_approval_ref,
        }


class ReviewedOverlayStream(CompletionContract):
    """Append-only ordered overlay stream."""

    stream_version: int = 1
    stream_id: str
    decisions: tuple[ReviewedClassification, ...]


class EffectiveClassification(CompletionContract):
    """Latest reviewed state or conservative default for one inventory item."""

    assertion: AssertionInventoryItem
    state: FormalizationState
    formalizable: bool | None
    reviewed: bool
    migration_family: MigrationFamily | None = None
    missing_requirements: tuple[str, ...] = ()
    trace_closed: bool = False
    blocker: str | None = None


class CompletionReport(CompletionContract):
    """Exactly reconciled completion result for DONE-001..003."""

    published_assertions: int
    canonical_policy_records: int
    total_inventory: int
    state_counts: dict[str, int]
    terminal_items: int
    formalizable_items: int
    validated_formalizable_items: int
    unresolved_items: int
    trace_closed_items: int
    provider_product_scopes: int
    closed_provider_product_scopes: int
    reviewed_migration_family_counts: dict[str, int]
    inventory_closed: bool
    formalizable_coverage_complete: bool
    document_trace_closed: bool
    complete: bool
    blockers: tuple[str, ...]


def load_published_assertion_inventory() -> list[AssertionInventoryItem]:
    """Load all active onboarding assertions without changing their states."""
    pointers = [ACTIVE_BATCH_ROOT / "active_batch_01.yaml"]
    pointers.extend(sorted((ACTIVE_BATCH_ROOT / "active_batches").glob("*.yaml")))
    items: list[AssertionInventoryItem] = []
    for pointer_path in pointers:
        if not pointer_path.exists():
            continue
        pointer = read_yaml(pointer_path)
        assertions = read_yaml(REPO_ROOT / pointer["assertions"])
        items.extend(
            AssertionInventoryItem(
                assertion_id=item["assertion_id"],
                origin=f"published_onboarding:{pointer_path.stem}",
                assertion_kind=item["assertion_kind"],
                provider=item["provider"],
                product_family=item["product_family"],
                source_version_ids=tuple(item.get("source_version_ids", [])),
            )
            for item in assertions
        )
    duplicates = sorted(
        assertion_id
        for assertion_id, count in Counter(item.assertion_id for item in items).items()
        if count > 1
    )
    if duplicates:
        raise ValueError(f"duplicate published assertion IDs: {duplicates}")
    return items


def load_reviewed_overlay_stream(
    path: Path = REVIEWED_OVERLAY_FILE,
) -> ReviewedOverlayStream:
    """Load the checked-in append-only review stream."""
    return ReviewedOverlayStream.model_validate(read_yaml(path))


def validate_overlay_stream(
    stream: ReviewedOverlayStream,
    inventory: list[AssertionInventoryItem],
) -> list[str]:
    """Validate append-only revision chains and inventory membership."""
    errors: list[str] = []
    inventory_ids = {item.assertion_id for item in inventory}
    by_assertion: dict[str, list[ReviewedClassification]] = defaultdict(list)
    overlay_ids: set[str] = set()
    for decision in stream.decisions:
        if decision.overlay_id in overlay_ids:
            errors.append(f"duplicate overlay ID: {decision.overlay_id}")
        overlay_ids.add(decision.overlay_id)
        if decision.assertion_id not in inventory_ids:
            errors.append(f"overlay references unknown assertion: {decision.assertion_id}")
        by_assertion[decision.assertion_id].append(decision)
    for assertion_id, decisions in by_assertion.items():
        expected_revision = 1
        previous: ReviewedClassification | None = None
        for decision in decisions:
            if decision.revision != expected_revision:
                errors.append(f"{assertion_id}: overlay revisions must be contiguous and ordered")
            if previous and decision.previous_overlay_id != previous.overlay_id:
                errors.append(f"{assertion_id}: broken previous_overlay_id chain")
            if previous and decision.reviewed_at < previous.reviewed_at:
                errors.append(f"{assertion_id}: reviewed_at must be append-only chronological")
            previous = decision
            expected_revision += 1
    return errors


def build_effective_classifications(
    inventory: list[AssertionInventoryItem],
    stream: ReviewedOverlayStream,
) -> list[EffectiveClassification]:
    """Overlay reviewed decisions; default every untouched record to unresolved source-only."""
    errors = validate_overlay_stream(stream, inventory)
    if errors:
        raise ValueError("reviewed overlay validation failed:\n- " + "\n- ".join(errors))
    latest: dict[str, ReviewedClassification] = {}
    for decision in stream.decisions:
        latest[decision.assertion_id] = decision
    effective: list[EffectiveClassification] = []
    for assertion in inventory:
        decision = latest.get(assertion.assertion_id)
        if decision is None:
            effective.append(
                EffectiveClassification(
                    assertion=assertion,
                    state=FormalizationState.SOURCE_ONLY,
                    formalizable=None,
                    reviewed=False,
                    blocker="no reviewed formalization classification overlay",
                )
            )
            continue
        source_trace_exists = bool(
            decision.trace.source_version_ids and decision.trace.source_span_ids
        )
        logic_trace_exists = bool(decision.trace.logical_unit_ids and decision.trace.atom_ids)
        trace_closed = source_trace_exists and (
            logic_trace_exists or bool(decision.trace.explicit_gap_reason)
        )
        effective.append(
            EffectiveClassification(
                assertion=assertion,
                state=decision.state,
                formalizable=decision.formalizable,
                reviewed=True,
                migration_family=decision.migration_family,
                missing_requirements=decision.missing_requirements,
                trace_closed=trace_closed,
                blocker="; ".join(decision.blockers) or None,
            )
        )
    return effective


def evaluate_completion(
    effective: list[EffectiveClassification],
) -> CompletionReport:
    """Evaluate DONE-001..003 with exact numerator/denominator reconciliation."""
    state_counts = Counter(item.state.value for item in effective)
    total = len(effective)
    if sum(state_counts.values()) != total:
        raise ValueError("formalization state totals do not reconcile")
    published = sum(item.assertion.origin.startswith("published_onboarding:") for item in effective)
    canonical = total - published
    terminal = sum(item.state in TERMINAL_STATES for item in effective)
    formalizable = sum(item.formalizable is True for item in effective)
    validated = sum(
        item.formalizable is True and item.state == FormalizationState.VALIDATED
        for item in effective
    )
    unresolved = total - terminal
    trace_closed = sum(item.trace_closed for item in effective)
    inventory_closed = terminal == total
    formalizable_complete = validated == formalizable
    document_trace_closed = trace_closed == total
    scopes: dict[tuple[str, str], list[EffectiveClassification]] = defaultdict(list)
    for item in effective:
        scopes[(item.assertion.provider, item.assertion.product_family)].append(item)
    closed_scopes = sum(
        all(
            item.state in TERMINAL_STATES
            and item.trace_closed
            and (item.formalizable is not True or item.state == FormalizationState.VALIDATED)
            for item in members
        )
        for members in scopes.values()
    )
    family_counts = Counter(
        item.migration_family.value for item in effective if item.migration_family is not None
    )
    blockers: list[str] = ["no published assertions configured"] if total == 0 else []
    if not inventory_closed:
        blockers.append(f"{unresolved} inventory items lack terminal reviewed states")
    if not formalizable_complete:
        blockers.append(f"validated formalizable coverage is {validated}/{formalizable}")
    if not document_trace_closed:
        blockers.append(f"document trace closure is {trace_closed}/{total}")
    if closed_scopes != len(scopes):
        blockers.append(f"provider/product-family closure is {closed_scopes}/{len(scopes)}")
    return CompletionReport(
        published_assertions=published,
        canonical_policy_records=canonical,
        total_inventory=total,
        state_counts=dict(sorted(state_counts.items())),
        terminal_items=terminal,
        formalizable_items=formalizable,
        validated_formalizable_items=validated,
        unresolved_items=unresolved,
        trace_closed_items=trace_closed,
        provider_product_scopes=len(scopes),
        closed_provider_product_scopes=closed_scopes,
        reviewed_migration_family_counts=dict(sorted(family_counts.items())),
        inventory_closed=inventory_closed,
        formalizable_coverage_complete=formalizable_complete,
        document_trace_closed=document_trace_closed,
        complete=(
            total > 0
            and inventory_closed
            and formalizable_complete
            and document_trace_closed
            and closed_scopes == len(scopes)
        ),
        blockers=tuple(blockers),
    )


def build_current_completion_report() -> CompletionReport:
    """Build the honest current report; this function is read-only."""
    inventory = load_published_assertion_inventory()
    stream = load_reviewed_overlay_stream()
    return evaluate_completion(build_effective_classifications(inventory, stream))


def validate_formalization_completion() -> list[str]:
    """Validate overlay integrity and exact, conservative completion accounting."""
    inventory = load_published_assertion_inventory()
    stream = load_reviewed_overlay_stream()
    errors = validate_overlay_stream(stream, inventory)
    if errors:
        raise ValueError("reviewed overlay validation failed:\n- " + "\n- ".join(errors))
    report = evaluate_completion(build_effective_classifications(inventory, stream))
    if report.total_inventory != len(inventory):
        raise ValueError("completion inventory total does not reconcile")
    if sum(report.state_counts.values()) != report.total_inventory:
        raise ValueError("completion state counts do not reconcile")
    if report.complete and report.blockers:
        raise ValueError("a complete report cannot retain blockers")
    if not report.complete and not report.blockers:
        raise ValueError("an incomplete report must expose blockers")
    return [
        f"inventory={report.total_inventory}",
        f"terminal={report.terminal_items}",
        f"validated_formalizable={report.validated_formalizable_items}/{report.formalizable_items}",
        f"trace_closed={report.trace_closed_items}/{report.total_inventory}",
        f"scopes_closed={report.closed_provider_product_scopes}/{report.provider_product_scopes}",
        f"complete={str(report.complete).lower()}",
    ]
