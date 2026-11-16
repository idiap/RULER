---
name: source-integrity-curator
description: Curate and validate RULER policy, product, tariff, and workbook source inventory records. Use when adding or updating source documents, extracted tables, source hashes, document versions, extraction quality, or source anchors for controlled reasoning.
---

# Source Integrity Curator

Maintain source records before any policy or product formalization.

## Procedure

1. Record each source in `the domain corpus manifest` or the production-equivalent inventory.
2. Include URI or internal reference, document category, provider, product family, version, retrieval time, `sha256:` hash, and extraction quality.
3. Preserve source IDs because clauses and product features cite them.
4. Mark unknown versions explicitly instead of inventing dates.
5. Run `uv run ruler validate contracts`.

## Gates

- Do not promote clauses whose `source_anchor.source_id` is missing.
- Do not treat marketing/workbook rows as policy evidence.
- Route stale or low-quality extraction records to human review.
