# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Completeness, composition, fidelity, and uncertainty controls for ingestion.

The objects here are deliberately target-neutral.  Prolog, ASP, and user-facing
renderings are projections of these records, never competing sources of truth.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.ingestion.contracts import (
    ExtractionArtifact,
    PageExtractionQuality,
    StructuralElement,
    TriageDecision,
    canonical_sha256,
    stable_id,
)


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MaterialCategory(StrEnum):
    GRANT = "grant"
    DEFINITION = "definition"
    ELIGIBILITY = "eligibility"
    CONDITION = "condition"
    EXCLUSION = "exclusion"
    EXCEPTION = "exception_to_exclusion"
    LIMIT = "limit"
    SERVICE_FEE = "service_fee"
    DUTY = "duty"
    TEMPORAL_SCOPE = "temporal_scope"
    GEOGRAPHIC_SCOPE = "geographic_scope"
    OPTIONAL_MODULE = "optional_module"
    PRECEDENCE = "precedence"
    TABLE = "table"
    CROSS_REFERENCE = "cross_reference"


class DocumentStructuralInventory(StrictRecord):
    """A lossless accounting envelope around extracted structural elements."""

    inventory_id: str
    source_version_id: str
    extraction_artifact_id: str
    element_ids: tuple[str, ...]
    triage_decision_ids: tuple[str, ...]
    raw_output_sha256: str
    cleaned_view_sha256: str

    @model_validator(mode="after")
    def stable_identity(self) -> "DocumentStructuralInventory":
        """Prove that every extracted element has exactly one recorded disposition."""
        if not self.element_ids or len(set(self.element_ids)) != len(self.element_ids):
            raise ValueError("inventory elements must be non-empty and unique")
        if len(self.triage_decision_ids) != len(self.element_ids):
            raise ValueError("every structural element requires exactly one disposition")
        payload = {
            "source_version_id": self.source_version_id,
            "extraction_artifact_id": self.extraction_artifact_id,
            "element_ids": self.element_ids,
            "triage_decision_ids": self.triage_decision_ids,
            "raw_output_sha256": self.raw_output_sha256,
            "cleaned_view_sha256": self.cleaned_view_sha256,
        }
        if self.inventory_id != stable_id("structural_inventory", payload):
            raise ValueError("inventory_id does not match the complete structural inventory")
        return self


class CompletenessEntry(StrictRecord):
    category: MaterialCategory
    status: Literal["represented", "not_present", "omitted_no_impact", "unresolved"]
    formal_element_ids: tuple[str, ...] = ()
    structural_element_ids: tuple[str, ...] = ()
    rationale: str
    reviewer_id: str | None = None

    @model_validator(mode="after")
    def evidence_and_review(self) -> "CompletenessEntry":
        """Require evidence for represented categories and rationale for omissions."""
        if self.status == "represented" and not self.formal_element_ids:
            raise ValueError("represented categories require formal elements")
        if self.status == "omitted_no_impact" and not self.reviewer_id:
            raise ValueError("no-impact omissions require a reviewer")
        return self


class PolicyCompletenessLedger(StrictRecord):
    ledger_id: str
    source_version_id: str
    recommendation_scope: str
    entries: tuple[CompletenessEntry, ...]
    review_state: Literal["draft", "reviewed"] = "draft"

    @model_validator(mode="after")
    def complete_categories(self) -> "PolicyCompletenessLedger":
        """Require one decision for every recommendation-material policy category."""
        categories = [item.category for item in self.entries]
        expected = set(MaterialCategory)
        if set(categories) != expected or len(categories) != len(expected):
            raise ValueError("completeness ledger must account for every material category once")
        if self.review_state == "reviewed" and any(
            item.status == "unresolved" for item in self.entries
        ):
            raise ValueError("reviewed completeness ledger cannot contain unresolved categories")
        payload = {
            "source_version_id": self.source_version_id,
            "recommendation_scope": self.recommendation_scope,
            "entries": [item.model_dump(mode="json") for item in self.entries],
        }
        if self.ledger_id != stable_id("completeness_ledger", payload):
            raise ValueError("ledger_id does not match its scope and entries")
        return self


class VocabularySenseDecision(StrictRecord):
    decision_id: str
    provider_term: str
    source_language: str
    canonical_concept_id: str | None = None
    sense_id: str | None = None
    units: tuple[str, ...] = ()
    currencies: tuple[str, ...] = ()
    modalities: tuple[str, ...] = ()
    status: Literal["proposed", "approved", "unresolved", "rejected"]
    rationale: str
    reviewer_id: str | None = None
    source_artifact_refs: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def governed_mapping(self) -> "VocabularySenseDecision":
        """Keep provider terminology reversible and block unresolved sense selection."""
        if self.status == "approved" and not all(
            (self.canonical_concept_id, self.sense_id, self.reviewer_id)
        ):
            raise ValueError("approved vocabulary mappings require concept, sense, and reviewer")
        if self.status == "unresolved" and self.sense_id is not None:
            raise ValueError("an unresolved term cannot silently select a sense")
        identity = {
            "provider_term": self.provider_term,
            "source_language": self.source_language,
            "canonical_concept_id": self.canonical_concept_id,
            "sense_id": self.sense_id,
            "units": self.units,
            "currencies": self.currencies,
            "modalities": self.modalities,
            "status": self.status,
            "source_artifact_refs": self.source_artifact_refs,
        }
        if self.decision_id != stable_id("vocabulary_decision", identity):
            raise ValueError("decision_id does not match the reversible lexical mapping")
        return self


class SemanticAtom(StrictRecord):
    atom_id: str
    role: Literal[
        "grant",
        "definition",
        "eligibility",
        "condition",
        "exclusion",
        "exception",
        "limit",
        "service_fee",
        "duty",
        "scope",
        "option_dependency",
        "precedence",
    ]
    subject: str
    predicate: str
    object_or_value: Any
    unit: str | None = None
    currency: str | None = None
    modality: str
    negated: bool = False
    quantifier: str | None = None
    source_version_id: str
    source_span_ids: tuple[str, ...] = Field(min_length=1)
    vocabulary_decision_ids: tuple[str, ...] = Field(min_length=1)
    dependency_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def stable_atom(self) -> "SemanticAtom":
        """Make semantically equivalent atoms share one canonical identity."""
        if self.atom_id != stable_id("semantic_atom", self.semantic_key_payload()):
            raise ValueError("atom_id does not match canonical semantics")
        return self

    def semantic_key_payload(self) -> dict[str, Any]:
        """Return the meaning-bearing fields used for deduplication and identity."""
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object_or_value": self.object_or_value,
            "unit": self.unit,
            "currency": self.currency,
            "modality": self.modality,
            "negated": self.negated,
            "quantifier": self.quantifier,
            "source_version_id": self.source_version_id,
        }


class ComposedClause(StrictRecord):
    clause_id: str
    operator: Literal["atom", "all_of", "any_of", "unless", "ordered"]
    member_atom_ids: tuple[str, ...] = ()
    member_clause_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def meaningful_composition(self) -> "ComposedClause":
        """Reject empty or structurally invalid logical clause compositions."""
        members = (*self.member_atom_ids, *self.member_clause_ids)
        if not members:
            raise ValueError("a composed clause requires at least one member")
        if self.operator == "atom" and len(self.member_atom_ids) != 1:
            raise ValueError("atom composition requires exactly one atom")
        return self


MANDATORY_FIDELITY_CHECKS = frozenset(
    {
        "source_entails_formal",
        "formal_entails_source",
        "contradiction",
        "numeric_unit_date",
        "exception_preservation",
        "cross_reference_preservation",
        "bilingual",
    }
)


class FidelityCheck(StrictRecord):
    check_kind: Literal[
        "source_entails_formal",
        "formal_entails_source",
        "contradiction",
        "numeric_unit_date",
        "exception_preservation",
        "cross_reference_preservation",
        "bilingual",
    ]
    status: Literal["pass", "fail", "uncertain"]
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    details: str
    adjudicated_by: str | None = None


class FidelityGate(StrictRecord):
    formal_element_id: str
    semantic_sha256: str
    checks: tuple[FidelityCheck, ...]
    optional_reviewer_metadata: dict[str, str] = Field(default_factory=dict)
    deterministic_gate_ids: tuple[str, ...] = ()
    generative_gate_ids: tuple[str, ...] = ()

    @property
    def compilation_allowed(self) -> bool:
        """Allow compilation only after all fidelity checks and both gate classes pass."""
        kinds = {item.check_kind for item in self.checks}
        return (
            kinds == MANDATORY_FIDELITY_CHECKS
            and all(item.status == "pass" for item in self.checks)
            and bool(self.deterministic_gate_ids)
            and bool(self.generative_gate_ids)
        )


class KnowledgeState(StrEnum):
    SUPPORTED = "supported"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    CONTRADICTORY = "contradictory"
    PROXY_ONLY = "proxy_only"
    CANDIDATE_ONLY = "candidate_only"
    STALE = "stale"
    REVIEW_REQUIRED = "review_required"
    NOT_OFFERED = "not_offered"


class KnowledgeStatusFact(StrictRecord):
    fact_id: str
    subject_id: str
    predicate: str
    state: KnowledgeState
    evidence_refs: tuple[str, ...] = ()
    rationale: str

    @model_validator(mode="after")
    def stable_status(self) -> "KnowledgeStatusFact":
        """Separate evidence-backed support/exclusion from unknown or unavailable states."""
        payload = {
            "subject_id": self.subject_id,
            "predicate": self.predicate,
            "state": self.state,
            "evidence_refs": self.evidence_refs,
            "rationale": self.rationale,
        }
        if self.fact_id != stable_id("knowledge_status", payload):
            raise ValueError("fact_id does not match knowledge status")
        if (
            self.state in {KnowledgeState.SUPPORTED, KnowledgeState.EXCLUDED}
            and not self.evidence_refs
        ):
            raise ValueError("positive and negative policy facts require evidence")
        return self


def build_structural_inventory(
    *,
    source_version_id: str,
    extraction: ExtractionArtifact,
    raw_text: str,
    cleaned_text: str,
) -> tuple[DocumentStructuralInventory, tuple[StructuralElement, ...], tuple[TriageDecision, ...]]:
    """Account for every non-empty block without a rank or count cap.

    Decisions start as ``defer/unresolved``: segmentation is not materiality review.
    Raw and cleaned hashes remain distinct so cleanup cannot overwrite evidence.
    """
    blocks = list(re.finditer(r"(?ms)(^|\n)([^\n].*?)(?=\n\s*\n|\Z)", cleaned_text))
    elements: list[StructuralElement] = []
    decisions: list[TriageDecision] = []
    ancestry: list[str] = []
    for match in blocks:
        text = match.group(2).strip()
        if not text:
            continue
        first = text.splitlines()[0].strip()
        heading = re.match(r"^(#{1,6})\s+(.+)$", first)
        if heading:
            level = len(heading.group(1))
            ancestry = ancestry[: level - 1] + [heading.group(2).strip()]
            kind = "heading"
        elif re.match(r"^([-*+] |\d+[.)] )", first):
            kind = "list"
        elif "|" in first and len(text.splitlines()) > 1:
            kind = "table"
        elif re.search(r"\b(annexe|appendix)\b", first, re.I):
            kind = "annex"
        elif re.search(r"\b(voir|cf\.|see)\s+(article|section|annexe|clause)", text, re.I):
            kind = "cross_reference"
        elif re.match(r"^(\*|\d+)\s", first) and len(text) < 400:
            kind = "footnote"
        else:
            kind = "paragraph"
        start, end = match.start(2), match.end(2)
        coordinates = {
            "source_version_id": source_version_id,
            "kind": kind,
            "character_offsets": (start, end),
            "heading_ancestry": tuple(ancestry),
            "text_sha256": canonical_sha256(text),
        }
        element_id = stable_id("structural_element", coordinates)
        element = StructuralElement(
            element_id=element_id,
            extraction_artifact_id=extraction.extraction_artifact_id,
            source_version_id=source_version_id,
            kind=kind,
            character_offsets=(start, end),
            heading_ancestry=tuple(ancestry),
            text_sha256=canonical_sha256(text),
        )
        decision_payload = {
            "structural_element_id": element_id,
            "disposition": "defer",
            "recommendation_materiality": "unresolved",
        }
        elements.append(element)
        decisions.append(
            TriageDecision.model_validate(
                dict(
                    triage_decision_id=stable_id("triage_decision", decision_payload),
                    **decision_payload,
                    rationale="Awaiting recommendation-materiality review.",
                )
            )
        )
    inventory_payload = {
        "source_version_id": source_version_id,
        "extraction_artifact_id": extraction.extraction_artifact_id,
        "element_ids": tuple(item.element_id for item in elements),
        "triage_decision_ids": tuple(item.triage_decision_id for item in decisions),
        "raw_output_sha256": canonical_sha256(raw_text),
        "cleaned_view_sha256": canonical_sha256(cleaned_text),
    }
    return (
        DocumentStructuralInventory(
            inventory_id=stable_id("structural_inventory", inventory_payload),
            **inventory_payload,
        ),
        tuple(elements),
        tuple(decisions),
    )


def extraction_quality_gate(
    artifact: ExtractionArtifact,
    pages: tuple[PageExtractionQuality, ...],
    *,
    minimum_quality: float = 0.75,
) -> tuple[bool, tuple[str, ...]]:
    """Return formalization readiness and explicit fallback/quarantine reasons."""
    reasons = list(artifact.warnings)
    if artifact.status != "complete":
        reasons.append(f"extraction_{artifact.status}")
    if artifact.quality < minimum_quality:
        reasons.append("document_quality_below_threshold")
    if not pages:
        reasons.append("missing_page_quality")
    for page in pages:
        if page.quality < minimum_quality:
            reasons.append(f"page_{page.page}_quality_below_threshold")
        if page.ocr_state in {"failed", "partial", "blocked_encrypted", "blocked_password"}:
            reasons.append(f"page_{page.page}_ocr_{page.ocr_state}")
    unique = tuple(dict.fromkeys(reasons))
    return not unique, unique


def extraction_fallback_order(
    *,
    native_text_characters: int,
    encrypted: bool = False,
    password_required: bool = False,
    table_heavy: bool = False,
    multilingual: bool = False,
) -> tuple[str, ...]:
    """Declare a bounded fallback plan; this function never performs OCR itself."""
    if password_required:
        return ("quarantine_password_protected",)
    if encrypted:
        return ("attempt_pypdf_decryption_without_secret", "quarantine_encrypted")
    order = ["docling_native_layout", "pypdf_native_comparison"]
    if native_text_characters < 40:
        order.append("bounded_page_ocr")
    if table_heavy:
        order.append("docling_table_structure_comparison")
    if multilingual:
        order.append("language_segmented_quality_review")
    order.append("quarantine_if_quality_gate_fails")
    return tuple(order)


def validate_inventory_accounting(
    inventory: DocumentStructuralInventory,
    elements: tuple[StructuralElement, ...],
    decisions: tuple[TriageDecision, ...],
) -> list[str]:
    """Reconcile structure and disposition objects, not merely declared counts."""
    errors: list[str] = []
    element_ids = [item.element_id for item in elements]
    decision_by_element: dict[str, list[TriageDecision]] = {}
    for decision in decisions:
        decision_by_element.setdefault(decision.structural_element_id, []).append(decision)
    if tuple(element_ids) != inventory.element_ids:
        errors.append("inventory element IDs do not match supplied structural elements")
    if tuple(item.triage_decision_id for item in decisions) != inventory.triage_decision_ids:
        errors.append("inventory decision IDs do not match supplied triage decisions")
    for element_id in inventory.element_ids:
        count = len(decision_by_element.get(element_id, ()))
        if count != 1:
            errors.append(f"{element_id}: expected exactly one disposition, found {count}")
    unknown = set(decision_by_element) - set(inventory.element_ids)
    errors.extend(f"{item}: decision targets element outside inventory" for item in sorted(unknown))
    return errors


def validate_vocabulary_coverage(
    corpus_terms: set[tuple[str, str]], decisions: tuple[VocabularySenseDecision, ...]
) -> list[str]:
    """Require a decision for every distinct (language, provider-term) pair."""
    by_term = {(item.source_language, item.provider_term): item for item in decisions}
    errors = [
        f"missing vocabulary decision for {language}:{term}"
        for language, term in sorted(corpus_terms - set(by_term))
    ]
    errors.extend(
        f"{item.decision_id}: unresolved or unapproved sense cannot compile"
        for item in decisions
        if item.status != "approved"
    )
    return errors


def validate_clause_composition(
    clause: ComposedClause,
    atoms: tuple[SemanticAtom, ...],
    clauses: tuple[ComposedClause, ...] = (),
) -> list[str]:
    """Validate references and reject duplicate canonical assertions."""
    atom_by_id = {item.atom_id: item for item in atoms}
    clause_ids = {item.clause_id for item in clauses} | {clause.clause_id}
    errors = [
        f"{clause.clause_id}: unknown atom {item}"
        for item in clause.member_atom_ids
        if item not in atom_by_id
    ]
    errors.extend(
        f"{clause.clause_id}: unknown composed clause {item}"
        for item in clause.member_clause_ids
        if item not in clause_ids
    )
    seen: dict[str, str] = {}
    for atom in atoms:
        key = canonical_sha256(atom.semantic_key_payload())
        if key in seen and seen[key] != atom.atom_id:
            errors.append(f"duplicate canonical assertion: {seen[key]} and {atom.atom_id}")
        seen[key] = atom.atom_id
    return errors


def render_controlled_clause(clause: ComposedClause, atoms: tuple[SemanticAtom, ...]) -> str:
    """Render every material atom explicitly for reviewer reconstruction."""
    atom_by_id = {item.atom_id: item for item in atoms}
    joiner = {
        "atom": "",
        "all_of": " AND ",
        "any_of": " OR ",
        "unless": " UNLESS ",
        "ordered": " THEN ",
    }[clause.operator]
    rendered: list[str] = []
    for atom_id in clause.member_atom_ids:
        atom = atom_by_id[atom_id]
        value = atom.object_or_value
        suffix = " ".join(item for item in (atom.unit, atom.currency) if item)
        expression = f"{atom.modality} {atom.subject} {atom.predicate} {value}"
        if suffix:
            expression += f" {suffix}"
        if atom.negated:
            expression = "NOT " + expression
        if atom.quantifier:
            expression = f"{atom.quantifier}({expression})"
        rendered.append(expression)
    return joiner.join(rendered)


def validate_compiled_annotation_comments(
    text: str, *, target: Literal["prolog", "asp"], expected_annotation_ids: set[str]
) -> list[str]:
    """Require compact bilingual comments and stable annotation references per rule."""
    marker = "%" if target in {"prolog", "asp"} else "#"
    found_refs = set(re.findall(r"Annotation-ID:\s*([^\s]+)", text))
    errors = [
        f"missing annotation reference {item}"
        for item in sorted(expected_annotation_ids - found_refs)
    ]
    blocks = re.split(r"(?=% Annotation-ID:)", text)
    for block in blocks:
        match = re.search(r"% Annotation-ID:\s*([^\s]+)", block)
        if not match or match.group(1) not in expected_annotation_ids:
            continue
        if f"{marker} NL-FR:" not in block or f"{marker} NL-EN:" not in block:
            errors.append(f"{match.group(1)}: missing adjacent bilingual comments")
    return errors
