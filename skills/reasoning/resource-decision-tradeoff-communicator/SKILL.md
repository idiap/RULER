---
name: resource-decision-tradeoff-communicator
description: Communicate a solver-backed resource-portfolio decision on the main report surface using a compact trade-off map, certified contrasts, cost provenance, and exact executed-scenario coverage. Use when an optimization result must be understandable without implying a branching decision process or exhaustive search.
---

# Resource Decision Trade-off Communicator

Build the main report argument only from the validated
`DecisionArgumentCertificate`, `CostObjectiveExplanation`, and
`ScenarioEnvelopeExplanation`. Produce those records through
`$recommendation-trace-guardian`, `$resource-cost-objective-explainer`, and
`$resource-scenario-coverage-explainer`; never reconstruct their claims from prose,
chart geometry, or solver logs. Use `$recommendation-argument-composer` only to
paraphrase the certified content.

## Use a trade-off map, not a decision tree

For a portfolio optimizer, use one compact **decision trade-off map** followed by a
vertical evidence narrative. A decision tree suggests that the result was reached by
following a sequence of contingent branches. That is inaccurate when a solver
evaluates a coupled feasible region and the report presents one policy judgment after
optimization evidence.

The map has two clearly labelled states:

1. **Recommended portfolio under the approved model** — decision class, operational
   outcome, and verified annual cost.
2. **Nearest certified contrast** — the same-model runner-up when one exists;
   otherwise the tested changed-policy sensitivity, visibly marked as unavailable
   under the approved model.

Between them, show the certified pivot: the feasibility requirement or objective
trade-off that distinguishes the states. Below them, show the operational consequence,
cost delta, and the assumption that would have to change. Do not use arrows that imply
causality unless the certificate supplies forcedness or ablation evidence. A decision
tree is appropriate only when the product genuinely asks the reader to choose among
sequential conditions; it is not the default visualization for this workflow.

## Main-tab story order

Use a single reading flow:

1. State the operational question and planning horizon.
2. Give the recommended portfolio and preserve the certified decision class.
3. Show the trade-off map and the concrete policy choice it exposes.
4. Explain the annual cost from the digest-closed objective decomposition.
5. State the investigated scenario envelope and execution outcomes.
6. Name the constraints, assumptions, untested dimensions, and change triggers.
7. Navigate to the accepted formal-KB tab and detailed evidence embedded in the same
   self-contained report.

Lead with the decision, not with formalization administration. Keep digests, provider
receipts, iteration logs, and raw assignments out of the main tab.

## Configuration coverage

Derive the number of investigated diagnostic configurations as
`sum(run_count for analysis in executed_analysis_classes)` from the validated
`ScenarioEnvelopeExplanation`. Report the count together with its composition by
analysis kind and status. For the current demonstration this evidence evaluates 13
diagnostic configurations: three parameter stresses, one same-model exclusion, four
variable-forcedness probes, four constraint ablations, and one policy sensitivity.
Do not hard-code 13 in the renderer or infer the count from labels. If the base solve
is mentioned, describe it separately rather than silently adding it to the diagnostic
count.

Say “13 executed diagnostic configurations across the declared envelope,” not “all
configurations,” “13 combinations,” or “an exhaustive search.” List the declared
untested dimensions adjacent to the count. Separate attempted runs from solved runs
when their recorded statuses differ.

## Evidence and language gates

- Preserve `unique_feasible`, `cost_preferred`, or `multiple_optima` exactly.
- For `unique_feasible`, say there is no same-model alternative. A cheaper
  changed-policy result is a sensitivity, not a runner-up or available saving.
- Use the verified annual objective and certified delta; do not calculate numbers in
  presentation code.
- A binding constraint is not automatically decisive. Use only certified forcedness
  and ablation roles for causal language.
- Show the accepted trade-off as both benefit and consequence. Do not disguise the
  consequence as a caveat elsewhere on the page.
- Generative prose may improve clarity, but it must remain a checked paraphrase of the
  typed records and add no numbers, causal claims, statuses, or authority.
- Do not expose hidden chain-of-thought. Display replayable facts, formal rules,
  solver-backed comparisons, and declared boundaries.

## Execution and acceptance

```bash
uv run ruler workflow resource-portfolio-demonstrator
uv run ruler validate resource-portfolio
uv run ruler validate deterministic-skills
```

Accept the main-tab communication only when a reader can identify the recommendation,
the policy trade-off, the applicable contrast, the annual cost basis, the exact extent
of executed diagnostics, and what remains untested—without consulting administrative
artifacts.
