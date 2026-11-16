<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Getting started

## Requirements

- Python 3.12 or newer
- [`uv`](https://docs.astral.sh/uv/) for dependency and command execution
- Git for repository checks and local hooks

Solver and document-processing dependencies are installed through the project lockfile;
do not install Clingo, Z3, OR-Tools, Docling, or the MCP SDK separately unless you are
debugging a platform-specific build. SWI-Prolog is a system executable rather than a
Python package; install it only when running a workflow that declares Prolog execution
as an acceptance requirement.

## Install

From the repository root:

```bash
uv sync --extra dev
uv run ruler validate deps
uv run ruler --help
```

`uv run ruler ...` is the canonical command surface used throughout the project.

## Verify the checkout

Use the focused gates while developing:

```bash
uv run ruler validate contracts
uv run ruler validate workflow-registry
uv run ruler validate cbr
uv run pytest -q tests/cbr
```

Before release or handoff, install SWI-Prolog so `swipl` is on `PATH`
(for example, `brew install swi-prolog` on macOS or
`sudo apt-get install swi-prolog-nox` on Ubuntu), then prepare the matching browser
and generated report inputs:

```bash
uv run playwright install chromium
uv run ruler prepare checks
```

On Linux CI, use `uv run playwright install --with-deps chromium`.
Preparation uses recorded local evidence and makes no live generative calls.
Validators must not generate or repair missing inputs. After preparation, run the
complete offline gate:

```bash
uv run ruler validate all
```

This command runs every registered validator, the full test suite, Ruff, and
`git diff --check`. Networked source refreshes and budgeted generative evaluations are
deliberately excluded.

## Choose an interface

The CLI is the execution boundary in every environment, so a workflow has the same
contracts and solver semantics whether a person or an agent starts it.

| Interface | Start here | Validate the integration |
|---|---|---|
| Terminal or application process | `uv run ruler --help` | `uv run ruler validate all` |
| Codex | Open the repository and request a canonical RULER skill or workflow | `uv run ruler validate codex` |
| Claude Code | Use a project RULER slash skill | `uv run ruler validate claude-code` |
| OpenCode | Use `/reason`, `/validate`, or a project RULER skill | `uv run ruler validate opencode` |
| Any MCP client | Launch `uv run ruler-mcp` over stdio | `uv run ruler validate mcp-server` |

The agent bridges contain routing instructions, not alternate reasoning
implementations. See the [Claude Code guide](guides/claude_code.md),
[OpenCode guide](guides/opencode.md), and [MCP guide](guides/mcp_server.md).

## Configure optional generative stages

The default local provider allows deterministic, network-free operation. Remote
generation is opt-in: choose a provider and model through the `RULER_GENAI_*`
environment variables, place its credential only in the environment variable named by
the provider configuration, and explicitly enable network use.

```bash
uv run ruler config generative
uv run ruler validate api-config
```

These commands report configuration with credentials redacted. Generative stages may
propose formalizations and explanations; accepted rules and deterministic backends keep
authority over computed conclusions.

To begin from a prose objective rather than a known command, use the orchestrator:

```bash
uv run ruler route guide "formalize these requirements and compare feasible options"
uv run ruler route guide --allow-network "help me identify the right governed workflow"
```

The first form remains offline. The second calls the configured provider only with
explicit authorization. Its output is schema-validated and restricted to registered
route identifiers. It returns canonical skills, commands, artifacts, and validation
gates for guidance, but does not execute a skill or authorize a write.

## Explore the knowledge-base portfolio

```bash
uv run ruler domains list
uv run ruler corpora list
uv run ruler corpora validate
uv run ruler kb list
uv run ruler kb show regulatory-proof
uv run ruler kb capabilities regulatory-proof
uv run ruler kb search proportionality --kb legal-sr101-art36
```

Corpus manifests are immutable, hash-bound inventories. The KB layer adds stable
names, releases, access control, search, capability routing, inference, replay, and
portable packages.

## Run a formal evaluation

```bash
uv run ruler evaluate regulatory-proof --case satisfied_boundary
uv run ruler evaluate regulatory-proof --case open_world_unknown
```

The second case demonstrates the open-world boundary: missing evidence is reported as
unknown, not silently converted to false.

## Run case-based reasoning

```bash
uv run ruler cbr libraries
uv run ruler cbr retrieve spending
uv run ruler cbr adapt spending spend-precedent-microscope-009
uv run ruler cbr verify spending
uv run ruler workflow cbr-demonstrators
uv run ruler workflow cbr-benchmark
```

Retrieval explains similarity and decisive differences. Adaptation is a typed proposal;
the historical disposition is not copied. Verification applies the current rule
release, and all actions remain human-review gated.

## Start local interfaces

Authenticated KB and Cases workspace:

```bash
uv run ruler serve kb-workspace
```

The server binds to loopback and prints a one-time URL containing an ephemeral token.
CBR API routes require a bearer token even when the visual KB routes accept the token
from the printed URL. The **Ask KB** tab uses an installed and authenticated `codex exec`
in an ephemeral read-only sandbox; see the
[conversational KB guide](guides/kb_conversation.md).

MCP stdio server:

```bash
uv run ruler serve mcp
# equivalent: uv run ruler-mcp
```

See the [KB guide](guides/kb_workspace.md), [CBR guide](guides/cbr_demonstrators.md),
and [MCP guide](guides/mcp_server.md) for the security and mutation boundaries.

## Where outputs go

- `build/ruler/` — reproducible reports and demonstrators
- `kb/corpora/` — reviewed declarative corpus manifests and artifacts
- `kb/workspaces/` — locally managed KB state and immutable releases
- `data/` — fixtures, candidates, use cases, source inventories, and operations data
- `skills/` — canonical runtime skills; `.claude/` and `.opencode/` contain wrappers

Do not edit generated output to change system behavior. Change the typed source,
manifest, registry, or workflow and regenerate it.
