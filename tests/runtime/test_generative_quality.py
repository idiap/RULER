# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for the bounded Codex-exec semantic-quality harness."""

from __future__ import annotations

from copy import deepcopy
import json
import subprocess
from pathlib import Path

import pytest

from ruler.runtime.generative_quality import (
    CriterionVerdict,
    EvaluationResult,
    MAX_QUALITY_INPUT_BYTES,
    QUALITY_CASES_FILE,
    QualityVerdict,
    AutomatedPromotionDecision,
    build_calibration_report,
    build_automated_promotion_decision,
    build_codex_command,
    load_quality_catalogue,
    quality_case_cache_key,
    resolve_quality_consensus,
    run_quality_case,
    stage_quality_case,
    validate_quality_verdict,
    validate_quality_configuration,
    write_consensus_bundle,
)
from ruler.io import read_yaml, stable_hash, write_yaml
from ruler.paths import REPO_ROOT


def _passing_verdict(case_id: str, criteria: list[str]) -> dict[str, object]:
    return {
        "case_id": case_id,
        "verdict": "pass",
        "summary": "The supplied representations preserve the assessed semantics.",
        "criteria": [
            {
                "criterion_id": criterion,
                "verdict": "pass",
                "severity": (
                    "major"
                    if criterion in {"controlled_language_quality", "semantic_minimality"}
                    else "critical"
                ),
                "rationale": "Supported by the supplied bounded evidence.",
                "evidence_ids": ["batch_source_spans"],
                "excerpt": "span_id",
            }
            for criterion in criteria
        ],
    }


def test_quality_catalogue_is_closed_and_resolves_evidence() -> None:
    catalogue = load_quality_catalogue(QUALITY_CASES_FILE)

    assert catalogue.catalogue_id == "generative-kb-quality-cases-v1"
    assert validate_quality_configuration() == []
    assert set(catalogue.profiles) == {"pr", "release"}


def test_staging_accepts_exact_evidence_boundary_and_rejects_one_byte_less(
    tmp_path: Path,
) -> None:
    catalogue = load_quality_catalogue(QUALITY_CASES_FILE)
    case = catalogue.cases[0]
    evidence_bytes = sum((REPO_ROOT / item.path).stat().st_size for item in case.evidence)

    staged_root, _ = stage_quality_case(
        case,
        destination=tmp_path / "exact",
        catalogue=catalogue,
        max_input_bytes=evidence_bytes,
    )
    manifest = read_yaml(staged_root / "input_manifest.yaml")
    prompt = (staged_root / "prompt.txt").read_text(encoding="utf-8")
    reference_lines = [line for line in prompt.splitlines() if line.startswith("- evidence_id=")]

    assert len(prompt) < 10_000
    assert len(reference_lines) == len(case.evidence)
    for evidence, staged in zip(case.evidence, manifest["evidence"], strict=True):
        source = REPO_ROOT / evidence.path
        staged_file = staged_root / staged["staged_path"]
        expected_reference = (
            f"- evidence_id={staged['evidence_id']}; "
            f"staged_path={staged['staged_path']}; "
            f"content_hash={staged['sha256']}; bytes={staged['bytes']}"
        )
        assert expected_reference in reference_lines
        assert staged_file.read_bytes() == source.read_bytes()
        assert source.read_text(encoding="utf-8", errors="replace") not in prompt
        assert staged["source_path"] not in prompt

    with pytest.raises(ValueError, match=f"evidence exceeds {evidence_bytes - 1} bytes"):
        stage_quality_case(
            case,
            destination=tmp_path / "under",
            catalogue=catalogue,
            max_input_bytes=evidence_bytes - 1,
        )


def test_verdict_integrity_is_bound_to_rubric_and_staged_evidence(tmp_path: Path) -> None:
    """Exercise production validation with real staged files, without a judge mock."""

    catalogue = load_quality_catalogue()
    case = catalogue.cases[0]
    staged, _ = stage_quality_case(
        case,
        destination=tmp_path / "case",
        catalogue=catalogue,
        max_input_bytes=MAX_QUALITY_INPUT_BYTES,
    )
    evidence_paths = {
        item.evidence_id: staged / "evidence" / f"{item.evidence_id}{Path(item.path).suffix}"
        for item in case.evidence
    }
    payload = _passing_verdict(case.case_id, case.expected_criteria)

    verdict = validate_quality_verdict(
        case,
        json.dumps(payload),
        rubric_path=staged / "rubric.yaml",
        evidence_paths=evidence_paths,
    )
    assert verdict.verdict == "pass"

    wrong_severity = deepcopy(payload)
    wrong_severity["criteria"][0]["severity"] = "advisory"
    with pytest.raises(ValueError, match="severity must be critical"):
        validate_quality_verdict(
            case,
            json.dumps(wrong_severity),
            rubric_path=staged / "rubric.yaml",
            evidence_paths=evidence_paths,
        )

    uncited = deepcopy(payload)
    uncited["criteria"][0]["evidence_ids"] = []
    with pytest.raises(ValueError, match="judge output schema violation"):
        validate_quality_verdict(
            case,
            json.dumps(uncited),
            rubric_path=staged / "rubric.yaml",
            evidence_paths=evidence_paths,
        )

    invented_excerpt = deepcopy(payload)
    invented_excerpt["criteria"][0]["excerpt"] = "text absent from every staged artifact"
    with pytest.raises(ValueError, match="excerpt is absent from cited evidence"):
        validate_quality_verdict(
            case,
            json.dumps(invented_excerpt),
            rubric_path=staged / "rubric.yaml",
            evidence_paths=evidence_paths,
        )


def test_quality_configuration_rejects_under_cap_and_over_ceiling_profiles(
    tmp_path: Path,
) -> None:
    payload = read_yaml(QUALITY_CASES_FILE)
    profile = payload["profiles"]["pr"]
    case_id = profile["case_ids"][0]
    case = next(item for item in payload["cases"] if item["case_id"] == case_id)
    evidence_bytes = sum((REPO_ROOT / item["path"]).stat().st_size for item in case["evidence"])
    profile["max_input_bytes"] = evidence_bytes - 1
    under_cap_path = tmp_path / "under-cap.yaml"
    write_yaml(under_cap_path, payload)

    errors = validate_quality_configuration(under_cap_path)
    assert any(
        f"evidence totals {evidence_bytes} bytes" in error
        and f"max_input_bytes={evidence_bytes - 1}" in error
        for error in errors
    )

    over_ceiling = deepcopy(read_yaml(QUALITY_CASES_FILE))
    over_ceiling["profiles"]["pr"]["max_input_bytes"] = MAX_QUALITY_INPUT_BYTES + 1
    over_ceiling_path = tmp_path / "over-ceiling.yaml"
    write_yaml(over_ceiling_path, over_ceiling)

    ceiling_errors = validate_quality_configuration(over_ceiling_path)
    assert any(str(MAX_QUALITY_INPUT_BYTES) in error for error in ceiling_errors)


def test_codex_command_is_read_only_ephemeral_and_shell_free(tmp_path: Path) -> None:
    command = build_codex_command(
        case_dir=tmp_path,
        model="gpt-5.4",
        output_path=tmp_path / "result.json",
    )

    assert command[:2] == ["codex", "exec"]
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in command
    assert "--strict-config" in command
    assert "--json" in command
    assert not any("bypass" in argument for argument in command)


def test_runner_validates_structured_verdict_and_discards_content_events(
    monkeypatch, tmp_path: Path
) -> None:
    catalogue = load_quality_catalogue()
    case = catalogue.cases[0]

    def fake_run(command, **kwargs):
        if command == ["codex", "--version"]:
            return subprocess.CompletedProcess(command, 0, "codex-cli test\n", "")
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(
            json.dumps(_passing_verdict(case.case_id, case.expected_criteria)),
            encoding="utf-8",
        )
        stdout = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "secret-session"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "reasoning", "text": "must not persist"},
                    }
                ),
                json.dumps({"type": "turn.completed", "usage": {"input_tokens": 12}}),
            ]
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_quality_case(
        case.case_id,
        profile_name="pr",
        model="gpt-5.4",
        output_dir=tmp_path / "results",
    )

    assert result.status == "pass"
    assert result.cache_key == quality_case_cache_key(
        case.case_id, profile_name="pr", model="gpt-5.4"
    )
    assert result.verdict is not None
    assert "must not persist" not in json.dumps(result.event_summary)
    assert (tmp_path / "results" / result.run_id / "result.yaml").is_file()


def test_runner_uses_temporary_auth_only_codex_home(monkeypatch, tmp_path: Path) -> None:
    catalogue = load_quality_catalogue()
    case = catalogue.cases[0]
    source_home = tmp_path / "source-codex-home"
    source_home.mkdir()
    auth_source = source_home / "auth.json"
    auth_source.write_text('{"test": "credential-placeholder"}', encoding="utf-8")
    (source_home / "config.toml").write_text("model = 'must-not-load'", encoding="utf-8")
    (source_home / "skills").mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source_home))
    monkeypatch.setenv("RULER_UNRELATED_SECRET", "must-not-pass")
    observed_homes: list[Path] = []

    def fake_run(command, **kwargs):
        environment = kwargs["env"]
        isolated_home = Path(environment["CODEX_HOME"])
        observed_homes.append(isolated_home)
        assert isolated_home != source_home
        assert {item.name for item in isolated_home.iterdir()} == {"auth.json"}
        assert (isolated_home / "auth.json").is_symlink()
        assert (isolated_home / "auth.json").resolve() == auth_source.resolve()
        assert "RULER_UNRELATED_SECRET" not in environment
        if command == ["codex", "--version"]:
            return subprocess.CompletedProcess(command, 0, "codex-cli test\n", "")
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text(
            json.dumps(_passing_verdict(case.case_id, case.expected_criteria)),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_quality_case(
        case.case_id,
        profile_name="pr",
        model="gpt-5.4",
        output_dir=tmp_path / "results",
    )

    assert result.status == "pass"
    assert len(observed_homes) == 2
    assert len(set(observed_homes)) == 1
    assert not observed_homes[0].exists()


def test_runner_retains_only_classified_audit_safe_stderr(monkeypatch, tmp_path: Path) -> None:
    catalogue = load_quality_catalogue()
    case = catalogue.cases[0]
    secret = "Bearer audit-secret-must-not-persist"
    local_path = "/Users/example/.codex/skills/broken/SKILL.md"

    def fake_run(command, **kwargs):
        if command == ["codex", "--version"]:
            return subprocess.CompletedProcess(command, 1, "", f"version failure {secret}")
        stderr = "\n".join(
            [
                f"failed to load skill {local_path}: missing YAML frontmatter",
                f"untrusted diagnostic payload {secret}",
                (
                    "Error: Input exceeds the maximum length. "
                    'data: {"input_error_code":"input_too_large",'
                    '"max_chars":1048576,"actual_chars":1168883}'
                ),
            ]
        )
        return subprocess.CompletedProcess(
            command,
            1,
            json.dumps({"type": "thread.started"}),
            stderr,
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_quality_case(
        case.case_id,
        profile_name="pr",
        model="gpt-5.4",
        output_dir=tmp_path / "results",
    )

    assert result.status == "runner_error"
    assert result.codex_version == "unknown"
    assert result.error is not None
    assert "diagnostic=input_too_large" in result.error
    assert "actual_chars=1168883" in result.error
    assert "max_chars=1048576" in result.error
    assert "ignored_skill_load_errors=1" in result.error
    assert "stderr_sha256=" in result.error
    assert secret not in result.error
    assert local_path not in result.error
    assert "untrusted diagnostic payload" not in result.error
    persisted = (tmp_path / "results" / result.run_id / "result.yaml").read_text()
    assert secret not in persisted
    assert local_path not in persisted


def test_dry_run_is_indeterminate_and_does_not_call_judge(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "codex-cli test\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_quality_case(
        "technical_support_fidelity",
        profile_name="pr",
        model="gpt-5.4",
        output_dir=tmp_path / "results",
        dry_run=True,
    )

    assert result.status == "indeterminate"
    assert result.error == "dry_run"
    assert calls == [["codex", "--version"]]


def test_consensus_requires_two_passes_and_never_averages_critical_failure(tmp_path: Path) -> None:
    catalogue = load_quality_catalogue()
    case = catalogue.cases[0]

    def result(run_id: str, verdict: str) -> EvaluationResult:
        payload = _passing_verdict(case.case_id, case.expected_criteria)
        payload["summary"] = f"Independent judgment {run_id}."
        payload["verdict"] = verdict
        if verdict == "fail":
            payload["criteria"][0]["verdict"] = "fail"
        return EvaluationResult.model_validate(
            {
                "run_id": run_id,
                "cache_key": "sha256:cache",
                "case_id": case.case_id,
                "profile": "release",
                "status": verdict,
                "blocking": True,
                "model": "gpt-5.4",
                "command": ["codex", "exec"],
                "catalogue_hash": "sha256:a",
                "rubric_hash": "sha256:b",
                "schema_hash": "sha256:c",
                "input_hash": "sha256:d",
                "codex_version": "test",
                "duration_ms": 1,
                "exit_code": 0,
                "event_summary": [],
                "verdict": payload,
            }
        )

    one_pass = resolve_quality_consensus([result("one", "pass")])
    two_passes = resolve_quality_consensus([result("one", "pass"), result("two", "pass")])
    critical_fail = resolve_quality_consensus(
        [result("one", "pass"), result("three", "fail"), result("two", "pass")]
    )

    assert one_pass.status == "indeterminate"
    assert one_pass.automated_promotion_allowed is False
    assert two_passes.status == "pass"
    assert two_passes.automated_promotion_allowed is True
    assert critical_fail.status == "fail"
    assert critical_fail.automated_promotion_allowed is False

    first = result("independent-one", "pass").model_copy(
        update={"request_id": "sha256:request-one", "response_hash": "sha256:same"}
    )
    replay = result("independent-two", "pass").model_copy(
        update={"request_id": "sha256:request-two", "response_hash": "sha256:same"}
    )
    duplicate_response = resolve_quality_consensus([first, replay])
    assert duplicate_response.status == "indeterminate"
    assert "duplicate request or response" in duplicate_response.reason

    drifted = result("provenance-drift", "pass").model_copy(
        update={"input_hash": "sha256:different"}
    )
    provenance_mismatch = resolve_quality_consensus([result("stable", "pass"), drifted])
    assert provenance_mismatch.status == "indeterminate"
    assert "provenance" in provenance_mismatch.reason

    path = write_consensus_bundle(
        [result("one", "pass"), result("two", "pass")], output_dir=tmp_path
    )
    assert path.is_file()


def test_automated_promotion_decision_is_content_bound() -> None:
    payload = {
        "case_id": "case",
        "consensus_hash": "sha256:consensus",
        "deterministic_gate_hashes": ("sha256:deterministic",),
        "decision": "promote",
        "rationale": "All deterministic and calibrated generative gates passed.",
    }
    decision = AutomatedPromotionDecision(
        decision_id=stable_hash(payload),
        **payload,
    )
    assert decision.decision == "promote"


def test_automated_promotion_requires_passing_consensus_and_deterministic_evidence() -> None:
    catalogue = load_quality_catalogue()
    case = catalogue.cases[0]
    results = []
    for run_id in ("one", "two"):
        verdict = _passing_verdict(case.case_id, case.expected_criteria)
        verdict["summary"] = f"Independent judgment {run_id}."
        results.append(
            EvaluationResult.model_validate(
                {
                    "run_id": run_id,
                    "cache_key": "sha256:cache",
                    "case_id": case.case_id,
                    "profile": "release",
                    "status": "pass",
                    "blocking": True,
                    "model": "gpt-5.4",
                    "command": ["codex", "exec"],
                    "catalogue_hash": "sha256:a",
                    "rubric_hash": "sha256:b",
                    "schema_hash": "sha256:c",
                    "input_hash": "sha256:d",
                    "codex_version": "test",
                    "duration_ms": 1,
                    "exit_code": 0,
                    "event_summary": [],
                    "verdict": verdict,
                }
            )
        )
    consensus = resolve_quality_consensus(results)
    decision = build_automated_promotion_decision(
        consensus, deterministic_gate_hashes=("sha256:deterministic",)
    )
    assert decision.decision == "promote"


def test_calibration_requires_complete_detection_of_seeded_defects() -> None:
    import yaml

    from ruler.runtime.generative_quality import QUALITY_CALIBRATION_FILE

    benchmark = yaml.safe_load(QUALITY_CALIBRATION_FILE.read_text(encoding="utf-8"))
    observed: dict[str, QualityVerdict] = {}
    for item in benchmark["cases"]:
        failed = item["expected_failed_criteria"]
        criterion_id = failed[0] if failed else "controlled_language_quality"
        expected = item["expected_verdict"]
        observed[item["calibration_id"]] = QualityVerdict(
            case_id=item["calibration_id"],
            verdict=expected,
            summary="Seeded-oracle calibration fixture result.",
            criteria=[
                CriterionVerdict(
                    criterion_id=criterion_id,
                    verdict=expected,
                    severity="critical" if expected == "fail" else "major",
                    rationale="Matches the seeded mutation label.",
                    evidence_ids=[],
                )
            ],
        )

    report = build_calibration_report(observed)
    assert report.calibrated is True
    observed.pop("deleted_exception")
    assert build_calibration_report(observed).calibrated is False
