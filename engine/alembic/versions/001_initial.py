"""Initial migration -- workflow_checkpoints, sessions, memory_documents.

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: str | None = None
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_checkpoints",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", sa.Text(), nullable=False),
        sa.Column("step_id", sa.Text(), nullable=False),
        sa.Column("state", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_wf_checkpoints_workflow_id", "workflow_checkpoints", ["workflow_id"])

    op.create_table(
        "sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("agent_name", sa.Text(), nullable=False),
        sa.Column("data_encrypted", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    # Enable pgvector extension and create memory_documents with vector column.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "memory_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=True, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    # Add the vector column via raw SQL (pgvector type not in SA dialect).
    op.execute("ALTER TABLE memory_documents ADD COLUMN embedding vector(1536)")
    op.execute(
        "CREATE INDEX ix_memory_documents_embedding "
        "ON memory_documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )


def downgrade() -> None:
    op.drop_table("memory_documents")
    op.drop_table("sessions")
    op.drop_table("workflow_checkpoints")
    op.execute("DROP EXTENSION IF EXISTS vector")
