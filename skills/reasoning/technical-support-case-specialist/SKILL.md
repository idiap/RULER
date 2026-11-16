---
name: technical-support-case-specialist
description: Adapt version-compatible support diagnostics while enforcing safety invariants, authorization, warranty, and SLA escalation.
---

# Technical Support Case Specialist

## Input contracts

- support `CBRCaseRecord`, product/hardware/firmware identifiers, active fault and safety state, manual/bulletin/SLA release digests

## Output artifacts

- compatibility matrix, applicable diagnostic sequence, procedure prerequisites, safety blockers, SLA/warranty route, and confirmed-resolution capture request

## Procedure

Hard-filter product and safety class, compare hardware and firmware exactly, exclude obsolete procedures, preserve interlocks, order non-destructive diagnostics, and route authorized physical work and production stops.

## Prohibited inferences

- Never bypass or deactivate a safety control, copy a procedure across incompatible versions, claim resolution before confirmation, or assign restricted work to an unauthorized person.

## Files owned

- `skills/reasoning/technical-support-case-specialist/SKILL.md`
- support CBR domain artifacts under `data/use_cases/cbr/technical_support/`

## Validation

`uv run ruler validate cbr`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`; `uv run ruler validate skills`
