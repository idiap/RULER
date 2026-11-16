---
name: policy-source-formalization-drift-guard
description: Check that RULER source clauses retain their conditions, exclusions, limits, and option requirements when converted into formal rules, policy effects, and decision packets.
---

# Policy Source Formalization Drift Guard

Prevent source meaning from being weakened by formalization.

## Procedure

1. Compare source clause text and structured clause fields with the formalizable unit, draft, policy effect, and decision packet usage.
2. Check condition preservation before accepting coverage or waiver effects.
3. Check exclusion preservation before allowing customer-facing explanation.
4. Check limits and option dependencies as machine-readable constraints, not prose-only caveats.
5. Treat missing source semantics as a blocking defect unless a bounded waiver is recorded.

## Gates

- `uv run ruler validate formalization-governance`
- `uv run ruler validate formalization-governance`
- `uv run ruler validate formalization-governance`
