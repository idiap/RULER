# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Explicit deployment job: migrate, initialize once, and grant bounded runtime access."""

from contextlib import closing
import os
from pathlib import Path

import sqlalchemy as sa
from pg8000.native import identifier, literal

from ruler.persistence.database import database_engine, database_url, upgrade_database
from ruler.persistence.schema import metadata, workspaces
from ruler.persistence.workspace import PostgresWorkspace


def prepare_deployment(source: Path, *, provision_runtime_role: bool = True) -> None:
    """Run with the migrator identity; never run on service startup."""
    runtime_url = database_url(os.environ.get("RULER_RUNTIME_DATABASE_URL"))
    owner_url = database_url()
    if (
        not runtime_url.database
        or not runtime_url.username
        or not runtime_url.password
        or runtime_url.username == owner_url.username
        or runtime_url.database != owner_url.database
        or runtime_url.host != owner_url.host
        or dict(runtime_url.query) != dict(owner_url.query)
    ):
        raise ValueError("runtime and migration URLs must target one database with separate users")
    engine = database_engine()
    store = PostgresWorkspace()
    try:
        # Serialize migration, first import, and grants across deployment runners.
        with engine.connect() as lock_connection:
            lock_connection.execute(sa.text("SELECT pg_advisory_lock(724852001)"))
            try:
                if not provision_runtime_role:
                    # On a shared instance, this login must own only the RULER
                    # database, with no instance-wide role-management authority.
                    elevated = lock_connection.execute(
                        sa.text(
                            "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication "
                            "OR rolbypassrls "
                            "OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid) "
                            "OR EXISTS (SELECT 1 FROM pg_database "
                            "WHERE datdba = r.oid AND datname <> current_database()) "
                            "OR NOT EXISTS (SELECT 1 FROM pg_database "
                            "WHERE datdba = r.oid AND datname = current_database()) "
                            "FROM pg_roles r WHERE rolname = current_user"
                        )
                    ).scalar_one()
                    if elevated:
                        raise ValueError("shared-instance migrator must own only its database")
                    # Verify the externally managed runtime login/password before
                    # migrating anything. The job never creates or rotates it.
                    runtime_engine = database_engine(
                        runtime_url.render_as_string(hide_password=False)
                    )
                    try:
                        with runtime_engine.connect() as connection:
                            connection.execute(sa.text("SELECT 1"))
                    finally:
                        runtime_engine.dispose()
                upgrade_database()
                with store.engine.connect() as connection:
                    exists = (
                        connection.execute(
                            sa.select(workspaces.c.workspace_id).where(
                                workspaces.c.workspace_id == store.workspace_id
                            )
                        ).first()
                        is not None
                    )
                if not exists:
                    store.import_workspace(source)
                with engine.begin() as connection:
                    # pg8000 quoting keeps passwords out of SQLAlchemy statement
                    # logging and safely handles identifier/literal characters.
                    driver = connection.connection.driver_connection
                    if driver is None:
                        raise RuntimeError("deployment database connection is unavailable")
                    with closing(driver.cursor()) as cursor:
                        cursor.execute(
                            "SELECT 1 FROM pg_roles WHERE rolname = %s", (runtime_url.username,)
                        )
                        role = identifier(runtime_url.username)
                        if cursor.fetchone() is None:
                            if not provision_runtime_role:
                                raise ValueError("runtime login must be preprovisioned")
                            cursor.execute(
                                f"CREATE ROLE {role} LOGIN PASSWORD {literal(runtime_url.password)}"
                            )
                        else:
                            # Never repurpose an existing privileged or owning role.
                            cursor.execute(
                                "SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication "
                                "OR rolbypassrls "
                                "OR EXISTS (SELECT 1 FROM pg_auth_members WHERE member = r.oid) "
                                "OR EXISTS (SELECT 1 FROM pg_class WHERE relowner = r.oid) "
                                "OR EXISTS (SELECT 1 FROM pg_database WHERE datdba = r.oid) "
                                "OR EXISTS (SELECT 1 FROM pg_namespace WHERE nspowner = r.oid) "
                                "FROM pg_roles r WHERE rolname = %s",
                                (runtime_url.username,),
                            )
                            if cursor.fetchone()[0]:
                                raise ValueError("runtime role must have no elevated privileges")
                            if provision_runtime_role:
                                cursor.execute(
                                    f"ALTER ROLE {role} LOGIN PASSWORD {literal(runtime_url.password)}"
                                )
                        cursor.execute(
                            f"GRANT CONNECT ON DATABASE {identifier(runtime_url.database)} TO {role}"
                        )
                        cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
                        cursor.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
                        cursor.execute(f"GRANT SELECT ON public.alembic_version TO {role}")
                        for table in metadata.sorted_tables:
                            cursor.execute(
                                "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE "
                                f"public.{identifier(table.name)} TO {role}"
                            )
            finally:
                lock_connection.execute(sa.text("SELECT pg_advisory_unlock(724852001)"))
    finally:
        store.engine.dispose()
        engine.dispose()
