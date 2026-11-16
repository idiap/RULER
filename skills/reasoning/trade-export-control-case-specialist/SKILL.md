---
name: trade-export-control-case-specialist
description: Apply classification, destination, end-use, sanctions freshness, licensing, and shipment-hold controls to trade cases.
---

# Trade Export Control Case Specialist

## Input contracts

- trade `CBRCaseRecord`, item/technology features, destination and parties, dated list release, fresh screening evidence, rule-release digest

## Output artifacts

- classification and component-threshold gaps, end-user/end-use ledger, screening freshness, licence-determination request, technology-transfer scope, and shipment hold

## Procedure

Require classification before authorization, cover tangible and intangible transfer, independently establish end user/end use and current screening, then verify against the as-of rule release and escalate.

## Prohibited inferences

- Never assert that a licence is unnecessary—or reuse one—because a similar export proceeded.
- Never clear a shipment with stale screening, missing classification, missing end-use evidence, or unresolved catch-all concern.

## Files owned

- `skills/reasoning/trade-export-control-case-specialist/SKILL.md`
- trade CBR domain artifacts under `data/use_cases/cbr/trade/`

## Validation

`uv run ruler validate cbr`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`; `uv run ruler validate skills`
