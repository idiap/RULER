---
name: resource-cost-objective-explainer
description: Build a deterministic, digest-closed decomposition of a verified resource-portfolio cost objective into its time basis, constant, coefficients, selected assignments, grounded sources, and correctly classified comparisons. Use when explaining where a portfolio cost or saving comes from.
---

# Resource Cost Objective Explainer

Use the solver and independent verifier through `$resource-portfolio-plan-optimizer`,
then call `build_cost_objective_explanation` in
`ruler/applications/resource_portfolio/explanation_records.py`. The returned
`CostObjectiveExplanation` is the numerical source of truth; do not reconstruct a
cost from report prose.

## Required evidence

- The exact `OptimizationProblem` and its matching independently `VerifiedPlan`.
- The objective identifier to explain.
- A reviewed time-basis label and its source references, such as an annual planning
  horizon. The objective unit and time basis are separate fields: `CHF` does not by
  itself mean annual, monthly, or weekly.
- The validated `DecisionArgumentCertificate` from
  `$recommendation-trace-guardian` when comparisons are discussed.
- `DemonstratorGrounding` when natural-language source spans exist. Without it, mark
  `grounding_complete: false`; solver origin references are not a substitute for an
  authenticated source span.

Persist the returned record as `cost_objective_explanation.yaml`. It deterministically
computes each `coefficient × selected_value` contribution, the non-zero constant,
the exact reconstructed total, and equality with the independently verified objective.
It fails closed on digest, certificate, verification, objective, arithmetic, or
time-basis mismatches.

## Explanation rules

- State the objective's sense, component, priority, unit, and attributed time basis
  before presenting the total.
- Show the equation as constant plus selected term contributions. Explain zero-valued
  terms when they clarify why an option contributes no cost.
- Distinguish unavoidable constants from decision-dependent coefficients. A constant
  belongs in the selected total but cannot explain why one assignment beats another.
- Trace coefficients and constants to objective origin references and, when available,
  exact grounding binding/span IDs. Never invent a tariff, depreciation basis, or
  annualization factor.
- Preserve comparison type from the certificate. A same-model alternative keeps
  `changes_approved_model: false`; a policy sensitivity has
  `changes_approved_model: true` and is not a runner-up.
- Interpret `selected_minus_compared` with the declared objective sense. For a
  minimized cost, a negative value means the selected base point is cheaper; for a
  policy sensitivity, the sign only compares the two solved models.
- Do not present a lower policy-sensitivity cost as an attainable saving without also
  naming the changed assumption and its operational consequence.

## Deterministic execution

```bash
uv run ruler workflow resource-portfolio-plan
uv run ruler portfolio optimize
uv run ruler portfolio verify-plan
uv run ruler validate resource-portfolio
```

Use `$recommendation-argument-composer` only after this record and the decision
certificate agree; generative wording may paraphrase their fields but cannot add
numbers or provenance.
