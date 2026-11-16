# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from ruler.applications.resource_portfolio.workflow import (
    WorkflowLimits,
    execute_resource_portfolio_workflow,
    run_sample_portfolio,
    verify_workflow_artifacts,
    write_sample_portfolio_artifacts,
)
from ruler.io import read_yaml, write_yaml
from ruler.paths import REPO_ROOT
from ruler.cli import main

FIXTURES = REPO_ROOT / "data" / "domains" / "construction_fleet" / "tests"


def test_bounded_workflow_executes_all_real_backends_and_closes_artifacts(
    tmp_path: Path,
) -> None:
    run = execute_resource_portfolio_workflow(FIXTURES, tmp_path)

    assert run.status == "pending_review"
    assert run.advisory_only is True
    assert run.externally_authorized is False
    assert run.solver_backends == (
        "scipy_weibull_mle",
        "z3",
        "pyomo_highs",
        "ortools_cp_sat_intervals",
    )
    assert verify_workflow_artifacts(tmp_path) == run

    evidence = read_yaml(tmp_path / "evidence.yaml")["payload"]
    assert len(evidence["normalization"]["canonical_events"]) == 3
    assert evidence["normalization"]["active_events"][0]["start_timestamp"].endswith("Z")
    assert evidence["state_reconstruction"]["intervals"][0]["state"] == "productive"
    assert evidence["state_reconstruction"]["intervals"][-1]["state"] == "unknown"
    assert {profile["profile_type"] for profile in evidence["profiles"]} == {
        "productivity",
        "reliability",
        "state",
        "use",
    }
    assert "scipy.optimize.minimize:L-BFGS-B" in evidence["profile_backends"]

    snapshot = read_yaml(tmp_path / "snapshot.yaml")["payload"]
    assert snapshot["snapshot_id"].startswith("resource_portfolio_snapshot:")
    assert snapshot["content_sha256"] != "sha256:" + "a" * 64

    compilation = read_yaml(tmp_path / "compilation.yaml")["payload"]
    assert compilation["z3_status"] == "sat"
    assert compilation["problem"]["snapshot_digest"] == snapshot["content_sha256"]
    assert compilation["compiled_rule_ids"] == ["minimum_capability_units"]
    assert compilation["rejected_rule_ids"] == ["generated_unapproved_preference"]

    plan = read_yaml(tmp_path / "plan.yaml")["payload"]
    assert plan["result"]["status"] == "OPTIMAL"
    assert plan["result"]["receipt"]["backend_id"] == "pyomo_highs"
    assert plan["result"]["receipt"]["library_version"]
    assert plan["verification"]["verified"] is True
    assert plan["review_status"] == "pending"

    schedule = read_yaml(tmp_path / "schedule.yaml")["payload"]
    assert schedule["status"] == "OPTIMAL"
    assert schedule["receipt"]["backend_id"] == "ortools_cp_sat_intervals"
    assert schedule["receipt"]["library_version"]
    first, second = schedule["assignments"]
    assert first["end"] <= second["start"] or second["end"] <= first["start"]

    stress = read_yaml(tmp_path / "stress.yaml")["payload"]
    assert len(stress["outcomes"]) == 2
    assert stress["risk"] is not None
    assert all(
        outcome["result"]["receipt"]["backend_id"] == "pyomo_highs"
        for outcome in stress["outcomes"]
    )

    counterfactual = read_yaml(tmp_path / "counterfactual.yaml")["payload"]
    assert counterfactual["base_model_digest"] != counterfactual["variant_model_digest"]
    assert counterfactual["result"]["status"] == "OPTIMAL"

    explanation = read_yaml(tmp_path / "explanation.yaml")["payload"]
    assert explanation["receipt"]["mode"] == "deterministic"
    assert explanation["candidate_only"] is False
    assert explanation["draft"]["cited_driver_ids"] == ["required_capacity"]
    review = read_yaml(tmp_path / "review.yaml")["payload"]
    assert review == {
        "run_id": run.run_id,
        "state": "pending_review",
        "advisory_only": True,
        "externally_authorized": False,
        "required_role": "fleet_director",
    }


def test_workflow_semantic_digest_replays_despite_wall_clock_telemetry(
    tmp_path: Path,
) -> None:
    first = execute_resource_portfolio_workflow(FIXTURES, tmp_path / "first")
    second = execute_resource_portfolio_workflow(FIXTURES, tmp_path / "second")
    assert first.run_id == second.run_id
    assert first.run_digest == second.run_digest
    assert [item.semantic_sha256 for item in first.artifacts] == [
        item.semantic_sha256 for item in second.artifacts
    ]


def test_workflow_detects_artifact_tampering(tmp_path: Path) -> None:
    execute_resource_portfolio_workflow(FIXTURES, tmp_path)
    path = tmp_path / "review.yaml"
    artifact = read_yaml(path)
    artifact["payload"]["externally_authorized"] = True
    write_yaml(path, artifact)
    with pytest.raises(ValueError, match="artifact payload digest mismatch"):
        verify_workflow_artifacts(tmp_path)


def test_workflow_enforces_resource_limits_before_solver_execution(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="variable limit exceeded"):
        execute_resource_portfolio_workflow(
            FIXTURES,
            tmp_path,
            limits=WorkflowLimits(max_variables=1),
        )


def test_sample_convenience_apis(tmp_path: Path) -> None:
    assert run_sample_portfolio().status == "pending_review"
    manifest = write_sample_portfolio_artifacts(tmp_path)
    assert manifest == tmp_path / "workflow_run.yaml"
    assert verify_workflow_artifacts(tmp_path).status == "pending_review"


def test_resource_portfolio_cli_executes_workflow_and_evidence_profiler(tmp_path: Path) -> None:
    runner = CliRunner()
    workflow_output = tmp_path / "workflow"
    result = runner.invoke(
        main,
        ["workflow", "resource-portfolio-plan", "--output-dir", str(workflow_output)],
    )
    assert result.exit_code == 0, result.output
    assert verify_workflow_artifacts(workflow_output).status == "pending_review"

    evidence_output = tmp_path / "evidence"
    result = runner.invoke(
        main,
        [
            "portfolio",
            "build-snapshot",
            str(FIXTURES / "evidence.yaml"),
            "--output",
            str(evidence_output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (evidence_output / "normalized_events.yaml").is_file()
    assert (evidence_output / "state_intervals.yaml").is_file()
    assert (evidence_output / "profiles.yaml").is_file()
    assert (evidence_output / "snapshot.yaml").is_file()
