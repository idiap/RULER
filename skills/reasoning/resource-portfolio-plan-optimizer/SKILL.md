---
name: resource-portfolio-plan-optimizer
description: Solve immutable multi-period resource portfolio models with a real MILP backend and emit independently checked advisory plans and solver receipts.
---

# Resource Portfolio Plan Optimizer

Run `uv run ruler portfolio optimize --backend highs`. The authoritative input is the
typed optimization IR, never an executable expression or domain fixture. Report native
termination, incumbent, bound, gap, objective components, model size, configuration,
and backend version. A timed-out incumbent is feasible, not optimal.

Every incumbent must pass `uv run ruler portfolio verify-plan`. The result remains
pending human approval and cannot execute a commercial or operational action.

## Validation

`uv run ruler validate resource-portfolio`
