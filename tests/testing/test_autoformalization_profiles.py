# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deterministic tests for blind criticism, replay identity, and profile gates."""

from __future__ import annotations

from pathlib import Path

from ruler.io import stable_hash
from ruler.testing.autoformalization_profiles import (
    AutoformalizationProfile,
    BlindCriticVerdict,
    CRITIC_DIMENSIONS,
    ContentAddressedReplayCache,
    CriticCalibrationBinding,
    CriticDimensionScore,
    DeterministicCaseEvidence,
    PROFILES,
    ProfileCaseRun,
    ProviderCallReceipt,
    build_blind_critic_input,
    evaluate_profile,
    run_profile,
)


def _receipt(
    role: str,
    identifier: str,
    *,
    kind: str = "fresh",
    output: dict | None = None,
    seed: str | None = None,
) -> ProviderCallReceipt:
    payload = output or {"candidate": identifier}
    return ProviderCallReceipt(
        execution_id=identifier,
        role=role,
        execution_kind=kind,
        provider="codex-exec",
        model="gpt-5.4",
        deployment="public",
        prompt_version=f"{role}-v1",
        prompt_sha256=stable_hash(f"{role}-prompt"),
        source_sha256=stable_hash("source bytes"),
        config_sha256=stable_hash({"temperature": 0}),
        output_sha256=stable_hash(payload),
        seed=seed or identifier,
        terminal_status="succeeded",
        source_execution_id="origin" if kind == "replay" else None,
    )


def _critic(producer: ProviderCallReceipt, identifier: str = "critic-1") -> BlindCriticVerdict:
    receipt = _receipt("critic", identifier)
    return BlindCriticVerdict(
        blind_case_id="blind:abc",
        producer_execution_id=producer.execution_id,
        critic_receipt=receipt,
        dimensions=tuple(
            CriticDimensionScore(
                dimension=dimension,
                score=1.0,
                verdict="pass",
                evidence_span_ids=("span-1",),
            )
            for dimension in CRITIC_DIMENSIONS
        ),
        overall="pass",
    )


def _deterministic(*, blockers: tuple[str, ...] = ()) -> DeterministicCaseEvidence:
    return DeterministicCaseEvidence(
        evidence_sha256=stable_hash("deterministic evidence"),
        blockers=blockers,
        behavioral_total=6,
        behavioral_passed=6,
        mutations_total=10,
        mutations_killed=10,
        backend_checks=2,
        backend_agreements=2,
    )


def _calibration(critic: BlindCriticVerdict, *, calibrated: bool = True):
    receipt = critic.critic_receipt
    return CriticCalibrationBinding(
        certification_id=stable_hash("certification identity"),
        certification_sha256=stable_hash("certification bytes"),
        calibrated=calibrated,
        provider=receipt.provider,
        model=receipt.model,
        deployment=receipt.deployment,
        prompt_version=receipt.prompt_version,
        config_sha256=receipt.config_sha256,
    )


def test_blind_critic_input_contains_source_and_candidate_but_no_oracle_labels() -> None:
    producer = _receipt("producer", "producer-1")
    payload = build_blind_critic_input(
        source_payload={"sources": [{"content": "Article 1 applies unless X."}]},
        candidate_payload={"spans": [{"span_id": "span-1"}], "rules": []},
        producer=producer,
    )

    assert payload["blind_case_id"].startswith("blind:")
    assert payload["producer_execution_id"] == producer.execution_id
    assert tuple(payload["required_dimensions"]) == CRITIC_DIMENSIONS
    assert "oracle" not in payload
    assert "expected" not in payload

    try:
        build_blind_critic_input(
            source_payload={"sources": [{"content": "safe", "oracle": "hidden"}]},
            candidate_payload={"rules": []},
            producer=producer,
        )
    except ValueError as exc:
        assert "evaluator-only" in str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("nested oracle metadata reached the critic")


def test_favorable_calibrated_critic_cannot_override_deterministic_blocker() -> None:
    producer = _receipt("producer", "producer-1")
    critic = _critic(producer)
    profile = AutoformalizationProfile(
        name="release",
        case_ids=("case-1",),
        fresh_producer_runs=1,
        fresh_critic_runs=1,
        allow_replay=False,
        blocking=True,
        require_calibration=True,
    )
    run = ProfileCaseRun(
        case_id="case-1",
        producer_receipts=(producer,),
        critic_verdicts=(critic,),
        calibration=_calibration(critic),
        deterministic=_deterministic(blockers=("source_digest_mismatch",)),
        structured_output_valid=True,
        abstention_correct=True,
        invariants_total=4,
        invariants_recalled=4,
        unsupported_additions=0,
    )

    report = evaluate_profile(profile, (run,))

    assert report.passed is False
    assert report.dispositions[0].status == "blocked"
    assert "deterministic:source_digest_mismatch" in report.dispositions[0].reasons


def test_release_critic_is_bound_to_exact_calibrated_configuration() -> None:
    producer = _receipt("producer", "producer-1")
    critic = _critic(producer)
    profile = AutoformalizationProfile(
        name="release",
        case_ids=("case-1",),
        fresh_producer_runs=1,
        fresh_critic_runs=1,
        allow_replay=False,
        blocking=True,
        require_calibration=True,
    )
    stale = _calibration(critic).model_copy(update={"config_sha256": stable_hash("old config")})
    run = ProfileCaseRun(
        case_id="case-1",
        producer_receipts=(producer,),
        critic_verdicts=(critic,),
        calibration=stale,
        deterministic=_deterministic(),
        structured_output_valid=True,
        abstention_correct=True,
        invariants_total=2,
        invariants_recalled=2,
        unsupported_additions=0,
    )

    assert evaluate_profile(profile, (run,)).dispositions[0].reasons == (
        "critic:stale_or_mismatched_calibration",
    )


def test_content_addressed_cache_replay_is_never_reported_as_fresh(tmp_path: Path) -> None:
    output = {"candidate": "one"}
    fresh = _receipt("producer", "producer-1", output=output)
    cache = ContentAddressedReplayCache(tmp_path)
    target = cache.store(fresh, output)

    replay, loaded = cache.replay(fresh)

    assert target.is_file()
    assert loaded == output
    assert replay.execution_kind == "replay"
    assert replay.source_execution_id == fresh.execution_id
    assert replay.execution_id != fresh.execution_id
    assert replay.cache_key == fresh.cache_key

    different_config = fresh.model_copy(update={"config_sha256": stable_hash("changed")})
    assert different_config.cache_key != fresh.cache_key


def test_profiles_cover_realistic_styles_and_measure_required_metrics() -> None:
    assert set(PROFILES) == {"local", "pr", "integration", "release", "drift"}
    assert PROFILES["local"].allow_replay is True
    assert PROFILES["pr"].blocking is False
    assert PROFILES["integration"].fresh_critic_runs == 1
    assert PROFILES["release"].fresh_producer_runs >= 3
    assert PROFILES["release"].require_calibration is True
    assert PROFILES["drift"].fresh_critic_runs >= 2

    profile = AutoformalizationProfile(
        name="local",
        case_ids=("case-1",),
        fresh_producer_runs=0,
        fresh_critic_runs=0,
        allow_replay=True,
        blocking=True,
        require_calibration=False,
    )
    replay = _receipt("producer", "replay-1", kind="replay")
    run = ProfileCaseRun(
        case_id="case-1",
        producer_receipts=(replay,),
        deterministic=_deterministic(),
        structured_output_valid=True,
        abstention_correct=True,
        invariants_total=5,
        invariants_recalled=5,
        unsupported_additions=0,
    )
    report = evaluate_profile(profile, (run,))
    assert report.passed
    assert set(report.metrics) == {
        "structured_output_validity",
        "abstention_correctness",
        "invariant_recall",
        "unsupported_addition_rate",
        "mutation_kill_rate",
        "cross_engine_agreement",
        "run_output_stability",
    }


def test_named_profile_runner_persists_content_addressed_report(tmp_path: Path) -> None:
    runs = tuple(
        ProfileCaseRun(
            case_id=case_id,
            deterministic=_deterministic(),
            structured_output_valid=True,
            abstention_correct=True,
            invariants_total=1,
            invariants_recalled=1,
            unsupported_additions=0,
        )
        for case_id in PROFILES["local"].case_ids
    )

    report = run_profile("local", runs, output_dir=tmp_path)

    persisted = list(tmp_path.glob("local-*.yaml"))
    assert report.passed
    assert len(persisted) == 1
    assert report.report_id.split(":", 1)[1][:20] in persisted[0].name
