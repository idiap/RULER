---
name: legal-semantic-projection-guard
description: Gate ASP, Prolog, TPTP, and Lean projections on complete digest bindings, bijective symbols, and explicit query-affecting semantic loss.
---

# Legal Semantic Projection Guard

Construct a `SemanticProjection` from a verified semantic basis. Bind source, basis, and program digests; enumerate represented and omitted elements; and classify each semantic dimension as represented, approximated, omitted, or unsupported. Any omitted element or query-affecting loss must set the projection to `blocked`.

Never treat successful compilation as proof of preservation or permit an unmapped engine symbol.

## Validation

`uv run pytest -q tests/kb/test_semantic_projection.py tests/kb/test_semantic_validation.py`
