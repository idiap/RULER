---
name: formal-reasoning-flow-guardian
description: Validate the complete source-to-semantics-to-projection-to-execution-to-certificate-to-review-to-release stage graph and its digest handoffs.
---

# Formal Reasoning Flow Guardian

Represent every stage and handoff with `FormalStage`, `FormalHandoff`, and `FormalFlowRun`. Reject unknown stages, backward edges, cycles, duplicate producers, mismatched digests, completed stages with blockers, and release claims that omit any required stage.

Every stage names its performing authority. An authorized release must contain exactly one completed stage of every formal kind, an unbroken digest handoff between each adjacent stage, and different authorities for review and release. Validate a serialized run through the repository boundary:

`uv run ruler formal-flow validate PATH`

This gate verifies provenance and control-flow closure; it does not infer that a solver result or review conclusion is substantively correct.

## Validation

`uv run pytest -q tests/assurance/test_formal_flow.py tests/runtime/test_ruler_cli.py`
