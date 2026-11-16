---
name: tradeoff-solver-ranker
description: Run RULER hard-before-soft configuration and preference ranking. Use when solving feasible configurations, enforcing dependencies, applying stakeholder preferences, or comparing cost and operational trade-offs.
---

# Tradeoff Solver Ranker

Rank only among configurations that satisfy hard rules.

## Procedure

1. Load the typed options, decision context, and preferences.
2. Enforce required existing selections and feature dependencies as hard constraints.
3. Compare stakeholder-facing benefits through the domain's reviewed value dimensions.
4. Encode hard preferences before soft objective terms.
5. Run the registered domain workflow; for machine portfolios use `uv run ruler workflow resource-portfolio-plan`.
6. Inspect the verified result, independent verification receipt, and decision argument.
7. Run `uv run ruler validate resource-portfolio` and `uv run ruler validate formalized-kb` when formal rule behavior changes.

## Gates

- Preferences cannot override policy exclusions or mandatory eligibility.
- Infeasible hard requirements must return a review or infeasible state, not a lower score.
- Ranking explanations must preserve objective criteria, customer advantages, caveats, and trade-offs.
