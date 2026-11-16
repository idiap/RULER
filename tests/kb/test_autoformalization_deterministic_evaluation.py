# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Real deterministic oracles for generated autoformalization candidates."""

from __future__ import annotations

import hashlib

from ruler.contracts.semantics import (
    SemanticBasis,
    SemanticElement,
    SemanticRole,
    SemanticSourceSpan,
    SemanticTemporalConstraint,
)
from ruler.kb.formalization import (
    PredicateRegistry,
    PredicateSignature,
    ValueType,
    WorldAssumption,
)
from ruler.kb.behavioral_validation import BehavioralCase
from ruler.kb.formalization_mutation import (
    MutationOperator,
    detect_behavioral_regression,
    detect_source_link_drift,
    mutation_trial,
)
from ruler.kb.logical_ir import (
    Atom,
    Constant,
    ExpressionKind,
    IRStatement,
    LogicalExpression,
    LogicalProgram,
    Modality,
    Variable,
)
from ruler.kb.prolog_compiler import (
    EpistemicExpectation,
    EpistemicStatus,
    crosscheck_asp_prolog_epistemic,
)
from ruler.kb.semantic_validation import generate_protected_semantic_mutants
from ruler.reasoning.procurement_reference import (
    ProcurementScenario,
    enumerate_procurement_decision,
    rerun_procurement_counterfactual,
)


def _provenance():
    from ruler.kb.formalization import SourceSpanRef

    return (
        SourceSpanRef(
            document_id="fictional-model-act",
            source_version="2026-01-01",
            section_id="Article 12.2",
            span_id="article-12-2",
            span_sha256="sha256:" + "a" * 64,
        ),
    )


def _legal_program() -> tuple[LogicalProgram, PredicateRegistry]:
    applicant = Variable(name="Applicant", value_type=ValueType.ENTITY_ID)
    predicates = ("complete_application", "fee_paid", "serious_risk", "grant_permit")
    registry = PredicateRegistry(
        signatures=tuple(
            PredicateSignature(
                name=name,
                argument_names=("applicant",),
                argument_types=(ValueType.ENTITY_ID,),
                family="article-12",
                world_assumption=WorldAssumption.OPEN,
            )
            for name in predicates
        )
    )

    def atom(name: str) -> Atom:
        return Atom(predicate=name, arguments=(applicant,))

    body = LogicalExpression(
        kind="exception",
        operands=(
            LogicalExpression.all_of(
                LogicalExpression.from_atom(atom("complete_application")),
                LogicalExpression.from_atom(atom("fee_paid")),
            ),
        ),
        exception_target=atom("serious_risk"),
    )
    rule = IRStatement(
        statement_id="article-12-2-grant",
        modality=Modality.IMPLICATION,
        head=atom("grant_permit"),
        body=body,
        source_assertion_ids=("complete", "fee", "risk-exception", "grant"),
        provenance=_provenance(),
    )
    defeat = IRStatement(
        statement_id="article-12-2-defeat",
        modality=Modality.EXCLUSION,
        head=atom("grant_permit").model_copy(update={"classical_negation": True}),
        body=LogicalExpression.from_atom(atom("serious_risk")),
        source_assertion_ids=("risk-exception",),
        provenance=_provenance(),
    )
    return (
        LogicalProgram(program_id="article-12", version="2026", statements=(rule, defeat)),
        registry,
    )


def _fact(predicate: str, applicant: Constant) -> IRStatement:
    return IRStatement(
        statement_id=f"scenario:{predicate}",
        modality=Modality.FACT,
        head=Atom(predicate=predicate, arguments=(applicant,)),
        source_assertion_ids=(f"given:{predicate}",),
        provenance=_provenance(),
    )


def test_real_clingo_and_swi_preserve_true_false_unknown_and_conflict() -> None:
    base, registry = _legal_program()
    applicant = Constant(value_type=ValueType.ENTITY_ID, value="applicant-17")
    query = Atom(predicate="grant_permit", arguments=(applicant,))
    scenarios = {
        EpistemicStatus.TRUE: ("complete_application", "fee_paid"),
        EpistemicStatus.FALSE: ("serious_risk",),
        EpistemicStatus.UNKNOWN: ("complete_application",),
    }
    for status, facts in scenarios.items():
        program = base.model_copy(
            update={"statements": (*base.statements, *(_fact(name, applicant) for name in facts))}
        )
        report = crosscheck_asp_prolog_epistemic(
            program,
            (EpistemicExpectation(expectation_id=status.value, atom=query, expected=status),),
            registry,
        )
        assert report.equivalent
        report.require_equivalent()

    conflict = base.model_copy(
        update={
            "statements": (
                *base.statements,
                *(
                    _fact(name, applicant)
                    for name in ("complete_application", "fee_paid", "serious_risk", "grant_permit")
                ),
            )
        }
    )
    conflict_report = crosscheck_asp_prolog_epistemic(
        conflict,
        (EpistemicExpectation(expectation_id="conflict", atom=query, expected="both"),),
        registry,
    )
    assert not conflict_report.equivalent


def test_procurement_oracle_executes_boundaries_exceptions_and_counterfactuals() -> None:
    cases = (
        (
            ProcurementScenario(
                scenario_id="amount_10000_one_quote_budget_available",
                amount_chf=10_000,
                written_quotations=1,
                budget_available=True,
                split_purchase_pattern=False,
            ),
            EpistemicStatus.TRUE,
            "up_to_10000",
        ),
        (
            ProcurementScenario(
                scenario_id="amount_10001_two_quotes_finance_approved",
                amount_chf=10_001,
                written_quotations=2,
                finance_approval=True,
                budget_available=True,
                split_purchase_pattern=False,
            ),
            EpistemicStatus.FALSE,
            "10001_through_50000",
        ),
        (
            ProcurementScenario(
                scenario_id="amount_50000_three_quotes_finance_approved",
                amount_chf=50_000,
                written_quotations=3,
                finance_approval=True,
                budget_available=True,
                split_purchase_pattern=False,
            ),
            EpistemicStatus.TRUE,
            "10001_through_50000",
        ),
        (
            ProcurementScenario(scenario_id="amount_50001", amount_chf=50_001),
            EpistemicStatus.UNKNOWN,
            None,
        ),
        (
            ProcurementScenario(
                scenario_id="emergency_without_cfo",
                amount_chf=9_000,
                written_quotations=0,
                documented_emergency=True,
                cfo_approval_recorded=False,
                budget_available=True,
                split_purchase_pattern=False,
            ),
            EpistemicStatus.FALSE,
            "up_to_10000",
        ),
        (
            ProcurementScenario(
                scenario_id="emergency_with_cfo_over_budget",
                amount_chf=9_000,
                written_quotations=0,
                documented_emergency=True,
                cfo_approval_recorded=True,
                budget_available=False,
                split_purchase_pattern=False,
            ),
            EpistemicStatus.FALSE,
            "up_to_10000",
        ),
        (
            ProcurementScenario(
                scenario_id="related_6000_orders_within_30_days",
                amount_chf=6_000,
                written_quotations=3,
                finance_approval=True,
                budget_available=True,
                split_purchase_pattern=False,
                related_orders=((6_000, 30),),
            ),
            EpistemicStatus.TRUE,
            "10001_through_50000",
        ),
    )
    decisions = [enumerate_procurement_decision(case) for case, _, _ in cases]
    assert [item.scenario_id for item in decisions] == [case.scenario_id for case, _, _ in cases]
    assert [(item.status, item.threshold_tier) for item in decisions] == [
        (status, tier) for _, status, tier in cases
    ]
    assert all(item.selected_release == (item.objective == 1) for item in decisions)
    baseline = cases[0][0]
    counterfactual = rerun_procurement_counterfactual(baseline, budget_available=False)
    assert decisions[0].status is EpistemicStatus.TRUE
    assert counterfactual.status is EpistemicStatus.FALSE
    assert counterfactual.selected_release is False


def test_procurement_missing_fact_is_unknown_not_false() -> None:
    decision = enumerate_procurement_decision(
        ProcurementScenario(
            scenario_id="budget-not-supplied",
            amount_chf=8_000,
            written_quotations=1,
            split_purchase_pattern=False,
        )
    )
    assert decision.status is EpistemicStatus.UNKNOWN
    assert decision.feasible_assignments == (False,)


def test_generated_semantic_mutations_cover_and_kill_every_protected_dimension() -> None:
    source = "Authority shall act and notify within 10 days unless risk; it means the permit."
    digest = "sha256:" + hashlib.sha256(source.encode()).hexdigest()
    span = SemanticSourceSpan(
        span_id="s",
        artifact_id="act",
        artifact_sha256=digest,
        exact_text=source,
        start_char=0,
        end_char=len(source),
    )
    entities = (
        SemanticElement(
            element_id="authority",
            kind="entity",
            predicate="authority_actor",
            source_span_ids=("s",),
        ),
        SemanticElement(
            element_id="applicant",
            kind="entity",
            predicate="applicant_actor",
            source_span_ids=("s",),
        ),
    )
    basis = SemanticBasis(
        basis_id="full-protected-basis",
        context_id="article-12",
        spans=(span,),
        elements=(
            *entities,
            SemanticElement(
                element_id="duty",
                kind="proposition",
                predicate="grant_permit",
                roles=(SemanticRole(role="actor", element_id="authority"),),
                modality="obligatory",
                connective="and",
                source_span_ids=("s",),
            ),
            SemanticElement(
                element_id="risk",
                kind="exception",
                predicate="serious_risk",
                connective="unless",
                source_span_ids=("s",),
            ),
            SemanticElement(
                element_id="amount",
                kind="quantity",
                predicate="day_limit",
                value=10,
                unit="calendar_day",
                source_span_ids=("s",),
            ),
            SemanticElement(
                element_id="window",
                kind="temporal_relation",
                predicate="notice_window",
                source_span_ids=("s",),
                temporal=SemanticTemporalConstraint(
                    kind="relative_deadline",
                    anchor_event="notice_trigger",
                    amount=10,
                    unit="calendar_days",
                    comparison="before_or_on",
                ),
            ),
            SemanticElement(
                element_id="pronoun",
                kind="coreference",
                predicate="pronoun_it",
                roles=(SemanticRole(role="antecedent", element_id="authority"),),
                source_span_ids=("s",),
            ),
        ),
    )
    mutations = generate_protected_semantic_mutants(basis)
    assert {item.dimension for item in mutations} == {
        "actor",
        "modality",
        "polarity",
        "connective",
        "exception",
        "quantity",
        "temporal",
        "coreference",
    }
    assert all(item.changed_path and not item.report.projection_allowed for item in mutations)
    assert all(item.report.blockers for item in mutations)


def test_ir_mutation_kills_are_produced_by_executed_and_source_detectors() -> None:
    base, registry = _legal_program()
    rule = base.statements[0]
    assert rule.body is not None
    applicant = Constant(value_type=ValueType.ENTITY_ID, value="applicant-17")
    conjunction = LogicalExpression.all_of(
        LogicalExpression.from_atom(Atom(predicate="complete_application", arguments=(applicant,))),
        LogicalExpression.from_atom(Atom(predicate="fee_paid", arguments=(applicant,))),
    )
    connective_rule = rule.model_copy(
        update={
            "head": Atom(predicate="grant_permit", arguments=(applicant,)),
            "body": conjunction,
        }
    )
    connective_base = base.model_copy(update={"statements": (connective_rule,)})
    disjunction = conjunction.model_copy(update={"kind": ExpressionKind.DISJUNCTION})
    mutant = connective_base.model_copy(
        update={"statements": (connective_rule.model_copy(update={"body": disjunction}),)}
    )
    query = Atom(predicate="grant_permit", arguments=(applicant,))
    case = BehavioralCase(
        case_id="fee-missing-connective-killer",
        kind="negative",
        rule_family="permit-grant",
        statement_ids=(connective_rule.statement_id,),
        given=(Atom(predicate="complete_application", arguments=(applicant,)),),
        expected_absences=(query,),
    )
    detection = detect_behavioral_regression(connective_base, mutant, (case,), registry=registry)
    trial = mutation_trial(
        "article-12:and-to-or",
        MutationOperator.CONNECTIVE,
        connective_base,
        mutant,
        (detection,),
    )
    assert detection.detected and trial.killed
    assert "fee-missing-connective-killer" in detection.evidence_id
    assert any("body.kind" in path for path in trial.changed_paths)

    changed_span = rule.provenance[0].model_copy(
        update={"span_id": "wrong-article", "span_sha256": "sha256:" + "b" * 64}
    )
    source_mutant = base.model_copy(
        update={
            "statements": (
                rule.model_copy(update={"provenance": (changed_span,)}),
                base.statements[1],
            )
        }
    )
    source_detection = detect_source_link_drift(base, source_mutant)
    source_trial = mutation_trial(
        "article-12:source-link",
        MutationOperator.SOURCE_LINK,
        base,
        source_mutant,
        (source_detection,),
    )
    assert source_detection.detected and source_trial.killed
    assert "provenance" in source_detection.evidence_id
