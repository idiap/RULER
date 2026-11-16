# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from ruler.applications.resource_portfolio.compiler import CompilationRequest, compile_rules
from ruler.applications.resource_portfolio.demonstrator import (
    SOURCE_ID,
    _build_grounding,
    _demonstrator_inputs,
)
from ruler.applications.resource_portfolio.demonstrator_formalization import (
    build_demonstrator_request,
    load_demonstrator_dossier,
)
from ruler.applications.resource_portfolio.demonstrator_grounding import (
    verify_demonstrator_grounding,
)
from ruler.applications.resource_portfolio.scheduling import SchedulingProblem, solve_schedule
from ruler.applications.resource_portfolio.optimization import optimize_portfolio
from ruler.applications.resource_portfolio.robustness import (
    CounterfactualChange,
    run_counterfactual,
)
from ruler.applications.resource_portfolio.workflow import build_evidence_snapshot
from ruler.kb.formalization import ValueType


def test_demonstrator_reuses_real_typed_generators_and_grounding_bridge() -> None:
    payloads = _demonstrator_inputs()
    _, _, _, snapshot = build_evidence_snapshot(payloads["evidence.yaml"])
    compilation_payload = deepcopy(payloads["compile.yaml"])
    compilation_payload["snapshot_digest"] = snapshot.content_sha256
    compilation = CompilationRequest.model_validate(compilation_payload)
    report = compile_rules(compilation)
    schedule_payload = deepcopy(payloads["schedule.yaml"])
    schedule_payload["plan_digest"] = report.problem.digest
    schedule = SchedulingProblem.model_validate(schedule_payload)

    grounding = _build_grounding(load_demonstrator_dossier(), compilation, schedule)
    verify_demonstrator_grounding(
        grounding,
        source_text=load_demonstrator_dossier(),
        compilation_request=compilation,
        scheduling_problem=schedule,
    )

    assert grounding.source_id == SOURCE_ID
    assert grounding.generated_candidate_solver_authority is False
    assert len(grounding.approved_rule_bindings) == 4
    assert len(grounding.objective_term_bindings) == 4
    assert solve_schedule(schedule).status == "OPTIMAL"


def test_enterprise_schedule_spans_annual_projects_and_shared_resources() -> None:
    payloads = _demonstrator_inputs()
    schedule_payload = payloads["schedule.yaml"]
    schedule_payload["plan_digest"] = "sha256:" + "1" * 64
    schedule = SchedulingProblem.model_validate(schedule_payload)
    result = solve_schedule(schedule, seed=20260903)

    assert result.status == "OPTIMAL"
    assert schedule.time_unit == "working_day"
    assert len(schedule.tasks) == 36
    assert {item.project_id for item in schedule.tasks} == {
        "alpine_station",
        "north_logistics_park",
        "rivergate_flood_defence",
        "valais_wind_access",
        "lakeview_hospital_enabling",
        "central_fleet_support",
    }
    assert len(schedule.resource_capability_ids) == 13
    assert len(schedule.precedences) == 22
    assert len(schedule.frozen_assignments) == 6
    assert schedule.capacity_limits == {
        "site_supervision": 4,
        "heavy_haul_dispatch": 2,
        "field_mechanics": 1,
    }
    assert not result.unassigned_task_ids
    assert result.objective_value is not None and result.objective_value >= 250
    assert max(item.latest_end for item in schedule.tasks) == 260
    assert {
        item.task_id for item in schedule.tasks if item.project_id == "central_fleet_support"
    } == {
        "depot_ibex_onboarding",
        "depot_furka_service",
        "depot_q1_safety_checks",
        "depot_atlas_midyear_service",
        "depot_cervo_overhaul",
        "depot_year_end_inspections",
    }
    assert {item.resource_id for item in result.assignments} == set(
        schedule.resource_capability_ids
    )


def test_productive_hour_quantity_is_duration_typed_not_money() -> None:
    request = build_demonstrator_request(source_text=load_demonstrator_dossier())
    signature = request.predicate_registry.require("activity_requires")

    assert signature.argument_types[-1] == ValueType.DURATION
    assert signature.units[-1] == "productive_hour"


def test_portfolio_capacity_projection_uses_an_annual_basis() -> None:
    payloads = _demonstrator_inputs()
    approved = {
        item["rule_id"]: item
        for item in payloads["compile.yaml"]["rules"]
        if item["status"] == "approved"
    }

    assert approved["rock_primary"]["coefficients"] == {
        "retain_atlas": 936,
        "reserve_ibex": 936,
    }
    assert approved["rock_primary"]["rhs"] == 936
    assert approved["standard_excavation"]["rhs"] == 624
    assert approved["haulage"]["rhs"] == 1_248


def test_annual_atlas_cost_grounding_separates_unavoidable_and_avoidable_cost() -> None:
    payloads = _demonstrator_inputs()
    source = load_demonstrator_dossier()
    _, _, _, snapshot = build_evidence_snapshot(payloads["evidence.yaml"])
    compilation_payload = deepcopy(payloads["compile.yaml"])
    compilation_payload["snapshot_digest"] = snapshot.content_sha256
    compilation = CompilationRequest.model_validate(compilation_payload)
    report = compile_rules(compilation)
    schedule_payload = deepcopy(payloads["schedule.yaml"])
    schedule_payload["plan_digest"] = report.problem.digest
    schedule = SchedulingProblem.model_validate(schedule_payload)
    grounding = _build_grounding(source, compilation, schedule)

    objective = report.problem.objectives[0]
    coefficients = {term.variable_id: term.coefficient for term in objective.expression.terms}
    assert objective.objective_id == "verified_annual_cost"
    assert objective.expression.constant == Decimal("171600")
    assert coefficients["retain_atlas"] == Decimal("265200")
    assert objective.expression.constant + coefficients["retain_atlas"] == Decimal("436800")
    assert "Keeping Atlas across the annual programme is costed at CHF 436,800" in source
    assert "Releasing Atlas for the year would avoid CHF 265,200" in source
    assert len(grounding.objective_constant_bindings) == 1
    constant = grounding.objective_constant_bindings[0]
    assert constant.objective_id == objective.objective_id
    assert constant.constant == Decimal("171600")
    assert "CHF 436,800" in constant.span.exact_text
    assert "CHF 265,200" in constant.span.exact_text


def test_relaxed_backup_counterfactual_selects_cheaper_atlas_only() -> None:
    payloads = _demonstrator_inputs()
    _, _, _, snapshot = build_evidence_snapshot(payloads["evidence.yaml"])
    compilation_payload = deepcopy(payloads["compile.yaml"])
    compilation_payload["snapshot_digest"] = snapshot.content_sha256
    problem = compile_rules(CompilationRequest.model_validate(compilation_payload)).problem

    base = optimize_portfolio(problem)
    specification = payloads["model.yaml"]["counterfactual"]
    changes = tuple(CounterfactualChange.model_validate(item) for item in specification["changes"])
    counterfactual = run_counterfactual(
        problem,
        changes,
        run_id="relax-independent-rock-backup",
        seed=20260903,
    )

    assert changes == (
        CounterfactualChange(kind="constraint_rhs", target_id="rock_backup", value=Decimal("1")),
    )
    assert base.result.objective_value == Decimal("1102400.0")
    assert counterfactual.result.objective_value == Decimal("743600.0")
    assert base.result.objective_value - counterfactual.result.objective_value == Decimal(
        "358800.0"
    )
    assert counterfactual.result.assignments == {
        "reserve_ibex": Decimal("0.0"),
        "retain_atlas": Decimal("1.0"),
        "retain_brenta": Decimal("1.0"),
        "retain_cervo": Decimal("1.0"),
    }
