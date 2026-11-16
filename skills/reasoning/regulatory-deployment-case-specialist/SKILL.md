---
name: regulatory-deployment-case-specialist
description: Apply effective-date, actor-role, scope, evidence, oversight, and monitoring policy to regulatory deployment cases.
---

# Regulatory Deployment Case Specialist

## Input contracts

- regulatory `CBRCaseRecord`, actor/scope registry, jurisdiction overlays, rule release with source spans and applicability dates

## Output artifacts

- actor and scope facts, effective-date resolution, obligation/evidence checklist, control gaps, monitoring route, and domain adaptation policy

## Procedure

Resolve jurisdiction, actor, use context, and as-of applicability before retrieving. Adapt a control checklist only, preserve sector differences, and verify operational permission against current rules.

## Prohibited inferences

- Never treat a sandbox or other-sector deployment as operational authorization.
- Never infer human oversight, notice, conformity evidence, or applicability from similarity.
- Never claim a provision is effective when date resolution is unknown.

## Files owned

- `skills/reasoning/regulatory-deployment-case-specialist/SKILL.md`
- regulatory CBR domain artifacts under `data/use_cases/cbr/regulatory/`

## Validation

`uv run ruler validate cbr`; `uv run ruler validate formalized-kb`; `uv run pytest -q tests/runtime/test_cbr_skills_workflow.py`
