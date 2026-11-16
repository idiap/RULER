# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Strict, immutable and domain-neutral resource-portfolio contracts.

The module deliberately contains no domain vocabulary.  A domain pack supplies
units, state mappings and taxonomies.  Snapshot validation closes references,
units and time ranges before any solver is allowed to consume the data.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar, Literal

from pydantic import Field, ValidationInfo, field_validator, model_validator

from ruler.contracts.common import StrictContract, validate_sha256
from ruler.ingestion.contracts import canonical_sha256, stable_id


def stable_contract_id(kind: str, identity: Any) -> str:
    """Create the canonical content-derived identifier used by these contracts."""
    return stable_id(kind, identity)


def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")


def _identifier(value: str) -> str:
    if not value.strip() or any(character.isspace() for character in value):
        raise ValueError("identifiers must be non-blank and contain no whitespace")
    return value


class TimeInterval(StrictContract):
    """A half-open ``[start, end)`` interval."""

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def ordered_and_aware(self) -> "TimeInterval":
        _aware(self.start, "start")
        _aware(self.end, "end")
        if self.end <= self.start:
            raise ValueError("time interval end must be after start")
        return self


class Quantity(StrictContract):
    """A finite decimal value with an explicit unit."""

    value: Decimal
    unit: str

    @field_validator("value")
    @classmethod
    def finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("quantity value must be finite")
        return value

    @field_validator("unit")
    @classmethod
    def named_unit(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("quantity unit must not be blank")
        return value


class UnitDefinition(StrictContract):
    unit_id: str
    dimension: str
    scale_to_base: Decimal = Decimal("1")
    offset_to_base: Decimal = Decimal("0")

    _unit_id = field_validator("unit_id")(_identifier)
    _dimension = field_validator("dimension")(_identifier)

    @model_validator(mode="after")
    def usable_conversion(self) -> "UnitDefinition":
        if not self.scale_to_base.is_finite() or self.scale_to_base <= 0:
            raise ValueError("unit scale_to_base must be finite and positive")
        if not self.offset_to_base.is_finite():
            raise ValueError("unit offset_to_base must be finite")
        return self


class Provenance(StrictContract):
    source_system: str
    source_record_ids: tuple[str, ...] = Field(min_length=1)
    observed_at: datetime
    ingested_at: datetime
    content_sha256: str
    transformation_version: str
    parent_artifact_ids: tuple[str, ...] = ()

    _hash = field_validator("content_sha256")(validate_sha256)

    @model_validator(mode="after")
    def temporal_provenance(self) -> "Provenance":
        _aware(self.observed_at, "observed_at")
        _aware(self.ingested_at, "ingested_at")
        if self.ingested_at < self.observed_at:
            raise ValueError("ingested_at cannot precede observed_at")
        if not self.source_system.strip() or not self.transformation_version.strip():
            raise ValueError("provenance source and transformation version are required")
        if len(set(self.source_record_ids)) != len(self.source_record_ids):
            raise ValueError("source_record_ids must be unique")
        return self


class QualityStatus(StrEnum):
    ACCEPTED = "accepted"
    SUSPECT = "suspect"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class Quality(StrictContract):
    status: QualityStatus
    confidence: Quantity
    flags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def confidence_is_probability(self) -> "Quality":
        if self.confidence.unit != "ratio" or not Decimal(0) <= self.confidence.value <= Decimal(1):
            raise ValueError("quality confidence must be a ratio between zero and one")
        return self


class CoreStateRole(StrEnum):
    READY = "ready"
    COMMITTED = "committed"
    PRODUCTIVE = "productive"
    ACTIVE_NONPRODUCTIVE = "active_nonproductive"
    WAITING = "waiting"
    MOVE = "move"
    PLANNED_SERVICE = "planned_service"
    UNPLANNED_DOWN = "unplanned_down"
    HOLD = "hold"
    OFF_HORIZON = "off_horizon"
    UNKNOWN = "unknown"


class Location(StrictContract):
    location_id: str
    location_type: str
    region: str
    validity: TimeInterval
    latitude: Quantity | None = None
    longitude: Quantity | None = None
    access_restrictions: tuple[str, ...] = ()
    provenance: Provenance

    _id = field_validator("location_id")(_identifier)


class Capability(StrictContract):
    capability_id: str
    output_unit: str
    compatible_capability_ids: tuple[str, ...] = ()
    validity: TimeInterval
    provenance: Provenance

    _id = field_validator("capability_id")(_identifier)


class ResourceType(StrictContract):
    resource_type_id: str
    taxonomy_path: tuple[str, ...] = Field(min_length=1)
    default_capability_ids: tuple[str, ...] = ()
    specifications: dict[str, Quantity] = Field(default_factory=dict)
    validity: TimeInterval
    provenance: Provenance

    _id = field_validator("resource_type_id")(_identifier)


class Configuration(StrictContract):
    configuration_id: str
    resource_id: str
    component_ids: tuple[str, ...] = ()
    capability_effects: dict[str, Quantity] = Field(default_factory=dict)
    setup_duration: Quantity
    validity: TimeInterval
    provenance: Provenance

    _id = field_validator("configuration_id")(_identifier)


class Resource(StrictContract):
    resource_id: str
    resource_type_id: str
    owner_id: str
    state: CoreStateRole
    location_id: str
    configuration_id: str | None = None
    capability_ids: tuple[str, ...] = ()
    attributes: dict[str, str] = Field(default_factory=dict)
    validity: TimeInterval
    as_of: datetime
    provenance: Provenance

    _id = field_validator("resource_id")(_identifier)

    @model_validator(mode="after")
    def aware_as_of(self) -> "Resource":
        _aware(self.as_of, "as_of")
        return self


class WorkUnit(StrictContract):
    work_unit_id: str
    work_unit_type: str
    location_id: str
    priority: str
    time_window: TimeInterval
    attributes: dict[str, str] = Field(default_factory=dict)
    provenance: Provenance

    _id = field_validator("work_unit_id")(_identifier)


class Activity(StrictContract):
    activity_id: str
    work_unit_id: str
    activity_type: str
    time_window: TimeInterval
    output: Quantity | None = None
    duration: Quantity | None = None
    predecessor_activity_ids: tuple[str, ...] = ()
    provenance: Provenance

    _id = field_validator("activity_id")(_identifier)


class Requirement(StrictContract):
    requirement_id: str
    work_unit_id: str
    activity_id: str | None
    capability_id: str
    quantity: Quantity
    period: TimeInterval
    criticality: Literal["low", "normal", "high", "safety_critical"]
    source_type: str
    confidence: Quantity
    profile_id: str | None = None
    provenance: Provenance

    _id = field_validator("requirement_id")(_identifier)

    @model_validator(mode="after")
    def confidence_is_probability(self) -> "Requirement":
        if self.confidence.unit != "ratio" or not Decimal(0) <= self.confidence.value <= Decimal(1):
            raise ValueError("requirement confidence must be a ratio between zero and one")
        if self.quantity.value < 0:
            raise ValueError("requirement quantity cannot be negative")
        return self


class OperationalEvent(StrictContract):
    event_id: str
    schema_version: Literal["operational-event-1.0"] = "operational-event-1.0"
    domain_id: str
    resource_id: str
    resource_type_id: str
    work_unit_id: str | None = None
    activity_id: str | None = None
    capability_id: str | None = None
    location_id: str
    start_timestamp: datetime
    end_timestamp: datetime
    state: CoreStateRole
    measurements: dict[str, Quantity] = Field(default_factory=dict)
    context: dict[str, str] = Field(default_factory=dict)
    source_event_id: str
    quality: Quality
    provenance: Provenance
    correction_of_event_id: str | None = None

    _id = field_validator("event_id")(_identifier)

    @model_validator(mode="after")
    def valid_interval(self) -> "OperationalEvent":
        TimeInterval(start=self.start_timestamp, end=self.end_timestamp)
        if self.correction_of_event_id == self.event_id:
            raise ValueError("an event cannot correct itself")
        return self


class StateInterval(StrictContract):
    state_interval_id: str
    resource_id: str
    state: CoreStateRole
    start_timestamp: datetime
    end_timestamp: datetime
    contributing_event_ids: tuple[str, ...] = ()
    as_of: datetime
    provenance: Provenance

    _id = field_validator("state_interval_id")(_identifier)

    @model_validator(mode="after")
    def valid_interval(self) -> "StateInterval":
        TimeInterval(start=self.start_timestamp, end=self.end_timestamp)
        _aware(self.as_of, "as_of")
        if self.state != CoreStateRole.UNKNOWN and not self.contributing_event_ids:
            raise ValueError("a known state interval requires contributing evidence")
        return self


class ExternalSupplyOffer(StrictContract):
    offer_id: str
    provider_id: str
    resource_type_id: str
    capability_ids: tuple[str, ...] = Field(min_length=1)
    region: str
    valid_period: TimeInterval
    capacity: Quantity
    recurring_price: Quantity
    recurring_period: Quantity
    mobilization_price: Quantity
    minimum_duration: Quantity
    lead_time: Quantity
    service_probability: Quantity
    as_of: datetime
    provenance: Provenance

    _id = field_validator("offer_id")(_identifier)

    @model_validator(mode="after")
    def valid_probability(self) -> "ExternalSupplyOffer":
        _aware(self.as_of, "as_of")
        if self.service_probability.unit != "ratio" or not Decimal(
            0
        ) <= self.service_probability.value <= Decimal(1):
            raise ValueError("service_probability must be a ratio between zero and one")
        return self


class ProfileType(StrEnum):
    USE = "use"
    PRODUCTIVITY = "productivity"
    STATE = "state"
    RELIABILITY = "reliability"
    DEMAND = "demand"
    CONCURRENCY = "concurrency"
    SUBSTITUTION = "substitution"
    EXTERNAL_SUPPLY = "external_supply"


class Profile(StrictContract):
    profile_id: str
    profile_version: int = Field(ge=1)
    profile_type: ProfileType
    applicability: dict[str, str] = Field(min_length=1)
    statistics: dict[str, Quantity] = Field(min_length=1)
    uncertainty: dict[str, Quantity] = Field(default_factory=dict)
    sample_support: dict[str, Quantity] = Field(default_factory=dict)
    fallback_level: int = Field(default=0, ge=0)
    as_of: datetime
    validity: TimeInterval
    provenance: Provenance

    _id = field_validator("profile_id")(_identifier)

    @model_validator(mode="after")
    def aware_as_of(self) -> "Profile":
        _aware(self.as_of, "as_of")
        return self


class Rule(StrictContract):
    rule_id: str
    version: str
    rule_type: Literal[
        "classification",
        "derivation",
        "validation",
        "eligibility",
        "requirement",
        "hard_policy",
        "soft_preference",
        "default",
        "temporal",
        "decision_dependent",
        "approval",
        "advisory",
    ]
    owner: str
    authority: str
    scope: dict[str, str]
    priority: int
    effective_period: TimeInterval
    expression: dict[str, Any]
    rationale: str
    test_case_ids: tuple[str, ...] = Field(min_length=1)
    provenance: Provenance

    _id = field_validator("rule_id")(_identifier)


class Scenario(StrictContract):
    scenario_id: str
    probability: Quantity
    demand_multipliers: dict[str, Quantity] = Field(default_factory=dict)
    availability_multipliers: dict[str, Quantity] = Field(default_factory=dict)
    duration_multipliers: dict[str, Quantity] = Field(default_factory=dict)
    cost_multipliers: dict[str, Quantity] = Field(default_factory=dict)
    supply_multipliers: dict[str, Quantity] = Field(default_factory=dict)
    information_set: str
    validity: TimeInterval
    as_of: datetime
    provenance: Provenance

    _id = field_validator("scenario_id")(_identifier)

    @model_validator(mode="after")
    def probability_is_valid(self) -> "Scenario":
        _aware(self.as_of, "as_of")
        if self.probability.unit != "ratio" or not Decimal(0) <= self.probability.value <= Decimal(
            1
        ):
            raise ValueError("scenario probability must be a ratio between zero and one")
        for collection in (
            self.demand_multipliers,
            self.availability_multipliers,
            self.duration_multipliers,
            self.cost_multipliers,
            self.supply_multipliers,
        ):
            if any(item.unit != "ratio" or item.value < 0 for item in collection.values()):
                raise ValueError("scenario multipliers must be non-negative ratios")
        return self


class DecisionType(StrEnum):
    RETAIN = "retain"
    RELEASE = "release"
    ACQUIRE = "acquire"
    RESERVE_EXTERNAL = "reserve_external"
    ACTIVATE_EXTERNAL = "activate_external"
    ALLOCATE = "allocate"
    MOVE = "move"
    SERVICE = "service"
    HOLD_RESERVE = "hold_reserve"
    ACCEPT_SHORTFALL = "accept_shortfall"


class Decision(StrictContract):
    decision_id: str
    decision_type: DecisionType
    target_id: str
    period: TimeInterval
    quantity: Quantity
    scenario_id: str | None = None
    information_set: str
    selected: bool
    trace_ref_ids: tuple[str, ...] = Field(min_length=1)
    provenance: Provenance

    _id = field_validator("decision_id")(_identifier)


class PlanStatus(StrEnum):
    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNBOUNDED = "unbounded"
    TIME_LIMIT = "time_limit"
    ERROR = "error"


class Plan(StrictContract):
    plan_id: str
    snapshot_id: str
    horizon: TimeInterval
    decisions: tuple[Decision, ...]
    objective_terms: dict[str, Quantity]
    status: PlanStatus
    incumbent: Quantity | None = None
    bound: Quantity | None = None
    relative_gap: Quantity | None = None
    backend_receipt_id: str
    created_at: datetime
    advisory: Literal[True] = True
    provenance: Provenance

    _id = field_validator("plan_id")(_identifier)

    @model_validator(mode="after")
    def valid_solver_result(self) -> "Plan":
        _aware(self.created_at, "created_at")
        if self.relative_gap and (self.relative_gap.unit != "ratio" or self.relative_gap.value < 0):
            raise ValueError("relative_gap must be a non-negative ratio")
        if self.status == PlanStatus.OPTIMAL and self.relative_gap and self.relative_gap.value != 0:
            raise ValueError("an optimal plan must have zero relative gap")
        if (
            self.status in {PlanStatus.INFEASIBLE, PlanStatus.UNBOUNDED, PlanStatus.ERROR}
            and self.decisions
        ):
            raise ValueError("a plan without a feasible incumbent cannot contain decisions")
        return self


class TraceEdge(StrictContract):
    source_id: str
    target_id: str
    relation: Literal[
        "supports", "derived_from", "compiled_from", "constrains", "selected_by", "observed_in"
    ]


class ExplanationTrace(StrictContract):
    trace_id: str
    plan_id: str
    node_ids: tuple[str, ...] = Field(min_length=1)
    edges: tuple[TraceEdge, ...]
    counterfactual_plan_ids: tuple[str, ...] = ()
    content_sha256: str
    as_of: datetime
    provenance: Provenance

    _id = field_validator("trace_id")(_identifier)
    _hash = field_validator("content_sha256")(validate_sha256)

    @model_validator(mode="after")
    def aware_as_of(self) -> "ExplanationTrace":
        _aware(self.as_of, "as_of")
        return self


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"
    EXPIRED = "expired"


class Approval(StrictContract):
    approval_id: str
    plan_id: str
    status: ApprovalStatus
    actor_id: str
    reason: str
    scope_decision_ids: tuple[str, ...]
    recorded_at: datetime
    expires_at: datetime | None = None
    supersedes_approval_id: str | None = None
    original_plan_sha256: str
    provenance: Provenance

    _id = field_validator("approval_id")(_identifier)
    _hash = field_validator("original_plan_sha256")(validate_sha256)

    @model_validator(mode="after")
    def valid_times(self) -> "Approval":
        _aware(self.recorded_at, "recorded_at")
        if self.expires_at is not None:
            _aware(self.expires_at, "expires_at")
            if self.expires_at <= self.recorded_at:
                raise ValueError("approval expiry must follow its recorded time")
        if self.status == ApprovalStatus.OVERRIDDEN and not self.supersedes_approval_id:
            raise ValueError("an override must identify the superseded approval")
        return self


class Outcome(StrictContract):
    outcome_id: str
    plan_id: str
    decision_id: str
    expected: dict[str, Quantity]
    realized: dict[str, Quantity]
    observed_period: TimeInterval
    recorded_at: datetime
    provenance: Provenance
    supersedes_outcome_id: str | None = None
    causal_claim: Literal[False] = False

    _id = field_validator("outcome_id")(_identifier)

    @model_validator(mode="after")
    def aware_recorded_at(self) -> "Outcome":
        _aware(self.recorded_at, "recorded_at")
        return self


def _walk_quantities(value: Any):
    if isinstance(value, Quantity):
        yield value
    elif isinstance(value, StrictContract):
        for field_value in value.__dict__.values():
            yield from _walk_quantities(field_value)
    elif isinstance(value, dict):
        for field_value in value.values():
            yield from _walk_quantities(field_value)
    elif isinstance(value, (tuple, list)):
        for field_value in value:
            yield from _walk_quantities(field_value)


class ImmutableSnapshot(StrictContract):
    """Digest-closed solver input; validates the complete reference graph."""

    _DIGEST_EXCLUDES: ClassVar[set[str]] = {"snapshot_id", "content_sha256"}

    snapshot_id: str
    schema_version: Literal["resource-portfolio-snapshot-1.0"] = "resource-portfolio-snapshot-1.0"
    domain_id: str
    domain_package_id: str
    as_of: datetime
    created_at: datetime
    currency_unit: str
    unit_definitions: tuple[UnitDefinition, ...] = Field(min_length=1)
    resources: tuple[Resource, ...]
    resource_types: tuple[ResourceType, ...]
    capabilities: tuple[Capability, ...]
    configurations: tuple[Configuration, ...] = ()
    locations: tuple[Location, ...]
    work_units: tuple[WorkUnit, ...]
    activities: tuple[Activity, ...]
    requirements: tuple[Requirement, ...]
    events: tuple[OperationalEvent, ...] = ()
    state_intervals: tuple[StateInterval, ...] = ()
    external_offers: tuple[ExternalSupplyOffer, ...] = ()
    profiles: tuple[Profile, ...] = ()
    rules: tuple[Rule, ...] = ()
    scenarios: tuple[Scenario, ...] = ()
    input_artifact_digests: dict[str, str] = Field(min_length=1)
    watermarks: dict[str, datetime] = Field(min_length=1)
    content_sha256: str

    _hash = field_validator("content_sha256")(validate_sha256)

    def digest_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude=self._DIGEST_EXCLUDES)

    @model_validator(mode="after")
    def closed_and_consistent(self, info: ValidationInfo) -> "ImmutableSnapshot":
        _aware(self.as_of, "as_of")
        _aware(self.created_at, "created_at")
        if self.created_at < self.as_of:
            raise ValueError("snapshot creation cannot precede its as-of time")
        for watermark in self.watermarks.values():
            _aware(watermark, "watermark")
            if watermark > self.as_of:
                raise ValueError("snapshot watermark cannot be later than as_of")
        for digest in self.input_artifact_digests.values():
            validate_sha256(digest)

        collections = (
            ("unit", self.unit_definitions, "unit_id"),
            ("resource", self.resources, "resource_id"),
            ("resource type", self.resource_types, "resource_type_id"),
            ("capability", self.capabilities, "capability_id"),
            ("configuration", self.configurations, "configuration_id"),
            ("location", self.locations, "location_id"),
            ("work unit", self.work_units, "work_unit_id"),
            ("activity", self.activities, "activity_id"),
            ("requirement", self.requirements, "requirement_id"),
            ("event", self.events, "event_id"),
            ("state interval", self.state_intervals, "state_interval_id"),
            ("offer", self.external_offers, "offer_id"),
            ("profile", self.profiles, "profile_id"),
            ("rule", self.rules, "rule_id"),
            ("scenario", self.scenarios, "scenario_id"),
        )
        indices: dict[str, set[str]] = {}
        for label, items, key in collections:
            values = [getattr(item, key) for item in items]
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {label} identifiers")
            indices[label] = set(values)

        known_units = indices["unit"]
        if self.currency_unit not in known_units:
            raise ValueError("currency_unit is not declared")
        unknown_units = sorted(
            {
                quantity.unit
                for quantity in _walk_quantities(self)
                if quantity.unit not in known_units
            }
        )
        if unknown_units:
            raise ValueError(f"unknown units: {', '.join(unknown_units)}")

        capability_units = {item.capability_id: item.output_unit for item in self.capabilities}
        unit_dimensions = {item.unit_id: item.dimension for item in self.unit_definitions}
        for capability in self.capabilities:
            if capability.output_unit not in known_units:
                raise ValueError(f"capability {capability.capability_id} has unknown output unit")
        for resource_type in self.resource_types:
            if not set(resource_type.default_capability_ids) <= indices["capability"]:
                raise ValueError(
                    f"resource type {resource_type.resource_type_id} refers to unknown capability"
                )
        for resource in self.resources:
            if (
                resource.resource_type_id not in indices["resource type"]
                or resource.location_id not in indices["location"]
            ):
                raise ValueError(
                    f"resource {resource.resource_id} has an unresolved type or location"
                )
            if (
                resource.configuration_id
                and resource.configuration_id not in indices["configuration"]
            ):
                raise ValueError(f"resource {resource.resource_id} has an unresolved configuration")
            if not set(resource.capability_ids) <= indices["capability"]:
                raise ValueError(f"resource {resource.resource_id} refers to unknown capability")
        for configuration in self.configurations:
            if configuration.resource_id not in indices["resource"]:
                raise ValueError(
                    f"configuration {configuration.configuration_id} has an unresolved resource"
                )
        for work_unit in self.work_units:
            if work_unit.location_id not in indices["location"]:
                raise ValueError(f"work unit {work_unit.work_unit_id} has an unresolved location")
        for activity in self.activities:
            if (
                activity.work_unit_id not in indices["work unit"]
                or not set(activity.predecessor_activity_ids) <= indices["activity"]
            ):
                raise ValueError(f"activity {activity.activity_id} has an unresolved reference")
        for requirement in self.requirements:
            if (
                requirement.work_unit_id not in indices["work unit"]
                or requirement.capability_id not in indices["capability"]
            ):
                raise ValueError(
                    f"requirement {requirement.requirement_id} has an unresolved reference"
                )
            if requirement.activity_id and requirement.activity_id not in indices["activity"]:
                raise ValueError(
                    f"requirement {requirement.requirement_id} has an unresolved activity"
                )
            expected = capability_units[requirement.capability_id]
            if unit_dimensions[requirement.quantity.unit] != unit_dimensions[expected]:
                raise ValueError(
                    f"requirement {requirement.requirement_id} has an incompatible unit"
                )
            if requirement.profile_id and requirement.profile_id not in indices["profile"]:
                raise ValueError(
                    f"requirement {requirement.requirement_id} has an unresolved profile"
                )
        for event in self.events:
            if event.domain_id != self.domain_id or event.resource_id not in indices["resource"]:
                raise ValueError(
                    f"event {event.event_id} has an unresolved resource or wrong domain"
                )
            if (
                event.resource_type_id not in indices["resource type"]
                or event.location_id not in indices["location"]
            ):
                raise ValueError(f"event {event.event_id} has an unresolved type or location")
            if event.work_unit_id and event.work_unit_id not in indices["work unit"]:
                raise ValueError(f"event {event.event_id} has an unresolved work unit")
            if event.activity_id and event.activity_id not in indices["activity"]:
                raise ValueError(f"event {event.event_id} has an unresolved activity")
            if event.capability_id and event.capability_id not in indices["capability"]:
                raise ValueError(f"event {event.event_id} has an unresolved capability")
            if (
                event.correction_of_event_id
                and event.correction_of_event_id not in indices["event"]
            ):
                raise ValueError(f"event {event.event_id} corrects an unknown event")
        for offer in self.external_offers:
            if (
                offer.resource_type_id not in indices["resource type"]
                or not set(offer.capability_ids) <= indices["capability"]
            ):
                raise ValueError(f"offer {offer.offer_id} has an unresolved type or capability")

        by_resource: defaultdict[str, list[StateInterval]] = defaultdict(list)
        for interval in self.state_intervals:
            if (
                interval.resource_id not in indices["resource"]
                or not set(interval.contributing_event_ids) <= indices["event"]
            ):
                raise ValueError(
                    f"state interval {interval.state_interval_id} has an unresolved reference"
                )
            by_resource[interval.resource_id].append(interval)
        for resource_id, intervals in by_resource.items():
            ordered = sorted(intervals, key=lambda item: item.start_timestamp)
            for previous, following in zip(ordered, ordered[1:], strict=False):
                if following.start_timestamp < previous.end_timestamp:
                    raise ValueError(f"overlapping consolidated states for resource {resource_id}")

        if self.scenarios:
            total = sum((item.probability.value for item in self.scenarios), Decimal(0))
            if not math.isclose(float(total), 1.0, rel_tol=0, abs_tol=1e-9):
                raise ValueError("scenario probabilities must sum to one")

        if info.context and info.context.get("skip_snapshot_digest"):
            return self
        expected_digest = canonical_sha256(self.digest_payload())
        expected_id = stable_id("resource_portfolio_snapshot", self.digest_payload())
        if self.content_sha256 != expected_digest:
            raise ValueError("snapshot content_sha256 does not match content")
        if self.snapshot_id != expected_id:
            raise ValueError("snapshot_id does not match immutable snapshot content")
        return self


Snapshot = ImmutableSnapshot


def build_snapshot(**payload: Any) -> ImmutableSnapshot:
    """Build a snapshot while deriving its digest and immutable identifier."""
    unsigned = dict(payload)
    unsigned.pop("snapshot_id", None)
    unsigned.pop("content_sha256", None)
    # Normalize nested mappings before hashing so mapping and model inputs have
    # identical canonical identities. All semantic checks still run here.
    provisional = ImmutableSnapshot.model_validate(
        {
            **unsigned,
            "snapshot_id": "provisional",
            "content_sha256": "sha256:" + "0" * 64,
        },
        context={"skip_snapshot_digest": True},
    )
    digest_payload = provisional.model_dump(mode="json", exclude=ImmutableSnapshot._DIGEST_EXCLUDES)
    unsigned["content_sha256"] = canonical_sha256(digest_payload)
    unsigned["snapshot_id"] = stable_id("resource_portfolio_snapshot", digest_payload)
    return ImmutableSnapshot.model_validate(unsigned)


__all__ = [name for name in globals() if not name.startswith("_")]
