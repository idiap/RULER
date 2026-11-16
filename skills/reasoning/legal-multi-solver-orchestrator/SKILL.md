---
name: legal-multi-solver-orchestrator
description: Route immutable formal subproblems by declared semantics and join only digest-compatible, independently checked backend evidence.
---

# Legal Multi-Solver Orchestrator

Start from a source-verified semantic basis and a `ReasoningQuery`. Route only to backends whose declared capabilities cover the query and whose projection policy is executable. Preserve target and contrary orientation, backend availability, model completeness, proof-object status, and blockers as independent axes. Connect stages with `FormalFlowRun` handoffs; every consumed digest must match its producer.

Do not count unavailable engines as panel agreement, compare solvers on different problems, or promote an encoding-relative result into domain truth.

## Validation

`uv run ruler validate kb-workspace`; `uv run pytest -q tests/assurance tests/domains/test_legal_evidence.py`
