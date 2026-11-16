# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Grounded synthetic dossier-to-optimization demonstration composition root."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ruler.applications.resource_portfolio.compiler import CompilationRequest
from ruler.applications.resource_portfolio.argumentation import (
    build_decision_argument_certificate,
)
from ruler.applications.resource_portfolio.demonstrator_formalization import (
    DemonstratorFormalizationRun,
    DemonstratorRefinementError,
    run_demonstrator_autoformalization,
)
from ruler.applications.resource_portfolio.demonstrator_approved_kb import (
    write_approved_formal_kb,
)
from ruler.applications.resource_portfolio.demonstrator_grounding import (
    ApprovedRuleGrounding,
    ObjectiveConstantGrounding,
    ObjectiveTermGrounding,
    ReviewerApproval,
    ScheduleTaskGrounding,
    build_demonstrator_grounding,
    exact_grounding_span,
)
from ruler.applications.resource_portfolio.explanations import (
    PortfolioExplanation,
    PortfolioExplanationEvidence,
    generate_explanation,
)
from ruler.applications.resource_portfolio.explanation_records import (
    CoverageExclusion,
    ScenarioCoverageDeclaration,
    build_cost_objective_explanation,
    build_scenario_envelope_explanation,
)
from ruler.applications.resource_portfolio.scheduling import SchedulingProblem
from ruler.applications.resource_portfolio.compiler import CompilationReport
from ruler.applications.resource_portfolio.optimization import VerifiedPlan
from ruler.applications.resource_portfolio.robustness import (
    CounterfactualChange,
    CounterfactualRun,
    ScenarioSet,
    StressReport,
)
from ruler.applications.resource_portfolio.synthetic import (
    SyntheticPortfolioConfig,
    generate_synthetic_portfolio_inputs,
)
from ruler.applications.resource_portfolio.workflow import (
    INPUT_FILENAMES,
    execute_resource_portfolio_workflow,
    verify_workflow_artifacts,
)
from ruler.interfaces.resource_portfolio_demonstrator import (
    write_resource_portfolio_demonstrator_report,
)
from ruler.interfaces.autoformalization_visualizer import (
    build_autoformalization_visualization,
    write_autoformalization_visualizer_artifact,
)
from ruler.io import read_yaml, stable_hash, write_text, write_yaml
from ruler.kb.generative_autoformalization import CodexExecTransport

SOURCE_ID = "data/domains/construction_fleet/demonstrator/alpine_station_expansion_dossier.md"


def _demonstrator_inputs() -> dict[str, dict[str, Any]]:
    """Build realistic typed inputs from the reusable seeded generator."""
    payloads, _ = generate_synthetic_portfolio_inputs(
        SyntheticPortfolioConfig.model_validate(
            dict(
                seed=20260903,
                dataset_id="alpine-station-expansion-synthetic",
                base_timestamp=datetime.fromisoformat("2026-09-07T06:00:00+00:00"),
                resource_count=4,
                event_days=2,
                events_per_resource_per_day=3,
                tasks_per_resource=1,
                scenario_count=3,
                anomaly_rate="0.08",
                duplicate_rate="0.08",
                correction_rate="0.08",
            )
        )
    )
    values = deepcopy(payloads)
    evidence = values["evidence.yaml"]
    resource_map = {
        "syn_ex_0001": ("excavator_atlas_35t", "rock_excavation", "AlpineBuild"),
        "syn_ex_0002": ("excavator_brenta_22t", "standard_excavation", "AlpineBuild"),
        "syn_ex_0003": ("truck_cervo_adt", "haulage", "AlpineBuild"),
        "syn_ex_0004": ("rental_ibex_35t", "rock_excavation", "Helvetic Plant"),
    }
    for resource in evidence["resources"]:
        old_id = resource["resource_id"]
        new_id, capability, owner = resource_map[old_id]
        resource["resource_id"] = new_id
        resource["owner_id"] = owner.lower().replace(" ", "_")
        resource["capability_ids"] = [capability]
        resource["attributes"] = {
            **resource["attributes"],
            "display_name": new_id,
            "portfolio_role": "external_backup" if old_id == "syn_ex_0004" else "owned",
        }
    for event in evidence["events"]:
        new_id, capability, _ = resource_map[event["resource_id"]]
        event["resource_id"] = new_id
        event["capability_id"] = capability
    for work in evidence["work_units"]:
        hint = work.get("attributes", {}).get("synthetic_resource_hint")
        if hint in resource_map:
            work["attributes"]["synthetic_resource_hint"] = resource_map[hint][0]
    base_capability = evidence["capabilities"][0]
    evidence["capabilities"] = [
        {
            **deepcopy(base_capability),
            "capability_id": capability,
            "provenance": {
                **deepcopy(base_capability["provenance"]),
                "source_record_ids": [f"capability:{capability}"],
                "content_sha256": stable_hash({"synthetic_capability": capability}),
            },
        }
        for capability in ("rock_excavation", "standard_excavation", "haulage")
    ]

    values["compile.yaml"] = {
        "problem_id": "alpinebuild-annual-portfolio-2027",
        "snapshot_digest": "sha256:" + "0" * 64,
        "variables": [
            {
                "variable_id": variable,
                "domain": "binary",
                "lower_bound": 0,
                "upper_bound": 1,
                "unit": "unit",
                "origin_refs": [f"resource:{resource}"],
            }
            for variable, resource in (
                ("retain_atlas", "excavator_atlas_35t"),
                ("retain_brenta", "excavator_brenta_22t"),
                ("retain_cervo", "truck_cervo_adt"),
                ("reserve_ibex", "rental_ibex_35t"),
            )
        ],
        "rules": [
            _rule(
                "rock_primary",
                {"retain_atlas": 936, "reserve_ibex": 936},
                936,
                unit="productive_hour",
            ),
            _rule("rock_backup", {"retain_atlas": 1, "reserve_ibex": 1}, 2),
            _rule(
                "standard_excavation",
                {"retain_brenta": 624},
                624,
                unit="productive_hour",
            ),
            _rule(
                "haulage",
                {"retain_cervo": 1248},
                1248,
                unit="productive_hour",
            ),
            {
                **_rule("generated_release_preference", {"retain_atlas": 1}, 0, sense="<="),
                "status": "candidate",
                "version": "0.1",
                "authority_ref": "candidate:autoformalization",
                "evidence_refs": ["candidate:unapproved"],
            },
        ],
        "objectives": [
            {
                "objective_id": "verified_annual_cost",
                "expression": {
                    "terms": [
                        {"variable_id": "retain_atlas", "coefficient": 265200},
                        {"variable_id": "retain_brenta", "coefficient": 166400},
                        {"variable_id": "retain_cervo", "coefficient": 140400},
                        {"variable_id": "reserve_ibex", "coefficient": 358800},
                    ],
                    "constant": 171600,
                },
                "sense": "minimize",
                "priority": 0,
                "unit": "CHF",
                "component": "lifecycle",
                "origin_refs": ["reviewed:commercial_observations"],
            }
        ],
        "metadata": {"synthetic": "true", "projection": "reviewer_approved_v1"},
    }
    values["schedule.yaml"] = {
        "schema_version": "resource-scheduling/v1",
        "schedule_id": "alpinebuild-enterprise-annual-2027",
        "plan_digest": "sha256:" + "0" * 64,
        "time_unit": "working_day",
        "tasks": list(_enterprise_schedule_tasks().values()),
        "precedences": [
            _precedence("alpine_mobilize_breaker", "alpine_rock_bench_cut"),
            _precedence("alpine_rock_bench_cut", "alpine_rock_trim"),
            _precedence("alpine_rock_trim", "alpine_final_haul"),
            _precedence("northpark_environmental_strip", "northpark_bulk_grade"),
            _precedence("northpark_bulk_grade", "northpark_utility_trench"),
            _precedence("northpark_utility_trench", "northpark_stormwater"),
            _precedence("northpark_stormwater", "northpark_subbase"),
            _precedence("northpark_subbase", "northpark_handover_survey"),
            _precedence("rivergate_setout", "rivergate_access_platform"),
            _precedence("rivergate_access_platform", "rivergate_cofferdam"),
            _precedence("rivergate_cofferdam", "rivergate_foundation_excavation"),
            _precedence("rivergate_foundation_excavation", "rivergate_backfill"),
            _precedence("rivergate_backfill", "rivergate_demobilize"),
            _precedence("windroad_rock_cut", "windroad_culvert"),
            _precedence("windroad_culvert", "windroad_aggregate_haul"),
            _precedence("windroad_aggregate_haul", "windroad_crane_pad"),
            _precedence("windroad_crane_pad", "windroad_laydown_lift"),
            _precedence("windroad_laydown_lift", "windroad_finish_grade"),
            _precedence("lakeview_setout", "lakeview_bulk_excavation"),
            _precedence("lakeview_bulk_excavation", "lakeview_foundation_drainage"),
            _precedence("lakeview_foundation_drainage", "lakeview_crane_base"),
            _precedence("lakeview_crane_base", "lakeview_handover_survey"),
        ],
        "travel_time": {
            "alpine_drainage_trench->northpark_utility_trench": 2,
            "alpine_spoil_removal->windroad_aggregate_haul": 3,
            "northpark_bulk_grade->rivergate_access_platform": 2,
            "rivergate_access_platform->northpark_subbase": 2,
            "windroad_rock_cut->rivergate_cofferdam": 3,
            "rivergate_cofferdam->rivergate_foundation_excavation": 0,
            "rivergate_foundation_excavation->rivergate_backfill": 0,
            "northpark_stormwater->lakeview_foundation_drainage": 2,
            "lakeview_bulk_excavation->alpine_rock_trim": 3,
            "lakeview_crane_base->windroad_crane_pad": 3,
        },
        "resource_capability_ids": {
            "excavator_atlas_35t": ["rock_excavation"],
            "excavator_brenta_22t": ["standard_excavation"],
            "rental_ibex_35t": ["rock_excavation"],
            "truck_cervo_adt": ["haulage"],
            "excavator_dolomite_30t": ["rock_excavation", "standard_excavation"],
            "excavator_eiger_25t": ["rock_excavation", "standard_excavation"],
            "truck_furka_adt": ["haulage"],
            "truck_gotthard_adt": ["haulage"],
            "dozer_jura_d6": ["earthmoving"],
            "dozer_matterhorn_d7": ["earthmoving"],
            "crane_limmat_60t": ["lifting"],
            "service_van_rhone": ["field_service"],
            "survey_crew_alpha": ["surveying"],
        },
        "resource_location_ids": {},
        "capacity_limits": {
            "site_supervision": 4,
            "heavy_haul_dispatch": 2,
            "field_mechanics": 1,
        },
        "frozen_assignments": [
            {"task_id": "rivergate_setout", "resource_id": "survey_crew_alpha", "start": 5},
            {"task_id": "alpine_rock_bench_cut", "resource_id": "excavator_atlas_35t", "start": 46},
            {
                "task_id": "depot_atlas_midyear_service",
                "resource_id": "service_van_rhone",
                "start": 124,
            },
            {
                "task_id": "lakeview_bulk_excavation",
                "resource_id": "excavator_brenta_22t",
                "start": 146,
            },
            {"task_id": "windroad_laydown_lift", "resource_id": "crane_limmat_60t", "start": 240},
            {
                "task_id": "depot_year_end_inspections",
                "resource_id": "service_van_rhone",
                "start": 246,
            },
        ],
    }
    values["stress.yaml"] = {
        "schema_version": "resource-scenarios/v1",
        "scenario_set_id": "alpine-station-commercial-stress",
        "seed": 20260903,
        "scenarios": [
            {
                "scenario_id": "quoted_rate",
                "probability": "0.50",
                "information_set": "initial",
                "parameter_multipliers": {
                    "objective_term:verified_annual_cost:reserve_ibex": "1.00"
                },
                "assumption_refs": ["dossier:helvetic_quote"],
            },
            {
                "scenario_id": "rental_scarcity",
                "probability": "0.30",
                "information_set": "initial",
                "parameter_multipliers": {
                    "objective_term:verified_annual_cost:reserve_ibex": "1.20"
                },
                "assumption_refs": ["scenario:rental_scarcity"],
            },
            {
                "scenario_id": "rental_discount",
                "probability": "0.20",
                "information_set": "initial",
                "parameter_multipliers": {
                    "objective_term:verified_annual_cost:reserve_ibex": "0.90"
                },
                "assumption_refs": ["scenario:rental_discount"],
            },
        ],
    }
    values["model.yaml"] = {
        "seed": 20260903,
        "threads": 1,
        "time_limit_seconds": 30,
        "counterfactual": {
            "counterfactual_id": "remove_independent_backup",
            "condition": "The independent rock-excavation backup policy is relaxed",
            "changed_action": "Re-solve with one rock-capable unit required",
            "changes": [{"kind": "constraint_rhs", "target_id": "rock_backup", "value": 1}],
        },
    }
    values["explanation.yaml"] = {
        "recommendation_id": "alpine-station-planning-horizon",
        "action": "SELECT VERIFIED PORTFOLIO",
        "target_id": "planning_horizon",
        "drivers": [
            {
                "driver_id": "rock_backup",
                "kind": "constraint",
                "statement": "The approved independent rock-backup rule requires both rock-capable units",
                "trace_refs": ["constraint:rock_backup"],
            },
            {
                "driver_id": "standard_excavation",
                "kind": "constraint",
                "statement": "The approved drainage requirement needs the standard excavator",
                "trace_refs": ["constraint:standard_excavation"],
            },
            {
                "driver_id": "haulage",
                "kind": "constraint",
                "statement": "The approved spoil-removal requirement needs the haulage resource",
                "trace_refs": ["constraint:haulage"],
            },
        ],
        "caveats": [
            "The dossier and operational evidence are synthetic",
            "The plan remains advisory until human approval",
        ],
        "required_reviewer_role": "fleet_director",
    }
    return values


def _rule(
    rule_id: str,
    coefficients: dict[str, int],
    rhs: int,
    *,
    sense: str = ">=",
    unit: str = "unit",
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "version": "1.0",
        "status": "approved",
        "authority_ref": "reviewer:alpine_station_planner",
        "constraint_id": rule_id,
        "coefficients": coefficients,
        "sense": sense,
        "rhs": rhs,
        "unit": unit,
        "hard": True,
        "evidence_refs": [f"dossier:{rule_id}"],
    }


def _task(
    task_id: str,
    project_id: str,
    location_id: str,
    duration: int,
    earliest: int,
    latest: int,
    resources: tuple[str, ...],
    capability: str,
    *,
    capacity_demands: dict[str, int] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "project_id": project_id,
        "location_id": location_id,
        "duration": duration,
        "earliest_start": earliest,
        "latest_end": latest,
        "eligible_resource_ids": list(resources),
        "required_capability_ids": [capability],
        "allowed_location_ids": [],
        "capacity_demands": capacity_demands or {"site_supervision": 1},
        "optional": False,
        "origin_refs": [f"dossier:{task_id}", f"project:{project_id}"],
    }


def _enterprise_schedule_tasks() -> dict[str, dict[str, Any]]:
    """Return the reviewed multi-project annual programme used by the CP-SAT solve.

    The 260-day horizon represents working days in the 2027 business year.  Tasks
    are project phases or operational milestones, rather than artificially long
    continuous construction operations.
    """

    atlas = "excavator_atlas_35t"
    brenta = "excavator_brenta_22t"
    ibex = "rental_ibex_35t"
    cervo = "truck_cervo_adt"
    dolomite = "excavator_dolomite_30t"
    eiger = "excavator_eiger_25t"
    furka = "truck_furka_adt"
    gotthard = "truck_gotthard_adt"
    jura = "dozer_jura_d6"
    matterhorn = "dozer_matterhorn_d7"
    crane = "crane_limmat_60t"
    service = "service_van_rhone"
    survey = "survey_crew_alpha"
    tasks = (
        _task(
            "alpine_mobilize_breaker",
            "alpine_station",
            "lower_station_north_portal",
            3,
            38,
            46,
            (atlas, ibex),
            "rock_excavation",
        ),
        _task(
            "alpine_rock_bench_cut",
            "alpine_station",
            "lower_station_north_portal",
            15,
            46,
            65,
            (atlas, ibex),
            "rock_excavation",
        ),
        _task(
            "alpine_drainage_trench",
            "alpine_station",
            "lower_station_drainage",
            12,
            42,
            78,
            (brenta,),
            "standard_excavation",
        ),
        _task(
            "alpine_spoil_removal",
            "alpine_station",
            "lower_station_north_portal",
            12,
            58,
            98,
            (cervo, furka),
            "haulage",
            capacity_demands={"site_supervision": 1, "heavy_haul_dispatch": 1},
        ),
        _task(
            "alpine_rock_trim",
            "alpine_station",
            "lower_station_north_portal",
            10,
            62,
            108,
            (atlas, ibex),
            "rock_excavation",
        ),
        _task(
            "alpine_hose_inspection",
            "alpine_station",
            "lower_station_service_bay",
            3,
            100,
            130,
            (service,),
            "field_service",
            capacity_demands={"field_mechanics": 1},
        ),
        _task(
            "alpine_final_haul",
            "alpine_station",
            "lower_station_north_portal",
            8,
            108,
            138,
            (cervo, furka),
            "haulage",
            capacity_demands={"site_supervision": 1, "heavy_haul_dispatch": 1},
        ),
        _task(
            "northpark_environmental_strip",
            "north_logistics_park",
            "northpark_plot_c",
            6,
            12,
            35,
            (jura, matterhorn),
            "earthmoving",
        ),
        _task(
            "northpark_bulk_grade",
            "north_logistics_park",
            "northpark_plot_c",
            15,
            30,
            65,
            (jura, matterhorn),
            "earthmoving",
        ),
        _task(
            "northpark_utility_trench",
            "north_logistics_park",
            "northpark_plot_c",
            12,
            58,
            95,
            (brenta, dolomite),
            "standard_excavation",
        ),
        _task(
            "northpark_stormwater",
            "north_logistics_park",
            "northpark_plot_c",
            10,
            88,
            122,
            (dolomite, eiger),
            "standard_excavation",
        ),
        _task(
            "northpark_subbase",
            "north_logistics_park",
            "northpark_plot_c",
            12,
            115,
            145,
            (jura, matterhorn),
            "earthmoving",
        ),
        _task(
            "northpark_handover_survey",
            "north_logistics_park",
            "northpark_plot_c",
            3,
            138,
            155,
            (survey,),
            "surveying",
        ),
        _task(
            "rivergate_setout",
            "rivergate_flood_defence",
            "rivergate_reach_2",
            2,
            0,
            15,
            (survey,),
            "surveying",
        ),
        _task(
            "rivergate_access_platform",
            "rivergate_flood_defence",
            "rivergate_reach_2",
            8,
            10,
            38,
            (jura,),
            "earthmoving",
        ),
        _task(
            "rivergate_cofferdam",
            "rivergate_flood_defence",
            "rivergate_reach_2",
            10,
            28,
            58,
            (dolomite, eiger),
            "rock_excavation",
        ),
        _task(
            "rivergate_foundation_excavation",
            "rivergate_flood_defence",
            "rivergate_reach_2",
            8,
            48,
            78,
            (dolomite, eiger),
            "standard_excavation",
        ),
        _task(
            "rivergate_backfill",
            "rivergate_flood_defence",
            "rivergate_reach_2",
            8,
            70,
            98,
            (dolomite, eiger),
            "standard_excavation",
        ),
        _task(
            "rivergate_demobilize",
            "rivergate_flood_defence",
            "rivergate_reach_2",
            5,
            90,
            112,
            (furka, gotthard),
            "haulage",
            capacity_demands={"heavy_haul_dispatch": 1},
        ),
        _task(
            "lakeview_setout",
            "lakeview_hospital_enabling",
            "lakeview_main_block",
            3,
            132,
            146,
            (survey,),
            "surveying",
        ),
        _task(
            "lakeview_bulk_excavation",
            "lakeview_hospital_enabling",
            "lakeview_main_block",
            20,
            146,
            170,
            (brenta, dolomite),
            "standard_excavation",
        ),
        _task(
            "lakeview_foundation_drainage",
            "lakeview_hospital_enabling",
            "lakeview_main_block",
            12,
            168,
            200,
            (dolomite, eiger),
            "standard_excavation",
        ),
        _task(
            "lakeview_crane_base",
            "lakeview_hospital_enabling",
            "lakeview_main_block",
            10,
            195,
            220,
            (jura, matterhorn),
            "earthmoving",
        ),
        _task(
            "lakeview_handover_survey",
            "lakeview_hospital_enabling",
            "lakeview_main_block",
            3,
            215,
            235,
            (survey,),
            "surveying",
        ),
        _task(
            "windroad_rock_cut",
            "valais_wind_access",
            "ridge_access_km_4",
            15,
            160,
            190,
            (dolomite, eiger),
            "rock_excavation",
        ),
        _task(
            "windroad_culvert",
            "valais_wind_access",
            "ridge_access_km_4",
            10,
            185,
            208,
            (eiger,),
            "standard_excavation",
        ),
        _task(
            "windroad_aggregate_haul",
            "valais_wind_access",
            "ridge_access_km_4",
            12,
            200,
            220,
            (cervo, furka, gotthard),
            "haulage",
            capacity_demands={"site_supervision": 1, "heavy_haul_dispatch": 1},
        ),
        _task(
            "windroad_crane_pad",
            "valais_wind_access",
            "ridge_access_km_4",
            10,
            212,
            238,
            (jura, matterhorn),
            "earthmoving",
        ),
        _task(
            "windroad_laydown_lift",
            "valais_wind_access",
            "ridge_laydown_area",
            5,
            240,
            248,
            (crane,),
            "lifting",
        ),
        _task(
            "windroad_finish_grade",
            "valais_wind_access",
            "ridge_access_km_4",
            8,
            245,
            260,
            (jura, matterhorn),
            "earthmoving",
        ),
        _task(
            "depot_ibex_onboarding",
            "central_fleet_support",
            "central_depot",
            2,
            30,
            45,
            (service,),
            "field_service",
            capacity_demands={"field_mechanics": 1},
        ),
        _task(
            "depot_furka_service",
            "central_fleet_support",
            "central_depot",
            3,
            10,
            40,
            (service,),
            "field_service",
            capacity_demands={"field_mechanics": 1},
        ),
        _task(
            "depot_q1_safety_checks",
            "central_fleet_support",
            "central_depot",
            5,
            45,
            68,
            (service,),
            "field_service",
            capacity_demands={"field_mechanics": 1},
        ),
        _task(
            "depot_atlas_midyear_service",
            "central_fleet_support",
            "central_depot",
            4,
            124,
            130,
            (service,),
            "field_service",
            capacity_demands={"field_mechanics": 1},
        ),
        _task(
            "depot_cervo_overhaul",
            "central_fleet_support",
            "central_depot",
            5,
            135,
            160,
            (service,),
            "field_service",
            capacity_demands={"field_mechanics": 1},
        ),
        _task(
            "depot_year_end_inspections",
            "central_fleet_support",
            "central_depot",
            6,
            246,
            255,
            (service,),
            "field_service",
            capacity_demands={"field_mechanics": 1},
        ),
    )
    return {item["task_id"]: item for item in tasks}


def _precedence(predecessor_id: str, successor_id: str) -> dict[str, Any]:
    return {
        "predecessor_id": predecessor_id,
        "successor_id": successor_id,
        "minimum_lag": 0,
        "origin_ref": f"reviewed:sequence:{predecessor_id}:{successor_id}",
    }


def _schedule_task_grounding_text(task: dict[str, Any]) -> str:
    resources = ", ".join(task["eligible_resource_ids"])
    capacity = ", ".join(
        f"{amount} {pool_id} slot" for pool_id, amount in sorted(task["capacity_demands"].items())
    )
    return (
        f"The mandatory activity {task['task_id']} belongs to project "
        f"{task['project_id']} at {task['location_id']}; it requires "
        f"{task['duration']} working days inside annual working days "
        f"{task['earliest_start']} through {task['latest_end']}, may use "
        f"{resources}, requires capability {task['required_capability_ids'][0]}, "
        f"and reserves {capacity}."
    )


def _write_inputs(payloads: dict[str, dict[str, Any]], directory: Path) -> None:
    for name in INPUT_FILENAMES:
        write_yaml(directory / name, payloads[name])


def _build_grounding(source: str, compilation: CompilationRequest, schedule: SchedulingProblem):
    rule_text = {
        "rock_primary": "For the reviewed annual planning projection, retaining Atlas or reserving Ibex contributes 936 productive hours of rock excavation per selected resource, and the hard annual minimum is 936 productive hours.",
        "rock_backup": "The reviewed backup rule counts Atlas and Ibex as two independently mobilizable rock resources and requires both selections.",
        "standard_excavation": "Retaining Brenta contributes 624 productive hours of standard excavation, exactly meeting the hard annual 624-hour minimum.",
        "haulage": "Retaining Cervo contributes 1,248 productive hours of haulage, exactly meeting the hard annual 1,248-hour minimum.",
    }
    rules = []
    for rule in compilation.rules:
        if rule.status != "approved":
            continue
        rules.append(
            ApprovedRuleGrounding(
                binding_id=f"rule:{rule.rule_id}",
                span=exact_grounding_span(
                    source, f"span:rule:{rule.rule_id}", rule_text[rule.rule_id]
                ),
                rule_id=rule.rule_id,
                rule_version=rule.version,
                authority_ref=rule.authority_ref,
                constraint_id=rule.constraint_id,
                coefficients=rule.coefficients,
                sense=rule.sense,
                rhs=rule.rhs,
                unit=rule.unit,
                hard=rule.hard,
                penalty=rule.penalty,
                evidence_refs=rule.evidence_refs,
            )
        )
    cost_text = {
        "retain_atlas": "Releasing Atlas for the year would avoid CHF 265,200 of that allowance but would remove the owned breaker capacity.",
        "reserve_ibex": "Helvetic Plant quoted CHF 358,800 to reserve Ibex across the annual programme.",
        "retain_brenta": "Brenta carries an annual attributable allowance of CHF 166,400.",
        "retain_cervo": "Cervo carries an annual attributable allowance of CHF 140,400.",
    }
    objective = compilation.objectives[0]
    terms = tuple(
        ObjectiveTermGrounding(
            binding_id=f"objective:{term.variable_id}",
            span=exact_grounding_span(
                source, f"span:objective:{term.variable_id}", cost_text[term.variable_id]
            ),
            objective_id=objective.objective_id,
            variable_id=term.variable_id,
            coefficient=term.coefficient,
            objective_sense=objective.sense,
            objective_priority=objective.priority,
            objective_unit=objective.unit,
            objective_component=objective.component,
            objective_origin_refs=objective.origin_refs,
        )
        for term in objective.expression.terms
    )
    atlas_cost_text = (
        "Keeping Atlas across the annual programme is costed at CHF 436,800, "
        "including a CHF 171,600 unavoidable ownership allowance. Releasing Atlas "
        "for the year would avoid CHF 265,200 of that allowance but would remove "
        "the owned breaker capacity."
    )
    constants = (
        ObjectiveConstantGrounding(
            binding_id=f"objective:{objective.objective_id}:constant",
            span=exact_grounding_span(
                source,
                f"span:objective:{objective.objective_id}:constant",
                atlas_cost_text,
            ),
            objective_id=objective.objective_id,
            constant=objective.expression.constant,
            objective_sense=objective.sense,
            objective_priority=objective.priority,
            objective_unit=objective.unit,
            objective_component=objective.component,
            objective_origin_refs=objective.origin_refs,
        ),
    )
    task_text = {
        task.task_id: _schedule_task_grounding_text(task.model_dump()) for task in schedule.tasks
    }
    tasks = tuple(
        ScheduleTaskGrounding(
            binding_id=f"task:{task.task_id}",
            span=exact_grounding_span(source, f"span:task:{task.task_id}", task_text[task.task_id]),
            **task.model_dump(),
        )
        for task in schedule.tasks
    )
    return build_demonstrator_grounding(
        source_id=SOURCE_ID,
        source_text=source,
        compilation_request=compilation,
        scheduling_problem=schedule,
        approval=ReviewerApproval(
            reviewer_id="synthetic_demo_planner",
            approved_at=datetime.fromisoformat("2026-09-03T16:00:00+02:00"),
            version="1.0",
        ),
        approved_rule_bindings=tuple(rules),
        objective_term_bindings=terms,
        objective_constant_bindings=constants,
        schedule_task_bindings=tasks,
    )


def _dossier_record(
    source: str, *, kb_profile: Literal["compact", "expanded"] = "compact"
) -> dict[str, Any]:
    return {
        "title": (
            "Alpine Station Expansion — expanded synthetic knowledge base"
            if kb_profile == "expanded"
            else "Alpine Station Expansion — grounded fleet plan"
        ),
        "scenario_id": "alpinebuild_annual_portfolio_2027",
        "synthetic": True,
        "source_text": source,
    }


def execute_grounded_demonstrator(
    output_dir: Path,
    *,
    model: str = "gpt-5.4",
    reuse_formalization: bool = False,
    kb_profile: Literal["compact", "expanded"] = "compact",
) -> Path:
    """Execute the live generative boundary and all real deterministic backends."""
    formalization_path = output_dir / "formalization.yaml"
    if reuse_formalization:
        formalization = DemonstratorFormalizationRun.model_validate(read_yaml(formalization_path))
    else:
        try:
            formalization = run_demonstrator_autoformalization(model=model, kb_profile=kb_profile)
        except DemonstratorRefinementError as exc:
            write_text(output_dir / "synthetic_dossier.md", exc.request.source_text)
            write_yaml(
                output_dir / "formalization_refinement_failed.yaml",
                exc.refinement.model_dump(mode="json"),
            )
            if exc.refinement.final_candidate is not None:
                write_autoformalization_visualizer_artifact(
                    exc.request,
                    exc.refinement.final_candidate,
                    output_dir / "candidate_rules_incomplete.html",
                    title=("Expanded autoformalization candidate — incomplete refinement"),
                )
            raise
        write_yaml(formalization_path, formalization.model_dump(mode="json"))
    if formalization.kb_profile != kb_profile:
        raise ValueError("reused formalization does not match requested KB profile")
    formal_kb_export = write_approved_formal_kb(formalization, output_dir)
    for legacy_candidate_artifact in (
        "candidate_kb.lp",
        "candidate_kb.pl",
        "candidate_kb_manifest.yaml",
    ):
        (output_dir / legacy_candidate_artifact).unlink(missing_ok=True)
    write_text(output_dir / "synthetic_dossier.md", formalization.source_text)
    payloads = _demonstrator_inputs()
    input_dir = output_dir / "inputs"
    workflow_dir = output_dir / "workflow"
    _write_inputs(payloads, input_dir)
    run = execute_resource_portfolio_workflow(input_dir, workflow_dir)
    verify_workflow_artifacts(workflow_dir)
    snapshot = read_yaml(workflow_dir / "snapshot.yaml")["payload"]
    compilation_payload = deepcopy(payloads["compile.yaml"])
    compilation_payload["snapshot_digest"] = snapshot["content_sha256"]
    compilation = CompilationRequest.model_validate(compilation_payload)
    compiled_problem = read_yaml(workflow_dir / "compilation.yaml")["payload"]["problem"]
    schedule_payload = deepcopy(payloads["schedule.yaml"])
    schedule_payload["plan_digest"] = stable_hash(compiled_problem)
    schedule = SchedulingProblem.model_validate(schedule_payload)
    grounding = _build_grounding(formalization.source_text, compilation, schedule)
    compilation_report = CompilationReport.model_validate(
        read_yaml(workflow_dir / "compilation.yaml")["payload"]
    )
    verified_plan = VerifiedPlan.model_validate(read_yaml(workflow_dir / "plan.yaml")["payload"])
    counterfactual_run = CounterfactualRun.model_validate(
        read_yaml(workflow_dir / "counterfactual.yaml")["payload"]
    )
    policy_changes = tuple(
        CounterfactualChange.model_validate(item)
        for item in payloads["model.yaml"]["counterfactual"]["changes"]
    )
    decision_argument = build_decision_argument_certificate(
        compilation_report.problem,
        verified_plan,
        policy_counterfactual=counterfactual_run,
        policy_changes=policy_changes,
        candidate_kb_digest=stable_hash(formalization.candidate.model_dump(mode="json")),
        seed=int(payloads["model.yaml"]["seed"]),
    )
    stress_payload = dict(read_yaml(workflow_dir / "stress.yaml")["payload"])
    scenario_set = ScenarioSet.model_validate(stress_payload.pop("scenario_set"))
    stress_report = StressReport.model_validate(stress_payload)
    scenario_explanation = build_scenario_envelope_explanation(
        compilation_report.problem,
        scenario_set,
        stress_report,
        ScenarioCoverageDeclaration(
            coverage_id="alpinebuild-2027-rental-rate-envelope",
            planning_horizon="260-working-day 2027 business year",
            investigated_question=(
                "Does the verified portfolio assignment change across the three "
                "reviewed Ibex reservation-rate scenarios?"
            ),
            exclusions=(
                CoverageExclusion(
                    dimension="weather, permitting, and project-window disruption",
                    reason="No reviewed probability or schedule-recourse model was supplied.",
                    origin_refs=("dossier:commercial_and_scheduling_observations",),
                ),
                CoverageExclusion(
                    dimension="machine outage and productivity uncertainty",
                    reason="The bounded experiment varies only the quoted rental-rate term.",
                    origin_refs=("review:scenario_scope",),
                ),
                CoverageExclusion(
                    dimension="project cancellation and portfolio demand mix",
                    reason="All approved annual project requirements remain fixed in these runs.",
                    origin_refs=("review:scenario_scope",),
                ),
            ),
            origin_refs=("dossier:commercial_stress_testing", "review:scenario_scope"),
        ),
        certificate=decision_argument,
    )
    cost_explanation = build_cost_objective_explanation(
        compilation_report.problem,
        verified_plan,
        objective_id="verified_annual_cost",
        time_basis="260-working-day 2027 business year",
        time_basis_origin_refs=("reviewed:commercial_observations",),
        grounding=grounding,
        certificate=decision_argument,
    )
    authoritative_explanation = deepcopy(read_yaml(workflow_dir / "explanation.yaml")["payload"])
    explanation_evidence = PortfolioExplanationEvidence.model_validate(
        authoritative_explanation.pop("evidence")
    )
    generative_path = output_dir / "generative_explanation.yaml"
    reusable_explanation = None
    if reuse_formalization and generative_path.is_file():
        candidate_explanation = PortfolioExplanation.model_validate(read_yaml(generative_path))
        if (
            candidate_explanation.candidate_only
            and candidate_explanation.receipt.mode == "generative"
            and candidate_explanation.receipt.evidence_digest
            == explanation_evidence.evidence_digest
        ):
            reusable_explanation = candidate_explanation
    if reusable_explanation is None:
        generative_explanation = generate_explanation(
            explanation_evidence,
            CodexExecTransport(model=model, timeout_seconds=600),
        )
    else:
        generative_explanation = reusable_explanation
    if not generative_explanation.candidate_only:
        raise ValueError("generative explanation crossed the candidate-only boundary")
    write_yaml(output_dir / "grounding.yaml", grounding.model_dump(mode="json"))
    write_yaml(
        output_dir / "decision_argument.yaml",
        decision_argument.model_dump(mode="json"),
    )
    write_yaml(
        output_dir / "scenario_envelope_explanation.yaml",
        scenario_explanation.model_dump(mode="json"),
    )
    write_yaml(
        output_dir / "cost_objective_explanation.yaml",
        cost_explanation.model_dump(mode="json"),
    )
    write_yaml(
        generative_path,
        generative_explanation.model_dump(mode="json"),
    )
    candidate_visualization = build_autoformalization_visualization(
        formalization.request,
        formalization.candidate,
        title="Alpine Station autoformalized rule candidate",
    )
    candidate_visualizer_path = write_autoformalization_visualizer_artifact(
        formalization.request,
        formalization.candidate,
        output_dir / "accepted_rules.html",
        title="Alpine Station accepted autoformalized rules",
        accepted=True,
    )
    (output_dir / "candidate_rules.html").unlink(missing_ok=True)
    formalization_record = {
        **formalization.model_dump(mode="json"),
        "grounding": grounding.model_dump(mode="json"),
        "generative_explanation": generative_explanation.model_dump(mode="json"),
        "candidate_visualization": candidate_visualization.model_dump(mode="json"),
        "decision_argument": decision_argument.model_dump(mode="json"),
        "accepted_formal_kb": formal_kb_export.model_dump(mode="json"),
        "scenario_envelope_explanation": scenario_explanation.model_dump(mode="json"),
        "cost_objective_explanation": cost_explanation.model_dump(mode="json"),
    }
    report = write_resource_portfolio_demonstrator_report(
        _dossier_record(formalization.source_text, kb_profile=kb_profile),
        formalization_record,
        workflow_dir,
        output_dir / "index.html",
    )
    manifest = {
        "schema_version": "resource-portfolio-grounded-demonstrator/v2",
        "kb_profile": kb_profile,
        "synthetic": True,
        "advisory_only": True,
        "externally_authorized": False,
        "formalization_run_digest": formalization.run_digest,
        "grounding_digest": grounding.grounding_sha256,
        "workflow_run_digest": run.run_digest,
        "generative_explanation_digest": stable_hash(
            generative_explanation.model_dump(mode="json")
        ),
        "candidate_visualization_digest": candidate_visualization.audit_hash,
        "accepted_formal_kb_digest": formal_kb_export.receipt_sha256,
        "accepted_formal_kb_manifest": "accepted_kb_manifest.yaml",
        "accepted_asp_kb": "accepted_kb.lp",
        "accepted_prolog_kb": "accepted_kb.pl",
        "accepted_asp_kb_digest": formal_kb_export.artifacts[0].content_sha256,
        "accepted_prolog_kb_digest": formal_kb_export.artifacts[1].content_sha256,
        "formal_logic_release": "formal_logic_release.yaml",
        "formal_logic_release_digest": formal_kb_export.formal_logic_release_sha256,
        "decision_argument_digest": decision_argument.certificate_sha256,
        "scenario_envelope_explanation_digest": scenario_explanation.coverage_sha256,
        "cost_objective_explanation_digest": cost_explanation.explanation_sha256,
        "scenario_envelope_explanation": "scenario_envelope_explanation.yaml",
        "cost_objective_explanation": "cost_objective_explanation.yaml",
        "decision_argument": "decision_argument.yaml",
        "accepted_rules_visualizer": candidate_visualizer_path.name,
        "report": "index.html",
    }
    manifest["content_sha256"] = stable_hash(manifest)
    write_yaml(output_dir / "demonstrator_run.yaml", manifest)
    return report


__all__ = ["SOURCE_ID", "execute_grounded_demonstrator"]
