# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Small application facade over the CBR kernel for CLI, API, and workflows."""

from __future__ import annotations

from ruler.cbr.adaptation import (
    FactBuilder,
    apply_adaptation,
    verify_adaptation,
)
from ruler.cbr.contracts import (
    AdaptationPlan,
    CBRCaseRecord,
    OutcomeObservation,
    RetrievalRequest,
    RetrievalResult,
    SimilarityProfile,
)
from ruler.cbr.registry import FeatureRegistry
from ruler.cbr.retrieval import CaseRetriever, compare_cases
from ruler.cbr.store import DecisionPacketStore, OutcomeStore
from ruler.evaluation.contracts import CounterfactualResult, EvaluationPacket, ExpectedRule
from ruler.evaluation.pipeline import EvaluationPipeline


class CBRService:
    """Unified in-process facade that preserves strict core contracts."""

    def __init__(
        self,
        *,
        registry: FeatureRegistry,
        profile: SimilarityProfile,
        cases: tuple[CBRCaseRecord, ...],
        decision_store: DecisionPacketStore | None = None,
        outcome_store: OutcomeStore | None = None,
        evaluation_pipeline: EvaluationPipeline | None = None,
    ) -> None:
        self.registry = registry
        self.profile = profile
        self.cases = {case.case_id: case for case in cases}
        if len(self.cases) != len(cases):
            raise ValueError("case library has duplicate IDs")
        for case in cases:
            registry.validate_case(case)
        self.retriever = CaseRetriever(registry, profile)
        self.decision_store = decision_store
        self.outcome_store = outcome_store
        self.evaluation_pipeline = evaluation_pipeline

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        return self.retriever.retrieve(request, tuple(self.cases.values()))

    def compare(self, left_case_id: str, right_case_id: str):
        return compare_cases(
            self.cases[left_case_id], self.cases[right_case_id], self.registry, self.profile
        )

    def adapt(
        self, plan: AdaptationPlan, query: CBRCaseRecord, source_case_id: str
    ) -> CBRCaseRecord:
        return apply_adaptation(plan, query, self.cases[source_case_id], self.registry)

    def verify(
        self,
        plan: AdaptationPlan,
        query: CBRCaseRecord,
        source_case_id: str,
        *,
        expected_rules: tuple[ExpectedRule, ...],
        fact_builder: FactBuilder,
    ) -> tuple[EvaluationPacket, tuple[CounterfactualResult, ...]]:
        if self.evaluation_pipeline is None:
            raise ValueError("formal verification is not configured")
        return verify_adaptation(
            self.evaluation_pipeline,
            plan,
            query,
            self.cases[source_case_id],
            self.registry,
            expected_rules=expected_rules,
            fact_builder=fact_builder,
        )

    def retain(self, outcome: OutcomeObservation) -> str:
        if self.outcome_store is None:
            raise ValueError("outcome retention is not configured")
        return self.outcome_store.retain(outcome)
