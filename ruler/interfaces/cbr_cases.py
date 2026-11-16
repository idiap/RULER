# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Unified application facade for the five governed CBR demonstrations."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from ruler.cbr.contracts import (
    AdaptationOperation,
    AdaptationPlan,
    CBRCaseRecord,
    OutcomeObservation,
    RetrievalRequest,
)
from ruler.cbr.registry import FeatureRegistry
from ruler.cbr.service import CBRService
from ruler.cbr.store import OutcomeStore, assess_release_drift
from ruler.domains.cbr_catalog import (
    DomainCBRDemo,
    load_all_cbr_demos,
    load_cbr_demo,
)


def cbr_service(
    domain_id: str, *, outcome_root: Path | None = None
) -> tuple[DomainCBRDemo, CBRService]:
    demo = load_cbr_demo(domain_id)
    service = CBRService(
        registry=FeatureRegistry(domain_id=domain_id, definitions=demo.feature_definitions),
        profile=demo.similarity_profile,
        cases=demo.library.cases,
        outcome_store=OutcomeStore(outcome_root) if outcome_root is not None else None,
    )
    return demo, service


def cbr_portfolio() -> dict[str, Any]:
    demos = load_all_cbr_demos()
    return {
        "schema_version": "ruler-cbr-portfolio/1",
        "count": len(demos),
        "domains": [
            {
                "domain_id": demo.domain_id,
                "case_kind": demo.query.case_kind,
                "query_case_id": demo.query.case_id,
                "library_id": demo.library.library_id,
                "library_release_id": demo.library.release_id,
                "library_case_count": len(demo.library.cases),
                "rule_release_id": demo.query.rule_release_id,
                "profile_id": demo.similarity_profile.profile_id,
                "claim_boundary": demo.claim_boundary,
            }
            for demo in demos
        ],
    }


def case_view(case: CBRCaseRecord, *, include_sensitive: bool = False) -> dict[str, Any]:
    payload = case.model_dump(mode="json")
    payload.pop("party_refs", None)
    if not include_sensitive:
        payload["subject_ref"] = "[redacted]"
        for feature in payload["features"]:
            feature.pop("source_ref", None)
        payload["source_refs"] = ["[redacted]"] if payload.get("source_refs") else []
        payload["evidence_digests"] = []
    return payload


def show_cbr_case(
    domain_id: str, case_id: str, *, include_sensitive: bool = False
) -> dict[str, Any]:
    demo = load_cbr_demo(domain_id)
    cases = {demo.query.case_id: demo.query, **{case.case_id: case for case in demo.library.cases}}
    try:
        case = cases[case_id]
    except KeyError as exc:
        raise LookupError("case is unavailable") from exc
    return case_view(case, include_sensitive=include_sensitive)


def build_retrieval_request(
    demo: DomainCBRDemo,
    *,
    query: CBRCaseRecord | None = None,
    top_k: int = 3,
    authorized_fields: frozenset[str] | None = None,
) -> RetrievalRequest:
    selected = query or demo.query
    return RetrievalRequest(
        request_id=f"retrieve-{secrets.token_hex(8)}",
        query_case=selected,
        case_library_release_id=demo.library.release_id,
        case_library_release_sha256=selected.case_library_release_sha256,
        similarity_profile_sha256=demo.similarity_profile.sha256(),
        rule_release_id=selected.rule_release_id,
        rule_release_sha256=selected.rule_release_sha256,
        top_k=top_k,
        authorized_fields=(
            authorized_fields
            if authorized_fields is not None
            else frozenset(item.feature_id for item in demo.feature_definitions)
        ),
        maximum_candidates=demo.similarity_profile.maximum_candidate_pool,
    )


def retrieve_cbr_cases(
    domain_id: str,
    *,
    query: CBRCaseRecord | None = None,
    top_k: int = 3,
    include_sensitive: bool = False,
) -> dict[str, Any]:
    demo, service = cbr_service(domain_id)
    request = build_retrieval_request(demo, query=query, top_k=top_k)
    result = service.retrieve(request)
    cases = {case.case_id: case for case in demo.library.cases}
    return {
        "domain_id": domain_id,
        "query_case_id": request.query_case.case_id,
        "case_library_release_id": request.case_library_release_id,
        "rule_release_id": request.rule_release_id,
        "result": result.model_dump(mode="json"),
        "cases": {
            item.case_id: case_view(cases[item.case_id], include_sensitive=include_sensitive)
            for item in result.retrieved
        },
        "claim_boundary": demo.claim_boundary,
    }


def compare_cbr_cases(domain_id: str, left_case_id: str, right_case_id: str) -> dict[str, Any]:
    demo, service = cbr_service(domain_id)
    known = {case.case_id for case in demo.library.cases}
    if left_case_id not in known or right_case_id not in known:
        raise LookupError("case is unavailable")
    return {
        "domain_id": domain_id,
        "left_case_id": left_case_id,
        "right_case_id": right_case_id,
        "contributions": [
            item.model_dump(mode="json") for item in service.compare(left_case_id, right_case_id)
        ],
        "claim_boundary": "Comparison explains similarity only; it establishes no current-rule conclusion.",
    }


def suggest_cbr_adaptation(domain_id: str, source_case_id: str) -> dict[str, Any]:
    demo, service = cbr_service(domain_id)
    try:
        source = service.cases[source_case_id]
    except KeyError as exc:
        raise LookupError("case is unavailable") from exc
    query_features = demo.query.feature_map()
    source_features = source.feature_map()
    operations = []
    for feature_id, query_feature in sorted(query_features.items()):
        # Approval and disposition fields are current-rule conclusions, never
        # transferable precedent facts. They remain inputs to verification.
        if "approval" in feature_id.lower():
            continue
        source_feature = source_features.get(feature_id)
        if source_feature != query_feature:
            operations.append(
                AdaptationOperation(
                    operation="retain",
                    source_case_id=source.case_id,
                    target_field=f"features.{feature_id}",
                    value=query_feature,
                    justification_code="preserve_current_case_fact_not_precedent_value",
                )
            )
    plan = AdaptationPlan(
        plan_id=f"adapt-{demo.query.case_id}-{source.case_id}",
        query_case_id=demo.query.case_id,
        source_case_id=source.case_id,
        rule_release_id=demo.query.rule_release_id,
        rule_release_sha256=demo.query.rule_release_sha256,
        operations=tuple(operations),
        evidence_requirements=demo.expected.adaptation_operations,
        proposed_action=demo.expected.rule_outcome,
    )
    adapted = service.adapt(plan, demo.query, source.case_id)
    return {
        "domain_id": domain_id,
        "plan": plan.model_dump(mode="json"),
        "adapted_case": case_view(adapted),
        "human_review_required": True,
        "claim_boundary": "The plan preserves current facts and proposes evidence work; it does not copy the precedent disposition.",
    }


def verify_cbr_demo(domain_id: str) -> dict[str, Any]:
    from ruler.domains.cbr_catalog import evaluate_cbr_demo

    evaluation = evaluate_cbr_demo(domain_id)
    return evaluation.model_dump(mode="json")


def release_drift_for_case(domain_id: str, case_id: str) -> dict[str, Any]:
    demo = load_cbr_demo(domain_id)
    case = next((item for item in demo.library.cases if item.case_id == case_id), None)
    if case is None:
        raise LookupError("case is unavailable")
    return assess_release_drift(
        case,
        current_release_id=demo.query.rule_release_id,
        current_release_sha256=demo.query.rule_release_sha256,
    ).model_dump(mode="json")


def retain_cbr_outcome(outcome: OutcomeObservation, *, root: Path) -> str:
    return OutcomeStore(root).retain(outcome)


__all__ = [
    "build_retrieval_request",
    "case_view",
    "cbr_portfolio",
    "cbr_service",
    "compare_cbr_cases",
    "release_drift_for_case",
    "retain_cbr_outcome",
    "retrieve_cbr_cases",
    "show_cbr_case",
    "suggest_cbr_adaptation",
    "verify_cbr_demo",
]
