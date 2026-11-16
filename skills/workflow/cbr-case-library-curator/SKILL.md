---
name: cbr-case-library-curator
description: Curate governed case-library releases through import, de-identification, review, publication, retirement, and rule-drift re-evaluation.
---

# CBR Case Library Curator

## Input contracts

- source case bundle, import authorization, domain feature registry, privacy/access policy, target case-library and rule-release digests

## Output artifacts

- import report, de-identification ledger, review evidence, content-addressed release manifest, publication/retirement receipt, and re-evaluation queue

## Procedure

Validate and quarantine imports, remove direct identifiers and risky free text, validate typed features and evidence digests, require independent review, publish immutably, retire without deletion, and mark cases stale when their pinned rule release drifts.

## Prohibited inferences

- Never publish unreviewed, unidentified, schema-invalid, poisoned, duplicate, future-leaking, or unsupported cases.
- Never rewrite a published release or silently upgrade a case's rule-release identity.

## Files owned

- `skills/workflow/cbr-case-library-curator/SKILL.md`
- case-library curation artifacts under `build/ruler/cbr/curation/`

## Validation

`uv run ruler validate cbr`; `uv run ruler validate skills`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`; `git diff --check`
