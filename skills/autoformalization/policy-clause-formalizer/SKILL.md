---
name: policy-clause-formalizer
description: Convert source-grounded contract clauses into controlled RULER clause graph records and draft policy DSL rules. Use for coverage grants, exclusions, exceptions, limits, duties, option dependencies, and formal rule promotion checks.
---

# Policy Clause Formalizer

Formalize policy text into auditable clauses and draft executable rules.

## Procedure

1. Add or update `PolicyClause` records with exact source anchors, clause type, modality, subject, conditions, exclusions, limits, and review status.
2. Add `PolicyRule` records only after the clause object exists.
3. Use controlled English translations from `build/ruler/translation_control/controlled_english_units.yaml`.
4. Use approved predicates from `tests/fixtures/translation/approved_predicates.yaml` and the harmonized map in `build/ruler/translation_control/vocabulary_predicate_map.yaml`.
5. Keep `coverage`, `exclusion`, `exception`, and `limit` effects separate.
6. Leave `review_status: needs_review` until bidirectional NLI or human review has passed.
7. Run `uv run ruler validate contracts`.
8. Update the applicable formal KB targets, then run `uv run ruler validate formalized-kb` and `uv run ruler validate prolog-nl-comments`.

## Gates

- Rules must cite source clauses.
- Approved rules must compile and pass symbolic consistency checks.
- A product label must never become a policy entitlement without clause grounding.
