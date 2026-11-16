# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Evidence-only assurance classification for legal reasoning packets."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ruler.contracts.common import StrictContract
from ruler.domains.legal.contracts import LegalReasoningPacket, ProofStatus
from ruler.domains.legal.evidence import LegalEvidenceVerification


class LegalAssuranceReport(StrictContract):
    packet_id: str
    status: Literal["blocked", "candidate_ready_for_review", "reviewed_candidate"]
    source_bound: bool
    formal_checks_complete: bool
    legal_review_complete: bool
    independent_review_complete: bool
    live_defeater_claim_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    strongest_supported_claim: str
    fit_for_legal_reliance: Literal[False] = False
    claim_boundary: str = Field(min_length=1)


def assess_legal_packet(
    packet: LegalReasoningPacket,
    evidence: LegalEvidenceVerification | None = None,
) -> LegalAssuranceReport:
    """Classify evidence without converting solver success into doctrine."""

    source_bound = evidence is not None and evidence.source_bound
    formal_checks_complete = (
        bool(packet.proof_obligations)
        and all(
            item.proof_status in {ProofStatus.PROVED, ProofStatus.TYPECHECKED}
            for item in packet.proof_obligations
        )
        and evidence is not None
        and evidence.proofs_verified
    )
    gate_status = {item.kind: item.status for item in packet.review_gates}
    legal_review = gate_status.get("legal") == "passed"
    independent_review = gate_status.get("independent") == "passed"
    live_defeaters = tuple(
        sorted(
            claim.claim_id
            for claim in packet.claims
            if claim.claim_type.value == "defeater"
            and any(claim.claim_id in argument.defeater_claim_ids for argument in packet.arguments)
            and not any(
                argument.status == "defeated" and claim.claim_id in argument.defeater_claim_ids
                for argument in packet.arguments
            )
        )
    )
    blockers: list[str] = []
    if not source_bound:
        blockers.append("material_legal_claim_not_exactly_source_bound")
    if not formal_checks_complete:
        blockers.append("formal_proof_obligations_incomplete")
    if live_defeaters:
        blockers.append("live_defeaters_require_resolution")
    if not legal_review:
        blockers.append("legal_review_incomplete")
    if not independent_review:
        blockers.append("independent_review_incomplete")
    if evidence is not None:
        blockers.extend(f"evidence:{item}" for item in evidence.blockers)
    if legal_review and independent_review and not live_defeaters and source_bound:
        status = "reviewed_candidate"
    elif source_bound and not live_defeaters:
        status = "candidate_ready_for_review"
    else:
        status = "blocked"
    strongest = (
        "bounded_logical_consequence_in_declared_encoding"
        if formal_checks_complete
        else "source_bound_candidate_interpretation" if source_bound else "unverified_candidate"
    )
    return LegalAssuranceReport(
        packet_id=packet.packet_id,
        status=status,
        source_bound=source_bound,
        formal_checks_complete=formal_checks_complete,
        legal_review_complete=legal_review,
        independent_review_complete=independent_review,
        live_defeater_claim_ids=live_defeaters,
        blockers=tuple(blockers),
        strongest_supported_claim=strongest,
        claim_boundary=(
            "This report classifies source, review, and solver evidence. It does not decide "
            "the law, establish model adequacy, or make the packet fit for legal reliance."
        ),
    )
