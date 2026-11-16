# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic empirical profiles and constrained-demand correction."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from statistics import median
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator
from scipy.optimize import minimize

from ruler.applications.resource_portfolio.contracts import (
    CoreStateRole,
    OperationalEvent,
    Profile,
    ProfileType,
    Provenance,
    Quantity,
    StateInterval,
    TimeInterval,
)


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _stable_id(kind: str, value: Any) -> str:
    return f"{kind}:{_digest(value).removeprefix('sha256:')}"


def _hours(start: datetime, end: datetime) -> Decimal:
    return Decimal(str((end - start).total_seconds())) / Decimal(3600)


class ReliabilityFit(BaseModel):
    """Two-parameter Weibull maximum-likelihood result with censoring."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    shape_beta: Decimal = Field(gt=0)
    scale_eta_hours: Decimal = Field(gt=0)
    failures: int = Field(ge=0)
    observations: int = Field(gt=0)
    converged: bool
    backend: str = "scipy.optimize.minimize:L-BFGS-B"

    def survival_probability(self, *, current_age_hours: Decimal, delta_hours: Decimal) -> Decimal:
        if current_age_hours < 0 or delta_hours < 0:
            raise ValueError("reliability exposure must be non-negative")
        beta = float(self.shape_beta)
        eta = float(self.scale_eta_hours)
        probability = math.exp(
            -((float(current_age_hours + delta_hours) / eta) ** beta)
            + ((float(current_age_hours) / eta) ** beta)
        )
        return Decimal(str(probability))


def fit_weibull_reliability(
    exposure_hours: Sequence[Decimal | float | int],
    failed: Sequence[bool],
) -> ReliabilityFit:
    """Fit censored Weibull survival data using a real SciPy optimizer backend."""

    if len(exposure_hours) != len(failed) or not exposure_hours:
        raise ValueError("exposure_hours and failed must be non-empty and have equal length")
    exposure = [float(value) for value in exposure_hours]
    if any(value <= 0 or not math.isfinite(value) for value in exposure):
        raise ValueError("all reliability exposures must be finite and positive")
    failures = sum(failed)
    if failures == 0:
        # With no observed failures the Weibull likelihood has no finite scale MLE.
        # Return the conservative empirical lower-bound model explicitly as unconverged.
        return ReliabilityFit(
            shape_beta=Decimal("1"),
            scale_eta_hours=Decimal(str(max(exposure) * (len(exposure) + 1))),
            failures=0,
            observations=len(exposure),
            converged=False,
        )

    def negative_log_likelihood(log_parameters: Sequence[float]) -> float:
        beta, eta = math.exp(log_parameters[0]), math.exp(log_parameters[1])
        result = 0.0
        for duration, is_failure in zip(exposure, failed, strict=True):
            cumulative_hazard = (duration / eta) ** beta
            if is_failure:
                result -= (
                    math.log(beta)
                    - math.log(eta)
                    + (beta - 1) * math.log(duration / eta)
                    - cumulative_hazard
                )
            else:
                result += cumulative_hazard
        return result

    initial_scale = median(exposure)
    result = minimize(
        negative_log_likelihood,
        x0=[0.0, math.log(initial_scale)],
        method="L-BFGS-B",
        bounds=[(math.log(0.1), math.log(20.0)), (math.log(1e-9), math.log(1e12))],
        options={"maxiter": 10_000, "ftol": 1e-12},
    )
    beta, eta = math.exp(result.x[0]), math.exp(result.x[1])
    return ReliabilityFit(
        shape_beta=Decimal(str(beta)),
        scale_eta_hours=Decimal(str(eta)),
        failures=failures,
        observations=len(exposure),
        converged=bool(result.success),
    )


def _quantile(values: Sequence[Decimal], probability: Decimal) -> Decimal:
    if not values:
        raise ValueError("cannot compute a quantile of no observations")
    ordered = sorted(values)
    position = (len(ordered) - 1) * float(probability)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = Decimal(str(position - lower))
    return ordered[lower] * (Decimal(1) - fraction) + ordered[upper] * fraction


def _profile(
    *,
    profile_type: ProfileType,
    applicability: Mapping[str, str],
    statistics: Mapping[str, Quantity],
    uncertainty: Mapping[str, Quantity],
    sample_support: Mapping[str, Quantity],
    event_ids: Sequence[str],
    as_of: datetime,
    validity: TimeInterval,
    transformation_version: str,
    fallback_level: int = 0,
) -> Profile:
    identity = {
        "type": profile_type,
        "applicability": dict(sorted(applicability.items())),
        "statistics": {key: value.model_dump(mode="json") for key, value in statistics.items()},
        "sample_support": {
            key: value.model_dump(mode="json") for key, value in sample_support.items()
        },
        "events": sorted(event_ids),
        "as_of": as_of,
        "validity": validity.model_dump(mode="json"),
    }
    digest = _digest(identity)
    return Profile(
        profile_id=_stable_id("profile", identity),
        profile_version=1,
        profile_type=profile_type,
        applicability=dict(sorted(applicability.items())),
        statistics=dict(statistics),
        uncertainty=dict(uncertainty),
        sample_support=dict(sample_support),
        fallback_level=fallback_level,
        as_of=as_of,
        validity=validity,
        provenance=Provenance(
            source_system="resource_portfolio.profile_builder",
            source_record_ids=tuple(sorted(event_ids)),
            observed_at=as_of,
            ingested_at=as_of,
            content_sha256=digest,
            transformation_version=transformation_version,
            parent_artifact_ids=tuple(sorted(event_ids)),
        ),
    )


def build_conditional_profiles(
    events: Iterable[OperationalEvent],
    state_intervals: Iterable[StateInterval],
    *,
    as_of: datetime,
    validity: TimeInterval,
    context_dimensions: Sequence[str] = (),
    minimum_exact_support: int = 3,
    transformation_version: str = "resource-profile-builder-1.0",
) -> tuple[Profile, ...]:
    """Build use, productivity, state, and reliability profiles by context.

    Sparse exact groups deterministically fall back to resource type and capability;
    the selected fallback level is recorded in applicability and uncertainty.
    """

    event_list = tuple(events)
    interval_list = tuple(state_intervals)
    groups: dict[tuple[tuple[str, str], ...], list[OperationalEvent]] = defaultdict(list)
    for event in event_list:
        applicability = {
            "domain_id": event.domain_id,
            "resource_type_id": event.resource_type_id,
        }
        if event.capability_id:
            applicability["capability_id"] = event.capability_id
        for dimension in context_dimensions:
            if dimension in event.context:
                applicability[dimension] = str(event.context[dimension])
        groups[tuple(sorted(applicability.items()))].append(event)

    # Pool sparse exact contexts at the broad resource/capability level.
    resolved: dict[tuple[tuple[str, str], ...], list[OperationalEvent]] = defaultdict(list)
    fallback: dict[tuple[tuple[str, str], ...], str] = {}
    for key, members in sorted(groups.items()):
        if len(members) >= minimum_exact_support or not context_dimensions:
            target = key
            fallback[target] = "exact"
        else:
            target = tuple(
                (name, value)
                for name, value in key
                if name in {"domain_id", "resource_type_id", "capability_id"}
            )
            fallback[target] = "resource_type_capability"
        resolved[target].extend(members)

    profiles: list[Profile] = []
    intervals_by_resource: dict[str, list[StateInterval]] = defaultdict(list)
    for interval in interval_list:
        intervals_by_resource[interval.resource_id].append(interval)

    for key, members in sorted(resolved.items()):
        applicability = dict(key)
        fallback_level = 0 if fallback[key] == "exact" else 4
        ids = sorted(event.event_id for event in members)
        durations = [_hours(event.start_timestamp, event.end_timestamp) for event in members]
        total_hours = sum(durations, Decimal(0))
        profiles.append(
            _profile(
                profile_type=ProfileType.USE,
                applicability=applicability,
                statistics={
                    "median_event_hours": Quantity(
                        value=_quantile(durations, Decimal("0.5")), unit="hour"
                    ),
                    "p90_event_hours": Quantity(
                        value=_quantile(durations, Decimal("0.9")), unit="hour"
                    ),
                    "total_observed_hours": Quantity(value=total_hours, unit="hour"),
                },
                uncertainty={
                    "relative_standard_error": Quantity(
                        value=Decimal(1) / Decimal(len(members)).sqrt(), unit="ratio"
                    )
                },
                sample_support={
                    "events": Quantity.model_validate(dict(value=len(members), unit="count"))
                },
                event_ids=ids,
                as_of=as_of,
                validity=validity,
                transformation_version=transformation_version,
                fallback_level=fallback_level,
            )
        )

        productivity: list[Decimal] = []
        output_unit: str | None = None
        for event in members:
            output = event.measurements.get("output")
            productive = event.measurements.get("productive_hours")
            if output is None or productive is None or productive.value <= 0:
                continue
            if productive.unit not in {"hour", "productive_hour"}:
                raise ValueError("productive_hours must use hour or productive_hour")
            if output_unit is not None and output.unit != output_unit:
                raise ValueError("cannot pool productivity outputs with incompatible units")
            output_unit = output.unit
            productivity.append(output.value / productive.value)
        if productivity and output_unit:
            profiles.append(
                _profile(
                    profile_type=ProfileType.PRODUCTIVITY,
                    applicability=applicability,
                    statistics={
                        "median_output_per_productive_hour": Quantity(
                            value=_quantile(productivity, Decimal("0.5")),
                            unit=f"{output_unit}/productive_hour",
                        ),
                        "p90_output_per_productive_hour": Quantity(
                            value=_quantile(productivity, Decimal("0.9")),
                            unit=f"{output_unit}/productive_hour",
                        ),
                    },
                    uncertainty={
                        "relative_standard_error": Quantity(
                            value=Decimal(1) / Decimal(len(productivity)).sqrt(), unit="ratio"
                        )
                    },
                    sample_support={
                        "events": Quantity.model_validate(
                            dict(value=len(productivity), unit="count")
                        )
                    },
                    event_ids=ids,
                    as_of=as_of,
                    validity=validity,
                    transformation_version=transformation_version,
                    fallback_level=fallback_level,
                )
            )

        group_resources = {event.resource_id for event in members}
        group_intervals = [
            interval
            for resource_id in group_resources
            for interval in intervals_by_resource.get(resource_id, ())
        ]
        if group_intervals:
            by_state: dict[CoreStateRole, Decimal] = defaultdict(Decimal)
            for interval in group_intervals:
                by_state[interval.state] += _hours(interval.start_timestamp, interval.end_timestamp)
            state_statistics = {
                f"state_fraction_{state.value}": Quantity(
                    value=hours / sum(by_state.values(), Decimal(0)), unit="ratio"
                )
                for state, hours in sorted(by_state.items(), key=lambda item: item[0].value)
            }
            profiles.append(
                _profile(
                    profile_type=ProfileType.STATE,
                    applicability=applicability,
                    statistics=state_statistics,
                    uncertainty={},
                    sample_support={
                        "intervals": Quantity.model_validate(
                            dict(value=len(group_intervals), unit="count")
                        )
                    },
                    event_ids=ids,
                    as_of=as_of,
                    validity=validity,
                    transformation_version=transformation_version,
                    fallback_level=fallback_level,
                )
            )

        reliability_samples: list[Decimal] = []
        failures: list[bool] = []
        for event in members:
            exposure = event.measurements.get("engine_hours")
            if exposure is None:
                exposure_hours = _hours(event.start_timestamp, event.end_timestamp)
            else:
                if exposure.unit != "hour":
                    raise ValueError("engine_hours must use hour")
                exposure_hours = exposure.value
            reliability_samples.append(exposure_hours)
            failures.append(event.state == CoreStateRole.UNPLANNED_DOWN)
        if reliability_samples:
            fit = fit_weibull_reliability(reliability_samples, failures)
            profiles.append(
                _profile(
                    profile_type=ProfileType.RELIABILITY,
                    applicability=applicability,
                    statistics={
                        "weibull_shape_beta": Quantity(value=fit.shape_beta, unit="ratio"),
                        "weibull_scale_eta": Quantity(value=fit.scale_eta_hours, unit="hour"),
                        "failure_count": Quantity.model_validate(
                            dict(value=fit.failures, unit="count")
                        ),
                    },
                    uncertainty={
                        "fit_converged": Quantity.model_validate(
                            dict(value=int(fit.converged), unit="boolean")
                        )
                    },
                    sample_support={
                        "events": Quantity.model_validate(
                            dict(value=fit.observations, unit="count")
                        )
                    },
                    event_ids=ids,
                    as_of=as_of,
                    validity=validity,
                    transformation_version=transformation_version,
                    fallback_level=fallback_level,
                )
            )
    return tuple(sorted(profiles, key=lambda item: item.profile_id))


class SupplyConstraintStatus(StrEnum):
    UNCONSTRAINED = "unconstrained"
    SUPPLY_CONSTRAINED = "supply_constrained"
    UNRESOLVED = "unresolved"


class LatentDemandEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    delivered: Quantity
    requested_minimum: Quantity | None = None
    output_driven_demand: Quantity | None = None
    latent_demand_lower_bound: Quantity
    shortfall_lower_bound: Quantity
    constraint_status: SupplyConstraintStatus
    corroborating_evidence: tuple[str, ...] = ()
    content_sha256: str

    @model_validator(mode="after")
    def units_match(self) -> "LatentDemandEstimate":
        quantities = (
            self.delivered,
            self.requested_minimum,
            self.output_driven_demand,
            self.latent_demand_lower_bound,
            self.shortfall_lower_bound,
        )
        if any(item is not None and item.unit != self.delivered.unit for item in quantities):
            raise ValueError("all latent-demand quantities must share a unit")
        return self


def estimate_latent_demand_lower_bound(
    *,
    delivered: Quantity,
    requested_minimum: Quantity | None = None,
    planned_output: Quantity | None = None,
    productivity: Quantity | None = None,
    constraint_evidence: Iterable[str] = (),
    ambiguous: bool = False,
) -> LatentDemandEstimate:
    """Reconcile shortage signals as bounds without double-counting corroboration."""

    if delivered.value < 0 or (requested_minimum and requested_minimum.value < 0):
        raise ValueError("demand quantities must be non-negative")
    candidates = [delivered]
    if requested_minimum is not None:
        if requested_minimum.unit != delivered.unit:
            raise ValueError("requested minimum and delivered quantities need matching units")
        candidates.append(requested_minimum)
    output_demand: Quantity | None = None
    if (planned_output is None) != (productivity is None):
        raise ValueError("planned_output and productivity must be supplied together")
    if planned_output is not None and productivity is not None:
        expected_productivity_unit = f"{planned_output.unit}/{delivered.unit}"
        if productivity.unit != expected_productivity_unit or productivity.value <= 0:
            raise ValueError(
                f"productivity must be positive and use {expected_productivity_unit!r}"
            )
        output_demand = Quantity(
            value=planned_output.value / productivity.value, unit=delivered.unit
        )
        candidates.append(output_demand)

    lower_bound_value = max(item.value for item in candidates)
    evidence = tuple(sorted(set(constraint_evidence)))
    if ambiguous:
        status = SupplyConstraintStatus.UNRESOLVED
    elif evidence:
        status = SupplyConstraintStatus.SUPPLY_CONSTRAINED
    else:
        status = SupplyConstraintStatus.UNCONSTRAINED
    payload = {
        "delivered": delivered.model_dump(mode="json"),
        "requested_minimum": (
            requested_minimum.model_dump(mode="json") if requested_minimum else None
        ),
        "output_driven_demand": output_demand.model_dump(mode="json") if output_demand else None,
        "lower_bound": str(lower_bound_value),
        "status": status,
        "evidence": evidence,
    }
    return LatentDemandEstimate(
        delivered=delivered,
        requested_minimum=requested_minimum,
        output_driven_demand=output_demand,
        latent_demand_lower_bound=Quantity(value=lower_bound_value, unit=delivered.unit),
        shortfall_lower_bound=Quantity(
            value=lower_bound_value - delivered.value, unit=delivered.unit
        ),
        constraint_status=status,
        corroborating_evidence=evidence,
        content_sha256=_digest(payload),
    )
