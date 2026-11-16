---
name: cbr-retrieval-auditor
description: Audit CBR rankings for determinism, temporal leakage, access leakage, unsafe similarity, and missing contrast.
---

# CBR Retrieval Auditor

## Input contracts

- retrieval packet, pinned request/profile digests, expected contrasts, authorization context

## Output artifacts

- stability, leakage, temporal, jurisdiction, diversity, and contrast audit report with pass/fail gates

## Procedure

Replay retrieval, verify exact rank and contributions, prove hard-filter precedence, check as-of visibility and redactions, and inspect duplicate dominance and sensitive proxies.

## Prohibited inferences

- Never excuse unexplained rank movement, unavailable future evidence, or hidden-field influence.
- Never equate a high similarity score with verification or compliance.

## Files owned

- `skills/reasoning/cbr-retrieval-auditor/SKILL.md`
- audit artifacts under `build/ruler/cbr/audits/`

## Validation

`uv run ruler validate cbr`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`; `git diff --check`
