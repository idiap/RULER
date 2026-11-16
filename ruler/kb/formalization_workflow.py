# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Corpus-neutral orchestration for source-locked formalization.

This module is an additive facade over the established IR compilers and immutable
release gate.  Domain packs contribute vocabulary, unit taxonomy, materiality, and
translation checks; the core owns freshness, lifecycle filtering, compilation, and
release closure.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, field_validator, model_validator

from ruler.contracts.common import StrictContract, validate_sha256
from ruler.domains.base import DomainPack, TranslationContract, validate_domain_pack
from ruler.kb.asp_compiler import CompiledASP, compile_asp
from ruler.kb.formalization import (
    PredicateRegistry,
    PredicateSignature,
    ValueType,
    WorldAssumption,
)
from ruler.kb.formalization_release import (
    FormalLogicRelease,
    FormalReviewDecision,
    ValidatorEvidence,
    build_formal_logic_release,
)
from ruler.kb.logical_ir import (
    Atom,
    ExpressionKind,
    IRStatement,
    LogicalExpression,
    LogicalProgram,
)
from ruler.kb.prolog_compiler import CompiledProlog, compile_prolog

UnitState = Literal[
    "candidate", "review_required", "approved", "rejected", "stale", "non_formalizable"
]


class FormalizationWorkflowConfig(StrictContract):
    """One domain/corpus/language profile for a formalization run."""

    domain_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    corpus_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    source_language: str = Field(min_length=2)
    target_language: str = Field(min_length=2)
    program_id: str = Field(min_length=1)
    program_version: str = Field(min_length=1)


class FormalizationDocument(StrictContract):
    """Pinned authoritative document version presented to the workflow."""

    document_id: str = Field(min_length=1)
    document_kind: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_sha256: str
    source_text: str = Field(min_length=1)
    language: str = Field(min_length=2)

    _source_hash = field_validator("source_sha256")(validate_sha256)

    @model_validator(mode="after")
    def source_digest_authenticates_supplied_bytes(self) -> "FormalizationDocument":
        actual = "sha256:" + hashlib.sha256(self.source_text.encode("utf-8")).hexdigest()
        if self.source_sha256 != actual:
            raise ValueError("source_sha256 does not authenticate supplied document bytes")
        return self


class FormalizationSpan(StrictContract):
    """Exact current text span from one pinned document version."""

    span_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    span_sha256: str

    _span_hash = field_validator("span_sha256")(validate_sha256)

    @model_validator(mode="after")
    def content_hash_matches(self) -> "FormalizationSpan":
        if self.end_char - self.start_char != len(self.text):
            raise ValueError("span offsets must equal exact text length")
        actual = "sha256:" + hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.span_sha256 != actual:
            raise ValueError("span hash is stale for the supplied text")
        return self


class FormalizationUnit(StrictContract):
    """A normalized unit and optional typed logical candidate."""

    unit_id: str = Field(min_length=1)
    span_id: str = Field(min_length=1)
    unit_type: str = Field(min_length=1)
    materiality_role: str = Field(min_length=1)
    state: UnitState
    controlled_text: str | None = None
    predicate_candidates: tuple[str, ...] = ()
    statement: IRStatement | None = None
    rationale: str | None = None

    @model_validator(mode="after")
    def lifecycle_shape_is_safe(self) -> "FormalizationUnit":
        if self.statement is not None and self.statement.statement_id != self.unit_id:
            raise ValueError("logical statement ID must equal its formalization unit ID")
        if self.state == "approved" and self.statement is None:
            raise ValueError("approved units require typed logical IR")
        if self.state in {"rejected", "stale", "non_formalizable"} and not (
            self.rationale and self.rationale.strip()
        ):
            raise ValueError(f"{self.state} units require a rationale")
        return self


class FormalizationWorkflowRequest(StrictContract):
    """Complete source/span/unit input to one deterministic run."""

    config: FormalizationWorkflowConfig
    documents: tuple[FormalizationDocument, ...] = Field(min_length=1)
    spans: tuple[FormalizationSpan, ...] = Field(min_length=1)
    units: tuple[FormalizationUnit, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def identifiers_are_unique(self) -> "FormalizationWorkflowRequest":
        for label, identifiers in {
            "document": [item.document_id for item in self.documents],
            "span": [item.span_id for item in self.spans],
            "unit": [item.unit_id for item in self.units],
        }.items():
            if len(identifiers) != len(set(identifiers)):
                raise ValueError(f"duplicate {label} identifiers")
        return self


class UnitDisposition(StrictContract):
    """Auditable projection decision for one input unit."""

    unit_id: str
    input_state: UnitState
    projection: Literal["active", "blocked"]
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class FormalizationWorkflowResult:
    """Compiled approved projection plus an optional immutable release."""

    domain_id: str
    corpus_id: str
    translation_contract_id: str
    dispositions: tuple[UnitDisposition, ...]
    active_program: LogicalProgram | None
    predicate_registry: PredicateRegistry | None
    asp: CompiledASP | None
    prolog: CompiledProlog | None
    release: FormalLogicRelease | None

    @property
    def active_unit_ids(self) -> tuple[str, ...]:
        return tuple(item.unit_id for item in self.dispositions if item.projection == "active")

    @property
    def blocked_unit_ids(self) -> tuple[str, ...]:
        return tuple(item.unit_id for item in self.dispositions if item.projection == "blocked")


def run_formalization_workflow(
    pack: DomainPack,
    request: FormalizationWorkflowRequest,
    *,
    validators: tuple[ValidatorEvidence, ...] = (),
    review_decisions: tuple[FormalReviewDecision, ...] = (),
) -> FormalizationWorkflowResult:
    """Validate, filter, compile, and optionally release approved domain units.

    Candidate, review-required, rejected, explicitly stale, non-formalizable, and
    evidence-stale units are always represented in the audit dispositions and never
    copied into the active program.  Supplying validator and review evidence invokes
    the existing immutable release gate; supplying neither produces a compiled review
    projection with no release.
    """

    state = prepare_formalization(pack, request)
    while state.cursor < len(request.units):
        classify_formalization_unit(state)
    has_active, has_evidence, _paired = formalization_projection_guards(
        state, validators, review_decisions
    )
    if not has_active:
        require_empty_projection_evidence(validators, review_decisions)
        return formalization_result(state)
    compiled = compile_formalization_projection(state)
    release = None
    if has_evidence:
        require_paired_projection_evidence(validators, review_decisions)
        release = release_formalization_projection(state, compiled, validators, review_decisions)
    return formalization_result(state, compiled, release)


@dataclass
class FormalizationExecutionState:
    """One ordered pass over supplied units with explicit accumulated state."""

    pack: DomainPack
    request: FormalizationWorkflowRequest
    translation: TranslationContract
    spans: dict[str, FormalizationSpan]
    cursor: int
    dispositions: list[UnitDisposition]
    active_statements: list[IRStatement]


@dataclass(frozen=True)
class FormalizationCompiledProjection:
    active_program: LogicalProgram
    predicate_registry: PredicateRegistry
    asp: CompiledASP
    prolog: CompiledProlog


def prepare_formalization(
    pack: DomainPack, request: FormalizationWorkflowRequest
) -> FormalizationExecutionState:
    """Authenticate the pack, translation selection, documents and spans."""
    validate_domain_pack(pack)
    config = request.config
    if config.domain_id != pack.domain_id:
        raise ValueError(
            f"workflow domain {config.domain_id!r} does not match pack {pack.domain_id!r}"
        )
    translation = _select_translation_contract(pack, config.source_language, config.target_language)
    _validate_request_sources(pack, request)

    spans = {item.span_id: item for item in request.spans}
    return FormalizationExecutionState(pack, request, translation, spans, 0, [], [])


def classify_formalization_unit(state: FormalizationExecutionState) -> bool:
    """Consume one unit, accumulating all blockers or its active statement."""
    pack, spans = state.pack, state.spans
    dispositions, active_statements = state.dispositions, state.active_statements
    if state.cursor >= len(state.request.units):
        raise ValueError("all formalization units have already been classified")
    unit = state.request.units[state.cursor]
    reasons = _unit_blockers(pack, unit, spans)
    if reasons:
        dispositions.append(
            UnitDisposition(
                unit_id=unit.unit_id,
                input_state=unit.state,
                projection="blocked",
                reasons=tuple(reasons),
            )
        )
        state.cursor += 1
        return state.cursor == len(state.request.units)
    assert unit.statement is not None
    active_statements.append(unit.statement)
    dispositions.append(
        UnitDisposition(unit_id=unit.unit_id, input_state=unit.state, projection="active")
    )
    state.cursor += 1
    return state.cursor == len(state.request.units)


def formalization_projection_guards(state, validators, review_decisions):
    """Native branch conditions; evidence is consumed only by the release step."""
    return (
        bool(state.active_statements),
        bool(validators or review_decisions),
        bool(validators and review_decisions),
    )


def require_empty_projection_evidence(validators, review_decisions) -> None:
    """The empty projection cannot consume release evidence."""
    if validators or review_decisions:
        raise ValueError("release evidence was supplied but no approved units are active")


def require_paired_projection_evidence(validators, review_decisions) -> None:
    """Both evidence collections are required before release construction."""
    if not validators or not review_decisions:
        raise ValueError("validators and review decisions must be supplied together")


def compile_formalization_projection(
    state: FormalizationExecutionState,
) -> FormalizationCompiledProjection:
    """Build and type-check IR, then compile ASP followed by Prolog."""
    pack, config, active_statements = state.pack, state.request.config, state.active_statements
    program = LogicalProgram(
        program_id=config.program_id,
        version=config.program_version,
        statements=tuple(active_statements),
        show=(),
        entrypoint_predicates=(),
    )
    registry = _registry_from_pack(pack, program)
    asp = compile_asp(program, registry)
    prolog = compile_prolog(program, registry)
    return FormalizationCompiledProjection(program, registry, asp, prolog)


def release_formalization_projection(
    state: FormalizationExecutionState,
    compiled: FormalizationCompiledProjection,
    validators: tuple[ValidatorEvidence, ...],
    review_decisions: tuple[FormalReviewDecision, ...],
) -> FormalLogicRelease:
    """Use the native source and evidence closure checks to build a release value."""
    request = state.request
    program, asp, prolog = compiled.active_program, compiled.asp, compiled.prolog
    document_hashes = {item.source_version: item.source_sha256 for item in request.documents}
    required_versions = {
        provenance.source_version
        for statement in program.statements
        for provenance in statement.provenance
    }
    source_hashes = {version: document_hashes[version] for version in required_versions}
    return build_formal_logic_release(
        program,
        asp,
        prolog,
        source_version_hashes=source_hashes,
        validators=validators,
        review_decisions=review_decisions,
    )


def formalization_result(
    state: FormalizationExecutionState,
    compiled: FormalizationCompiledProjection | None = None,
    release: FormalLogicRelease | None = None,
) -> FormalizationWorkflowResult:
    """Return the native audit result for an empty, review, or released projection."""
    pack, config, translation = state.pack, state.request.config, state.translation
    dispositions = state.dispositions
    program = compiled.active_program if compiled else None
    registry = compiled.predicate_registry if compiled else None
    asp = compiled.asp if compiled else None
    prolog = compiled.prolog if compiled else None
    return FormalizationWorkflowResult(
        domain_id=pack.domain_id,
        corpus_id=config.corpus_id,
        translation_contract_id=translation.contract_id,
        dispositions=tuple(dispositions),
        active_program=program,
        predicate_registry=registry,
        asp=asp,
        prolog=prolog,
        release=release,
    )


def _select_translation_contract(pack: DomainPack, source: str, target: str):
    matches = [
        item
        for item in pack.translation_contracts
        if source in item.source_languages and target == item.target_language
    ]
    if len(matches) != 1:
        raise ValueError(
            f"domain {pack.domain_id!r} requires exactly one translation contract for "
            f"{source}->{target}; found {len(matches)}"
        )
    return matches[0]


def _validate_request_sources(pack: DomainPack, request: FormalizationWorkflowRequest) -> None:
    documents = {item.document_id: item for item in request.documents}
    versions: dict[str, str] = {}
    for document in request.documents:
        if document.document_kind not in pack.document_kinds:
            raise ValueError(
                f"document {document.document_id}: kind {document.document_kind!r} is not "
                f"registered by domain {pack.domain_id!r}"
            )
        if document.language != request.config.source_language:
            raise ValueError(f"document {document.document_id}: source language mismatch")
        previous = versions.setdefault(document.source_version, document.document_id)
        if previous != document.document_id:
            raise ValueError(f"source version {document.source_version!r} is not unique")
    for span in request.spans:
        document = documents.get(span.document_id)
        if document is None:
            raise ValueError(f"span {span.span_id}: unknown document {span.document_id}")
        if span.source_version != document.source_version:
            raise ValueError(f"span {span.span_id}: source version is stale")
        if document.source_text[span.start_char : span.end_char] != span.text:
            raise ValueError(
                f"span {span.span_id}: exact text does not match authenticated document offsets"
            )


def _unit_blockers(
    pack: DomainPack,
    unit: FormalizationUnit,
    spans: dict[str, FormalizationSpan],
) -> list[str]:
    reasons: list[str] = []
    if unit.unit_type not in pack.taxonomy.unit_types:
        raise ValueError(f"unit {unit.unit_id}: unknown domain unit type {unit.unit_type!r}")
    if unit.materiality_role not in pack.taxonomy.materiality_roles:
        raise ValueError(f"unit {unit.unit_id}: unknown materiality role {unit.materiality_role!r}")
    unknown_predicates = sorted(set(unit.predicate_candidates) - set(pack.predicates))
    if unknown_predicates:
        raise ValueError(
            f"unit {unit.unit_id}: predicates are not registered by the domain pack: "
            + ", ".join(unknown_predicates)
        )
    span = spans.get(unit.span_id)
    if span is None:
        reasons.append("source_span_missing")
    if unit.state != "approved":
        reasons.append(f"lifecycle_{unit.state}")
    if unit.statement is not None:
        referenced = [item for item in unit.statement.provenance if item.span_id == unit.span_id]
        if not referenced:
            reasons.append("exact_span_provenance_missing")
        elif span is not None and any(
            item.span_sha256 != span.span_sha256
            or item.source_version != span.source_version
            or item.document_id != span.document_id
            or item.section_id != span.section_id
            for item in referenced
        ):
            reasons.append("source_span_stale")
        for predicate in _statement_atoms(unit.statement):
            if predicate.predicate not in pack.predicates:
                raise ValueError(
                    f"unit {unit.unit_id}: executable predicate {predicate.predicate!r} is not "
                    "registered by the domain pack"
                )
    elif unit.state == "approved":
        reasons.append("logical_ir_missing")
    return reasons


def _registry_from_pack(pack: DomainPack, program: LogicalProgram) -> PredicateRegistry:
    observed: dict[str, tuple[ValueType, ...]] = {}
    for statement in program.statements:
        for atom in _statement_atoms(statement):
            descriptor = pack.predicates.get(atom.predicate)
            if descriptor is None:
                raise ValueError(f"undeclared domain predicate: {atom.predicate}")
            types = tuple(argument.value_type for argument in atom.arguments)
            if len(types) != len(descriptor.arguments):
                raise ValueError(f"predicate {atom.predicate}: domain-pack arity mismatch")
            for index, (actual, declared) in enumerate(
                zip(types, descriptor.arguments, strict=True), start=1
            ):
                allowed = _allowed_ir_types(pack, declared.value_type)
                if actual not in allowed:
                    expected = ", ".join(sorted(item.value for item in allowed))
                    raise ValueError(
                        f"predicate {atom.predicate}: argument {index} ({declared.name}) "
                        f"has type {actual.value!r}; domain type {declared.value_type!r} "
                        f"permits only {expected}"
                    )
            previous = observed.setdefault(atom.predicate, types)
            if previous != types:
                raise ValueError(f"predicate {atom.predicate}: inconsistent typed IR signatures")
    signatures = tuple(
        PredicateSignature(
            name=name,
            argument_names=tuple(argument.name for argument in pack.predicates[name].arguments),
            argument_types=types,
            family=pack.predicates[name].role,
            world_assumption=WorldAssumption.OPEN,
            units=tuple(None for _ in types),
            value_domains=tuple(None for _ in types),
        )
        for name, types in sorted(observed.items())
    )
    return PredicateRegistry(signatures=signatures)


def _allowed_ir_types(pack: DomainPack, domain_type: str) -> frozenset[ValueType]:
    """Map a domain declaration to the closed executable IR types it may refine to."""

    direct: dict[str, frozenset[ValueType]] = {
        "boolean": frozenset({ValueType.BOOLEAN}),
        "integer": frozenset({ValueType.COUNT}),
        "decimal": frozenset({ValueType.MONEY, ValueType.PERCENTAGE}),
        "string": frozenset({ValueType.SYMBOL}),
        "date": frozenset({ValueType.DATE}),
        "datetime": frozenset({ValueType.DATE}),
        "entity": frozenset(
            {
                ValueType.ENTITY_ID,
                ValueType.CLAIM_ID,
                ValueType.POLICY_ID,
                ValueType.DOCUMENT_ID,
                ValueType.SUBJECT,
                ValueType.COVERED_OBJECT,
                ValueType.BENEFIT,
                ValueType.COVERAGE,
                ValueType.EVENT,
                ValueType.OPTION,
                ValueType.GEOGRAPHY,
            }
        ),
    }
    explicit: dict[str, frozenset[ValueType]] = {
        "money_chf": frozenset({ValueType.MONEY}),
        "domain_option": frozenset({ValueType.OPTION}),
        "regulated_subject": frozenset({ValueType.SUBJECT}),
    }
    if domain_type in explicit:
        return explicit[domain_type]
    if domain_type in direct:
        return direct[domain_type]
    descriptor = pack.value_types.get(domain_type)
    if descriptor is None:
        raise ValueError(f"unknown domain value type: {domain_type}")
    allowed = direct.get(descriptor.scalar_kind)
    if allowed is None:
        raise ValueError(f"domain value type {domain_type!r} has no executable IR type mapping")
    return allowed


def _statement_atoms(statement: IRStatement) -> tuple[Atom, ...]:
    atoms: list[Atom] = []
    if statement.head is not None:
        atoms.append(statement.head)
    if statement.body is not None:
        atoms.extend(_expression_atoms(statement.body))
    return tuple(atoms)


def _expression_atoms(expression: LogicalExpression) -> list[Atom]:
    atoms: list[Atom] = []
    if expression.kind == ExpressionKind.ATOM and expression.atom is not None:
        atoms.append(expression.atom)
    if expression.aggregation is not None:
        atoms.append(expression.aggregation.atom)
    if expression.exception_target is not None:
        atoms.append(expression.exception_target)
    for operand in expression.operands:
        atoms.extend(_expression_atoms(operand))
    return atoms


__all__ = [
    "FormalizationDocument",
    "FormalizationSpan",
    "FormalizationUnit",
    "FormalizationWorkflowConfig",
    "FormalizationWorkflowRequest",
    "FormalizationWorkflowResult",
    "UnitDisposition",
    "run_formalization_workflow",
]
