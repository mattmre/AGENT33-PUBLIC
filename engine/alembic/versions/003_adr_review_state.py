"""ADR: Review state stored in JSON state store, not Postgres.

This migration records an architectural schema decision. The review
subsystem (engine/src/agent33/review/) persists reviewer assignments,
signoff state-machine transitions, and review history via
OrchestrationStateStore (Redis-backed JSON) rather than Postgres tables.

Rationale: Review state is transient, ephemeral per-run data that benefits
from fast key-value access and automatic expiry. The overhead of relational
schema migrations for reviewer assignment churn would not improve durability
and would complicate rollback scenarios.

Revision ID: 003
Revises: 002
Create Date: 2026-04-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None

_TABLE = "schema_decisions"
_DECISION_ID = "review-state-store"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("subsystem", sa.Text(), nullable=False),
        sa.Column("state_store", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {_TABLE} (id, subsystem, state_store, decision, rationale) "
            "VALUES (:id, :subsystem, :state_store, :decision, :rationale)"
        ),
        {
            "id": _DECISION_ID,
            "subsystem": "review",
            "state_store": "OrchestrationStateStore",
            "decision": "Review state is persisted in Redis-backed JSON state, not Postgres.",
            "rationale": (
                "Reviewer assignments and signoff transitions are transient per-run state "
                "with expiry needs and key-value access patterns."
            ),
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text(f"DELETE FROM {_TABLE} WHERE id = :id"), {"id": _DECISION_ID})
    op.drop_table(_TABLE)
