# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic normalization and state reconstruction for resource evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from ruler.applications.resource_portfolio.contracts import (
    CoreStateRole,
    OperationalEvent,
    Provenance,
    QualityStatus,
    Quantity,
    StateInterval,
)


def _canonical(value: Any) -> bytes:
    def default(item: Any) -> str:
        if isinstance(item, Decimal):
            return format(item, "f")
        if isinstance(item, datetime):
            return item.isoformat()
        return str(item)

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=default
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _stable_id(kind: str, value: Any) -> str:
    return f"{kind}:{_digest(value).removeprefix('sha256:')}"


def _event_payload(event: OperationalEvent) -> dict[str, Any]:
    return event.model_dump(mode="json", exclude_none=False)


def _event_delivery_semantics(event: OperationalEvent) -> dict[str, Any]:
    """Return observation semantics while ignoring local receipt bookkeeping."""
    payload = event.model_dump(mode="json", exclude={"event_id"}, exclude_none=False)
    provenance = dict(payload["provenance"])
    provenance.pop("ingested_at", None)
    provenance.pop("transformation_version", None)
    payload["provenance"] = provenance
    return payload


class EvidenceNormalizationResult(BaseModel):
    """Canonical evidence plus an explicit, auditable supersession view."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_events: tuple[OperationalEvent, ...]
    active_events: tuple[OperationalEvent, ...]
    duplicate_event_ids: tuple[str, ...] = ()
    correction_pairs: tuple[tuple[str, str], ...] = ()
    content_sha256: str


class StateOverlapDiagnostic(BaseModel):
    """A source overlap resolved by declared precedence, never by mutation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    start_timestamp: datetime
    end_timestamp: datetime
    selected_state: CoreStateRole
    contributing_event_ids: tuple[str, ...]


class StateReconstructionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intervals: tuple[StateInterval, ...]
    overlap_diagnostics: tuple[StateOverlapDiagnostic, ...] = ()
    content_sha256: str


DEFAULT_STATE_PRECEDENCE: tuple[CoreStateRole, ...] = tuple(
    CoreStateRole(value)
    for value in (
        "off_horizon",
        "hold",
        "unplanned_down",
        "planned_service",
        "move",
        "productive",
        "committed",
        "waiting",
        "active_nonproductive",
        "ready",
        "unknown",
    )
)


def normalize_operational_events(
    events: Iterable[OperationalEvent],
    *,
    identity_maps: Mapping[str, Mapping[str, str]] | None = None,
    state_map: Mapping[str, CoreStateRole | str] | None = None,
    unit_conversions: Mapping[str, tuple[str, Decimal | int | float | str]] | None = None,
    split_boundaries: Sequence[datetime] = (),
    additive_measurements: frozenset[str] = frozenset(
        {
            "engine_hours",
            "productive_hours",
            "idle_hours",
            "output",
            "fuel",
            "cost",
            "consumption",
        }
    ),
    transformation_version: str = "resource-evidence-normalizer-1.0",
) -> EvidenceNormalizationResult:
    """Normalize events without losing local timestamps, units, or correction history.

    Duplicate source deliveries collapse by canonical content. A source identity reused
    with different content is rejected unless the newer record explicitly corrects the
    earlier event. Calling this function repeatedly on its own canonical output is
    therefore idempotent.
    """

    identity_maps = identity_maps or {}
    state_map = state_map or {}
    unit_conversions = unit_conversions or {}
    normalized: list[OperationalEvent] = []

    for source_event in events:
        start = source_event.start_timestamp.astimezone(UTC)
        end = source_event.end_timestamp.astimezone(UTC)
        context = dict(source_event.context)
        context.setdefault("original_start_timestamp", source_event.start_timestamp.isoformat())
        context.setdefault("original_end_timestamp", source_event.end_timestamp.isoformat())

        measurements: dict[str, Quantity] = {}
        encoded_original_units = context.get("original_measurement_units")
        original_units: dict[str, str] = (
            json.loads(encoded_original_units) if encoded_original_units else {}
        )
        for name, quantity in sorted(source_event.measurements.items()):
            conversion = unit_conversions.get(quantity.unit)
            if conversion is None:
                measurements[name] = quantity
                continue
            target_unit, factor = conversion
            original_units.setdefault(name, quantity.unit)
            measurements[name] = Quantity(
                value=quantity.value * Decimal(str(factor)), unit=target_unit
            )
        if original_units:
            context["original_measurement_units"] = json.dumps(original_units, sort_keys=True)

        updates: dict[str, Any] = {
            "resource_id": identity_maps.get("resource_id", {}).get(
                source_event.resource_id, source_event.resource_id
            ),
            "resource_type_id": identity_maps.get("resource_type_id", {}).get(
                source_event.resource_type_id, source_event.resource_type_id
            ),
            "start_timestamp": start,
            "end_timestamp": end,
            "measurements": measurements,
            "context": context,
            "provenance": source_event.provenance.model_copy(
                update={"transformation_version": transformation_version}
            ),
        }
        for field in ("work_unit_id", "activity_id", "capability_id", "location_id"):
            value = getattr(source_event, field)
            if value is not None:
                updates[field] = identity_maps.get(field, {}).get(value, value)
        mapped_state = state_map.get(
            str(source_event.state), state_map.get(source_event.state.value)
        )
        if mapped_state is not None:
            updates["state"] = CoreStateRole(mapped_state)
        canonical = OperationalEvent.model_validate(
            {**source_event.model_dump(mode="python"), **updates}
        )

        boundaries = sorted(
            {boundary.astimezone(UTC) for boundary in split_boundaries if start < boundary < end}
        )
        points = [start, *boundaries, end]
        if len(points) == 2:
            normalized.append(canonical)
        else:
            for index, (part_start, part_end) in enumerate(zip(points, points[1:])):
                identity = {
                    "parent_event_id": canonical.event_id,
                    "part": index,
                    "start": part_start,
                    "end": part_end,
                }
                share = Decimal(str((part_end - part_start).total_seconds())) / Decimal(
                    str((end - start).total_seconds())
                )
                part_measurements = {
                    name: (
                        Quantity(value=value.value * share, unit=value.unit)
                        if name in additive_measurements
                        else value
                    )
                    for name, value in canonical.measurements.items()
                }
                normalized.append(
                    canonical.model_copy(
                        update={
                            "event_id": _stable_id("event", identity),
                            "start_timestamp": part_start,
                            "end_timestamp": part_end,
                            "measurements": part_measurements,
                            "context": {**canonical.context, "parent_event_id": canonical.event_id},
                        }
                    )
                )

    by_delivery: dict[tuple[str, str], OperationalEvent] = {}
    duplicates: list[str] = []
    for event in sorted(normalized, key=lambda item: (item.provenance.ingested_at, item.event_id)):
        key = (
            event.provenance.source_system,
            event.event_id if "parent_event_id" in event.context else event.source_event_id,
        )
        previous = by_delivery.get(key)
        if previous is None:
            by_delivery[key] = event
            continue
        if _event_delivery_semantics(previous) == _event_delivery_semantics(event):
            duplicates.append(event.event_id)
            continue
        if event.correction_of_event_id != previous.event_id:
            raise ValueError(
                f"source event {key!r} changed without correction_of_event_id={previous.event_id!r}"
            )
        # Keep correction artifacts separately even where a source reuses its record ID.
        by_delivery[(key[0], f"{key[1]}#correction:{event.event_id}")] = event

    canonical_events = tuple(
        sorted(by_delivery.values(), key=lambda item: (item.start_timestamp, item.event_id))
    )
    by_id = {event.event_id: event for event in canonical_events}
    corrected_ids = {
        event.correction_of_event_id
        for event in canonical_events
        if event.correction_of_event_id is not None
    }
    missing = sorted(corrected_ids - by_id.keys())
    if missing:
        raise ValueError(f"corrections reference absent events: {missing}")
    active_events = tuple(
        event for event in canonical_events if event.event_id not in corrected_ids
    )
    correction_pairs = tuple(
        sorted(
            (event.correction_of_event_id, event.event_id)
            for event in canonical_events
            if event.correction_of_event_id is not None
        )
    )
    body = {
        "canonical_events": [_event_payload(event) for event in canonical_events],
        "active_event_ids": [event.event_id for event in active_events],
        "duplicates": sorted(duplicates),
        "corrections": correction_pairs,
    }
    return EvidenceNormalizationResult(
        canonical_events=canonical_events,
        active_events=active_events,
        duplicate_event_ids=tuple(sorted(duplicates)),
        correction_pairs=correction_pairs,
        content_sha256=_digest(body),
    )


def reconstruct_state_intervals(
    events: Iterable[OperationalEvent],
    *,
    scope_start: datetime,
    scope_end: datetime,
    as_of: datetime,
    resource_ids: Iterable[str] = (),
    state_precedence: Sequence[CoreStateRole] = DEFAULT_STATE_PRECEDENCE,
    included_quality_statuses: frozenset[QualityStatus] = frozenset(
        {QualityStatus.ACCEPTED, QualityStatus.SUSPECT}
    ),
    transformation_version: str = "resource-state-reconstructor-1.0",
) -> StateReconstructionResult:
    """Sweep event boundaries into non-overlapping intervals with explicit gaps."""

    start = scope_start.astimezone(UTC)
    end = scope_end.astimezone(UTC)
    if start >= end:
        raise ValueError("state reconstruction scope must be a non-empty interval")
    rank = {state: index for index, state in enumerate(state_precedence)}
    if len(state_precedence) != len(CoreStateRole) or set(rank) != set(CoreStateRole):
        raise ValueError("state_precedence must contain every CoreStateRole exactly once")

    supplied_events = tuple(events)
    corrected_ids = {
        event.correction_of_event_id
        for event in supplied_events
        if event.correction_of_event_id is not None
    }
    selected_events = [
        event
        for event in supplied_events
        if event.start_timestamp < end
        and event.end_timestamp > start
        and event.quality.status in included_quality_statuses
        and event.event_id not in corrected_ids
    ]
    resources = sorted({event.resource_id for event in selected_events} | set(resource_ids))
    intervals: list[StateInterval] = []
    diagnostics: list[StateOverlapDiagnostic] = []
    for resource_id in resources:
        resource_events = [event for event in selected_events if event.resource_id == resource_id]
        points = sorted(
            {start, end}
            | {
                max(start, min(end, point))
                for event in resource_events
                for point in (event.start_timestamp, event.end_timestamp)
            }
        )
        for part_start, part_end in zip(points, points[1:]):
            active = sorted(
                (
                    event
                    for event in resource_events
                    if event.start_timestamp < part_end and event.end_timestamp > part_start
                ),
                key=lambda event: (rank[event.state], event.event_id),
            )
            selected_state = active[0].state if active else CoreStateRole.UNKNOWN
            contributing_ids = tuple(event.event_id for event in active)
            if len(active) > 1:
                diagnostics.append(
                    StateOverlapDiagnostic(
                        resource_id=resource_id,
                        start_timestamp=part_start,
                        end_timestamp=part_end,
                        selected_state=selected_state,
                        contributing_event_ids=contributing_ids,
                    )
                )
            identity = {
                "resource_id": resource_id,
                "state": selected_state,
                "start": part_start,
                "end": part_end,
                "events": contributing_ids,
                "as_of": as_of,
            }
            provenance = Provenance(
                source_system="resource_portfolio.state_reconstruction",
                source_record_ids=contributing_ids or (f"scope:{resource_id}",),
                observed_at=part_end,
                ingested_at=as_of,
                content_sha256=_digest(identity),
                transformation_version=transformation_version,
                parent_artifact_ids=contributing_ids,
            )
            intervals.append(
                StateInterval(
                    state_interval_id=_stable_id("state_interval", identity),
                    resource_id=resource_id,
                    state=selected_state,
                    start_timestamp=part_start,
                    end_timestamp=part_end,
                    contributing_event_ids=contributing_ids,
                    as_of=as_of,
                    provenance=provenance,
                )
            )
    intervals.sort(
        key=lambda item: (item.resource_id, item.start_timestamp, item.state_interval_id)
    )
    body = [interval.model_dump(mode="json") for interval in intervals]
    return StateReconstructionResult(
        intervals=tuple(intervals),
        overlap_diagnostics=tuple(diagnostics),
        content_sha256=_digest(body),
    )
