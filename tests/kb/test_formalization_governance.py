# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Prolog mirrors, behavioral coverage, mutation, and immutable release tests."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from ruler.kb.asp_compiler import compile_asp
from ruler.kb.behavioral_validation import (
    BehavioralCase,
    BehavioralCaseKind,
    evaluate_behavioral_cases,
)
from ruler.kb.formalization import SourceSpanRef, ValueType
from ruler.kb.formalization_mutation import (
    MutationDetection,
    MutationDetectorKind,
    MutationOperator,
    detect_static_reference_drift,
    evaluate_mutation_gate,
    mutation_trial,
)
from ruler.kb.formalization_release import (
    FormalLogicRelease,
    FormalReviewDecision,
    ValidatorEvidence,
    build_formal_logic_release,
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
    TemporalInterval,
    Variable,
)
from ruler.kb.prolog_compiler import (
    ConclusionExpectation,
    compile_prolog,
    crosscheck_asp_prolog,
)


def _span(span_id: str = "span:B1.2:0-80", hash_character: str = "b") -> SourceSpanRef:
    return SourceSpanRef(
        document_id="document:policy-2026",
        source_version="edition:2026-01",
        section_id="section:B1.2",
        span_id=span_id,
        span_sha256="sha256:" + hash_character * 64,
    )


def _constant(value_type: ValueType, value: str | int) -> Constant:
    return Constant(value_type=value_type, value=value)


def _service_fee_atom(*, variables: bool, amount: int = 50000) -> Atom:
    if variables:
        return Atom(
            predicate="service_fee_applies",
            arguments=(
                Variable(name="Claim", value_type=ValueType.CLAIM_ID),
                Variable(name="Coverage", value_type=ValueType.COVERAGE),
                Variable(name="Amount", value_type=ValueType.MONEY),
                Variable(name="Currency", value_type=ValueType.CURRENCY),
            ),
        )
    return Atom(
        predicate="service_fee_applies",
        arguments=(
            _constant(ValueType.CLAIM_ID, "claim-1"),
            _constant(ValueType.COVERAGE, "collision"),
            _constant(ValueType.MONEY, amount),
            _constant(ValueType.CURRENCY, "CHF"),
        ),
    )


def _coverage_atom(claim: str = "claim-1") -> Atom:
    return Atom(
        predicate="coverage_applies",
        arguments=(
            _constant(ValueType.CLAIM_ID, claim),
            _constant(ValueType.COVERAGE, "collision"),
        ),
    )


def _program(*, include_fact: bool) -> LogicalProgram:
    service_fee = _service_fee_atom(variables=True)
    rule = IRStatement(
        statement_id="rule:coverage-after-service_fee",
        modality=Modality.IMPLICATION,
        head=Atom(
            predicate="coverage_applies",
            arguments=(service_fee.arguments[0], service_fee.arguments[1]),
        ),
        body=LogicalExpression.from_atom(service_fee),
        source_assertion_ids=("assertion:rule",),
        provenance=(_span(),),
    )
    statements = [rule]
    if include_fact:
        statements.append(
            IRStatement(
                statement_id="fact:service_fee",
                modality=Modality.FACT,
                head=_service_fee_atom(variables=False),
                source_assertion_ids=("assertion:fact",),
                provenance=(_span("span:B1.3:0-40", "c"),),
            )
        )
    return LogicalProgram(
        program_id="policy:governance-test",
        version="1",
        statements=tuple(statements),
        show=(ShowDirective(predicate="coverage_applies", arity=2),),
        entrypoint_predicates=("coverage_applies",),
    )


def test_prolog_mirror_is_stable_and_matches_authoritative_asp_conclusions() -> None:
    program = _program(include_fact=True)
    first = compile_prolog(program)
    second = compile_prolog(program)

    assert first.text == second.text
    assert first.sha256 == second.sha256
    assert first.authority == "asp"
    assert "coverage_applies(Claim,Coverage) :-" in first.text
    report = crosscheck_asp_prolog(
        program,
        (
            ConclusionExpectation(
                expectation_id="covered-claim",
                atom=_coverage_atom(),
                expected=True,
            ),
            ConclusionExpectation(
                expectation_id="unseen-claim",
                atom=_coverage_atom("claim-2"),
                expected=False,
            ),
        ),
    )
    assert report.equivalent
    report.require_equivalent()


def test_behavioral_gate_requires_six_case_kinds_and_negative_material_coverage() -> None:
    program = _program(include_fact=False)
    rule_id = "rule:coverage-after-service_fee"
    cases = []
    for kind in BehavioralCaseKind:
        positive = kind in {BehavioralCaseKind.POSITIVE, BehavioralCaseKind.BOUNDARY}
        given = (_service_fee_atom(variables=False),) if positive else ()
        expected_satisfiable = True
        if kind == BehavioralCaseKind.CONFLICT:
            service_fee = _service_fee_atom(variables=False)
            given = (service_fee, service_fee.model_copy(update={"classical_negation": True}))
            expected_satisfiable = False
        cases.append(
            BehavioralCase(
                case_id=f"coverage:{kind.value}",
                kind=kind,
                rule_family="coverage",
                statement_ids=(rule_id,),
                given=given,
                expected_conclusions=(_coverage_atom(),) if positive else (),
                expected_absences=() if positive else (_coverage_atom(),),
                expected_satisfiable=expected_satisfiable,
            )
        )
    report = evaluate_behavioral_cases(
        program,
        tuple(cases),
        validated_statement_ids=frozenset({rule_id}),
        material_statement_ids=frozenset({rule_id}),
        required_rule_families=frozenset({"coverage"}),
    )

    assert report.passed
    report.require_passed()
    incomplete = evaluate_behavioral_cases(
        program,
        tuple(cases[:2]),
        validated_statement_ids=frozenset({rule_id}),
        material_statement_ids=frozenset({rule_id}),
        required_rule_families=frozenset({"coverage"}),
    )
    assert incomplete.incomplete_rule_families == ("coverage",)
    with pytest.raises(ValueError, match="behavioral coverage gate failed"):
        incomplete.require_passed()


def test_mutation_gate_requires_all_high_risk_operators_and_independent_detection() -> None:
    base = _program(include_fact=True)
    rule, fact = base.statements

    def replace(program: LogicalProgram, old: IRStatement, new: IRStatement) -> LogicalProgram:
        return program.model_copy(
            update={
                "statements": tuple(
                    new if statement is old else statement for statement in program.statements
                )
            }
        )

    assert rule.body is not None
    negated_rule = rule.model_copy(
        update={"body": LogicalExpression(kind=ExpressionKind.NEGATION, operands=(rule.body,))}
    )
    negated = replace(base, rule, negated_rule)

    second_operand = LogicalExpression.from_atom(
        Atom(
            predicate="excluded_event",
            arguments=(
                _constant(ValueType.POLICY_ID, "policy-1"),
                _constant(ValueType.EVENT, "collision"),
            ),
        )
    )
    conjunction_rule = rule.model_copy(
        update={"body": LogicalExpression.all_of(rule.body, second_operand)}
    )
    conjunction = replace(base, rule, conjunction_rule)
    disjunction_rule = conjunction_rule.model_copy(
        update={
            "body": LogicalExpression(
                kind=ExpressionKind.DISJUNCTION,
                operands=(rule.body, second_operand),
            )
        }
    )
    disjunction = replace(conjunction, conjunction_rule, disjunction_rule)

    comparison_body = LogicalExpression(
        kind=ExpressionKind.COMPARISON,
        comparison=Comparison(
            operator=">=",
            left=_constant(ValueType.MONEY, 50000),
            right=_constant(ValueType.MONEY, 50000),
        ),
    )
    comparison_rule = rule.model_copy(update={"body": comparison_body})
    comparison_program = replace(base, rule, comparison_rule)
    changed_comparison = comparison_body.model_copy(
        update={"comparison": comparison_body.comparison.model_copy(update={"operator": ">"})}
    )
    comparison_mutant = replace(
        comparison_program,
        comparison_rule,
        comparison_rule.model_copy(update={"body": changed_comparison}),
    )

    assert fact.head is not None
    fact_arguments = list(fact.head.arguments)
    fact_arguments[2] = _constant(ValueType.COUNT, 50000)
    unit_mutant = replace(
        base,
        fact,
        fact.model_copy(
            update={"head": fact.head.model_copy(update={"arguments": tuple(fact_arguments)})}
        ),
    )
    constant_arguments = list(fact.head.arguments)
    constant_arguments[2] = _constant(ValueType.MONEY, 50001)
    constant_mutant = replace(
        base,
        fact,
        fact.model_copy(
            update={"head": fact.head.model_copy(update={"arguments": tuple(constant_arguments)})}
        ),
    )

    precedence_fact = IRStatement(
        statement_id="fact:precedence",
        modality=Modality.FACT,
        head=Atom(
            predicate="takes_precedence",
            arguments=(
                _constant(ValueType.SYMBOL, "special-clause"),
                _constant(ValueType.SYMBOL, "general-clause"),
            ),
        ),
        source_assertion_ids=("assertion:precedence",),
        provenance=(_span(),),
    )
    precedence_program = LogicalProgram(
        program_id="policy:precedence",
        version="1",
        statements=(precedence_fact,),
    )
    precedence_mutant = precedence_program.model_copy(
        update={
            "statements": (
                precedence_fact.model_copy(
                    update={
                        "head": precedence_fact.head.model_copy(
                            update={"arguments": tuple(reversed(precedence_fact.head.arguments))}
                        )
                    }
                ),
            )
        }
    )

    temporal = LogicalExpression(
        kind=ExpressionKind.TEMPORAL,
        temporal=TemporalInterval(
            event=_constant(ValueType.EVENT, "collision"),
            start=Constant(value_type=ValueType.DATE, value=date(2026, 1, 1)),
            end=Constant(value_type=ValueType.DATE, value=date(2026, 12, 31)),
            end_inclusive=True,
        ),
    )
    temporal_rule = rule.model_copy(update={"body": temporal, "modality": Modality.TEMPORAL_RULE})
    temporal_program = replace(base, rule, temporal_rule)
    temporal_mutant_expression = temporal.model_copy(
        update={"temporal": temporal.temporal.model_copy(update={"end_inclusive": False})}
    )
    temporal_mutant = replace(
        temporal_program,
        temporal_rule,
        temporal_rule.model_copy(update={"body": temporal_mutant_expression}),
    )

    source_mutant = replace(
        base,
        rule,
        rule.model_copy(update={"provenance": (_span("span:B1.2:1-80", "e"),)}),
    )
    mutations = {
        MutationOperator.NEGATION: (base, negated),
        MutationOperator.CONNECTIVE: (conjunction, disjunction),
        MutationOperator.COMPARISON: (comparison_program, comparison_mutant),
        MutationOperator.UNIT: (base, unit_mutant),
        MutationOperator.CONSTANT: (base, constant_mutant),
        MutationOperator.PRECEDENCE: (precedence_program, precedence_mutant),
        MutationOperator.TEMPORAL_BOUND: (temporal_program, temporal_mutant),
        MutationOperator.SOURCE_LINK: (base, source_mutant),
    }
    trials = [
        mutation_trial(
            f"mutation:{operator.value}",
            operator,
            original,
            mutant,
            (detect_static_reference_drift(operator, original, mutant),),
        )
        for operator, (original, mutant) in mutations.items()
    ]
    report = evaluate_mutation_gate(tuple(trials))

    assert report.passed
    assert {trial.operator for trial in trials} == set(MutationOperator)
    assert all(trial.changed_paths for trial in trials)
    assert all(
        detection.detected and "$." in detection.evidence_id
        for trial in trials
        for detection in trial.detections
    )
    report.require_passed()
    survivor = trials[0].model_copy(
        update={
            "detections": (
                MutationDetection(
                    detector_kind=MutationDetectorKind.IMMUTABLE_RELEASE,
                    evidence_id="release:only",
                    detected=True,
                ),
            )
        }
    )
    failed = evaluate_mutation_gate((survivor,))
    assert failed.surviving_trial_ids == (survivor.trial_id,)
    assert failed.missing_operators


def test_immutable_release_binds_every_dependency_and_invalidates_stale_evidence() -> None:
    program = _program(include_fact=True)
    asp = compile_asp(program)
    prolog = compile_prolog(program)
    validator = ValidatorEvidence.create(
        validator_id="static-semantics",
        validator_version="1",
        evaluated_ir_sha256=program.sha256(),
        passed=True,
    )
    decision = FormalReviewDecision.create(
        decision_id="review:1",
        reviewer_id="reviewer:test",
        decision="approved",
        logical_unit_ids=tuple(statement.statement_id for statement in program.statements),
        rationale="The source-locked logic and behavior fixtures were reviewed.",
        decided_at=datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
    )
    source_hashes = {"edition:2026-01": "sha256:" + "d" * 64}
    release = build_formal_logic_release(
        program,
        asp,
        prolog,
        source_version_hashes=source_hashes,
        validators=(validator,),
        review_decisions=(decision,),
    )

    assert release.ir_sha256 == program.sha256()
    assert set(release.generated_program_hashes) == {"asp", "prolog"}
    assert len(release.span_hashes) == 2
    assert FormalLogicRelease.model_validate_json(release.model_dump_json()) == release
    tampered = release.model_dump(mode="json")
    tampered["generated_program_hashes"]["asp"] = "sha256:" + "e" * 64
    with pytest.raises(ValidationError, match="release ID"):
        FormalLogicRelease.model_validate(tampered)

    changed_program = program.model_copy(update={"version": "2"})
    with pytest.raises(ValueError, match="stale"):
        build_formal_logic_release(
            changed_program,
            compile_asp(changed_program),
            compile_prolog(changed_program),
            source_version_hashes=source_hashes,
            validators=(validator,),
            review_decisions=(decision,),
        )
