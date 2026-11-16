# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Safety and determinism tests for the neutral CBR kernel."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError

from ruler.cbr.adaptation import apply_adaptation, verify_adaptation
from ruler.cbr.contracts import (
    AdaptationOperation,
    AdaptationPlan,
    CBRCaseRecord,
    CBRDecisionPacket,
    CaseDisposition,
    CaseLibraryDependency,
    CaseLibraryManifest,
    CaseFeature,
    ComparisonPolicy,
    DiversityPolicy,
    FeatureDefinition,
    FeatureWeight,
    HardFilter,
    Missingness,
    OutcomeObservation,
    RetrievalRequest,
    ReviewState,
    SimilarityProfile,
)
from ruler.cbr.registry import FeatureRegistry
from ruler.cbr.retrieval import CaseRetriever, compare_features
from ruler.cbr.store import DecisionPacketStore, OutcomeStore, assess_release_drift
from ruler.contracts.common import TypedValue
from ruler.domains.regulatory import (
    REGULATORY_RELEASE_ID,
    build_regulatory_program,
    regulatory_expected_rules,
    regulatory_registry,
)
from ruler.evaluation import EvaluationPipeline, EvaluationStatus
from ruler.kb.formalization import ValueType
from ruler.kb.logical_ir import Atom, Constant

DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _feature(
    feature_id: str,
    value: object | None,
    policy: ComparisonPolicy = ComparisonPolicy.CATEGORICAL,
    *,
    missingness: Missingness = Missingness.OBSERVED,
    value_type: str = "string",
) -> CaseFeature:
    return CaseFeature(
        feature_id=feature_id,
        value=(
            TypedValue(value_type=value_type, value=value)
            if missingness == Missingness.OBSERVED
            else None
        ),
        observed_at=NOW if missingness == Missingness.OBSERVED else None,
        source_ref="evidence:1" if missingness == Missingness.OBSERVED else None,
        confidence=1 if missingness == Missingness.OBSERVED else None,
        missingness=missingness,
        comparison_policy=policy,
    )


def _case(
    case_id: str,
    *features: CaseFeature,
    jurisdiction: str = "CH",
    rule_digest: str = DIGEST_A,
    as_of: date = date(2026, 8, 1),
) -> CBRCaseRecord:
    return CBRCaseRecord(
        case_id=case_id,
        case_kind="purchase",
        domain_id="spending",
        schema_version="1",
        opened_at=NOW,
        as_of_date=as_of,
        jurisdictions=(jurisdiction,),
        rule_release_id="rules-1",
        rule_release_sha256=rule_digest,
        case_library_release_id="cases-1",
        case_library_release_sha256=DIGEST_B,
        subject_ref=f"subject:{case_id}",
        features=features,
        requested_action="buy",
        retention_policy_id="internal-7y",
    )


def _registry() -> FeatureRegistry:
    return FeatureRegistry(
        domain_id="spending",
        definitions=(
            FeatureDefinition(
                feature_id="kind",
                value_type="string",
                comparison_policy="categorical",
                diversity_key=True,
            ),
            FeatureDefinition(
                feature_id="amount",
                value_type="money",
                comparison_policy="numeric_range",
                numeric_range=(0, 100_000),
                missing_behavior="penalize",
            ),
        ),
    )


def _profile() -> SimilarityProfile:
    return SimilarityProfile(
        profile_id="spending-purchase",
        version="1",
        domain_id="spending",
        case_kind="purchase",
        feature_weights=(
            FeatureWeight(feature_id="kind", weight=0.4),
            FeatureWeight(feature_id="amount", weight=0.6),
        ),
        hard_filters=(
            HardFilter(filter_id="kind", kind="case_kind"),
            HardFilter(filter_id="domain", kind="domain"),
            HardFilter(filter_id="jurisdiction", kind="jurisdiction"),
            HardFilter(filter_id="temporal", kind="temporal"),
        ),
        missing_penalty=0.25,
        diversity=DiversityPolicy(feature_id="kind", max_per_value=1),
    )


def _request(query: CBRCaseRecord, profile: SimilarityProfile, top_k: int = 3) -> RetrievalRequest:
    return RetrievalRequest(
        request_id="retrieve-1",
        query_case=query,
        case_library_release_id="cases-1",
        case_library_release_sha256=DIGEST_B,
        similarity_profile_sha256=profile.sha256(),
        rule_release_id="rules-1",
        rule_release_sha256=DIGEST_A,
        top_k=top_k,
        authorized_fields=frozenset({"kind", "amount"}),
    )


def test_missing_states_are_distinct_strict_and_round_trip() -> None:
    values = [
        _feature("x", None, missingness=state)
        for state in (Missingness.UNKNOWN, Missingness.NOT_APPLICABLE, Missingness.REDACTED)
    ]
    assert [
        CaseFeature.model_validate_json(item.model_dump_json()).missingness for item in values
    ] == [
        Missingness.UNKNOWN,
        Missingness.NOT_APPLICABLE,
        Missingness.REDACTED,
    ]
    with pytest.raises(ValidationError):
        CaseFeature.model_validate({**values[0].model_dump(), "unexpected": True})
    with pytest.raises(ValidationError, match="cannot carry values"):
        CaseFeature(
            feature_id="x",
            value=TypedValue(value_type="boolean", value=False),
            missingness="unknown",
            comparison_policy="categorical",
        )


def test_registry_rejects_undeclared_and_wrongly_typed_features() -> None:
    registry = _registry()
    with pytest.raises(ValueError, match="undeclared"):
        registry.validate_case(_case("x", _feature("secret", "x")))
    with pytest.raises(ValueError, match="expected value type money"):
        registry.validate_case(_case("x", _feature("amount", 10, ComparisonPolicy.NUMERIC_RANGE)))


def test_case_library_manifest_is_content_addressed_and_dependency_pinned() -> None:
    case = _case("c", _feature("kind", "compute")).model_copy(
        update={
            "review_state": ReviewState.REVIEWED,
            "disposition": CaseDisposition(
                disposition_id="d1",
                decision="held",
                actor_role="reviewer",
                decided_at=NOW,
                rule_release_id="rules-1",
                rule_release_sha256=DIGEST_A,
            ),
        }
    )
    manifest = CaseLibraryManifest(
        library_id="spending-cases",
        release_id="cases-1",
        cases=(case,),
        dependencies=(
            CaseLibraryDependency(rule_release_id="rules-1", rule_release_sha256=DIGEST_A),
        ),
        profile_sha256=DIGEST_B,
        created_at=NOW,
    )
    assert (
        manifest.sha256()
        == CaseLibraryManifest.model_validate_json(manifest.model_dump_json()).sha256()
    )
    with pytest.raises(ValidationError, match="no pinned rule dependency"):
        CaseLibraryManifest(
            library_id="spending-cases",
            release_id="cases-1",
            cases=(case,),
            dependencies=(
                CaseLibraryDependency(rule_release_id="rules-other", rule_release_sha256=DIGEST_A),
            ),
            profile_sha256=DIGEST_B,
            created_at=NOW,
        )


def test_all_comparators_are_typed_and_explained() -> None:
    samples = (
        (ComparisonPolicy.CATEGORICAL, "a", "a", {}),
        (ComparisonPolicy.ORDINAL, "low", "high", {"ordinal_values": ("low", "medium", "high")}),
        (ComparisonPolicy.NUMERIC_RANGE, 10, 20, {"numeric_range": (0, 100)}),
        (ComparisonPolicy.SET, ["a", "b"], ["b", "c"], {}),
        (ComparisonPolicy.TEMPORAL, "2026-01-01", "2026-02-01", {}),
        (
            ComparisonPolicy.TAXONOMY,
            "gpu",
            "cpu",
            {"taxonomy_parents": {"gpu": "compute", "cpu": "compute", "compute": None}},
        ),
        (ComparisonPolicy.VERSION, "5.5.1", "5.4.2", {}),
    )
    for policy, left, right, kwargs in samples:
        definition = FeatureDefinition(
            feature_id="f", value_type="string", comparison_policy=policy, **kwargs
        )
        score, explanation = compare_features(
            _feature("f", left, policy), _feature("f", right, policy), definition
        )
        assert 0 <= score <= 1
        assert policy.value in explanation


def test_retrieval_is_stable_diverse_and_includes_unscored_contrast() -> None:
    registry, profile = _registry(), _profile()
    query = _case(
        "query",
        _feature("kind", "compute"),
        _feature("amount", 71_800, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    same_a = _case(
        "a",
        _feature("kind", "compute"),
        _feature("amount", 70_000, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    same_b = _case(
        "b",
        _feature("kind", "compute"),
        _feature("amount", 71_000, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    other = _case(
        "c",
        _feature("kind", "microscope"),
        _feature("amount", 72_000, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    foreign = _case(
        "tempting",
        _feature("kind", "compute"),
        _feature("amount", 71_800, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
        jurisdiction="US",
    )
    result = CaseRetriever(registry, profile).retrieve(
        _request(query, profile), (foreign, other, same_b, same_a)
    )
    assert [item.case_id for item in result.retrieved] == ["b", "c"]
    assert [item.rank for item in result.retrieved] == [1, 2]
    assert result.excluded_contrast is not None
    assert result.excluded_contrast.case_id == "tempting"
    assert result.excluded_contrast.score == 0
    assert result.excluded_contrast.mismatched_hard_filters[0].code == "jurisdiction_mismatch"


def test_future_cases_and_access_incompatible_cases_never_score() -> None:
    profile = _profile().model_copy(
        update={
            "hard_filters": _profile().hard_filters
            + (HardFilter(filter_id="access", kind="access"),)
        }
    )
    query = _case(
        "query",
        _feature("kind", "compute"),
        _feature("amount", 10, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    future = _case(
        "future",
        _feature("kind", "compute"),
        _feature("amount", 10, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
        as_of=date(2027, 1, 1),
    )
    request = _request(query, profile).model_copy(update={"authorized_fields": frozenset({"kind"})})
    result = CaseRetriever(_registry(), profile).retrieve(request, (future,))
    assert not result.retrieved
    assert result.excluded_contrast and result.excluded_contrast.score == 0
    assert {reason.code for reason in result.excluded_contrast.mismatched_hard_filters} == {
        "future_or_stale_case",
        "field_access_denied",
    }


def test_adaptation_is_typed_and_cannot_copy_approval_or_disposition() -> None:
    registry = _registry()
    query = _case(
        "query",
        _feature("kind", "compute"),
        _feature("amount", 10, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    source = _case(
        "source",
        _feature("kind", "microscope"),
        _feature("amount", 20, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    replacement = _feature("amount", 15, ComparisonPolicy.NUMERIC_RANGE, value_type="money")
    plan = AdaptationPlan(
        plan_id="p1",
        query_case_id="query",
        source_case_id="source",
        rule_release_id="rules-1",
        rule_release_sha256=DIGEST_A,
        operations=(
            AdaptationOperation(
                operation="replace",
                source_case_id="source",
                target_field="features.amount",
                value=replacement,
                justification_code="threshold_alignment",
            ),
        ),
    )
    adapted = apply_adaptation(plan, query, source, registry)
    assert adapted.feature_map()["amount"].value.value == 15
    forbidden = plan.model_copy(
        update={
            "operations": (
                AdaptationOperation(
                    operation="retain",
                    source_case_id="source",
                    target_field="disposition",
                    value="approved",
                    justification_code="copy",
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="cannot be adapted"):
        apply_adaptation(forbidden, query, source, registry)


def test_adaptation_bridge_uses_current_rule_pipeline_and_preserves_unknown() -> None:
    registry = _registry()
    query = _case(
        "query",
        _feature("kind", "compute"),
        _feature("amount", 10, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    source = _case(
        "source",
        _feature("kind", "compute"),
        _feature("amount", 20, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    plan = AdaptationPlan(
        plan_id="p1",
        query_case_id="query",
        source_case_id="source",
        rule_release_id=REGULATORY_RELEASE_ID,
        rule_release_sha256=DIGEST_A,
        operations=(
            AdaptationOperation(
                operation="retain",
                source_case_id="source",
                target_field="features.kind",
                value=query.feature_map()["kind"],
                justification_code="same_kind",
            ),
        ),
    )
    query = query.model_copy(update={"rule_release_id": REGULATORY_RELEASE_ID})

    def facts(_: CBRCaseRecord) -> tuple[Atom, ...]:
        return (
            Atom(
                predicate="in_scope",
                arguments=(Constant(value_type=ValueType.SUBJECT, value="operator"),),
            ),
        )

    packet, counterfactuals = verify_adaptation(
        EvaluationPipeline(build_regulatory_program(), regulatory_registry()),
        plan,
        query,
        source.model_copy(update={"rule_release_id": REGULATORY_RELEASE_ID}),
        registry,
        expected_rules=regulatory_expected_rules(),
        fact_builder=facts,
    )
    assert packet.release_id == REGULATORY_RELEASE_ID
    assert set(item.status for item in packet.consequences) == {EvaluationStatus.UNKNOWN}
    assert len(counterfactuals) == 1


def test_outcomes_are_immutable_independently_reviewed_and_superseded(tmp_path) -> None:
    store = OutcomeStore(tmp_path)
    original = OutcomeObservation(
        outcome_id="o1",
        case_id="c1",
        observed_at=NOW,
        source_ref="ticket:1",
        reviewer_id="human-reviewer",
        original_proposer_id="automation",
        status="success",
        causal_claim_boundary="Temporal association only; no causal inference.",
        visibility="internal",
        retention_policy_id="7y",
    )
    store.retain(original)
    with pytest.raises(ValueError, match="immutable"):
        store.retain(original)
    correction = original.model_copy(
        update={
            "outcome_id": "o2",
            "observed_at": NOW + timedelta(days=1),
            "status": "partial_success",
            "supersedes_outcome_id": "o1",
        }
    )
    store.supersede(correction)
    assert store.get("o1").status == "success"
    assert [item.outcome_id for item in store.list_for_case("c1")] == ["o1", "o2"]
    with pytest.raises(ValidationError, match="independent"):
        original.model_copy(
            update={"outcome_id": "bad", "reviewer_id": "automation"}, deep=True
        ).__class__.model_validate(
            {**original.model_dump(), "outcome_id": "bad", "reviewer_id": "automation"}
        )


def test_decision_packets_are_content_addressed_and_release_drift_is_explicit(tmp_path) -> None:
    query = _case(
        "query",
        _feature("kind", "compute"),
        _feature("amount", 10, ComparisonPolicy.NUMERIC_RANGE, value_type="money"),
    )
    profile = _profile()
    retrieval = CaseRetriever(_registry(), profile).retrieve(_request(query, profile), ())
    plan = AdaptationPlan(
        plan_id="p",
        query_case_id="query",
        source_case_id="none",
        rule_release_id=REGULATORY_RELEASE_ID,
        rule_release_sha256=DIGEST_A,
        operations=(),
    )
    pipeline = EvaluationPipeline(build_regulatory_program(), regulatory_registry())
    evaluation = pipeline.evaluate(
        __import__("ruler.evaluation.contracts", fromlist=["EvaluationRequest"]).EvaluationRequest(
            request_id="e",
            case_id="query",
            release_id=REGULATORY_RELEASE_ID,
            facts=(),
            expected_rules=regulatory_expected_rules(),
        )
    )
    packet = CBRDecisionPacket(
        packet_id="packet",
        query_case_id="query",
        case_library_release_id="cases-1",
        case_library_release_sha256=DIGEST_B,
        rule_release_id=REGULATORY_RELEASE_ID,
        rule_release_sha256=DIGEST_A,
        retrieval=retrieval,
        adaptation=plan,
        evaluation=evaluation,
        unknowns=("approval_missing",),
        trace=("artifact:query",),
    )
    store = DecisionPacketStore(tmp_path)
    digest = store.put(packet)
    assert store.get(digest) == packet
    assert (
        assess_release_drift(
            query, current_release_id="rules-2", current_release_sha256=DIGEST_B
        ).status
        == "requires_reevaluation"
    )
    assert (
        assess_release_drift(
            query, current_release_id="rules-1", current_release_sha256=DIGEST_A
        ).status
        == "current"
    )
