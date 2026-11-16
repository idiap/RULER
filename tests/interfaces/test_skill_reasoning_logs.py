# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Tests for catalogue profiles and honest, invocation-backed skill events."""

from __future__ import annotations

import pytest

from ruler.interfaces.skill_reasoning_logs import (
    EXPECTED_CANONICAL_SKILL_COUNT,
    SkillArtifactEvidence,
    SkillReasoningEvent,
    build_skill_reasoning_profiles,
    load_skill_reasoning_events,
    record_skill_reasoning_event,
    validate_skill_reasoning_log_artifacts,
    write_skill_reasoning_log_artifacts,
)
from ruler.io import read_yaml


def test_every_canonical_skill_has_one_understandable_profile() -> None:
    profiles = build_skill_reasoning_profiles()

    assert len(profiles) == EXPECTED_CANONICAL_SKILL_COUNT
    assert len({profile.skill_id for profile in profiles}) == len(profiles)
    assert all(profile.purpose and profile.stages for profile in profiles)
    assert all(
        profile.observable_inputs
        and profile.observable_actions
        and profile.observable_evidence
        and profile.observable_outputs
        and profile.decision_impact
        for profile in profiles
    )
    assert all("not evidence of execution" in profile.limitations[0] for profile in profiles)
    assert all(not profile.backend_ids for profile in profiles if not profile.executable)
    assert any(profile.mode_source == "binding" for profile in profiles)
    assert all(profile.mode_source in {"binding", "description_inference"} for profile in profiles)


def test_artifacts_separate_profiles_from_actual_execution(tmp_path) -> None:
    paths = write_skill_reasoning_log_artifacts(tmp_path)

    assert validate_skill_reasoning_log_artifacts(tmp_path) == []
    assert (
        len(paths["jsonl"].read_text(encoding="utf-8").splitlines())
        == EXPECTED_CANONICAL_SKILL_COUNT
    )
    assert paths["events"].read_text(encoding="utf-8") == ""
    manifest = read_yaml(paths["manifest"])
    assert (
        manifest["profile_coverage"]
        == f"{EXPECTED_CANONICAL_SKILL_COUNT}/{EXPECTED_CANONICAL_SKILL_COUNT}"
    )
    assert manifest["execution_coverage"] == f"0/{EXPECTED_CANONICAL_SKILL_COUNT}"
    assert manifest["actual_event_count"] == 0


def test_actual_event_requires_real_identity_artifacts_and_public_reasoning(tmp_path) -> None:
    event = SkillReasoningEvent(
        skill_id="policy-reasoning-log-guardian",
        workflow_id="reasoning-logs",
        invocation_id="test-invocation",
        sequence=1,
        status="succeeded",
        mode="deterministic",
        stage="reasoning-log",
        question="Are the public reasoning artifacts complete?",
        observable_move="Compared the emitted profile identifiers with the canonical inventory.",
        outcome="Every canonical skill has one profile.",
        decision_impact="The catalogue can now be audited consistently.",
        artifacts=(
            SkillArtifactEvidence(
                role="validation",
                artifact_id="build/ruler/skill_reasoning_logs/manifest.yaml",
                digest="sha256:" + "a" * 64,
            ),
        ),
        validation_commands=("uv run ruler validate skill-reasoning-logs",),
        validation_status="passed",
    )

    path = record_skill_reasoning_event(event, tmp_path)

    assert load_skill_reasoning_events(path) == [event]


def test_actual_event_rejects_secret_bearing_explanations() -> None:
    with pytest.raises(ValueError, match="credentials or secrets"):
        SkillReasoningEvent(
            skill_id="policy-reasoning-log-guardian",
            workflow_id="reasoning-logs",
            invocation_id="unsafe",
            sequence=1,
            status="failed",
            mode="deterministic",
            stage="reasoning-log",
            question="Why did the request fail?",
            observable_move="Read API key=do-not-log-this from configuration.",
            outcome="Request rejected.",
            decision_impact="None.",
        )


def test_succeeded_event_requires_artifact_evidence() -> None:
    with pytest.raises(ValueError, match="require typed artifact evidence"):
        SkillReasoningEvent(
            skill_id="policy-reasoning-log-guardian",
            workflow_id="reasoning-logs",
            invocation_id="missing-evidence",
            sequence=1,
            status="succeeded",
            mode="deterministic",
            stage="reasoning-log",
            question="Was the output emitted?",
            observable_move="Completed the public rendering stage.",
            outcome="Reported completion without an artifact.",
            decision_impact="The claim cannot be audited.",
        )


def test_validator_checks_mode_sequence_and_terminal_state(tmp_path) -> None:
    paths = write_skill_reasoning_log_artifacts(tmp_path)
    started = SkillReasoningEvent(
        skill_id="policy-reasoning-log-guardian",
        workflow_id="reasoning-logs",
        invocation_id="incomplete",
        sequence=2,
        status="started",
        mode="hybrid",
        stage="reasoning-log",
        question="Has rendering started?",
        observable_move="Opened the declared input artifacts.",
        outcome="Rendering remains in progress.",
        decision_impact="No completed output is yet available.",
    )
    record_skill_reasoning_event(started, tmp_path)
    write_skill_reasoning_log_artifacts(tmp_path)

    errors = validate_skill_reasoning_log_artifacts(tmp_path)

    assert any("does not match" in error for error in errors)
    assert any("contiguous from 1" in error for error in errors)
    assert any("terminal status" in error for error in errors)
    assert paths["events"].exists()
