# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Independent exhaustive reference for procurement autoformalization behavior.

This is intentionally small and deterministic.  It is not a second spelling of a
greedy implementation: it enumerates the complete Boolean decision space and scores
only feasible assignments.  It is suitable as an oracle for generated symbolic rules.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ruler.kb.prolog_compiler import EpistemicStatus


class ProcurementScenario(BaseModel):
    """Ground operational facts; ``None`` means that the source fact was not supplied."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    amount_chf: int = Field(ge=0)
    written_quotations: int | None = Field(default=None, ge=0)
    finance_approval: bool | None = None
    documented_emergency: bool | None = None
    cfo_approval_recorded: bool | None = None
    budget_available: bool | None = None
    split_purchase_pattern: bool | None = None
    related_orders: tuple[tuple[int, int], ...] = ()  # (amount CHF, age in days)


class ProcurementDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    scenario_id: str
    aggregate_amount_chf: int
    threshold_tier: str | None
    quotation_requirement_waived: bool
    status: EpistemicStatus
    selected_release: bool
    objective: int
    feasible_assignments: tuple[bool, ...]
    trace: tuple[str, ...]


def enumerate_procurement_decision(scenario: ProcurementScenario) -> ProcurementDecision:
    """Enumerate release=False/True and maximize release subject to known controls."""

    aggregate = scenario.amount_chf + sum(
        amount for amount, age_days in scenario.related_orders if age_days <= 30
    )
    if aggregate <= 10_000:
        tier, quotes_required, finance_required = "up_to_10000", 1, False
    elif aggregate <= 50_000:
        tier, quotes_required, finance_required = "10001_through_50000", 3, True
    else:
        return ProcurementDecision(
            scenario_id=scenario.scenario_id,
            aggregate_amount_chf=aggregate,
            threshold_tier=None,
            quotation_requirement_waived=False,
            status=EpistemicStatus.UNKNOWN,
            selected_release=False,
            objective=0,
            feasible_assignments=(False,),
            trace=("aggregate_rolling_30_days", "outside_formalized_tiers"),
        )

    emergency_waiver = (
        scenario.documented_emergency is True and scenario.cfo_approval_recorded is True
    )
    known_failure = (
        scenario.budget_available is False
        or scenario.split_purchase_pattern is True
        or (
            scenario.written_quotations is not None
            and scenario.written_quotations < quotes_required
            and not emergency_waiver
        )
        or (finance_required and scenario.finance_approval is False)
    )
    missing_required = (
        scenario.budget_available is None
        or scenario.split_purchase_pattern is None
        or (scenario.written_quotations is None and not emergency_waiver)
        or (finance_required and scenario.finance_approval is None)
    )
    releasable = not known_failure and not missing_required
    feasible = tuple(release for release in (False, True) if not release or releasable)
    selected = max(feasible, key=int)
    status = (
        EpistemicStatus.FALSE
        if known_failure
        else EpistemicStatus.UNKNOWN if missing_required else EpistemicStatus.TRUE
    )
    return ProcurementDecision(
        scenario_id=scenario.scenario_id,
        aggregate_amount_chf=aggregate,
        threshold_tier=tier,
        quotation_requirement_waived=emergency_waiver,
        status=status,
        selected_release=selected,
        objective=int(selected),
        feasible_assignments=feasible,
        trace=(
            "aggregate_rolling_30_days",
            "select_inclusive_threshold_tier",
            "quotation_or_narrow_emergency_waiver",
            "finance_approval",
            "anti_splitting",
            "budget",
            "exhaustive_binary_maximization",
        ),
    )


def rerun_procurement_counterfactual(
    scenario: ProcurementScenario, **changes: object
) -> ProcurementDecision:
    """Apply typed input changes and execute the complete enumeration again."""

    return enumerate_procurement_decision(scenario.model_copy(update=changes))


__all__ = [
    "ProcurementDecision",
    "ProcurementScenario",
    "enumerate_procurement_decision",
    "rerun_procurement_counterfactual",
]
