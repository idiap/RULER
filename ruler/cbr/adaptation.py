# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Typed precedent adaptation and the current-rule verification boundary."""

from __future__ import annotations

from collections.abc import Callable

from ruler.cbr.contracts import (
    AdaptationPlan,
    CBRCaseRecord,
    CaseFeature,
)
from ruler.cbr.registry import FeatureRegistry
from ruler.evaluation.contracts import (
    CounterfactualResult,
    EvaluationPacket,
    EvaluationRequest,
    ExpectedRule,
)
from ruler.evaluation.pipeline import EvaluationPipeline
from ruler.kb.logical_ir import Atom

FactBuilder = Callable[[CBRCaseRecord], tuple[Atom, ...]]

_PROHIBITED_TARGETS = {
    "disposition",
    "observed_outcome_id",
    "review_state",
    "rule_release_id",
    "rule_release_sha256",
    "case_library_release_id",
    "case_library_release_sha256",
}


def validate_adaptation(
    plan: AdaptationPlan,
    query: CBRCaseRecord,
    source: CBRCaseRecord,
    registry: FeatureRegistry,
) -> None:
    """Reject adaptations that copy conclusions, approvals, or incompatible feature types."""
    registry.validate_case(query)
    registry.validate_case(source)
    if plan.query_case_id != query.case_id or plan.source_case_id != source.case_id:
        raise ValueError("adaptation identities do not match the supplied cases")
    if plan.rule_release_sha256 != query.rule_release_sha256:
        raise ValueError("adaptation must be verified against the query's current rule release")
    touched: set[str] = set()
    for operation in plan.operations:
        if operation.source_case_id != source.case_id:
            raise ValueError("every operation must identify the selected source case")
        root = operation.target_field.split(".", 1)[0]
        if root in _PROHIBITED_TARGETS or "approval" in operation.target_field.lower():
            raise ValueError(
                f"precedent conclusions and approvals cannot be adapted: {operation.target_field}"
            )
        if operation.target_field in touched:
            raise ValueError(f"target field adapted more than once: {operation.target_field}")
        touched.add(operation.target_field)
        if root == "features":
            parts = operation.target_field.split(".")
            if len(parts) != 2:
                raise ValueError("feature targets must use features.<feature_id>")
            definition = registry.require(parts[1])
            if isinstance(operation.value, CaseFeature):
                if operation.value.feature_id != parts[1]:
                    raise ValueError("adapted feature ID must match its target")
                if (
                    operation.value.value
                    and operation.value.value.value_type != definition.value_type
                ):
                    raise ValueError("adapted feature type differs from the registry")
            elif operation.operation in {"add", "replace", "retain"}:
                raise ValueError("feature operations require a CaseFeature value")
        elif operation.target_field != "requested_action":
            raise ValueError(f"unsupported adaptation target: {operation.target_field}")


def apply_adaptation(
    plan: AdaptationPlan,
    query: CBRCaseRecord,
    source: CBRCaseRecord,
    registry: FeatureRegistry,
) -> CBRCaseRecord:
    validate_adaptation(plan, query, source, registry)
    features = query.feature_map()
    requested_action = query.requested_action
    for operation in plan.operations:
        if operation.target_field.startswith("features."):
            feature_id = operation.target_field.split(".", 1)[1]
            if operation.operation == "remove":
                if feature_id not in features:
                    raise ValueError(f"cannot remove absent feature: {feature_id}")
                del features[feature_id]
            elif operation.operation == "retain":
                if feature_id not in features:
                    raise ValueError(f"cannot retain absent feature: {feature_id}")
            else:
                assert isinstance(operation.value, CaseFeature)
                if operation.operation == "add" and feature_id in features:
                    raise ValueError(f"cannot add existing feature: {feature_id}")
                if operation.operation == "replace" and feature_id not in features:
                    raise ValueError(f"cannot replace absent feature: {feature_id}")
                features[feature_id] = operation.value
        elif operation.target_field == "requested_action":
            if operation.operation == "remove":
                raise ValueError("requested_action cannot be removed")
            if operation.operation != "retain":
                assert isinstance(operation.value, str)
                requested_action = operation.value
    return query.model_copy(
        update={
            "features": tuple(features[key] for key in sorted(features)),
            "requested_action": requested_action,
        }
    )


def build_evaluation_request(
    plan: AdaptationPlan,
    query: CBRCaseRecord,
    source: CBRCaseRecord,
    registry: FeatureRegistry,
    *,
    expected_rules: tuple[ExpectedRule, ...],
    fact_builder: FactBuilder,
) -> EvaluationRequest:
    adapted = apply_adaptation(plan, query, source, registry)
    return EvaluationRequest(
        request_id=f"{plan.plan_id}:verification",
        case_id=query.case_id,
        release_id=plan.rule_release_id,
        facts=fact_builder(adapted),
        expected_rules=expected_rules,
    )


def verify_adaptation(
    pipeline: EvaluationPipeline,
    plan: AdaptationPlan,
    query: CBRCaseRecord,
    source: CBRCaseRecord,
    registry: FeatureRegistry,
    *,
    expected_rules: tuple[ExpectedRule, ...],
    fact_builder: FactBuilder,
) -> tuple[EvaluationPacket, tuple[CounterfactualResult, ...]]:
    """Evaluate the adapted case and compare it with the unadapted query under current rules."""
    request = build_evaluation_request(
        plan, query, source, registry, expected_rules=expected_rules, fact_builder=fact_builder
    )
    packet = pipeline.evaluate(request)
    counterfactual = pipeline.counterfactual(
        request,
        probe_id=f"{plan.plan_id}:unadapted",
        facts=fact_builder(query),
    )
    return packet, (counterfactual,)


def requires_human_gate(plan: AdaptationPlan) -> bool:
    """All action/evidence adaptations remain review-gated; this function is explicit for callers."""
    return bool(plan.operations or plan.evidence_requirements or plan.proposed_action)
