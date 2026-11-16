# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Real PostgreSQL acceptance tests; no SQLite or in-memory database substitute.

Set RULER_TEST_DATABASE_URL to a disposable PostgreSQL database. Each test creates
and removes its own schema, leaving unrelated tables and workspaces untouched.
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import hashlib
import os
import shutil
from uuid import uuid4
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from click.testing import CliRunner
import pytest
import sqlalchemy as sa
import yaml
from ruler.cli import main
from ruler.paths import CODE_ROOT
from ruler.persistence.database import database_engine, database_url, migration_config
from ruler.persistence.schema import entries, metadata, objects, plans
from ruler.persistence.workspace import PostgresMCPRuntime, PostgresWorkspace
from ruler.runtime.mcp_server import MCP_TOOL_NAMES, create_mcp_server


@pytest.fixture
def postgres(monkeypatch):
    raw = os.environ.get("RULER_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set RULER_TEST_DATABASE_URL to run real PostgreSQL integration tests")
    admin = database_engine(raw)
    schema = "ruler_test_" + uuid4().hex
    with admin.begin() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    url = database_url(raw).update_query_dict({"options": f"-csearch_path={schema}"})
    monkeypatch.setenv("RULER_DATABASE_URL", url.render_as_string(hide_password=False))
    monkeypatch.setenv("RULER_MCP_WORKSPACE", "acceptance")
    result = CliRunner().invoke(main, ["database", "upgrade"])
    assert result.exit_code == 0, result.output
    store = PostgresWorkspace()
    try:
        yield store
    finally:
        store.engine.dispose()
        with admin.begin() as connection:
            connection.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "seed"
    corpus = root / "kb/corpora/test-corpus"
    corpus.mkdir(parents=True)
    content = b"ok.\n-obligation(subject).\n"
    (corpus / "rules.lp").write_bytes(content)
    manifest = {
        "schema_version": "2.0",
        "domain_id": "regulatory",
        "corpus_id": "test-corpus",
        "description": "Database-backed inference acceptance corpus.",
        "artifacts": [
            {
                "artifact_id": "rules-v1",
                "document_id": "rules",
                "document_version": "1",
                "status": "approved",
                "path": "kb/corpora/test-corpus/rules.lp",
                "sha256": "sha256:" + hashlib.sha256(content).hexdigest(),
                "language": "asp",
                "category": "formal_logic",
                "artifact_type": "asp_module",
                "role": "Rules",
                "references": [],
            }
        ],
    }
    (corpus / "manifest.yaml").write_text(yaml.safe_dump(manifest))
    # Include representative inputs for every non-KB MCP persistence surface.
    for name in (
        ".ruler",
        "skills",
        "data/use_cases",
        "data/reference",
        "data/cbr",
        "data/domains",
    ):
        shutil.copytree(CODE_ROOT / name, root / name)
    return root


def call(server, name, **arguments):
    _, result = asyncio.run(server.call_tool(name, arguments))
    return result


def test_database_configuration_is_postgres_only_and_redacted(monkeypatch):
    monkeypatch.delenv("RULER_DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="no filesystem fallback"):
        PostgresWorkspace()
    for value in ("sqlite:///data.db", "not-a-url-password", "mysql://secret@host/db"):
        with pytest.raises(ValueError) as error:
            database_url(value)
        assert "secret" not in str(error.value)
        assert "password" not in str(error.value)


@pytest.mark.parametrize(
    "driver", ["postgres", "postgresql", "postgresql+pg8000", "postgresql+psycopg"]
)
def test_database_urls_select_pg8000_and_preserve_unix_socket(driver):
    url = database_url(f"{driver}://user:password@/ruler?host=/var/run/postgresql")
    assert url.drivername == "postgresql+pg8000"
    assert url.host is None
    assert dict(url.query) == {"unix_sock": "/var/run/postgresql/.s.PGSQL.5432"}
    assert url.username == "user"
    assert url.password == "password"


def test_pg8000_startup_options_are_passed_as_server_parameters():
    engine = database_engine("postgresql+pg8000://user@localhost/ruler?options=-csearch_path=test")
    try:
        assert "options" not in engine.url.query
        # Build the connection arguments without opening a network connection.
        captured = {}

        @sa.event.listens_for(engine, "do_connect")
        def capture(dialect, connection_record, args, kwargs):
            captured.update(kwargs)
            raise RuntimeError("connection intercepted")

        with pytest.raises(RuntimeError, match="connection intercepted"):
            engine.connect()
        assert captured["startup_params"] == {"options": "-csearch_path=test"}
    finally:
        engine.dispose()


def test_legacy_socket_url_preserves_query_port():
    url = database_url("postgresql://user@/ruler?host=/tmp&port=55439")
    assert dict(url.query) == {"unix_sock": "/tmp/.s.PGSQL.55439"}


def test_migrations_upgrade_downgrade_and_schema_drift(postgres):
    with postgres.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), metadata) == []
        assert set(sa.inspect(connection).get_table_names()) == {
            "alembic_version",
            "mcp_workspaces",
            "mcp_objects",
            "mcp_workspace_entries",
            "mcp_import_plans",
            "mcp_invocations",
            "mcp_workspace_objects",
        }
    command.downgrade(migration_config(), "base")
    with postgres.engine.connect() as connection:
        assert sa.inspect(connection).get_table_names() == ["alembic_version"]
    with pytest.raises(RuntimeError, match="schema is not current"):
        postgres.check_ready()
    command.upgrade(migration_config(), "head")
    with pytest.raises(RuntimeError, match="not initialized"):
        postgres.check_ready()


def test_product_import_inference_and_results_survive_restart(postgres, source):
    imported = CliRunner().invoke(main, ["database", "import-workspace", "--source", str(source)])
    assert imported.exit_code == 0, imported.output
    shutil.rmtree(source)
    server = create_mcp_server(runtime=PostgresMCPRuntime(postgres))
    assert {t.name for t in asyncio.run(server.list_tools())} == set(MCP_TOOL_NAMES)
    plan = call(
        server,
        "ruler_prepare_knowledge",
        input={"action": "plan_import", "project_id": "regulatory", "corpus_id": "test-corpus"},
    )
    assert plan["status"] == "planned"
    args = {"input": {"action": "apply_import", "plan_id": plan["plan_id"]}}
    assert call(server, "ruler_prepare_knowledge", **args)["status"] == "blocked"
    other_store = PostgresWorkspace()
    restarted = create_mcp_server(runtime=PostgresMCPRuntime(other_store))
    try:
        assert (
            call(restarted, "ruler_prepare_knowledge", **args, allow_write=True)["status"]
            == "blocked"
        )
        imported = call(server, "ruler_prepare_knowledge", **args, allow_write=True)
        assert imported["status"] == "imported"
        assert imported["persistent_artifacts"]
        assert (
            call(server, "ruler_prepare_knowledge", **args, allow_write=True)["status"] == "blocked"
        )
        request = {
            "request_id": "pg-query",
            "operation": "query",
            "backend_id": "clingo-ground-query-v1",
            "artifact_id": "rules-v1",
            "query": "ok",
        }
        assert (
            call(restarted, "ruler_prepare_request", kb_id=imported["kb_id"], request=request)[
                "status"
            ]
            == "blocked"
        )
        prepared = call(restarted, "ruler_prepare_request", kb_id="test-corpus", request=request)[
            "prepared"
        ]
        assert call(restarted, "ruler_execute_reasoning", prepared=prepared)["status"] == "blocked"
        executed = call(restarted, "ruler_execute_reasoning", prepared=prepared, allow_execute=True)
        assert executed["status"] == "completed"
        assert executed["result"]["target_support"] == "proved"
        retrieved = call(server, "ruler_retrieve_results", run_id=executed["run_id"])
        assert retrieved["record"]["result"] == executed["result"]
        artifact = executed["persistent_artifacts"][0]
        assert postgres.artifact(artifact["sha256"][7:])["content_base64"]
        assert asyncio.run(server.read_resource(artifact["uri"]))
        with postgres.engine.connect() as connection:
            assert (
                connection.execute(sa.select(sa.func.count()).select_from(plans)).scalar_one() == 0
            )
    finally:
        other_store.engine.dispose()


def test_failed_worker_and_failed_database_commit_roll_back(postgres, source, monkeypatch):
    postgres.import_workspace(source)
    runtime = PostgresMCPRuntime(postgres)
    with postgres.engine.connect() as connection:
        before = postgres.snapshot(connection)

    def partial_failure(root, operation, arguments, pending):
        (root / "partial.txt").write_bytes(b"uncommitted")
        raise RuntimeError("injected worker failure")

    with monkeypatch.context() as patch:
        patch.setattr(runtime, "_execute", partial_failure)
        with pytest.raises(RuntimeError, match="injected worker failure"):
            runtime.invoke("ruler_prepare_knowledge", {"input": {"action": "discover"}})

    def fail_commit(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO mcp_invocations"):
            raise RuntimeError("injected commit failure")

    sa.event.listen(postgres.engine, "before_cursor_execute", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="injected commit failure"):
            runtime.invoke("ruler_prepare_knowledge", {"input": {"action": "discover"}})
    finally:
        sa.event.remove(postgres.engine, "before_cursor_execute", fail_commit)
    with postgres.engine.connect() as connection:
        assert postgres.snapshot(connection) == before
    plan = runtime.invoke(
        "ruler_prepare_knowledge",
        {
            "input": {
                "action": "plan_import",
                "project_id": "regulatory",
                "corpus_id": "test-corpus",
            }
        },
    )
    sa.event.listen(postgres.engine, "before_cursor_execute", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="injected commit failure"):
            runtime.invoke(
                "ruler_prepare_knowledge",
                {
                    "input": {"action": "apply_import", "plan_id": plan["plan_id"]},
                    "allow_write": True,
                },
            )
    finally:
        sa.event.remove(postgres.engine, "before_cursor_execute", fail_commit)
    with postgres.engine.connect() as connection:
        assert postgres.snapshot(connection) == before
        assert connection.execute(sa.select(plans.c.plan_id)).scalar_one() == plan["plan_id"]
    assert (
        runtime.invoke(
            "ruler_prepare_knowledge",
            {"input": {"action": "apply_import", "plan_id": plan["plan_id"]}, "allow_write": True},
        )["status"]
        == "imported"
    )


def test_concurrent_imports_are_single_use_and_expired_plans_fail(postgres, source):
    postgres.import_workspace(source)
    runtime = PostgresMCPRuntime(postgres)
    plan = runtime.invoke(
        "ruler_prepare_knowledge",
        {
            "input": {
                "action": "plan_import",
                "project_id": "regulatory",
                "corpus_id": "test-corpus",
            }
        },
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                runtime.invoke,
                "ruler_prepare_knowledge",
                {
                    "input": {"action": "apply_import", "plan_id": plan["plan_id"]},
                    "allow_write": True,
                },
            )
            for _ in range(2)
        ]
        assert sorted((future.result()["status"] for future in futures)) == ["blocked", "imported"]
    expiring = runtime.invoke(
        "ruler_prepare_knowledge",
        {
            "input": {
                "action": "plan_import",
                "project_id": "regulatory",
                "corpus_id": "test-corpus",
                "kb_id": "expired-copy",
            }
        },
    )
    with postgres.engine.begin() as connection:
        connection.execute(
            plans.update().values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert (
        runtime.invoke(
            "ruler_prepare_knowledge",
            {
                "input": {"action": "apply_import", "plan_id": expiring["plan_id"]},
                "allow_write": True,
            },
        )["status"]
        == "blocked"
    )


def test_integrity_workspace_isolation_and_no_overwrite(postgres, source, tmp_path):
    postgres.import_workspace(source)
    with pytest.raises(ValueError, match="already exists"):
        postgres.import_workspace(source)
    other = PostgresWorkspace(workspace_id="isolated")
    minimal = tmp_path / "other"
    minimal.mkdir()
    (minimal / "README.md").write_text("unrelated workspace")
    other.import_workspace(minimal)
    with postgres.engine.begin() as connection:
        sha256 = postgres.put(connection, "data/private.bin", b"\x00\xffprivate")
        current_sha = postgres.put(connection, "data/private.bin", b"updated evidence")
    assert postgres.artifact(sha256)["content_base64"]
    with pytest.raises(LookupError, match="unavailable"):
        other.artifact(sha256)
    with postgres.engine.begin() as connection:
        connection.execute(
            objects.update()
            .where(objects.c.sha256.in_([sha256, current_sha]))
            .values(content=b"corrupted")
        )
    with pytest.raises(ValueError, match="SHA-256"):
        postgres.artifact(sha256)
    with pytest.raises(ValueError, match="SHA-256"):
        PostgresMCPRuntime(postgres).invoke(
            "ruler_prepare_knowledge", {"input": {"action": "discover"}}
        )
    other.engine.dispose()


def test_unsafe_artifact_paths_are_rejected(postgres, source):
    postgres.import_workspace(source)
    with postgres.engine.begin() as connection:
        for path in (
            ".",
            "../escape",
            "/tmp/escape",
            "kb/../../escape",
            "kb\\escape",
            "kb//escape",
        ):
            with pytest.raises(ValueError, match="relative paths"):
                postgres.put(connection, path, b"unsafe")
        assert not connection.execute(
            sa.select(entries).where(entries.c.path == "../escape")
        ).first()
