<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Release checklist

## 1. Scope and provenance

- Identify changed contracts, corpora, domain packs, workflows, interfaces, and outputs.
- Confirm every new source artifact has a stable ID, version/as-of date, SHA-256, role,
  language, status, and references.
- Confirm synthetic and metadata-only sources carry visible claim boundaries.
- Confirm no candidate artifact is represented as published or authoritative.

## 2. Reasoning safety

- Verify unknown/false/redacted/not-applicable behavior.
- Verify target and contrary support separately.
- Verify hard constraints precede ranking and optimization.
- Verify release and effective-date pins.
- For CBR, verify exact top-k order, excluded contrast, no approval/disposition copying,
  current-rule evaluation, human review, and independently reviewed retention.

## 3. Interfaces

- Check CLI help and dry-run defaults.
- Check bearer authentication, redaction, CSP, bounded previews, and uniform not-found.
- Check ETag, confirmation, idempotency, audit, and immutable revision behavior.
- Check that MCP remains allowlisted and read-only by default and exposes no retention.
- Regenerate and visually review user-facing HTML/PDF artifacts where applicable.

## 4. Registry and focused gates

```bash
uv run ruler validate contracts
uv run ruler corpora validate
uv run ruler validate cbr
uv run ruler validate kb-workspace
uv run ruler validate workflow-router
uv run ruler validate workflow-registry
uv run ruler validate skills
uv run ruler validate hooks
uv run ruler validate mcp-server
```

## 5. Complete gate

Install SWI-Prolog so `swipl` is on `PATH`, then prepare the matching browser and
recorded report inputs before validation. On Linux CI use
`uv run playwright install --with-deps chromium` for browser system dependencies.

```bash
uv run playwright install chromium
uv run ruler prepare checks
uv run ruler validate all
```

The release is not complete unless the full test suite, Ruff, and `git diff --check`
pass. The gate is offline: separately record any required live source refresh and any
budgeted generative evaluation with its evidence and review decision.

## 6. Handoff

- Include RULER's Idiap research and education license in Python distributions
  and container images. Preserve pg8000's BSD-3-Clause copyright/license notice
  and the notices supplied by other installed dependencies.
- Summarize behavior and trust-boundary changes.
- Link user-facing guides and generated evidence.
- Report skipped live or generative checks explicitly.
- Report warnings separately from failures.
- Do not call metadata-only public-law demonstrations authoritative.
