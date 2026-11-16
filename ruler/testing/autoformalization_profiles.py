# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Governed generative autoformalization profiles and blind-critic controls.

This module deliberately separates evidence collection from disposition.  Provider
calls create immutable receipts; deterministic gates, calibration, and the profile
policy decide whether those receipts are sufficient.  Replayed provider output is
useful local evidence, but is never relabelled as a fresh model execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ruler.io import stable_hash, write_yaml
from ruler.kb.generative_autoformalization import GenerativeTransport

SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
CRITIC_DIMENSIONS = (
    "source_fidelity",
    "semantic_preservation",
    "predicate_grounding",
    "provenance",
    "epistemic_discipline",
    "controlled_language_quality",
)


class ProviderCallReceipt(BaseModel):
    """Content-bound identity for one producer or critic invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_id: str
    role: Literal["producer", "critic"]
    execution_kind: Literal["fresh", "replay"]
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    deployment: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=SHA256_PATTERN)
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    config_sha256: str = Field(pattern=SHA256_PATTERN)
    output_sha256: str = Field(pattern=SHA256_PATTERN)
    seed: str = Field(min_length=1)
    terminal_status: Literal["succeeded", "failed", "timeout"]
    source_execution_id: str | None = None

    @property
    def cache_key(self) -> str:
        """Exact provider/model/prompt/source/config cache identity."""

        return stable_hash(
            {
                "provider": self.provider,
                "model": self.model,
                "deployment": self.deployment,
                "role": self.role,
                "prompt_sha256": self.prompt_sha256,
                "source_sha256": self.source_sha256,
                "config_sha256": self.config_sha256,
                # Seed is an explicit part of the effective generation configuration.
                "seed": self.seed,
            }
        )

    @model_validator(mode="after")
    def replay_has_origin(self) -> "ProviderCallReceipt":
        if self.execution_kind == "fresh" and self.source_execution_id is not None:
            raise ValueError("fresh execution cannot cite a replay origin")
        if self.execution_kind == "replay" and not self.source_execution_id:
            raise ValueError("replay must cite its original fresh execution")
        return self


class CriticDimensionScore(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dimension: Literal[
        "source_fidelity",
        "semantic_preservation",
        "predicate_grounding",
        "provenance",
        "epistemic_discipline",
        "controlled_language_quality",
    ]
    score: float = Field(ge=0.0, le=1.0)
    verdict: Literal["pass", "fail", "indeterminate"]
    evidence_span_ids: tuple[str, ...] = Field(min_length=1)


class BlindCriticVerdict(BaseModel):
    """Supplementary judgment over only public source and candidate output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blind_case_id: str
    producer_execution_id: str
    critic_receipt: ProviderCallReceipt
    dimensions: tuple[CriticDimensionScore, ...]
    overall: Literal["pass", "fail", "indeterminate"]

    @model_validator(mode="after")
    def complete_and_independent(self) -> "BlindCriticVerdict":
        if self.critic_receipt.role != "critic":
            raise ValueError("critic verdict requires a critic receipt")
        names = [item.dimension for item in self.dimensions]
        if set(names) != set(CRITIC_DIMENSIONS) or len(names) != len(CRITIC_DIMENSIONS):
            raise ValueError("critic must score every dimension exactly once")
        if self.producer_execution_id == self.critic_receipt.execution_id:
            raise ValueError("producer and critic executions must be independent")
        if any(item.verdict != "pass" for item in self.dimensions) and self.overall == "pass":
            raise ValueError("non-passing critic dimension cannot yield overall pass")
        return self


class BlindCriticDraft(BaseModel):
    """Strict provider output before execution provenance is attached."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    blind_case_id: str
    dimensions: tuple[CriticDimensionScore, ...]
    overall: Literal["pass", "fail", "indeterminate"]

    @model_validator(mode="after")
    def complete(self) -> "BlindCriticDraft":
        names = [item.dimension for item in self.dimensions]
        if set(names) != set(CRITIC_DIMENSIONS) or len(names) != len(CRITIC_DIMENSIONS):
            raise ValueError("critic must score every dimension exactly once")
        if any(item.verdict != "pass" for item in self.dimensions) and self.overall == "pass":
            raise ValueError("non-passing critic dimension cannot yield overall pass")
        return self


class CriticCalibrationBinding(BaseModel):
    """Exact calibration certification authorized for one critic configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    certification_id: str = Field(pattern=SHA256_PATTERN)
    certification_sha256: str = Field(pattern=SHA256_PATTERN)
    calibrated: bool
    provider: str
    model: str
    deployment: str
    prompt_version: str = Field(min_length=1)
    config_sha256: str = Field(pattern=SHA256_PATTERN)

    def authorizes(self, receipt: ProviderCallReceipt) -> bool:
        return (
            self.calibrated
            and receipt.role == "critic"
            and receipt.provider == self.provider
            and receipt.model == self.model
            and receipt.deployment == self.deployment
            and receipt.prompt_version == self.prompt_version
            and receipt.config_sha256 == self.config_sha256
        )


class DeterministicCaseEvidence(BaseModel):
    """Non-generative gates that remain authoritative over model opinions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_sha256: str = Field(pattern=SHA256_PATTERN)
    blockers: tuple[str, ...] = ()
    behavioral_total: int = Field(ge=0)
    behavioral_passed: int = Field(ge=0)
    mutations_total: int = Field(ge=0)
    mutations_killed: int = Field(ge=0)
    backend_checks: int = Field(ge=0)
    backend_agreements: int = Field(ge=0)

    @model_validator(mode="after")
    def counts_are_bounded(self) -> "DeterministicCaseEvidence":
        if self.behavioral_passed > self.behavioral_total:
            raise ValueError("behavioral passes exceed executed cases")
        if self.mutations_killed > self.mutations_total:
            raise ValueError("mutation kills exceed generated mutations")
        if self.backend_agreements > self.backend_checks:
            raise ValueError("backend agreements exceed checks")
        return self


class AutoformalizationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Literal["local", "pr", "integration", "release", "drift"]
    case_ids: tuple[str, ...] = Field(min_length=1)
    fresh_producer_runs: int = Field(ge=0)
    fresh_critic_runs: int = Field(ge=0)
    allow_replay: bool
    blocking: bool
    require_calibration: bool
    require_complete_deterministic_evidence: bool = True


class ProfileCaseRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    producer_receipts: tuple[ProviderCallReceipt, ...] = ()
    critic_verdicts: tuple[BlindCriticVerdict, ...] = ()
    calibration: CriticCalibrationBinding | None = None
    deterministic: DeterministicCaseEvidence
    structured_output_valid: bool
    abstention_correct: bool
    invariants_total: int = Field(ge=0)
    invariants_recalled: int = Field(ge=0)
    unsupported_additions: int = Field(ge=0)


class CaseDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    status: Literal["pass", "advisory", "blocked"]
    reasons: tuple[str, ...]


class ProfileRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_id: str
    profile: str
    dispositions: tuple[CaseDisposition, ...]
    metrics: dict[str, float]
    provenance_sha256: str = Field(pattern=SHA256_PATTERN)
    passed: bool

    @model_validator(mode="after")
    def content_addressed(self) -> "ProfileRunReport":
        expected = stable_hash(self.model_dump(mode="json", exclude={"report_id"}))
        if self.report_id != expected:
            raise ValueError("profile report ID does not match its contents")
        return self


PROFILES: dict[str, AutoformalizationProfile] = {
    "local": AutoformalizationProfile(
        name="local",
        case_ids=(
            "legal_conditional_exception_permission",
            "procurement_thresholds_table",
            "regulatory_temporal_amendment",
            "coreference_open_texture",
        ),
        fresh_producer_runs=0,
        fresh_critic_runs=0,
        allow_replay=True,
        blocking=True,
        require_calibration=False,
    ),
    "pr": AutoformalizationProfile(
        name="pr",
        case_ids=(
            "legal_conditional_exception_permission",
            "procurement_thresholds_table",
            "coreference_open_texture",
        ),
        fresh_producer_runs=1,
        fresh_critic_runs=0,
        allow_replay=False,
        blocking=False,
        require_calibration=False,
    ),
    "integration": AutoformalizationProfile(
        name="integration",
        case_ids=(
            "legal_conditional_exception_permission",
            "procurement_thresholds_table",
            "regulatory_temporal_amendment",
            "coreference_open_texture",
        ),
        fresh_producer_runs=1,
        fresh_critic_runs=1,
        allow_replay=False,
        blocking=False,
        require_calibration=False,
    ),
    "release": AutoformalizationProfile(
        name="release",
        case_ids=(
            "legal_conditional_exception_permission",
            "procurement_thresholds_table",
            "regulatory_temporal_amendment",
            "coreference_open_texture",
        ),
        fresh_producer_runs=3,
        fresh_critic_runs=2,
        allow_replay=False,
        blocking=True,
        require_calibration=True,
    ),
    "drift": AutoformalizationProfile(
        name="drift",
        case_ids=(
            "legal_conditional_exception_permission",
            "procurement_thresholds_table",
            "regulatory_temporal_amendment",
            "coreference_open_texture",
        ),
        fresh_producer_runs=2,
        fresh_critic_runs=2,
        allow_replay=False,
        blocking=True,
        require_calibration=True,
    ),
}


def build_blind_critic_input(
    *,
    source_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    producer: ProviderCallReceipt,
) -> dict[str, Any]:
    """Build the critic bundle without oracle labels or producer-side authority."""

    forbidden = {
        "oracle",
        "expected",
        "expected_disposition",
        "semantic_invariants",
        "required_mutations",
        "behavioral_cases",
        "forbidden_claims",
    }

    def keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {key for item in value.values() for key in keys(item)}
        if isinstance(value, (list, tuple)):
            return {key for item in value for key in keys(item)}
        return set()

    if forbidden & keys(source_payload):
        raise ValueError("critic source payload contains evaluator-only fields")
    if producer.role != "producer":
        raise ValueError("blind critic input requires a producer receipt")
    blind_case_id = (
        "blind:"
        + stable_hash(
            {
                "source": source_payload,
                "candidate": candidate_payload,
                "producer_execution_id": producer.execution_id,
            }
        ).split(":", 1)[1][:24]
    )
    return {
        "blind_case_id": blind_case_id,
        "source": source_payload,
        "candidate": candidate_payload,
        "producer_execution_id": producer.execution_id,
        "required_dimensions": list(CRITIC_DIMENSIONS),
    }


def run_blind_critic(
    blind_input: dict[str, Any],
    *,
    producer: ProviderCallReceipt,
    transport: GenerativeTransport,
    deployment: str,
    config_sha256: str,
    seed: str,
) -> BlindCriticVerdict:
    """Perform a fresh structured critic call over the blinded public bundle."""

    if producer.role != "producer" or producer.execution_kind != "fresh":
        raise ValueError("live criticism requires an original fresh producer execution")
    if blind_input.get("producer_execution_id") != producer.execution_id:
        raise ValueError("critic input is not bound to the supplied producer execution")
    prompt = (
        "You are an independent semantic critic, never an activation authority. "
        "Assess only the supplied public source and candidate. Do not infer expected labels. "
        "Return strict JSON and score every required dimension separately. Cite candidate "
        "span IDs; use indeterminate when evidence is insufficient.\nBLIND_BUNDLE\n"
        + json.dumps(blind_input, ensure_ascii=False, sort_keys=True)
        + f"\nINDEPENDENT_RUN_NONCE: {seed}\n"
    )
    raw = transport.generate(prompt=prompt, output_schema=BlindCriticDraft.model_json_schema())
    draft = BlindCriticDraft.model_validate(raw)
    if draft.blind_case_id != blind_input.get("blind_case_id"):
        raise ValueError("critic changed the blinded case identity")
    prompt_digest = stable_hash(prompt)
    output_digest = stable_hash(draft.model_dump(mode="json"))
    receipt = ProviderCallReceipt(
        execution_id=stable_hash(
            {
                "role": "critic",
                "producer": producer.execution_id,
                "prompt": prompt_digest,
                "output": output_digest,
                "seed": seed,
            }
        ),
        role="critic",
        execution_kind="fresh",
        provider=transport.provider,
        model=transport.model,
        deployment=deployment,
        prompt_version="blind-autoformalization-critic-v1",
        prompt_sha256=prompt_digest,
        source_sha256=stable_hash(blind_input["source"]),
        config_sha256=config_sha256,
        output_sha256=output_digest,
        seed=seed,
        terminal_status="succeeded",
    )
    return BlindCriticVerdict(
        blind_case_id=draft.blind_case_id,
        producer_execution_id=producer.execution_id,
        critic_receipt=receipt,
        dimensions=draft.dimensions,
        overall=draft.overall,
    )


def evaluate_profile(
    profile: AutoformalizationProfile, runs: tuple[ProfileCaseRun, ...]
) -> ProfileRunReport:
    """Apply deterministic-first profile policy and calculate stability metrics."""

    by_case = {item.case_id: item for item in runs}
    if set(by_case) != set(profile.case_ids) or len(by_case) != len(runs):
        raise ValueError("profile runs must cover every configured case exactly once")
    dispositions: list[CaseDisposition] = []
    for case_id in profile.case_ids:
        run = by_case[case_id]
        reasons: list[str] = []
        deterministic = run.deterministic
        # These blockers are authoritative even when every critic says pass.
        reasons.extend(f"deterministic:{item}" for item in deterministic.blockers)
        if profile.require_complete_deterministic_evidence:
            if deterministic.behavioral_passed != deterministic.behavioral_total:
                reasons.append("deterministic:behavioral_failure")
            if deterministic.mutations_killed != deterministic.mutations_total:
                reasons.append("deterministic:surviving_mutation")
            if deterministic.backend_agreements != deterministic.backend_checks:
                reasons.append("deterministic:backend_disagreement")
            if not run.structured_output_valid:
                reasons.append("deterministic:invalid_structured_output")
            if run.unsupported_additions:
                reasons.append("deterministic:unsupported_addition")

        fresh_producers = [
            item
            for item in run.producer_receipts
            if item.execution_kind == "fresh" and item.terminal_status == "succeeded"
        ]
        if len(fresh_producers) < profile.fresh_producer_runs:
            reasons.append("profile:insufficient_fresh_producer_runs")
        if len({item.execution_id for item in fresh_producers}) != len(fresh_producers) or len(
            {item.seed for item in fresh_producers}
        ) != len(fresh_producers):
            reasons.append("profile:producer_runs_not_independent")
        if not profile.allow_replay and any(
            item.execution_kind == "replay" for item in run.producer_receipts
        ):
            reasons.append("profile:replay_not_fresh_evidence")

        fresh_critics = [
            item
            for item in run.critic_verdicts
            if item.critic_receipt.execution_kind == "fresh"
            and item.critic_receipt.terminal_status == "succeeded"
        ]
        if len(fresh_critics) < profile.fresh_critic_runs:
            reasons.append("profile:insufficient_fresh_critic_runs")
        critic_receipts = [item.critic_receipt for item in fresh_critics]
        if len({item.execution_id for item in critic_receipts}) != len(critic_receipts) or len(
            {item.seed for item in critic_receipts}
        ) != len(critic_receipts):
            reasons.append("profile:critic_runs_not_independent")
        producer_ids = {item.execution_id for item in run.producer_receipts}
        if any(item.producer_execution_id not in producer_ids for item in run.critic_verdicts):
            reasons.append("critic:unknown_producer_execution")
        if profile.require_calibration:
            if run.calibration is None:
                reasons.append("critic:missing_calibration")
            elif any(
                not run.calibration.authorizes(item.critic_receipt) for item in run.critic_verdicts
            ):
                reasons.append("critic:stale_or_mismatched_calibration")
        if any(item.overall != "pass" for item in run.critic_verdicts):
            reasons.append("critic:nonpass")

        status: Literal["pass", "advisory", "blocked"]
        if reasons:
            status = "blocked" if profile.blocking else "advisory"
        else:
            status = "pass"
        dispositions.append(CaseDisposition(case_id=case_id, status=status, reasons=tuple(reasons)))

    total_invariants = sum(item.invariants_total for item in runs)
    total_mutations = sum(item.deterministic.mutations_total for item in runs)
    backend_checks = sum(item.deterministic.backend_checks for item in runs)
    case_stabilities = []
    for run in runs:
        outputs = [item.output_sha256 for item in run.producer_receipts]
        if outputs:
            case_stabilities.append(
                max(outputs.count(item) for item in set(outputs)) / len(outputs)
            )
    metrics = {
        "structured_output_validity": sum(item.structured_output_valid for item in runs)
        / len(runs),
        "abstention_correctness": sum(item.abstention_correct for item in runs) / len(runs),
        "invariant_recall": (
            sum(item.invariants_recalled for item in runs) / total_invariants
            if total_invariants
            else 1.0
        ),
        "unsupported_addition_rate": sum(item.unsupported_additions for item in runs)
        / max(total_invariants, 1),
        "mutation_kill_rate": (
            sum(item.deterministic.mutations_killed for item in runs) / total_mutations
            if total_mutations
            else 1.0
        ),
        "cross_engine_agreement": (
            sum(item.deterministic.backend_agreements for item in runs) / backend_checks
            if backend_checks
            else 1.0
        ),
        "run_output_stability": (
            sum(case_stabilities) / len(case_stabilities) if case_stabilities else 1.0
        ),
    }
    payload: dict[str, Any] = {
        "profile": profile.name,
        "dispositions": [item.model_dump(mode="json") for item in dispositions],
        "metrics": metrics,
        "provenance_sha256": stable_hash(
            {
                "profile": profile.model_dump(mode="json"),
                "runs": [item.model_dump(mode="json") for item in runs],
            }
        ),
        "passed": all(item.status == "pass" for item in dispositions),
    }
    return ProfileRunReport(report_id=stable_hash(payload), **payload)


class ContentAddressedReplayCache:
    """Persist successful provider outputs under their exact request identity."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def store(self, receipt: ProviderCallReceipt, output: dict[str, Any]) -> Path:
        if receipt.execution_kind != "fresh" or receipt.terminal_status != "succeeded":
            raise ValueError("only successful fresh executions may populate replay cache")
        if stable_hash(output) != receipt.output_sha256:
            raise ValueError("cached output digest differs from provider receipt")
        target = self.root / f"{receipt.cache_key.split(':', 1)[1]}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "cache_key": receipt.cache_key,
                    "receipt": receipt.model_dump(mode="json"),
                    "output": output,
                },
                sort_keys=True,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return target

    def replay(self, receipt: ProviderCallReceipt) -> tuple[ProviderCallReceipt, dict[str, Any]]:
        target = self.root / f"{receipt.cache_key.split(':', 1)[1]}.json"
        payload = json.loads(target.read_text(encoding="utf-8"))
        if payload["cache_key"] != receipt.cache_key:
            raise ValueError("replay cache key mismatch")
        original = ProviderCallReceipt.model_validate(payload["receipt"])
        output = payload["output"]
        if original.cache_key != receipt.cache_key or stable_hash(output) != original.output_sha256:
            raise ValueError("replay cache provenance or output digest mismatch")
        replay_payload = original.model_dump(mode="python")
        replay_payload.update(
            execution_id=stable_hash(
                {"replay_of": original.execution_id, "cache_key": original.cache_key}
            ),
            execution_kind="replay",
            source_execution_id=original.execution_id,
        )
        return ProviderCallReceipt.model_validate(replay_payload), output


def write_profile_report(report: ProfileRunReport, output_dir: Path) -> Path:
    target = output_dir / f"{report.profile}-{report.report_id.split(':', 1)[1][:20]}.yaml"
    write_yaml(target, report.model_dump(mode="json"))
    return target


def run_profile(
    profile_name: str,
    runs: tuple[ProfileCaseRun, ...],
    *,
    output_dir: Path,
) -> ProfileRunReport:
    """Execute one named policy evaluation and persist its content-addressed report."""

    try:
        profile = PROFILES[profile_name]
    except KeyError as exc:
        raise ValueError(f"unknown autoformalization profile: {profile_name}") from exc
    report = evaluate_profile(profile, runs)
    write_profile_report(report, output_dir)
    return report


__all__ = [
    "AutoformalizationProfile",
    "BlindCriticDraft",
    "BlindCriticVerdict",
    "CRITIC_DIMENSIONS",
    "CaseDisposition",
    "ContentAddressedReplayCache",
    "CriticCalibrationBinding",
    "CriticDimensionScore",
    "DeterministicCaseEvidence",
    "PROFILES",
    "ProfileCaseRun",
    "ProfileRunReport",
    "ProviderCallReceipt",
    "build_blind_critic_input",
    "evaluate_profile",
    "run_blind_critic",
    "run_profile",
    "write_profile_report",
]
