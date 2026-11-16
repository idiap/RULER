# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from ruler.applications.resource_portfolio.compiler import (
    CompilationRequest,
    compile_rules,
)
from ruler.applications.resource_portfolio.synthetic import (
    SyntheticPortfolioConfig,
    generate_synthetic_portfolio_inputs,
    load_synthetic_config,
    verify_synthetic_portfolio_inputs,
    write_synthetic_portfolio_inputs,
)
from ruler.applications.resource_portfolio.workflow import (
    build_evidence_snapshot,
    execute_resource_portfolio_workflow,
)
from ruler.io import read_yaml, write_yaml
from ruler.cli import main

CONFIGS = Path("data/domains/construction_fleet/synthetic")


def test_seeded_generation_is_reproducible_and_scaled() -> None:
    config = SyntheticPortfolioConfig(
        seed=8128,
        resource_count=5,
        event_days=2,
        events_per_resource_per_day=4,
        tasks_per_resource=3,
        scenario_count=4,
    )

    first_payloads, first_manifest = generate_synthetic_portfolio_inputs(config)
    second_payloads, second_manifest = generate_synthetic_portfolio_inputs(config)

    assert first_payloads == second_payloads
    assert first_manifest == second_manifest
    assert first_manifest.resource_count == 5
    assert first_manifest.base_event_count == 40
    assert first_manifest.task_count == 15
    assert first_manifest.scenario_count == 4
    assert len(first_payloads["compile.yaml"]["variables"]) == 6
    assert all(
        event["provenance"]["source_system"] == "ruler_synthetic_generator"
        for event in first_payloads["evidence.yaml"]["events"]
    )


def test_anomalies_duplicates_and_corrections_exercise_normalization() -> None:
    config = SyntheticPortfolioConfig(
        resource_count=1,
        event_days=1,
        events_per_resource_per_day=2,
        tasks_per_resource=1,
        scenario_count=1,
        anomaly_rate=1,
        duplicate_rate=1,
        correction_rate=1,
    )
    payloads, manifest = generate_synthetic_portfolio_inputs(config)

    normalized, reconstructed, _, snapshot = build_evidence_snapshot(payloads["evidence.yaml"])

    assert manifest.duplicate_count == manifest.base_event_count
    assert manifest.correction_count == manifest.base_event_count
    assert manifest.anomaly_count == manifest.base_event_count
    assert len(normalized.duplicate_event_ids) == manifest.duplicate_count
    assert len(normalized.correction_pairs) == manifest.correction_count
    assert reconstructed.overlap_diagnostics
    assert snapshot.events


def test_written_inputs_are_digest_verified_and_tampering_is_detected(
    tmp_path: Path,
) -> None:
    config = load_synthetic_config(CONFIGS / "default.yaml")
    manifest = write_synthetic_portfolio_inputs(config, tmp_path)

    assert verify_synthetic_portfolio_inputs(tmp_path) == manifest
    with pytest.raises(FileExistsError, match="already exists"):
        write_synthetic_portfolio_inputs(config, tmp_path)

    evidence = read_yaml(tmp_path / "evidence.yaml")
    evidence["domain_id"] = "tampered"
    write_yaml(tmp_path / "evidence.yaml", evidence)
    with pytest.raises(ValueError, match="digest mismatch: evidence.yaml"):
        verify_synthetic_portfolio_inputs(tmp_path)


def test_feasible_generated_directory_executes_real_workflow(tmp_path: Path) -> None:
    config = SyntheticPortfolioConfig(
        seed=77,
        resource_count=3,
        event_days=2,
        events_per_resource_per_day=2,
        tasks_per_resource=2,
        scenario_count=2,
        anomaly_rate="0.2",
        duplicate_rate="0.2",
        correction_rate="0.2",
    )
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    write_synthetic_portfolio_inputs(config, input_dir)

    run = execute_resource_portfolio_workflow(input_dir, output_dir)

    assert run.status == "pending_review"
    assert {"z3", "pyomo_highs", "ortools_cp_sat_intervals"} <= set(run.solver_backends)
    assert (output_dir / "workflow_run.yaml").is_file()


def test_infeasible_variant_is_typed_and_rejected_by_real_z3() -> None:
    config = load_synthetic_config(CONFIGS / "infeasible.yaml")
    payloads, manifest = generate_synthetic_portfolio_inputs(config)
    request = CompilationRequest.model_validate(payloads["compile.yaml"])

    assert manifest.expected_compilation_status == "unsat"
    with pytest.raises(ValueError, match="unsatisfiable"):
        compile_rules(request)


@pytest.mark.parametrize("name", ["default.yaml", "scaled.yaml", "infeasible.yaml"])
def test_packaged_generation_configs_are_strict_and_valid(name: str) -> None:
    config = load_synthetic_config(CONFIGS / name)
    payloads, manifest = generate_synthetic_portfolio_inputs(config)

    assert tuple(payloads) == (
        "evidence.yaml",
        "compile.yaml",
        "model.yaml",
        "schedule.yaml",
        "stress.yaml",
        "explanation.yaml",
    )
    assert manifest.configuration_sha256.startswith("sha256:")


@pytest.mark.parametrize(
    ("config_name", "expected_status"),
    [("default.yaml", "passed"), ("infeasible.yaml", "expected_infeasible")],
)
def test_synthetic_cli_executes_expected_solver_path(
    tmp_path: Path, config_name: str, expected_status: str
) -> None:
    output = tmp_path / config_name.removesuffix(".yaml")
    result = CliRunner().invoke(
        main,
        [
            "portfolio",
            "generate-synthetic",
            str(CONFIGS / config_name),
            "--seed",
            "31415",
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert read_yaml(output / "synthetic_test.yaml")["status"] == expected_status
    if expected_status == "passed":
        assert (output / "workflow_run" / "workflow_run.yaml").is_file()
    else:
        receipt = read_yaml(output / "infeasibility.yaml")
        assert receipt["backend_id"] == "z3"
        assert receipt["status"] == "unsat"
        assert receipt["expected"] is True
