"""ADR: Evaluation gate results stored in JSON state store, not Postgres.

This migration records an architectural schema decision. The evaluation
subsystem (engine/src/agent33/evaluation/) persists golden-task results,
regression indicator records, and gate enforcer decisions via
OrchestrationStateStore (Redis-backed JSON) rather than Postgres tables.

Rationale: Evaluation runs produce high-churn intermediate result objects that
are queried by run ID with a short retention window. The Redis state store
provides the necessary TTL-based cleanup and sub-millisecond access without
requiring schema changes for each new gate threshold.

Revision ID: 004
Revises: 003
Create Date: 2026-04-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None

_TABLE = "schema_decisions"
_DECISION_ID = "evaluation-state-store"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {_TABLE} (id, subsystem, state_store, decision, rationale) "
            "VALUES (:id, :subsystem, :state_store, :decision, :rationale)"
        ),
        {
            "id": _DECISION_ID,
            "subsystem": "evaluation",
            "state_store": "OrchestrationStateStore",
            "decision": "Evaluation gate state is persisted in Redis-backed JSON state.",
            "rationale": (
                "Evaluation runs produce high-churn intermediate result objects with "
                "short retention windows and run-ID lookup patterns."
            ),
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text(f"DELETE FROM {_TABLE} WHERE id = :id"), {"id": _DECISION_ID})
