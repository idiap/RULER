# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import dataclass
from typing import Mapping

import pytest
import yaml
from pydantic import ValidationError

from ruler.domains.legal import (
    FormalProofObligation,
    LegalReasoningPacket,
    ProofEvidenceIdentity,
    assess_legal_packet,
    verify_legal_packet_evidence,
)
from ruler.kb.corpus_manifest import load_corpus_manifest
from ruler.paths import REPO_ROOT

CORPUS_ROOT = REPO_ROOT / "kb/corpora/legal-sr101-art36"
PACKET_PATH = CORPUS_ROOT / "candidate/art36_packet.yaml"
MANIFEST_PATH = CORPUS_ROOT / "manifest.yaml"


def _payload() -> dict[str, object]:
    return yaml.safe_load(PACKET_PATH.read_text(encoding="utf-8"))


def _digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class AcceptingReplayVerifier:
    verifier_id: str = "independent-tstp-replay"
    verifier_version: str = "1"

    def verify(
        self,
        obligation: FormalProofObligation,
        evidence: ProofEvidenceIdentity,
        artifacts: Mapping[str, bytes],
    ) -> bool:
        return (
            obligation.target_claim_id == "cumulative-test-reading"
            and evidence.certificate_artifact_id in artifacts
        )


def test_source_verification_binds_spans_to_manifest_declared_bytes() -> None:
    packet = LegalReasoningPacket.model_validate(_payload())
    verification = verify_legal_packet_evidence(
        packet,
        load_corpus_manifest(MANIFEST_PATH),
        repo_root=REPO_ROOT,
    )

    assert verification.source_bound
    assert verification.source_verified_span_ids == (
        "art36-p1",
        "art36-p2",
        "art36-p3",
        "art36-p4",
    )
    assert assess_legal_packet(packet).source_bound is False
    assert assess_legal_packet(packet, verification).source_bound is True


def test_self_rehashed_but_fabricated_source_text_fails_filesystem_binding() -> None:
    changed = deepcopy(_payload())
    span = changed["source_spans"][0]
    span["exact_text"] += " fabricated"
    span["end_char"] = span["start_char"] + len(span["exact_text"])
    span["text_sha256"] = _digest(span["exact_text"].encode())
    packet = LegalReasoningPacket.model_validate(changed)

    verification = verify_legal_packet_evidence(
        packet,
        load_corpus_manifest(MANIFEST_PATH),
        repo_root=REPO_ROOT,
    )

    assert not verification.source_bound
    assert "art36-p1:source_slice_mismatch" in verification.blockers


def test_successful_proof_status_rejects_bare_or_unverified_digest() -> None:
    changed = deepcopy(_payload())
    obligation = changed["proof_obligations"][0]
    obligation["proof_status"] = "proved"
    obligation["proof_digest"] = "sha256:" + "0" * 64

    with pytest.raises(ValidationError, match="structured proof evidence"):
        LegalReasoningPacket.model_validate(changed)


def test_proof_completion_requires_exact_artifacts_and_independent_replay() -> None:
    artifacts = {
        "input": b"fof(input,axiom,p).",
        "output": b"SZS status Theorem",
        "certificate": b"proof steps",
        "engine": b"vampire executable bytes",
        "configuration": b"--mode casc --time_limit 10",
        "replay": b"independent replay result",
    }
    changed = deepcopy(_payload())
    obligation = changed["proof_obligations"][0]
    obligation["proof_status"] = "proved"
    obligation["proof_digest"] = _digest(artifacts["certificate"])
    obligation["evidence"] = {
        "input_artifact_id": "input",
        "input_digest": _digest(artifacts["input"]),
        "output_artifact_id": "output",
        "output_digest": _digest(artifacts["output"]),
        "certificate_artifact_id": "certificate",
        "certificate_digest": _digest(artifacts["certificate"]),
        "engine_id": "vampire",
        "engine_version": "4.9",
        "engine_artifact_id": "engine",
        "engine_digest": _digest(artifacts["engine"]),
        "configuration_artifact_id": "configuration",
        "configuration_digest": _digest(artifacts["configuration"]),
        "verifier_id": "independent-tstp-replay",
        "verifier_version": "1",
        "replay_artifact_id": "replay",
        "replay_digest": _digest(artifacts["replay"]),
        "verification_status": "verified",
    }
    packet = LegalReasoningPacket.model_validate(changed)
    manifest = load_corpus_manifest(MANIFEST_PATH)

    without_replay = verify_legal_packet_evidence(
        packet,
        manifest,
        repo_root=REPO_ROOT,
        proof_artifacts=artifacts,
    )
    assert not without_replay.proofs_verified
    assert "art36-cumulative-preservation:independent_replay_unavailable" in without_replay.blockers

    wrong_verifier = verify_legal_packet_evidence(
        packet,
        manifest,
        repo_root=REPO_ROOT,
        proof_artifacts=artifacts,
        replay_verifier=AcceptingReplayVerifier(verifier_version="2"),
    )
    assert not wrong_verifier.proofs_verified
    assert (
        "art36-cumulative-preservation:replay_verifier_identity_mismatch" in wrong_verifier.blockers
    )

    verified = verify_legal_packet_evidence(
        packet,
        manifest,
        repo_root=REPO_ROOT,
        proof_artifacts=artifacts,
        replay_verifier=AcceptingReplayVerifier(),
    )
    assert verified.proofs_verified
    assert assess_legal_packet(packet, verified).formal_checks_complete

    tampered = dict(artifacts)
    tampered["certificate"] = b"different proof"
    rejected = verify_legal_packet_evidence(
        packet,
        manifest,
        repo_root=REPO_ROOT,
        proof_artifacts=tampered,
        replay_verifier=AcceptingReplayVerifier(),
    )
    assert not rejected.proofs_verified
    assert "art36-cumulative-preservation:certificate_artifact_digest_mismatch" in rejected.blockers
