# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Generic applicability and consequence assembly over the neutral rule engine."""

from __future__ import annotations

import clingo

from ruler.evaluation.contracts import (
    CounterfactualChange,
    CounterfactualResult,
    EvaluationPacket,
    EvaluationRequest,
    EvaluationStatus,
    EvaluationTraceEvent,
    RuleConsequence,
)
from ruler.kb.formalization import PredicateRegistry
from ruler.kb.logical_ir import Atom, LogicalProgram
from ruler.kb.rule_engine import run_rule_scenario


class EvaluationPipeline:
    """Evaluate explicit consequences and preserve open-world unknowns."""

    def __init__(
        self,
        program: LogicalProgram,
        registry: PredicateRegistry,
        *,
        outcome_predicate: str = "evaluation_outcome",
    ) -> None:
        signature = registry.require(outcome_predicate)
        if signature.arity != 3:
            raise ValueError("evaluation outcome predicates require rule, subject, and status")
        self.program = program
        self.registry = registry
        self.outcome_predicate = outcome_predicate

    def evaluate(self, request: EvaluationRequest) -> EvaluationPacket:
        result = run_rule_scenario(self.program, request.facts, registry=self.registry)
        expected = {item.rule_id: item for item in request.expected_rules}
        explicit: dict[str, tuple[str, EvaluationStatus, str]] = {}
        for atom_text in sorted(result.atoms):
            symbol = clingo.parse_term(atom_text)
            if symbol.type != clingo.SymbolType.Function or symbol.name != self.outcome_predicate:
                continue
            if len(symbol.arguments) != 3:
                raise ValueError(f"malformed evaluation outcome: {atom_text}")
            rule_id, subject, status_value = (_symbol_text(item) for item in symbol.arguments)
            if rule_id not in expected:
                raise ValueError(f"outcome references rule outside the pinned request: {rule_id}")
            try:
                status = EvaluationStatus(status_value)
            except ValueError as exc:
                raise ValueError(f"unknown evaluation status in {atom_text}") from exc
            prior = explicit.get(rule_id)
            current = (subject, status, atom_text)
            if prior is not None and prior != current:
                raise ValueError(f"conflicting outcomes for rule {rule_id}")
            explicit[rule_id] = current

        consequences: list[RuleConsequence] = []
        for rule_id, rule in sorted(expected.items()):
            outcome = explicit.get(rule_id)
            consequences.append(
                RuleConsequence(
                    rule_id=rule_id,
                    modality=rule.modality,
                    status=outcome[1] if outcome else EvaluationStatus.UNKNOWN,
                    subject=outcome[0] if outcome else None,
                    evidence=rule.evidence,
                    release_id=request.release_id,
                    derived_atom=outcome[2] if outcome else None,
                )
            )
        trace = (
            EvaluationTraceEvent(
                sequence=0,
                event_type="facts_activated",
                artifact_ids=tuple(sorted(atom.key() for atom in request.facts)),
            ),
            EvaluationTraceEvent(
                sequence=1,
                event_type="program_evaluated",
                artifact_ids=(self.program.program_id, self.program.sha256(), request.release_id),
            ),
            EvaluationTraceEvent(
                sequence=2,
                event_type="consequences_assembled",
                artifact_ids=tuple(item.rule_id for item in consequences),
            ),
        )
        return EvaluationPacket(
            request_id=request.request_id,
            case_id=request.case_id,
            release_id=request.release_id,
            program_id=self.program.program_id,
            program_sha256=self.program.sha256(),
            consequences=tuple(consequences),
            trace=trace,
        )

    def counterfactual(
        self,
        request: EvaluationRequest,
        *,
        probe_id: str,
        facts: tuple[Atom, ...],
    ) -> CounterfactualResult:
        """Evaluate an explicit replacement fact set and report status changes only."""
        baseline = self.evaluate(request)
        counterfactual_request = request.model_copy(
            update={"request_id": f"{request.request_id}:counterfactual:{probe_id}", "facts": facts}
        )
        counterfactual = self.evaluate(counterfactual_request)
        baseline_by_rule = {item.rule_id: item.status for item in baseline.consequences}
        counterfactual_by_rule = {item.rule_id: item.status for item in counterfactual.consequences}
        changes = tuple(
            CounterfactualChange(
                rule_id=rule_id,
                baseline_status=baseline_by_rule[rule_id],
                counterfactual_status=counterfactual_by_rule[rule_id],
            )
            for rule_id in sorted(baseline_by_rule)
            if baseline_by_rule[rule_id] != counterfactual_by_rule[rule_id]
        )
        return CounterfactualResult(
            probe_id=probe_id,
            baseline=baseline,
            counterfactual=counterfactual,
            changes=changes,
        )


def evaluate_request(
    program: LogicalProgram, registry: PredicateRegistry, request: EvaluationRequest
) -> EvaluationPacket:
    """Convenience entrypoint for document/case evaluation without solver ranking."""
    return EvaluationPipeline(program, registry).evaluate(request)


def _symbol_text(symbol: clingo.Symbol) -> str:
    if symbol.type == clingo.SymbolType.String:
        return symbol.string
    if symbol.type == clingo.SymbolType.Function and not symbol.arguments:
        return symbol.name
    if symbol.type == clingo.SymbolType.Number:
        return str(symbol.number)
    raise ValueError(f"evaluation outcomes require scalar arguments, got {symbol}")
