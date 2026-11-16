# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Honest formalization inventory, vocabulary, contracts, and coverage semantics.

This module deliberately keeps evidence approval separate from executable-logic state.
An approved source record therefore remains ``source_only`` until a logical unit passes
the explicit formalization transitions.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.io import read_yaml
from ruler.kb.repository import ReleasedAssertion
from ruler.paths import REPO_ROOT


class FormalizationState(StrEnum):
    """Lifecycle state of one published assertion, never of a pipeline artifact."""

    SOURCE_ONLY = "source_only"
    NORMALIZED = "normalized"
    CANDIDATE_LOGIC = "candidate_logic"
    REVIEW_REQUIRED = "review_required"
    APPROVED_LOGIC = "approved_logic"
    COMPILED = "compiled"
    VALIDATED = "validated"
    REJECTED = "rejected"
    NON_FORMALIZABLE = "non_formalizable"


class FormalizationModality(StrEnum):
    """Closed operational modalities used for inventory and coverage reporting."""

    FACT = "fact"
    DEFINITION = "definition"
    IMPLICATION = "implication"
    CONSTRAINT = "constraint"
    EXCLUSION = "exclusion"
    EXCEPTION = "exception"
    PRECEDENCE_RULE = "precedence_rule"
    LIMIT = "limit"
    TEMPORAL_RULE = "temporal_rule"
    UNKNOWN = "unknown"


TERMINAL_STATES = frozenset(
    {
        FormalizationState.VALIDATED,
        FormalizationState.REJECTED,
        FormalizationState.NON_FORMALIZABLE,
    }
)
LOGIC_STATES = frozenset(
    {
        FormalizationState.CANDIDATE_LOGIC,
        FormalizationState.REVIEW_REQUIRED,
        FormalizationState.APPROVED_LOGIC,
        FormalizationState.COMPILED,
        FormalizationState.VALIDATED,
    }
)
APPROVED_STATES = frozenset(
    {
        FormalizationState.APPROVED_LOGIC,
        FormalizationState.COMPILED,
        FormalizationState.VALIDATED,
    }
)

_ALLOWED_TRANSITIONS: dict[FormalizationState, frozenset[FormalizationState]] = {
    FormalizationState.SOURCE_ONLY: frozenset(
        {
            FormalizationState.NORMALIZED,
            FormalizationState.REJECTED,
            FormalizationState.NON_FORMALIZABLE,
        }
    ),
    FormalizationState.NORMALIZED: frozenset(
        {
            FormalizationState.CANDIDATE_LOGIC,
            FormalizationState.REVIEW_REQUIRED,
            FormalizationState.REJECTED,
            FormalizationState.NON_FORMALIZABLE,
        }
    ),
    FormalizationState.CANDIDATE_LOGIC: frozenset(
        {
            FormalizationState.REVIEW_REQUIRED,
            FormalizationState.APPROVED_LOGIC,
            FormalizationState.REJECTED,
        }
    ),
    FormalizationState.REVIEW_REQUIRED: frozenset(
        {
            FormalizationState.CANDIDATE_LOGIC,
            FormalizationState.APPROVED_LOGIC,
            FormalizationState.REJECTED,
            FormalizationState.NON_FORMALIZABLE,
        }
    ),
    FormalizationState.APPROVED_LOGIC: frozenset(
        {
            FormalizationState.COMPILED,
            FormalizationState.REVIEW_REQUIRED,
            FormalizationState.REJECTED,
        }
    ),
    FormalizationState.COMPILED: frozenset(
        {
            FormalizationState.VALIDATED,
            FormalizationState.REVIEW_REQUIRED,
            FormalizationState.REJECTED,
        }
    ),
    FormalizationState.VALIDATED: frozenset({FormalizationState.REVIEW_REQUIRED}),
    FormalizationState.REJECTED: frozenset(),
    FormalizationState.NON_FORMALIZABLE: frozenset(),
}


def may_transition(current: FormalizationState, target: FormalizationState) -> bool:
    """Return whether an explicit lifecycle transition is legal."""
    return current == target or target in _ALLOWED_TRANSITIONS[current]


class UncertaintyKind(StrEnum):
    """Material uncertainty classes that must remain visible to promotion gates."""

    NONE = "none"
    UNKNOWN = "unknown"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"
    UNDERSPECIFIED = "underspecified"
    REVIEW_REQUIRED = "review_required"


class Uncertainty(BaseModel):
    """Explicit uncertainty; unresolved material uncertainty blocks approval."""

    model_config = ConfigDict(extra="forbid")

    kind: UncertaintyKind = UncertaintyKind.NONE
    material: bool = False
    resolved: bool = True
    rationale: str = ""
    resolution_ref: str | None = None

    @model_validator(mode="after")
    def resolution_is_evidenced(self) -> "Uncertainty":
        if self.kind == UncertaintyKind.NONE:
            if self.material or not self.resolved:
                raise ValueError("uncertainty kind 'none' cannot be material or unresolved")
        elif not self.rationale.strip():
            raise ValueError("uncertainty requires a rationale")
        if self.resolved and self.kind != UncertaintyKind.NONE and not self.resolution_ref:
            raise ValueError("resolved uncertainty requires resolution_ref")
        return self

    @property
    def blocks_promotion(self) -> bool:
        """Whether this uncertainty prevents approved executable truth."""
        return self.kind != UncertaintyKind.NONE and self.material and not self.resolved


class SourceSpanRef(BaseModel):
    """Smallest immutable evidence link required by an inventory item."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    source_version: str
    section_id: str
    span_id: str
    span_sha256: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class InventoryItem(BaseModel):
    """Exactly one inventory record for one published assertion."""

    model_config = ConfigDict(extra="forbid")

    assertion_id: str
    assertion_kind: str
    provider: str
    product_family: str
    clause_type: str
    modality: FormalizationModality
    source_modality: str | None = None
    source_span: SourceSpanRef
    state: FormalizationState = FormalizationState.SOURCE_ONLY
    target_formalism: Literal["asp", "prolog", "asp_prolog", "none"]
    predicate_family: str | None = None
    logical_unit_ids: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    owner: str
    source_record_review: Literal["unreviewed", "approved", "rejected"] = "unreviewed"
    uncertainty: Uncertainty = Field(default_factory=Uncertainty)
    terminal_reason: str | None = None
    metadata_projection: bool = False

    @model_validator(mode="after")
    def state_has_required_evidence(self) -> "InventoryItem":
        if self.metadata_projection and self.state in LOGIC_STATES:
            raise ValueError("generic metadata projections cannot count as domain logic")
        if self.state in LOGIC_STATES and not self.logical_unit_ids:
            raise ValueError("logic states require at least one logical_unit_id")
        if self.state in APPROVED_STATES:
            if self.target_formalism == "none" or not self.predicate_family:
                raise ValueError("approved logic requires a target formalism and predicate family")
            if self.uncertainty.blocks_promotion:
                raise ValueError("unresolved material uncertainty blocks approved logic")
        if self.state in {FormalizationState.REJECTED, FormalizationState.NON_FORMALIZABLE}:
            if not self.terminal_reason:
                raise ValueError("rejected and non-formalizable items require a terminal_reason")
        elif self.terminal_reason:
            raise ValueError("terminal_reason is only valid for rejected or non-formalizable items")
        if self.state == FormalizationState.NON_FORMALIZABLE and self.target_formalism != "none":
            raise ValueError("non-formalizable items must use target_formalism='none'")
        return self


class FormalizationInventory(BaseModel):
    """A complete, unique inventory with an optional expected release total."""

    model_config = ConfigDict(extra="forbid")

    inventory_id: str
    release_id: str
    expected_assertion_count: int = Field(ge=0)
    items: list[InventoryItem]

    @model_validator(mode="after")
    def assertions_are_unique_and_complete(self) -> "FormalizationInventory":
        ids = [item.assertion_id for item in self.items]
        duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate inventory assertions: {', '.join(duplicates)}")
        if len(ids) != self.expected_assertion_count:
            raise ValueError(
                f"inventory has {len(ids)} assertions; expected {self.expected_assertion_count}"
            )
        return self


class CoverageCounts(BaseModel):
    """Reconciled counts over source assertions, never intermediate artifacts."""

    model_config = ConfigDict(extra="forbid")

    source_assertions: int
    formalizable_assertions: int
    approved_logical_units: int
    compiled_units: int
    validated_units: int
    validated_assertions: int
    rejected_units: int
    non_formalizable_units: int
    unresolved_units: int


class CoverageSlice(BaseModel):
    """Coverage for a dimension value with an explicit denominator."""

    model_config = ConfigDict(extra="forbid")

    dimension: Literal["provider", "product_family", "clause_type", "modality"]
    value: str
    counts: CoverageCounts
    validated_percentage_of_formalizable: float | None


class CoverageReport(BaseModel):
    """Coverage totals and required dimensional breakdowns."""

    model_config = ConfigDict(extra="forbid")

    inventory_id: str
    denominator_definition: str
    numerator_definition: str
    totals: CoverageCounts
    slices: list[CoverageSlice]


def build_coverage_report(inventory: FormalizationInventory) -> CoverageReport:
    """Build exact, assertion-based coverage totals and four dimensional views."""

    def counts(items: Iterable[InventoryItem]) -> CoverageCounts:
        rows = list(items)
        non_formalizable = sum(item.state == FormalizationState.NON_FORMALIZABLE for item in rows)
        return CoverageCounts(
            source_assertions=len(rows),
            formalizable_assertions=len(rows) - non_formalizable,
            approved_logical_units=sum(
                len(item.logical_unit_ids) for item in rows if item.state in APPROVED_STATES
            ),
            compiled_units=sum(
                len(item.logical_unit_ids)
                for item in rows
                if item.state in {FormalizationState.COMPILED, FormalizationState.VALIDATED}
            ),
            validated_units=sum(
                len(item.logical_unit_ids)
                for item in rows
                if item.state == FormalizationState.VALIDATED
            ),
            validated_assertions=sum(item.state == FormalizationState.VALIDATED for item in rows),
            rejected_units=sum(item.state == FormalizationState.REJECTED for item in rows),
            non_formalizable_units=non_formalizable,
            unresolved_units=sum(item.state not in TERMINAL_STATES for item in rows),
        )

    slices: list[CoverageSlice] = []
    for dimension in ("provider", "product_family", "clause_type", "modality"):
        groups: dict[str, list[InventoryItem]] = defaultdict(list)
        for item in inventory.items:
            groups[getattr(item, dimension)].append(item)
        for value in sorted(groups):
            dimension_counts = counts(groups[value])
            denominator = dimension_counts.formalizable_assertions
            percentage = (
                round(100 * dimension_counts.validated_assertions / denominator, 2)
                if denominator
                else None
            )
            slices.append(
                CoverageSlice(
                    dimension=dimension,  # type: ignore[arg-type]
                    value=value,
                    counts=dimension_counts,
                    validated_percentage_of_formalizable=percentage,
                )
            )
    return CoverageReport(
        inventory_id=inventory.inventory_id,
        denominator_definition=(
            "published source assertions excluding items reviewed as non_formalizable"
        ),
        numerator_definition="source assertions whose formalization state is validated",
        totals=counts(inventory.items),
        slices=slices,
    )


def load_active_onboarding_inventory(
    repository_root: Path = REPO_ROOT,
    *,
    classifications: Mapping[str, Mapping[str, Any]] | None = None,
) -> FormalizationInventory:
    """Enumerate every assertion in all active progressive-onboarding releases.

    ``classifications`` is an optional reviewed overlay keyed by assertion ID. In its
    absence every approved source record stays ``source_only``: publication approval
    does not imply logical formalization. Both the legacy active first-batch pointer and
    the current active-batches directory are included; duplicate assertion IDs fail.
    """
    release_root = repository_root / "kb" / "releases" / "product_onboarding"
    pointers = sorted((release_root / "active_batches").glob("*.yaml"))
    legacy_pointer = release_root / "active_batch_01.yaml"
    if legacy_pointer.exists():
        pointers.append(legacy_pointer)

    rows: list[tuple[ReleasedAssertion, str, str]] = []
    release_ids: list[str] = []
    for pointer in pointers:
        manifest = read_yaml(pointer)
        batch_id = str(manifest.get("batch_id") or pointer.stem)
        release_id = str(manifest["kb_release_id"])
        release_ids.append(release_id)
        release_manifest_path = _repository_path(repository_root, str(manifest["manifest"]))
        release_manifest = read_yaml(release_manifest_path)
        if release_manifest.get("release_status") != "published":
            raise ValueError(f"active batch {batch_id} does not reference a published release")
        if release_manifest.get("kb_release_id") != release_id:
            raise ValueError(
                f"active batch {batch_id} release identity does not match its manifest"
            )
        assertions_path = _repository_path(repository_root, str(manifest["assertions"]))
        assertions = [ReleasedAssertion.model_validate(row) for row in read_yaml(assertions_path)]
        rows.extend((assertion, batch_id, release_id) for assertion in assertions)

    ids = [row[0].assertion_id for row in rows]
    duplicates = sorted(key for key, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise ValueError(f"active releases contain duplicate assertions: {', '.join(duplicates)}")

    overlays = classifications or {}
    unknown_overlays = sorted(set(overlays) - set(ids))
    if unknown_overlays:
        raise ValueError(
            f"classification overlay has unknown assertions: {', '.join(unknown_overlays)}"
        )

    items = [
        _inventory_item_from_released(assertion, batch_id, overlays.get(assertion.assertion_id, {}))
        for assertion, batch_id, _ in rows
    ]
    release_fingerprint = "+".join(sorted(release_ids))
    return FormalizationInventory(
        inventory_id=f"active_product_onboarding:{len(items)}",
        release_id=release_fingerprint,
        expected_assertion_count=len(items),
        items=sorted(items, key=lambda item: item.assertion_id),
    )


def _repository_path(repository_root: Path, relative_path: str) -> Path:
    path = (repository_root / relative_path).resolve()
    try:
        path.relative_to(repository_root.resolve())
    except ValueError as exc:
        raise ValueError(f"active release path escapes repository: {path}") from exc
    return path


def _inventory_item_from_released(
    assertion: ReleasedAssertion,
    batch_id: str,
    overlay: Mapping[str, Any],
) -> InventoryItem:
    record = assertion.payload.get("record", {})
    if not isinstance(record, dict):
        record = {}
    source_anchor = record.get("source_anchor", {})
    if not isinstance(source_anchor, dict):
        source_anchor = {}
    raw_hash = record.get("raw_text_hash")
    has_exact_span = bool(source_anchor.get("span") and raw_hash)
    span_hash = raw_hash if has_exact_span else assertion.payload_sha256
    source_version = assertion.source_version_ids[0]
    default_blockers = [] if has_exact_span else ["exact_document_span_pending"]
    clause_type = str(record.get("clause_type") or assertion.assertion_kind)
    source_modality = record.get("modality")
    modality = _normalized_modality(assertion.assertion_kind, clause_type)
    family = _predicate_family(assertion.assertion_kind, clause_type)
    base: dict[str, Any] = {
        "assertion_id": assertion.assertion_id,
        "assertion_kind": assertion.assertion_kind,
        "provider": assertion.provider,
        "product_family": assertion.product_family,
        "clause_type": clause_type,
        "modality": modality,
        "source_modality": str(source_modality) if source_modality else None,
        "source_span": SourceSpanRef(
            document_id=str(source_anchor.get("source_id") or source_version),
            source_version=source_version,
            section_id=str(source_anchor.get("section") or assertion.assertion_kind),
            span_id=str(source_anchor.get("span") or f"assertion_payload:{assertion.assertion_id}"),
            span_sha256=str(span_hash),
        ),
        "state": FormalizationState.SOURCE_ONLY,
        "target_formalism": "asp",
        "predicate_family": family,
        "blockers": default_blockers,
        "owner": f"formalization-wave:{batch_id}",
        "source_record_review": "approved",
    }
    base.update(dict(overlay))
    return InventoryItem.model_validate(base)


def _normalized_modality(assertion_kind: str, clause_type: str) -> FormalizationModality:
    by_clause = {
        "definition": FormalizationModality.DEFINITION,
        "coverage_grant": FormalizationModality.IMPLICATION,
        "inclusion": FormalizationModality.IMPLICATION,
        "exclusion": FormalizationModality.EXCLUSION,
        "exception_to_exclusion": FormalizationModality.EXCEPTION,
        "exception": FormalizationModality.EXCEPTION,
        "limit": FormalizationModality.LIMIT,
        "service_fee": FormalizationModality.LIMIT,
        "duty": FormalizationModality.CONSTRAINT,
        "temporal_rule": FormalizationModality.TEMPORAL_RULE,
        "option_dependency": FormalizationModality.IMPLICATION,
        "precedence": FormalizationModality.PRECEDENCE_RULE,
    }
    by_kind = {
        "rule": FormalizationModality.IMPLICATION,
        "definition": FormalizationModality.DEFINITION,
        "condition": FormalizationModality.IMPLICATION,
        "exclusion": FormalizationModality.EXCLUSION,
        "exception": FormalizationModality.EXCEPTION,
        "limit": FormalizationModality.LIMIT,
        "precedence": FormalizationModality.PRECEDENCE_RULE,
    }
    return by_clause.get(clause_type, by_kind.get(assertion_kind, FormalizationModality.UNKNOWN))


def _predicate_family(assertion_kind: str, clause_type: str) -> str:
    if assertion_kind == "feature":
        return "option"
    aliases = {
        "coverage_grant": "coverage",
        "inclusion": "coverage",
        "temporal_rule": "time",
        "option_dependency": "option",
        "definition": "document_applicability",
    }
    return aliases.get(clause_type, clause_type or assertion_kind)


class ValueType(StrEnum):
    """Closed value domains available to approved predicate signatures."""

    ENTITY_ID = "entity_id"
    CLAIM_ID = "claim_id"
    POLICY_ID = "policy_id"
    DOCUMENT_ID = "document_id"
    SUBJECT = "subject"
    COVERED_OBJECT = "covered_object"
    BENEFIT = "benefit"
    COVERAGE = "coverage"
    EVENT = "event"
    OPTION = "option"
    GEOGRAPHY = "geography"
    CURRENCY = "currency"
    MONEY = "money"
    PERCENTAGE = "percentage"
    DURATION = "duration"
    COUNT = "count"
    DATE = "date"
    TIME_INTERVAL = "time_interval"
    SYMBOL = "symbol"
    BOOLEAN = "boolean"


class WorldAssumption(StrEnum):
    """Predicate-level treatment of absent knowledge."""

    OPEN = "open"
    CLOSED = "closed"


class PredicateSignature(BaseModel):
    """Approved canonical predicate declaration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    argument_names: tuple[str, ...]
    argument_types: tuple[ValueType, ...]
    family: str
    world_assumption: WorldAssumption
    units: tuple[str | None, ...] = ()
    value_domains: tuple[tuple[str, ...] | None, ...] = ()
    approved: bool = True

    @model_validator(mode="after")
    def arities_match(self) -> "PredicateSignature":
        arity = len(self.argument_names)
        if len(self.argument_types) != arity:
            raise ValueError("argument_names and argument_types must have equal arity")
        if self.units and len(self.units) != arity:
            raise ValueError("units must be empty or match predicate arity")
        if self.value_domains and len(self.value_domains) != arity:
            raise ValueError("value_domains must be empty or match predicate arity")
        return self

    @property
    def arity(self) -> int:
        return len(self.argument_names)


def _signature(
    name: str,
    names: tuple[str, ...],
    types: tuple[ValueType, ...],
    family: str,
    *,
    world: WorldAssumption = WorldAssumption.OPEN,
    units: tuple[str | None, ...] = (),
    value_domains: tuple[tuple[str, ...] | None, ...] = (),
) -> PredicateSignature:
    return PredicateSignature(
        name=name,
        argument_names=names,
        argument_types=types,
        family=family,
        world_assumption=world,
        units=units or tuple(None for _ in types),
        value_domains=value_domains or tuple(None for _ in types),
    )


# The minimum complete vocabulary families required for policy clauses. Product-specific
# predicates must be mapped onto these signatures or be explicitly registered and approved.
CANONICAL_PREDICATES: tuple[PredicateSignature, ...] = (
    _signature(
        "benefit_applies", ("claim", "benefit"), (ValueType.CLAIM_ID, ValueType.BENEFIT), "benefit"
    ),
    _signature(
        "coverage_applies",
        ("claim", "coverage"),
        (ValueType.CLAIM_ID, ValueType.COVERAGE),
        "coverage",
    ),
    _signature(
        "coverage_limit",
        ("policy", "coverage", "amount", "currency"),
        (ValueType.POLICY_ID, ValueType.COVERAGE, ValueType.MONEY, ValueType.CURRENCY),
        "limit",
        units=(None, None, "currency_minor_units", "iso_4217"),
        value_domains=(None, None, None, ("CHF", "EUR", "USD")),
    ),
    _signature(
        "service_fee_applies",
        ("claim", "coverage", "amount", "currency"),
        (ValueType.CLAIM_ID, ValueType.COVERAGE, ValueType.MONEY, ValueType.CURRENCY),
        "service_fee",
        units=(None, None, "currency_minor_units", "iso_4217"),
        value_domains=(None, None, None, ("CHF", "EUR", "USD")),
    ),
    _signature(
        "excluded_event",
        ("policy", "event"),
        (ValueType.POLICY_ID, ValueType.EVENT),
        "exclusion",
        world=WorldAssumption.CLOSED,
    ),
    _signature(
        "exception_applies",
        ("claim", "exception"),
        (ValueType.CLAIM_ID, ValueType.SYMBOL),
        "exception",
    ),
    _signature(
        "eligible_subject",
        ("policy", "subject"),
        (ValueType.POLICY_ID, ValueType.SUBJECT),
        "eligibility",
    ),
    _signature(
        "contract_subject",
        ("policy", "subject"),
        (ValueType.POLICY_ID, ValueType.SUBJECT),
        "contract_subject",
    ),
    _signature(
        "covered_object",
        ("policy", "object"),
        (ValueType.POLICY_ID, ValueType.COVERED_OBJECT),
        "covered_object",
    ),
    _signature(
        "within_geography",
        ("event", "geography"),
        (ValueType.EVENT, ValueType.GEOGRAPHY),
        "geography",
    ),
    _signature(
        "within_interval", ("event", "interval"), (ValueType.EVENT, ValueType.TIME_INTERVAL), "time"
    ),
    _signature(
        "duty_satisfied",
        ("claim", "duty"),
        (ValueType.CLAIM_ID, ValueType.SYMBOL),
        "duty",
        world=WorldAssumption.CLOSED,
    ),
    _signature(
        "takes_precedence",
        ("higher_clause", "lower_clause"),
        (ValueType.SYMBOL, ValueType.SYMBOL),
        "precedence",
    ),
    _signature(
        "document_applies",
        ("document", "policy"),
        (ValueType.DOCUMENT_ID, ValueType.POLICY_ID),
        "document_applicability",
    ),
    _signature(
        "option_selected",
        ("policy", "option"),
        (ValueType.POLICY_ID, ValueType.OPTION),
        "option",
        world=WorldAssumption.CLOSED,
    ),
)


class PredicateRegistry(BaseModel):
    """Registry that rejects ad-hoc or unapproved predicate use."""

    model_config = ConfigDict(extra="forbid")

    signatures: tuple[PredicateSignature, ...] = CANONICAL_PREDICATES

    @model_validator(mode="after")
    def names_are_unique(self) -> "PredicateRegistry":
        names = [signature.name for signature in self.signatures]
        duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate predicate signatures: {', '.join(duplicates)}")
        return self

    def require(self, name: str) -> PredicateSignature:
        """Resolve an approved signature; fail closed on ad-hoc predicates."""
        for signature in self.signatures:
            if signature.name == name and signature.approved:
                return signature
        raise ValueError(f"undeclared or unapproved predicate: {name}")


class ClauseTranslationContract(BaseModel):
    """Deterministic clause-to-IR shape plus four mandatory fixture classes."""

    model_config = ConfigDict(extra="forbid")

    clause_type: str
    modality: str
    head_family: str | None
    body_families: tuple[str, ...]
    split_on: tuple[str, ...]
    required_fixture_kinds: tuple[
        Literal["positive", "negative", "boundary", "counterexample"], ...
    ]
    promotion_requirements: tuple[str, ...]

    @model_validator(mode="after")
    def all_fixture_classes_exist(self) -> "ClauseTranslationContract":
        expected = {"positive", "negative", "boundary", "counterexample"}
        if set(self.required_fixture_kinds) != expected:
            raise ValueError("translation contracts require all four fixture classes")
        return self


class ClauseContractFixture(BaseModel):
    """Executable contract expectation, separate from any source prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str
    clause_type: str
    fixture_kind: Literal["positive", "negative", "boundary", "counterexample"]
    input_shape: str
    expected_decision: Literal["compile", "reject", "hold_for_review"]


def _contract(
    clause_type: str,
    modality: str,
    head_family: str | None,
    body_families: tuple[str, ...],
    *,
    split_on: tuple[str, ...] = ("independent consequence",),
    extra: tuple[str, ...] = (),
) -> ClauseTranslationContract:
    return ClauseTranslationContract(
        clause_type=clause_type,
        modality=modality,
        head_family=head_family,
        body_families=body_families,
        split_on=split_on,
        required_fixture_kinds=("positive", "negative", "boundary", "counterexample"),
        promotion_requirements=("exact_source_span", "approved_predicates", "semantic_review")
        + extra,
    )


CLAUSE_TRANSLATION_CONTRACTS: tuple[ClauseTranslationContract, ...] = (
    _contract("definition", "definition", "eligibility", ("document_applicability",)),
    _contract("inclusion", "implication", "coverage", ("eligibility", "document_applicability")),
    _contract(
        "exclusion",
        "exclusion",
        "exclusion",
        ("document_applicability",),
        extra=("explicit_negation",),
    ),
    _contract("obligation", "constraint", "duty", ("coverage",), extra=("deadline_if_present",)),
    _contract("permission", "implication", "coverage", ("eligibility",)),
    _contract("limit", "limit", "limit", ("coverage",), extra=("typed_quantity", "scope")),
    _contract(
        "service_fee", "limit", "service_fee", ("coverage",), extra=("typed_quantity", "scope")
    ),
    _contract("temporal", "temporal_rule", "time", ("coverage",), extra=("closed_open_bounds",)),
    _contract("precedence", "precedence_rule", "precedence", ("document_applicability",)),
    _contract(
        "cross_reference", "definition", "document_applicability", (), extra=("resolved_target",)
    ),
    _contract("exception", "exception", "exception", ("exclusion",), extra=("exception_target",)),
)


CLAUSE_CONTRACT_FIXTURES: tuple[ClauseContractFixture, ...] = tuple(
    ClauseContractFixture.model_validate(
        dict(
            fixture_id=f"{contract.clause_type}:{fixture_kind}",
            clause_type=contract.clause_type,
            fixture_kind=fixture_kind,
            input_shape={
                "positive": "all required typed fields and exact source grounding are present",
                "negative": "a required operational condition is absent",
                "boundary": "all typed boundary values are exact and scope-preserving",
                "counterexample": "candidate widens scope or erases an exception",
            }[fixture_kind],
            expected_decision={
                "positive": "compile",
                "negative": "reject",
                "boundary": "compile",
                "counterexample": "hold_for_review",
            }[fixture_kind],
        )
    )
    for contract in CLAUSE_TRANSLATION_CONTRACTS
    for fixture_kind in contract.required_fixture_kinds
)


def require_translation_contract(clause_type: str) -> ClauseTranslationContract:
    """Resolve a deterministic contract, failing closed for unsupported clauses."""
    for contract in CLAUSE_TRANSLATION_CONTRACTS:
        if contract.clause_type == clause_type:
            return contract
    raise ValueError(f"unsupported clause type: {clause_type}")
