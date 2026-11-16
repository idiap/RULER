---
name: fiscal-vat-case-specialist
description: Normalize line-level VAT cases with period-pinned rates and evidence-dependent input-tax conclusions.
---

# Fiscal VAT Case Specialist

## Input contracts

- fiscal `CBRCaseRecord`, invoice lines, currency/tax-period facts, rate-release digest, business-purpose evidence

## Output artifacts

- line classifications, rate and rounding calculations, tax-period compatibility, evidence gaps, correction packet, and tax-review route

## Procedure

Classify each supply independently, select the rate effective for its tax point, retain auditable rounding, separate coding from deductibility, and formally verify the proposal.

## Prohibited inferences

- Never copy documented business purpose, registration, deductibility, place-of-supply, or tax mechanism from a precedent.
- Never collapse unknown input-tax status to non-service_fee or service_fee.

## Files owned

- `skills/reasoning/fiscal-vat-case-specialist/SKILL.md`
- fiscal CBR domain artifacts under `data/use_cases/cbr/fiscal/`

## Validation

`uv run ruler validate cbr`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`; `uv run ruler validate skills`
