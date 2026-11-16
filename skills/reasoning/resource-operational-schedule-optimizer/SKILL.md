---
name: resource-operational-schedule-optimizer
description: Solve bounded resource allocation, movement, precedence, and service schedules with real OR-Tools CP-SAT interval constraints.
---

# Resource Operational Schedule Optimizer

Run `uv run ruler portfolio schedule`. Preserve the digest-bound portfolio handoff and
frozen decisions. Use exact integer scaling, optional intervals, no-overlap,
precedence, travel, eligibility, configuration, service windows, and workshop
capacity. Report infeasibility instead of silently relaxing a hard condition.

## Validation

`uv run ruler validate resource-portfolio`
