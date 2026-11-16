# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Executable blind calibration and recertification tests with a mocked Codex CLI."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from ruler.cli import main
from ruler.io import read_yaml, stable_hash, write_yaml
from ruler.runtime.generative_calibration import (
    CALIBRATION_FIXTURES_FILE,
    CalibrationObservation,
    calculate_calibration,
    calibration_order,
    load_calibration_fixtures,
    run_calibration_suite,
)
from ruler.runtime.generative_quality import QUALITY_CALIBRATION_FILE, QUALITY_RUBRIC_FILE


def _mock_codex(command, **kwargs):
    prompt = kwargs["input"]
    fixtures = read_yaml(CALIBRATION_FIXTURES_FILE)["cases"]
    benchmark = {
        item["calibration_id"]: item for item in read_yaml(QUALITY_CALIBRATION_FILE)["cases"]
    }
    fixture = next(item for item in fixtures if item["evidence"] in prompt)
    label = benchmark[fixture["calibration_id"]]
    blind_id = next(
        line.split(": ", 1)[1] for line in prompt.splitlines() if line.startswith("Blind case ID:")
    )
    criteria = read_yaml(QUALITY_RUBRIC_FILE)["criteria"]
    failed = set(label["expected_failed_criteria"])
    verdict = {
        "case_id": blind_id,
        "verdict": label["expected_verdict"],
        "summary": "Mocked independently seeded calibration verdict.",
        "criteria": [
            {
                "criterion_id": item["criterion_id"],
                "verdict": "fail" if item["criterion_id"] in failed else "pass",
                "severity": item["severity"],
                "rationale": "The bounded fixture supports this calibration verdict.",
                "evidence_ids": ["calibration_fixture"],
                "excerpt": "bounded fixture",
            }
            for item in criteria
        ],
    }
    output = Path(command[command.index("--output-last-message") + 1])
    output.write_text(json.dumps(verdict), encoding="utf-8")
    return subprocess.CompletedProcess(command, 0, "", "")


def test_fixture_coverage_and_blind_order_are_closed_and_deterministic() -> None:
    fixtures = load_calibration_fixtures()
    benchmark_ids = {
        item["calibration_id"] for item in read_yaml(QUALITY_CALIBRATION_FILE)["cases"]
    }
    assert {item.calibration_id for item in fixtures.cases} == benchmark_ids
    first = calibration_order(fixtures, judge_config_hash="sha256:config", repetition=1)
    second = calibration_order(fixtures, judge_config_hash="sha256:config", repetition=1)
    shifted = calibration_order(fixtures, judge_config_hash="sha256:config", repetition=2)
    assert first == second
    assert [item.calibration_id for item in first] != [item.calibration_id for item in shifted]


def test_mocked_codex_suite_enforces_thresholds_and_emits_recertification(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(subprocess, "run", _mock_codex)
    certification = run_calibration_suite(
        model="gpt-5.4",
        codex_version="codex-cli-test",
        judge_config={"prompt": "v2", "temperature": 0},
        output_dir=tmp_path,
    )
    observations = read_yaml(tmp_path / "observations.yaml")
    assert certification.calibrated is True
    assert certification.finite_critical_detection == 1.0
    assert certification.major_recall == 1.0
    assert certification.false_positive_rate == 0.0
    assert certification.evidence_reference_validity == 1.0
    assert len(observations) == certification.total_cases * 2
    assert all(item["blind_case_id"].startswith("blind:") for item in observations)
    assert all(item["calibration_id"] not in item["blind_case_id"] for item in observations)

    regressed: list[CalibrationObservation] = []
    for raw in observations:
        observation = CalibrationObservation.model_validate(raw)
        if observation.calibration_id == "deleted_exception":
            verdict = observation.verdict.model_copy(
                update={
                    "verdict": "pass",
                    "criteria": [
                        item.model_copy(update={"verdict": "pass"})
                        for item in observation.verdict.criteria
                    ],
                }
            )
            payload = observation.model_dump(mode="python", exclude={"observation_id"})
            payload["verdict"] = verdict
            observation = CalibrationObservation(
                observation_id=stable_hash({**payload, "verdict": verdict.model_dump(mode="json")}),
                **payload,
            )
        regressed.append(observation)
    regressed_certification = calculate_calibration(
        regressed,
        model="gpt-5.4",
        codex_version="codex-cli-test",
        judge_config_hash=certification.judge_config_hash,
        fixture_set=load_calibration_fixtures(),
        repetitions=2,
    )
    assert regressed_certification.calibrated is False
    assert "finite_critical_detection" in regressed_certification.threshold_failures

    judge_config = tmp_path / "judge_config.yaml"
    write_yaml(judge_config, {"prompt": "v2", "temperature": 0})
    result = CliRunner().invoke(
        main,
        [
            "workflow",
            "calibrate-generative-judge",
            "--model",
            "gpt-5.4",
            "--codex-version",
            "codex-cli-test",
            "--judge-config",
            str(judge_config),
            "--results",
            str(tmp_path / "observations.yaml"),
            "--output-dir",
            str(tmp_path / "recalculated"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "calibrated=True" in result.output

    write_yaml(judge_config, {"prompt": "v3", "temperature": 0})
    stale = CliRunner().invoke(
        main,
        [
            "workflow",
            "calibrate-generative-judge",
            "--model",
            "gpt-5.4",
            "--codex-version",
            "codex-cli-test",
            "--judge-config",
            str(judge_config),
            "--results",
            str(tmp_path / "observations.yaml"),
        ],
    )
    assert stale.exit_code != 0
    assert "judge config differs" in str(stale.exception)


def test_schema_invalid_mocked_judge_output_cannot_be_calibrated(monkeypatch, tmp_path) -> None:
    def invalid(command, **kwargs):
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text('{"case_id":"blind:wrong","verdict":"pass"}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", invalid)
    with pytest.raises(Exception):
        run_calibration_suite(
            model="gpt-5.4",
            codex_version="codex-cli-test",
            judge_config={"prompt": "v2"},
            output_dir=tmp_path,
        )
