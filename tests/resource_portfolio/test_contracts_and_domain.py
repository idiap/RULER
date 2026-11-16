# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ruler.applications.resource_portfolio import (
    Capability,
    CoreStateRole,
    OperationalEvent,
    Profile,
    ProfileType,
    Provenance,
    Quality,
    QualityStatus,
    Quantity,
    Requirement,
    Resource,
    ResourceType,
    StateInterval,
    TimeInterval,
    UnitDefinition,
    WorkUnit,
    build_snapshot,
)
from ruler.domains.base import validate_domain_pack
from ruler.domains.construction_fleet import CONSTRUCTION_FLEET_DOMAIN_PACK, load_domain_manifest
from ruler.ingestion.contracts import canonical_sha256
from ruler.io import read_yaml
from ruler.paths import REPO_ROOT

NOW = datetime(2026, 9, 1, tzinfo=UTC)
VALIDITY = TimeInterval(start=NOW - timedelta(days=365), end=NOW + timedelta(days=365))


def provenance(record: str = "source-1") -> Provenance:
    return Provenance(
        source_system="reviewer_fixture",
        source_record_ids=(record,),
        observed_at=NOW - timedelta(days=1),
        ingested_at=NOW,
        content_sha256=canonical_sha256(record),
        transformation_version="fixture-1.0",
    )


def minimal_snapshot(**updates):
    location = {
        "location_id": "depot_west",
        "location_type": "depot",
        "region": "ch_west",
        "validity": VALIDITY,
        "provenance": provenance("location"),
    }
    capability = Capability(
        capability_id="capacity_a",
        output_unit="productive_hour",
        validity=VALIDITY,
        provenance=provenance("capability"),
    )
    resource_type = ResourceType(
        resource_type_id="type_a",
        taxonomy_path=("mobile", "type_a"),
        default_capability_ids=(capability.capability_id,),
        validity=VALIDITY,
        provenance=provenance("resource_type"),
    )
    resource = Resource(
        resource_id="resource_a",
        resource_type_id=resource_type.resource_type_id,
        owner_id="owner_a",
        state=CoreStateRole.PRODUCTIVE,
        location_id="depot_west",
        capability_ids=(capability.capability_id,),
        validity=VALIDITY,
        as_of=NOW,
        provenance=provenance("resource"),
    )
    work_unit = WorkUnit(
        work_unit_id="work_a",
        work_unit_type="project",
        location_id="depot_west",
        priority="normal",
        time_window=VALIDITY,
        provenance=provenance("work"),
    )
    event = OperationalEvent(
        event_id="event_a",
        domain_id="neutral_test",
        resource_id=resource.resource_id,
        resource_type_id=resource_type.resource_type_id,
        work_unit_id=work_unit.work_unit_id,
        location_id="depot_west",
        start_timestamp=NOW - timedelta(minutes=87),
        end_timestamp=NOW,
        state=CoreStateRole.PRODUCTIVE,
        measurements={"productive_time": Quantity(value=Decimal("87"), unit="minute")},
        source_event_id="source-event-a",
        quality=Quality(
            status=QualityStatus.ACCEPTED,
            confidence=Quantity(value=Decimal("0.96"), unit="ratio"),
        ),
        provenance=provenance("event"),
    )
    state = StateInterval(
        state_interval_id="state_a",
        resource_id=resource.resource_id,
        state=CoreStateRole.PRODUCTIVE,
        start_timestamp=event.start_timestamp,
        end_timestamp=event.end_timestamp,
        contributing_event_ids=(event.event_id,),
        as_of=NOW,
        provenance=provenance("state"),
    )
    requirement = Requirement(
        requirement_id="requirement_a",
        work_unit_id=work_unit.work_unit_id,
        activity_id=None,
        capability_id=capability.capability_id,
        quantity=Quantity(value=Decimal("40"), unit="hour"),
        period=VALIDITY,
        criticality="normal",
        source_type="reviewer_plan",
        confidence=Quantity(value=Decimal("0.9"), unit="ratio"),
        provenance=provenance("requirement"),
    )
    profile = Profile(
        profile_id="profile_a",
        profile_version=1,
        profile_type=ProfileType.USE,
        applicability={"capability_id": capability.capability_id},
        statistics={"median": Quantity(value=Decimal("39.6"), unit="productive_hour")},
        sample_support={"events": Quantity(value=Decimal("1"), unit="unit")},
        as_of=NOW,
        validity=VALIDITY,
        provenance=provenance("profile"),
    )
    payload = {
        "domain_id": "neutral_test",
        "domain_package_id": "neutral-test-1.0",
        "as_of": NOW,
        "created_at": NOW,
        "currency_unit": "CHF",
        "unit_definitions": (
            UnitDefinition(unit_id="ratio", dimension="dimensionless"),
            UnitDefinition(unit_id="unit", dimension="count"),
            UnitDefinition(
                unit_id="minute",
                dimension="time",
                scale_to_base=Decimal("0.01666666666666666666666666667"),
            ),
            UnitDefinition(unit_id="hour", dimension="time"),
            UnitDefinition(unit_id="productive_hour", dimension="time"),
            UnitDefinition(unit_id="CHF", dimension="currency"),
        ),
        "resources": (resource,),
        "resource_types": (resource_type,),
        "capabilities": (capability,),
        "locations": (location,),
        "work_units": (work_unit,),
        "activities": (),
        "requirements": (requirement,),
        "events": (event,),
        "state_intervals": (state,),
        "profiles": (profile,),
        "input_artifact_digests": {"source": canonical_sha256("input")},
        "watermarks": {"events": NOW},
    }
    payload.update(updates)
    return build_snapshot(**payload)


def test_snapshot_is_digest_closed_immutable_and_round_trips() -> None:
    snapshot = minimal_snapshot()
    assert snapshot.snapshot_id.startswith("resource_portfolio_snapshot:")
    assert snapshot == type(snapshot).model_validate_json(snapshot.model_dump_json())
    with pytest.raises(ValidationError, match="content_sha256"):
        type(snapshot).model_validate({**snapshot.model_dump(), "domain_package_id": "tampered"})
    with pytest.raises(ValidationError, match="frozen"):
        snapshot.domain_id = "changed"  # type: ignore[misc]


def test_snapshot_rejects_unknown_and_incompatible_units() -> None:
    original = minimal_snapshot()
    requirement = original.requirements[0].model_copy(
        update={"quantity": Quantity(value=Decimal("40"), unit="mystery")}
    )
    with pytest.raises(ValidationError, match="unknown units"):
        minimal_snapshot(requirements=(requirement,))

    volume = UnitDefinition(unit_id="m3", dimension="volume")
    requirement = original.requirements[0].model_copy(
        update={"quantity": Quantity(value=Decimal("40"), unit="m3")}
    )
    with pytest.raises(ValidationError, match="incompatible unit"):
        minimal_snapshot(
            requirements=(requirement,),
            unit_definitions=(*original.unit_definitions, volume),
        )


def test_snapshot_rejects_overlapping_consolidated_states() -> None:
    original = minimal_snapshot()
    second = original.state_intervals[0].model_copy(
        update={
            "state_interval_id": "state_b",
            "start_timestamp": NOW - timedelta(minutes=20),
            "end_timestamp": NOW + timedelta(minutes=10),
        }
    )
    with pytest.raises(ValidationError, match="overlapping consolidated states"):
        minimal_snapshot(state_intervals=(*original.state_intervals, second))


def test_unknown_gap_needs_no_fabricated_event_but_known_state_does() -> None:
    unknown = StateInterval(
        state_interval_id="gap_a",
        resource_id="resource_a",
        state=CoreStateRole.UNKNOWN,
        start_timestamp=NOW,
        end_timestamp=NOW + timedelta(hours=1),
        as_of=NOW,
        provenance=provenance("gap"),
    )
    assert unknown.contributing_event_ids == ()
    with pytest.raises(ValidationError, match="requires contributing evidence"):
        StateInterval(
            state_interval_id="unsupported_ready",
            resource_id="resource_a",
            state=CoreStateRole.READY,
            start_timestamp=NOW,
            end_timestamp=NOW + timedelta(hours=1),
            as_of=NOW,
            provenance=provenance("unsupported"),
        )


def test_time_and_probability_contracts_fail_closed() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        TimeInterval(start=datetime(2026, 1, 1), end=datetime(2026, 1, 2))
    with pytest.raises(ValidationError, match="between zero and one"):
        Quality(
            status=QualityStatus.ACCEPTED,
            confidence=Quantity(value=Decimal("1.1"), unit="ratio"),
        )


def test_construction_pack_is_real_validated_and_maps_unknown_fail_closed() -> None:
    pack = CONSTRUCTION_FLEET_DOMAIN_PACK
    validate_domain_pack(pack)
    assert load_domain_manifest().package_id == "construction-fleet-1.0.0"
    assert pack.map_source_state("PRODUCTIVE_WORK") == CoreStateRole.PRODUCTIVE
    assert pack.map_source_state("DIG") == CoreStateRole.PRODUCTIVE
    assert pack.map_source_state("new_vendor_code") == CoreStateRole.UNKNOWN
    assert pack.convert_quantity(Quantity(value=Decimal("87"), unit="minute"), "hour") == Quantity(
        value=Decimal("1.45"), unit="hour"
    )
    with pytest.raises(ValueError, match="cannot convert"):
        pack.convert_quantity(Quantity(value=Decimal("1"), unit="hour"), "CHF")


def test_alpinebuild_fixture_contains_inputs_but_no_answer_oracle() -> None:
    fixture = read_yaml(REPO_ROOT / "data/domains/construction_fleet/alpinebuild_case.yaml")
    assert len(fixture["resources"]) == 5
    assert len(fixture["work_units"]) == 3
    assert "recommendation" not in fixture
    assert "no plan or recommendation" in fixture["fixture_policy"]
