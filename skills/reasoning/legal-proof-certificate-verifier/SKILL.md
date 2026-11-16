---
name: legal-proof-certificate-verifier
description: Verify proof evidence against exact source, input, output, engine, configuration, certificate, and independent replay identities before raising assurance.
---

# Legal Proof Certificate Verifier

Use `verify_legal_packet_evidence` with a released `CorpusManifest`, exact artifact bytes, and a named/versioned independent replay verifier. Recompute every digest and verify the intended proof evidence rather than trusting `proof_status`, SZS output, or an arbitrary hash. Missing artifacts, identity drift, unavailable replay, or target mismatch remain blocking.

Proof remains relative to its encoded packet and never substitutes for legal review.

## Validation

`uv run pytest -q tests/domains/test_legal_evidence.py`
