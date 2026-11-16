---
name: translation-fidelity-validator
description: Validate source-language to English translations for semantic fidelity, terminology consistency, value preservation, and policy-risk drift. Use when English translations must be checked before becoming reasoning inputs, customer-facing copy, or formalization candidates.
---

# Translation Fidelity Validator

Check that translated English remains faithful to the source.

## Procedure

1. Compare each English unit to its source unit and glossary entries.
2. Verify preserved numbers, dates, limits, locations, service_fees, benefit scopes, and exclusions.
3. Check modality and obligation words for drift.
4. Confirm terminology consistency across repeated source terms.
5. Flag additions, omissions, softened exclusions, broadened coverage, and customer-value paraphrases.
6. Assign review status before any translation enters formalization or recommendation workflows.

## Output Contract

Each validation result should expose:

- `unit_id`
- `status`: `pass`, `warn`, `fail`, or `needs_human_review`
- `fidelity_findings`
- `terminology_findings`
- `preserved_values`
- `missing_values`
- `review_required_reason`

## Gates

- Failed units cannot enter reasoning truth.
- Warnings must remain visible in downstream formalization drafts.
- Any translated exclusion, exception, or limit with drift requires human review.
