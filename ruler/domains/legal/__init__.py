# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Legal interpretation domain and evidence-only assurance boundary."""

from ruler.domains.legal.assurance import LegalAssuranceReport, assess_legal_packet
from ruler.domains.legal.contracts import (
    ExactSourceSpan,
    FormalProofObligation,
    InterpretiveArgument,
    LegalAuthority,
    LegalClaim,
    LegalIssueFrame,
    LegalReasoningPacket,
    ProofEvidenceIdentity,
)
from ruler.domains.legal.evidence import (
    LegalEvidenceVerification,
    ProofReplayVerifier,
    verify_legal_packet_evidence,
)
from ruler.domains.legal.pack import LEGAL_DOMAIN_PACK, LegalDomainPack

__all__ = [
    "LEGAL_DOMAIN_PACK",
    "ExactSourceSpan",
    "FormalProofObligation",
    "InterpretiveArgument",
    "LegalAssuranceReport",
    "LegalAuthority",
    "LegalClaim",
    "LegalDomainPack",
    "LegalIssueFrame",
    "LegalReasoningPacket",
    "LegalEvidenceVerification",
    "ProofEvidenceIdentity",
    "ProofReplayVerifier",
    "assess_legal_packet",
    "verify_legal_packet_evidence",
]
