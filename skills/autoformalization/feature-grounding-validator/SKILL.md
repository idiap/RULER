---
name: feature-grounding-validator
description: Validate RULER product feature records against canonical taxonomy, dependencies, parameters, policy grounding statuses, and source-backed clauses. Use when adding product features, mapping provider labels, or deciding whether a feature is recommendation eligible.
---

# Feature Grounding Validator

Keep commercial features separate from policy truth.

## Procedure

1. Normalize provider and UI labels into one `ProductFeature` record per canonical feature.
2. Encode `requires`, `excludes`, `implies`, parameters, pricing references, and comparison dimensions.
3. Set `policy_grounding.status` conservatively.
4. Cite policy clauses for `verified` and `verified_partial` features.
5. Use `marketing_only`, `unknown`, `stale_source`, or `contradicted` when evidence is insufficient.
6. Run `uv run ruler validate contracts`.

## Gates

- `verified` and `verified_partial` require at least one clause.
- `marketing_only`, `unknown`, `contradicted`, and `stale_source` are not automated recommendation claims.
- Parameterized service capabilities must keep limits, location, option, and caveats visible.
