<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Progressive product KB construction runbook

This runbook is the complete operational entry point for constructing the remaining
domain-specific product KB batches. It assumes only a clean repository checkout and access to
the policy documents selected for the batch. It does not rely on prior chat history,
machine-specific paths, or unpublished local conventions.

## 1. Install and verify the environment

```bash
uv sync --extra dev
uv run ruler workflow progressive-product-onboarding
uv run ruler validate batch-pipeline
uv run ruler workflow kb-statistics
```

The canonical catalogue is
`data/operations/progressive_onboarding/pipeline_catalogue.yaml`. It lists every batch,
its order, product labels, bounded paths, quality case ID, and output root. Never edit
the generated catalogue directly; its source of truth is the workbook-derived
progressive plan.

## 2. Select the only legal next batch and stage

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id phase-01-batch-01 \
  --stage status
```

The JSON response contains `current_stage`, `next_stage`, `blocked_by_batch`,
`missing_inputs`, and an exact `next_command`. Only run that command. The controller
allows one batch at a time and advances one lifecycle stage per invocation.

The lifecycle is:

```text
planned -> sources-ready -> extracted -> completeness-verified -> formalized
        -> deterministic-verified -> generative-verified -> coherence-verified
        -> published
```

Use `--dry-run` with any stage to inspect readiness without changing the append-only
progress ledger.

## 3. Prepare the batch inputs

Copy the examples from
`data/operations/progressive_onboarding/templates/` into the exact paths reported by
the status command. All paths stored in manifests must be repository-relative.

Each batch accepts at most three product labels and three documents.

### Source selection

`source_selection.yaml` declares the exact workbook labels, provider, jurisdiction,
controlled product-family ID, selected document IDs, and why the documents cover the
batch. `link_manifest.yaml` provides the provider-neutral source link records.

Advance only after both exist:

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage sources-ready
```

### Extraction

Fetch and extract only the selected document IDs using the controlled source workflow.
Place the resulting manifest at the batch's `extraction_manifest` path. Every selected
document must have `status: extracted`, an immutable `raw_sha256`, and extracted
artifacts. The manifest must contain exactly the selected documents.

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage extracted
```

Do not proceed if OCR or extraction quality is quarantined. Repair or replace the
source and regenerate the extraction manifest explicitly.

### Completeness and spans

Create `span_specs.yaml` with stable document IDs, repository-relative extracted text
paths, exact line ranges, and headings. Create `completeness_ledger.yaml` with one
`keep`, `defer`, or `omit` disposition for every structural policy element. Omissions
require recommendation-impact reasoning. Unresolved cross-references block progress.

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage completeness-verified
```

### Formal elements

Create `formal_elements.yaml`. Every element declares:

- `record_type`: `feature`, `clause`, or `rule`;
- a complete typed `ProductFeature`, `PolicyClause`, or `PolicyRule` payload;
- exact source-span IDs;
- a source-language controlled explanation;
- controlled English commentary; and
- any governed terminology-decision IDs.

Every workbook product label must resolve to a `ProductFeature`. Spelling variants or
catalogue labels may be grouped in one feature through explicit `workbook_label:`
source-candidate IDs when the policy evidence defines one combined scope. Product
features should remain `is_selectable: false` unless separate commercial evidence
supports selectability. Rules must include a source-faithful Prolog target and must preserve
conditions, exceptions, modalities, numbers, units, dates, territory, parties, and
cross-references.

If formalization exposes corrected source catalogue coordinates after source,
extraction, and completeness checkpoints already exist, amend those manifests and run
the explicit non-advancing provenance remediation before retrying formalization:

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage source-revision
```

This revalidates source selection, extraction, completeness, source registry, and
source versions and records their current hashes in an append-only amendment. It is
legal only while the effective batch stage is `completeness_verified`.

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage formalized
```

This constructs candidates, immutable source bindings, released-assertion candidates,
bilingual annotations, source/version registries, and compiled Prolog under the
batch's output root. It does not publish them.

## 4. Verify and publish

Run deterministic verification first:

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage deterministic-verified
```

Then run the explicit networked semantic-quality stage. The runner exposes only the
batch's allowlisted evidence to Codex in a read-only ephemeral sandbox. A critical
failure or indeterminate result blocks publication; model output cannot silently edit
or promote content.

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage generative-verified --model gpt-5.4
```

If the gate preserves a failed or invalid current-hash judgment, correct the
source-bound completeness and formalization inputs. Status will then expose the
append-only remediation command:

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage revision
```

Revision retains the failed result IDs, revalidates completeness, rebuilds the typed
artifacts, reruns deterministic verification, and records a non-advancing revision
checkpoint. Run the new exact `generative-verified` command only after status reports
the corrected content hash as ready.

The same revision stage reopens an unpublished batch when a correction changes the
formalization inputs after `generative-verified` or `coherence-verified`. Correct the
source-bound inputs first, then run the `revision` command reported by status. The
append-only revision records the superseded consensus and coherence hashes, resets the
effective stage to `deterministic-verified`, and requires fresh generative and coherence
checks. Never reopen a published batch; publish a new immutable release for a later
correction.

After a passing current-hash consensus:

```bash
uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage coherence-verified

uv run ruler workflow product-batch-pipeline \
  --batch-id <batch-id> --stage published
```

Publication writes an immutable content-addressed release under
`kb/releases/product_onboarding/` and a per-batch active pointer under
`kb/releases/product_onboarding/active_batches/`. A rerun with identical semantic
content is a no-op; a real collision is rejected.

## 5. Verify every checkpoint

After every successful stage:

```bash
uv run ruler validate progressive-onboarding
uv run ruler validate batch-pipeline
uv run ruler workflow kb-statistics
```

Before handing off a published batch:

```bash
uv run ruler validate all
```

Statistics report canonical KB records and progressive onboarding releases separately.
Growth is expected only for source-supported, annotated, gated elements. Unexpected
growth, duplicate semantics, commentary imbalance, source drift, or recommendation
changes are release blockers.

## 6. Failure and transfer rules

- Never skip a stage or create a checkpoint manually to bypass its owning validator.
- Never start a later batch while `blocked_by_batch` is non-null.
- Retain failed generative results; correct the source-bound formalization and rerun so
  the new evidence receives a new cache key.
- Record an unrecoverable batch as `blocked` with an immutable remediation artifact;
  do not treat it as published.
- Do not copy `build/` results between environments as authority. Recreate generative
  evidence in the target environment. Immutable source, candidate, annotation, and
  release hashes make results comparable.
- Do not place credentials, customer PII, hidden reasoning, or full unrelated documents
  in quality evidence bundles.

The `execute-progressive-product-batch` skill contains the same operational boundary
for agents and automation.
