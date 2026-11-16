# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""PostgreSQL is authoritative; files exist only in disposable execution scratch space.

The artifact table preserves exact binary evidence and existing hash-bound manifests.
Legacy readers/solvers run in an isolated process so module-level paths and caches
cannot escape into another workspace or the checkout. A workspace row lock covers
snapshot, execution, and commit, including single-use import plan consumption.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid4
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError

from ruler.persistence.database import database_engine, migration_config
from ruler.persistence.schema import (
    entries,
    invocations,
    objects,
    plans,
    workspace_objects,
    workspaces,
)

# Only explicit repository inputs are imported. Never traverse .git, virtualenvs,
# credentials, activity logs, caches, or developer-specific configuration.
IMPORT_ROOTS = (
    "data",
    "kb",
    "rules",
    "skills",
    "proj_skills",
    ".ruler",
    ".opencode",
    ".claude",
    ".githooks",
    ".github",
    "docs",
    "scripts",
    "refs",
    "config",
    "build/ruler",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "UPSTREAM_PROVENANCE.md",
    "pyproject.toml",
    "uv.lock",
    ".gitattributes",
    ".gitignore",
)
IGNORED_PARTS = {"__pycache__", ".DS_Store", ".pytest_cache", ".ruff_cache", "activity_sessions"}


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or "\x00" in value
        or path.as_posix() != value
    ):
        raise ValueError("workspace paths must be normalized relative paths")
    return value


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _scan(root: Path, *, importing: bool = False) -> dict[str, bytes]:
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("workspace symbolic links are not supported")
        if path.is_file():
            key = safe_path(path.relative_to(root).as_posix())
            if importing and (
                ".local." in key
                or any(part.startswith(".env") for part in path.relative_to(root).parts)
            ):
                continue
            if not IGNORED_PARTS.intersection(path.relative_to(root).parts):
                result[key] = path.read_bytes()
    return result


class PostgresWorkspace:
    def __init__(self, url: str | None = None, workspace_id: str | None = None) -> None:
        self.workspace_id = workspace_id or os.environ.get("RULER_MCP_WORKSPACE", "default")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", self.workspace_id):
            raise ValueError("invalid MCP workspace identifier")
        self.engine = database_engine(url)

    def check_schema(self, connection) -> None:
        heads = MigrationContext.configure(connection).get_current_heads()
        expected = ScriptDirectory.from_config(migration_config()).get_heads()
        if set(heads) != set(expected):
            raise RuntimeError("MCP database schema is not current; run ruler database upgrade")

    def lock(self, connection) -> None:
        self.check_schema(connection)
        connection.execute(sa.text("SET LOCAL lock_timeout = '30s'"))
        row = connection.execute(
            sa.select(workspaces.c.workspace_id)
            .where(workspaces.c.workspace_id == self.workspace_id)
            .with_for_update()
        ).first()
        if row is None:
            raise RuntimeError(
                "MCP workspace is not initialized; run ruler database import-workspace"
            )

    def check_ready(self) -> None:
        try:
            with self.engine.begin() as connection:
                self.lock(connection)
        except SQLAlchemyError:
            raise RuntimeError(
                "PostgreSQL is unavailable; MCP has no filesystem fallback"
            ) from None

    def snapshot(self, connection) -> dict[str, bytes]:
        rows = connection.execute(
            sa.select(entries.c.path, objects.c.sha256, objects.c.content)
            .join(objects, entries.c.sha256 == objects.c.sha256)
            .where(entries.c.workspace_id == self.workspace_id)
        )
        result = {}
        for path, expected, payload in rows:
            content = bytes(payload)
            if digest(content) != expected:
                raise ValueError("PostgreSQL artifact failed SHA-256 verification")
            result[safe_path(path)] = content
        return result

    def put(self, connection, path: str, content: bytes) -> str:
        path = safe_path(path)
        sha256 = digest(content)
        connection.execute(
            insert(objects).values(sha256=sha256, content=content).on_conflict_do_nothing()
        )
        # Detect corruption/collisions rather than silently associating bad evidence.
        stored = connection.execute(
            sa.select(objects.c.content).where(objects.c.sha256 == sha256)
        ).scalar_one()
        if bytes(stored) != content:
            raise ValueError("PostgreSQL artifact content-address collision")
        connection.execute(
            insert(workspace_objects)
            .values(
                workspace_id=self.workspace_id,
                sha256=sha256,
            )
            .on_conflict_do_nothing()
        )
        connection.execute(
            insert(entries)
            .values(
                workspace_id=self.workspace_id,
                path=path,
                sha256=sha256,
            )
            .on_conflict_do_update(
                index_elements=[entries.c.workspace_id, entries.c.path],
                set_={"sha256": sha256},
            )
        )
        return sha256

    def import_workspace(self, source: Path) -> int:
        """Explicit, atomic, one-time migration of local data; never merge/overwrite."""
        root = source.resolve(strict=True)
        payloads = {}
        for name in IMPORT_ROOTS:
            path = root / name
            if path.is_symlink():
                raise ValueError("workspace import does not follow symbolic links")
            if path.is_dir():
                for relative, content in _scan(path, importing=True).items():
                    payloads[f"{name}/{relative}"] = content
            elif path.is_file():
                payloads[name] = path.read_bytes()
        if not payloads:
            raise ValueError("no workspace data to import")
        try:
            with self.engine.begin() as connection:
                self.check_schema(connection)
                if connection.execute(
                    sa.select(workspaces).where(
                        workspaces.c.workspace_id == self.workspace_id,
                    )
                ).first():
                    raise ValueError(
                        "workspace already exists; import never overwrites database state"
                    )
                connection.execute(workspaces.insert().values(workspace_id=self.workspace_id))
                for path, content in sorted(payloads.items()):
                    self.put(connection, path, content)
        except SQLAlchemyError:
            raise RuntimeError(
                "PostgreSQL workspace import failed; no changes were committed"
            ) from None
        return len(payloads)

    def artifact(self, sha256: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-f0-9]{64}", sha256):
            raise ValueError("invalid artifact digest")
        with self.engine.begin() as connection:
            self.lock(connection)
            # Historical objects stay available after a mutable path changes.
            content = connection.execute(
                sa.select(objects.c.content)
                .join(
                    workspace_objects,
                    workspace_objects.c.sha256 == objects.c.sha256,
                )
                .where(
                    workspace_objects.c.workspace_id == self.workspace_id,
                    objects.c.sha256 == sha256,
                )
            ).scalar()
            if content is None:
                raise LookupError("artifact unavailable in this workspace")
            payload = bytes(content)
            if digest(payload) != sha256:
                raise ValueError("PostgreSQL artifact failed SHA-256 verification")
            return {
                "sha256": "sha256:" + sha256,
                "content_base64": base64.b64encode(payload).decode(),
            }


class PostgresMCPRuntime:
    def __init__(self, store: PostgresWorkspace | None = None, *, timeout: int = 600) -> None:
        self._store = store
        self.session_id = secrets.token_hex(32)
        self.timeout = timeout

    @property
    def store(self) -> PostgresWorkspace:
        if self._store is None:
            self._store = PostgresWorkspace()
        return self._store

    def invoke(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from ruler.runtime.product_workflows import WORKFLOWS

        if operation not in {f"ruler_{name}" for name in WORKFLOWS}:
            raise ValueError("operation is not a product workflow")
        try:
            return self._invoke(operation, arguments)
        except SQLAlchemyError:
            raise RuntimeError("PostgreSQL operation failed; no changes were committed") from None

    def _invoke(self, operation: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with self.store.engine.begin() as connection:
            self.store.lock(connection)
            before = self.store.snapshot(connection)
            connection.execute(plans.delete().where(plans.c.expires_at <= sa.func.now()))
            session_filter = sa.and_(
                plans.c.workspace_id == self.store.workspace_id,
                plans.c.session_id == self.session_id,
            )
            pending = {
                row.plan_id: [row.expires_at.timestamp(), row.payload]
                for row in connection.execute(sa.select(plans).where(session_filter))
            }
            with TemporaryDirectory(prefix="ruler-mcp-") as temporary:
                root = Path(temporary).resolve()
                for path, content in before.items():
                    target = root / safe_path(path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                response = self._execute(root, operation, arguments, pending)
                after = _scan(root)
            result = response["result"]
            changed = sorted(
                path for path in before.keys() | after.keys() if before.get(path) != after.get(path)
            )
            # Fail/blocked tool results must not leave partially generated evidence.
            if result.get("status") in {"blocked", "error", "fail"}:
                changed = []
            for path in changed:
                if path in after:
                    self.store.put(connection, path, after[path])
                else:
                    connection.execute(
                        entries.delete().where(
                            entries.c.workspace_id == self.store.workspace_id,
                            entries.c.path == path,
                        )
                    )
            connection.execute(plans.delete().where(session_filter))
            for plan_id, (expiry, payload) in response["plans"].items():
                connection.execute(
                    plans.insert().values(
                        workspace_id=self.store.workspace_id,
                        session_id=self.session_id,
                        plan_id=plan_id,
                        expires_at=datetime.fromtimestamp(expiry, UTC),
                        payload=payload,
                    )
                )
            if changed:
                result["persistent_artifacts"] = [
                    {
                        "path": path,
                        "sha256": "sha256:" + digest(after[path]),
                        "uri": "ruler://artifacts/" + digest(after[path]),
                    }
                    for path in changed
                    if path in after
                ]
            connection.execute(
                invocations.insert().values(
                    invocation_id=uuid4().hex,
                    workspace_id=self.store.workspace_id,
                    session_id=self.session_id,
                    operation=operation,
                    result=result,
                    changed_paths=changed,
                )
            )
            return result

    def _execute(self, root: Path, operation: str, arguments: dict, pending: dict) -> dict:
        env = os.environ.copy()
        env["RULER_WORKSPACE_ROOT"] = str(root)
        # A configured file path must resolve inside the database-backed workspace.
        override = env.get("RULER_GENAI_CONFIG")
        if override:
            env["RULER_GENAI_CONFIG"] = str(root / safe_path(override))
        env.pop("RULER_DATABASE_URL", None)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "ruler.runtime.mcp_worker"],
                cwd=root,
                env=env,
                input=json.dumps(
                    {"operation": operation, "arguments": arguments, "plans": pending}
                ),
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("MCP operation timed out; no changes were committed") from None
        try:
            response = json.loads(completed.stdout)
        except (ValueError, TypeError):
            raise RuntimeError("MCP worker failed; no changes were committed") from None
        if completed.returncode or not response.get("ok"):
            raise RuntimeError("MCP operation failed; no changes were committed")
        return response
