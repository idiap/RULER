---
name: vocabulary-predicate-harmonizer
description: Harmonize bilingual policy vocabulary into stable predicate candidates for RULER autoformalization and executable rule review.
---

# Vocabulary Predicate Harmonizer

Use this skill when French or source-language policy terms need stable English renderings and predicate names.

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
uv run ruler validate formalized-kb
```
