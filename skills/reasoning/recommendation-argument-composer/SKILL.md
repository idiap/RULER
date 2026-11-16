---
name: recommendation-argument-composer
description: Compose a single-column, customer-readable recommendation from a validated DecisionArgumentCertificate. Use after recommendation-trace-guardian for solver-backed explanations, including runner-up contrasts, policy sensitivity, formal evidence, caveats, and review gates.
---

# Recommendation Argument Composer

For solver-backed work, require a validated `DecisionArgumentCertificate` from
`$recommendation-trace-guardian`. `PortfolioExplanationEvidence`, a plan, or a
comparison surface alone is insufficient. Prefer deterministic rendering.
Generative prose is optional via
`uv run ruler portfolio explain --generative-draft`; it remains a candidate and
must be checked against the certificate before display.

Use this skill after the certificate establishes whether a same-model comparison
exists. It turns certified decision evidence into concise customer-facing reasoning.
For resource portfolios, use the deterministic records from
`$resource-scenario-coverage-explainer` and `$resource-cost-objective-explainer` for
scenario-range and cost-origin sections. Do not derive those sections independently.

## Argument shape

Write recommendations with this sequence:

1. Practical question and scope.
2. Decision and human review gate.
3. Certified reason, preserving `unique_feasible`, `cost_preferred`, or
   `multiple_optima` exactly.
4. Same-model runner-up contrast, or an explicit `unique_feasible` statement.
5. Policy sensitivity in a separate section; never present it as the runner-up.
6. Assumptions, coverage gaps, and what would change the decision.
7. Decision-relevant natural-language evidence and approved formal model.
8. Candidate KB material only as a separately labelled, non-authoritative appendix.

Use one vertical reading flow. Do not use multi-column panels, side-by-side cards,
or dashboard grids. Keep the complete dossier, full candidate rule table, hashes,
receipts, manifests, and raw metadata in linked artifacts rather than the main
argument.

## Preferred prose patterns

When a same-model runner-up exists:

```text
Given [specific customer facts], Ruler recommends [option/package].
It is preferred because [advantage 1], [advantage 2], and [advantage 3].
Compared with [runner-up], it better handles [decisive axis], while [tradeoff].
[Deferred/review-only line] remains outside the final recommendation until [evidence/advisor condition].
```

When the point is uniquely feasible, replace the comparison sentence with:

```text
The approved requirements force this point; there is no other feasible portfolio
under the unchanged model. Under [explicit policy change], the sensitivity solve
changes [result], but that is not an available base-policy alternative.
```

## Inputs

The mandatory solver-backed input is `DecisionArgumentCertificate`. Use only claims
and values admitted by that certificate. Comparison-surface fields may provide
customer wording, but cannot override its proof classifications.

Use these fields from the comparison surface:

- `customer_context.summary`
- `customer_context.top_needs`
- `options[].customer_fit.advantages`
- `options[].customer_fit.disadvantages`
- `options[].customer_fit.caveats`
- `comparison_axes[].option_positions`
- `recommendation_bridge.decisive_reasons`
- `recommendation_bridge.why_not_runner_up`
- `recommendation_bridge.what_would_change_the_decision`

## Proof-aware language rules

- Say “the requirements uniquely force this point” only for `unique_feasible`.
- Say “the objective prefers X to the same-model runner-up Y” only when the
  certificate supplies that runner-up and objective contrast.
- Say “under the tested policy change” for policy sensitivity. Never call a
  changed-policy solution the runner-up or a currently feasible alternative.
- Do not infer causation from zero slack. Use “decisive” only for certified
  forcedness or ablation evidence.
- Describe the candidate KB as a parallel review artifact with
  `candidate_kb_solver_authority: false`. Only the reviewed model has solver
  authority; certificate version 1 does not prove a candidate-to-model transformation.

- Explain certified tradeoffs using the domain's ordinary terms, such as
  service capacity, resource availability, and operating cost.
- Display certified decision-relevant quantities when they explain the choice;
  keep solver telemetry and administrative values in audit artifacts.
- Do not expose hidden chain-of-thought. Use surfaced facts, rules, tradeoff
  axes, source status, and review gates as the explanation substrate.

## Output Contract

Emit:

```yaml
recommendation_argument:
  certificate_ref: string
  headline: string
  short_argument: string
  decision_class: unique_feasible | cost_preferred | multiple_optima
  decisive_reasons: [string]
  same_model_runner_up: string | null
  policy_sensitivity: [string]
  tradeoff_caveats: [string]
  candidate_kb_relation: parallel_non_authoritative
  candidate_kb_solver_authority: false
  solver_authority_source: reviewed_model
  review_gate: string
  customer_safe: true | false
  blocked_reason: string | null
```

## Quality Bar

The argument is acceptable when it can be read aloud without internal solver jargon
and every causal, comparative, numerical, and authority statement maps to the
certificate. It must preserve:

- the final recommendation;
- the actual same-model alternatives, or their certified absence;
- the tradeoffs;
- why the runner-up did not win, when one exists;
- policy sensitivity as a different model rather than an alternative;
- the boundary between candidate knowledge and solver authority;
- what remains uncertain or review-only;
- what would change the recommendation.
