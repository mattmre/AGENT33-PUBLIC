"""ADR: Continuous improvement records stored in JSON state store, not Postgres.

This migration records an architectural schema decision. The continuous
improvement subsystem (engine/src/agent33/improvement/) persists research intake lifecycle
(SUBMITTED → TRIAGED → ANALYZING → ACCEPTED/DEFERRED/REJECTED → TRACKED),
lessons learned with action tracking, and improvement checklist items
(CI-01..CI-15) via OrchestrationStateStore (Redis-backed JSON) rather than
Postgres tables.

Rationale: Improvement records are iterative and change frequently during a
review cycle. The JSON state store provides the necessary flexibility for
ad-hoc key additions without requiring schema migrations for each new
improvement dimension added to the checklist.

Revision ID: 007
Revises: 006
Create Date: 2026-04-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None

_TABLE = "schema_decisions"
_DECISION_ID = "improvement-state-store"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {_TABLE} (id, subsystem, state_store, decision, rationale) "
            "VALUES (:id, :subsystem, :state_store, :decision, :rationale)"
        ),
        {
            "id": _DECISION_ID,
            "subsystem": "improvement",
            "state_store": "OrchestrationStateStore",
            "decision": "Continuous improvement state is persisted in Redis-backed JSON state.",
            "rationale": (
                "Improvement records are iterative review-cycle data that benefit from "
                "flexible JSON keys and state-store retention."
            ),
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text(f"DELETE FROM {_TABLE} WHERE id = :id"), {"id": _DECISION_ID})
