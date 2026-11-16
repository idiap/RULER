# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import json

import pytest

from ruler.cbr.contracts import RetrievalRequest
from ruler.cbr.registry import FeatureRegistry
from ruler.cbr.retrieval import CaseRetriever
from ruler.domains.base import validate_domain_pack
from ruler.domains.cbr_catalog import (
    available_cbr_demos,
    evaluate_cbr_demo,
    load_all_cbr_demos,
    load_cbr_demo,
)
from ruler.domains.fiscal import FISCAL_DOMAIN_PACK
from ruler.domains.regulatory.cbr import (
    REGULATORY_CBR_DOMAIN_PACK,
    REGULATORY_CBR_PREDICATES,
)
from ruler.domains.spending import SPENDING_DOMAIN_PACK
from ruler.domains.technical_support import TECHNICAL_SUPPORT_DOMAIN_PACK
from ruler.domains.trade import TRADE_DOMAIN_PACK
from ruler.kb.corpus_manifest import (
    discover_corpus_manifests,
    load_corpus_manifest,
    validate_corpus_manifest,
)

PACKS = (
    SPENDING_DOMAIN_PACK,
    FISCAL_DOMAIN_PACK,
    TRADE_DOMAIN_PACK,
    TECHNICAL_SUPPORT_DOMAIN_PACK,
)


def test_new_domain_packs_are_valid_and_safety_vocabulary_is_explicit() -> None:
    for pack in PACKS:
        validate_domain_pack(pack)
    validate_domain_pack(REGULATORY_CBR_DOMAIN_PACK)
    assert SPENDING_DOMAIN_PACK.predicates["purchase_releasable"].role == "effect"
    assert FISCAL_DOMAIN_PACK.predicates["input_tax_status"].description.startswith(
        "Evidence-dependent"
    )
    assert TRADE_DOMAIN_PACK.predicates["screening_freshness"].role == "condition"
    assert TECHNICAL_SUPPORT_DOMAIN_PACK.predicates["safety_interlock"].role == "constraint"
    assert {"applicable_on", "oversight_assigned", "deployment_permitted"} <= set(
        REGULATORY_CBR_PREDICATES
    )


def test_all_five_libraries_are_strict_reviewed_and_release_pinned() -> None:
    demos = load_all_cbr_demos()
    assert tuple(item.domain_id for item in demos) == (
        "fiscal",
        "regulatory",
        "spending",
        "technical_support",
        "trade",
    )
    assert available_cbr_demos() == tuple(item.domain_id for item in demos)
    for demo in demos:
        assert len(demo.library.cases) == 6
        assert all(case.review_state.value == "reviewed" for case in demo.library.cases)
        assert all(case.disposition is not None for case in demo.library.cases)
        assert all(case.evidence_digests for case in demo.library.cases)
        assert demo.query.review_state.value == "draft"
        assert demo.query.case_library_release_id == demo.library.release_id
        assert all(
            case.rule_release_sha256 == demo.query.rule_release_sha256
            for case in demo.library.cases
        )
        incomplete = [case for case in demo.library.cases if case.observed_outcome_id is None]
        assert len(incomplete) == 1
        assert any(feature.missingness.value == "unknown" for feature in incomplete[0].features)


def test_every_demo_has_exact_golden_order_and_mandatory_excluded_contrast() -> None:
    for demo in load_all_cbr_demos():
        registry = FeatureRegistry(domain_id=demo.domain_id, definitions=demo.feature_definitions)
        request = RetrievalRequest(
            request_id=f"golden-{demo.domain_id}",
            query_case=demo.query,
            case_library_release_id=demo.query.case_library_release_id,
            case_library_release_sha256=demo.query.case_library_release_sha256,
            similarity_profile_sha256=demo.similarity_profile.sha256(),
            rule_release_id=demo.query.rule_release_id,
            rule_release_sha256=demo.query.rule_release_sha256,
            top_k=3,
        )
        first = CaseRetriever(registry, demo.similarity_profile).retrieve(
            request, demo.library.cases
        )
        replay = CaseRetriever(registry, demo.similarity_profile).retrieve(
            request, tuple(reversed(demo.library.cases))
        )
        actual = tuple(item.case_id for item in first.retrieved)
        assert actual == demo.expected.retrieval_order
        assert tuple(item.case_id for item in replay.retrieved) == actual
        assert first.excluded_contrast is not None
        assert first.excluded_contrast.case_id == demo.expected.excluded_case_id
        assert first.excluded_contrast.mismatched_hard_filters


def test_domain_evaluators_do_not_copy_positive_precedent_outcomes() -> None:
    spending = evaluate_cbr_demo("spending")
    assert spending.status == "blocked"
    assert spending.action == "hold_order"
    assert set(spending.blockers) == {
        "two_additional_comparable_quotes_or_approved_waiver",
        "finance_approval",
    }

    regulatory = evaluate_cbr_demo("regulatory")
    assert regulatory.status == "blocked"
    assert "competent_human_oversight_assignment" in regulatory.blockers

    fiscal = evaluate_cbr_demo("fiscal")
    assert fiscal.status == "unknown"
    assert fiscal.unknowns == ("input_tax_eligibility_without_business_purpose_evidence",)

    trade = evaluate_cbr_demo("trade")
    assert trade.status == "unknown"
    assert {"technical_classification", "current_sanctions_screen", "licence_determination"} <= set(
        trade.unknowns
    )
    assert trade.action.startswith("stop_shipment")

    support = evaluate_cbr_demo("technical_support")
    assert support.status == "blocked_pending_service"
    assert support.action == "keep_interlock_and_dispatch_authorized_technician"
    assert support.blockers == ()


def test_unknown_is_not_coerced_to_false() -> None:
    trade = load_cbr_demo("trade").query.feature_map()
    assert trade["classification_state"].value is None
    assert trade["classification_state"].missingness.value == "unknown"
    assert trade["end_user_known"].value is not None
    assert trade["end_user_known"].value.value is False
    assert trade["end_user_known"].missingness.value == "observed"


def test_all_ten_cbr_corpora_are_hash_bound_and_source_metadata_is_honest() -> None:
    paths = [path for path in discover_corpus_manifests() if path.parent.name.startswith("cbr-")]
    assert len(paths) == 10
    for path in paths:
        validate_corpus_manifest(load_corpus_manifest(path))

    metadata_paths = [
        "kb/corpora/cbr-regulatory-rules/source/eur_lex_source_metadata.json",
        "kb/corpora/cbr-fiscal-rules/source/swiss_fta_source_metadata.json",
        "kb/corpora/cbr-trade-rules/source/seco_source_metadata.json",
    ]
    for relative in metadata_paths:
        payload = json.loads((paths[0].parents[3] / relative).read_text(encoding="utf-8"))
        assert payload["canonical_url"].startswith("https://")
        assert payload["metadata_checked_at"] == "2026-08-30T00:00:00Z"
        assert "claim_boundary" in payload
        assert (
            "official_text" in payload["snapshot_status"]
            or "reviewed_tabular_demo" in payload["snapshot_status"]
        )


def test_unknown_demo_is_uniform() -> None:
    with pytest.raises(LookupError, match="unknown CBR demonstration"):
        load_cbr_demo("not-a-domain")
