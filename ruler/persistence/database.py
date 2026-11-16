# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Database configuration without logging connection strings or credentials."""

import os
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url


def database_url(value: str | None = None):
    raw = value or os.environ.get("RULER_DATABASE_URL")
    if not raw:
        raise ValueError("RULER_DATABASE_URL is required; MCP has no filesystem fallback")
    try:
        url = make_url(raw)
    except Exception:
        raise ValueError("RULER_DATABASE_URL must be a PostgreSQL URL") from None
    if url.drivername not in {"postgres", "postgresql", "postgresql+pg8000", "postgresql+psycopg"}:
        raise ValueError("RULER_DATABASE_URL must use PostgreSQL with pg8000")
    expected = os.environ.get("RULER_EXPECTED_DATABASE")
    if expected and url.database != expected:
        raise ValueError("database URL does not target RULER_EXPECTED_DATABASE")
    # Accept existing configuration without loading the former driver. libpq's
    # host-directory convention needs a full socket filename with pg8000.
    host = url.query.get("host", url.host)
    if isinstance(host, str) and host.startswith("/"):
        query = dict(url.query)
        query.pop("host", None)
        port = query.pop("port", url.port or 5432)
        query.setdefault("unix_sock", f"{host.rstrip('/')}/.s.PGSQL.{port}")
        url = url._replace(host=None, port=None, query=query)
    return url.set(drivername="postgresql+pg8000")


def database_engine(value: str | None = None):
    url = database_url(value)
    connect_args = {}
    if "options" in url.query:
        connect_args["startup_params"] = {"options": url.query["options"]}
        url = url.difference_update_query(["options"])
    return sa.create_engine(
        url,
        connect_args=connect_args,
        pool_pre_ping=True,
        hide_parameters=True,
        pool_size=2,
        max_overflow=0,
        pool_timeout=30,
    )


def migration_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    return config


def upgrade_database() -> None:
    command.upgrade(migration_config(), "head")
