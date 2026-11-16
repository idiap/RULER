# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic loader for the five realistic CBR domain demonstrations.

The compact JSON source is converted immediately into frozen CBR contracts.  It is
not an alternative permissive representation: undeclared features, malformed
release pins, future precedents, and incomplete expectations fail at load time.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from pydantic import Field, model_validator

from ruler.cbr.contracts import (
    CBRCaseRecord,
    CaseDisposition,
    CaseFeature,
    CaseLibraryDependency,
    CaseLibraryManifest,
    ComparisonPolicy,
    FeatureDefinition,
    FeatureWeight,
    HardFilter,
    SimilarityProfile,
)
from ruler.contracts.common import StrictContract, TypedValue
from ruler.paths import REPO_ROOT

DATA_PATH = REPO_ROOT / "data" / "cbr" / "demonstrations.json"


class ExpectedJourney(StrictContract):
    retrieval_order: tuple[str, ...] = Field(min_length=3)
    excluded_case_id: str
    adaptation_operations: tuple[str, ...] = Field(min_length=1)
    rule_outcome: str
    counterfactuals: tuple[str, ...] = Field(min_length=1)


class DomainCBRDemo(StrictContract):
    domain_id: str
    query: CBRCaseRecord
    library: CaseLibraryManifest
    feature_definitions: tuple[FeatureDefinition, ...]
    similarity_profile: SimilarityProfile
    expected: ExpectedJourney
    claim_boundary: str

    @model_validator(mode="after")
    def journey_is_complete(self) -> "DomainCBRDemo":
        case_ids = {case.case_id for case in self.library.cases}
        if len(self.library.cases) < 6:
            raise ValueError(f"{self.domain_id} requires at least six reviewed precedents")
        expected_ids = set(self.expected.retrieval_order) | {self.expected.excluded_case_id}
        if not expected_ids <= case_ids:
            raise ValueError(f"{self.domain_id} expectations refer to unknown cases")
        if self.query.domain_id != self.domain_id:
            raise ValueError("query domain does not match demonstration domain")
        return self


class DemoEvaluation(StrictContract):
    """Deterministic current-rule gate for a demonstration query."""

    domain_id: str
    status: str
    action: str
    blockers: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    counterfactuals: tuple[str, ...] = ()
    human_review_required: bool = True
    claim_boundary: str


def available_cbr_demos() -> tuple[str, ...]:
    """Return stable identifiers without constructing a mutable registry."""
    return tuple(item.domain_id for item in load_all_cbr_demos())


def load_cbr_demo(domain_id: str, *, path: Path = DATA_PATH) -> DomainCBRDemo:
    """Load one domain demo or raise a uniform lookup error."""
    demos = {item.domain_id: item for item in load_all_cbr_demos(path=path)}
    try:
        return demos[domain_id]
    except KeyError as error:
        raise LookupError(f"unknown CBR demonstration: {domain_id}") from error


def load_all_cbr_demos(*, path: Path = DATA_PATH) -> tuple[DomainCBRDemo, ...]:
    """Validate the canonical data file and return demos sorted by domain ID."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "ruler-cbr-domain-data/1":
        raise ValueError("unsupported CBR domain-data schema")
    claim_boundary = str(payload["claim_boundary"])
    demos = tuple(_build_demo(item, claim_boundary) for item in payload["domains"])
    ids = [demo.domain_id for demo in demos]
    if len(ids) != len(set(ids)) or set(ids) != {
        "spending",
        "regulatory",
        "fiscal",
        "trade",
        "technical_support",
    }:
        raise ValueError("CBR data must declare each of the five domains exactly once")
    return tuple(sorted(demos, key=lambda demo: demo.domain_id))


def _build_demo(raw: dict[str, Any], claim_boundary: str) -> DomainCBRDemo:
    domain_id = raw["domain_id"]
    definitions = tuple(
        FeatureDefinition(
            feature_id=feature_id,
            value_type=configuration[0],
            comparison_policy=ComparisonPolicy(configuration[1]),
            sensitivity="internal",
            missing_behavior="exclude" if feature_id in _hard_features(domain_id) else "ignore",
            numeric_range=_numeric_range(feature_id),
            ordinal_values=_ordinal_values(feature_id),
            diversity_key=feature_id
            in {
                "procurement_route",
                "use_context",
                "transaction_direction",
                "product_taxonomy",
                "firmware_version",
            },
        )
        for feature_id, configuration in raw["feature_definitions"].items()
    )
    declared = {definition.feature_id: definition for definition in definitions}
    query = _case(raw, raw["query"], declared, reviewed=False)
    candidates = tuple(_case(raw, item, declared, reviewed=True) for item in raw["cases"])
    if any(case.as_of_date > query.as_of_date for case in candidates):
        raise ValueError(f"{domain_id}: future cases cannot enter the demonstration library")
    configured_weights = _weight_map(domain_id)
    profile = SimilarityProfile(
        profile_id=f"{domain_id}-demonstration-v1",
        version="1.0",
        domain_id=domain_id,
        case_kind=raw["case_kind"],
        feature_weights=tuple(
            FeatureWeight(feature_id=key, weight=value) for key, value in configured_weights.items()
        ),
        hard_filters=(
            HardFilter(filter_id="domain", kind="domain"),
            HardFilter(filter_id="case_kind", kind="case_kind"),
            HardFilter(filter_id="jurisdiction", kind="jurisdiction"),
            HardFilter(filter_id="as_of_date", kind="temporal"),
            *(
                HardFilter(filter_id=f"feature:{feature_id}", kind="feature", feature_id=feature_id)
                for feature_id in _hard_features(domain_id)
            ),
        ),
        maximum_candidate_pool=50,
        maximum_top_k=3,
        minimum_evidence_completeness=0.7,
        require_contrast=True,
    )
    library = CaseLibraryManifest(
        library_id=f"{domain_id}-case-library",
        release_id=raw["library_release_id"],
        cases=candidates,
        dependencies=(
            CaseLibraryDependency(
                rule_release_id=raw["rule_release_id"],
                rule_release_sha256=raw["rule_release_sha256"],
            ),
        ),
        profile_sha256=profile.sha256(),
        created_at=_at_utc(date(2026, 8, 30)),
    )
    return DomainCBRDemo(
        domain_id=domain_id,
        query=query,
        library=library,
        feature_definitions=definitions,
        similarity_profile=profile,
        expected=ExpectedJourney.model_validate(raw["expected"]),
        claim_boundary=claim_boundary,
    )


def _case(
    domain: dict[str, Any],
    raw: dict[str, Any],
    definitions: dict[str, FeatureDefinition],
    *,
    reviewed: bool,
) -> CBRCaseRecord:
    undeclared = set(raw["features"]) - set(definitions)
    missing = set(definitions) - set(raw["features"])
    if undeclared or missing:
        raise ValueError(
            f"{raw['case_id']}: feature schema mismatch; undeclared={sorted(undeclared)}, missing={sorted(missing)}"
        )
    as_of = date.fromisoformat(raw["as_of_date"])
    opened_at = _at_utc(as_of)
    digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    features = tuple(
        _feature(feature_id, raw["features"][feature_id], definition, opened_at, raw["case_id"])
        for feature_id, definition in definitions.items()
    )
    disposition = None
    if reviewed:
        disposition = CaseDisposition(
            disposition_id=f"{raw['case_id']}-disposition",
            decision=raw["decision"],
            actor_role="independent_domain_reviewer",
            decided_at=opened_at,
            approval_refs=(f"review:{raw['case_id']}",),
            rule_release_id=domain["rule_release_id"],
            rule_release_sha256=domain["rule_release_sha256"],
        )
    sources = _source_refs(domain["domain_id"])
    return CBRCaseRecord.model_validate(
        dict(
            case_id=raw["case_id"],
            case_kind=raw.get("case_kind", domain["case_kind"]),
            domain_id=domain["domain_id"],
            schema_version="1.0",
            opened_at=opened_at,
            closed_at=opened_at if reviewed else None,
            as_of_date=as_of,
            jurisdictions=tuple(domain["jurisdictions"]),
            rule_release_id=domain["rule_release_id"],
            rule_release_sha256=domain["rule_release_sha256"],
            case_library_release_id=domain["library_release_id"],
            case_library_release_sha256=domain["library_release_sha256"],
            subject_ref=f"pseudonymous:{raw['case_id']}",
            party_refs=(),
            features=features,
            goals=("retrieve_comparable_experience", "verify_against_current_rules"),
            hard_constraints=_hard_constraints(domain["domain_id"]),
            requested_action=raw.get("requested_action", raw.get("decision", "review_case")),
            source_refs=sources,
            evidence_digests=(digest,),
            sensitivity_labels=frozenset({"synthetic", "internal"}),
            disposition=disposition,
            observed_outcome_id=raw.get("observed_outcome_id"),
            review_state="reviewed" if reviewed else "draft",
            retention_policy_id="cbr-demo-reviewed-v1",
        )
    )


def _feature(
    feature_id: str, value: Any, definition: FeatureDefinition, observed_at: datetime, case_id: str
) -> CaseFeature:
    if value is None:
        return CaseFeature.model_validate(
            dict(
                feature_id=feature_id,
                comparison_policy=definition.comparison_policy,
                missingness="unknown",
                source_ref=f"case:{case_id}",
            )
        )
    unit = (
        "CHF"
        if feature_id == "amount_chf"
        else ("percent" if feature_id == "component_share_percent" else None)
    )
    return CaseFeature.model_validate(
        dict(
            feature_id=feature_id,
            value=TypedValue(value_type=definition.value_type, value=value, unit=unit),
            observed_at=observed_at,
            source_ref=f"case:{case_id}",
            confidence=1.0,
            missingness="observed",
            comparison_policy=definition.comparison_policy,
        )
    )


def _at_utc(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=UTC)


def _hard_features(domain_id: str) -> frozenset[str]:
    return {
        "spending": frozenset({"currency", "procurement_route"}),
        "regulatory": frozenset({"jurisdiction"}),
        "fiscal": frozenset({"tax_jurisdiction", "transaction_direction"}),
        "trade": frozenset({"exporter_jurisdiction"}),
        "technical_support": frozenset({"product_family", "hardware_revision", "safety_class"}),
    }[domain_id]


def _numeric_range(feature_id: str) -> tuple[float, float] | None:
    return {
        "amount_chf": (0, 250_000),
        "quote_count": (0, 10),
        "budget_coverage": (0, 3),
        "component_share_percent": (0, 100),
    }.get(feature_id)


def _ordinal_values(feature_id: str) -> tuple[str, ...]:
    return {
        "sole_source_status": (
            "not_applicable",
            "justification_missing",
            "justified_not_approved",
            "waiver_approved",
        ),
        "deployment_stage": ("sandbox", "pilot", "operational"),
        "classification_state": ("unreviewed", "reviewed_not_listed", "reviewed_listed"),
        "screening_freshness": ("stale", "fresh"),
        "production_impact": ("none", "degraded", "line_stopped"),
    }.get(feature_id, ())


def _hard_constraints(domain_id: str) -> tuple[str, ...]:
    return {
        "spending": ("no_commitment_without_current_approval", "no_order_splitting"),
        "regulatory": (
            "current_effective_rules_override_precedent",
            "human_oversight_not_inferred",
        ),
        "fiscal": ("input_tax_requires_business_evidence", "unknown_is_not_false"),
        "trade": ("no_shipment_without_classification_and_release", "screening_must_be_fresh"),
        "technical_support": (
            "never_bypass_safety_interlock",
            "procedure_must_match_product_version",
        ),
    }[domain_id]


def _source_refs(domain_id: str) -> tuple[str, ...]:
    return {
        "spending": ("synthetic-internal-procurement-policy-2026.1",),
        "regulatory": ("source-metadata:eur-lex-2024-1689-2026-08-30",),
        "fiscal": ("source-metadata:swiss-fta-vat-rates-2026-08-30",),
        "trade": (
            "source-metadata:seco-industrial-goods-2026-08-30",
            "fresh-evidence-required:sanctions-screen",
        ),
        "technical_support": (
            "synthetic-tc8-manual-5.5",
            "synthetic-tc8-bulletin-2026-04",
            "synthetic-support-sla-v3",
        ),
    }[domain_id]


def evaluate_cbr_demo(domain_id: str, *, path: Path = DATA_PATH) -> DemoEvaluation:
    """Evaluate the typed query using explicit domain gates, never precedent outcomes."""
    demo = load_cbr_demo(domain_id, path=path)
    features = demo.query.feature_map()

    def value(feature_id: str) -> Any:
        feature = features[feature_id]
        return feature.value.value if feature.value is not None else None

    blockers: list[str] = []
    unknowns: list[str] = []
    if domain_id == "spending":
        if value("budget_coverage") is None or float(value("budget_coverage")) < 1:
            blockers.append("insufficient_approved_budget")
        quotes_sufficient = int(value("quote_count") or 0) >= 3
        exception_approved = value("sole_source_status") == "waiver_approved"
        if not quotes_sufficient and not exception_approved:
            blockers.append("two_additional_comparable_quotes_or_approved_waiver")
        if value("finance_approval") is not True:
            blockers.append("finance_approval")
        if value("split_pattern") is True:
            blockers.append("anti_splitting_audit")
        status, action = (
            ("blocked", "hold_order") if blockers else ("eligible", "route_to_human_release")
        )
    elif domain_id == "regulatory":
        for feature_id, blocker in (
            ("oversight_assigned", "competent_human_oversight_assignment"),
            ("affected_person_informed", "affected_person_information"),
            ("input_data_reviewed", "input_representativeness_review"),
        ):
            if value(feature_id) is not True:
                blockers.append(blocker)
        status, action = (
            ("blocked", "block_operational_deployment")
            if blockers
            else ("eligible", "route_to_legal_and_human_release_review")
        )
    elif domain_id == "fiscal":
        if value("business_purpose_evidenced") is not True:
            unknowns.append("input_tax_eligibility_without_business_purpose_evidence")
        mixed = len(set(value("rate_pattern") or [])) > 1
        status = "unknown" if unknowns else "review_required"
        action = (
            "split_tax_codes_and_hold_input_tax_claim"
            if mixed and unknowns
            else "route_line_coding_to_tax_review"
        )
    elif domain_id == "trade":
        for feature_id, unknown in (
            ("classification_state", "technical_classification"),
            ("screening_freshness", "current_sanctions_screen"),
        ):
            if value(feature_id) is None:
                unknowns.append(unknown)
        if value("end_user_known") is not True:
            blockers.append("verified_ultimate_end_user")
        if value("end_use_evidenced") is not True:
            blockers.append("end_use_statement")
        if value("licence_state") not in {
            "authorization_confirmed",
            "determination_complete",
            "not_required_by_review",
        }:
            unknowns.append("licence_determination")
        status, action = "unknown", "stop_shipment_and_escalate_export_control"
    else:
        if value("interlock_active") is not True:
            blockers.append("safety_interlock_must_remain_active")
        if value("firmware_version") != "5.5.1" or value("hardware_revision") != "C":
            unknowns.append("version_specific_procedure_not_resolved")
        status, action = (
            "blocked_pending_service",
            "keep_interlock_and_dispatch_authorized_technician",
        )
    return DemoEvaluation(
        domain_id=domain_id,
        status=status,
        action=action,
        blockers=tuple(blockers),
        unknowns=tuple(unknowns),
        counterfactuals=demo.expected.counterfactuals,
        claim_boundary=demo.claim_boundary,
    )


def _weight_map(domain_id: str) -> dict[str, float]:
    return {
        "spending": {
            "amount_chf": 0.18,
            "quote_count": 0.17,
            "sole_source_status": 0.40,
            "finance_approval": 0.03,
            "budget_coverage": 0.02,
            "split_pattern": 0.20,
        },
        "regulatory": {
            "actor_role": 0.15,
            "oversight_assigned": 0.20,
            "logging_enabled": 0.05,
            "affected_person_informed": 0.15,
            "input_data_reviewed": 0.10,
            "deployment_stage": 0.15,
            "use_context": 0.20,
        },
        "fiscal": {
            "category_mix": 0.30,
            "rate_pattern": 0.20,
            "business_purpose_evidenced": 0.25,
            "supplier_country": 0.15,
            "tax_period": 0.05,
            "transaction_direction": 0.05,
        },
        "trade": {
            "destination_country": 0.13,
            "transfer_mode": 0.05,
            "product_taxonomy": 0.07,
            "classification_state": 0.15,
            "end_user_known": 0.20,
            "end_use_evidenced": 0.15,
            "component_share_percent": 0.15,
            "licence_state": 0.05,
            "screening_freshness": 0.05,
        },
        "technical_support": {
            "firmware_version": 0.20,
            "error_code": 0.25,
            "trigger_event": 0.10,
            "self_test_pattern": 0.10,
            "interlock_active": 0.15,
            "production_impact": 0.10,
            "hardware_revision": 0.10,
        },
    }[domain_id]


__all__ = [
    "DATA_PATH",
    "DemoEvaluation",
    "DomainCBRDemo",
    "ExpectedJourney",
    "available_cbr_demos",
    "evaluate_cbr_demo",
    "load_all_cbr_demos",
    "load_cbr_demo",
]
