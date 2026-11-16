---
name: policy-autoformalization-orchestrator
description: Coordinate source-grounded normative formalization, translation review, and explicit release gates.
---

# Policy Autoformalization Orchestrator

1. Select a domain corpus and identify exact source spans for each normative unit.
2. Review controlled English against the original source, including modality,
   exceptions, scope, values, and temporal conditions.
3. Map terms to reviewed predicates and build typed candidate assertions.
4. Retain grounding, reference resolution, entailment, and review evidence.
5. Keep candidates out of solver authority until the domain release gates pass.

The synthetic maintenance translation example lives in `tests/fixtures/translation/`.
Run `uv run ruler workflow translation-control`, then
`uv run ruler validate translation-control`,
`uv run ruler validate vocabulary-predicates`, and
`uv run ruler validate formalization-governance`.
