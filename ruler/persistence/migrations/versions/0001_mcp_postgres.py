# SPDX-FileCopyrightText: Copyright © 2026 Idiap Research Institute <contact@idiap.ch>
# SPDX-FileContributor: Danilo Gusicuma <danilo.gusicuma@idiap.ch>
# SPDX-License-Identifier: LicenseRef-Idiap-Research-Education

"""Store all MCP workspace data, import plans, and observable results in PostgreSQL."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001_mcp_postgres"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_workspaces",
        sa.Column("workspace_id", sa.Text, primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "mcp_objects",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("content", sa.LargeBinary, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("sha256 ~ '^[a-f0-9]{64}$'", name="mcp_object_digest"),
    )
    op.create_table(
        "mcp_workspace_entries",
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
    op.create_table(
        "mcp_workspace_objects",
        sa.Column(
            "workspace_id",
            sa.Text,
            sa.ForeignKey("mcp_workspaces.workspace_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("sha256", sa.String(64), sa.ForeignKey("mcp_objects.sha256"), primary_key=True),
    )
    op.create_table(
        "mcp_import_plans",
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
    )
    op.create_index("ix_mcp_import_plans_expiry", "mcp_import_plans", ["expires_at"])
    op.create_table(
        "mcp_invocations",
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
    )
    op.create_index(
        "ix_mcp_invocations_workspace", "mcp_invocations", ["workspace_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("mcp_invocations")
    op.drop_table("mcp_import_plans")
    op.drop_table("mcp_workspace_objects")
    op.drop_table("mcp_workspace_entries")
    op.drop_table("mcp_objects")
    op.drop_table("mcp_workspaces")
