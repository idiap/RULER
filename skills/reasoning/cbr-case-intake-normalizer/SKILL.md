---
name: cbr-case-intake-normalizer
description: Normalize a narrative case into a strict CBR query while preserving unknown, redacted, and not-applicable values.
---

# CBR Case Intake Normalizer

## Input contracts

- `ruler.cbr.contracts.CBRCaseRecord` draft or narrative mapped by a registered domain pack
- domain `FeatureRegistry`, authorized source references, and sensitivity policy

## Output artifacts

- validated `CBRCaseRecord`, explicit unknown-feature list, sensitivity map, and source-to-feature trace

## Procedure

1. Select the domain and case-kind registry before interpreting fields.
2. Type every feature and record its observation time, source, confidence, and missingness.
3. Preserve `unknown`, `redacted`, and `not_applicable`; validate release and jurisdiction identities.
4. Stop on an undeclared feature or an observed value without evidence provenance.

## Prohibited inferences

- Never present a model guess, default, precedent value, approval, licence, tax fact, or safety state as observed.
- Never convert missingness to zero, false, an empty collection, or a favorable answer.
- Never expose a redacted field through trace text.

## Files owned

- `skills/reasoning/cbr-case-intake-normalizer/SKILL.md`
- Domain-normalized query artifacts under `data/use_cases/cbr/queries/`.

## Validation

```bash
uv run ruler validate cbr
uv run ruler validate skills
uv run pytest -q tests/runtime/test_cbr_skills_workflow.py
```
