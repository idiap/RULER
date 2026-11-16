---
name: resource-portfolio-synthetic-data-generator
description: Generate reproducible synthetic resource-portfolio cases and execute the real deterministic planning workflow against them. Use for solver, workflow, robustness, and regression testing without operational data.
---

# Resource Portfolio Synthetic Data Generator

Run:

`uv run ruler portfolio generate-synthetic CONFIG_PATH --seed SEED --output OUTPUT_DIR`

`CONFIG_PATH` is a validated YAML or JSON generation specification containing only
declared case counts, bounded ranges, and feature toggles. `SEED` is a required integer;
all sampling and identifiers must derive from that seed and stable case coordinates.
Identical generator version, config digest, and seed must produce identical case and
manifest content. Solver replay is semantic: semantic digests exclude measured
`runtime_seconds`, while raw telemetry artifacts may differ. Use a dedicated empty or
nonexistent `OUTPUT_DIR`; never mix generated files with real evidence or an earlier run.

The command must emit a manifest containing the synthetic classification, seed, config
digest, generator version, case inventory, and content digests. Generated identifiers,
provenance, and source labels must be explicitly synthetic. Do not infer that synthetic
observations, costs, rules, or outcomes describe a real organization.

## Execution gate

Generation alone is not a passing test. Require the command to run each emitted case
through the real `resource-portfolio-plan` implementation, including rule compilation,
the configured solver backends, independent plan verification, scheduling when present,
stress/counterfactual evaluation, artifact-digest verification, and the pending-review
gate. Preserve failed and infeasible cases as classified test outcomes with an
authenticated Z3 infeasibility receipt;
do not rewrite them into feasible fixtures.

This skill and its generator are deterministic. Do not use a generative model to create
facts, rules, expected answers, or repairs. All resulting plans are synthetic, advisory,
and never approved for execution.

## Validation

Run `uv run ruler validate resource-portfolio` and
`uv run ruler validate deterministic-skills`.
