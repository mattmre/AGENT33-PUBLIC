"""ADR: Autonomy budget records stored in JSON state store, not Postgres.

This migration records an architectural schema decision. The autonomy
enforcement subsystem (engine/src/agent33/autonomy/) persists budget lifecycle
state (DRAFT → ACTIVE → COMPLETED), preflight check results (PF-01..PF-10),
and runtime enforcer decisions (EF-01..EF-08) via OrchestrationStateStore
(Redis-backed JSON) rather than Postgres tables.

Rationale: Autonomy budget records are scoped to a single agent run and do not
require long-term relational storage. The JSON state store supports atomic
compare-and-swap updates for budget transitions without the latency of a
Postgres write for each guarded action.

Revision ID: 005
Revises: 004
Create Date: 2026-04-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

_TABLE = "schema_decisions"
_DECISION_ID = "autonomy-state-store"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {_TABLE} (id, subsystem, state_store, decision, rationale) "
            "VALUES (:id, :subsystem, :state_store, :decision, :rationale)"
        ),
        {
            "id": _DECISION_ID,
            "subsystem": "autonomy",
            "state_store": "OrchestrationStateStore",
            "decision": "Autonomy budget state is persisted in Redis-backed JSON state.",
            "rationale": (
                "Budget records are scoped to individual agent runs and require atomic "
                "transition updates without relational query requirements."
            ),
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text(f"DELETE FROM {_TABLE} WHERE id = :id"), {"id": _DECISION_ID})
