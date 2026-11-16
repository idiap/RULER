# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Execute every hidden-oracle behavioral row over independently typed facts."""

from __future__ import annotations

from datetime import date

from ruler.kb.prolog_compiler import EpistemicStatus
from ruler.reasoning.procurement_reference import (
    ProcurementScenario,
    enumerate_procurement_decision,
)
from ruler.testing.autoformalization_behavior import (
    CoreferenceScenario,
    LegalScenario,
    RegulatoryScenario,
    evaluate_coreference_scenario,
    evaluate_legal_scenario,
    evaluate_regulatory_scenario,
)
from ruler.testing.autoformalization_cases import (
    load_autoformalization_case_catalogue,
    load_autoformalization_oracle,
)


def _executed_labels() -> dict[str, dict[str, str]]:
    legal_inputs = {
        "complete_paid_no_established_risk": LegalScenario(
            complete_application=True, fee_paid=True, serious_risk_established=False
        ),
        "fee_missing": LegalScenario(
            complete_application=True, fee_paid=False, serious_risk_established=False
        ),
        "serious_risk_established": LegalScenario(
            complete_application=True, fee_paid=True, serious_risk_established=True
        ),
        "safety_review_pending": LegalScenario(safety_review_pending=True),
    }
    legal_expected = {
        "complete_paid_no_established_risk": "grant_permit_supported",
        "fee_missing": "grant_permit_not_proved",
        "serious_risk_established": "grant_permit_defeated",
        "safety_review_pending": "provisional_permit_permitted_not_obligatory",
    }
    legal = {
        identifier: expected
        for identifier, expected in legal_expected.items()
        if expected in evaluate_legal_scenario(legal_inputs[identifier])
    }

    procurement_inputs = {
        "amount_10000_one_quote_budget_available": ProcurementScenario(
            scenario_id="p1",
            amount_chf=10_000,
            written_quotations=1,
            budget_available=True,
            split_purchase_pattern=False,
        ),
        "amount_10001_two_quotes_finance_approved": ProcurementScenario(
            scenario_id="p2",
            amount_chf=10_001,
            written_quotations=2,
            finance_approval=True,
            budget_available=True,
            split_purchase_pattern=False,
        ),
        "amount_50000_three_quotes_finance_approved": ProcurementScenario(
            scenario_id="p3",
            amount_chf=50_000,
            written_quotations=3,
            finance_approval=True,
            budget_available=True,
            split_purchase_pattern=False,
        ),
        "amount_50001": ProcurementScenario(scenario_id="p4", amount_chf=50_001),
        "emergency_without_cfo": ProcurementScenario(
            scenario_id="p5",
            amount_chf=9_000,
            written_quotations=0,
            documented_emergency=True,
            cfo_approval_recorded=False,
            budget_available=True,
            split_purchase_pattern=False,
        ),
        "emergency_with_cfo_over_budget": ProcurementScenario(
            scenario_id="p6",
            amount_chf=9_000,
            written_quotations=0,
            documented_emergency=True,
            cfo_approval_recorded=True,
            budget_available=False,
            split_purchase_pattern=False,
        ),
        "related_6000_orders_within_30_days": ProcurementScenario(
            scenario_id="p7",
            amount_chf=6_000,
            written_quotations=3,
            finance_approval=True,
            budget_available=True,
            split_purchase_pattern=False,
            related_orders=((6_000, 30),),
        ),
    }
    procurement: dict[str, str] = {}
    for identifier, scenario in procurement_inputs.items():
        decision = enumerate_procurement_decision(scenario)
        if identifier == "amount_50001":
            label = "outside_formalized_tiers" if decision.threshold_tier is None else ""
        elif identifier == "emergency_without_cfo":
            label = (
                "quotation_requirement_not_waived"
                if not decision.quotation_requirement_waived
                else ""
            )
        elif identifier == "related_6000_orders_within_30_days":
            label = (
                "aggregate_12000_tier_applies"
                if decision.aggregate_amount_chf == 12_000
                and decision.threshold_tier == "10001_through_50000"
                else ""
            )
        else:
            label = (
                "purchase_releasable"
                if decision.status == EpistemicStatus.TRUE
                else "purchase_not_releasable"
            )
        procurement[identifier] = label

    regulatory_inputs = {
        "events_100_on_2026_03_31": RegulatoryScenario(
            event_date=date(2026, 3, 31), reportable_events=100, employee_count=10
        ),
        "events_101_on_2026_03_31": RegulatoryScenario(
            event_date=date(2026, 3, 31), reportable_events=101, employee_count=10
        ),
        "events_76_on_2026_04_01": RegulatoryScenario(
            event_date=date(2026, 4, 1), reportable_events=76, employee_count=10
        ),
        "nine_employees": RegulatoryScenario(
            event_date=date(2026, 4, 1), reportable_events=76, employee_count=9
        ),
        "ten_employees": RegulatoryScenario(
            event_date=date(2026, 4, 1), reportable_events=76, employee_count=10
        ),
        "submission_exactly_on_deadline": RegulatoryScenario(
            event_date=date(2026, 4, 1),
            reportable_events=76,
            employee_count=10,
            submission_days_after_threshold=5,
        ),
    }
    regulatory: dict[str, str] = {}
    for identifier, scenario in regulatory_inputs.items():
        decision = evaluate_regulatory_scenario(scenario)
        labels = {
            "events_100_on_2026_03_31": (
                "notice_not_triggered" if decision.notice_status == EpistemicStatus.FALSE else ""
            ),
            "events_101_on_2026_03_31": (
                "ten_day_notice_triggered"
                if decision.notice_status == EpistemicStatus.TRUE
                and decision.deadline_calendar_days == 10
                else ""
            ),
            "events_76_on_2026_04_01": (
                "five_day_notice_triggered"
                if decision.notice_status == EpistemicStatus.TRUE
                and decision.deadline_calendar_days == 5
                else ""
            ),
            "nine_employees": "undertaking_exception_applies" if decision.exception_applies else "",
            "ten_employees": (
                "undertaking_exception_does_not_apply" if not decision.exception_applies else ""
            ),
            "submission_exactly_on_deadline": (
                "within_deadline" if decision.submission_status == EpistemicStatus.TRUE else ""
            ),
        }
        regulatory[identifier] = labels[identifier]

    coreference_inputs = {
        "breach_discovered_no_prior_knowledge": CoreferenceScenario(
            query="notice", breach_discovered=True, purchaser_prior_knowledge=False
        ),
        "purchaser_already_knew": CoreferenceScenario(
            query="notice", breach_discovered=True, purchaser_prior_knowledge=True
        ),
        "concealed_it": CoreferenceScenario(query="concealment"),
        "reasonable_measures": CoreferenceScenario(query="reasonable_measures"),
    }
    coreference = {
        identifier: evaluate_coreference_scenario(scenario)
        for identifier, scenario in coreference_inputs.items()
    }

    return {
        "legal_conditional_exception_permission": legal,
        "procurement_thresholds_table": procurement,
        "regulatory_temporal_amendment": regulatory,
        "coreference_open_texture": coreference,
    }


def test_every_hidden_oracle_behavioral_row_is_mechanically_executed() -> None:
    catalogue = load_autoformalization_case_catalogue()
    actual = _executed_labels()
    assert set(actual) == {case.case_id for case in catalogue.cases}
    for case in catalogue.cases:
        oracle = load_autoformalization_oracle(case)
        expected = {item["id"]: item["expected"] for item in oracle.behavioral_cases}
        assert actual[case.case_id] == expected


def test_adversarial_boundaries_do_not_create_hybrid_or_broaden_exceptions() -> None:
    march = evaluate_regulatory_scenario(
        RegulatoryScenario(event_date=date(2026, 3, 31), reportable_events=76, employee_count=10)
    )
    april = evaluate_regulatory_scenario(
        RegulatoryScenario(event_date=date(2026, 4, 1), reportable_events=76, employee_count=10)
    )
    assert (march.version, march.threshold, march.deadline_calendar_days) == ("section_8", 100, 10)
    assert (april.version, april.threshold, april.deadline_calendar_days) == ("section_8a", 75, 5)
    assert evaluate_legal_scenario(
        LegalScenario(complete_application=True, fee_paid=True, serious_risk_established=True)
    ) == frozenset({"grant_permit_defeated"})


def test_blank_table_cell_and_unsupplied_open_texture_remain_unknown() -> None:
    blank = enumerate_procurement_decision(
        ProcurementScenario(
            scenario_id="blank-quotation-cell",
            amount_chf=8_000,
            written_quotations=None,
            budget_available=True,
            split_purchase_pattern=False,
        )
    )
    assert blank.status == EpistemicStatus.UNKNOWN
    assert (
        evaluate_coreference_scenario(CoreferenceScenario(query="concealment"))
        == "unresolved_coreference_blocks_counter_exception"
    )
