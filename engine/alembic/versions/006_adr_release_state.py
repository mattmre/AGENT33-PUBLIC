"""ADR: Release lifecycle records stored in JSON state store, not Postgres.

This migration records an architectural schema decision. The release
automation subsystem (engine/src/agent33/release/) persists release lifecycle state
(PLANNED → FROZEN → RC → VALIDATING → RELEASED → ROLLED_BACK),
pre-release checklist items (RL-01..RL-08), and rollback decision matrix
entries via OrchestrationStateStore (Redis-backed JSON) rather than Postgres.

Rationale: Release records are created and consumed within a bounded deployment
window. Using the JSON state store avoids coupling the release pipeline to
Postgres availability and allows rollback records to expire automatically after
the retention period.

Revision ID: 006
Revises: 005
Create Date: 2026-04-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None

_TABLE = "schema_decisions"
_DECISION_ID = "release-state-store"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {_TABLE} (id, subsystem, state_store, decision, rationale) "
            "VALUES (:id, :subsystem, :state_store, :decision, :rationale)"
        ),
        {
            "id": _DECISION_ID,
            "subsystem": "release",
            "state_store": "OrchestrationStateStore",
            "decision": "Release lifecycle state is persisted in Redis-backed JSON state.",
            "rationale": (
                "Release records are bounded deployment-window data that can expire "
                "after retention without blocking rollback flows on Postgres writes."
            ),
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text(f"DELETE FROM {_TABLE} WHERE id = :id"), {"id": _DECISION_ID})
