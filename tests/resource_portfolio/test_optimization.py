# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Behavioral tests that execute the real optimization backends."""

from decimal import Decimal

import pytest
from click.testing import CliRunner

from ruler.applications.resource_portfolio.compiler import (
    ApprovedLinearRule,
    CompilationRequest,
    compile_rules,
)
from ruler.applications.resource_portfolio.optimization import (
    BaselineDefinition,
    compare_baselines,
    optimize_portfolio,
)
from ruler.applications.resource_portfolio.robustness import (
    CounterfactualChange,
    ScenarioFactor,
    ScenarioSet,
    build_scenarios,
    calculate_cvar,
    run_counterfactual,
    stress_test,
)
from ruler.applications.resource_portfolio.scheduling import (
    ScheduleTask,
    SchedulingProblem,
    solve_schedule,
)
from ruler.optimization.contracts import (
    LinearObjective,
    LinearExpression,
    LinearTerm,
    OptimizationVariable,
)
from ruler.optimization.verification import verify_result
from ruler.optimization.diagnostics import diagnose_infeasibility
from ruler.optimization.contracts import LinearConstraint, OptimizationProblem, Scenario
from ruler.cli import main
from ruler.io import read_yaml, write_yaml

SNAPSHOT = "sha256:" + "a" * 64


def _problem():
    variables = (
        OptimizationVariable(
            variable_id="owned",
            domain="integer",
            lower_bound=0,
            upper_bound=3,
            unit="resource",
            origin_refs=("snapshot:resources",),
        ),
        OptimizationVariable(
            variable_id="rented",
            domain="integer",
            lower_bound=0,
            upper_bound=3,
            unit="resource",
            origin_refs=("snapshot:offers",),
        ),
    )
    request = CompilationRequest(
        problem_id="tiny-capacity",
        snapshot_digest=SNAPSHOT,
        variables=variables,
        rules=(
            ApprovedLinearRule(
                rule_id="minimum-capacity",
                version="1",
                status="approved",
                authority_ref="policy:capacity",
                constraint_id="capacity",
                coefficients={"owned": Decimal(1), "rented": Decimal(1)},
                sense=">=",
                rhs=2,
                unit="resource",
                evidence_refs=("demand:period-1",),
            ),
        ),
        objectives=(
            LinearObjective(
                objective_id="lifecycle-cost",
                expression=LinearExpression(
                    terms=(
                        LinearTerm(variable_id="owned", coefficient=3),
                        LinearTerm(variable_id="rented", coefficient=5),
                    )
                ),
                unit="CHF",
                component="lifecycle",
                origin_refs=("cost:model",),
            ),
        ),
    )
    return compile_rules(request).problem


def test_real_highs_solve_has_truthful_receipt_and_independent_verification():
    problem = _problem()
    plan = optimize_portfolio(problem)
    assert plan.result.status == "OPTIMAL"
    assert plan.result.assignments == {"owned": Decimal("2.0"), "rented": Decimal("0.0")}
    assert plan.result.objective_value == Decimal("6.0")
    assert plan.result.receipt.backend_id == "pyomo_highs"
    assert plan.result.receipt.library_version
    assert plan.result.receipt.native_termination_condition == "optimal"
    assert plan.verification.verified
    assert plan.advisory_only and plan.review_status == "pending"


def test_independent_verifier_detects_corrupted_plan():
    problem = _problem()
    result = optimize_portfolio(problem).result
    corrupted = result.model_copy(
        update={"assignments": {"owned": Decimal(0), "rented": Decimal(0)}}
    )
    report = verify_result(problem, corrupted)
    assert not report.verified
    assert report.constraint_checks[0].constraint_id == "capacity"
    assert report.constraint_checks[0].violation == 2


def test_rule_mutation_changes_digest_and_solution():
    problem = _problem()
    changed = run_counterfactual(
        problem,
        (CounterfactualChange(kind="constraint_rhs", target_id="capacity", value=3),),
        run_id="cf-demand-3",
    )
    assert changed.base_model_digest != changed.variant_model_digest
    assert changed.result.objective_value == Decimal("9.0")


def test_compiler_rejects_hard_conflict_with_real_z3():
    problem = _problem()
    variables = problem.variables
    with pytest.raises(ValueError, match="unsatisfiable"):
        compile_rules(
            CompilationRequest(
                problem_id="conflict",
                snapshot_digest=SNAPSHOT,
                variables=variables,
                rules=(
                    ApprovedLinearRule(
                        rule_id="min",
                        version="1",
                        status="approved",
                        authority_ref="p:1",
                        constraint_id="min",
                        coefficients={"owned": 1},
                        sense=">=",
                        rhs=2,
                        unit="resource",
                        evidence_refs=("e:1",),
                    ),
                    ApprovedLinearRule(
                        rule_id="max",
                        version="1",
                        status="approved",
                        authority_ref="p:2",
                        constraint_id="max",
                        coefficients={"owned": 1},
                        sense="<=",
                        rhs=1,
                        unit="resource",
                        evidence_refs=("e:2",),
                    ),
                ),
                objectives=problem.objectives,
            )
        )


def test_cp_sat_prevents_double_booking():
    problem = SchedulingProblem(
        schedule_id="schedule-1",
        plan_digest="sha256:" + "b" * 64,
        time_unit="hour",
        tasks=(
            ScheduleTask(
                task_id="a",
                duration=3,
                earliest_start=0,
                latest_end=6,
                eligible_resource_ids=("r1",),
                origin_refs=("work:a",),
            ),
            ScheduleTask(
                task_id="b",
                duration=3,
                earliest_start=0,
                latest_end=6,
                eligible_resource_ids=("r1",),
                origin_refs=("work:b",),
            ),
        ),
    )
    result = solve_schedule(problem)
    assert result.status == "OPTIMAL"
    assert result.receipt.backend_id == "ortools_cp_sat_intervals"
    a, b = result.assignments
    assert a.end <= b.start or b.end <= a.start


def test_cp_sat_enforces_capability_compatibility():
    problem = SchedulingProblem(
        schedule_id="schedule-capability",
        plan_digest="sha256:" + "c" * 64,
        time_unit="hour",
        tasks=(
            ScheduleTask(
                task_id="specialized",
                duration=1,
                earliest_start=0,
                latest_end=2,
                eligible_resource_ids=("r1",),
                required_capability_ids=("cap:special",),
                origin_refs=("requirement:special",),
            ),
        ),
        resource_capability_ids={"r1": ("cap:basic",)},
    )
    result = solve_schedule(problem)
    assert result.status == "INFEASIBLE"


def test_seeded_scenarios_and_hand_computed_cvar_are_reproducible():
    kwargs = dict(
        scenario_set_id="joint-1",
        factors=(ScenarioFactor(parameter_id="demand", low=Decimal("0.8"), high=Decimal("1.2")),),
        count=2,
        seed=17,
        assumption_refs=("profile:demand",),
    )
    first = build_scenarios(**kwargs)
    second = build_scenarios(**kwargs)
    assert first.digest == second.digest
    result = calculate_cvar(
        {first.scenarios[0].scenario_id: Decimal(10), first.scenarios[1].scenario_id: Decimal(30)},
        first.scenarios,
        Decimal("0.5"),
    )
    assert result.expected_loss == 20
    assert result.conditional_value_at_risk == 30


def test_infeasibility_diagnostic_preserves_status_and_quantifies_repair():
    base = _problem()
    infeasible = OptimizationProblem.model_validate(
        {
            **base.model_dump(mode="python"),
            "problem_id": "infeasible-capacity",
            "constraints": [
                LinearConstraint(
                    constraint_id="impossible-capacity",
                    expression=LinearExpression(
                        terms=(LinearTerm(variable_id="owned", coefficient=1),)
                    ),
                    sense=">=",
                    rhs=4,
                    unit="resource",
                    origin_refs=("rule:redundancy",),
                ).model_dump(mode="python")
            ],
        }
    )
    report = diagnose_infeasibility(infeasible)
    assert report.original_status == "INFEASIBLE"
    assert report.relaxation_status == "OPTIMAL"
    assert report.repairs[0].constraint_id == "impossible-capacity"
    assert report.repairs[0].required_relaxation == 1


def test_infeasible_baseline_is_not_given_a_fabricated_cost():
    baseline = compare_baselines(
        _problem(),
        (
            BaselineDefinition(
                baseline_id="no-supply",
                fixed_assignments={"owned": Decimal(0), "rented": Decimal(0)},
                origin_ref="baseline:declared:no-supply",
            ),
        ),
    )[0]
    assert baseline.plan.result.status == "INFEASIBLE"
    assert baseline.plan.result.objective_value is None


def test_stress_test_executes_scenario_specific_resolves():
    scenarios = ScenarioSet(
        scenario_set_id="stress-1",
        seed=3,
        scenarios=(
            Scenario(
                scenario_id="normal",
                probability=Decimal("0.5"),
                information_set="initial",
                parameter_multipliers={"constraint_rhs:capacity": Decimal(1)},
                assumption_refs=("profile:demand",),
            ),
            Scenario(
                scenario_id="high",
                probability=Decimal("0.5"),
                information_set="initial",
                parameter_multipliers={"constraint_rhs:capacity": Decimal("1.5")},
                assumption_refs=("profile:demand",),
            ),
        ),
    )
    report = stress_test(_problem(), scenarios, alpha=Decimal("0.5"))
    assert [item.result.objective_value for item in report.outcomes] == [
        Decimal("6.0"),
        Decimal("9.0"),
    ]
    assert report.risk is not None
    assert report.risk.conditional_value_at_risk == 9


def test_portfolio_optimize_cli_executes_highs_and_writes_verified_artifact(tmp_path):
    model_path = tmp_path / "model.yaml"
    output_dir = tmp_path / "result"
    write_yaml(model_path, _problem().model_dump(mode="json"))
    invocation = CliRunner().invoke(
        main, ["portfolio", "optimize", str(model_path), "--output", str(output_dir)]
    )
    assert invocation.exit_code == 0, invocation.output
    artifact = read_yaml(output_dir / "verified_plan.yaml")
    assert artifact["result"]["status"] == "OPTIMAL"
    assert artifact["result"]["receipt"]["backend_id"] == "pyomo_highs"
    assert artifact["verification"]["verified"] is True
