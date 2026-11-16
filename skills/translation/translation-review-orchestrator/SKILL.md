---
name: translation-review-orchestrator
description: Coordinate a controlled source-language to English translation workflow across segmentation, terminology, controlled translation, fidelity validation, human review, and promotion into reasoning artifacts. Use when translation needs an end-to-end governed workflow rather than a one-off English paraphrase.
---

# Translation Review Orchestrator

Coordinate controlled translation as a promotion workflow.

## Procedure

1. Run `source-text-intake-segmenter` to create immutable source units.
2. Run `translation-terminology-curator` to establish controlled terminology.
3. Run `controlled-english-translator` to produce aligned English units.
4. Run `translation-fidelity-validator` to classify pass, warn, fail, and human-review units.
5. Promote only passed or explicitly reviewed warning units into extraction candidates or formalization drafts.
6. Record a translation review packet with source IDs, translated IDs, reviewer notes, and unresolved issues.

## Promotion Rules

- `pass`: eligible for downstream extraction or formalization.
- `warn`: eligible only if the warning is copied into downstream caveats.
- `needs_human_review`: blocked until reviewed.
- `fail`: blocked; source segmentation, glossary, or translation must be revised.

## Hook

Use the `translation-control` hook as the workflow checkpoint. At minimum, run:

```bash
uv run ruler validate skills
uv run ruler validate hooks
```
