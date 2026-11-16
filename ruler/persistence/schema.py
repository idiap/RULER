# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Relational workspace catalogue and content-addressed artifact objects."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

metadata = sa.MetaData()

workspaces = sa.Table(
    "mcp_workspaces",
    metadata,
    sa.Column("workspace_id", sa.Text, primary_key=True),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
)
objects = sa.Table(
    "mcp_objects",
    metadata,
    sa.Column("sha256", sa.String(64), primary_key=True),
    sa.Column("content", sa.LargeBinary, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="mcp_object_digest"),
)
entries = sa.Table(
    "mcp_workspace_entries",
    metadata,
    sa.Column(
        "workspace_id",
        sa.Text,
        sa.ForeignKey("mcp_workspaces.workspace_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("path", sa.Text, primary_key=True),
    sa.Column("sha256", sa.String(64), sa.ForeignKey("mcp_objects.sha256"), nullable=False),
    sa.CheckConstraint(
        "path <> '' AND path !~ '(^/|(^|/)\\.\\.(/|$))'", name="mcp_entry_relative_path"
    ),
)
workspace_objects = sa.Table(
    "mcp_workspace_objects",
    metadata,
    sa.Column(
        "workspace_id",
        sa.Text,
        sa.ForeignKey("mcp_workspaces.workspace_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("sha256", sa.String(64), sa.ForeignKey("mcp_objects.sha256"), primary_key=True),
)
plans = sa.Table(
    "mcp_import_plans",
    metadata,
    sa.Column(
        "workspace_id",
        sa.Text,
        sa.ForeignKey("mcp_workspaces.workspace_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column("session_id", sa.String(64), primary_key=True),
    sa.Column("plan_id", sa.Text, primary_key=True),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("payload", JSONB, nullable=False),
    sa.Index("ix_mcp_import_plans_expiry", "expires_at"),
)
invocations = sa.Table(
    "mcp_invocations",
    metadata,
    sa.Column("invocation_id", sa.String(32), primary_key=True),
    sa.Column(
        "workspace_id",
        sa.Text,
        sa.ForeignKey("mcp_workspaces.workspace_id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("session_id", sa.String(64), nullable=False),
    sa.Column("operation", sa.Text, nullable=False),
    sa.Column("result", JSONB, nullable=False),
    sa.Column("changed_paths", JSONB, nullable=False),
    sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    ),
    sa.Index("ix_mcp_invocations_workspace", "workspace_id", "created_at"),
)
