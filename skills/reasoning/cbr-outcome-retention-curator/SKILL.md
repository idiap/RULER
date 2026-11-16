---
name: cbr-outcome-retention-curator
description: Retain independently reviewed CBR dispositions and later observations immutably with privacy and supersession controls.
---

# CBR Outcome Retention Curator

## Input contracts

- reviewed disposition, later `OutcomeObservation`, independent reviewer, provenance, visibility and retention policy, expected release ETag

## Output artifacts

- immutable outcome record, content digest, audit event, supersession link, and rule-drift re-evaluation status

## Procedure

Dry-run first. Confirm retention separately from verification, verify reviewer independence and source, de-identify, apply retention/access policy, then append idempotently. Correct only with a new superseding record.

## Prohibited inferences

- Never retain without explicit confirmation, provenance, privacy policy, or independent review.
- Never overwrite history, claim causality from correlation, or expose restricted observations.

## Files owned

- `skills/reasoning/cbr-outcome-retention-curator/SKILL.md`
- reviewed outcome artifacts under managed case-library releases

## Validation

`uv run ruler validate cbr`; `uv run ruler validate skills`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`
