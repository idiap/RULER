<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Ruler system architecture

Ruler is a controlled neuro-symbolic platform for converting rigorously stated
documents into inspectable formal knowledge, managing multiple immutable knowledge
bases, and applying those KBs to verification, compliance, recommendation,
optimization, and case-based reasoning.

The architecture separates authority from convenience: source evidence, formalization,
formal inference, historical experience, generative assistance, and human decisions
remain distinct artifacts with explicit promotion and review boundaries.

## System context

```text
documents, tables, manuals, policies, regulations, contracts
                         |
                 governed ingestion
                         v
source inventory -> extracted spans -> formalization candidates
                                         |
                                  review/promotion
                                         v
             immutable formal KB releases and case-library releases
                      |                         |
              formal evaluation          CBR retrieval
                      |                         |
                      +---- adaptation + current-rule verification
                                         |
                              decision packet / replay
                                         |
                                   human review
                                         |
                          independently reviewed outcome
```

No source extraction, model output, solver result, or precedent independently
authorizes an external action.

## Architectural layers

| Layer | Main paths | Responsibility |
|---|---|---|
| Contracts and IO | `ruler/contracts/`, `ruler/schemas.py`, `ruler/io.py`, `ruler/paths.py` | Strict typed boundaries, serialization, identifiers, and repository paths |
| Ingestion and sources | `ruler/ingestion/`, `ruler/source/`, `data/sources/`, `refs/` | Discover, fetch, extract, inventory, and stage evidence without automatic promotion |
| Formal knowledge | `ruler/kb/`, `kb/corpora/`, `kb/formalized/` | Corpus manifests, logical IR, formalism projections, source grounding, promotion, and release validation |
| KB management | `ruler/kb/workspace_*`, `kb/workspaces/` | Named KBs, immutable revisions, lifecycle, search, capabilities, packages, RBAC, inference, and replay |
| Domain packs | `ruler/domains/` | Vocabulary, document taxonomy, predicates, translation contracts, and domain-specific rules |
| Formal evaluation | `ruler/evaluation/`, `ruler/reasoning/`, `ruler/solvers/` | Release-pinned consequences, contradictions, eligibility, counterfactuals, recommendation, and optimization |
| Case-based reasoning | `ruler/cbr/`, `data/cbr/` | Strict case records, profiles, hard filters, deterministic similarity, adaptation, replay, and outcomes |
| Interfaces | `ruler/interfaces/` | Visual workspace, API, demonstrators, graphs, dashboards, and redacted views |
| Runtime governance | `ruler/runtime/`, `.ruler/`, `skills/`, `.githooks/` | CLI/MCP execution, validation, workflows, hooks, routing, skills, and client bridges |

Dependencies flow inward toward contracts and formal evaluation. Domain packs and
interfaces extend the core; they do not redefine its semantics. The architectural
rule is recorded in [ADR 0001](adr/0001-core-domain-application-boundary.md).

## Knowledge representation

Ruler supports multiple formalization styles through one managed interface:

- Logical IR as a typed interchange representation;
- ASP/Clingo for rule consequences and model-based checks;
- Prolog projections for operational cross-checks;
- Z3 and MaxSMT for constraints and preference-aware optimization;
- OR-Tools for bounded configuration problems;
- RDF graphs for linked assertions and provenance;
- TPTP/Vampire and Lean-oriented artifacts for proof/consistency workflows;
- structured legal assurance packets that classify support without making legal determinations.

Capabilities are discovered from the selected immutable artifact release. The system
does not claim a backend operation that the artifact cannot truthfully support.

## Knowledge-base management

`KnowledgeBaseCatalog` adapts declarative corpus manifests as read-only KBs and manages
locally created KBs. A managed KB has:

- immutable `kb_id` and mutable display metadata;
- one or more immutable content-addressed versions;
- declared domain, purpose, formalism, language, status, and access mode;
- artifact dependencies and source references;
- draft/candidate/reviewed/published/retired release envelopes;
- capability-routed queries and content-addressed run replay.

Mutations use exact confirmation, ETags, idempotency keys, per-KB locking, and
append-only audit. Published revisions are superseded, not overwritten. Portable KB
packages preserve digests and reject collisions, traversal, and undeclared content.

See [KB Workspace](../guides/kb_workspace.md).

## Formal evaluation

An evaluation request identifies the case, immutable rule release, typed facts, and
expected rules. The pipeline reports support for target and contrary conclusions and
uses an explicit status such as satisfied, violated, unknown, or conflict. It never
equates missing support with domain falsity.

Hard constraints establish feasibility. Only feasible options reach recommendation or
optimization. Counterfactuals rerun the same formal boundary with explicit fact
changes; explanations are derived from stored artifacts and traces.

## Case-based reasoning

The CBR kernel adds operational experience without weakening formal authority:

1. Normalize a strict current case against a domain feature registry.
2. Apply access, domain, kind, jurisdiction, temporal, release, and feature hard filters.
3. Rank eligible reviewed cases with transparent typed comparators.
4. Return stable top-k results plus a deliberately excluded contrast.
5. Construct a typed adaptation that preserves current facts and never copies approvals
   or dispositions.
6. Verify the proposal against the current rule release and generate counterfactuals.
7. Retain an observed outcome only after independent review.

Case libraries are release-pinned KBs dependent on formal rule releases. Old cases
remain historical records when rules change and are marked for re-evaluation rather
than rewritten. See [CBR demonstrators](../guides/cbr_demonstrators.md).

## Domain packs

Installed packs include legal, regulatory, spending, fiscal,
trade, and technical support. A pack declares vocabulary and semantics; it does not
own the neutral contracts, storage, API, or solver infrastructure.

New packs must fail closed on undeclared predicates/features, define scope and
translation contracts, and include negative tests. Public-law packs carry explicit
as-of dates and non-reliance boundaries.

## Interfaces

### CLI

`ruler/cli.py` exposes the neutral `ruler` command and `ruler` compatibility
alias. The CLI is the canonical local execution boundary for KB, CBR, ingestion,
workflow, routing, hook, serving, and validation operations.

### HTTP workspace

`create_kb_workspace_app` provides a loopback, token-protected FastAPI application.
It combines the KB portfolio with the Cases workspace and enforces redaction,
resource bounds, CSP, ETags, idempotency, and immutable replay.

### MCP

The FastMCP stdio server exposes a bounded allowlist of resources and tools. It has no
arbitrary shell tool. Workflow writes require explicit permission; all CBR MCP tools
are read-only and outcome retention is absent.

### Generated artifacts

Dashboards, workflow graphs, demonstrators, comparison reports, decision packets, and
benchmarks are written under `build/ruler/`. They are reproducible views, not
authoritative editable state.

## Runtime governance

Three registries must agree:

- `.ruler/workflows.yaml` — execution classification, effects, inputs, outputs,
  validators, tools, and lifecycle;
- `.ruler/hooks.yaml` — named command gates;
- `skills/SKILL_HOOKS.yaml` — skill ownership and stage bindings.

`data/use_cases/workflow_router.yaml` maps user intent to registered workflows. The
execution-catalogue validator checks that every public workflow has a live Click
command and that hooks, router entries, and skills resolve without drift.

The generative orchestrator builds on this deterministic router. A configured model
may interpret an ambiguous request and propose only route identifiers enumerated in a
strict response schema. RULER then discards any model-supplied operational metadata and
loads commands, skills, inputs, outputs, and gates from the trusted catalogue. Its
artifact-level receipt records selected route and skill identifiers, provider/model,
schema validation, and content hashes—not hidden reasoning—and explicitly records that
no selected skill was executed. Execution remains a separate authorized operation.

## Security and privacy boundaries

- Loopback-only visual service with ephemeral authentication token.
- Field-level RBAC and redacted source/case views.
- Bounded input sizes, candidate pools, solver models, previews, and concurrency.
- Traversal, symlink, collision, stale-write, and duplicate-content checks.
- Secret-bearing configuration is reported only as presence/absence.
- Stored content is escaped; visual pages use restrictive browser headers.
- No hidden chain-of-thought in artifacts or logs.
- External acquisition and model-backed workflows are explicit and separately budgeted.

The complete rationale is in [Trust and assurance](../concepts/trust-and-assurance.md).

## Validation architecture

`ruler/runtime/validation.py` aggregates focused validators. `ruler validate all`
runs every offline gate, then pytest, Ruff, and `git diff --check`. Live source refreshes
and generative release suites are intentionally separate.

Important focused commands:

```bash
uv run ruler validate contracts
uv run ruler corpora validate
uv run ruler validate kb-workspace
uv run ruler validate cbr
uv run ruler validate workflow-registry
uv run ruler validate mcp-server
```

See the [release checklist](../operations/release-checklist.md).

## Extension sequence

1. Add or version source evidence and corpus manifests.
2. Add neutral contract capability only if it generalizes beyond one domain.
3. Add domain vocabulary and semantics in a domain pack.
4. Add formal artifacts, goldens, negative controls, and release pins.
5. Add the smallest truthful CLI/API/MCP surface.
6. Register workflows, hooks, router intents, and skills.
7. Document the trust boundary and run focused plus complete validation.
