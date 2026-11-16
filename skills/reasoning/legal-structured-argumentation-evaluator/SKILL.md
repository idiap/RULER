---
name: legal-structured-argumentation-evaluator
description: Evaluate finite source-bound argument graphs under grounded, preferred, and stable semantics with an independent Clingo equivalence check.
---

# Legal Structured Argumentation Evaluator

Build typed `StructuredArgument` and `ArgumentRelation` records. Keep support separate from rebuttal, undercut, premise-undermining, distinction, and authority challenge. Require a cited basis and policy revision for preferences. Run `evaluate_argument_framework`; retain accepted, rejected, and undecided arguments and block on enumeration limits or backend divergence.

Framework-relative warrant is not legal truth and must not authorize release.

## Validation

`uv run pytest -q tests/assurance/test_argumentation.py`
