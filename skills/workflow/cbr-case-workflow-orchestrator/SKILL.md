---
name: cbr-case-workflow-orchestrator
description: Orchestrate the governed CBR cycle from typed intake through retrieve, adapt, verify, review, and separately confirmed retention.
---

# CBR Case Workflow Orchestrator

## Input contracts

- query `CBRCaseRecord`, authorized case-library release, `SimilarityProfile`, current rule-release digest, resource and review policy

## Output artifacts

- workflow plan, retrieval packet, adaptation plan, evaluation packet, `CBRDecisionPacket`, review record, and optional separately confirmed retention receipt

## Procedure

1. Route domain normalization through `cbr-case-intake-normalizer` and one domain specialist.
2. Run `cbr-case-retriever`, then `cbr-retrieval-auditor`.
3. Run `cbr-adaptation-planner` with a usable precedent.
4. Run `cbr-formal-verification-gate` against the current digest-pinned rule release.
5. Pause for an authorized human disposition; verification does not authorize execution.
6. End without retention by default. Only a distinct confirmed action may invoke `cbr-outcome-retention-curator` for a later observation.

## Prohibited inferences

- Never reorder or bypass retrieve, audit, adapt, verify, and review gates.
- Never let precedent fill missing authority or let workflow completion imply approval.
- Never retain during the review action or without explicit separate confirmation.

## Files owned

- `skills/workflow/cbr-case-workflow-orchestrator/SKILL.md`
- `ruler/workflows/cbr_case.py`
- `data/use_cases/cbr_workflows.yaml`

## Validation

`uv run ruler workflow cbr-case`; `uv run ruler validate cbr`; `uv run ruler validate workflow-router`; `uv run ruler validate skills`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`
