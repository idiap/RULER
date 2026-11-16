---
name: cbr-adaptation-planner
description: Turn an eligible precedent into an explicit typed feature and evidence diff for current-rule verification.
---

# CBR Adaptation Planner

## Input contracts

- query `CBRCaseRecord`, usable `RetrievedCase`, pinned current rule release, domain adaptation policy

## Output artifacts

- `AdaptationPlan` containing typed add/remove/replace/retain operations, justification codes, missing evidence, and verification flags

## Procedure

Diff query and precedent feature-by-feature. Retain only compatible evidence checklists or candidate actions, identify every material difference, then mark all rule-relevant operations for verification.

## Prohibited inferences

- Never copy a prior approval, authorization, tax status, licence, safety condition, disposition, or outcome.
- Never adapt across an excluded hard filter or invent evidence to close a gap.

## Files owned

- `skills/reasoning/cbr-adaptation-planner/SKILL.md`
- adaptation artifacts under `build/ruler/cbr/adaptations/`

## Validation

`uv run ruler validate cbr`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`; `uv run ruler validate skills`
