# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Adversarial and metamorphic checks for the resource-portfolio workflow.

These tests deliberately construct small synthetic instances rather than relying only
on the happy-path AlpineBuild fixture.  A failure here should identify an invariant
at a trust boundary, not a change in a particular solver's preferred representation.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from random import Random
from shutil import copytree
from typing import Any

import pytest

from ruler.applications.resource_portfolio.compiler import (
    ApprovedLinearRule,
    CompilationRequest,
    compile_rules,
)
from ruler.applications.resource_portfolio.optimization import optimize_portfolio
from ruler.applications.resource_portfolio.scheduling import (
    FrozenAssignment,
    ScheduleTask,
    SchedulingProblem,
    solve_schedule,
)
from ruler.applications.resource_portfolio.synthetic import (
    SyntheticPortfolioConfig,
    generate_synthetic_portfolio_inputs,
    verify_synthetic_portfolio_inputs,
    write_synthetic_portfolio_inputs,
)
from ruler.applications.resource_portfolio.workflow import (
    build_evidence_snapshot,
    execute_resource_portfolio_workflow,
    verify_workflow_artifacts,
)
from ruler.io import read_yaml, stable_hash, write_yaml
from ruler.optimization.contracts import (
    LinearExpression,
    LinearObjective,
    LinearTerm,
    OptimizationVariable,
)
from ruler.paths import REPO_ROOT

FIXTURES = REPO_ROOT / "data" / "domains" / "construction_fleet" / "tests"


def _synthetic_problem(seed: int, *, required: int | None = None):
    """Build a feasible integer portfolio instance from a reproducible seed."""
    rng = Random(seed)
    capacity = required if required is not None else rng.randint(1, 5)
    owned_cost = rng.randint(2, 8)
    rental_cost = owned_cost + rng.randint(1, 5)
    variables = (
        OptimizationVariable(
            variable_id="owned",
            domain="integer",
            lower_bound=0,
            upper_bound=capacity,
            unit="unit",
            origin_refs=(f"synthetic:seed:{seed}",),
        ),
        OptimizationVariable(
            variable_id="rented",
            domain="integer",
            lower_bound=0,
            upper_bound=capacity,
            unit="unit",
            origin_refs=(f"synthetic:seed:{seed}",),
        ),
    )
    request = CompilationRequest(
        problem_id=f"synthetic-{seed}-{capacity}",
        snapshot_digest="sha256:" + f"{seed:064x}"[-64:],
        variables=variables,
        rules=(
            ApprovedLinearRule(
                rule_id="reviewed-capacity",
                version="1",
                status="approved",
                authority_ref="synthetic:reviewed-policy",
                constraint_id="capacity",
                coefficients={"owned": 1, "rented": 1},
                sense=">=",
                rhs=capacity,
                unit="unit",
                evidence_refs=("synthetic:demand",),
            ),
        ),
        objectives=(
            LinearObjective(
                objective_id="cost",
                expression=LinearExpression(
                    terms=(
                        LinearTerm(variable_id="owned", coefficient=owned_cost),
                        LinearTerm(variable_id="rented", coefficient=rental_cost),
                    )
                ),
                unit="CHF",
                component="lifecycle",
                origin_refs=("synthetic:cost-model",),
            ),
        ),
    )
    return compile_rules(request).problem


def _copy_inputs(tmp_path: Path) -> Path:
    target = tmp_path / "inputs"
    copytree(FIXTURES, target)
    return target


def _without_runtime(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_runtime(item) for key, item in value.items() if key != "runtime_seconds"
        }
    if isinstance(value, list):
        return [_without_runtime(item) for item in value]
    return value


def _rehash_artifact_and_manifest(output_dir: Path, filename: str) -> None:
    """Model an attacker able to recompute unkeyed hashes after changing a payload."""
    artifact_path = output_dir / filename
    envelope = read_yaml(artifact_path)
    envelope["payload_sha256"] = stable_hash(envelope["payload"])
    envelope["semantic_sha256"] = stable_hash(_without_runtime(envelope["payload"]))
    write_yaml(artifact_path, envelope)

    manifest_path = output_dir / "workflow_run.yaml"
    manifest = read_yaml(manifest_path)
    entry = next(item for item in manifest["artifacts"] if item["relative_path"] == filename)
    entry["payload_sha256"] = envelope["payload_sha256"]
    entry["semantic_sha256"] = envelope["semantic_sha256"]
    digest_payload = deepcopy(manifest)
    digest_payload.pop("run_digest")
    digest_payload["artifacts"] = [
        {
            "artifact_type": item["artifact_type"],
            "relative_path": item["relative_path"],
            "semantic_sha256": item["semantic_sha256"],
        }
        for item in digest_payload["artifacts"]
    ]
    manifest["run_digest"] = stable_hash(digest_payload)
    write_yaml(manifest_path, manifest)


@pytest.mark.parametrize("seed", range(6))
def test_seeded_synthetic_optimization_is_repeatable_and_verified(seed: int) -> None:
    problem = _synthetic_problem(seed)
    first = optimize_portfolio(problem, seed=seed, threads=1)
    second = optimize_portfolio(problem, seed=seed, threads=1)

    assert first.result.assignments == second.result.assignments
    assert first.result.objective_value == second.result.objective_value
    assert first.result.semantic_digest == second.result.semantic_digest
    assert first.verification.verified and second.verification.verified
    assert first.result.receipt.model_digest == problem.digest


def test_increasing_reviewed_demand_cannot_reduce_minimized_cost() -> None:
    low = optimize_portfolio(_synthetic_problem(41, required=2))
    high = optimize_portfolio(_synthetic_problem(41, required=5))

    assert low.verification.verified and high.verification.verified
    assert high.result.objective_value >= low.result.objective_value


def test_full_synthetic_generator_is_seed_deterministic_and_seed_sensitive() -> None:
    config = SyntheticPortfolioConfig(
        seed=107,
        resource_count=3,
        event_days=2,
        anomaly_rate="0.25",
        duplicate_rate="0.25",
        correction_rate="0.25",
    )
    first_payloads, first_manifest = generate_synthetic_portfolio_inputs(config)
    replay_payloads, replay_manifest = generate_synthetic_portfolio_inputs(config)
    changed_payloads, changed_manifest = generate_synthetic_portfolio_inputs(
        config.model_copy(update={"seed": 108})
    )

    assert first_payloads == replay_payloads
    assert first_manifest == replay_manifest
    assert first_manifest.content_sha256 == replay_manifest.content_sha256
    assert changed_manifest.content_sha256 != first_manifest.content_sha256
    assert changed_payloads != first_payloads
    assert first_manifest.emitted_event_count == len(first_payloads["evidence.yaml"]["events"])
    assert {
        event["provenance"]["source_system"] for event in first_payloads["evidence.yaml"]["events"]
    } == {"ruler_synthetic_generator"}


def test_generated_dataset_runs_end_to_end_and_manifest_detects_tampering(
    tmp_path: Path,
) -> None:
    inputs = tmp_path / "inputs"
    output = tmp_path / "output"
    manifest = write_synthetic_portfolio_inputs(
        SyntheticPortfolioConfig(
            seed=19,
            resource_count=2,
            event_days=2,
            tasks_per_resource=1,
            scenario_count=2,
        ),
        inputs,
    )

    assert verify_synthetic_portfolio_inputs(inputs) == manifest
    run = execute_resource_portfolio_workflow(inputs, output)
    assert run.status == "pending_review"
    assert run.advisory_only and not run.externally_authorized

    model = read_yaml(inputs / "model.yaml")
    model["seed"] += 1
    write_yaml(inputs / "model.yaml", model)
    with pytest.raises(ValueError, match="synthetic input digest mismatch"):
        verify_synthetic_portfolio_inputs(inputs)


def test_generated_infeasible_variant_fails_at_real_compilation(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    write_synthetic_portfolio_inputs(
        SyntheticPortfolioConfig(
            seed=31,
            resource_count=2,
            event_days=1,
            tasks_per_resource=1,
            scenario_count=2,
            model_variant="infeasible",
        ),
        inputs,
    )

    assert verify_synthetic_portfolio_inputs(inputs).expected_compilation_status == "unsat"
    with pytest.raises(ValueError, match="unsatisfiable"):
        execute_resource_portfolio_workflow(inputs, tmp_path / "output")


@pytest.mark.parametrize("seed", (0, 1, 7, 11))
def test_anomaly_rich_generated_inputs_survive_full_workflow(seed: int, tmp_path: Path) -> None:
    inputs = tmp_path / f"inputs-{seed}"
    output = tmp_path / f"output-{seed}"
    manifest = write_synthetic_portfolio_inputs(
        SyntheticPortfolioConfig(
            seed=seed,
            resource_count=3,
            event_days=2,
            tasks_per_resource=2,
            scenario_count=3,
            anomaly_rate="0.2",
            duplicate_rate="0.2",
            correction_rate="0.2",
        ),
        inputs,
    )

    run = execute_resource_portfolio_workflow(inputs, output)

    assert manifest.emitted_event_count >= manifest.base_event_count
    assert run.status == "pending_review"
    assert verify_workflow_artifacts(output) == run


def test_candidate_rule_cannot_gain_solver_authority() -> None:
    base = _synthetic_problem(9, required=3)
    candidate = ApprovedLinearRule(
        rule_id="generated-do-not-use",
        version="0",
        status="candidate",
        authority_ref="generative:autoformalization",
        constraint_id="force-impossible-owned-count",
        coefficients={"owned": 1},
        sense=">=",
        rhs=999,
        unit="unit",
        evidence_refs=("candidate:not-reviewed",),
    )
    request = CompilationRequest(
        problem_id=base.problem_id,
        snapshot_digest=base.snapshot_digest,
        variables=base.variables,
        rules=(candidate,),
        axioms=base.constraints,
        objectives=base.objectives,
    )
    report = compile_rules(request)
    plan = optimize_portfolio(report.problem)

    assert report.rejected_rule_ids == (candidate.rule_id,)
    assert candidate.constraint_id not in {
        constraint.constraint_id for constraint in report.problem.constraints
    }
    assert plan.verification.verified
    assert plan.result.status == "OPTIMAL"


def test_evidence_and_snapshot_are_invariant_to_input_event_permutation() -> None:
    payload = read_yaml(FIXTURES / "evidence.yaml")
    permuted = deepcopy(payload)
    permuted["events"] = list(reversed(permuted["events"]))

    original = build_evidence_snapshot(payload)
    reordered = build_evidence_snapshot(permuted)

    assert original[0].content_sha256 == reordered[0].content_sha256
    assert original[1].content_sha256 == reordered[1].content_sha256
    assert original[3].content_sha256 == reordered[3].content_sha256


def test_frozen_double_booking_is_reported_infeasible() -> None:
    problem = SchedulingProblem(
        schedule_id="synthetic-frozen-conflict",
        plan_digest="sha256:" + "b" * 64,
        time_unit="hour",
        tasks=(
            ScheduleTask(
                task_id="left",
                duration=2,
                earliest_start=0,
                latest_end=4,
                eligible_resource_ids=("machine",),
                origin_refs=("synthetic:left",),
            ),
            ScheduleTask(
                task_id="right",
                duration=2,
                earliest_start=0,
                latest_end=4,
                eligible_resource_ids=("machine",),
                origin_refs=("synthetic:right",),
            ),
        ),
        frozen_assignments=(
            FrozenAssignment(task_id="left", resource_id="machine", start=0),
            FrozenAssignment(task_id="right", resource_id="machine", start=0),
        ),
    )

    result = solve_schedule(problem)

    assert result.status == "INFEASIBLE"
    assert result.assignments == ()
    assert result.receipt.problem_digest == problem.digest


def test_workflow_fails_closed_when_synthetic_schedule_is_infeasible(tmp_path: Path) -> None:
    inputs = _copy_inputs(tmp_path)
    schedule = read_yaml(inputs / "schedule.yaml")
    for task in schedule["tasks"]:
        task["duration"] = 5
    write_yaml(inputs / "schedule.yaml", schedule)

    with pytest.raises(ValueError, match="CP-SAT did not produce a usable schedule"):
        execute_resource_portfolio_workflow(inputs, tmp_path / "output")


def test_verifier_rejects_rehashed_plan_bound_to_another_model(tmp_path: Path) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    plan = read_yaml(output / "plan.yaml")
    foreign_digest = "sha256:" + "d" * 64
    plan["payload"]["result"]["model_digest"] = foreign_digest
    plan["payload"]["result"]["receipt"]["model_digest"] = foreign_digest
    write_yaml(output / "plan.yaml", plan)
    _rehash_artifact_and_manifest(output, "plan.yaml")

    with pytest.raises(ValueError, match="plan.*bound|compiled model"):
        verify_workflow_artifacts(output)


def test_verifier_recomputes_plan_feasibility_instead_of_trusting_report(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    plan = read_yaml(output / "plan.yaml")
    plan["payload"]["result"]["assignments"] = {
        "owned_units": "0",
        "rental_units": "0",
    }
    plan["payload"]["result"]["objective_value"] = "0"
    write_yaml(output / "plan.yaml", plan)
    _rehash_artifact_and_manifest(output, "plan.yaml")

    with pytest.raises(ValueError, match="verification|constraint|plan"):
        verify_workflow_artifacts(output)


def test_verifier_rejects_rehashed_schedule_bound_to_another_plan(tmp_path: Path) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    schedule = read_yaml(output / "schedule.yaml")
    schedule["payload"]["receipt"]["problem_digest"] = "sha256:" + "e" * 64
    write_yaml(output / "schedule.yaml", schedule)
    _rehash_artifact_and_manifest(output, "schedule.yaml")

    with pytest.raises(ValueError, match="schedule.*bound|scheduling problem"):
        verify_workflow_artifacts(output)


def test_verifier_rejects_rehashed_overlapping_schedule_assignments(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    schedule = read_yaml(output / "schedule.yaml")
    for assignment in schedule["payload"]["assignments"]:
        assignment["start"] = 0
        assignment["end"] = 4
    write_yaml(output / "schedule.yaml", schedule)
    _rehash_artifact_and_manifest(output, "schedule.yaml")

    with pytest.raises(ValueError, match="schedule|overlap|assignment"):
        verify_workflow_artifacts(output)


def test_review_gate_cannot_be_rehashed_into_external_authority(tmp_path: Path) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    review = read_yaml(output / "review.yaml")
    review["payload"]["state"] = "approved"
    review["payload"]["advisory_only"] = False
    review["payload"]["externally_authorized"] = True
    write_yaml(output / "review.yaml", review)
    _rehash_artifact_and_manifest(output, "review.yaml")

    with pytest.raises(ValueError, match="review|advisory|authoriz"):
        verify_workflow_artifacts(output)


def test_verifier_rejects_counterfactual_result_not_bound_to_variant(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    counterfactual = read_yaml(output / "counterfactual.yaml")
    counterfactual["payload"]["result"]["model_digest"] = "sha256:" + "3" * 64
    write_yaml(output / "counterfactual.yaml", counterfactual)
    _rehash_artifact_and_manifest(output, "counterfactual.yaml")

    with pytest.raises(ValueError, match="counterfactual|variant model"):
        verify_workflow_artifacts(output)


def test_generative_explanation_cannot_be_rehashed_into_decision_authority(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    explanation = read_yaml(output / "explanation.yaml")
    explanation["payload"]["receipt"]["mode"] = "generative"
    explanation["payload"]["receipt"]["provider"] = "synthetic-provider"
    explanation["payload"]["candidate_only"] = False
    write_yaml(output / "explanation.yaml", explanation)
    _rehash_artifact_and_manifest(output, "explanation.yaml")

    with pytest.raises(ValueError, match="generative|candidate|explanation"):
        verify_workflow_artifacts(output)


def test_verifier_rejects_rehashed_stress_outcome_with_foreign_model(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    stress = read_yaml(output / "stress.yaml")
    outcome = stress["payload"]["outcomes"][0]
    foreign_digest = "sha256:" + "f" * 64
    outcome["result"]["model_digest"] = foreign_digest
    outcome["result"]["receipt"]["model_digest"] = foreign_digest
    write_yaml(output / "stress.yaml", stress)
    _rehash_artifact_and_manifest(output, "stress.yaml")

    with pytest.raises(ValueError, match="stress|scenario|variant model"):
        verify_workflow_artifacts(output)


def test_verifier_rejects_rehashed_stress_risk_not_derived_from_outcomes(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    stress = read_yaml(output / "stress.yaml")
    stress["payload"]["risk"]["expected_loss"] = "0"
    stress["payload"]["risk"]["conditional_value_at_risk"] = "0"
    write_yaml(output / "stress.yaml", stress)
    _rehash_artifact_and_manifest(output, "stress.yaml")

    with pytest.raises(ValueError, match="stress|risk|CVaR"):
        verify_workflow_artifacts(output)


def test_verifier_rejects_rehashed_explanation_response_digest(tmp_path: Path) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    explanation = read_yaml(output / "explanation.yaml")
    explanation["payload"]["receipt"]["response_digest"] = "sha256:" + "1" * 64
    write_yaml(output / "explanation.yaml", explanation)
    _rehash_artifact_and_manifest(output, "explanation.yaml")

    with pytest.raises(ValueError, match="explanation|response digest"):
        verify_workflow_artifacts(output)


def test_verifier_rejects_rehashed_unbound_explanation_evidence_digest(
    tmp_path: Path,
) -> None:
    output = tmp_path / "output"
    execute_resource_portfolio_workflow(FIXTURES, output)
    explanation = read_yaml(output / "explanation.yaml")
    explanation["payload"]["receipt"]["evidence_digest"] = "sha256:" + "2" * 64
    write_yaml(output / "explanation.yaml", explanation)
    _rehash_artifact_and_manifest(output, "explanation.yaml")

    with pytest.raises(ValueError, match="explanation|evidence digest"):
        verify_workflow_artifacts(output)
