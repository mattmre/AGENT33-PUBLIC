"""ADR: SkillRegistry persistence stored in JSON state store, not Postgres.

This migration records an architectural schema decision. The skill registry
(engine/src/agent33/skills/registry.py) persists dynamically registered skills
(those without a file-backed base_path) via OrchestrationStateStore
(Redis-backed JSON) rather than a Postgres table.

Rationale: File-backed skills are discovered from disk on startup and do not
need persistence. API-registered skills are few in number, change infrequently,
and benefit from the fast key-value access provided by the JSON state store.
Adding a dedicated Postgres table for skill metadata would introduce a migration
dependency for what is fundamentally a configuration cache.

See also: engine/src/agent33/skills/registry.py _persist_state / _load_state.

Revision ID: 008
Revises: 007
Create Date: 2026-04-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

_TABLE = "schema_decisions"
_DECISION_ID = "skill-registry-state-store"


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            f"INSERT INTO {_TABLE} (id, subsystem, state_store, decision, rationale) "
            "VALUES (:id, :subsystem, :state_store, :decision, :rationale)"
        ),
        {
            "id": _DECISION_ID,
            "subsystem": "skill-registry",
            "state_store": "OrchestrationStateStore",
            "decision": "Dynamic skill registry state is persisted in Redis-backed JSON state.",
            "rationale": (
                "File-backed skills are discovered from disk; API-registered skills are "
                "configuration-like records suited to key-value persistence."
            ),
        },
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text(f"DELETE FROM {_TABLE} WHERE id = :id"), {"id": _DECISION_ID})
