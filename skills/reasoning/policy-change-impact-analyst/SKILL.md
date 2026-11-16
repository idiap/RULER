---
name: policy-change-impact-analyst
description: Analyze RULER policy document, clause, rule, tariff, and product-feature changes for material impact. Use when comparing policy KB versions, identifying affected recommendations, rerunning regression scenarios, or deciding whether advisor explanations must be updated.
---

# Policy Change Impact Analyst

Treat policy changes as versioned impact events.

## Procedure

1. Compare old and new source records, clause records, and policy rules.
2. Classify changes as added, removed, modified, split, merged, renumbered, limit changed, exception changed, or condition changed.
3. Identify affected product features and open recommendations through source clause references.
4. Rerun `uv run ruler validate all` after changing rules or feature grounding.
5. Route material changes to human review.

## Gates

- Changed source hashes invalidate stale verified grounding until reviewed.
- Changed limits, exclusions, or exception scope require explanation refresh.
- Prior client-facing wording must not be reused blindly after a material clause change.
