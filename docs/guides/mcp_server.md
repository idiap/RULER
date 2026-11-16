<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# MCP server

RULER exposes exactly four product workflows through FastMCP, over stdio or
Streamable HTTP. There is no arbitrary shell access and no case editing through
this interface. Developer workflows remain available through the native CLI.

## Run

```bash
uv sync --extra dev
# Supply a PostgreSQL database owned by the application; keep credentials in env.
export RULER_DATABASE_URL='postgresql+pg8000://ruler@localhost/ruler'
export RULER_MCP_WORKSPACE=default
uv run ruler database upgrade
uv run ruler database import-workspace --source .
uv run ruler serve mcp
# equivalent entry point
uv run ruler-mcp
```

Example client configuration from this repository root:

```json
{
  "mcpServers": {
    "ruler": {
      "command": "uv",
      "args": ["run", "ruler-mcp"],
      "cwd": "/absolute/path/to/ruler"
    }
  }
}
```

Use an absolute local path in `cwd`; do not copy a developer-specific path.
Configure `RULER_DATABASE_URL` in the MCP process environment as well. Never commit
database passwords to a client configuration. `RULER_MCP_WORKSPACE` selects the
database workspace and defaults to `default`.

## Product workflow surface

| Tool | Purpose |
| --- | --- |
| `ruler_prepare_knowledge` | Discover projects/KBs, plan and apply imports, author typed artifacts, advance governed release transitions, or run a registered batch stage. |
| `ruler_prepare_request` | Validate structured input, check backend capabilities, and pin a request to published knowledge. |
| `ruler_execute_reasoning` | Recheck the release pin, execute inference, and persist the completed result with a run ID. |
| `ruler_retrieve_results` | Retrieve the stored request, result and evidence with digest verification. |

The plugin exposes matching skills. There are no tools for developer validation,
benchmarks, demonstrations, workflow routing, source-code export, or generic
workflow dispatch. Those operations cannot be reached by naming an old tool.

### Prepare knowledge

Pass an `input` object with one of these `action` values:

- `discover`: list registered projects and KB metadata.
- `inspect`: provide `project_id` or `kb_id`; KB inspection includes product
  backend capabilities, artifact identifiers, version digest and release evidence.
- `plan_import`: provide `project_id`, `corpus_id`, optional `kb_id`.
- `apply_import`: provide the returned `plan_id` in the same MCP session and set
  `allow_write=true`. Plans expire and are single-use. Imports produce drafts.
- `create`: provide a native `definition` with a registered `domain_id`.
- `add_artifact`: provide `kb_id` and a native typed `artifact`, including its
  content and safe filename. Content is limited to one million characters.
- `transition`: provide `kb_id`, `target`, and existing hash-bound `evidence`.
  The native draft → candidate → reviewed → published order remains enforced;
  validation, review and publication evidence are required at their boundaries.
- `batch_status` / `batch_stage`: provide a registered `batch_id`, and for execution
  a `stage`. Native next-stage ordering and evidence gates remain authoritative.

All mutations require `allow_write=true`; batch execution additionally requires
`allow_network=true`. This is permission to run the configured native producer,
not permission to skip review. Raw source material must be formalized before it
can support executable inference. Batch automation still needs the prepared
project-specific catalogue and inputs; it is not a generic document converter.

### Prepare and execute a request

After a KB is published, inspect its capabilities and prepare a request:

```json
{
  "kb_id": "my-kb",
  "request": {
    "request_id": "question-1",
    "operation": "query",
    "backend_id": "clingo-ground-query-v1",
    "artifact_id": "rules",
    "query": "eligible(alice)",
    "asserted_facts": ["qualified(alice)"]
  }
}
```

The currently allowed product backends are `clingo-ground-query-v1` and
`legal-packet-assurance-v1`, where the selected KB actually supports them.
Natural-language intent must be formalized and reviewed before submission.
There is no synthetic-case substitution, preview execution or automatic backend
fallback. Pass the returned `prepared` object to `ruler_execute_reasoning` with
`allow_execute=true`, which authorizes inference and result storage. Changed
release pins require preparing the request again.

Use the returned `run_id` with `ruler_retrieve_results`. Preserve the native
conclusion, evidence, blockers and claim boundary in the product UI. Failed or
unsupported inference does not create a completed run. Result retrieval never
re-executes reasoning.

## Persistence and isolation

PostgreSQL is authoritative for every public tool. Alembic migrations and an
initialized workspace are required; there is no filesystem or SQLite fallback.
Each invocation materializes a workspace snapshot in an isolated worker. Changes,
import-plan consumption and invocation records commit under a workspace row lock.
Failed or blocked calls do not commit partial artifact changes. API credentials
remain in the environment.

Successful mutations return `persistent_artifacts`, including content-addressed
`ruler://artifacts/{digest}` URIs. This is the only resource template. Artifact
reads verify both workspace ownership and stored bytes. Completed run records
remain retrievable across server restarts; import plans remain session-bound.

Use [Portable deployment](deployment.md) for Streamable HTTP,
PostgreSQL provisioning and hosting configuration. Run `uv run ruler validate mcp-server`
and `uv run ruler validate plugins` to check the published surface.
