# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Explicit, unmocked model calls for candidate autoformalization.

These tests are skipped during offline validation and are executed by
``ruler workflow test-generative-smoke``. They never substitute replayed output.
"""

from __future__ import annotations

import hashlib
import os

import pytest

from ruler.io import stable_hash, write_yaml
from ruler.kb.formalization import PredicateRegistry, PredicateSignature, ValueType, WorldAssumption
from ruler.kb.generative_autoformalization import (
    AutoformalizationRequest,
    CodexExecTransport,
    generate_autoformalization_candidate,
)
from ruler.paths import BUILD_DIR
from ruler.testing.autoformalization_cases import (
    build_producer_input,
    load_autoformalization_case_catalogue,
)
from ruler.testing.autoformalization_profiles import (
    ProviderCallReceipt,
    build_blind_critic_input,
    run_blind_critic,
)

CASES = (
    (
        "norm_with_exception",
        "If the customer reports the outage within 48 hours and provides a diagnostic log, "
        "the provider must issue a service credit up to CHF 2,500. "
        "However, no reimbursement is due when the vehicle was left unlocked.",
        (
            "theft_reported_within_48_hours",
            "replacement_cost_reimbursable",
            "vehicle_left_unlocked",
        ),
    ),
    (
        "permission_with_temporal_limit",
        "A laboratory manager may approve access only if training is current. "
        "Access expires 30 days after the training certificate expires.",
        ("training_current", "access_approvable", "access_expires_after_days"),
    ),
)


def _smoke_predicate_registry(case_id: str, predicates: tuple[str, ...]) -> PredicateRegistry:
    """Explicit fixture signatures; generation must not infer executable arities."""
    claim = case_id == "norm_with_exception"
    signatures = []
    for name in predicates:
        temporal = name == "access_expires_after_days"
        signatures.append(
            PredicateSignature(
                name=name,
                argument_names=(
                    ("claim",) if claim else (("access", "days") if temporal else ("access",))
                ),
                argument_types=(
                    (ValueType.CLAIM_ID,)
                    if claim
                    else (
                        (ValueType.ENTITY_ID, ValueType.DURATION)
                        if temporal
                        else (ValueType.ENTITY_ID,)
                    )
                ),
                units=(None, "day") if temporal else (),
                family="autoformalization-smoke",
                world_assumption=WorldAssumption.OPEN,
            )
        )
    return PredicateRegistry(signatures=tuple(signatures))


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.mark.skipif(
    os.environ.get("RULER_RUN_LIVE_CODEX_AUTOFORMALIZATION") != "1"
    or os.environ.get("RULER_AUTOFORMALIZATION_PROFILE") not in {None, "smoke"},
    reason="explicit live Codex autoformalization test",
)
@pytest.mark.parametrize("case_id,source,predicates", CASES, ids=[item[0] for item in CASES])
def test_live_generator_produces_source_locked_blocked_candidates(
    case_id: str, source: str, predicates: tuple[str, ...]
) -> None:
    """Exercise the production Codex transport over two distinct source styles."""

    request = AutoformalizationRequest(
        request_id=f"live-{case_id}",
        artifact_id=f"source-{case_id}",
        artifact_sha256=_sha256(source),
        source_text=source,
        source_version="2026-09-01",
        context_id=case_id,
        domain_id=case_id,
        allowed_predicates=predicates,
        predicate_registry=_smoke_predicate_registry(case_id, predicates),
    )
    candidate = generate_autoformalization_candidate(
        request,
        CodexExecTransport(
            model=os.environ.get("RULER_CODEX_MODEL", "gpt-5.4"),
            timeout_seconds=300,
        ),
    )

    assert candidate.receipt.provider == "codex-exec"
    assert candidate.receipt.attempts in {1, 2}
    assert candidate.projection.activation_status == "blocked"
    assert candidate.semantic_basis.spans
    assert candidate.logical_program.statements
    assert {item.predicate for item in candidate.semantic_basis.elements} <= set(predicates)


CATALOGUE = load_autoformalization_case_catalogue()
PROFILE_CASES = {
    "pr": {
        "legal_conditional_exception_permission",
        "procurement_thresholds_table",
        "coreference_open_texture",
    },
    "integration": {item.case_id for item in CATALOGUE.cases},
    "release": {item.case_id for item in CATALOGUE.cases},
    "drift": {item.case_id for item in CATALOGUE.cases},
}


def _case_source(payload: dict[str, object]) -> str:
    sources = payload["sources"]
    assert isinstance(sources, list)
    if len(sources) == 1:
        return str(sources[0]["content"])
    return "\n\n".join(
        f"SOURCE {item['source_id']} START\n{item['content']}\nSOURCE {item['source_id']} END"
        for item in sources
    )


@pytest.mark.skipif(
    os.environ.get("RULER_RUN_LIVE_CODEX_AUTOFORMALIZATION") != "1"
    or os.environ.get("RULER_AUTOFORMALIZATION_PROFILE") not in PROFILE_CASES,
    reason="explicit governed catalogue profile",
)
@pytest.mark.parametrize("case", CATALOGUE.cases, ids=lambda item: item.case_id)
def test_live_catalogue_profile_runs_fresh_producer_and_independent_critics(case) -> None:
    """Run each configured style with fresh provider calls and persist safe receipts."""

    profile = os.environ["RULER_AUTOFORMALIZATION_PROFILE"]
    if case.case_id not in PROFILE_CASES[profile]:
        pytest.skip(f"case is outside {profile} profile")
    repetition = os.environ.get("RULER_AUTOFORMALIZATION_REPETITION", "1")
    payload = build_producer_input(case)
    source = _case_source(payload)
    transport = CodexExecTransport(
        model=os.environ.get("RULER_CODEX_MODEL", "gpt-5.4"),
        timeout_seconds=600,
    )
    request = AutoformalizationRequest(
        request_id=f"{profile}-{case.case_id}-{repetition}",
        artifact_id=f"bundle-{case.case_id}",
        artifact_sha256=_sha256(source),
        source_text=source,
        source_version=f"fixture-v{CATALOGUE.version}",
        context_id=case.case_id,
        domain_id=case.domain_id,
        allowed_predicates=case.allowed_predicates,
        max_output_tokens=12_000,
        guidance=(case.task, f"Independent producer run nonce: {repetition}"),
    )
    candidate = generate_autoformalization_candidate(request, transport)
    producer = ProviderCallReceipt(
        execution_id=stable_hash(
            {
                "receipt": candidate.receipt.model_dump(mode="json"),
                "repetition": repetition,
            }
        ),
        role="producer",
        execution_kind="fresh",
        provider=candidate.receipt.provider,
        model=candidate.receipt.model,
        deployment=candidate.receipt.deployment,
        prompt_version=candidate.receipt.prompt_version,
        prompt_sha256=candidate.receipt.prompt_sha256,
        source_sha256=candidate.receipt.source_artifact_sha256,
        config_sha256=stable_hash(
            {
                "schema": candidate.receipt.schema_sha256,
                "token_budget": candidate.receipt.token_budget,
                "timeout_seconds": candidate.receipt.timeout_seconds,
            }
        ),
        output_sha256=candidate.receipt.response_sha256,
        seed=repetition,
        terminal_status="succeeded",
    )
    critic_count = 0 if profile == "pr" else (1 if profile == "integration" else 2)
    blind_input = build_blind_critic_input(
        source_payload=payload,
        candidate_payload=candidate.model_dump(mode="json"),
        producer=producer,
    )
    critics = tuple(
        run_blind_critic(
            blind_input,
            producer=producer,
            transport=transport,
            deployment=candidate.receipt.deployment,
            config_sha256=stable_hash(
                {"prompt_version": "blind-autoformalization-critic-v1", "temperature": 0}
            ),
            seed=f"{repetition}-critic-{index}",
        )
        for index in range(1, critic_count + 1)
    )
    assert candidate.projection.activation_status == "blocked"
    assert all(item.producer_execution_id == producer.execution_id for item in critics)
    assert len({item.critic_receipt.execution_id for item in critics}) == len(critics)

    output_dir = BUILD_DIR / "generative" / profile
    record = {
        "profile": profile,
        "case_id": case.case_id,
        "repetition": repetition,
        "execution_kind": "fresh",
        "producer": producer.model_dump(mode="json"),
        "critics": [item.model_dump(mode="json") for item in critics],
        "candidate_sha256": stable_hash(candidate.model_dump(mode="json")),
    }
    record["record_sha256"] = stable_hash(record)
    write_yaml(
        output_dir / f"{case.case_id}-repetition-{repetition}.yaml",
        record,
    )
