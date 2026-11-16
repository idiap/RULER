# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Independent, typed behavioral oracles for the realistic formalization corpus.

These functions consume ground facts, never case identifiers or model prose.  They are
kept outside producer code so a generative candidate cannot see or select its expected
label.  ``unknown`` outcomes are deliberate open-world results.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ruler.kb.prolog_compiler import EpistemicStatus


class LegalScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    complete_application: bool | None = None
    fee_paid: bool | None = None
    serious_risk_established: bool | None = None
    safety_review_pending: bool | None = None


def evaluate_legal_scenario(case: LegalScenario) -> frozenset[str]:
    results: set[str] = set()
    if case.serious_risk_established is True:
        results.add("grant_permit_defeated")
    elif case.complete_application is True and case.fee_paid is True:
        results.add("grant_permit_supported")
    else:
        results.add("grant_permit_not_proved")
    if case.safety_review_pending is True:
        results.add("provisional_permit_permitted_not_obligatory")
    return frozenset(results)


class RegulatoryScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    event_date: date
    reportable_events: int = Field(ge=0)
    employee_count: int = Field(ge=0)
    submission_days_after_threshold: int | None = Field(default=None, ge=0)


class RegulatoryDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: str
    threshold: int
    deadline_calendar_days: int
    exception_applies: bool
    notice_status: EpistemicStatus
    submission_status: EpistemicStatus


def evaluate_regulatory_scenario(case: RegulatoryScenario) -> RegulatoryDecision:
    amendment_date = date(2026, 4, 1)
    if case.event_date >= amendment_date:
        version, threshold, deadline = "section_8a", 75, 5
    else:
        version, threshold, deadline = "section_8", 100, 10
    exception = case.employee_count < 10
    triggered = case.reportable_events > threshold and not exception
    notice = EpistemicStatus.TRUE if triggered else EpistemicStatus.FALSE
    if not triggered or case.submission_days_after_threshold is None:
        submission = EpistemicStatus.UNKNOWN
    else:
        submission = (
            EpistemicStatus.TRUE
            if case.submission_days_after_threshold <= deadline
            else EpistemicStatus.FALSE
        )
    return RegulatoryDecision(
        version=version,
        threshold=threshold,
        deadline_calendar_days=deadline,
        exception_applies=exception,
        notice_status=notice,
        submission_status=submission,
    )


class CoreferenceQuery(StrEnum):
    NOTICE = "notice"
    CONCEALMENT = "concealment"
    REASONABLE_MEASURES = "reasonable_measures"


class CoreferenceScenario(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    query: CoreferenceQuery
    breach_discovered: bool | None = None
    purchaser_prior_knowledge: bool | None = None
    pronoun_antecedent_supplied: str | None = None
    open_texture_definition_supplied: bool = False


def evaluate_coreference_scenario(case: CoreferenceScenario) -> str:
    if case.query == CoreferenceQuery.CONCEALMENT:
        return (
            "counter_exception_candidate"
            if case.pronoun_antecedent_supplied
            else "unresolved_coreference_blocks_counter_exception"
        )
    if case.query == CoreferenceQuery.REASONABLE_MEASURES:
        return (
            "formalizable_with_supplied_definition"
            if case.open_texture_definition_supplied
            else "non_formalizable_without_definition"
        )
    if case.purchaser_prior_knowledge is True:
        return "notification_exception_candidate"
    if case.breach_discovered is True:
        return "notification_obligation_candidate"
    return "notification_obligation_unknown"


__all__ = [
    "CoreferenceQuery",
    "CoreferenceScenario",
    "LegalScenario",
    "RegulatoryDecision",
    "RegulatoryScenario",
    "evaluate_coreference_scenario",
    "evaluate_legal_scenario",
    "evaluate_regulatory_scenario",
]
