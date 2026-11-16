<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Contributing

## Design rules

- Keep the core domain-neutral. Domain vocabulary and semantics belong in
  `ruler/domains/<domain>/`.
- Use frozen, strict Pydantic contracts at subsystem boundaries.
- Preserve source spans, hashes, release identities, and review state.
- Treat missing information as unknown; never infer false from absence.
- Put hard scope, authorization, and safety filters before scoring or optimization.
- Keep generated explanations trace-bound and free of hidden chain-of-thought.
- Do not mutate published artifacts. Create a revision, release, or superseding record.

## Development loop

```bash
uv sync --extra dev
uv run pytest -q PATH_TO_FOCUSED_TESTS
uv run ruff check CHANGED_PATHS
git diff --check
```

Then run the validators affected by the change. Examples:

```bash
uv run ruler validate contracts
uv run ruler validate cbr
uv run ruler validate skills
uv run ruler validate hooks
uv run ruler validate workflow-router
uv run ruler validate workflow-registry
uv run ruler validate mcp-server
```

Finish with `uv run ruler validate all` for changes crossing subsystem boundaries or
before release.

## Adding capabilities

- Corpus: follow [add_corpus.md](../guides/add_corpus.md).
- Domain pack: follow [add_domain_pack.md](../guides/add_domain_pack.md).
- Workflow: add a live Click command, canonical `.ruler/workflows.yaml` entry,
  declared hook if needed, router entry if user-facing, skill binding, and tests.
- API: require authentication, strict request models, uniform errors, resource bounds,
  redaction, and concurrency/idempotency controls for mutations.
- MCP: prefer read-only tools; every tool must be named in `MCP_TOOL_NAMES`, registered
  in FastMCP, represented in the manifest, bounded, and tested. Do not expose arbitrary
  shell execution.
- CBR: declare the feature registry and similarity profile, add at least six reviewed
  cases, exact golden order, an excluded contrast, independent rule evaluation, and
  current-release verification.

## Tests and fixtures

- Tests live under `tests/` following the package boundary.
- Synthetic fixtures must be clearly labelled and deterministic.
- Golden tests should assert identities/order and negative controls, not only counts.
- Adversarial tests should cover access, temporal leakage, traversal, oversized input,
  stored content, duplicate dominance, stale ETags, and unsafe inference transfer.
- Update inventory expectations when deliberately adding workflows, routes, skills,
  hooks, corpora, MCP tools, or KBs.

## Documentation

Update the relevant guide and `docs/README.md` whenever a public command, route,
contract, trust boundary, or operational procedure changes. Keep generated reports in
`build/ruler/`. Plans may explain rationale but must not be the sole usage reference.

## Change hygiene

The worktree may contain user changes. Do not reset or overwrite unrelated files.
Use repository-relative paths in persisted artifacts, never secrets or local absolute
paths. External acquisition and generative evaluations must remain explicit, bounded,
and separately authorized.
