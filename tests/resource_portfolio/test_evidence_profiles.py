# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from ruler.applications.resource_portfolio.contracts import (
    Capability,
    CoreStateRole,
    Location,
    OperationalEvent,
    Provenance,
    Quality,
    Quantity,
    Resource,
    ResourceType,
    TimeInterval,
    UnitDefinition,
)
from ruler.applications.resource_portfolio.evidence import (
    normalize_operational_events,
    reconstruct_state_intervals,
)
from ruler.applications.resource_portfolio.profiles import (
    SupplyConstraintStatus,
    build_conditional_profiles,
    estimate_latent_demand_lower_bound,
    fit_weibull_reliability,
)
from ruler.applications.resource_portfolio.snapshot import build_immutable_snapshot

NOW = datetime(2026, 9, 3, 12, tzinfo=UTC)
START = datetime(2026, 5, 14, 5, tzinfo=UTC)
HASH = "sha256:" + "a" * 64


def provenance(record: str, *, observed: datetime = START) -> Provenance:
    return Provenance(
        source_system="test-source",
        source_record_ids=(record,),
        observed_at=observed,
        ingested_at=NOW,
        content_sha256=HASH,
        transformation_version="source-1",
    )


def event(
    event_id: str,
    start_hour: int,
    end_hour: int,
    state: CoreStateRole,
    *,
    source_event_id: str | None = None,
    correction_of_event_id: str | None = None,
    output: str = "100",
) -> OperationalEvent:
    return OperationalEvent(
        event_id=event_id,
        domain_id="test-domain",
        resource_id="resource-1",
        resource_type_id="type-1",
        capability_id="capability-1",
        location_id="location-1",
        start_timestamp=START + timedelta(hours=start_hour),
        end_timestamp=START + timedelta(hours=end_hour),
        state=state,
        measurements={
            "productive_hours": Quantity(value=end_hour - start_hour, unit="hour"),
            "engine_hours": Quantity(value=end_hour - start_hour, unit="hour"),
            "output": Quantity(value=output, unit="item"),
        },
        context={"weather": "dry"},
        source_event_id=source_event_id or event_id,
        quality=Quality(
            status="accepted", confidence=Quantity(value=Decimal("0.95"), unit="ratio")
        ),
        provenance=provenance(source_event_id or event_id),
        correction_of_event_id=correction_of_event_id,
    )


def test_normalization_is_idempotent_and_retains_correction_history() -> None:
    original = event("event-1", 0, 2, CoreStateRole.PRODUCTIVE, source_event_id="source-1")
    corrected = event(
        "event-2",
        0,
        1,
        CoreStateRole.PRODUCTIVE,
        source_event_id="source-1",
        correction_of_event_id="event-1",
    )
    once = normalize_operational_events([original, original, corrected])
    twice = normalize_operational_events(once.canonical_events)

    assert [item.event_id for item in once.canonical_events] == ["event-1", "event-2"]
    assert [item.event_id for item in once.active_events] == ["event-2"]
    assert once.correction_pairs == (("event-1", "event-2"),)
    assert twice.canonical_events == once.canonical_events
    assert twice.active_events == once.active_events


def test_duplicate_source_redelivery_ignores_receipt_id_and_ingestion_time() -> None:
    original = event("receipt-1", 0, 2, CoreStateRole.PRODUCTIVE, source_event_id="source-1")
    redelivery = original.model_copy(
        update={
            "event_id": "receipt-2",
            "provenance": original.provenance.model_copy(
                update={"ingested_at": NOW + timedelta(minutes=1)}
            ),
        }
    )
    result = normalize_operational_events([original, redelivery])

    assert len(result.canonical_events) == 1
    assert result.duplicate_event_ids == ("receipt-2",)


def test_boundary_splitting_preserves_additive_measurement_total() -> None:
    source = event("event-split", 0, 2, CoreStateRole.PRODUCTIVE, output="100")
    result = normalize_operational_events([source], split_boundaries=[START + timedelta(hours=1)])

    assert len(result.canonical_events) == 2
    assert sum(item.measurements["output"].value for item in result.canonical_events) == Decimal(
        "100"
    )


def test_normalization_preserves_local_time_and_converts_units_once() -> None:
    local = timezone(timedelta(hours=2))
    source = event("event-local", 0, 1, CoreStateRole.PRODUCTIVE).model_copy(
        update={
            "start_timestamp": START.astimezone(local),
            "end_timestamp": (START + timedelta(hours=1)).astimezone(local),
            "measurements": {"duration": Quantity(value=Decimal("87"), unit="minute")},
        }
    )
    normalized = normalize_operational_events(
        [source], unit_conversions={"minute": ("hour", Decimal(1) / Decimal(60))}
    )
    replayed = normalize_operational_events(
        normalized.canonical_events,
        unit_conversions={"minute": ("hour", Decimal(1) / Decimal(60))},
    )
    item = replayed.active_events[0]
    assert item.measurements["duration"] == Quantity(value=Decimal("1.45"), unit="hour")
    assert item.context["original_start_timestamp"].endswith("+02:00")
    assert item.context["original_measurement_units"] == '{"duration": "minute"}'


def test_state_sweep_applies_precedence_and_materializes_unknown_gaps() -> None:
    productive = event("productive", 1, 4, CoreStateRole.PRODUCTIVE)
    down = event("down", 2, 3, CoreStateRole.UNPLANNED_DOWN)
    result = reconstruct_state_intervals(
        [productive, down],
        scope_start=START,
        scope_end=START + timedelta(hours=5),
        as_of=NOW,
        resource_ids=["resource-1"],
    )

    assert [item.state for item in result.intervals] == [
        CoreStateRole.UNKNOWN,
        CoreStateRole.PRODUCTIVE,
        CoreStateRole.UNPLANNED_DOWN,
        CoreStateRole.PRODUCTIVE,
        CoreStateRole.UNKNOWN,
    ]
    assert result.intervals[0].contributing_event_ids == ()
    assert len(result.overlap_diagnostics) == 1
    assert all(
        following.start_timestamp >= previous.end_timestamp
        for previous, following in zip(result.intervals, result.intervals[1:])
    )


def test_profiles_use_numeric_evidence_and_real_scipy_reliability_fit() -> None:
    events = [
        event("e1", 0, 1, CoreStateRole.PRODUCTIVE, output="10"),
        event("e2", 1, 3, CoreStateRole.PRODUCTIVE, output="40"),
        event("e3", 3, 4, CoreStateRole.UNPLANNED_DOWN, output="0"),
    ]
    states = reconstruct_state_intervals(
        events,
        scope_start=START,
        scope_end=START + timedelta(hours=4),
        as_of=NOW,
    ).intervals
    profiles = build_conditional_profiles(
        events,
        states,
        as_of=NOW,
        validity=TimeInterval(start=NOW, end=NOW + timedelta(days=90)),
        context_dimensions=("weather",),
    )
    types = {profile.profile_type.value for profile in profiles}
    productivity = next(
        profile for profile in profiles if profile.profile_type.value == "productivity"
    )
    reliability = next(
        profile for profile in profiles if profile.profile_type.value == "reliability"
    )

    assert types == {"use", "productivity", "state", "reliability"}
    assert productivity.statistics["median_output_per_productive_hour"].value == 10
    assert reliability.statistics["failure_count"].value == 1
    fit = fit_weibull_reliability([10, 12, 7, 20], [False, True, False, True])
    assert fit.backend.startswith("scipy.optimize.minimize")
    assert fit.shape_beta > 0 and fit.scale_eta_hours > 0
    assert (
        Decimal(0)
        < fit.survival_probability(current_age_hours=Decimal(10), delta_hours=Decimal(5))
        < Decimal(1)
    )


def test_latent_demand_uses_max_bound_and_deduplicates_shortage_signals() -> None:
    estimate = estimate_latent_demand_lower_bound(
        delivered=Quantity(value=Decimal("14.4"), unit="productive_hour"),
        requested_minimum=Quantity(value=Decimal("18"), unit="productive_hour"),
        planned_output=Quantity(value=Decimal("1100"), unit="m3"),
        productivity=Quantity(value=Decimal("56.9"), unit="m3/productive_hour"),
        constraint_evidence=["rental_unavailable", "request_rejected", "rental_unavailable"],
    )
    reduced_supply = estimate_latent_demand_lower_bound(
        delivered=Quantity(value=Decimal("10"), unit="productive_hour"),
        requested_minimum=Quantity(value=Decimal("18"), unit="productive_hour"),
        planned_output=Quantity(value=Decimal("1100"), unit="m3"),
        productivity=Quantity(value=Decimal("56.9"), unit="m3/productive_hour"),
        constraint_evidence=["rental_unavailable"],
    )

    assert estimate.latent_demand_lower_bound.value == Decimal("1100") / Decimal("56.9")
    assert (
        reduced_supply.latent_demand_lower_bound.value >= estimate.latent_demand_lower_bound.value
    )
    assert estimate.constraint_status == SupplyConstraintStatus.SUPPLY_CONSTRAINED
    assert estimate.corroborating_evidence == ("rental_unavailable", "request_rejected")


def test_snapshot_builder_is_order_independent_digest_closed_and_safety_blocking() -> None:
    validity = TimeInterval(start=START, end=NOW + timedelta(days=365))
    location = Location(
        location_id="location-1",
        location_type="site",
        region="region-1",
        validity=validity,
        provenance=provenance("location"),
    )
    capability = Capability(
        capability_id="capability-1",
        output_unit="item",
        validity=validity,
        provenance=provenance("capability"),
    )
    resource_type = ResourceType(
        resource_type_id="type-1",
        taxonomy_path=("resource",),
        default_capability_ids=("capability-1",),
        validity=validity,
        provenance=provenance("type"),
    )
    resource = Resource(
        resource_id="resource-1",
        resource_type_id="type-1",
        owner_id="owner-1",
        state=CoreStateRole.READY,
        location_id="location-1",
        capability_ids=("capability-1",),
        attributes={"safety_eligibility": "eligible"},
        validity=validity,
        as_of=NOW,
        provenance=provenance("resource"),
    )
    units = [
        UnitDefinition(unit_id="CHF", dimension="currency"),
        UnitDefinition(unit_id="item", dimension="output"),
        UnitDefinition(unit_id="ratio", dimension="ratio"),
    ]
    arguments = dict(
        domain_id="test-domain",
        domain_package_id="test-domain-1.0",
        as_of=NOW,
        created_at=NOW,
        currency_unit="CHF",
        unit_definitions=reversed(units),
        resources=[resource],
        resource_types=[resource_type],
        capabilities=[capability],
        locations=[location],
        work_units=[],
        activities=[],
        requirements=[],
        watermarks={"events": NOW},
        safety_critical_capability_ids=["capability-1"],
    )
    first = build_immutable_snapshot(**arguments)
    second = build_immutable_snapshot(**{**arguments, "unit_definitions": units})
    changed = build_immutable_snapshot(
        **{
            **arguments,
            "unit_definitions": units,
            "resources": [resource.model_copy(update={"owner_id": "owner-2"})],
        }
    )

    assert first.snapshot_id == second.snapshot_id
    assert first.content_sha256 == second.content_sha256
    assert changed.content_sha256 != first.content_sha256
    with pytest.raises(ValueError, match="safety eligibility"):
        build_immutable_snapshot(
            **{
                **arguments,
                "unit_definitions": units,
                "resources": [resource.model_copy(update={"attributes": {}})],
            }
        )
