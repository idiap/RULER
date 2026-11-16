# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Reviewed logical program for the locally-authored Regulatory Proof Instrument."""

from __future__ import annotations

import hashlib

from ruler.evaluation.contracts import ExpectedRule
from ruler.kb.formalization import (
    PredicateRegistry,
    PredicateSignature,
    SourceSpanRef,
    ValueType,
    WorldAssumption,
)
from ruler.kb.logical_ir import (
    Atom,
    Comparison,
    Constant,
    ExpressionKind,
    IRStatement,
    LogicalExpression,
    LogicalProgram,
    Modality,
    ShowDirective,
    Variable,
)
from ruler.paths import REPO_ROOT

SOURCE_FILE = REPO_ROOT / "data" / "regulatory" / "proof" / "regulatory_proof_instrument.txt"
SOURCE_VERSION = "regulatory-proof-instrument/1.0"
DOCUMENT_ID = "regulatory_proof_instrument"
REGULATORY_SOURCE_SHA256 = "sha256:76c199f5e8e0be6ec3676b045f9ab0c388ec3dcd6c99cca586ffc10c967f8669"
REGULATORY_PROGRAM_SHA256 = (
    "sha256:88606f40dd668b997be859e93a6aa2a8a0b3a51080c4cd7a9a3bda6425a51091"
)
REGULATORY_RELEASE_ID = (
    "kb_release:a7177ef2cf36992a1bb0b5e5a9f59b98573e237a001000a20a70569b3fb8dc27"
)


def _signature(
    name: str, names: tuple[str, ...], types: tuple[ValueType, ...]
) -> PredicateSignature:
    return PredicateSignature(
        name=name,
        argument_names=names,
        argument_types=types,
        family="regulatory_proof",
        world_assumption=WorldAssumption.OPEN,
        units=tuple(None for _ in types),
        value_domains=tuple(None for _ in types),
    )


def regulatory_registry() -> PredicateRegistry:
    """Return the proof domain's closed, independently registered vocabulary."""
    subject = (ValueType.SUBJECT,)
    return PredicateRegistry(
        signatures=(
            _signature("in_scope", ("subject",), subject),
            _signature("out_of_scope", ("subject",), subject),
            _signature("submitted_notice", ("subject",), subject),
            _signature("notice_missing", ("subject",), subject),
            _signature("within_deadline", ("subject",), subject),
            _signature("after_deadline", ("subject",), subject),
            _signature("restricted_action", ("subject",), subject),
            _signature("authorized_exception", ("subject",), subject),
            _signature(
                "regulated_quantity", ("subject", "quantity"), (ValueType.SUBJECT, ValueType.COUNT)
            ),
            _signature(
                "evaluation_outcome",
                ("rule", "subject", "status"),
                (ValueType.SYMBOL, ValueType.SUBJECT, ValueType.SYMBOL),
            ),
        )
    )


def _source_spans() -> dict[str, SourceSpanRef]:
    text = SOURCE_FILE.read_text(encoding="utf-8")
    source_hash = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    if source_hash != REGULATORY_SOURCE_SHA256:
        raise ValueError("regulatory proof source hash changed without a new pinned version")
    lines = [line for line in text.splitlines() if line.startswith("RG-")]
    spans: dict[str, SourceSpanRef] = {}
    for line in lines:
        section = line.split()[0].removesuffix(":")
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()
        spans[section] = SourceSpanRef(
            document_id=DOCUMENT_ID,
            source_version=SOURCE_VERSION,
            section_id=section,
            span_id=f"{DOCUMENT_ID}:{section}",
            span_sha256=f"sha256:{digest}",
        )
    required = {"RG-1", "RG-3", "RG-4", "RG-5", "RG-6", "RG-7"}
    if set(spans) != required | {"RG-2"}:
        raise ValueError("regulatory proof source sections changed without review")
    return spans


def _constant(value: str, value_type: ValueType = ValueType.SYMBOL) -> Constant:
    return Constant(value_type=value_type, value=value)


def _atom(predicate: str, *arguments: Constant | Variable) -> Atom:
    return Atom(predicate=predicate, arguments=arguments)


def _outcome(rule_id: str, status: str, subject: Variable) -> Atom:
    return _atom("evaluation_outcome", _constant(rule_id), subject, _constant(status))


def build_regulatory_program() -> LogicalProgram:
    """Build the reviewed obligation/prohibition/limit/deadline proof program."""
    spans = _source_spans()
    subject = Variable(name="Subject", value_type=ValueType.SUBJECT)
    quantity = Variable(name="Quantity", value_type=ValueType.COUNT)
    scope = LogicalExpression.from_atom(_atom("in_scope", subject))
    statements: list[IRStatement] = []

    def add(
        statement_id: str,
        rule_id: str,
        status: str,
        body: LogicalExpression,
        section: str,
        modality: Modality = Modality.IMPLICATION,
    ) -> None:
        statements.append(
            IRStatement(
                statement_id=statement_id,
                modality=modality,
                head=_outcome(rule_id, status, subject),
                body=body,
                source_assertion_ids=(f"assertion:{section}",),
                provenance=(spans[section],),
            )
        )

    add(
        "obligation_satisfied",
        "rg_notice_obligation",
        "satisfied",
        LogicalExpression.all_of(
            scope,
            LogicalExpression.from_atom(_atom("submitted_notice", subject)),
            LogicalExpression.from_atom(_atom("within_deadline", subject)),
        ),
        "RG-3",
    )
    add(
        "obligation_missing",
        "rg_notice_obligation",
        "violated",
        LogicalExpression.all_of(
            scope, LogicalExpression.from_atom(_atom("notice_missing", subject))
        ),
        "RG-3",
    )
    prohibited = LogicalExpression.from_atom(_atom("restricted_action", subject))
    add(
        "prohibition_violated",
        "rg_action_prohibition",
        "violated",
        LogicalExpression(
            kind=ExpressionKind.EXCEPTION,
            operands=(LogicalExpression.all_of(scope, prohibited),),
            exception_target=_atom("authorized_exception", subject),
        ),
        "RG-4",
        Modality.EXCLUSION,
    )
    add(
        "prohibition_exception",
        "rg_action_prohibition",
        "exception",
        LogicalExpression.all_of(
            scope, prohibited, LogicalExpression.from_atom(_atom("authorized_exception", subject))
        ),
        "RG-5",
        Modality.EXCEPTION,
    )
    measured = LogicalExpression.from_atom(_atom("regulated_quantity", subject, quantity))
    for status, operator in (("satisfied", "<="), ("violated", ">")):
        comparison = LogicalExpression(
            kind=ExpressionKind.COMPARISON,
            comparison=Comparison.model_validate(
                dict(
                    operator=operator,
                    left=quantity,
                    right=Constant(value_type=ValueType.COUNT, value=10),
                )
            ),
        )
        add(
            f"numeric_{status}",
            "rg_quantity_limit",
            status,
            LogicalExpression.all_of(scope, measured, comparison),
            "RG-6",
            Modality.LIMIT,
        )
    for status, predicate in (("satisfied", "within_deadline"), ("violated", "after_deadline")):
        add(
            f"deadline_{status}",
            "rg_notice_deadline",
            status,
            LogicalExpression.all_of(scope, LogicalExpression.from_atom(_atom(predicate, subject))),
            "RG-7",
            Modality.TEMPORAL_RULE,
        )
    for rule_id in (
        "rg_action_prohibition",
        "rg_notice_deadline",
        "rg_notice_obligation",
        "rg_quantity_limit",
    ):
        add(
            f"{rule_id}_inapplicable",
            rule_id,
            "inapplicable",
            LogicalExpression.from_atom(_atom("out_of_scope", subject)),
            "RG-1",
        )
    program = LogicalProgram(
        program_id="regulatory.proof.evaluation",
        version="1.0",
        statements=tuple(statements),
        show=(ShowDirective(predicate="evaluation_outcome", arity=3),),
        entrypoint_predicates=("in_scope", "out_of_scope"),
    )
    if program.sha256() != REGULATORY_PROGRAM_SHA256:
        raise ValueError("regulatory proof program changed without a new pinned release")
    return program


def regulatory_expected_rules() -> tuple[ExpectedRule, ...]:
    spans = _source_spans()
    return (
        ExpectedRule(
            rule_id="rg_notice_obligation", modality="obligation", evidence=(spans["RG-3"],)
        ),
        ExpectedRule(
            rule_id="rg_action_prohibition",
            modality="prohibition",
            evidence=(spans["RG-4"], spans["RG-5"]),
        ),
        ExpectedRule(
            rule_id="rg_quantity_limit", modality="numeric_limit", evidence=(spans["RG-6"],)
        ),
        ExpectedRule(
            rule_id="rg_notice_deadline", modality="temporal_rule", evidence=(spans["RG-7"],)
        ),
    )
