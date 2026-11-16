---
name: legal-semantic-basis-builder
description: Build and verify a typed, atomic semantic basis whose spans are checked against immutable source artifact bytes before formal projection.
---

# Legal Semantic Basis Builder

Create `SemanticSourceSpan`, `SemanticElement`, and `SemanticBasis` records from exact source text. Model actors, actions, objects, modality, polarity, connectives, exceptions, quantities, temporal relations, and coreference separately. Call `SemanticBasis.verify_source_artifacts`; a digest copied from the candidate is not evidence. Keep every ungrounded interpretation as an explicit candidate assumption.

Reject dangling roles, sentence-shaped predicates, incomplete quantity types, stale artifact digests, offset drift, and unsupported source text.

## Validation

`uv run pytest -q tests/kb/test_semantic_projection.py tests/kb/test_semantic_validation.py`
