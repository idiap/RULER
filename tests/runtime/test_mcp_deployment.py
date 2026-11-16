# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: André Freitas <andre.freitas@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Deployment initialization against a disposable real PostgreSQL database."""

from contextlib import closing
import os
from uuid import uuid4

from click.testing import CliRunner
from pg8000.native import identifier, literal
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError

from ruler.cli import main
from ruler.persistence.database import database_engine, database_url
from ruler.persistence.schema import entries, workspaces
from ruler.persistence.workspace import PostgresWorkspace


@pytest.fixture
def deployment_database(monkeypatch, tmp_path):
    raw = os.environ.get("RULER_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set RULER_TEST_DATABASE_URL for real PostgreSQL deployment tests")
    admin = sa.create_engine(database_url(raw), isolation_level="AUTOCOMMIT")
    name = "ruler_deploy_" + uuid4().hex
    username = 'ruler_app_"' + uuid4().hex
    with admin.connect() as connection:
        connection.exec_driver_sql(f"CREATE DATABASE {identifier(name)}")
    owner = database_url(raw).set(database=name)
    runtime = owner.set(username=username, password="test secret ' @ percent % \\ ü")
    monkeypatch.setenv("RULER_DATABASE_URL", owner.render_as_string(hide_password=False))
    monkeypatch.setenv("RULER_RUNTIME_DATABASE_URL", runtime.render_as_string(hide_password=False))
    monkeypatch.setenv("RULER_MCP_WORKSPACE", "demo")
    source = tmp_path / "seed"
    source.mkdir()
    (source / "README.md").write_text("first import")
    try:
        yield source, runtime
    finally:
        with admin.connect() as connection:
            connection.exec_driver_sql(f"DROP DATABASE {identifier(name)} WITH (FORCE)")
            connection.exec_driver_sql(f"DROP ROLE IF EXISTS {identifier(username)}")
        admin.dispose()


def test_deployment_seeds_once_and_runtime_cannot_change_schema(deployment_database):
    source, runtime = deployment_database
    runner = CliRunner()
    result = runner.invoke(main, ["database", "prepare-deployment", "--source", str(source)])
    assert result.exit_code == 0, result.output
    (source / "README.md").write_text("must not replace persisted data")
    result = runner.invoke(main, ["database", "prepare-deployment", "--source", str(source)])
    assert result.exit_code == 0, result.output
    store = PostgresWorkspace(url=runtime.render_as_string(hide_password=False))
    try:
        store.check_ready()
        with store.engine.begin() as connection:
            assert store.snapshot(connection)["README.md"] == b"first import"
            # Runtime has the row-lock/update permissions needed by MCP.
            connection.execute(workspaces.update().values(workspace_id="demo"))
            assert connection.execute(sa.select(entries.c.path)).first() == ("README.md",)
        for statement in (
            "CREATE TABLE public.not_allowed (id integer)",
            "DROP TABLE public.mcp_workspaces CASCADE",
            "UPDATE public.alembic_version SET version_num = 'bad'",
            "CREATE ROLE not_allowed",
        ):
            with pytest.raises(ProgrammingError), store.engine.begin() as connection:
                connection.execute(sa.text(statement))
    finally:
        store.engine.dispose()


def test_deployment_refuses_to_reuse_owner_as_runtime(deployment_database, monkeypatch):
    source, _ = deployment_database
    monkeypatch.setenv("RULER_RUNTIME_DATABASE_URL", os.environ["RULER_DATABASE_URL"])
    result = CliRunner().invoke(main, ["database", "prepare-deployment", "--source", str(source)])
    assert result.exit_code != 0
    assert "Deployment preparation failed" in result.output
    assert "test secret" not in result.output


@pytest.fixture
def shared_deployment_database(deployment_database, monkeypatch):
    source, runtime = deployment_database
    original = database_url()
    admin = database_engine(original.render_as_string(hide_password=False))
    migrator = "ruler_migrate_" + uuid4().hex
    with admin.begin() as connection:
        with closing(connection.connection.driver_connection.cursor()) as cursor:
            cursor.execute(
                f"CREATE ROLE {identifier(migrator)} LOGIN PASSWORD 'migration_test_only'"
            )
            cursor.execute(
                f"CREATE ROLE {identifier(runtime.username)} LOGIN PASSWORD {literal(runtime.password)}"
            )
            cursor.execute(
                f"ALTER DATABASE {identifier(original.database)} OWNER TO {identifier(migrator)}"
            )
    monkeypatch.setenv(
        "RULER_DATABASE_URL",
        original.set(username=migrator, password="migration_test_only").render_as_string(
            hide_password=False
        ),
    )
    monkeypatch.setenv("RULER_EXPECTED_DATABASE", original.database)
    try:
        yield source, runtime, original
    finally:
        # Remove objects owned by the temporary migrator before dropping its role.
        with admin.begin() as connection:
            with closing(connection.connection.driver_connection.cursor()) as cursor:
                cursor.execute(
                    f"REASSIGN OWNED BY {identifier(migrator)} TO {identifier(original.username)}"
                )
                cursor.execute(f"DROP OWNED BY {identifier(migrator)}")
                cursor.execute(f"DROP ROLE {identifier(migrator)}")
        admin.dispose()


def test_shared_deployment_uses_database_owner_without_role_management(shared_deployment_database):
    source, runtime, _ = shared_deployment_database
    for _ in range(2):
        result = CliRunner().invoke(
            main,
            ["database", "prepare-deployment", "--source", str(source), "--preprovisioned-runtime"],
        )
        assert result.exit_code == 0, result.output
    store = PostgresWorkspace(url=runtime.render_as_string(hide_password=False))
    try:
        store.check_ready()
        with store.engine.connect() as connection:
            assert store.snapshot(connection)["README.md"] == b"first import"
        with pytest.raises(ProgrammingError), store.engine.begin() as connection:
            connection.execute(sa.text("CREATE TABLE public.forbidden (id integer)"))
    finally:
        store.engine.dispose()
    migrator = database_engine()
    try:
        with pytest.raises(ProgrammingError), migrator.begin() as connection:
            connection.execute(sa.text("CREATE ROLE forbidden"))
    finally:
        migrator.dispose()


def test_shared_deployment_rejects_admin_before_migration(shared_deployment_database, monkeypatch):
    source, _, original = shared_deployment_database
    monkeypatch.setenv("RULER_DATABASE_URL", original.render_as_string(hide_password=False))
    result = CliRunner().invoke(
        main,
        ["database", "prepare-deployment", "--source", str(source), "--preprovisioned-runtime"],
    )
    assert result.exit_code != 0
    engine = database_engine()
    try:
        assert sa.inspect(engine).get_table_names() == []
    finally:
        engine.dispose()


def test_database_target_guard_rejects_unrelated_database_before_connecting(monkeypatch):
    monkeypatch.setenv("RULER_EXPECTED_DATABASE", "ruler")
    with pytest.raises(ValueError, match="RULER_EXPECTED_DATABASE"):
        database_engine("postgresql+pg8000://ruler_migrator:secret@localhost/unrelated_database")
