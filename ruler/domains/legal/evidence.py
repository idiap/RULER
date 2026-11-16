# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Filesystem-bound evidence verification for legal reasoning packets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from pydantic import Field

from ruler.contracts.common import StrictContract
from ruler.domains.legal.contracts import (
    FormalProofObligation,
    LegalReasoningPacket,
    ProofEvidenceIdentity,
    ProofStatus,
)
from ruler.kb.corpus_manifest import CorpusManifest, sha256_file


class ProofReplayVerifier(Protocol):
    """Independent, named checker for the exact evidence bundle."""

    verifier_id: str
    verifier_version: str

    def verify(
        self,
        obligation: FormalProofObligation,
        evidence: ProofEvidenceIdentity,
        artifacts: Mapping[str, bytes],
    ) -> bool: ...


class LegalEvidenceVerification(StrictContract):
    """Result of checking packet claims against immutable bytes and replay evidence."""

    packet_id: str
    source_verified_span_ids: tuple[str, ...]
    proof_verified_obligation_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    source_bound: bool
    proofs_verified: bool
    verification_digest: str = Field(min_length=71, max_length=71)


def verify_legal_packet_evidence(
    packet: LegalReasoningPacket,
    manifest: CorpusManifest,
    *,
    repo_root: Path,
    proof_artifacts: Mapping[str, bytes] | None = None,
    replay_verifier: ProofReplayVerifier | None = None,
) -> LegalEvidenceVerification:
    """Verify source slices and proof identities against caller-supplied immutable bytes.

    Merely carrying a digest or a ``verified`` label is insufficient. Source text must
    equal the declared slice of a manifest-bound file. Successful proof obligations
    additionally require all three declared artifacts and a separate replay callback.
    """

    blockers: list[str] = []
    verified_spans: list[str] = []
    verified_proofs: list[str] = []
    manifest_is_legal = manifest.domain_id == "legal"
    if not manifest_is_legal:
        blockers.append("manifest_domain_mismatch")
    artifacts = {item.artifact_id: item for item in manifest.artifacts}
    corpus_root = (repo_root / "kb" / "corpora" / manifest.corpus_id).resolve()

    for span in packet.source_spans:
        artifact = artifacts.get(span.source_artifact_id)
        if artifact is None:
            blockers.append(f"{span.span_id}:source_artifact_not_in_manifest")
            continue
        if artifact.status not in {"reviewed", "approved", "active"}:
            blockers.append(f"{span.span_id}:source_artifact_not_released")
            continue
        try:
            source_path = (repo_root / artifact.path).resolve()
            source_path.relative_to(corpus_root)
        except ValueError:
            blockers.append(f"{span.span_id}:source_path_escapes_corpus")
            continue
        if not source_path.is_file():
            blockers.append(f"{span.span_id}:source_artifact_missing")
            continue
        if sha256_file(source_path) != artifact.sha256:
            blockers.append(f"{span.span_id}:source_artifact_digest_mismatch")
            continue
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            blockers.append(f"{span.span_id}:source_artifact_not_utf8")
            continue
        if source_text[span.start_char : span.end_char] != span.exact_text:
            blockers.append(f"{span.span_id}:source_slice_mismatch")
            continue
        verified_spans.append(span.span_id)

    supplied = proof_artifacts or {}
    for obligation in packet.proof_obligations:
        if obligation.proof_status not in {ProofStatus.PROVED, ProofStatus.TYPECHECKED}:
            continue
        evidence = obligation.evidence
        if evidence is None:  # Defensive for objects loaded before the stricter contract.
            blockers.append(f"{obligation.obligation_id}:proof_evidence_missing")
            continue
        identities = (
            (evidence.input_artifact_id, evidence.input_digest, "input"),
            (evidence.output_artifact_id, evidence.output_digest, "output"),
            (evidence.certificate_artifact_id, evidence.certificate_digest, "certificate"),
            (evidence.engine_artifact_id, evidence.engine_digest, "engine"),
            (
                evidence.configuration_artifact_id,
                evidence.configuration_digest,
                "configuration",
            ),
            (evidence.replay_artifact_id, evidence.replay_digest, "replay"),
        )
        identity_failed = False
        for artifact_id, expected_digest, role in identities:
            content = supplied.get(artifact_id)
            if content is None:
                blockers.append(f"{obligation.obligation_id}:{role}_artifact_missing")
                identity_failed = True
            elif _sha256(content) != expected_digest:
                blockers.append(f"{obligation.obligation_id}:{role}_artifact_digest_mismatch")
                identity_failed = True
        if identity_failed:
            continue
        if replay_verifier is None:
            blockers.append(f"{obligation.obligation_id}:independent_replay_unavailable")
            continue
        if (
            replay_verifier.verifier_id != evidence.verifier_id
            or replay_verifier.verifier_version != evidence.verifier_version
        ):
            blockers.append(f"{obligation.obligation_id}:replay_verifier_identity_mismatch")
            continue
        if not replay_verifier.verify(obligation, evidence, supplied):
            blockers.append(f"{obligation.obligation_id}:independent_replay_failed")
            continue
        verified_proofs.append(obligation.obligation_id)

    declared_span_ids = {item.span_id for item in packet.source_spans}
    successful_ids = {
        item.obligation_id
        for item in packet.proof_obligations
        if item.proof_status in {ProofStatus.PROVED, ProofStatus.TYPECHECKED}
    }
    source_bound = manifest_is_legal and declared_span_ids == set(verified_spans)
    proofs_verified = bool(successful_ids) and successful_ids <= set(verified_proofs)
    canonical = json.dumps(
        {
            "packet": packet.model_dump(mode="json"),
            "manifest": manifest.model_dump(mode="json"),
            "source_verified_span_ids": sorted(verified_spans),
            "proof_verified_obligation_ids": sorted(verified_proofs),
            "blockers": sorted(blockers),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return LegalEvidenceVerification(
        packet_id=packet.packet_id,
        source_verified_span_ids=tuple(sorted(verified_spans)),
        proof_verified_obligation_ids=tuple(sorted(verified_proofs)),
        blockers=tuple(sorted(blockers)),
        source_bound=source_bound,
        proofs_verified=proofs_verified,
        verification_digest=_sha256(canonical),
    )


def _sha256(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


__all__ = [
    "LegalEvidenceVerification",
    "ProofReplayVerifier",
    "verify_legal_packet_evidence",
]
