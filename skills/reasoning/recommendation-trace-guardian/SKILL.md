---
name: recommendation-trace-guardian
description: Build and validate a deterministic DecisionArgumentCertificate for a solver-backed recommendation. Use before composing or displaying an explanation that claims why a decision won, what the runner-up was, or what a policy change would do.
---

# Recommendation Trace Guardian

This is the proof-certificate boundary for decision explanations. Run the real
workflow and use the canonical implementation in
`ruler/applications/resource_portfolio/argumentation.py`. The required output is a
validated `DecisionArgumentCertificate`, persisted as `decision_argument.yaml`.
Do not substitute a prose trace, solver receipt, or hand-authored explanation.

## Execution

```bash
uv run ruler workflow resource-portfolio-plan
uv run ruler validate resource-portfolio
```

Build the certificate from the authenticated base problem, verified plan,
constraint replay, grounding, and executed comparison runs. Fail closed when any
claimed relation is absent from the certificate.

## Certificate gates

- A binding constraint is not causal evidence. Call it decisive only when the
  certificate contains a deterministic forcedness or ablation result supporting
  that claim.
- Keep the same-model runner-up separate from policy sensitivity. A runner-up must
  be solved under the unchanged approved model. A relaxed or changed rule belongs
  only under policy sensitivity.
- Preserve the certificate's exact decision class: `unique_feasible`,
  `cost_preferred`, or `multiple_optima`. When no same-model alternative exists,
  say that the requirements force the point; do not say that the objective preferred
  it over a runner-up. Never present one of several tied optima as a unique winner.
- Preserve each certified constraint role: `cost_decisive`,
  `optimal_set_restricting`, `redundant_at_optimum`, or `unresolved`. Do not promote
  `binding_at_selected_point` into one of those roles.
- Attribute a changed policy outcome to both the structural change and the
  objective comparison when both are needed to explain the selected variant.
- Candidate KB statements have no solver authority. Version 1 records the candidate
  digest and the reviewed model as separate authority domains; it does not certify a
  candidate → reviewed-model transformation. Treat them as parallel artifacts.
- Preserve semantic coverage gaps, omitted facts, schedule-compatibility limits,
  uncertainty, and the human review gate.

## Output

Return or persist the validated `DecisionArgumentCertificate`. Block explanation
composition when the certificate is missing, invalid, or lacks evidence for a
requested causal or comparative claim. Generative prose may later paraphrase the
certificate; it may never add claims, identifiers, numbers, authority, or status.
