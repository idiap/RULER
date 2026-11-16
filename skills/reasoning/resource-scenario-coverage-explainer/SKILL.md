---
name: resource-scenario-coverage-explainer
description: Build a deterministic, digest-closed explanation of executed resource-portfolio scenarios, tested parameter ranges, assignment stability, and explicitly untested dimensions. Use when presenting scenario coverage without claiming universal robustness.
---

# Resource Scenario Coverage Explainer

Run the real resource-portfolio workflow and scenario re-solves through
`$resource-scenario-robustness-analyst`. Then call
`build_scenario_envelope_explanation` in
`ruler/applications/resource_portfolio/explanation_records.py`; do not assemble the
coverage claim from prose or scenario names.

## Required evidence

- The typed `OptimizationProblem` used as the base model.
- The reviewed `ScenarioSet` and its matching executed `StressReport`.
- A reviewed `ScenarioCoverageDeclaration` naming the planning horizon, question,
  and at least one untested dimension with source references.
- When available, the validated `DecisionArgumentCertificate` produced by
  `$recommendation-trace-guardian`. This adds executed same-model exclusion,
  forcedness, ablation, and policy-sensitivity probes to the coverage record.

Persist the returned `ScenarioEnvelopeExplanation` as
`scenario_envelope_explanation.yaml`. Its digests, outcome identities, statuses,
parameter minima and maxima, objective range, expected objective, CVaR, and distinct
assignment count are computed from typed artifacts. Never hand-edit those values.

## Interpretation boundary

- Say **assignment-stable across the tested scenarios** only when the record's
  `assignment_stable_across_tested_scenarios` is true. Do not shorten this to
  “robust,” “future-proof,” or “stable under uncertainty.”
- Describe the tested envelope by exact parameter identifiers, values, probabilities,
  assumptions, and planning horizon. Scenario labels alone do not define coverage.
- List declared exclusions next to tested dimensions. Absence of a dimension from the
  scenario set is not evidence that it cannot change the decision.
- Keep analysis classes distinct: parameter stress and policy sensitivity change model
  inputs; the no-good solve tests an alternative under the approved policy; forcedness
  and ablation answer different causal questions.
- Do not infer probability calibration, independence, exhaustive combinations, or
  out-of-envelope performance unless separately reviewed evidence establishes it.
- If an outcome did not solve with a feasible incumbent, report its status and do not
  use it to support stability.

## Deterministic execution

```bash
uv run ruler workflow resource-portfolio-plan
uv run ruler portfolio stress
uv run ruler validate resource-portfolio
```

This skill explains the finite experiment; it does not create scenario assumptions or
replace review of their realism.
