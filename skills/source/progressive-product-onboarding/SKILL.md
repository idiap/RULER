---
name: progressive-product-onboarding
description: Prepare, inspect, and advance small domain-specific product onboarding batches from the reference workbook while preserving append-only progress evidence. Use for onboarding planning, selecting the next product family, checking batch status, or recording a verified lifecycle checkpoint without performing bulk ingestion.
---

# Progressive Product Onboarding

Use the repository CLI as the execution boundary. Never advance multiple lifecycle stages in one checkpoint.

## Procedure

1. Run `uv run ruler workflow progressive-product-onboarding` to materialize the ordered plan and seed the first planned checkpoint.
2. Read `data/operations/progressive_onboarding/plan.yaml` and `progress_ledger.jsonl`.
3. Select only the earliest unfinished batch. Keep each batch at three product labels and three documents or fewer.
5. Execute only the requested ingestion stage. Do not infer permission to crawl, extract, formalize, or publish later stages.
6. Record successful progress with `uv run ruler workflow onboarding-checkpoint --batch-id <id> --stage <stage> --evidence-id <id> --note <text>`.
7. Record failures as `blocked`; retain the last successful stage and the remediation evidence.
8. Re-run the consistency and statistics workflows after every checkpoint.

## Gates

- Stages advance in declared order only.
- Every advancement after `planned` requires immutable evidence IDs.
- A blocked event never counts as advancement.
- Never start the next phase until the current phase is published or explicitly blocked.
- This skill prepares and tracks work; it does not authorize bulk processing.
