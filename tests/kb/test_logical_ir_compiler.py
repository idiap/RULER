# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Typed logical IR, deterministic ASP compilation, and semantic validation tests."""

from __future__ import annotations

from datetime import date

import clingo
import pytest
from pydantic import ValidationError

from ruler.kb.asp_compiler import ASPCompilationError, compile_asp
from ruler.kb.formalization import FormalizationInventory, SourceSpanRef, ValueType
from ruler.kb.formalization_validation import validate_static_semantics
from ruler.kb.logical_ir import (
    Atom,
    Constant,
    IRStatement,
    LogicalExpression,
    LogicalProgram,
    Modality,
    ShowDirective,
    Variable,
)


def _span(*, exact: bool = True) -> SourceSpanRef:
    return SourceSpanRef(
        document_id="document:policy-2026",
        source_version="edition:2026-01",
        section_id="section:B1.2",
        span_id="span:B1.2:0-80" if exact else "assertion_payload:a1",
        span_sha256="sha256:" + "b" * 64,
    )


def _constant(value_type: ValueType, value: str | int | bool | date) -> Constant:
    return Constant(value_type=value_type, value=value)


def _fact(statement_id: str, atom: Atom, *, exact: bool = True) -> IRStatement:
    return IRStatement(
        statement_id=statement_id,
        modality=Modality.FACT,
        head=atom,
        source_assertion_ids=(f"assertion:{statement_id}",),
        provenance=(_span(exact=exact),),
    )


def _valid_program() -> LogicalProgram:
    claim = Variable(name="Claim", value_type=ValueType.CLAIM_ID)
    coverage = Variable(name="Coverage", value_type=ValueType.COVERAGE)
    amount = Variable(name="Amount", value_type=ValueType.MONEY)
    currency = Variable(name="Currency", value_type=ValueType.CURRENCY)
    service_fee = Atom(
        predicate="service_fee_applies",
        arguments=(claim, coverage, amount, currency),
    )
    coverage_head = Atom(predicate="coverage_applies", arguments=(claim, coverage))
    rule = IRStatement(
        statement_id="rule:coverage-after-service_fee",
        modality=Modality.IMPLICATION,
        head=coverage_head,
        body=LogicalExpression.from_atom(service_fee),
        source_assertion_ids=("assertion:rule",),
        provenance=(_span(),),
    )
    fact = _fact(
        "fact:service_fee",
        Atom(
            predicate="service_fee_applies",
            arguments=(
                _constant(ValueType.CLAIM_ID, "claim-1"),
                _constant(ValueType.COVERAGE, "collision"),
                _constant(ValueType.MONEY, 50000),
                _constant(ValueType.CURRENCY, "CHF"),
            ),
        ),
    )
    return LogicalProgram(
        program_id="policy:test",
        version="1",
        statements=(rule, fact),
        show=(ShowDirective(predicate="coverage_applies", arity=2),),
        entrypoint_predicates=("coverage_applies",),
    )


def test_ir_round_trips_deterministically_and_rejects_prose_fields() -> None:
    program = _valid_program()
    restored = LogicalProgram.model_validate_json(program.canonical_json())

    assert restored == program
    assert restored.sha256() == program.sha256()
    with pytest.raises(ValidationError, match="Extra inputs"):
        LogicalExpression.model_validate(
            {
                "kind": "atom",
                "atom": {
                    "predicate": "coverage_applies",
                    "arguments": [],
                },
                "source_prose": "coverage applies broadly",
            }
        )


def test_typed_constants_comparisons_and_temporal_bounds_fail_closed() -> None:
    with pytest.raises(ValidationError, match="require an integer"):
        Constant(value_type=ValueType.MONEY, value="CHF 500")
    with pytest.raises(ValidationError, match="must not follow"):
        LogicalExpression.model_validate(
            {
                "kind": "temporal",
                "temporal": {
                    "event": {"kind": "constant", "value_type": "event", "value": "loss"},
                    "start": {
                        "kind": "constant",
                        "value_type": "date",
                        "value": date(2026, 2, 1),
                    },
                    "end": {
                        "kind": "constant",
                        "value_type": "date",
                        "value": date(2026, 1, 1),
                    },
                },
            }
        )
    temporal = LogicalExpression.model_validate(
        {
            "kind": "temporal",
            "temporal": {
                "event": {"kind": "constant", "value_type": "event", "value": "loss"},
                "start": {
                    "kind": "constant",
                    "value_type": "date",
                    "value": date(2026, 1, 1),
                },
                "end": {
                    "kind": "constant",
                    "value_type": "date",
                    "value": date(2026, 12, 31),
                },
            },
        }
    )
    assert LogicalExpression.model_validate_json(temporal.model_dump_json()) == temporal


def test_compiler_emits_stable_clingo_program_and_expected_inference() -> None:
    program = _valid_program()
    first = compile_asp(program)
    second = compile_asp(program)
    reordered = compile_asp(
        program.model_copy(update={"statements": tuple(reversed(program.statements))})
    )

    assert first.text == second.text
    assert first.sha256 == second.sha256
    assert reordered.sha256 == first.sha256
    assert "#show coverage_applies/2." in first.text
    control = clingo.Control()
    control.add("base", [], first.text)
    control.ground([("base", [])])
    models: list[set[str]] = []
    with control.solve(yield_=True) as handle:
        for model in handle:
            models.append({str(symbol) for symbol in model.symbols(shown=True)})
    assert models == [{'coverage_applies("claim-1","collision")'}]


def test_compiler_rejects_ad_hoc_predicates_and_unlowered_temporal_expressions() -> None:
    ad_hoc = LogicalProgram(
        program_id="bad:predicate",
        version="1",
        statements=(
            _fact(
                "fact:ad-hoc",
                Atom(
                    predicate="marketing_claim",
                    arguments=(_constant(ValueType.SYMBOL, "best"),),
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="undeclared or unapproved"):
        compile_asp(ad_hoc)

    temporal = LogicalExpression.model_validate(
        {
            "kind": "temporal",
            "temporal": {
                "event": {"kind": "constant", "value_type": "event", "value": "loss"},
                "start": {
                    "kind": "constant",
                    "value_type": "date",
                    "value": date(2026, 1, 1),
                },
                "end": {
                    "kind": "constant",
                    "value_type": "date",
                    "value": date(2026, 12, 31),
                },
            },
        }
    )
    statement = IRStatement(
        statement_id="temporal:unlowered",
        modality=Modality.TEMPORAL_RULE,
        head=Atom(
            predicate="coverage_applies",
            arguments=(
                _constant(ValueType.CLAIM_ID, "claim-1"),
                _constant(ValueType.COVERAGE, "collision"),
            ),
        ),
        body=temporal,
        source_assertion_ids=("assertion:temporal",),
        provenance=(_span(),),
    )
    with pytest.raises(ASPCompilationError, match="normalized to declared predicates"):
        compile_asp(LogicalProgram(program_id="bad:temporal", version="1", statements=(statement,)))


def test_static_semantics_accepts_well_typed_safe_grounded_program() -> None:
    report = validate_static_semantics(_valid_program())
    assert report.valid
    assert report.issues == ()


def test_static_semantics_names_all_core_defect_classes() -> None:
    policy = _constant(ValueType.POLICY_ID, "policy-1")
    subject = _constant(ValueType.SUBJECT, "holder")
    positive = Atom(predicate="contract_subject", arguments=(policy, subject))
    negative = positive.model_copy(update={"classical_negation": True})
    undeclared = Atom(
        predicate="unknown_policy_predicate",
        arguments=(_constant(ValueType.SYMBOL, "x"),),
    )
    wrong_arity = Atom(predicate="contract_subject", arguments=(policy,))
    wrong_type = Atom(
        predicate="contract_subject",
        arguments=(policy, _constant(ValueType.CURRENCY, "CHF")),
    )
    unsafe_variable = Variable(name="Policy", value_type=ValueType.POLICY_ID)
    unsafe = IRStatement(
        statement_id="rule:unsafe",
        modality=Modality.IMPLICATION,
        head=Atom(
            predicate="document_applies",
            arguments=(_constant(ValueType.DOCUMENT_ID, "doc"), unsafe_variable),
        ),
        body=LogicalExpression.from_atom(positive),
        source_assertion_ids=("assertion:unsafe",),
        provenance=(_span(),),
    )
    cycle_variable = Variable(name="Claim", value_type=ValueType.CLAIM_ID)
    cycle_coverage = Variable(name="Coverage", value_type=ValueType.COVERAGE)
    cyclic_atom = Atom(
        predicate="coverage_applies",
        arguments=(cycle_variable, cycle_coverage),
    )
    cyclic = IRStatement(
        statement_id="rule:cycle",
        modality=Modality.IMPLICATION,
        head=cyclic_atom,
        body=LogicalExpression.from_atom(cyclic_atom),
        source_assertion_ids=("assertion:cycle",),
        provenance=(_span(),),
    )
    program = LogicalProgram(
        program_id="bad:all-static",
        version="1",
        statements=(
            _fact("fact:positive", positive),
            _fact("fact:negative", negative),
            _fact("fact:undeclared", undeclared),
            _fact("fact:arity", wrong_arity),
            _fact("fact:type", wrong_type),
            _fact("fact:fallback", positive, exact=False),
            unsafe,
            cyclic,
        ),
        show=(ShowDirective(predicate="document_applies", arity=2),),
        entrypoint_predicates=("document_applies",),
    )
    report = validate_static_semantics(program)
    codes = {issue.code for issue in report.issues}

    assert {
        "undeclared_predicate",
        "arity_error",
        "type_error",
        "unsafe_variable",
        "contradictory_fact",
        "dependency_cycle",
        "unreachable_rule",
        "missing_grounding",
    } <= codes
    assert not report.valid
    with pytest.raises(ValueError, match="static semantic validation failed"):
        report.require_valid()


def test_static_semantics_rejects_statements_orphaned_from_inventory() -> None:
    empty_inventory = FormalizationInventory(
        inventory_id="inventory:empty",
        release_id="release:test",
        expected_assertion_count=0,
        items=[],
    )
    report = validate_static_semantics(_valid_program(), inventory=empty_inventory)
    assert "orphan_clause" in {issue.code for issue in report.issues}
