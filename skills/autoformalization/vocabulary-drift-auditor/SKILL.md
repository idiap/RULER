---
name: vocabulary-drift-auditor
description: Audit RULER autoformalization vocabulary for concept drift, ambiguous source terms, sense splits, predicate-signature reuse, and promotion readiness.
---

# Vocabulary Drift Auditor

Use this skill when source-language terms, controlled English units, or formalization drafts may change the meaning of an existing concept or predicate.

## Procedure

1. Load the domain's reviewed vocabulary and source-linked translation units.
2. Compare source terms, controlled English, predicate signatures, and typed arguments.
3. Record ambiguous terms and require review before changing an approved meaning.
4. Keep candidate mappings separate from approved executable rules.
5. Use `tests/fixtures/translation/` as the synthetic maintenance example and
   `uv run ruler workflow translation-control` to inspect its validation report.

## Gates

```bash
uv run ruler validate vocabulary-predicates
uv run ruler validate translation-control
```
