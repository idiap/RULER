<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# RULER

## Overview

RULER turns rigorously stated natural-language sources into formal knowledge
bases, checked decisions, and traceable explanations. It combines generative
interpretation with deterministic validation and logic or optimization backends.
The result retains source evidence, accepted facts and rules, assumptions, solver
outputs, counterfactuals, and grounded explanations.

## Key concepts

- **Formal KB releases:** manage source-grounded facts and rules with immutable identities and explicit scope.
- **Controlled autoformalization:** propose, validate, execute, and review formal statements before acceptance.
- **Solver-backed decisions:** use declared logic, optimization, or scheduling capabilities for the computed result.
- **Case-based reasoning:** retrieve governed precedents, then verify the current case against current rules.
- **Separate authority:** generative interpretation and explanation cannot promote rules or replace formal inference; unknown remains distinct from false.

## Getting started

Use Python 3.12 or newer, Git, and `uv`. From the repository root:

```bash
uv sync --extra dev
uv run ruler validate deps
uv run ruler --help
```

SWI-Prolog is a separate system executable required by workflows that declare Prolog
acceptance checks. The complete gate also requires browser and report preparation;
follow [getting started](docs/getting-started/README.md) before running it.
For agent skill discovery, see the [plugin guide](docs/guides/plugins.md).

Product integrations use four MCP workflows: prepare knowledge, prepare a request,
execute reasoning, and retrieve results. The plugin exports only these workflows;
see the [MCP guide](docs/guides/mcp_server.md) for inputs and release requirements.

The CLI supports macOS, Linux, and Windows. For repository development, install
hooks with `uv run python scripts/install_hooks.py` and check portability with
`uv run ruler validate cross-platform`.

## Examples

Run two release-pinned evaluation cases:

```bash
uv run ruler evaluate regulatory-proof --case satisfied_boundary
uv run ruler evaluate regulatory-proof --case open_world_unknown
```

These contrast a satisfied boundary with an explicitly unknown outcome.
For a full cost, schedule, proof, and sensitivity report:

```bash
uv run ruler workflow resource-portfolio-demonstrator --kb-profile expanded
```

The [detailed project guide](docs/guides/project-guide.md#workflow-catalogue) preserves
the complete workflow catalog, diagrams, inputs, outputs, checks, and live-testing
profiles. Generated outputs belong under `build/ruler/`.

## Architecture

```text
source evidence → semantic basis → candidate facts and rules → acceptance gates
                → immutable formal KB → inference / optimization
                → decision packet, counterfactuals, and grounded explanation
```

`ruler/` implements the canonical CLI, typed contracts, ingestion, KB management,
reasoning, interfaces, and runtime adapters. `kb/` holds declarative knowledge;
`skills/` holds runtime skills; `proj_skills/` holds maintenance skills.
Agent bridges and MCP invoke the same CLI and contracts.

Read the [system architecture](docs/architecture/system_architecture.md),
[trust model](docs/concepts/trust-and-assurance.md), and
[repository walkthrough](docs/architecture/directory_structure_walkthrough.md).

## Documentation

<a id="knowledge-bases-and-formal-evaluation"></a>
<a id="source-acquisition-and-product-onboarding"></a>
<a id="translation-and-formalization"></a>
<a id="resource-portfolios"></a>
<a id="case-based-reasoning"></a>
<a id="assurance-logs-and-workflow-inspection"></a>
<a id="deterministic-and-generative-testing"></a>
<a id="what-ruler-does"></a>
<a id="get-started"></a>
<a id="workflow-catalogue"></a>
<a id="run-from-an-agent-or-mcp-client"></a>
<a id="cross-platform-operation"></a>
<a id="dependencies-and-licenses"></a>

Start with the [documentation index](docs/README.md). All project documentation
uses the same reading areas; specialist collections retain their stable paths.

- [Getting started](docs/getting-started/README.md) — Install the environment and complete a first example.
- [Concepts](docs/concepts/README.md) — Understand the project model, terminology, and evidence boundaries.
- [Guides](docs/guides/README.md) — Carry out tasks and interpret their outputs.
- [Architecture](docs/architecture/README.md) — Understand components, data flow, contracts, and extension points.
- [Reference](docs/reference/README.md) — Look up commands, skills, workflows, and documentation sources.
- [Development](docs/development/README.md) — Change the project and run the relevant checks.
- [Operations](docs/operations/README.md) — Configure, run, observe, and release maintained workflows.
- [Governance](docs/governance/README.md) — Check licensing, provenance, review, and publication requirements.
- [Archive](docs/archive/README.md) — Find historical material and distinguish plans from current behavior.

## Development and validation

Use [AGENTS.md](AGENTS.md) and [contributing](docs/development/contributing.md).
Start with checks appropriate to the changed surface. Before the complete gate,
install SWI-Prolog and prepare the required browser and reports:

```bash
uv run playwright install chromium
uv run ruler prepare checks
uv run ruler validate all
```

On Linux CI, use `uv run playwright install --with-deps chromium`.
Preparation uses recorded local evidence. Validators must not generate or repair
their inputs. The full offline gate includes tests, Ruff, and whitespace checks;
live acquisition and generative evaluations remain separate operations.

## Limitations and status

The computed result is conditional on the declared source, release, facts,
assumptions, and backend capability. Solver success does not supply absent evidence,
causal truth, or permission to act. Historical approval is not transferred to a new
case. Generative outputs remain candidates until their explicit acceptance gates
pass. Demonstrations and fixture metrics have the scope stated in their reports.

## Dependencies and license

RULER is licensed for non-commercial research and educational use only; see [LICENSE](LICENSE). Its PostgreSQL adapter uses pg8000 under BSD-3-Clause.
See [dependency licenses](docs/governance/LICENSES.md) for the dependency inventory and
upstream terms. The [software-disclosure guide](docs/development/software-disclosure.md)
explains source-only and development branches, restored evidence, and CI boundaries.
