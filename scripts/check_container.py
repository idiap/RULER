# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Run the built image with disposable PostgreSQL and no exposed host ports."""

from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

CLIENT = """
import asyncio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def main():
    async with streamable_http_client('http://127.0.0.1:8080/mcp') as (read, write, _):
        async with ClientSession(read, write) as client:
            await client.initialize()
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {'ruler_prepare_knowledge', 'ruler_prepare_request', 'ruler_execute_reasoning', 'ruler_retrieve_results'}
            projects = await client.call_tool('ruler_prepare_knowledge', {'input': {'action': 'discover'}})
            assert not projects.isError, projects
            assert projects.structuredContent['count'] > 0, projects
asyncio.run(main())
"""


def check(image: str, *, shared: bool = False) -> None:
    mode = "shared PostgreSQL 16" if shared else "standalone PostgreSQL 17"
    print(f"Checking {mode}...", flush=True)
    prefix = "ruler-container-check-" + uuid4().hex[:10]
    database, service = prefix + "-db", prefix + "-mcp"
    # These credentials exist only in this isolated, temporary test network.
    owner = "postgresql+pg8000://ruler_migrator:ci_test_only@postgres/ruler"
    runtime = "postgresql+pg8000://ruler_runtime:ci_runtime_only@postgres/ruler"

    def docker(*arguments, timeout=300, required=True, input_text=None):
        result = subprocess.run(
            ["docker", *arguments],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            input=input_text,
        )
        if required and result.returncode:
            # Only isolated test credentials are passed to these containers.
            print(result.stdout + result.stderr, file=sys.stderr)
            result.check_returncode()
        return result

    docker("network", "create", prefix)
    try:
        docker(
            "run",
            "--detach",
            "--name",
            database,
            "--network",
            prefix,
            "--network-alias",
            "postgres",
            "--env",
            "POSTGRES_USER=postgres",
            "--env",
            "POSTGRES_PASSWORD=ci_test_only",
            "--env",
            "POSTGRES_DB=postgres",
            "postgres:16" if shared else "postgres:17",
        )
        deadline = time.monotonic() + 60
        while docker(
            "exec",
            database,
            "pg_isready",
            "-h",
            "127.0.0.1",
            "-U",
            "postgres",
            "-d",
            "postgres",
            required=False,
        ).returncode:
            if time.monotonic() >= deadline:
                raise RuntimeError("test PostgreSQL did not start")
            time.sleep(1)
        # Exercise a non-superuser migration login and database
        # ownership, rather than giving the migration job PostgreSQL superuser.
        if shared:
            # Exercise the checked-in bootstrap with a restricted database admin,
            # including PostgreSQL 16's SET ROLE requirement for DB ownership.
            docker(
                "exec",
                database,
                "psql",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                "CREATE ROLE bootstrap LOGIN CREATEROLE CREATEDB;",
            )
            setup = (Path(__file__).parents[1] / "infra/postgres/bootstrap.sql.example").read_text()
            setup = setup.replace("REPLACE_WITH_NEW_MIGRATOR_PASSWORD", "ci_test_only")
            setup = setup.replace("REPLACE_WITH_NEW_RUNTIME_PASSWORD", "ci_runtime_only")
            docker(
                "exec",
                "-i",
                database,
                "psql",
                "-U",
                "bootstrap",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                "-",
                input_text=setup,
            )
        else:
            docker(
                "exec",
                "-i",
                database,
                "psql",
                "-U",
                "postgres",
                "-d",
                "postgres",
                "-v",
                "ON_ERROR_STOP=1",
                "-f",
                "-",
                input_text=(
                    "CREATE ROLE database_owner CREATEROLE CREATEDB; "
                    "CREATE ROLE ruler_migrator LOGIN CREATEROLE CREATEDB "
                    "PASSWORD 'ci_test_only' IN ROLE database_owner; "
                    "CREATE DATABASE ruler OWNER database_owner;"
                ),
            )
        uid = docker("run", "--rm", "--entrypoint", "id", image, "-u").stdout.strip()
        assert uid == "10001", uid
        docker(
            "run",
            "--rm",
            "--network",
            prefix,
            "--env",
            f"RULER_DATABASE_URL={owner}",
            "--env",
            f"RULER_RUNTIME_DATABASE_URL={runtime}",
            "--env",
            "RULER_EXPECTED_DATABASE=ruler",
            image,
            "uv",
            "run",
            "--no-sync",
            "ruler",
            "database",
            "prepare-deployment",
            "--source",
            "/app",
            *(["--preprovisioned-runtime"] if shared else []),
        )
        docker(
            "run",
            "--detach",
            "--name",
            service,
            "--network",
            prefix,
            "--memory=2g",
            "--cpus=1",
            "--env",
            f"RULER_DATABASE_URL={runtime}",
            "--env",
            "RULER_EXPECTED_DATABASE=ruler",
            image,
        )
        deadline = time.monotonic() + 180
        while docker(
            "exec",
            service,
            "python",
            "-c",
            "from urllib.request import urlopen; "
            "assert urlopen('http://127.0.0.1:8080/healthz', timeout=2).read() == b'ok'",
            required=False,
        ).returncode:
            if time.monotonic() >= deadline:
                raise RuntimeError("test MCP service did not become healthy")
            if (
                docker("inspect", "--format", "{{.State.Running}}", service).stdout.strip()
                != "true"
            ):
                raise RuntimeError("test MCP service exited")
            time.sleep(1)
        docker("exec", service, "python", "-c", CLIENT)
        print(
            f"Container passed ({mode}): nonroot, migration/import, health and PostgreSQL-backed MCP.",
            flush=True,
        )
    except Exception:
        result = docker("logs", service, required=False)
        print(result.stdout + result.stderr, file=sys.stderr)
        raise
    finally:
        docker("rm", "--force", "--volumes", service, database, required=False)
        docker("network", "rm", prefix, required=False)


if __name__ == "__main__":
    try:
        check(sys.argv[1])
        check(sys.argv[1], shared=True)
    except Exception:
        sys.exit("Container check failed; disposable containers/network have been removed.")
