---
name: resource-portfolio-workflow-orchestrator
description: Execute the digest-closed resource portfolio workflow from evidence and approved rules through optimization, verification, explanation, and pending review.
---

# Resource Portfolio Workflow Orchestrator

Run `uv run ruler workflow resource-portfolio-plan`. Require an immutable snapshot,
approved-rule compilation, a real MILP receipt, independent feasibility verification,
and trace closure. Run CP scheduling and stress/counterfactual stages when declared by
the request. Generative work is limited to blocked rule autoformalization candidates
and optional explanation prose over verified traces.

Workflow completion never implies approval. Every artifact handoff must match its
producer digest, and every declared output must exist.

## Validation

`uv run ruler validate resource-portfolio`; `uv run ruler validate deterministic-skills`
