<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Command-line reference

Run commands from the repository root through `uv`:

```bash
uv run ruler COMMAND
```

`ruler` is the canonical project CLI. Use `--help` at any level for the exact options
of the installed revision, for example `uv run ruler kb infer --help`.

## Command families

| Family | Purpose | Mutation behavior |
|---|---|---|
| `domains` | List and inspect installed domain packs | Read-only |
| `corpora` | List, validate, and emit the corpus schema | Read-only |
| `kb` | Manage named KBs, releases, search, inference, replay, and packages | Management commands are dry-run unless `--apply` |
| `cbr` | List libraries; show, retrieve, compare, adapt, verify, and retain cases | Retention is dry-run unless `--apply` |
| `evaluate` | Run release-pinned formal evaluation cases | Read-only |
| `legal` | Validate source-bound legal candidate packets | Read-only assurance only |
| `ingestion` | Run the provider-neutral staged ingestion pipeline | Stage-specific; publication is separately gated |
| `sources` | Plan, acquire, extract, and inspect source corpora | Network and writes are explicit per subcommand |
| `workflow` | Run registered artifact workflows | Effects are declared in `.ruler/workflows.yaml` |
| `route` | Match natural-language intent to known workflows | Read-only; catalogue generation writes artifacts |
| `validate` | Run focused or complete deterministic gates | Read-only except declared generated validation artifacts |
| `serve` | Start the loopback KB workspace or stdio MCP server | Long-running local process |
| `hook` | Run a named governed hook | Effects declared in `.ruler/hooks.yaml` |
| `config` | Inspect redacted runtime configuration | Read-only |

## Knowledge bases

```bash
ruler kb list
ruler kb show KB_ID
ruler kb search TEXT [--kb KB_ID]
ruler kb capabilities KB_ID
ruler kb releases KB_ID
ruler kb compare LEFT_KB RIGHT_KB
ruler kb query-editor KB_ID
ruler kb infer KB_ID [OPTIONS]
```

Managed writes preserve immutable revisions:

```bash
ruler kb create [OPTIONS]                 # dry-run
ruler kb create [OPTIONS] --apply
ruler kb rename KB_ID NAME --apply
ruler kb add-artifact KB_ID [OPTIONS] --apply
ruler kb release-transition KB_ID STAGE --evidence FILE --apply
ruler kb package-export KB_ID OUTPUT --apply
ruler kb package-inspect PACKAGE
ruler kb package-import PACKAGE           # dry-run
```

Use command help for typed formalism and inference options. Input atoms are bounded and
validated; arbitrary solver programs and arbitrary shell commands are not accepted.

## Case-based reasoning

```bash
ruler cbr libraries
ruler cbr show-case DOMAIN CASE_ID
ruler cbr retrieve DOMAIN [--query-file CASE.json] [--top-k 3]
ruler cbr compare DOMAIN LEFT_CASE RIGHT_CASE
ruler cbr adapt DOMAIN SOURCE_CASE
ruler cbr verify DOMAIN
ruler cbr retain OUTCOME.json              # validation-only dry-run
ruler cbr retain OUTCOME.json --apply
```

`retrieve` accepts at most a bounded strict `CBRCaseRecord`. `adapt` emits a typed plan
and never copies a precedent disposition or approval. `verify` evaluates the canonical
demonstration query against current rules. A retained `OutcomeObservation` must be
reviewed and identify an independent reviewer.

## Workflows and validation

Discover registered commands dynamically:

```bash
ruler workflow --help
ruler workflow execution-catalogue
ruler route catalogue
ruler validate --help
```

Frequently used CBR and platform gates:

```bash
ruler workflow cbr-demonstrators
ruler workflow cbr-benchmark
ruler validate cbr
ruler validate kb-workspace
ruler validate workflow-registry
ruler validate mcp-server
ruler validate all
```

`validate all` is the release gate. It intentionally skips live source acquisition and
budgeted generative runs; those have separate explicit workflows.

## Intent orchestration

```bash
ruler route query "describe the desired outcome"
ruler route guide "describe the desired outcome"
ruler route guide --allow-network "describe an ambiguous objective"
```

`query` is the lexical deterministic router. `guide` adds an explanatory envelope and
remains deterministic/offline by default. With explicit network authorization it uses
the configured provider for schema-constrained semantic interpretation. It may select
only registered route identifiers; all operational metadata is reloaded from the
catalogue, and no suggested command or skill is executed.

## Exit behavior

- Exit code `0`: the command completed and its declared checks passed.
- Nonzero exit: validation, schema, lookup, safety, resource, or execution failure.
- “unknown” in a reasoning payload is a domain result, not a process failure.
- Dry-run success confirms that a request validates; it does not mean a mutation occurred.
