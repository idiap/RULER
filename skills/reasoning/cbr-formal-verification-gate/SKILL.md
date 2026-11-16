---
name: cbr-formal-verification-gate
description: Verify a CBR adaptation against the current digest-pinned formal rule release and preserve blockers and unknowns.
---

# CBR Formal Verification Gate

## Input contracts

- `AdaptationPlan`, current formal KB release and digest, bridged `EvaluationRequest`, domain human-review policy

## Output artifacts

- current-rule `EvaluationPacket`, counterfactuals, blocker/unknown ledger, and a non-executable `CBRDecisionPacket`

## Procedure

Reject digest drift, map only typed observed/query facts, execute the registered formal backend, surface contrary support and counterfactuals, and require domain human review.

## Prohibited inferences

- Never let similarity override current rules or resolve unknown as false/true.
- Never mark an action executable merely because verification passed.
- Never expose solver chain-of-thought; retain artifact-level provenance only.

## Files owned

- `skills/reasoning/cbr-formal-verification-gate/SKILL.md`
- verification artifacts under `build/ruler/cbr/verification/`

## Validation

`uv run ruler validate cbr`; `uv run ruler validate kb-workspace`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`
