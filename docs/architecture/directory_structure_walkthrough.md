<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Directory Structure Walkthrough

This is a concise orientation to the RULER repository. It is meant for maintainers,
reviewers, and future agents who need to know where to look before changing the system.

## Quick Orientation

| Path | Purpose |
|---|---|
| `ruler/` | Main Python package: CLI, typed contracts, reasoning, KB utilities, source ingestion, interfaces, runtime adapters, and solvers. |
| `kb/` | Declarative corpora, formalized artifacts, and locally managed immutable KB releases. |
| `data/` | Example inputs, synthetic cases, extracted candidates, source manifests, reference configuration, and workflow route data. |
| `skills/` | Runtime reasoning and workflow skills bound to hooks and validations. |
| `proj_skills/` | Project communication, compliance, and project-management skills kept outside the runtime skill registry. |
| `docs/` | Long-lived project documentation, plans, architecture notes, walkthroughs, and generated inventories. |
| `tests/` | Pytest suite organized by the same broad themes as the source package. |
| `build/ruler/` | Generated workflow outputs, dashboards, logs, graphs, and decision artifacts. |
| `.ruler/` | Canonical workflow registry and hook definitions used by the visible control plane. |
| `.githooks/` | Git hook entrypoints that call RULER validation workflows. |

## Runtime Package Map

| Path | What lives there |
|---|---|
| `ruler/cli.py` | Click command surface for workflows, validation, source processing, dashboards, and MCP startup. |
| `ruler/schemas.py` | Pydantic contracts shared across source, KB, reasoning, interfaces, and runtime adapters. |
| `ruler/io.py` | YAML, text, stable hash, and path-friendly serialization helpers. |
| `ruler/paths.py` | Repository path constants used by workflows and validators. |
| `ruler/contracts/` | Domain-neutral strict contracts shared by formalization and reasoning services. |
| `ruler/domains/` | Versioned vocabulary, predicate, taxonomy, and translation packs. |
| `ruler/ingestion/` | Provider-neutral staged ingestion, resource budgets, checkpoints, and publication gates. |
| `ruler/evaluation/` | Release-pinned formal evaluation and counterfactual contracts. |
| `ruler/reasoning/` | Fact activation, eligibility, policy effects, decision packets, package reasoning, counterfactuals, use cases, and reasoning controls. |
| `ruler/kb/` | Corpus adaptation, named KB management, release governance, capability-routed inference, replay, packages, translation, and formalization. |
| `ruler/cbr/` | Strict case records, feature registries, deterministic retrieval, adaptation, replay, and outcome retention. |
| `ruler/source/` | Source corpus extraction, exact-document intake, and evidence-preserving adapters. |
| `ruler/interfaces/` | Authenticated KB/CBR workspace, API, dashboards, logs, workflow graphs, and demonstrators. |
| `ruler/runtime/` | Validation control plane, hooks, MCP server, Claude Code bridge, OpenCode bridge, API config, and cross-platform support. |
| `ruler/solvers/` | Solver backends, currently including MaxSMT feature-choice support. |

## Data, KB, and Reference Material

`data/` holds registered domain inputs, case-based reasoning examples, operational
plans, and workflow-router cases. Synthetic translation fixtures live under
`tests/fixtures/translation/`.

`kb/corpora/` holds hash-bound corpus manifests and artifacts. `kb/workspaces/` holds
managed KB identities, immutable revisions, releases, run replay, and audit state.
Treat promoted KB material as separate from candidate extraction material: source
extraction does not automatically become active KB truth.

`refs/` stores reference documents copied into the project. It is an input/reference area,
not the runtime source of truth for promoted reasoning facts.

## Skills and Workflow Control

`skills/` contains runtime skills grouped by theme, such as `reasoning`, `source`,
`translation`, `workflow`, `runtime`, and `autoformalization`. Bindings live in
`skills/SKILL_HOOKS.yaml`.

`proj_skills/` contains project-facing skills for documentation, architecture
communication, license inventories, and project-management walkthroughs. These are not
the same as runtime reasoning skills.

`.ruler/hooks.yaml` defines named workflow stages. `.githooks/` contains local git hook
entrypoints that call those stages.

## Generated Artifacts

`build/ruler/` is generated. It contains dashboards, reasoning logs, workflow graphs,
decision packets, validation-derived reports, and demo artifacts. Regenerate artifacts
through the CLI instead of editing generated files by hand.

Common commands:

```bash
uv run ruler workflow inference-dashboard
uv run ruler workflow workflow-graphs
uv run ruler workflow cbr-demonstrators
uv run ruler workflow cbr-benchmark
```

## Tests and Validation

`tests/` mirrors the source layout:

- `tests/reasoning/`
- `tests/kb/`
- `tests/source/`
- `tests/interfaces/`
- `tests/runtime/`
- `tests/cbr/`
- `tests/domains/`

Run focused tests while changing a package, then run the broader gates before handoff:

```bash
uv run pytest -q
uv run ruler validate all
git diff --check
```

## Where to Start

- To understand the architecture, read `docs/architecture/system_architecture.md`.
- To understand the diagrams, read `docs/architecture/system_architecture_diagrams.md`.
- To follow the reasoning core, start with `ruler/reasoning/decision_packet.py`.
- To inspect KB loading and validation, start with `ruler/kb/formalized_kb.py`.
- To inspect named KB management, start with `ruler/kb/workspace_catalog.py`.
- To inspect case-based reasoning, start with `ruler/cbr/service.py` and
  `ruler/domains/cbr_catalog.py`.
- To understand runtime gates, start with `ruler/runtime/validation.py`.
- To add project communication docs, use `proj_skills/`.
