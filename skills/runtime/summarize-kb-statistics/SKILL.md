---
name: summarize-kb-statistics
description: Generate and interpret descriptive statistics for the RULER knowledge base and processed policy documents, including canonical clauses and rules, candidates, drafts, compiled facts and rules, bilingual comments, document types, extraction successes, and failures. Use for progress reports, growth checks, or onboarding baselines.
---

# Summarize KB Statistics

## Procedure

1. Run `uv run ruler workflow kb-statistics`.
2. Read `build/ruler/kb_statistics/kb_statistics.yaml` for automation or `kb_statistics.md` for a compact report.
3. Report canonical YAML records separately from executable Prolog/ASP statements.
4. Use per-target counts to expose compilation growth; do not sum compatibility mirrors as independent knowledge.
5. Report manifest records and content-identified unique documents separately because one document may occur in multiple manifests.
6. Compare snapshot hashes and counts before and after each onboarding checkpoint.
7. Investigate unexpected fact/rule growth, commentary imbalance, duplicate semantics, or document failures with `$verify-kb-consistency`.

## Limits

- Counts do not prove correctness, completeness, or coverage.
- Generated projections and mirror files are derived views, not new canonical facts.
- Never modify KB truth while producing statistics.
