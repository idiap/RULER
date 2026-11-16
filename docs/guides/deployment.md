<!--
SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
SPDX-License-Identifier: LicenseRef-Idiap-Research-Education
-->

# Portable deployment

RULER runs on any host that supports its Python runtime and PostgreSQL, or its
Linux container image. Hosting, image registries, TLS, authentication, secret
injection and database operations are supplied by the operator. The repository
contains no provider-specific provisioning or deployment pipeline.

## Prepare the database

Provision a dedicated PostgreSQL database and separate migration and runtime
logins. For a shared instance, an administrator can adapt
[`bootstrap.sql.example`](../../infra/postgres/bootstrap.sql.example); replace
both password placeholders securely before execution. The migration login must
own only the RULER database and have no elevated instance-wide privileges.

Inject these settings into a one-off migration process:

- `RULER_DATABASE_URL`: migration login URL.
- `RULER_RUNTIME_DATABASE_URL`: runtime login URL for the same database.
- `RULER_EXPECTED_DATABASE`: database name, such as `ruler`.
- `RULER_MCP_WORKSPACE`: workspace name, defaulting to `default`.

Use PostgreSQL URLs such as `postgresql+pg8000://USER:PASSWORD@HOST:5432/ruler`,
with credentials supplied through your host's secret mechanism. Then run:

```bash
uv run ruler database prepare-deployment --source . --preprovisioned-runtime
```

This applies migrations, imports the workspace only if it does not exist, and
grants bounded runtime access. Run it explicitly before starting the service.
On a dedicated instance where the migration login can manage roles, omit
`--preprovisioned-runtime` to create or rotate the runtime login.

## Run the service

Supply `RULER_DATABASE_URL` using the runtime login, `RULER_EXPECTED_DATABASE`,
and the same `RULER_MCP_WORKSPACE`. For HTTP, set `RULER_MCP_ALLOWED_HOSTS` to a
comma-separated list of the actual request hostnames (including ports where
needed). It defaults to loopback hosts. Configure TLS and authentication at the
hosting boundary; the host allowlist is not authentication.

```bash
uv run ruler serve mcp --transport streamable-http --host 0.0.0.0 --port 8080
```

The MCP endpoint is `/mcp`; `/healthz` provides a health probe. `PORT` also sets
the listening port. HTTP sessions are stateful: route a session to the same
process and reconnect after restarts. PostgreSQL stores persistent workspace
state; local workspace materializations are temporary.

## Container and verification

Prepare the intended workspace inputs before building; see the
[development guide](../development/contributing.md) for evidence preparation.
The image runs as UID 10001 and starts the HTTP server on port 8080 by default.

```bash
docker build -t ruler-mcp:local .
python scripts/check_container.py ruler-mcp:local
```

The check starts disposable PostgreSQL containers on an isolated Docker network,
verifies migrations, nonroot execution, health and MCP calls, then removes the
test containers and network. CI runs this check without hosting credentials.
Deploy the image using your chosen container runtime, injecting the settings
above. Run the migration command as a separate container command with
`--source /app`, before starting service containers. Back up PostgreSQL and
review schema compatibility before rolling back an image.

```bash
uv run ruler validate mcp-server
uv run ruler validate plugins
```
