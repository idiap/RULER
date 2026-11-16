---
name: policy-layout-extraction-auditor
description: Audit selective policy-section extraction before promotion. Use when checking extracted policy spans, detecting missing neighboring clauses, validating section boundaries, or deciding whether layout-derived text is safe for autoformalization.
---

# Policy Layout Extraction Auditor

Use this after a section has been selected or extracted.

## Audit Checks

1. Boundary integrity:
   - start marker matches the intended heading
   - end marker stops before the next unrelated heading
   - page range includes all continuation text
2. Layout integrity:
   - list items remain attached to their parent sentence
   - tables preserve row and column headers
   - benefit amounts retain currency, period, and territory
   - exceptions remain attached to exclusions they qualify
3. Reasoning integrity:
   - every extracted span has a declared role
   - every limit has a triggering condition
   - every exclusion has a coverage family
   - every duty is kept separate from coverage grants
4. Promotion integrity:
   - candidate spans stay `needs_review` until reviewed
   - promoted spans cite source section and extraction method
   - rule candidates cite the exact extracted span IDs they use

## Output Contract

For each audited section, record:

- `section`
- `boundary_status`
- `layout_status`
- `reasoning_status`
- `promotion_status`
- `blocking_issues`
- `recommended_next_action`

## Gates

- Block promotion when a section references another article that is absent from the extraction bundle.
- Block promotion when a benefit amount is extracted without territory, duration, or event conditions.
- Block promotion when an exception clause is extracted without its explicit exceptions.
