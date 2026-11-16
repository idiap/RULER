# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Seeded synthetic inputs for deterministic resource-portfolio experiments.

The generator creates complete workflow input directories.  It does not call a
language model and does not copy the packaged reference fixture.  Every value,
identifier and provenance digest is derived from the validated configuration.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from ruler.applications.resource_portfolio.compiler import CompilationRequest
from ruler.applications.resource_portfolio.explanations import ExplanationDriver
from ruler.applications.resource_portfolio.robustness import (
    CounterfactualChange,
    ScenarioSet,
)
from ruler.applications.resource_portfolio.scheduling import SchedulingProblem
from ruler.applications.resource_portfolio.workflow import (
    INPUT_FILENAMES,
    build_evidence_snapshot,
)
from ruler.contracts.common import StrictContract, validate_sha256
from ruler.io import read_yaml, stable_hash, write_yaml

GENERATOR_VERSION = "resource-portfolio-synthetic/v1"


class SyntheticPortfolioConfig(StrictContract):
    """Bounded controls for a reproducible synthetic portfolio data set."""

    schema_version: Literal["resource-portfolio-synthetic-config/v1"] = (
        "resource-portfolio-synthetic-config/v1"
    )
    seed: int = 23
    dataset_id: str = "synthetic-construction-fleet"
    base_timestamp: datetime = datetime(2026, 1, 5, tzinfo=UTC)
    resource_count: int = Field(default=4, ge=1, le=500)
    event_days: int = Field(default=3, ge=1, le=90)
    events_per_resource_per_day: int = Field(default=3, ge=1, le=12)
    tasks_per_resource: int = Field(default=2, ge=1, le=20)
    scenario_count: int = Field(default=3, ge=1, le=100)
    anomaly_rate: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    duplicate_rate: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    correction_rate: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    model_variant: Literal["feasible", "infeasible"] = "feasible"
    demand_ratio: Decimal = Field(default=Decimal("0.80"), gt=0, le=2)
    time_limit_seconds: float = Field(default=10.0, gt=0, le=300)

    @model_validator(mode="after")
    def bounded_workflow_size(self) -> "SyntheticPortfolioConfig":
        if self.resource_count * self.tasks_per_resource > 10_000:
            raise ValueError("synthetic schedule exceeds 10,000 tasks")
        return self


class SyntheticCounterfactualSpec(StrictContract):
    counterfactual_id: str
    condition: str
    changed_action: str
    changes: tuple[CounterfactualChange, ...] = Field(min_length=1)


class SyntheticWorkflowModelConfig(StrictContract):
    seed: int
    threads: Literal[1] = 1
    time_limit_seconds: float = Field(gt=0, le=300)
    counterfactual: SyntheticCounterfactualSpec


class SyntheticExplanationInput(StrictContract):
    recommendation_id: str
    action: str
    target_id: str
    drivers: tuple[ExplanationDriver, ...] = Field(min_length=1)
    caveats: tuple[str, ...] = Field(min_length=1)
    required_reviewer_role: str


class SyntheticDatasetManifest(StrictContract):
    schema_version: Literal["resource-portfolio-synthetic-manifest/v1"] = (
        "resource-portfolio-synthetic-manifest/v1"
    )
    dataset_id: str
    generator_version: Literal["resource-portfolio-synthetic/v1"] = GENERATOR_VERSION
    seed: int
    model_variant: Literal["feasible", "infeasible"]
    configuration_sha256: str
    file_digests: dict[str, str]
    resource_count: int
    base_event_count: int
    emitted_event_count: int
    duplicate_count: int
    correction_count: int
    anomaly_count: int
    task_count: int
    scenario_count: int
    expected_compilation_status: Literal["sat", "unsat"]
    content_sha256: str

    @model_validator(mode="after")
    def validate_hashes(self) -> "SyntheticDatasetManifest":
        validate_sha256(self.configuration_sha256)
        validate_sha256(self.content_sha256)
        for digest in self.file_digests.values():
            validate_sha256(digest)
        unsigned = self.model_dump(mode="json", exclude={"content_sha256"})
        if stable_hash(unsigned) != self.content_sha256:
            raise ValueError("synthetic manifest digest mismatch")
        return self


def _timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("base_timestamp must be timezone-aware")
    return value.astimezone(UTC).replace(microsecond=0)


def _provenance(
    config: SyntheticPortfolioConfig,
    record_id: str,
    observed_at: datetime,
    payload: Any,
    *,
    ingest_offset_minutes: int = 5,
) -> dict[str, Any]:
    return {
        "source_system": "ruler_synthetic_generator",
        "source_record_ids": [record_id],
        "observed_at": observed_at.isoformat(),
        "ingested_at": (observed_at + timedelta(minutes=ingest_offset_minutes)).isoformat(),
        "content_sha256": stable_hash(
            {
                "generator": GENERATOR_VERSION,
                "seed": config.seed,
                "record": record_id,
                "payload": payload,
            }
        ),
        "transformation_version": GENERATOR_VERSION,
    }


def _quantity(value: Decimal | int | str, unit: str) -> dict[str, str]:
    return {"value": str(value), "unit": unit}


def _build_evidence(
    config: SyntheticPortfolioConfig, rng: random.Random
) -> tuple[dict[str, Any], dict[str, int]]:
    base = _timestamp(config.base_timestamp)
    horizon_end = base + timedelta(days=config.event_days)
    as_of = horizon_end + timedelta(days=1)
    created_at = as_of + timedelta(hours=1)
    validity = {
        "start": (base - timedelta(days=30)).isoformat(),
        "end": (as_of + timedelta(days=365)).isoformat(),
    }
    location_id = "synthetic_site"
    capability_id = "standard_excavation"
    resource_type_id = "synthetic_excavator"

    resources: list[dict[str, Any]] = []
    work_units: list[dict[str, Any]] = []
    activities: list[dict[str, Any]] = []
    requirements: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    duplicate_count = correction_count = anomaly_count = 0

    for resource_index in range(config.resource_count):
        resource_id = f"syn_ex_{resource_index + 1:04d}"
        record_id = f"resource:{resource_id}"
        resources.append(
            {
                "resource_id": resource_id,
                "resource_type_id": resource_type_id,
                "owner_id": "synthetic_owner",
                "state": "ready",
                "location_id": location_id,
                "capability_ids": [capability_id],
                "attributes": {"safety_eligibility": "eligible", "synthetic": "true"},
                "validity": validity,
                "as_of": as_of.isoformat(),
                "provenance": _provenance(
                    config, record_id, base, {"resource_index": resource_index}
                ),
            }
        )
        for task_index in range(config.tasks_per_resource):
            ordinal = resource_index * config.tasks_per_resource + task_index + 1
            work_unit_id = f"syn_work_{ordinal:05d}"
            activity_id = f"syn_activity_{ordinal:05d}"
            window_start = base + timedelta(hours=task_index)
            window_end = horizon_end
            work_units.append(
                {
                    "work_unit_id": work_unit_id,
                    "work_unit_type": "earthworks",
                    "location_id": location_id,
                    "priority": "normal",
                    "time_window": {
                        "start": window_start.isoformat(),
                        "end": window_end.isoformat(),
                    },
                    "attributes": {"synthetic_resource_hint": resource_id},
                    "provenance": _provenance(
                        config, f"work:{work_unit_id}", base, {"ordinal": ordinal}
                    ),
                }
            )
            activities.append(
                {
                    "activity_id": activity_id,
                    "work_unit_id": work_unit_id,
                    "activity_type": "excavation",
                    "time_window": {
                        "start": window_start.isoformat(),
                        "end": window_end.isoformat(),
                    },
                    "duration": _quantity(1, "hour"),
                    "predecessor_activity_ids": [],
                    "provenance": _provenance(
                        config, f"activity:{activity_id}", base, {"ordinal": ordinal}
                    ),
                }
            )
            requirements.append(
                {
                    "requirement_id": f"syn_requirement_{ordinal:05d}",
                    "work_unit_id": work_unit_id,
                    "activity_id": activity_id,
                    "capability_id": capability_id,
                    "quantity": _quantity(1, "productive_hour"),
                    "period": {"start": window_start.isoformat(), "end": window_end.isoformat()},
                    "criticality": "normal",
                    "source_type": "synthetic_reviewed_requirement",
                    "confidence": _quantity("0.95", "ratio"),
                    "provenance": _provenance(
                        config, f"requirement:{ordinal}", base, {"ordinal": ordinal}
                    ),
                }
            )

        for day in range(config.event_days):
            for slot in range(config.events_per_resource_per_day):
                event_number = day * config.events_per_resource_per_day + slot
                start = base + timedelta(days=day, hours=slot * 2)
                end = start + timedelta(hours=1)
                event_id = f"{resource_id}:event:{event_number:04d}"
                source_event_id = f"telemetry:{resource_id}:{event_number:04d}"
                state = "unplanned_down" if rng.random() < 0.12 else "productive"
                productive = Decimal(0) if state == "unplanned_down" else Decimal(1)
                output = (
                    Decimal(0) if not productive else Decimal(str(round(rng.uniform(36, 64), 3)))
                )
                payload = {
                    "resource": resource_id,
                    "start": start.isoformat(),
                    "state": state,
                    "output": str(output),
                }
                event = {
                    "event_id": event_id,
                    "domain_id": "construction_fleet",
                    "resource_id": resource_id,
                    "resource_type_id": resource_type_id,
                    "capability_id": capability_id,
                    "location_id": location_id,
                    "start_timestamp": start.isoformat(),
                    "end_timestamp": end.isoformat(),
                    "state": state,
                    "measurements": {
                        "productive_hours": _quantity(productive, "hour"),
                        "engine_hours": _quantity(1, "hour"),
                        "output": _quantity(output, "m3"),
                    },
                    "context": {"work_phase": "earthworks", "synthetic": "true"},
                    "source_event_id": source_event_id,
                    "quality": {
                        "status": "accepted",
                        "confidence": _quantity("0.97", "ratio"),
                    },
                    "provenance": _provenance(config, source_event_id, start, payload),
                }
                events.append(event)

                if rng.random() < float(config.duplicate_rate):
                    duplicate_count += 1
                    duplicate = {
                        **event,
                        "event_id": f"{event_id}:duplicate",
                        "provenance": {
                            **event["provenance"],
                            "ingested_at": (start + timedelta(minutes=6)).isoformat(),
                        },
                    }
                    events.append(duplicate)
                if rng.random() < float(config.correction_rate):
                    correction_count += 1
                    corrected_output = output + Decimal("1.25") if productive else output
                    correction_payload = {
                        **payload,
                        "output": str(corrected_output),
                        "correction": True,
                    }
                    correction = {
                        **event,
                        "event_id": f"{event_id}:correction",
                        "measurements": {
                            **event["measurements"],
                            "output": _quantity(corrected_output, "m3"),
                        },
                        "correction_of_event_id": event_id,
                        "provenance": _provenance(
                            config,
                            source_event_id,
                            start,
                            correction_payload,
                            ingest_offset_minutes=7,
                        ),
                    }
                    events.append(correction)
                if rng.random() < float(config.anomaly_rate):
                    anomaly_count += 1
                    anomaly_id = f"{event_id}:overlap"
                    anomaly_start = start + timedelta(minutes=30)
                    events.append(
                        {
                            **event,
                            "event_id": anomaly_id,
                            "source_event_id": f"anomaly:{source_event_id}",
                            "start_timestamp": anomaly_start.isoformat(),
                            "end_timestamp": (end + timedelta(minutes=30)).isoformat(),
                            "state": "unplanned_down",
                            "measurements": {
                                "productive_hours": _quantity(0, "hour"),
                                "engine_hours": _quantity(1, "hour"),
                                "output": _quantity(0, "m3"),
                            },
                            "quality": {
                                "status": "suspect",
                                "confidence": _quantity("0.60", "ratio"),
                                "flags": ["synthetic_overlap_anomaly"],
                            },
                            "provenance": _provenance(
                                config,
                                f"anomaly:{source_event_id}",
                                anomaly_start,
                                {"parent": event_id, "kind": "overlap"},
                            ),
                        }
                    )

    static_observed = base
    evidence = {
        "domain_id": "construction_fleet",
        "domain_package_id": "construction-fleet-1.0.0",
        "as_of": as_of.isoformat(),
        "created_at": created_at.isoformat(),
        "scope_start": base.isoformat(),
        "scope_end": horizon_end.isoformat(),
        "profile_validity": {
            "start": as_of.isoformat(),
            "end": (as_of + timedelta(days=180)).isoformat(),
        },
        "profile_context_dimensions": ["work_phase"],
        "minimum_exact_profile_support": 3,
        "currency_unit": "CHF",
        "watermarks": {"operational_events": as_of.isoformat()},
        "safety_critical_capability_ids": [capability_id],
        "normalization": {},
        "unit_definitions": [
            {"unit_id": "CHF", "dimension": "currency"},
            {"unit_id": "boolean", "dimension": "boolean"},
            {"unit_id": "count", "dimension": "count"},
            {"unit_id": "hour", "dimension": "time"},
            {"unit_id": "m3", "dimension": "volume"},
            {"unit_id": "m3/productive_hour", "dimension": "productivity"},
            {"unit_id": "productive_hour", "dimension": "time"},
            {"unit_id": "ratio", "dimension": "dimensionless"},
        ],
        "locations": [
            {
                "location_id": location_id,
                "location_type": "work_site",
                "region": "SYNTHETIC",
                "validity": validity,
                "provenance": _provenance(
                    config, f"location:{location_id}", static_observed, location_id
                ),
            }
        ],
        "capabilities": [
            {
                "capability_id": capability_id,
                "output_unit": "productive_hour",
                "validity": validity,
                "provenance": _provenance(
                    config, f"capability:{capability_id}", static_observed, capability_id
                ),
            }
        ],
        "resource_types": [
            {
                "resource_type_id": resource_type_id,
                "taxonomy_path": ["mobile_resource", "excavation_resource", "synthetic"],
                "default_capability_ids": [capability_id],
                "validity": validity,
                "provenance": _provenance(
                    config, f"resource_type:{resource_type_id}", static_observed, resource_type_id
                ),
            }
        ],
        "resources": resources,
        "configurations": [],
        "work_units": work_units,
        "activities": activities,
        "requirements": requirements,
        "external_offers": [],
        "profiles": [],
        "rules": [],
        "scenarios": [],
        "events": events,
    }
    return evidence, {
        "base_event_count": config.resource_count
        * config.event_days
        * config.events_per_resource_per_day,
        "emitted_event_count": len(events),
        "duplicate_count": duplicate_count,
        "correction_count": correction_count,
        "anomaly_count": anomaly_count,
    }


def _build_compile(config: SyntheticPortfolioConfig) -> dict[str, Any]:
    variables = [
        {
            "variable_id": f"owned_{index + 1:04d}",
            "domain": "binary",
            "lower_bound": 0,
            "upper_bound": 1,
            "unit": "unit",
            "origin_refs": [f"resource:syn_ex_{index + 1:04d}"],
        }
        for index in range(config.resource_count)
    ]
    variables.append(
        {
            "variable_id": "rental_units",
            "domain": "integer",
            "lower_bound": 0,
            "upper_bound": config.resource_count,
            "unit": "unit",
            "origin_refs": ["synthetic_external_supply"],
        }
    )
    total_upper = config.resource_count * 2
    demand = (
        total_upper + 1
        if config.model_variant == "infeasible"
        else max(1, int(config.resource_count * float(config.demand_ratio)))
    )
    coefficients = {item["variable_id"]: 1 for item in variables}
    terms = [
        {"variable_id": item["variable_id"], "coefficient": 2 + (index % 3)}
        for index, item in enumerate(variables[:-1])
    ]
    terms.append({"variable_id": "rental_units", "coefficient": 7})
    return {
        "problem_id": f"{config.dataset_id}-{config.model_variant}",
        "snapshot_digest": "sha256:" + "0" * 64,
        "variables": variables,
        "rules": [
            {
                "rule_id": "synthetic_minimum_capacity",
                "version": "1.0",
                "status": "approved",
                "authority_ref": "synthetic:reviewed_capacity_policy",
                "constraint_id": "capacity",
                "coefficients": coefficients,
                "sense": ">=",
                "rhs": demand,
                "unit": "unit",
                "hard": True,
                "evidence_refs": ["synthetic:requirements"],
            },
            {
                "rule_id": "synthetic_unapproved_candidate",
                "version": "0.1",
                "status": "candidate",
                "authority_ref": "candidate:autoformalization",
                "constraint_id": "candidate_rental_preference",
                "coefficients": {"rental_units": 1},
                "sense": "<=",
                "rhs": 0,
                "unit": "unit",
                "hard": True,
                "evidence_refs": ["synthetic:candidate_only"],
            },
        ],
        "objectives": [
            {
                "objective_id": "lifecycle_cost",
                "expression": {"terms": terms, "constant": 0},
                "sense": "minimize",
                "priority": 0,
                "unit": "CHF",
                "component": "lifecycle",
                "origin_refs": ["synthetic:cost_model"],
            }
        ],
        "metadata": {
            "fixture": "deterministically_generated",
            "dataset_id": config.dataset_id,
            "model_variant": config.model_variant,
        },
    }


def _build_schedule(config: SyntheticPortfolioConfig) -> dict[str, Any]:
    resource_ids = [f"syn_ex_{index + 1:04d}" for index in range(config.resource_count)]
    tasks = []
    ordinal = 0
    for resource_index, resource_id in enumerate(resource_ids):
        for task_index in range(config.tasks_per_resource):
            ordinal += 1
            tasks.append(
                {
                    "task_id": f"syn_task_{ordinal:05d}",
                    "duration": 1,
                    "earliest_start": task_index,
                    "latest_end": config.tasks_per_resource,
                    "eligible_resource_ids": [resource_id],
                    "required_capability_ids": ["standard_excavation"],
                    "allowed_location_ids": ["synthetic_site"],
                    "optional": False,
                    "origin_refs": [f"work_unit:syn_work_{ordinal:05d}"],
                }
            )
    return {
        "schema_version": "resource-scheduling/v1",
        "schedule_id": f"{config.dataset_id}-schedule",
        "plan_digest": "sha256:" + "0" * 64,
        "time_unit": "hour",
        "tasks": tasks,
        "precedences": [],
        "travel_time": {},
        "resource_capability_ids": {
            resource_id: ["standard_excavation"] for resource_id in resource_ids
        },
        "resource_location_ids": {resource_id: "synthetic_site" for resource_id in resource_ids},
        "capacity_limits": {},
        "frozen_assignments": [],
    }


def _build_stress(config: SyntheticPortfolioConfig, rng: random.Random) -> dict[str, Any]:
    probability = Decimal(1) / Decimal(config.scenario_count)
    remaining = Decimal(1)
    scenarios = []
    for index in range(config.scenario_count):
        current = remaining if index == config.scenario_count - 1 else probability
        remaining -= current
        multiplier = Decimal(str(round(rng.uniform(0.75, 1.15), 6)))
        scenarios.append(
            {
                "scenario_id": f"synthetic_scenario_{index + 1:04d}",
                "probability": str(current),
                "information_set": "initial",
                "parameter_multipliers": {"constraint_rhs:capacity": str(multiplier)},
                "assumption_refs": ["synthetic:demand_distribution"],
            }
        )
    return {
        "schema_version": "resource-scenarios/v1",
        "scenario_set_id": f"{config.dataset_id}-stress",
        "seed": config.seed,
        "scenarios": scenarios,
    }


def generate_synthetic_portfolio_inputs(
    config: SyntheticPortfolioConfig,
) -> tuple[dict[str, dict[str, Any]], SyntheticDatasetManifest]:
    """Generate and type-check all six workflow input payloads in memory."""
    rng = random.Random(config.seed)
    evidence, counts = _build_evidence(config, rng)
    compilation = _build_compile(config)
    schedule = _build_schedule(config)
    stress = _build_stress(config, rng)
    demand = int(compilation["rules"][0]["rhs"])
    model = SyntheticWorkflowModelConfig(
        seed=config.seed,
        time_limit_seconds=config.time_limit_seconds,
        counterfactual=SyntheticCounterfactualSpec(
            counterfactual_id="synthetic_demand_increment",
            condition="Required capacity increases by one unit",
            changed_action="Reserve one additional external unit",
            changes=(
                CounterfactualChange(
                    kind="constraint_rhs", target_id="capacity", value=Decimal(demand + 1)
                ),
            ),
        ),
    ).model_dump(mode="json")
    explanation = SyntheticExplanationInput(
        recommendation_id="synthetic_capacity_plan",
        action="RETAIN",
        target_id="owned_0001",
        drivers=(
            ExplanationDriver(
                driver_id="synthetic_required_capacity",
                kind="constraint",
                statement="The reviewed synthetic capacity requirement bounds the portfolio",
                trace_refs=("constraint:capacity",),
            ),
        ),
        caveats=(
            "Inputs are deterministic synthetic evidence",
            "The plan remains advisory until human approval",
        ),
        required_reviewer_role="synthetic_fleet_reviewer",
    ).model_dump(mode="json")
    payloads = {
        "evidence.yaml": evidence,
        "compile.yaml": compilation,
        "model.yaml": model,
        "schedule.yaml": schedule,
        "stress.yaml": stress,
        "explanation.yaml": explanation,
    }

    # Fail before writing if any generated structure violates a runtime contract.
    build_evidence_snapshot(evidence)
    CompilationRequest.model_validate(compilation)
    SchedulingProblem.model_validate(schedule)
    ScenarioSet.model_validate(stress)
    SyntheticWorkflowModelConfig.model_validate(model)
    SyntheticExplanationInput.model_validate(explanation)

    file_digests = {name: stable_hash(payload) for name, payload in payloads.items()}
    unsigned_manifest = {
        "schema_version": "resource-portfolio-synthetic-manifest/v1",
        "dataset_id": config.dataset_id,
        "generator_version": GENERATOR_VERSION,
        "seed": config.seed,
        "model_variant": config.model_variant,
        "configuration_sha256": stable_hash(config.model_dump(mode="json")),
        "file_digests": file_digests,
        "resource_count": config.resource_count,
        **counts,
        "task_count": config.resource_count * config.tasks_per_resource,
        "scenario_count": config.scenario_count,
        "expected_compilation_status": "sat" if config.model_variant == "feasible" else "unsat",
    }
    manifest = SyntheticDatasetManifest(
        **unsigned_manifest,
        content_sha256=stable_hash(unsigned_manifest),
    )
    return payloads, manifest


def write_synthetic_portfolio_inputs(
    config: SyntheticPortfolioConfig,
    output_dir: Path,
    *,
    overwrite: bool = False,
) -> SyntheticDatasetManifest:
    """Write one complete generated input directory after full in-memory validation."""
    payloads, manifest = generate_synthetic_portfolio_inputs(config)
    targets = [output_dir / name for name in (*INPUT_FILENAMES, "synthetic_manifest.yaml")]
    conflicts = [path for path in targets if path.exists()]
    if conflicts and not overwrite:
        raise FileExistsError(f"synthetic output already exists: {conflicts[0]}")
    for name in INPUT_FILENAMES:
        write_yaml(output_dir / name, payloads[name])
    write_yaml(output_dir / "synthetic_manifest.yaml", manifest.model_dump(mode="json"))
    return manifest


def verify_synthetic_portfolio_inputs(input_dir: Path) -> SyntheticDatasetManifest:
    """Verify the manifest and revalidate all generated runtime input contracts."""
    manifest = SyntheticDatasetManifest.model_validate(
        read_yaml(input_dir / "synthetic_manifest.yaml")
    )
    payloads: dict[str, dict[str, Any]] = {}
    for name in INPUT_FILENAMES:
        payload = read_yaml(input_dir / name)
        if not isinstance(payload, dict):
            raise ValueError(f"synthetic input {name} must be a mapping")
        if stable_hash(payload) != manifest.file_digests.get(name):
            raise ValueError(f"synthetic input digest mismatch: {name}")
        payloads[name] = payload
    build_evidence_snapshot(payloads["evidence.yaml"])
    CompilationRequest.model_validate(payloads["compile.yaml"])
    SchedulingProblem.model_validate(payloads["schedule.yaml"])
    ScenarioSet.model_validate(payloads["stress.yaml"])
    SyntheticWorkflowModelConfig.model_validate(payloads["model.yaml"])
    SyntheticExplanationInput.model_validate(payloads["explanation.yaml"])
    return manifest


def load_synthetic_config(path: Path) -> SyntheticPortfolioConfig:
    """Load a strict synthetic generation configuration from YAML."""
    return SyntheticPortfolioConfig.model_validate(read_yaml(path))


__all__ = [
    "GENERATOR_VERSION",
    "SyntheticCounterfactualSpec",
    "SyntheticDatasetManifest",
    "SyntheticExplanationInput",
    "SyntheticPortfolioConfig",
    "SyntheticWorkflowModelConfig",
    "generate_synthetic_portfolio_inputs",
    "load_synthetic_config",
    "verify_synthetic_portfolio_inputs",
    "write_synthetic_portfolio_inputs",
]
