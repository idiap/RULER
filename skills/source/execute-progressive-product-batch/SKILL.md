---
name: execute-progressive-product-batch
description: Execute exactly one legal stage of the portable progressive domain-specific product KB construction pipeline, from source readiness through immutable publication. Use when preparing, validating, formalizing, quality-checking, publishing, or transferring a named onboarding batch.
---

# Execute Progressive Product Batch

Use only the repository CLI. Read `docs/operations/progressive_product_onboarding_runbook.md` before
the first execution in an environment.

## Procedure

1. Run `uv sync --extra dev` and `uv run ruler validate batch-pipeline`.
2. Run `uv run ruler workflow product-batch-pipeline --batch-id <id> --stage status`.
3. Stop if `blocked_by_batch` is non-null. Supply only the listed `missing_inputs` using
   the checked-in templates.
4. Run the exact `next_command`; never skip or combine lifecycle stages.
5. For `generative-verified`, add `--model <allowlisted-model>` and preserve every result.
   If status reports `revision` after a failed current-hash judgment, correct the
   source-bound inputs and run that exact command before retrying the generative gate.
   If formalization instead exposes corrected catalogue provenance after completeness
   was checkpointed, run the explicit non-advancing `source-revision` stage before
   retrying formalization.
   `uv run ruler workflow kb-statistics`.
7. Before handoff run `uv run ruler validate all`.

## Invariants

- Maximum three product labels and three documents per batch.
- One active batch; ordered predecessors must be published or explicitly blocked.
- Every formal element binds exact source-version and span hashes.
- Every formal element carries source-language and controlled-English commentary.
- Completeness decisions preserve material conditions, exclusions, exceptions, limits,
  duties, definitions, precedence, and cross-references.
- Candidate, stale, quarantined, ungated, or failed content never enters runtime truth.
- Publication requires deterministic evidence, current-hash generative consensus,
  coherence, and an immutable release/projection.
- Human approval is not an authorization gate; automated evidence is mandatory.
- Never perform bulk extraction or advance another batch implicitly.
