---
name: reasoning-example-html-reviewer
description: Review RULER detailed reasoning example HTML artifacts for clarity, auditability, self-contained rendering, source-grounded claims, useful rule and stage explanations, and visible inference controls.
---

# Reasoning Example HTML Reviewer

Use this skill to review detailed reasoning example pages before sharing or committing them.

## Review Checklist

1. Confirm the page is self-contained:
   - inline CSS and JavaScript
   - embedded JSON payload
   - no remote assets or external scripts
2. Confirm visible reasoning details:
   - customer question and value hypothesis
   - inference steps and counts
   - activated facts
   - fired rules
   - solver constraints
   - counterfactuals
   - advisor and outbound-communication gates
3. Confirm auditability:
   - fired versus evaluated rules are visually distinct
   - selected stage detail exposes telemetry and status counts
   - rule detail exposes evidence references and triggers
   - hidden chain-of-thought is not claimed or exposed
4. Confirm language quality:
   - visible labels use spaces, not raw underscores
   - technical terms are explained functionally
   - customer recommendation is connected to formal reasoning evidence
5. Confirm implementation hygiene:
   - generated files live under `build/ruler/reasoning_example/`
   - source generator lives under the builder skill
   - `git diff --check` passes

## Failure Modes

- The page looks like a generic dashboard but does not teach the reasoning sequence.
- The recommendation is shown without rule activations or solver constraints.
- The page claims source evidence without pointing to trace or KB artifacts.
- The interface exposes raw paths or identifiers as primary labels when a human label is possible.
