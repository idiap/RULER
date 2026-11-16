---
name: spending-procurement-case-specialist
description: Apply procurement-specific normalization and adaptation policy without treating precedent approvals as reusable authority.
---

# Spending Procurement Case Specialist

## Input contracts

- spending `CBRCaseRecord`, spending feature registry, procurement rule-release digest, quote/approval evidence references

## Output artifacts

- typed amount/currency/threshold features, quote and approval gap ledger, anti-splitting signal, budget feasibility facts, and domain adaptation policy

## Procedure

Normalize money without changing currency, distinguish quote sufficiency from approved exception, test conflicts and aggregate related orders, and route the plan through `cbr-formal-verification-gate`.

## Prohibited inferences

- Never infer a waiver, approval, budget availability, sole-source status, or lawful split from a prior case.
- Never recommend commitment or payment while a required gate is missing.

## Files owned

- `skills/reasoning/spending-procurement-case-specialist/SKILL.md`
- spending CBR domain artifacts under `data/use_cases/cbr/spending/`

## Validation

`uv run ruler validate cbr`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`; `uv run ruler validate skills`
