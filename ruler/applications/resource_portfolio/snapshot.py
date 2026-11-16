# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Digest-closed planning snapshot construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from ruler.applications.resource_portfolio.contracts import (
    Activity,
    Capability,
    Configuration,
    ExternalSupplyOffer,
    ImmutableSnapshot,
    Location,
    OperationalEvent,
    Profile,
    Requirement,
    Resource,
    ResourceType,
    Rule,
    Scenario,
    StateInterval,
    UnitDefinition,
    WorkUnit,
    build_snapshot,
)
from ruler.ingestion.contracts import canonical_sha256


def _ordered(items: Iterable[Any], identifier: str) -> tuple[Any, ...]:
    return tuple(sorted(items, key=lambda item: getattr(item, identifier)))


def _collection_digest(items: tuple[Any, ...]) -> str:
    return canonical_sha256([item.model_dump(mode="json") for item in items])


def build_immutable_snapshot(
    *,
    domain_id: str,
    domain_package_id: str,
    as_of: datetime,
    created_at: datetime,
    currency_unit: str,
    unit_definitions: Iterable[UnitDefinition],
    resources: Iterable[Resource],
    resource_types: Iterable[ResourceType],
    capabilities: Iterable[Capability],
    locations: Iterable[Location],
    work_units: Iterable[WorkUnit],
    activities: Iterable[Activity],
    requirements: Iterable[Requirement],
    configurations: Iterable[Configuration] = (),
    events: Iterable[OperationalEvent] = (),
    state_intervals: Iterable[StateInterval] = (),
    external_offers: Iterable[ExternalSupplyOffer] = (),
    profiles: Iterable[Profile] = (),
    rules: Iterable[Rule] = (),
    scenarios: Iterable[Scenario] = (),
    watermarks: Mapping[str, datetime],
    input_artifact_digests: Mapping[str, str] | None = None,
    safety_critical_capability_ids: Iterable[str] = (),
) -> ImmutableSnapshot:
    """Freeze, sort, hash, and cross-validate every solver input.

    Artifact collection digests are computed here rather than accepted on trust.
    Caller-supplied upstream digests may add source pins, but cannot contradict a
    computed collection digest. Safety-critical resources require an explicit
    ``safety_eligibility=eligible`` attribute; absent information is blocking.
    """

    collections = {
        "unit_definitions": _ordered(unit_definitions, "unit_id"),
        "resources": _ordered(resources, "resource_id"),
        "resource_types": _ordered(resource_types, "resource_type_id"),
        "capabilities": _ordered(capabilities, "capability_id"),
        "configurations": _ordered(configurations, "configuration_id"),
        "locations": _ordered(locations, "location_id"),
        "work_units": _ordered(work_units, "work_unit_id"),
        "activities": _ordered(activities, "activity_id"),
        "requirements": _ordered(requirements, "requirement_id"),
        "events": _ordered(events, "event_id"),
        "state_intervals": _ordered(state_intervals, "state_interval_id"),
        "external_offers": _ordered(external_offers, "offer_id"),
        "profiles": _ordered(profiles, "profile_id"),
        "rules": _ordered(rules, "rule_id"),
        "scenarios": _ordered(scenarios, "scenario_id"),
    }
    critical = set(safety_critical_capability_ids)
    known_capabilities = {item.capability_id for item in collections["capabilities"]}
    if not critical <= known_capabilities:
        raise ValueError(
            f"unknown safety-critical capabilities: {sorted(critical - known_capabilities)}"
        )
    for resource in collections["resources"]:
        if critical.intersection(resource.capability_ids):
            status = resource.attributes.get("safety_eligibility", "unknown")
            if status != "eligible":
                raise ValueError(
                    f"resource {resource.resource_id} has safety eligibility {status!r}; "
                    "missing or unknown safety information cannot grant permission"
                )

    computed = {
        f"collection:{name}": _collection_digest(items) for name, items in collections.items()
    }
    pinned = dict(input_artifact_digests or {})
    contradictions = {
        name: (pinned[name], digest)
        for name, digest in computed.items()
        if name in pinned and pinned[name] != digest
    }
    if contradictions:
        raise ValueError(f"input artifact digest mismatch: {contradictions}")
    pinned.update(computed)
    domain_digest = canonical_sha256(
        {"domain_id": domain_id, "domain_package_id": domain_package_id}
    )
    if "domain_package" in pinned and pinned["domain_package"] != domain_digest:
        raise ValueError("input artifact digest mismatch for domain_package")
    pinned["domain_package"] = domain_digest

    return build_snapshot(
        domain_id=domain_id,
        domain_package_id=domain_package_id,
        as_of=as_of,
        created_at=created_at,
        currency_unit=currency_unit,
        watermarks=dict(sorted(watermarks.items())),
        input_artifact_digests=dict(sorted(pinned.items())),
        **collections,
    )


__all__ = ["build_immutable_snapshot"]
