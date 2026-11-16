# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Skill-governed formalization-wave and document-grounding contracts.

The contracts in this module do not formalize policy prose.  They make every wave
prove that it ran the canonical skill sequence and that each promoted logical atom
is grounded in an immutable document part with independently reviewed entailment.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ruler.ingestion.contracts import canonical_sha256, stable_id
from ruler.io import read_yaml
from ruler.paths import REPO_ROOT

FORMALIZATION_WAVE_TEMPLATE = (
    REPO_ROOT
    / "data"
    / "operations"
    / "formalization_waves"
    / "templates"
    / "formalization_wave_manifest.yaml"
)
REQUIRED_SKILL_SEQUENCE = (
    "policy-layout-extraction-auditor",
    "autoformalization-translation-aligner",
    "vocabulary-predicate-harmonizer",
    "policy-autoformalization-orchestrator",
    "policy-clause-formalizer",
    "bilingual-prolog-commentator",
    "feature-grounding-validator",
    "policy-source-formalization-drift-guard",
    "verify-kb-consistency",
    "formalized-kb-curator",
)

REQUIRED_WAVE_VALIDATORS = frozenset(
    {
        "uv run ruler validate translation-control",
        "uv run ruler validate vocabulary-predicates",
        "uv run ruler validate formalization-governance",
        "uv run ruler validate contracts",
        "uv run ruler validate formalized-kb",
        "uv run ruler validate prolog-nl-comments",
        "uv run ruler validate formalized-kb",
        "uv run ruler validate skills",
        "uv run ruler validate hooks",
    }
)


class WaveContract(BaseModel):
    """Strict base for portable YAML wave records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class GateDecision(StrEnum):
    """A skill gate cannot silently disappear from a wave."""

    PENDING = "pending"
    PASS = "pass"
    HOLD = "hold"
    WAIVED = "waived"
    FAIL = "fail"


class SkillGateEvidence(WaveContract):
    """Inputs, outputs, decisions, and evidence for one canonical skill invocation."""

    skill: str
    sequence: int = Field(ge=1)
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    owning_workflow: str
    validators: tuple[str, ...]
    decision: GateDecision
    evidence_refs: tuple[str, ...] = ()
    holds: tuple[str, ...] = ()
    waivers: tuple[str, ...] = ()
    human_approvals: tuple[str, ...] = ()

    @model_validator(mode="after")
    def decision_has_explicit_evidence(self) -> "SkillGateEvidence":
        """Prevent passing, holding, or waiving a gate without an audit trail."""
        if not self.inputs or not self.outputs or not self.validators:
            raise ValueError("skill gates require declared inputs, outputs, and validators")
        if self.decision == GateDecision.PASS and not self.evidence_refs:
            raise ValueError("passing skill gates require evidence_refs")
        if self.decision == GateDecision.HOLD and not self.holds:
            raise ValueError("held skill gates require explicit holds")
        if self.decision == GateDecision.WAIVED and (not self.waivers or not self.human_approvals):
            raise ValueError("waived skill gates require a waiver and human approval")
        return self


class ArtifactOwnership(WaveContract):
    """One generated artifact has exactly one declared skill/workflow owner."""

    artifact_ref: str
    owning_skill: str
    owning_workflow: str


class DocumentIdentity(WaveContract):
    """Stable semantic document identity and immutable source-version identity."""

    document_id: str
    source_version_id: str
    provider: str
    document_name: str
    product_family: str
    edition: str
    language: str
    public_url: str
    source_sha256: str

    @field_validator("source_sha256")
    @classmethod
    def source_hash_is_canonical(cls, value: str) -> str:
        """Require a complete lowercase SHA-256 digest."""
        digest = value.removeprefix("sha256:")
        if not value.startswith("sha256:") or len(digest) != 64:
            raise ValueError("source_sha256 must use sha256:<64 lowercase hex> form")
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("source_sha256 must use lowercase hexadecimal")
        return value

    @model_validator(mode="after")
    def identities_are_content_bound(self) -> "DocumentIdentity":
        """Keep a semantic document stable while versions remain content immutable."""
        document_coordinates = {
            "provider": self.provider,
            "document_name": self.document_name,
            "product_family": self.product_family,
        }
        if self.document_id != stable_id("document", document_coordinates):
            raise ValueError("document_id must derive from provider, name, and product family")
        version_coordinates = {
            "document_id": self.document_id,
            "edition": self.edition,
            "language": self.language,
            "public_url": self.public_url,
            "source_sha256": self.source_sha256,
        }
        if self.source_version_id != stable_id("document_version", version_coordinates):
            raise ValueError("source_version_id must derive from immutable version coordinates")
        if not self.public_url.startswith(("https://", "http://")):
            raise ValueError("public_url must be an HTTP(S) URL")
        return self


class DocumentPartType(StrEnum):
    """Canonical document hierarchy levels."""

    DOCUMENT = "document"
    PART = "part"
    CHAPTER = "chapter"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    SPAN = "span"


class DocumentPart(WaveContract):
    """A hash- and offset-bound node in the canonical document hierarchy."""

    part_id: str
    source_version_id: str
    part_type: DocumentPartType
    parent_part_id: str | None = None
    printed_label: str | None = None
    character_offsets: tuple[int, int]
    byte_offsets: tuple[int, int]
    text_sha256: str

    @field_validator("text_sha256")
    @classmethod
    def text_hash_is_canonical(cls, value: str) -> str:
        """Require a complete span/content hash."""
        digest = value.removeprefix("sha256:")
        if not value.startswith("sha256:") or len(digest) != 64:
            raise ValueError("text_sha256 must use sha256:<64 lowercase hex> form")
        return value

    @model_validator(mode="after")
    def coordinates_are_valid(self) -> "DocumentPart":
        """Protect parent/root shape and ordered non-empty offsets."""
        if self.part_type == DocumentPartType.DOCUMENT and self.parent_part_id is not None:
            raise ValueError("document roots cannot have a parent")
        if self.part_type != DocumentPartType.DOCUMENT and self.parent_part_id is None:
            raise ValueError("non-document parts require a parent")
        if self.character_offsets[1] <= self.character_offsets[0]:
            raise ValueError("character offsets must describe a non-empty ordered range")
        if self.byte_offsets[1] <= self.byte_offsets[0]:
            raise ValueError("byte offsets must describe a non-empty ordered range")
        identity = {
            "source_version_id": self.source_version_id,
            "part_type": self.part_type,
            "parent_part_id": self.parent_part_id,
            "printed_label": self.printed_label,
            "character_offsets": self.character_offsets,
            "byte_offsets": self.byte_offsets,
            "text_sha256": self.text_sha256,
        }
        if self.part_id != stable_id("document_part", identity):
            raise ValueError("part_id must derive from its immutable document coordinates")
        return self


class AtomRole(StrEnum):
    """Source grounding roles inside a logical unit."""

    HEAD = "head"
    BODY_CONDITION = "body_condition"
    EXCEPTION = "exception"
    EXCLUSION = "exclusion"
    LIMIT = "limit"
    CONSTANT = "constant"


class LogicAtomGrounding(WaveContract):
    """Bidirectional link from one logical atom to its smallest sufficient spans."""

    atom_id: str
    formal_element_id: str
    role: AtomRole
    source_span_ids: tuple[str, ...]

    @model_validator(mode="after")
    def spans_are_declared(self) -> "LogicAtomGrounding":
        """Every atom needs at least one exact source span."""
        if not self.source_span_ids:
            raise ValueError("logical atoms require at least one source span")
        if len(set(self.source_span_ids)) != len(self.source_span_ids):
            raise ValueError("logical atom source spans must be unique")
        return self


class ReferenceStatus(StrEnum):
    """Cross-reference resolution state."""

    RESOLVED = "resolved"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


class CrossReferenceResolution(WaveContract):
    """Explicit intra- or cross-document reference resolution."""

    reference_id: str
    source_part_id: str
    printed_target: str
    status: ReferenceStatus
    target_part_ids: tuple[str, ...] = ()
    blocker: str | None = None

    @model_validator(mode="after")
    def resolution_is_explicit(self) -> "CrossReferenceResolution":
        """Resolved references need targets; unresolved references need blockers."""
        if self.status == ReferenceStatus.RESOLVED and not self.target_part_ids:
            raise ValueError("resolved cross-references require target_part_ids")
        if self.status == ReferenceStatus.UNRESOLVED and not self.blocker:
            raise ValueError("unresolved cross-references require a blocker")
        if self.status != ReferenceStatus.UNRESOLVED and self.blocker:
            raise ValueError("only unresolved cross-references may declare a blocker")
        return self


class EntailmentStatus(StrEnum):
    """Independent textual fidelity decision."""

    PASS = "pass"
    FAIL = "fail"
    REVIEW_REQUIRED = "review_required"


class EntailmentAssessment(WaveContract):
    """Separate source-to-logic and logic-to-source semantic assessment."""

    formal_element_id: str
    source_entails_logic: EntailmentStatus
    logic_entails_source: EntailmentStatus
    evidence_refs: tuple[str, ...]
    material_failure: bool = False
    reviewer_id: str | None = None
    review_decision: Literal["approved", "rejected", "changes_requested"] | None = None
    caveats: tuple[str, ...] = ()

    @model_validator(mode="after")
    def failures_require_human_review(self) -> "EntailmentAssessment":
        """Compilation is never a substitute for reviewing material semantic loss."""
        if not self.evidence_refs:
            raise ValueError("entailment assessments require independent evidence")
        directions = {self.source_entails_logic, self.logic_entails_source}
        if self.material_failure or EntailmentStatus.FAIL in directions:
            if not self.reviewer_id or not self.review_decision:
                raise ValueError("material or failed entailment requires human review")
        if EntailmentStatus.REVIEW_REQUIRED in directions and not self.caveats:
            raise ValueError("review-required entailment must preserve explicit caveats")
        return self

    @property
    def promotion_allowed(self) -> bool:
        """Only lossless two-way entailment can authorize promotion."""
        return (
            self.source_entails_logic == EntailmentStatus.PASS
            and self.logic_entails_source == EntailmentStatus.PASS
            and not self.material_failure
        )


class LogicalUnitGrounding(WaveContract):
    """Grounding closure for one candidate, rule, fact, or constraint."""

    formal_element_id: str
    source_version_id: str
    atom_ids: tuple[str, ...]
    cross_reference_ids: tuple[str, ...] = ()
    entailment_id: str
    compiled: bool = False
    promoted: bool = False

    @model_validator(mode="after")
    def logical_unit_has_atoms(self) -> "LogicalUnitGrounding":
        """Never treat a prose record without grounded atoms as executable logic."""
        if not self.atom_ids:
            raise ValueError("logical units require grounded atom_ids")
        return self


class FormalizationWaveManifest(WaveContract):
    """Complete reusable contract for one provider/product-family wave."""

    manifest_version: Literal[1] = 1
    template_only: bool = False
    wave_id: str
    provider: str
    product_family: str
    assertion_ids: tuple[str, ...]
    promoted_extension_assertion_ids: tuple[str, ...] = ()
    candidate_only_assertion_ids: tuple[str, ...] = ()
    source_span_ids: tuple[str, ...]
    promotion_target: Literal["candidate_only", "active_reasoner"]
    review_state: Literal["draft", "review_required", "approved", "rejected"]
    skill_gates: tuple[SkillGateEvidence, ...]
    artifact_ownership: tuple[ArtifactOwnership, ...]
    wave_validators: tuple[str, ...]
    documents: tuple[DocumentIdentity, ...]
    document_parts: tuple[DocumentPart, ...]
    atom_groundings: tuple[LogicAtomGrounding, ...]
    cross_references: tuple[CrossReferenceResolution, ...]
    entailment_assessments: tuple[EntailmentAssessment, ...]
    logical_units: tuple[LogicalUnitGrounding, ...]
    release_evidence_refs: tuple[str, ...] = ()
    holds: tuple[str, ...] = ()
    waivers: tuple[str, ...] = ()
    human_approvals: tuple[str, ...] = ()


def load_formalization_wave_manifest(
    path: Path = FORMALIZATION_WAVE_TEMPLATE,
) -> FormalizationWaveManifest:
    """Load and schema-validate one formalization-wave manifest."""
    return FormalizationWaveManifest.model_validate(read_yaml(path))


def validate_formalization_wave_manifest(manifest: FormalizationWaveManifest) -> list[str]:
    """Return cross-record errors for skills, ownership, grounding, and promotion."""
    errors: list[str] = []
    skill_names = tuple(item.skill for item in manifest.skill_gates)
    if skill_names != REQUIRED_SKILL_SEQUENCE:
        errors.append("skill_gates must use the complete canonical sequence in order")
    sequences = tuple(item.sequence for item in manifest.skill_gates)
    if sequences != tuple(range(1, len(REQUIRED_SKILL_SEQUENCE) + 1)):
        errors.append("skill gate sequence numbers must be contiguous and ordered")
    classified_assertions = set(manifest.promoted_extension_assertion_ids) | set(
        manifest.candidate_only_assertion_ids
    )
    overlap = sorted(
        set(manifest.promoted_extension_assertion_ids) & set(manifest.candidate_only_assertion_ids)
    )
    if overlap:
        errors.append(f"assertions cannot be both extension-promoted and candidate-only: {overlap}")
    if classified_assertions != set(manifest.assertion_ids):
        errors.append("every assertion must be classified as extension-promoted or candidate-only")
    missing_validators = sorted(REQUIRED_WAVE_VALIDATORS - set(manifest.wave_validators))
    if missing_validators:
        errors.append(f"missing mandatory wave validators: {missing_validators}")

    ownership_counts = Counter(item.artifact_ref for item in manifest.artifact_ownership)
    for artifact_ref, count in sorted(ownership_counts.items()):
        if count != 1:
            errors.append(f"{artifact_ref}: expected one artifact owner, found {count}")
    ownership = {item.artifact_ref: item for item in manifest.artifact_ownership}
    for gate in manifest.skill_gates:
        for output in gate.outputs:
            owner = ownership.get(output)
            if owner is None:
                errors.append(f"{gate.skill}: output has no declared owner: {output}")
            elif owner.owning_skill != gate.skill or owner.owning_workflow != gate.owning_workflow:
                errors.append(f"{output}: artifact owner does not match its skill gate")

    errors.extend(validate_grounding_bundle(manifest))

    if not manifest.template_only and manifest.promotion_target == "active_reasoner":
        failed = [gate.skill for gate in manifest.skill_gates if gate.decision != GateDecision.PASS]
        if failed:
            errors.append(f"active promotion has non-passing skill gates: {failed}")
        if manifest.review_state != "approved":
            errors.append("active promotion requires approved wave review_state")
        if not manifest.release_evidence_refs:
            errors.append("active promotion requires release_evidence_refs")
        if not manifest.human_approvals:
            errors.append("active promotion requires explicit human approvals")
    return errors


def validate_grounding_bundle(manifest: FormalizationWaveManifest) -> list[str]:
    """Validate GROUND-001..005 as one closed bidirectional graph."""
    errors: list[str] = []
    documents = {item.source_version_id: item for item in manifest.documents}
    parts = {item.part_id: item for item in manifest.document_parts}
    atoms = {item.atom_id: item for item in manifest.atom_groundings}
    references = {item.reference_id: item for item in manifest.cross_references}
    entailments = {item.formal_element_id: item for item in manifest.entailment_assessments}
    units = {item.formal_element_id: item for item in manifest.logical_units}

    _append_duplicate_errors(
        errors, "source version", [item.source_version_id for item in manifest.documents]
    )
    _append_duplicate_errors(
        errors, "document part", [item.part_id for item in manifest.document_parts]
    )
    _append_duplicate_errors(
        errors, "atom grounding", [item.atom_id for item in manifest.atom_groundings]
    )
    _append_duplicate_errors(
        errors, "logical unit", [item.formal_element_id for item in manifest.logical_units]
    )

    roots_by_version: Counter[str] = Counter()
    for part in manifest.document_parts:
        if part.source_version_id not in documents:
            errors.append(f"{part.part_id}: unknown immutable source version")
        if part.part_type == DocumentPartType.DOCUMENT:
            roots_by_version[part.source_version_id] += 1
        elif part.parent_part_id not in parts:
            errors.append(f"{part.part_id}: unknown parent part {part.parent_part_id}")
        else:
            parent = parts[part.parent_part_id]
            if parent.source_version_id != part.source_version_id:
                errors.append(f"{part.part_id}: parent belongs to another source version")
            if not _range_contains(parent.character_offsets, part.character_offsets):
                errors.append(f"{part.part_id}: character offsets escape parent")
            if not _range_contains(parent.byte_offsets, part.byte_offsets):
                errors.append(f"{part.part_id}: byte offsets escape parent")
            if _has_parent_cycle(part.part_id, parts):
                errors.append(f"{part.part_id}: document hierarchy contains a cycle")
    for source_version_id in documents:
        if roots_by_version[source_version_id] != 1:
            errors.append(
                f"{source_version_id}: expected one document root, "
                f"found {roots_by_version[source_version_id]}"
            )

    span_ids = {
        part.part_id for part in manifest.document_parts if part.part_type == DocumentPartType.SPAN
    }
    for declared_span_id in manifest.source_span_ids:
        if declared_span_id not in span_ids:
            errors.append(f"wave source span is not a canonical span part: {declared_span_id}")
    for atom in manifest.atom_groundings:
        if atom.formal_element_id not in units:
            errors.append(f"{atom.atom_id}: unknown formal element {atom.formal_element_id}")
        for span_id in atom.source_span_ids:
            if span_id not in span_ids:
                errors.append(f"{atom.atom_id}: grounding target is not an exact span: {span_id}")

    for reference in manifest.cross_references:
        if reference.source_part_id not in parts:
            errors.append(f"{reference.reference_id}: unknown source part")
        for target_id in reference.target_part_ids:
            if target_id not in parts:
                errors.append(f"{reference.reference_id}: unknown target part {target_id}")

    referenced_spans: set[str] = set()
    for atom in manifest.atom_groundings:
        referenced_spans.update(atom.source_span_ids)
    unused_spans = sorted(set(manifest.source_span_ids) - referenced_spans)
    if unused_spans:
        errors.append(f"promoted source spans without logical consequences: {unused_spans}")

    for unit in manifest.logical_units:
        if unit.source_version_id not in documents:
            errors.append(f"{unit.formal_element_id}: unknown immutable source version")
        for atom_id in unit.atom_ids:
            atom = atoms.get(atom_id)
            if atom is None:
                errors.append(f"{unit.formal_element_id}: unknown atom grounding {atom_id}")
            elif atom.formal_element_id != unit.formal_element_id:
                errors.append(f"{unit.formal_element_id}: atom belongs to another logical unit")
        for reference_id in unit.cross_reference_ids:
            reference = references.get(reference_id)
            if reference is None:
                errors.append(f"{unit.formal_element_id}: unknown cross-reference {reference_id}")
            elif unit.compiled and reference.status == ReferenceStatus.UNRESOLVED:
                errors.append(f"{unit.formal_element_id}: compiled with unresolved cross-reference")
        entailment = entailments.get(unit.entailment_id)
        if entailment is None:
            errors.append(f"{unit.formal_element_id}: missing entailment assessment")
        elif unit.entailment_id != unit.formal_element_id:
            errors.append(f"{unit.formal_element_id}: entailment assessment is for another unit")
        elif (unit.compiled or unit.promoted) and not entailment.promotion_allowed:
            errors.append(f"{unit.formal_element_id}: compilation/promotion blocked by entailment")
        if unit.promoted and not unit.compiled:
            errors.append(f"{unit.formal_element_id}: promoted unit is not compiled")
    return errors


def validate_formalization_wave_configuration(
    path: Path = FORMALIZATION_WAVE_TEMPLATE,
) -> list[str]:
    """Validate the reusable repository template without mutating any artifacts."""
    manifests = [load_formalization_wave_manifest(path)]
    errors = [
        f"{manifest.wave_id}: {error}"
        for manifest in manifests
        for error in validate_formalization_wave_manifest(manifest)
    ]
    if errors:
        raise ValueError("formalization-wave validation failed:\n- " + "\n- ".join(errors))
    return [
        f"manifests={len(manifests)}",
        f"skill_gates={sum(len(item.skill_gates) for item in manifests)}",
        f"documents={sum(len(item.documents) for item in manifests)}",
        f"logical_units={sum(len(item.logical_units) for item in manifests)}",
        "grounding=closed",
    ]


def _append_duplicate_errors(errors: list[str], kind: str, values: list[str]) -> None:
    for value, count in Counter(values).items():
        if count > 1:
            errors.append(f"duplicate {kind}: {value}")


def _range_contains(parent: tuple[int, int], child: tuple[int, int]) -> bool:
    return parent[0] <= child[0] and child[1] <= parent[1]


def _has_parent_cycle(part_id: str, parts: dict[str, DocumentPart]) -> bool:
    visited: set[str] = set()
    current: str | None = part_id
    while current is not None:
        if current in visited:
            return True
        visited.add(current)
        item = parts.get(current)
        current = item.parent_part_id if item else None
    return False


def build_template_identity_values() -> dict[str, Any]:
    """Return deterministic IDs/hashes used by the checked-in reusable example."""
    source_sha256 = canonical_sha256("replace with exact source bytes")
    document_coordinates = {
        "provider": "replace-provider",
        "document_name": "replace-document",
        "product_family": "replace-family",
    }
    document_id = stable_id("document", document_coordinates)
    version_coordinates = {
        "document_id": document_id,
        "edition": "replace-edition",
        "language": "fr",
        "public_url": "https://example.invalid/policy.pdf",
        "source_sha256": source_sha256,
    }
    source_version_id = stable_id("document_version", version_coordinates)
    root_coordinates = {
        "source_version_id": source_version_id,
        "part_type": DocumentPartType.DOCUMENT,
        "parent_part_id": None,
        "printed_label": None,
        "character_offsets": (0, 100),
        "byte_offsets": (0, 100),
        "text_sha256": source_sha256,
    }
    root_id = stable_id("document_part", root_coordinates)
    span_hash = canonical_sha256("replace with the smallest sufficient source span")
    span_coordinates = {
        "source_version_id": source_version_id,
        "part_type": DocumentPartType.SPAN,
        "parent_part_id": root_id,
        "printed_label": "B1.1.1",
        "character_offsets": (10, 90),
        "byte_offsets": (10, 90),
        "text_sha256": span_hash,
    }
    return {
        "document_id": document_id,
        "source_version_id": source_version_id,
        "source_sha256": source_sha256,
        "root_id": root_id,
        "span_id": stable_id("document_part", span_coordinates),
        "span_sha256": span_hash,
    }
